from src.ingestion.html_extract import extract_readable_text, parse_html
from src.ingestion.link_reader import LinkReader, html_to_document

PAGE = b"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Leave Policy | Acme</title><meta name="description" content="How leave works.">
<script>var tracking = 1;</script><style>.x{}</style></head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header"><nav><a href="/login">Log in</a><a href="/">Home</a></nav></header>
  <div id="cookie-consent">We use cookies. Accept all?</div>
  <main id="main">
    <article>
      <header><h1>Annual leave</h1><p class="byline">HR team</p></header>
      <p>Full-time staff receive <a href="/glossary#leave">24 days</a> of paid leave per year.
         See the <a href="/policies/carry-over">carry-over rules</a>.</p>
      <p>The accrual rate is <span class="math"><span style="display: none"><math><mi>r</mi><mo>=</mo><mn>2</mn></math></span></span> days per month.</p>
      <table><tr><th>Grade</th><th>Days</th></tr><tr><td>Junior</td><td>24</td></tr><tr><td>Senior</td><td>28</td></tr></table>
      <div aria-hidden="true">decorative duplicate text</div>
    </article>
    <aside>Related: office parking</aside>
  </main>
  <footer>Copyright 2026 Acme. Privacy policy.</footer>
</body></html>"""


def _text(page=PAGE):
    return extract_readable_text(parse_html(page))


def test_boilerplate_is_removed():
    text = _text()
    for chrome in ["Skip to content", "Log in", "We use cookies", "Copyright 2026", "Privacy policy",
                   "office parking", "tracking", "decorative duplicate"]:
        assert chrome not in text, chrome


def test_content_is_kept_with_sentences_intact():
    text = _text()
    # Inline links must not split the sentence across lines.
    assert "Full-time staff receive 24 days of paid leave per year. See the carry-over rules." in text
    # An article's own header is content (its title), unlike the page header.
    assert "Annual leave" in text and "HR team" in text
    # Accessible copies hidden with inline display:none (e.g. formula MathML) are kept.
    assert "r=2" in text.replace(" ", "")


def test_table_rows_stay_on_one_line():
    lines = _text().splitlines()
    assert "Grade | Days" in lines and "Junior | 24" in lines and "Senior | 28" in lines


def test_falls_back_to_body_when_main_is_too_small():
    page = b"""<html><body><main><p>Hi.</p></main>
    <div><p>""" + b"The real article text lives outside main on this site. " * 8 + b"""</p></div></body></html>"""
    assert "The real article text lives outside main" in _text(page)


def test_meta_charset_is_honoured_without_an_http_charset():
    # The HTTP header gave no charset; decoding these windows-1252 bytes as UTF-8
    # garbled them (the earlier "About Python�" title).
    page = '<html><head><meta charset="windows-1252"><title>Café ™</title></head><body><main><p>' \
           '<b>Crème brûlée</b> costs 6 euros. ' + 'More text. ' * 30 + '</p></main></body></html>'
    doc, _ = html_to_document(page.encode("cp1252"), "https://example.com/menu")
    assert doc.metadata["title"] == "Café ™"
    assert "Crème brûlée costs 6 euros." in doc.page_content


def test_metadata_and_links_come_from_the_content():
    doc, content = html_to_document(PAGE, "https://acme.example/hr/leave")
    assert doc.metadata == {"source": "https://acme.example/hr/leave", "title": "Leave Policy | Acme",
                            "description": "How leave works.", "language": "en"}
    links = LinkReader()._extract_same_domain_links(content, "https://acme.example/hr/leave")
    assert "https://acme.example/policies/carry-over" in links
    assert not any(l.endswith("/login") for l in links)  # menu link no longer followed
