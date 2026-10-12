"""
Builds docs/AnyDoc_Complete_Visual_Architecture_Guide.pdf from the Markdown source
docs/AnyDoc_Complete_Visual_Architecture_Guide.md.

Markdown -> HTML (python-markdown + Pygments) -> PDF (headless Chrome over the
DevTools protocol, for page-number footers) -> second pass fills the table of
contents with real page numbers -> PyMuPDF adds PDF bookmarks.

Requires: markdown, pygments, websocket-client, pymupdf, pillow, requests, Google Chrome.
    python docs/guide_src/build_guide.py
"""
import base64, html, json, os, re, shutil, socket, subprocess, sys, tempfile, time

import fitz  # PyMuPDF
import markdown
import requests
import websocket
from PIL import Image
from pygments.formatters import HtmlFormatter

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.dirname(HERE)
ASSETS = os.path.join(DOCS, "guide_assets")
MD = os.path.join(DOCS, "AnyDoc_Complete_Visual_Architecture_Guide.md")
PDF = os.path.join(DOCS, "AnyDoc_Complete_Visual_Architecture_Guide.pdf")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# Screenshot crops (from the 1440 px-wide captures): drop the sidebar where it adds nothing.
CROPS = {
    "ui_overview": (0, 70, 1440, 890),
    "ui_ingestion_rejected": (360, 255, 1360, 715),
    "ui_chat": (360, 255, 1360, 1395),
    "ui_chunking_lab": (360, 255, 1360, 1085),
    "ui_evaluation": (360, 255, 1360, 1015),
}

CSS = r"""
:root { --ink:#1A202C; --muted:#4A5568; --blue:#2B6CB0; --navy:#1A365D; --line:#E2E8F0; }
html { font-size: 10.2pt; }
body { font-family: "Segoe UI", Helvetica, Arial, sans-serif; color: var(--ink); line-height: 1.5; margin: 0; }
p { margin: 0 0 7pt 0; orphans: 3; widows: 3; }
h1 { break-before: page; font-size: 21pt; color: var(--navy); margin: 0 0 12pt 0; padding-bottom: 6pt;
     border-bottom: 3px solid var(--blue); line-height: 1.2; }
.chap-label { break-before: page; font-size: 8.5pt; letter-spacing: 2.5pt; color: var(--blue); font-weight: 700; margin-bottom: 2pt; }
.chap-label + h1 { break-before: avoid; }
h2 { font-size: 13.5pt; color: var(--navy); margin: 14pt 0 6pt; break-after: avoid; }
h3 { font-size: 11.5pt; color: #2D3748; margin: 12pt 0 5pt; break-after: avoid; }
a { color: var(--blue); text-decoration: none; }
ul, ol { margin: 0 0 7pt 0; padding-left: 16pt; }
li { margin-bottom: 2.5pt; }
code { font-family: Consolas, "Courier New", monospace; font-size: 8.8pt; background: #EDF2F7; padding: 0.5pt 3pt; border-radius: 3px; }
.codehilite { background: #F7FAFC; border: 1px solid var(--line); border-left: 3px solid #3949AB; border-radius: 4px;
              padding: 6pt 9pt; margin: 6pt 0 9pt; break-inside: avoid; }
.codehilite pre { margin: 0; font-family: Consolas, "Courier New", monospace; font-size: 8.3pt; line-height: 1.38; white-space: pre-wrap; }
.codehilite code { background: none; padding: 0; font-size: inherit; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.6pt; line-height: 1.35; }
th { background: #EDF2F7; color: var(--navy); text-align: left; font-weight: 700; }
th, td { border: 1px solid #CBD5E0; padding: 3.5pt 5pt; vertical-align: top; }
tr { break-inside: avoid; }
tbody tr:nth-child(even) td { background: #FAFBFC; }
.stage-table table, .glossary table, .decisions table { font-size: 7.7pt; }
img { display: block; margin: 8pt auto 2pt; max-width: 100%; max-height: 228mm; }
p:has(> img) { break-inside: avoid; break-after: avoid; margin: 0; }
img[src$=".png"] { border: 1px solid #CBD5E0; border-radius: 4px; }
.caption { text-align: center; font-size: 8.6pt; color: var(--muted); margin: 3pt 0 10pt; break-before: avoid; }
.tag { display: inline-block; font-size: 6.8pt; font-weight: 700; letter-spacing: 0.6pt; padding: 0.5pt 5pt; border-radius: 8px;
       border: 1px solid; vertical-align: 1pt; font-style: normal; }
.t-real { color: #22543D; background: #E6F4E7; border-color: #2F7D3A; }
.t-ill  { color: #7A5C00; background: #FFFBEA; border-color: #A68A00; }
.t-prop { color: #553C9A; background: #F1E9FB; border-color: #7B3FB5; }
.callout { border-radius: 6px; padding: 7pt 10pt; margin: 8pt 0 10pt; border: 1px solid; break-inside: avoid; }
.callout p:last-child { margin-bottom: 0; }
.callout.warn { background: #FDECEC; border-color: #E8A0A0; }
.callout.ill { background: #FFFBEA; border-color: #E6D27A; }
.legend-box table { font-size: 8.8pt; }
.chunks { display: grid; grid-template-columns: 1fr; gap: 6pt; margin: 6pt 0 8pt; break-inside: avoid; }
.chunk { border: 1.5px solid; border-radius: 6px; padding: 6pt 9pt; font-size: 9.4pt; }
.chunk-h { font-size: 7.6pt; font-weight: 700; letter-spacing: 1pt; text-transform: uppercase; margin-bottom: 2pt; }
.c1 { border-color: #1F7A70; background: #E3F4F1; } .c2 { border-color: #1F7A70; background: #E3F4F1; }
.c3 { border-color: #B83232; background: #FDECEC; border-style: dashed; }
mark { background: #FFE58A; padding: 0 1.5pt; border-radius: 2px; }
.qa p { font-size: 8.7pt; line-height: 1.42; margin-bottom: 5pt; break-inside: avoid; }
.checklist ul { columns: 2; column-gap: 18pt; list-style: none; padding-left: 0; }
.checklist li { break-inside: avoid; font-size: 9.3pt; }
.qa h3 { margin-top: 10pt; color: var(--blue); }
/* cover */
.cover { height: 250mm; background: linear-gradient(160deg, #102A43 0%, #1A365D 55%, #234E7A 100%); color: #FFFFFF;
         border-radius: 10px; padding: 26mm 18mm; box-sizing: border-box; break-after: page; position: relative; }
.cover-top { font-size: 8.5pt; letter-spacing: 3pt; color: #90CDF4; font-weight: 700; }
.cover-title { font-size: 54pt; font-weight: 800; margin-top: 30mm; line-height: 1; }
.cover-sub { font-size: 19pt; color: #E2E8F0; margin-top: 6mm; font-weight: 600; }
.cover-desc { font-size: 11pt; color: #CBD5E0; margin-top: 10mm; max-width: 150mm; line-height: 1.55; }
.cover-chips { margin-top: 14mm; }
.chip { display: inline-block; font-size: 8.6pt; font-weight: 600; padding: 3pt 9pt; border-radius: 12px; margin: 0 5pt 6pt 0; color: #1A202C; }
.c-user { background: #BEE3F8; } .c-search { background: #C3DAFE; } .c-ai { background: #E9D8FD; }
.c-store { background: #C6F6D5; } .c-sec { background: #FEEBC8; } .c-infra { background: #E2E8F0; }
.cover-foot { position: absolute; bottom: 20mm; left: 18mm; right: 18mm; font-size: 8.5pt; color: #A0AEC0; line-height: 1.5; }
/* toc */
.toc-page { break-after: page; }
.toc-title { font-size: 20pt; color: var(--navy); border-bottom: 3px solid var(--blue); padding-bottom: 5pt; margin-bottom: 10pt; }
.toc { list-style: none; padding: 0; margin: 0; }
.toc li { display: flex; align-items: baseline; font-size: 10pt; margin: 0 0 4.2pt 0; }
.toc li a { color: var(--ink); }
.toc li .dots { flex: 1; border-bottom: 1px dotted #A0AEC0; margin: 0 6pt; transform: translateY(-3pt); }
.toc li .pg { font-weight: 700; color: var(--blue); min-width: 16pt; text-align: right; }
"""

FOOTER = ('<div style="width:100%; font-family:Segoe UI, Arial; font-size:7.5pt; color:#718096; padding:0 15mm; '
          'display:flex; justify-content:space-between;"><span>AnyDoc · Complete Visual Architecture &amp; Learning Guide</span>'
          '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')


def crop_screenshots():
    for name, box in CROPS.items():
        src = os.path.join(ASSETS, f"{name}.png")
        if not os.path.exists(src):
            sys.exit(f"missing screenshot {src}: run capture_screenshots.py first")
        im = Image.open(src).convert("RGB")
        box = (box[0], box[1], min(box[2], im.width), min(box[3], im.height))
        im.crop(box).save(os.path.join(ASSETS, f"{name}_c.png"), optimize=True)


def chapters(md_text):
    return re.findall(r"^# (.+?) \{#(\w+)\}\s*$", md_text, flags=re.M)


def label_for(cid):
    if cid == "ch0":
        return "START HERE"
    if cid.startswith("app"):
        return "APPENDIX " + cid[3:].upper()
    return f"CHAPTER {int(cid[2:]):02d}"


def toc_html(chs, pages=None):
    items = []
    for title, cid in chs:
        pg = str(pages.get(cid, "")) if pages else ""
        items.append(f'<li><a href="#{cid}">{html.escape(title)}</a><span class="dots"></span><span class="pg">{pg}</span></li>')
    return '<ol class="toc">' + "".join(items) + "</ol>"


def render_html(md_text, pages=None):
    chs = chapters(md_text)
    body = markdown.markdown(md_text, extensions=["extra", "codehilite", "sane_lists"],
                             extension_configs={"codehilite": {"guess_lang": False, "css_class": "codehilite"}})
    body = body.replace("<!--TOC-->", toc_html(chs, pages))
    body = re.sub(r'<h1 id="(\w+)">', lambda m: f'<div class="chap-label">{label_for(m.group(1))}</div><h1 id="{m.group(1)}">', body)
    for name in CROPS:
        body = body.replace(f'guide_assets/{name}.png', f'guide_assets/{name}_c.png')
    pyg = HtmlFormatter(style="friendly").get_style_defs(".codehilite")
    base = "file:///" + DOCS.replace("\\", "/") + "/"
    return (f'<!doctype html><html><head><meta charset="utf-8"><base href="{base}">'
            f'<title>AnyDoc: Complete Visual Architecture Guide</title><style>{CSS}\n{pyg}</style></head><body>{body}</body></html>')


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def print_pdf(html_text, out_path):
    tmp = tempfile.mkdtemp()
    page_file = os.path.join(tmp, "guide.html")
    with open(page_file, "w", encoding="utf-8") as f:
        f.write(html_text)
    port = free_port()
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--remote-allow-origins=http://127.0.0.1:{port}",
                             f"--user-data-dir={os.path.join(tmp, 'profile')}", "--allow-file-access-from-files", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                targets = requests.get(f"http://127.0.0.1:{port}/json", timeout=1).json()
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120, origin=f"http://127.0.0.1:{port}")
        counter = [0]

        def cdp(method, **params):
            counter[0] += 1
            ws.send(json.dumps({"id": counter[0], "method": method, "params": params}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == counter[0]:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg["result"]

        cdp("Page.enable")
        cdp("Page.navigate", url="file:///" + page_file.replace("\\", "/"))
        for _ in range(100):  # wait for fonts and images
            state = cdp("Runtime.evaluate", expression="document.readyState === 'complete' && [...document.images].every(i => i.complete)",
                        returnByValue=True)["result"]["value"]
            if state:
                break
            time.sleep(0.2)
        time.sleep(1)
        res = cdp("Page.printToPDF", paperWidth=8.27, paperHeight=11.69, marginTop=0.55, marginBottom=0.65,
                  marginLeft=0.6, marginRight=0.6, printBackground=True, displayHeaderFooter=True,
                  headerTemplate="<span></span>", footerTemplate=FOOTER, preferCSSPageSize=False)
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(res["data"]))
        ws.close()
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def find_pages(pdf_path, chs):
    doc = fitz.open(pdf_path)
    # Letter-spaced labels extract as "C H A P T E R 0 1", so compare without whitespace.
    texts = [re.sub(r"\s+", "", doc[i].get_text()) for i in range(doc.page_count)]
    pages = {}
    for title, cid in chs:
        label = label_for(cid).replace(" ", "")
        for i, t in enumerate(texts):
            if i < 2:  # cover + contents
                continue
            if label in t:
                pages[cid] = i + 1
                break
    return pages, doc.page_count


def main():
    md_text = open(MD, encoding="utf-8").read()
    crop_screenshots()
    chs = chapters(md_text)
    tmp_pdf = PDF + ".pass1.pdf"
    print_pdf(render_html(md_text), tmp_pdf)
    pages, _ = find_pages(tmp_pdf, chs)
    for _ in range(2):
        print_pdf(render_html(md_text, pages), tmp_pdf)
        check, total = find_pages(tmp_pdf, chs)
        if check == pages:
            break
        pages = check
    missing = [cid for _, cid in chs if cid not in pages]
    if missing:
        sys.exit(f"could not locate chapters in PDF: {missing}")
    doc = fitz.open(tmp_pdf)
    first = doc[0]  # hide the footer on the cover
    first.draw_rect(fitz.Rect(0, first.rect.height - 0.65 * 72, first.rect.width, first.rect.height), color=None, fill=(1, 1, 1))
    doc.set_toc([[1, "Contents", 2]] + [[1, title, pages[cid]] for title, cid in chs])
    doc.set_metadata({"title": "AnyDoc: Complete Visual Architecture & Learning Guide", "subject": "AnyDoc RAG system architecture",
                      "creator": "docs/guide_src/build_guide.py"})
    doc.save(PDF, garbage=3, deflate=True)
    doc.close()
    os.remove(tmp_pdf)
    print(f"PDF: {PDF}  pages={total}  chapters={len(chs)}")


if __name__ == "__main__":
    main()
