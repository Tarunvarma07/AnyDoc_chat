import os
import logging
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, Field, field_validator
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

logger = logging.getLogger(__name__)

app = FastAPI(title="Universal Q&A Pipeline API")

DB_DIR = "./chroma_db"
MAX_UPLOAD_MB = 10
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
        "reranker_enabled": retriever.reranker is not None,
        "hybrid_k": retriever.k,
        "top_n": retriever.top_n,
    }

@app.post("/evaluate")
def run_evaluation_endpoint():
    """
    Runs the dense-vs-hybrid retrieval benchmark and returns the hit-rate
    results. Reuses this process's already-loaded embedding model rather
    than loading a second copy - this endpoint exists specifically so the
    (memory-constrained) Streamlit frontend never has to spawn a subprocess
    that loads its own duplicate model just to trigger this benchmark.
    """
    from src.evaluation.evaluator import run_evaluation
    return run_evaluation(embeddings=embed_store.embeddings)

class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank")
        return v

class URLIngestRequest(BaseModel):
    url: str = Field(max_length=2048)

def require_extractable_text(docs, what: str):
    """Reject inputs that loaded but contain no text, instead of reporting
    "Successfully ingested 0 chunks" (e.g. a scanned PDF with no text layer)."""
    if not any(d.page_content.strip() for d in docs):
        raise HTTPException(
            status_code=422,
            detail=f"No extractable text found in the {what}. Scanned/image-only PDFs "
                   "are not supported (OCR is not implemented).",
        )

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
    require_extractable_text(docs, "page")

    docs = metadata_extractor.process_documents(docs)
    chunks = chunker.split_documents(docs)
    embed_store.add_documents(chunks)

    return {"message": f"Successfully ingested {len(chunks)} chunks from URL."}

@app.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    # Only the (lowercased) extension of the client-supplied filename goes into
    # the temp path. Embedding the whole filename let "../" or "..\" segments
    # place the file outside the temp directory.
    filename = os.path.basename((file.filename or "").replace("\\", "/"))
    suffix = os.path.splitext(filename)[1].lower()

    # Read at most one byte past the limit, so an oversized upload is never
    # held in memory in full.
    content = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        try:
            validate_file(tmp_path, max_size_mb=MAX_UPLOAD_MB)
        except SecurityError as e:
            raise HTTPException(status_code=400, detail=str(e))

        reader = FileReader()
        try:
            docs = reader.load(tmp_path, max_size_mb=MAX_UPLOAD_MB)
        except Exception as e:
            # e.g. a corrupt or encrypted PDF. Logged in full server-side; the
            # client gets a stable message without internal paths.
            logger.error(f"Failed to extract {filename!r}: {e!r}")
            raise HTTPException(status_code=422, detail=f"Could not extract text from '{filename}'. The file may be corrupt, encrypted, or malformed.")
        if not docs:
            raise HTTPException(status_code=400, detail="Failed to read content from file.")
        require_extractable_text(docs, "file")

        # Add original filename to metadata since tempfile name is obfuscated
        for doc in docs:
            doc.metadata["source"] = filename

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
        content = doc.page_content
        page = doc.metadata.get("page")  # PyPDFLoader's 0-based page index
        sources.append({
            "id": i,
            "source": doc.metadata.get("source", "Unknown"),
            "page": page + 1 if isinstance(page, int) else None,
            "content": content[:200] + "..." if len(content) > 200 else content,
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
