"""
Readable-text extraction from HTML pages.

The previous approach (BeautifulSoup get_text() over the whole page, as
LangChain's WebBaseLoader does) kept menus, footers and cookie banners, and
glued adjacent blocks into one word ("Main pageContentsCurrent events"). This
module picks the page's main content area, removes common boilerplate, and
keeps block boundaries as line breaks. It uses generic HTML conventions only
(semantic tags, ARIA roles, common banner class names), never site-specific rules.
"""
import copy
import re
from typing import Optional

from bs4 import BeautifulSoup
from bs4.element import Tag

# Never content: code, styling, embedded media, controls and dialogs.
ALWAYS_REMOVE = ["script", "style", "noscript", "template", "svg", "canvas", "iframe", "object",
                 "form", "button", "select", "input", "textarea", "label", "dialog", "nav", "aside"]
# Page-level headers/footers are site chrome; inside an <article> they hold its title or byline.
PAGE_CHROME = ["header", "footer"]
BOILERPLATE_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "dialog", "alertdialog"}
BANNER_PATTERN = re.compile(r"cookie|consent|gdpr|newsletter|subscribe|breadcrumb|sidebar|advert|popup|modal|skip-?link", re.I)
MIN_MAIN_TEXT = 200  # below this, the "main" element was probably wrong: fall back to the whole body


def _attr_text(tag: Tag) -> str:
    classes = tag.get("class") or []
    return " ".join([tag.get("id") or ""] + (classes if isinstance(classes, list) else [classes]))


def _is_hidden(tag: Tag) -> bool:
    # Inline "display:none" is deliberately NOT treated as hidden: pages use it
    # for accessible copies of visual content (Wikipedia hides the MathML of every
    # formula that way), and removing it deleted the formulas' text.
    return tag.has_attr("hidden") or tag.get("aria-hidden") == "true"


def _prune(body: Tag, keep: Optional[Tag] = None) -> None:
    """Removes boilerplate under `body`, never touching `keep` (the main content
    element) or its ancestors, whose class names could match the patterns."""
    protected = set()
    if keep is not None:
        protected = {id(keep)} | {id(p) for p in keep.parents}
    for tag in body.find_all(ALWAYS_REMOVE):
        if id(tag) not in protected:
            tag.decompose()
    for tag in body.find_all(PAGE_CHROME):
        if not tag.decomposed and id(tag) not in protected and tag.find_parent("article") is None:
            tag.decompose()
    for tag in body.find_all(True):
        if tag.decomposed or id(tag) in protected:
            continue
        if (tag.get("role") in BOILERPLATE_ROLES or _is_hidden(tag)
                or BANNER_PATTERN.search(_attr_text(tag))):
            tag.decompose()


# Elements that start a new line. Inline elements (links, emphasis, inline
# math) must NOT: get_text("\n") broke sentences apart at every link, which
# fragmented chunks and hurt retrieval.
BLOCK_TAGS = {"p", "div", "section", "article", "main", "header", "footer", "li", "ul", "ol", "dl", "dt", "dd",
              "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tfoot", "tr", "caption",
              "pre", "blockquote", "figure", "figcaption", "address", "details", "summary", "hr"}


def _text(root: Tag) -> str:
    # Work on a copy: separators are inserted into the tree, and the body
    # fallback below would otherwise insert them a second time.
    root = copy.copy(root)
    # HTML treats newlines inside text as spaces (except in <pre>); only the
    # block boundaries added below should start new lines.
    for s in root.find_all(string=True):
        if "\n" in s and s.find_parent("pre") is None:
            s.replace_with(re.sub(r"\s+", " ", str(s)))
    for br in root.find_all("br"):
        br.replace_with("\n")
    for cell in root.find_all(["td", "th"]):
        cell.insert_before(" | ")        # keeps a table row's cells on one line
    for tag in root.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    out = []
    for line in root.get_text("").splitlines():
        line = " ".join(line.split()).strip(" |")
        if line and (not out or out[-1] != line):  # drop blanks and immediate repeats
            out.append(line)
    return "\n".join(out)


def _main_root(soup: BeautifulSoup) -> Optional[Tag]:
    main = soup.find("main") or soup.find(attrs={"role": "main"})
    if main:
        return main
    articles = soup.find_all("article")
    if articles:
        return max(articles, key=lambda a: len(a.get_text(" ", strip=True)))
    return None


def extract_readable_text(soup: BeautifulSoup) -> str:
    """Main-content text of a parsed page. Mutates `soup` (removes boilerplate)."""
    body = soup.body or soup
    root = _main_root(soup)
    _prune(body, keep=root)
    if root is not None:
        text = _text(root)
        if len(text) >= MIN_MAIN_TEXT:
            return text
    return _text(body)


def parse_html(html: bytes, declared_encoding: Optional[str] = None) -> BeautifulSoup:
    """Parses raw bytes so BeautifulSoup can honour <meta charset> when the
    HTTP header gives no encoding (decoding as UTF-8 blindly garbled pages)."""
    return BeautifulSoup(html, "html.parser", from_encoding=declared_encoding)
