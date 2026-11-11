import io
import pytest
from src.ingestion.guardrails import SecurityError
import socket
from unittest.mock import patch, MagicMock

import requests

from src.ingestion.file_reader import FileReader
from src.ingestion.link_reader import LinkReader


def test_txt_with_non_utf8_bytes_loads(tmp_path):
    # Latin-1 text used to fail with a UnicodeDecodeError (HTTP 500).
    f = tmp_path / "menu.txt"
    f.write_bytes("Caf\xe9 menu: cr\xe8me br\xfbl\xe9e costs 6 euros.".encode("latin-1"))
    docs = FileReader().load(str(f))
    assert "crème brûlée" in docs[0].page_content


def test_csv_is_read_as_utf8_with_bom_stripped(tmp_path):
    # CSVLoader used the OS default encoding (cp1252 on Windows, UTF-8 on Linux).
    f = tmp_path / "people.csv"
    f.write_bytes("﻿name,city\nJosé,São Paulo\n".encode("utf-8"))
    docs = FileReader().load(str(f))
    assert docs[0].page_content == "name: José\ncity: São Paulo"


def _public_dns(host, *args, **kwargs):
    return [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 80))]


def test_robots_txt_redirect_to_internal_address_is_not_followed():
    # rp.read() fetched robots.txt with urllib, which follows redirects without
    # any SSRF check - a public site could bounce it to an internal address.
    redirect = MagicMock(is_redirect=True, headers={"Location": "http://127.0.0.1:8080/admin"})
    with patch("socket.getaddrinfo", side_effect=_public_dns), \
         patch("requests.Session.get", return_value=redirect), \
         patch("urllib.request.urlopen") as unvalidated_fetch, \
         patch("src.ingestion.link_reader.requests.get") as direct_get:
        allowed = LinkReader()._can_fetch("http://public.example/page")
    assert allowed is False
    unvalidated_fetch.assert_not_called()
    direct_get.assert_not_called()


def test_robots_txt_rules_are_respected():
    robots = MagicMock(status_code=200, ok=True, is_redirect=False, text="User-agent: *\nDisallow: /private/\n")
    not_redirect = MagicMock(is_redirect=False)

    def fake_get(self, url, **kwargs):  # every fetch now goes through the pinned session
        return robots if url.endswith("/robots.txt") else not_redirect

    with patch("socket.getaddrinfo", side_effect=_public_dns), \
         patch("requests.Session.get", fake_get):
        reader = LinkReader()
        assert reader._can_fetch("http://public.example/docs/page") is True
        assert reader._can_fetch("http://public.example/private/page") is False


def test_http_error_page_is_not_ingested():
    # WebBaseLoader ignores HTTP status by default, so a 404 page's text was indexed.
    not_found = requests.Response()
    not_found.status_code = 404
    not_found._content = b"<html><body>Page not found</body></html>"
    not_found.url = "http://public.example/missing"
    not_found.raw = io.BytesIO()  # real responses have a stream; closing one needs it
    reader = LinkReader()
    with patch("src.ingestion.link_reader.resolve_safe_url", side_effect=lambda u, **kw: u), \
         patch.object(reader, "_can_fetch", return_value=True), \
         patch("requests.Session.get", return_value=not_found):
        assert reader._load_single_url("http://public.example/missing") == []


# ---- IP pinning (DNS rebinding) -------------------------------------------------

import contextlib
import http.server
import threading


class _Recorder(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits.append((self.path, self.headers.get("Host")))
        body = self.server.body
        self.send_response(200)
        self.send_header("Content-Type", self.server.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def _servers_on_same_port(content_type="text/html", body=b"<html><body><p>Public page.</p></body></html>"):
    """An 'allowed' server on 127.0.0.2 and an 'internal' one on 127.0.0.1, same port."""
    allowed = http.server.HTTPServer(("127.0.0.2", 0), _Recorder)
    port = allowed.server_address[1]
    internal = http.server.HTTPServer(("127.0.0.1", port), _Recorder)
    for srv in (allowed, internal):
        srv.hits, srv.content_type, srv.body = [], content_type, body
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield allowed, internal, port
    finally:
        for srv in (allowed, internal):
            srv.shutdown()
            srv.server_close()


def _rebinding_dns(answers):
    """getaddrinfo that answers 'rebind.test' from `answers` in turn (the last one
    repeats) and resolves IP literals normally - like a hostile DNS server."""
    real = socket.getaddrinfo
    calls = {"n": 0}

    def fake(host, *args, **kwargs):
        if host == "rebind.test":
            ip = answers[min(calls["n"], len(answers) - 1)]
            calls["n"] += 1
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, args[0] if args else 0))]
        return real(host, *args, **kwargs)
    return fake, calls


def _only_127_0_0_1_is_internal(ip):
    return ip == "127.0.0.1"   # let the test's "public" stand-in, 127.0.0.2, through


def test_dns_rebinding_is_blocked_by_ip_pinning():
    from src.ingestion.guardrails import safe_session, validate_url
    with _servers_on_same_port() as (allowed, internal, port), \
         patch("src.ingestion.guardrails.is_internal_ip", side_effect=_only_127_0_0_1_is_internal):
        url = f"http://rebind.test:{port}/page"

        # The attack against check-then-connect: validation sees the allowed
        # address, the connection's own lookup gets the internal one.
        fake, calls = _rebinding_dns(["127.0.0.2", "127.0.0.1"])
        with patch("socket.getaddrinfo", side_effect=fake):
            validate_url(url)
            requests.get(url, timeout=5)
        assert internal.hits, "unpinned request should reach the internal server"
        internal.hits.clear()

        # The pinned session resolves once and connects to the address it validated.
        fake, calls = _rebinding_dns(["127.0.0.2", "127.0.0.1"])
        with patch("socket.getaddrinfo", side_effect=fake):
            resp = safe_session().get(url, timeout=5)
        assert resp.status_code == 200
        assert internal.hits == []
        assert allowed.hits == [("/page", f"rebind.test:{port}")]  # Host header keeps the real name
        assert calls["n"] == 1


def test_pinned_session_rejects_internal_addresses():
    from src.ingestion.guardrails import safe_session
    with pytest.raises(SecurityError, match="internal/private"):
        safe_session().get("http://127.0.0.1:9/", timeout=2)


def test_pinned_https_keeps_hostname_for_sni_and_certificate():
    from src.ingestion.guardrails import PinnedIPAdapter
    req = requests.Request("GET", "https://93.184.216.34/").prepare()
    req.anydoc_hostname = "example.com"
    _, pool_kwargs = PinnedIPAdapter().build_connection_pool_key_attributes(req, verify=True)
    assert pool_kwargs["server_hostname"] == "example.com"
    assert pool_kwargs["assert_hostname"] == "example.com"


def test_non_html_and_oversized_pages_are_skipped():
    for content_type, body, max_bytes in [("application/pdf", b"%PDF-1.4 ...", 5 * 1024 * 1024),
                                          ("text/html", b"<html>" + b"x" * 5000 + b"</html>", 1000)]:
        with _servers_on_same_port(content_type=content_type, body=body) as (allowed, internal, port), \
             patch("src.ingestion.guardrails.is_internal_ip", side_effect=_only_127_0_0_1_is_internal):
            fake, _ = _rebinding_dns(["127.0.0.2"])
            reader = LinkReader(max_bytes=max_bytes)
            with patch("socket.getaddrinfo", side_effect=fake), patch.object(reader, "_can_fetch", return_value=True):
                assert reader.load(f"http://rebind.test:{port}/doc") == []


# ---- PDF tables ------------------------------------------------------------------

from pathlib import Path
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_pdf_table_rows_name_their_columns():
    from src.ingestion.file_reader import extract_pdf_tables
    tables = extract_pdf_tables(str(SAMPLES / "price_list.pdf"))
    assert len(tables) == 1
    lines = tables[0].page_content.splitlines()
    assert lines[0] == "Table 1 on page 1 (columns: Product, SKU, Unit price, Lead time, Warehouse)"
    # pypdf alone gave "Torque Sensor AR-500 780 USD 12 days Pune", with the header
    # often in a different chunk.
    assert "Product: Torque Sensor; SKU: AR-500; Unit price: 780 USD; Lead time: 12 days; Warehouse: Pune" in lines
    assert len(lines) == 21
    assert tables[0].metadata["page"] == 0 and tables[0].metadata["content_type"] == "table"


def test_pdf_loader_adds_tables_to_page_text_and_skips_pdfs_without_tables():
    docs = FileReader().load(str(SAMPLES / "support_plans.pdf"))
    assert [d.metadata.get("content_type") for d in docs] == [None, "table"]
    assert "Plan: Pro; Monthly price: 199 USD; Response time: 8 hours; Seats: 25; Phone support: Yes" in docs[1].page_content
    assert all(d.metadata.get("content_type") != "table" for d in FileReader().load(str(SAMPLES / "acme_handbook.pdf")))


def test_table_extraction_failure_never_fails_the_upload():
    with patch("pdfplumber.open", side_effect=RuntimeError("corrupt table stream")):
        docs = FileReader().load(str(SAMPLES / "price_list.pdf"))
    assert len(docs) == 1 and "Torque Sensor" in docs[0].page_content  # page text still loaded
