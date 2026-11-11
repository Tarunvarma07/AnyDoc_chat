"""
API-level tests through FastAPI's TestClient. src.api.main builds its
components at import time, so it is imported from inside a scratch working
directory (its ./chroma_db lands there), and every LLM-backed stage is stubbed:
these tests never call Groq, whatever key is configured.

The working directory stays changed for the whole module: Chroma resolves the
relative ./chroma_db lazily, so changing back right after import made later
writes land in the repository's own chroma_db.
"""
import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class _Answer:
    def __init__(self, content):
        self.content = content


class _StubChain:
    def invoke(self, args):
        return _Answer("Stubbed answer citing [1].")


LIMIT_VARS = ("ANYDOC_API_KEY", "RATE_LIMIT_QUERIES_PER_MIN", "RATE_LIMIT_WRITES_PER_HOUR", "RATE_LIMIT_EVALS_PER_HOUR")


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    cwd = os.getcwd()
    saved = {k: os.environ.get(k) for k in LIMIT_VARS}
    # Open API and no rate limits for the functional tests below; the auth and
    # rate-limit tests switch them on individually with monkeypatch.
    os.environ.pop("ANYDOC_API_KEY", None)
    for k in LIMIT_VARS[1:]:
        os.environ[k] = "0"
    os.chdir(tmp_path_factory.mktemp("api"))
    try:
        main = importlib.import_module("src.api.main")
        main.metadata_extractor.process_documents = lambda docs: docs
        main.query_rewriter.rewrite = lambda q: q
        main.qa_generator.chain = _StubChain()
        yield main
    finally:
        os.chdir(cwd)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(scope="module")
def client(api):
    return TestClient(api.app, raise_server_exceptions=False)


def _upload(client, filename, content):
    return client.post("/ingest/file", files={"file": (filename, content, "application/octet-stream")})


def _count(client):
    return client.get("/stats").json()["document_count"]


def test_upload_filename_cannot_escape_temp_dir(api, client, monkeypatch, tmp_path):
    # The client filename used to be embedded in the temp path, so "..\" or
    # "../" segments created the file outside the temp directory.
    temp_dir = tmp_path / "uploads"
    temp_dir.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp_dir))
    seen = []
    real_validate = api.validate_file
    monkeypatch.setattr(api, "validate_file", lambda p, **kw: (seen.append(os.path.abspath(p)), real_validate(p, **kw))[1])

    res = _upload(client, "x/../../../escaped.txt", b"Traversal probe text.")
    assert res.status_code == 200
    assert os.path.dirname(seen[-1]) == os.path.abspath(temp_dir)


def test_reingesting_a_file_does_not_duplicate_chunks(client):
    content = (SAMPLES / "release_notes.txt").read_bytes()
    assert _upload(client, "release_notes.txt", content).status_code == 200
    before = _count(client)
    assert _upload(client, "release_notes.txt", content).status_code == 200
    assert _count(client) == before


def test_text_free_files_are_rejected_not_reported_as_success(client):
    # Used to return 200 "Successfully ingested 0 chunks".
    res = _upload(client, "scan.pdf", (SAMPLES / "scanned_like.pdf").read_bytes())
    assert res.status_code == 422
    assert "OCR" in res.json()["detail"]
    assert _upload(client, "blank.txt", b"   \n\n   ").status_code == 422


def test_spoofed_and_unsupported_files_get_controlled_errors(client):
    assert _upload(client, "invoice.pdf", (SAMPLES / "invoice.pdf").read_bytes()).status_code == 400
    assert _upload(client, "handbook.txt", (SAMPLES / "acme_handbook.pdf").read_bytes()).status_code == 400
    assert _upload(client, "notes.md", b"Plain text with a markdown extension.").status_code == 400


def test_malformed_pdf_returns_controlled_error(client):
    res = _upload(client, "broken.pdf", b"%PDF-1.4\nthis is not a valid pdf body\n")
    assert res.status_code in (400, 422)
    assert "Traceback" not in res.text


def test_oversized_upload_rejected(client):
    res = _upload(client, "big.txt", b"a " * (6 * 1024 * 1024))
    assert res.status_code == 400
    assert "exceeds maximum allowed size" in res.json()["detail"]


def test_blank_or_missing_query_rejected(client):
    assert client.post("/query", json={"query": ""}).status_code == 422
    assert client.post("/query", json={"query": "   "}).status_code == 422
    assert client.post("/query", json={}).status_code == 422


def test_query_returns_cited_sources_with_page_numbers(client):
    assert _upload(client, "acme_handbook.pdf", (SAMPLES / "acme_handbook.pdf").read_bytes()).status_code == 200
    res = client.post("/query", json={"query": "What does error code ZX-4471 mean?"})
    assert res.status_code == 200
    body = res.json()
    top = body["sources"][0]
    assert top["source"] == "acme_handbook.pdf"
    assert top["page"] == 3
    assert "ZX-4471" in top["content"]
    assert body["answer"] == "Stubbed answer citing [1]."


def test_url_ingestion_rejects_internal_targets(client):
    for url in ["http://127.0.0.1:8000/stats", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd"]:
        res = client.post("/ingest/url", json={"url": url})
        assert res.status_code == 400


def test_llm_failure_returns_503_with_reason(api, client, monkeypatch):
    # Used to be HTTP 200 with an error sentence as the "answer".
    class AuthFailingChain:
        def invoke(self, args):
            raise type("AuthenticationError", (Exception,), {})("Error code: 401 - Invalid API Key")

    _upload(client, "acme_handbook.pdf", (SAMPLES / "acme_handbook.pdf").read_bytes())
    monkeypatch.setattr(api.qa_generator, "chain", AuthFailingChain())
    res = client.post("/query", json={"query": "What does error code ZX-4471 mean?"})
    assert res.status_code == 503
    assert res.json()["detail"] == "The language model is unavailable: the Groq API key was rejected."


def test_documents_can_be_listed_and_deleted(client):
    assert _upload(client, "release_notes.txt", (SAMPLES / "release_notes.txt").read_bytes()).status_code == 200
    listed = {d["source"]: d for d in client.get("/documents").json()["documents"]}
    assert listed["release_notes.txt"]["chunks"] >= 1
    assert listed["release_notes.txt"]["ingested_at"]

    before = _count(client)
    res = client.delete("/documents", params={"source": "release_notes.txt"})
    assert res.status_code == 200 and res.json()["deleted_chunks"] == listed["release_notes.txt"]["chunks"]
    assert _count(client) == before - res.json()["deleted_chunks"]
    assert "release_notes.txt" not in {d["source"] for d in client.get("/documents").json()["documents"]}
    assert client.delete("/documents", params={"source": "release_notes.txt"}).status_code == 404


def test_reuploading_an_edited_file_replaces_its_old_chunks(client):
    old = "Visitor parking is in lot C. " * 40          # several chunks
    new = "Visitor parking moved to lot F next to the gym."
    first = _upload(client, "parking.txt", old.encode()).json()
    second = _upload(client, "parking.txt", new.encode()).json()
    assert second["replaced_chunks"] == first["chunks"]
    rows = {d["source"]: d for d in client.get("/documents").json()["documents"]}
    assert rows["parking.txt"]["chunks"] == second["chunks"] == 1
    top = client.post("/query", json={"query": "Where is visitor parking?"}).json()["sources"][0]
    assert "lot F" in top["content"]


def test_request_id_is_returned_and_validated(client):
    assert len(client.get("/health").headers["X-Request-ID"]) == 12  # generated
    assert client.get("/health", headers={"X-Request-ID": "demo-123"}).headers["X-Request-ID"] == "demo-123"
    bad = client.get("/health", headers={"X-Request-ID": "x" * 100 + "<script>"}).headers["X-Request-ID"]
    assert bad != "x" * 100 + "<script>" and len(bad) == 12


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---- Authentication and rate limiting ------------------------------------------

def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("ANYDOC_API_KEY", "s3cret-test-key")
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/documents", headers={"X-API-Key": "s3cret-test-key"}).status_code == 200
    assert client.get("/health").status_code == 200          # public: platform health checks
    assert client.get("/openapi.json").status_code == 200    # public: API docs
    assert client.get("/documents").headers.get("X-Request-ID")  # rejections are still traced


def test_queries_are_rate_limited_per_client(api, client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_QUERIES_PER_MIN", "2")
    api.rate_limiter.reset()
    ask = lambda **h: client.post("/query", json={"query": "Where is visitor parking?"}, headers=h)
    assert ask().status_code == 200
    assert ask().status_code == 200
    blocked = ask()
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) >= 1

    # Without an API key configured, the forwarded-client header is ignored, so it
    # cannot be used to dodge the limit.
    assert ask(**{"X-AnyDoc-Client": "203.0.113.7"}).status_code == 429

    # With a key, the UI's forwarded visitor IP gets its own budget.
    monkeypatch.setenv("ANYDOC_API_KEY", "k")
    api.rate_limiter.reset()
    for _ in range(2):
        assert ask(**{"X-API-Key": "k", "X-AnyDoc-Client": "198.51.100.1"}).status_code == 200
    assert ask(**{"X-API-Key": "k", "X-AnyDoc-Client": "198.51.100.1"}).status_code == 429
    assert ask(**{"X-API-Key": "k", "X-AnyDoc-Client": "198.51.100.2"}).status_code == 200
    api.rate_limiter.reset()


def test_rate_limiter_window_and_memory_bound():
    from src.api.security import RateLimiter
    rl = RateLimiter(max_keys=2)
    assert rl.hit("a", 2, 60, now=0) is None
    assert rl.hit("a", 2, 60, now=1) is None
    assert rl.hit("a", 2, 60, now=2) == 59      # oldest hit (t=0) frees its slot at t=60
    assert rl.hit("a", 2, 60, now=61) is None   # window slid past it
    rl.hit("b", 2, 60, now=61)
    rl.hit("c", 2, 60, now=61)                  # third client evicts the least recently seen
    assert "a" not in rl._hits and len(rl._hits) == 2
    assert rl.hit("x", 0, 60) is None           # 0 disables the limit


def test_query_finds_labelled_table_row(api, client):
    assert _upload(client, "price_list.pdf", (SAMPLES / "price_list.pdf").read_bytes()).status_code == 200
    question = "What is the lead time for the Torque Sensor?"
    top = client.post("/query", json={"query": question}).json()["sources"][0]
    assert top["source"] == "price_list.pdf" and top["page"] == 1
    # The response carries a 200-character excerpt; check the full chunk the LLM receives.
    docs, _ = api.retriever.retrieve(question)
    assert "Product: Torque Sensor; SKU: AR-500; Unit price: 780 USD; Lead time: 12 days" in docs[0].page_content


def test_source_excerpt_starts_at_the_matching_line(api):
    chunk = "\n".join([f"Product: Part {i}; Lead time: {i} days" for i in range(1, 9)] +
                      ["Product: Torque Sensor; Unit price: 780 USD; Lead time: 12 days"])
    text = api.excerpt(chunk, "What is the lead time for the Torque Sensor?")
    assert text.startswith("...Product: Torque Sensor;")   # used to be the chunk's first 200 characters
    assert api.excerpt("Short chunk.", "anything") == "Short chunk."
