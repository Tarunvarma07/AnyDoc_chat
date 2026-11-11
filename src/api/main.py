import os
import re
import time
import uuid
import logging
import tempfile
from contextvars import ContextVar
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import List
from dotenv import load_dotenv

load_dotenv()

# Every log line carries the id of the request that produced it, so one request
# can be followed through the logs. The id comes from the caller's X-Request-ID
# header when it is well-formed, otherwise a new one is generated.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_RequestIdFilter())
logging.getLogger("src").setLevel(logging.INFO)
access_log = logging.getLogger("src.api.access")


from src.ingestion.file_reader import FileReader
from src.ingestion.link_reader import LinkReader
from src.ingestion.guardrails import validate_file, validate_url, SecurityError
from src.ingestion.metadata_extractor import MetadataExtractor
from src.pipeline.chunk import Chunker
from src.pipeline.embed_store import EmbedStore
from src.retrieval.hybrid_search import HybridRetriever
from src.retrieval.reranker import Reranker
from src.retrieval.query_rewriter import QueryRewriter
from src.generation.qa_chain import QAGenerator, LLMUnavailableError
from src.api.security import (PUBLIC_PATHS, RateLimiter, client_identity, configured_api_key,
                              is_authorized, rate_rule)

logger = logging.getLogger(__name__)

app = FastAPI(title="Universal Q&A Pipeline API")

if not configured_api_key():
    logger.warning("ANYDOC_API_KEY is not set: the API accepts requests from anyone who can reach it.")

rate_limiter = RateLimiter()


# Registered before request_context, so it runs inside it: rejected requests
# still get a request id and an access-log line.
@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    if request.url.path not in PUBLIC_PATHS:
        if not is_authorized(request):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid API key."})
        rule = rate_rule(request)
        if rule:
            bucket, limit, window = rule
            retry_after = rate_limiter.hit(f"{client_identity(request)}|{bucket}", limit, window)
            if retry_after:
                return JSONResponse(status_code=429, headers={"Retry-After": str(retry_after)},
                                    content={"detail": f"Too many requests. Try again in {retry_after} seconds."})
    return await call_next(request)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex[:12]
    token = request_id_var.set(request_id)
    start = time.time()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        access_log.info("%s %s -> %s in %.0f ms", request.method, request.url.path,
                        response.status_code, (time.time() - start) * 1000)
        return response
    except Exception:
        logger.exception("Unhandled error")
        raise
    finally:
        request_id_var.reset(token)

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

@app.get("/health")
def health():
    """Liveness check: answers without touching the database or models."""
    return {"status": "ok"}


@app.get("/documents")
def list_documents():
    """Every ingested source (file name or page URL) with its chunk count."""
    docs = embed_store.list_sources()
    return {"documents": docs, "total_chunks": sum(d["chunks"] for d in docs)}


@app.delete("/documents")
def delete_document(source: str):
    """Removes all chunks of one source, e.g. DELETE /documents?source=handbook.pdf"""
    removed = embed_store.delete_source(source)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No indexed document named '{source}'.")
    return {"source": source, "deleted_chunks": removed}


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

def store(docs, kind: str) -> dict:
    """Shared tail of both ingest routes: metadata, chunking, and storing the
    chunks in place of any earlier version of the same source(s)."""
    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for d in docs:
        d.metadata["ingested_at"] = ingested_at
    docs = metadata_extractor.process_documents(docs)
    chunks = chunker.split_documents(docs)
    replaced = embed_store.replace_documents(chunks)
    note = f" (replaced {replaced} chunks from the previous version)" if replaced else ""
    return {"message": f"Successfully ingested {len(chunks)} chunks from {kind}{note}.",
            "chunks": len(chunks), "replaced_chunks": replaced,
            "sources": sorted({c.metadata.get("source", "") for c in chunks})}


def excerpt(content: str, query: str, width: int = 200) -> str:
    """
    The part of a chunk worth showing next to a citation: starts at the line
    sharing the most words with the question (the first line on a tie), instead
    of always the chunk's first 200 characters, which for a long table showed
    rows that had nothing to do with the answer.
    """
    query_tokens = set(retriever._tokenize(query))
    lines = content.splitlines() or [content]
    best = max(range(len(lines)), key=lambda i: (len(query_tokens & set(retriever._tokenize(lines[i]))), -i))
    start = sum(len(line) + 1 for line in lines[:best])
    text = content[start:]
    snippet = text[:width] + ("..." if len(text) > width else "")
    return ("..." + snippet) if start else snippet


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
    return store(docs, "URL")

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

        return store(docs, "file")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@app.post("/query")
def query_documents(req: QueryRequest):
    t0 = time.time()
    search_query = query_rewriter.rewrite(req.query)
    t1 = time.time()
    # Retrieval uses the rewritten (keyword-enriched) query; generation and
    # citation/guardrail checks stay anchored to the user's original question.
    retrieved_docs, pipeline_stats = retriever.retrieve(search_query)
    t2 = time.time()
    try:
        answer = qa_generator.generate_answer(req.query, retrieved_docs)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=f"The language model is unavailable: {e.reason}.")
    t3 = time.time()

    rewrite_ms = round((t1 - t0) * 1000, 2)
    retrieval_ms = round((t2 - t1) * 1000, 2)
    gen_ms = round((t3 - t2) * 1000, 2)

    sources = []
    for i, doc in enumerate(retrieved_docs, start=1):
        page = doc.metadata.get("page")  # PyPDFLoader's 0-based page index
        sources.append({
            "id": i,
            "source": doc.metadata.get("source", "Unknown"),
            "page": page + 1 if isinstance(page, int) else None,
            "content": excerpt(doc.page_content, req.query),
            "rerank_score": doc.metadata.get("rerank_score")
        })

    return {
        "answer": answer,
        "sources": sources,
        "search_query": search_query,
        "pipeline": pipeline_stats,
        "timings": {
            "rewrite_ms": rewrite_ms,
            "retrieval_ms": retrieval_ms,
            "gen_ms": gen_ms
        }
    }
