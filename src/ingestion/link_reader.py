import logging
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urljoin
import urllib.robotparser
from bs4 import BeautifulSoup
import requests
from langchain_core.documents import Document

from src.ingestion.guardrails import resolve_safe_url, safe_session, SecurityError
from src.ingestion.html_extract import extract_readable_text, parse_html

logger = logging.getLogger(__name__)

HTML_TYPES = ("text/html", "application/xhtml+xml")


def html_to_document(html, url: str, encoding: Optional[str] = None) -> Tuple[Document, BeautifulSoup]:
    """
    Turns an HTML page (bytes, or str) into a Document holding its main
    readable text plus title, description and language metadata (the fields
    WebBaseLoader produced). Also returns the parsed page with boilerplate
    removed, so links can be taken from the content rather than the menus.
    """
    soup = parse_html(html, encoding) if isinstance(html, bytes) else BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    description = soup.find("meta", attrs={"name": "description"})
    html_tag = soup.find("html")
    metadata = {
        "source": url,
        "title": title.get_text(strip=True) if title else "No title found.",
        "description": description.get("content", "No description found.") if description else "No description found.",
        "language": html_tag.get("lang", "No language found.") if html_tag else "No language found.",
    }
    return Document(page_content=extract_readable_text(soup), metadata=metadata), soup


class LinkReader:
    def __init__(self, max_linked_pages: int = 5, session: Optional[requests.Session] = None,
                 timeout: int = 10, max_bytes: int = 5 * 1024 * 1024):
        self.max_linked_pages = max_linked_pages
        # Every request - redirect checks, robots.txt and the pages themselves -
        # goes through one IP-pinning session (see guardrails.PinnedIPAdapter).
        self.session = session or safe_session()
        self.timeout = timeout
        self.max_bytes = max_bytes
        # Cache robot parsers per domain
        self._robot_parsers = {}

    def _can_fetch(self, url: str) -> bool:
        """Check robots.txt if we are allowed to fetch this URL."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        if base_url not in self._robot_parsers:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{base_url}/robots.txt")
            try:
                # Fetched through resolve_safe_url rather than rp.read(): urllib
                # follows redirects on its own, so a public site could redirect
                # robots.txt to an internal address without any hop being checked.
                # Status handling mirrors RobotFileParser.read().
                robots_url = resolve_safe_url(f"{base_url}/robots.txt", session=self.session)
                resp = self.session.get(robots_url, timeout=5, allow_redirects=False)
                if resp.status_code in (401, 403):
                    rp.disallow_all = True
                elif 400 <= resp.status_code < 500:
                    rp.allow_all = True
                elif resp.ok:
                    rp.parse(resp.text.splitlines())
            except Exception as e:
                # The parser is left unread, so can_fetch() returns False and
                # the page is skipped (fail closed).
                logger.warning(f"Could not read robots.txt for {base_url}: {e}")
            self._robot_parsers[base_url] = rp

        return self._robot_parsers[base_url].can_fetch("*", url)

    def _extract_same_domain_links(self, html_content, base_url: str) -> List[str]:
        """Extract same-domain links from HTML content (a string or a parsed page)."""
        soup = html_content if isinstance(html_content, BeautifulSoup) else BeautifulSoup(html_content, 'html.parser')
        links = []
        parsed_base = urlparse(base_url)

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            parsed_url = urlparse(full_url)

            # Check if same domain and http/https
            if parsed_url.netloc == parsed_base.netloc and parsed_url.scheme in ('http', 'https'):
                # Clean up fragments
                clean_url = full_url.split('#')[0]
                if clean_url != base_url and clean_url not in links:
                    links.append(clean_url)

        return links

    def _fetch_html(self, url: str) -> Tuple[Optional[str], Optional[bytes], Optional[str]]:
        """
        Fetches one page safely and returns (final_url, html_bytes, declared_charset),
        or (None, None, None) when it must be skipped: a security rejection, robots.txt, an HTTP
        error, a non-HTML response, or a body larger than max_bytes.
        """
        try:
            final_url = resolve_safe_url(url, session=self.session)
        except SecurityError as e:
            logger.warning(f"Skipping URL {url} due to security error: {e}")
            return None, None, None

        if not self._can_fetch(final_url):
            logger.warning(f"Skipping URL {final_url} - blocked by robots.txt")
            return None, None, None

        try:
            # Redirects were already resolved (and validated) above.
            with self.session.get(final_url, timeout=self.timeout, allow_redirects=False, stream=True) as resp:
                # Without this, a 404/500 error page would be ingested as content.
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if content_type and content_type not in HTML_TYPES:
                    logger.warning(f"Skipping URL {final_url} - not an HTML page ({content_type})")
                    return None, None, None
                body = b""
                for block in resp.iter_content(64 * 1024):
                    body += block
                    if len(body) > self.max_bytes:
                        logger.warning(f"Skipping URL {final_url} - larger than {self.max_bytes} bytes")
                        return None, None, None
                declared = resp.encoding if "charset" in resp.headers.get("Content-Type", "").lower() else None
                # Bytes, not text: without a declared charset BeautifulSoup reads
                # the page's own <meta charset> instead of guessing.
                return final_url, body, declared
        except (requests.RequestException, SecurityError) as e:
            logger.warning(f"Failed to load URL {final_url}: {e}")
            return None, None, None

    def _load_single_url(self, url: str) -> List[Document]:
        """Load a single URL with guardrails and robots.txt check."""
        final_url, html, encoding = self._fetch_html(url)
        if html is None:
            return []
        return [html_to_document(html, final_url, encoding)[0]]

    def load(self, url: str) -> List[Document]:
        """
        Load the primary URL and up to `max_linked_pages` direct same-domain links.
        Enforces partial failure resilience: bad links are skipped, not crashed.
        """
        # 1. Load the primary URL; its HTML is reused for link extraction
        #    (it used to be downloaded a second time just for that).
        final_url, html, encoding = self._fetch_html(url)
        if html is None:
            logger.error(f"Failed to load primary URL: {url}")
            return []
        doc, content = html_to_document(html, final_url, encoding)
        all_docs = [doc]

        # 2. Same-domain links from the page's content (menus, headers and
        #    footers are already removed, so "Log in" or "Privacy" links are not followed)
        direct_links = self._extract_same_domain_links(content, final_url)

        # 3. Load up to max_linked_pages
        for link in direct_links[:self.max_linked_pages]:
            logger.info(f"Loading linked page: {link}")
            all_docs.extend(self._load_single_url(link))

        return all_docs
