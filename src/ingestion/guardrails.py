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

# Which content types each supported extension may actually contain. The
# extension picks the loader, so a file whose bytes don't match its extension
# (e.g. a PDF renamed to .txt) must be rejected rather than fed to the wrong
# loader. libmagic reports most CSVs as text/plain, so both are accepted.
EXTENSION_MIME_TYPES = {
    '.pdf': {'application/pdf'},
    '.docx': {'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},
    '.txt': {'text/plain'},
    '.csv': {'text/csv', 'text/plain'},
}

def is_internal_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        # is_global is False for private, loopback, link-local, unspecified,
        # reserved and shared (100.64.0.0/10, CGNAT) ranges - the last of
        # which is_private misses, and which hosts some cloud metadata
        # services (e.g. 100.100.100.200). Multicast counts as "global".
        return (not ip.is_global) or ip.is_multicast
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

def resolve_all_addresses(hostname: str) -> list:
    """
    Every IPv4 and IPv6 address the hostname resolves to. Checking only the
    first IPv4 address (gethostbyname) misses a host whose A record is public
    but whose AAAA record is internal - the HTTP client may connect over IPv6.
    """
    if hostname.lower() == 'localhost':
        return ['127.0.0.1']
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return []
    # Strip any IPv6 zone index ("fe80::1%eth0") before parsing.
    return list(dict.fromkeys(info[4][0].split('%')[0] for info in infos))

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
        
    # 2. Hostname resolution and IP check - every resolved address must be public.
    addresses = resolve_all_addresses(hostname)
    if not addresses:
        raise SecurityError(f"Could not resolve hostname: {hostname}")

    for ip_addr in addresses:
        if is_internal_ip(ip_addr):
            raise SecurityError(f"URL points to an internal/private IP address: {ip_addr}")

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

    # 3. The content must match the extension, since the extension selects the loader.
    _, ext = os.path.splitext(file_path.lower())
    if ext not in EXTENSION_MIME_TYPES:
        raise SecurityError(f"Unsupported file extension: '{ext}'. Allowed: {', '.join(EXTENSION_MIME_TYPES)}")
    if actual_mime_type not in EXTENSION_MIME_TYPES[ext]:
        raise SecurityError(f"File content ({actual_mime_type}) does not match its extension ('{ext}').")

    return True
