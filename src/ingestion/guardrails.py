import ipaddress
import os
from urllib.parse import urlparse
import socket
import magic

class SecurityError(Exception):
    """Raised when a security guardrail is violated."""
    pass

# Allowlist of mime types we support
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    'text/csv'
}

def is_internal_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False

def resolve_hostname(hostname: str) -> str:
    """Resolve a hostname to an IP address, handling localhost explicitly."""
    if hostname.lower() == 'localhost':
        return '127.0.0.1'
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None

def validate_url(url: str) -> bool:
    """
    Validates a URL against SSRF attacks.
    Rejects localhost, 127.0.0.1, 169.254.169.254, private IPs, and non-HTTP schemes.
    """
    parsed = urlparse(url)
    
    # 1. Scheme check
    if parsed.scheme not in ('http', 'https'):
        raise SecurityError(f"Invalid URL scheme: '{parsed.scheme}'. Only http and https are allowed.")
        
    hostname = parsed.hostname
    if not hostname:
        raise SecurityError("Invalid URL: No hostname found.")
        
    # 2. Hostname resolution and IP check
    ip_addr = resolve_hostname(hostname)
    if not ip_addr:
        raise SecurityError(f"Could not resolve hostname: {hostname}")
        
    if is_internal_ip(ip_addr):
        raise SecurityError(f"URL points to an internal/private IP address: {ip_addr}")
        
    # Special check for cloud metadata service
    if ip_addr == '169.254.169.254':
         raise SecurityError("URL points to cloud metadata IP address.")

    return True

def resolve_safe_url(url: str, max_redirects: int = 5) -> str:
    """
    Follows redirects manually, validating each hop to prevent SSRF bypass via redirects.
    Returns the final resolved URL if all hops are safe.
    """
    import requests
    from urllib.parse import urljoin
    
    current_url = url
    session = requests.Session()
    
    for _ in range(max_redirects):
        # Validate the current hop
        validate_url(current_url)
        
        try:
            # We use stream=True so we don't download the body just to check headers
            resp = session.get(current_url, allow_redirects=False, timeout=5, stream=True)
            resp.close()
            
            if resp.is_redirect:
                next_url = resp.headers.get('Location')
                if not next_url:
                    raise SecurityError(f"Redirect missing Location header at {current_url}")
                # resolve relative redirects
                current_url = urljoin(current_url, next_url)
            else:
                return current_url
                
        except requests.RequestException as e:
            raise SecurityError(f"Network error while resolving {current_url}: {e}")
            
    raise SecurityError(f"Too many redirects ({max_redirects}) starting from {url}")

def validate_file(file_path: str, max_size_mb: int = 10) -> bool:
    """
    Validates a file based on its size and actual content type (magic bytes).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    # 1. Size check
    file_size_bytes = os.path.getsize(file_path)
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size_bytes > max_size_bytes:
         raise SecurityError(f"File size ({file_size_bytes} bytes) exceeds maximum allowed size ({max_size_mb} MB).")
         
    # 2. Magic bytes check
    mime = magic.Magic(mime=True)
    actual_mime_type = mime.from_file(file_path)
    
    if actual_mime_type not in ALLOWED_MIME_TYPES:
        raise SecurityError(f"File type not allowed: {actual_mime_type}. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}")
        
    return True
