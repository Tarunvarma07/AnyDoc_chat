import pytest
import os
from src.ingestion.guardrails import validate_url, validate_file, SecurityError

def test_validate_url_ssrf():
    # These should fail
    bad_urls = [
        "http://localhost",
        "http://127.0.0.1",
        "http://169.254.169.254", # Cloud metadata
        "http://192.168.1.1", # Private IP
        "http://10.0.0.1", # Private IP
        "file:///etc/passwd", # Non-HTTP scheme
        "ftp://example.com/file" # Non-HTTP scheme
    ]
    
    for url in bad_urls:
        with pytest.raises(SecurityError):
            validate_url(url)
            
    # These should pass
    good_urls = [
        "http://example.com",
        "https://google.com"
    ]
    
    for url in good_urls:
        assert validate_url(url) == True

def test_validate_file_magic_bytes(tmp_path):
    # Create an executable binary with a fake .pdf extension
    really_bad_file = tmp_path / "fake.pdf"
    really_bad_file.write_bytes(b"\x7fELF\x02\x01\x01\x00") # Fake ELF binary
    
    with pytest.raises(SecurityError, match="File type not allowed"):
        validate_file(str(really_bad_file))
        
    # Create a valid text file
    valid_file = tmp_path / "real.txt"
    valid_file.write_text("This is a real text file.")
    
    assert validate_file(str(valid_file)) == True

def test_validate_file_size(tmp_path):
    # Create a dummy file
    dummy_file = tmp_path / "large.txt"
    # Write 2MB of data
    dummy_file.write_bytes(b"0" * (2 * 1024 * 1024))
    
    # Should pass with max_size_mb = 3
    assert validate_file(str(dummy_file), max_size_mb=3) == True
    
    # Should fail with max_size_mb = 1
    with pytest.raises(SecurityError, match="exceeds maximum allowed size"):
        validate_file(str(dummy_file), max_size_mb=1)


def test_validate_url_blocks_shared_address_space():
    # 100.64.0.0/10 (CGNAT) is not "private" in Python's ipaddress, so the
    # original is_private/loopback/link_local check let it through. It hosts
    # some cloud metadata services (e.g. Alibaba Cloud's 100.100.100.200).
    for url in ["http://100.100.100.200/latest/meta-data/", "http://100.64.0.10/", "http://0.0.0.0/"]:
        with pytest.raises(SecurityError):
            validate_url(url)


def test_validate_url_checks_every_resolved_address():
    # A public A record must not hide a loopback AAAA record: the HTTP client
    # may connect over IPv6, which gethostbyname() never looked at.
    import socket
    from unittest.mock import patch
    infos = [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 80)),
             (socket.AF_INET6, 1, 6, "", ("::1", 80, 0, 0))]
    with patch("socket.getaddrinfo", return_value=infos):
        with pytest.raises(SecurityError, match="internal/private"):
            validate_url("http://dual-stack.example/")


def test_resolve_safe_url_blocks_redirect_to_metadata_ip():
    import socket
    from unittest.mock import patch, MagicMock
    from src.ingestion.guardrails import resolve_safe_url

    def fake_getaddrinfo(host, *args, **kwargs):
        ip = "93.184.216.34" if host == "public.example" else host
        return [(socket.AF_INET, 1, 6, "", (ip, 80))]

    redirect = MagicMock(is_redirect=True, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
    with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo), \
         patch("requests.Session.get", return_value=redirect):
        with pytest.raises(SecurityError, match="internal/private"):
            resolve_safe_url("http://public.example/")


def test_validate_file_rejects_content_extension_mismatch(tmp_path):
    # A real PDF renamed .txt passed the MIME allowlist and was then decoded by
    # TextLoader as raw PDF syntax and indexed as garbage.
    pdf_as_txt = tmp_path / "report.txt"
    pdf_as_txt.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n")
    with pytest.raises(SecurityError, match="does not match its extension"):
        validate_file(str(pdf_as_txt))

    # Allowed content type, but no loader for the extension: was a 500, now a SecurityError (400).
    markdown = tmp_path / "notes.md"
    markdown.write_text("Plain text in a markdown file.")
    with pytest.raises(SecurityError, match="Unsupported file extension"):
        validate_file(str(markdown))


def test_validate_file_accepts_csv(tmp_path):
    # libmagic usually reports CSV as text/plain; it must still be accepted for .csv.
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("a,b\n1,2\n")
    assert validate_file(str(csv_file)) == True
