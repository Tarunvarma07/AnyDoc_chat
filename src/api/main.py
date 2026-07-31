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
from src.retrieval.reranker import Reranker
from src.retrieval.query_rewriter import QueryRewriter
from src.generation.qa_chain import QAGenerator

app = FastAPI(title="Universal Q&A Pipeline API")

DB_DIR = "./chroma_db"
os.makedirs(DB_DIR, exist_ok=True)

# Fail fast on startup if components cannot be initialized (e.g., missing API keys).
# The reranker model is loaded lazily on first query, so instantiating it here
# doesn't slow down startup or require network access at boot.
embed_store = EmbedStore(persist_directory=DB_DIR)
reranker = Reranker()
retriever = HybridRetriever(embed_store=embed_store, reranker=reranker)
query_rewriter = QueryRewriter()
qa_generator = QAGenerator()
metadata_extractor = MetadataExtractor()
chunker = Chunker(strategy="recursive")

@app.get("/stats")
def get_stats():
    """Live corpus/pipeline stats for the dashboard's Overview tab."""
    return {
        "document_count": embed_store.vector_store._collection.count(),
        "embedding_model": embed_store.model_name,
        "reranker_model": reranker.model_name,
        "reranker_enabled": True,
        "hybrid_k": retriever.k,
        "top_n": retriever.top_n,
    }

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
    search_query = query_rewriter.rewrite(req.query)
    t1 = time.time()
    # Retrieval uses the rewritten (keyword-enriched) query; generation and
    # citation/guardrail checks stay anchored to the user's original question.
    retrieved_docs = retriever.get_relevant_documents(search_query)
    t2 = time.time()
    answer = qa_generator.generate_answer(req.query, retrieved_docs)
    t3 = time.time()

    rewrite_ms = round((t1 - t0) * 1000, 2)
    retrieval_ms = round((t2 - t1) * 1000, 2)
    gen_ms = round((t3 - t2) * 1000, 2)

    sources = []
    for i, doc in enumerate(retrieved_docs, start=1):
        sources.append({
            "id": i,
            "source": doc.metadata.get("source", "Unknown"),
            "content": doc.page_content[:200] + "...",
            "rerank_score": doc.metadata.get("rerank_score")
        })

    return {
        "answer": answer,
        "sources": sources,
        "search_query": search_query,
        "pipeline": retriever.last_run_stats,
        "timings": {
            "rewrite_ms": rewrite_ms,
            "retrieval_ms": retrieval_ms,
            "gen_ms": gen_ms
        }
    }
