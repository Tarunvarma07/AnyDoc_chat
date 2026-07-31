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
