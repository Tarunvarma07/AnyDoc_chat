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
    robots = MagicMock(status_code=200, ok=True, text="User-agent: *\nDisallow: /private/\n")
    not_redirect = MagicMock(is_redirect=False)
    with patch("socket.getaddrinfo", side_effect=_public_dns), \
         patch("requests.Session.get", return_value=not_redirect), \
         patch("src.ingestion.link_reader.requests.get", return_value=robots):
        reader = LinkReader()
        assert reader._can_fetch("http://public.example/docs/page") is True
        assert reader._can_fetch("http://public.example/private/page") is False


def test_http_error_page_is_not_ingested():
    # WebBaseLoader ignores HTTP status by default, so a 404 page's text was indexed.
    not_found = requests.Response()
    not_found.status_code = 404
    not_found._content = b"<html><body>Page not found</body></html>"
    not_found.url = "http://public.example/missing"
    reader = LinkReader()
    with patch("src.ingestion.link_reader.resolve_safe_url", side_effect=lambda u: u), \
         patch.object(reader, "_can_fetch", return_value=True), \
         patch("requests.Session.get", return_value=not_found):
        assert reader._load_single_url("http://public.example/missing") == []
