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


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    cwd = os.getcwd()
    os.chdir(tmp_path_factory.mktemp("api"))
    try:
        main = importlib.import_module("src.api.main")
        main.metadata_extractor.process_documents = lambda docs: docs
        main.query_rewriter.rewrite = lambda q: q
        main.qa_generator.chain = _StubChain()
        yield main
    finally:
        os.chdir(cwd)


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
