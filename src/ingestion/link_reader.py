import logging
from typing import List
from urllib.parse import urlparse, urljoin
import urllib.robotparser
from bs4 import BeautifulSoup
import requests
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document

from src.ingestion.guardrails import resolve_safe_url, SecurityError

logger = logging.getLogger(__name__)

class LinkReader:
    def __init__(self, max_linked_pages: int = 5):
        self.max_linked_pages = max_linked_pages
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
                # set a timeout for robots.txt fetch
                import socket
                socket.setdefaulttimeout(5)
                rp.read()
            except Exception as e:
                logger.warning(f"Could not read robots.txt for {base_url}: {e}")
                # If we can't read it, we assume we can fetch
                pass
            finally:
                import socket
                socket.setdefaulttimeout(None)
            self._robot_parsers[base_url] = rp
            
        return self._robot_parsers[base_url].can_fetch("*", url)

    def _extract_same_domain_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract same-domain links from HTML content."""
        soup = BeautifulSoup(html_content, 'html.parser')
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

    def _load_single_url(self, url: str) -> List[Document]:
        """Load a single URL with guardrails and robots.txt check."""
        try:
            # Safely resolve all redirects first
            safe_final_url = resolve_safe_url(url)
        except SecurityError as e:
            logger.warning(f"Skipping URL {url} due to security error: {e}")
            return []
            
        if not self._can_fetch(safe_final_url):
            logger.warning(f"Skipping URL {safe_final_url} - blocked by robots.txt")
            return []
            
        try:
            loader = WebBaseLoader(safe_final_url)
            # Since we already resolved redirects safely, disable auto-following in WebBaseLoader
            loader.requests_kwargs = {'timeout': 10, 'allow_redirects': False} 
            docs = loader.load()
            return docs
        except Exception as e:
            logger.warning(f"Failed to load URL {safe_final_url}: {e}")
            return []

    def load(self, url: str) -> List[Document]:
        """
        Load the primary URL and up to `max_linked_pages` direct same-domain links.
        Enforces partial failure resilience: bad links are skipped, not crashed.
        """
        all_docs = []
        
        # 1. Load primary URL
        primary_docs = self._load_single_url(url)
        if not primary_docs:
            logger.error(f"Failed to load primary URL: {url}")
            return []
            
        all_docs.extend(primary_docs)
        
        # 2. Extract links from the primary document's HTML
        try:
            safe_final_url = resolve_safe_url(url)
            resp = requests.get(safe_final_url, timeout=10, allow_redirects=False)
            resp.raise_for_status()
            direct_links = self._extract_same_domain_links(resp.text, safe_final_url)
        except Exception as e:
            logger.warning(f"Failed to fetch HTML for link extraction from {url}: {e}")
            direct_links = []
            
        # 3. Load up to max_linked_pages
        links_to_process = direct_links[:self.max_linked_pages]
        for link in links_to_process:
            logger.info(f"Loading linked page: {link}")
            linked_docs = self._load_single_url(link)
            all_docs.extend(linked_docs)
            
        return all_docs
