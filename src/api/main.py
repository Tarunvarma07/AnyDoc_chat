import os
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv

load_dotenv()


from src.ingestion.file_reader import FileReader
from src.ingestion.link_reader import LinkReader
from src.ingestion.guardrails import validate_file, validate_url, SecurityError
from src.ingestion.metadata_extractor import MetadataExtractor
from src.pipeline.chunk import Chunker
from src.pipeline.embed_store import EmbedStore
from src.retrieval.hybrid_search import HybridRetriever
from src.generation.qa_chain import QAGenerator

app = FastAPI(title="Universal Q&A Pipeline API")

DB_DIR = "./chroma_db"
os.makedirs(DB_DIR, exist_ok=True)

# Fail fast on startup if components cannot be initialized (e.g., missing API keys)
embed_store = EmbedStore(persist_directory=DB_DIR)
retriever = HybridRetriever(embed_store=embed_store)
qa_generator = QAGenerator()
metadata_extractor = MetadataExtractor()
chunker = Chunker(strategy="recursive")

class QueryRequest(BaseModel):
    query: str

class URLIngestRequest(BaseModel):
    url: str

@app.post("/ingest/url")
def ingest_url(req: URLIngestRequest):
    try:
        validate_url(req.url)
    except SecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    reader = LinkReader()
    docs = reader.load(req.url)
    if not docs:
        raise HTTPException(status_code=400, detail="Failed to read content from URL.")
        
    docs = metadata_extractor.process_documents(docs)
    chunks = chunker.split_documents(docs)
    embed_store.add_documents(chunks)
    
    return {"message": f"Successfully ingested {len(chunks)} chunks from URL."}

@app.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    # Save uploaded file to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        try:
            validate_file(tmp_path)
        except SecurityError as e:
            raise HTTPException(status_code=400, detail=str(e))
            
        reader = FileReader()
        docs = reader.load(tmp_path)
        if not docs:
            raise HTTPException(status_code=400, detail="Failed to read content from file.")
            
        # Add original filename to metadata since tempfile name is obfuscated
        for doc in docs:
            doc.metadata["source"] = file.filename
            
        docs = metadata_extractor.process_documents(docs)
        chunks = chunker.split_documents(docs)
        embed_store.add_documents(chunks)
        
        return {"message": f"Successfully ingested {len(chunks)} chunks from file."}
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@app.post("/query")
def query_documents(req: QueryRequest):
    import time
    
    t0 = time.time()
    retrieved_docs = retriever.get_relevant_documents(req.query)
    t1 = time.time()
    answer = qa_generator.generate_answer(req.query, retrieved_docs)
    t2 = time.time()
    
    retrieval_ms = round((t1 - t0) * 1000, 2)
    gen_ms = round((t2 - t1) * 1000, 2)
    
    sources = []
    for i, doc in enumerate(retrieved_docs, start=1):
        sources.append({
            "id": i,
            "source": doc.metadata.get("source", "Unknown"),
            "content": doc.page_content[:200] + "..."
        })
        
    return {
        "answer": answer,
        "sources": sources,
        "timings": {
            "retrieval_ms": retrieval_ms,
            "gen_ms": gen_ms
        }
    }
