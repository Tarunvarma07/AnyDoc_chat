"""
API-key authentication and per-client rate limiting for the FastAPI app.

Configuration (environment variables):
    ANYDOC_API_KEY               if set, every route except PUBLIC_PATHS needs the
                                 header "X-API-Key: <value>". Unset = open API
                                 (local development), with a warning at startup.
    RATE_LIMIT_QUERIES_PER_MIN   default 20   POST /query
    RATE_LIMIT_WRITES_PER_HOUR   default 30   POST /ingest/*, DELETE /documents
    RATE_LIMIT_EVALS_PER_HOUR    default 3    POST /evaluate
                                 (0 disables that limit)
    TRUST_PROXY                  "1" when a reverse proxy sets X-Forwarded-For
                                 (e.g. Render); otherwise the socket address is used.
"""
import hmac
import os
import threading
import time
from collections import OrderedDict, deque
from typing import Optional, Tuple

from fastapi import Request

API_KEY_HEADER = "X-API-Key"
# Set by the Streamlit UI: the end user's IP, so limits apply per visitor rather
# than to the UI server as a whole. Trusted only on requests with a valid API key.
CLIENT_HEADER = "X-AnyDoc-Client"
PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def configured_api_key() -> str:
    return os.environ.get("ANYDOC_API_KEY", "").strip()


def is_authorized(request: Request) -> bool:
    expected = configured_api_key()
    if not expected:
        return True
    supplied = request.headers.get(API_KEY_HEADER, "")
    # Constant-time comparison: a plain == leaks how many leading characters matched.
    return hmac.compare_digest(supplied.encode(), expected.encode())


def client_identity(request: Request) -> str:
    forwarded_user = request.headers.get(CLIENT_HEADER, "").strip()
    if configured_api_key() and forwarded_user and is_authorized(request):
        return "user:" + forwarded_user[:100]
    if os.environ.get("TRUST_PROXY") == "1":
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return "ip:" + xff.split(",")[0].strip()[:100]
    return "ip:" + (request.client.host if request.client else "unknown")


def _limit(env: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(env, default)))
    except ValueError:
        return default


def rate_rule(request: Request) -> Optional[Tuple[str, int, int]]:
    """(bucket, max requests, window seconds) for a request, or None if unlimited."""
    method, path = request.method, request.url.path
    if method == "POST" and path == "/query":
        return "query", _limit("RATE_LIMIT_QUERIES_PER_MIN", 20), 60
    if (method == "POST" and path.startswith("/ingest/")) or (method == "DELETE" and path == "/documents"):
        return "write", _limit("RATE_LIMIT_WRITES_PER_HOUR", 30), 3600
    if method == "POST" and path == "/evaluate":
        return "evaluate", _limit("RATE_LIMIT_EVALS_PER_HOUR", 3), 3600
    return None


class RateLimiter:
    """
    Sliding-window limiter kept in process memory: for each (client, bucket)
    it remembers the timestamps of recent requests. Good for a single-instance
    deployment; several instances would each count separately (a shared store
    such as Redis would be needed then).
    """

    def __init__(self, max_keys: int = 10_000):
        self.max_keys = max_keys
        self._hits: "OrderedDict[str, deque]" = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int, now: Optional[float] = None) -> Optional[int]:
        """Records a request. Returns None if allowed, else seconds until a slot frees up."""
        if limit <= 0:
            return None
        now = time.time() if now is None else now
        with self._lock:
            hits = self._hits.pop(key, None) or deque()
            while hits and hits[0] <= now - window:
                hits.popleft()
            retry_after = None
            if len(hits) >= limit:
                retry_after = max(1, int(hits[0] + window - now) + 1)
            else:
                hits.append(now)
            self._hits[key] = hits  # most recently used last
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)  # forget the least recently seen client
            return retry_after

    def reset(self):
        with self._lock:
            self._hits.clear()
