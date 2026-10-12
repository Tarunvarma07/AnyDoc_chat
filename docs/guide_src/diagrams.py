"""
Generates the SVG diagrams for the AnyDoc visual guide (docs/guide_assets/d*.svg).
Pure Python, no dependencies. Values marked "real" come from examples.json, which
compute_examples.py produces by running AnyDoc's own components.

    python docs/guide_src/diagrams.py
"""
import json
import os
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "guide_assets")
EX = json.load(open(os.path.join(ASSETS, "examples.json"), encoding="utf-8"))

KINDS = {
    "user":     ("#E8F0FE", "#2B6CB0", "User / interface"),
    "api":      ("#F3F4F8", "#4A5568", "API / backend"),
    "data":     ("#E3F4F1", "#1F7A70", "Data processing"),
    "search":   ("#E9ECFB", "#3949AB", "Search / retrieval"),
    "ai":       ("#F1E9FB", "#7B3FB5", "AI model"),
    "store":    ("#E6F4E7", "#2F7D3A", "Storage"),
    "security": ("#FFF1E3", "#C2601A", "Validation / security"),
    "infra":    ("#EEF0F2", "#5F6B76", "Infrastructure"),
    "error":    ("#FDECEC", "#B83232", "Error / rejection"),
    "note":     ("#FFFBEA", "#A68A00", "Note"),
}
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
MONO = "Consolas, 'Courier New', monospace"


class SVG:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=15, anchor="start", weight="normal", color="#1A202C", mono=False, italic=False):
        style = "font-style:italic;" if italic else ""
        self.add(f'<text x="{x}" y="{y}" font-family="{MONO if mono else FONT}" font-size="{size}" '
                 f'text-anchor="{anchor}" font-weight="{weight}" fill="{color}" style="{style}">{escape(str(s))}</text>')

    def lines(self, x, y, items, size=14, gap=None, **kw):
        gap = gap or size * 1.35
        for i, s in enumerate(items):
            self.text(x, y + i * gap, s, size=size, **kw)

    def rect(self, x, y, w, h, fill, stroke, r=10, sw=1.8, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def box(self, x, y, w, h, title, sub=(), kind="data", num=None, size=15, subsize=12.5, align="center", mono_sub=False, dash=None):
        fill, stroke, _ = KINDS[kind]
        self.rect(x, y, w, h, fill, stroke, dash=dash)
        n = 1 + len(sub)
        block = size * 1.25 + len(sub) * subsize * 1.35
        top = y + (h - block) / 2 + size
        tx = x + w / 2 if align == "center" else x + 14
        anchor = "middle" if align == "center" else "start"
        self.text(tx, top, title, size=size, anchor=anchor, weight="600", color="#1A202C")
        for i, s in enumerate(sub):
            self.text(tx, top + size * 0.35 + (i + 1) * subsize * 1.35, s, size=subsize, anchor=anchor, color="#2D3748", mono=mono_sub)
        if num is not None:
            self.badge(x, y, num, stroke)

    def badge(self, x, y, num, color="#2D3748"):
        self.add(f'<circle cx="{x}" cy="{y}" r="13" fill="{color}"/>')
        self.text(x, y + 5, num, size=13, anchor="middle", weight="700", color="#FFFFFF")

    def arrow(self, pts, label=None, color="#4A5568", dash=False, lx=None, ly=None, size=12.5, label_color="#2D3748"):
        if len(pts) == 2 and isinstance(pts[0], (int, float)):
            pts = [(pts[0], pts[1])]
        d = " ".join(f"{'M' if i == 0 else 'L'}{px},{py}" for i, (px, py) in enumerate(pts))
        da = ' stroke-dasharray="6 5"' if dash else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{da} marker-end="url(#ah)"/>')
        if label:
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            lx = lx if lx is not None else (x1 + x2) / 2
            ly = ly if ly is not None else (y1 + y2) / 2 - 7
            self.text(lx, ly, label, size=size, anchor="middle", color=label_color)

    def legend(self, x, y, kinds, cols=4, colw=200):
        for i, k in enumerate(kinds):
            fill, stroke, name = KINDS[k]
            cx, cy = x + (i % cols) * colw, y + (i // cols) * 24
            self.rect(cx, cy - 12, 18, 14, fill, stroke, r=3, sw=1.5)
            self.text(cx + 26, cy, name, size=12.5, color="#2D3748")

    def banner(self, text, kind="note"):
        fill, stroke, _ = KINDS[kind]
        self.rect(self.w - 330, 8, 320, 26, fill, stroke, r=13, sw=1.3)
        self.text(self.w - 170, 26, text, size=12.5, anchor="middle", weight="600", color=stroke)

    def save(self, name):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">'
                '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                '<path d="M0,0 L10,5 L0,10 z" fill="#4A5568"/></marker></defs>'
                f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>')
        with open(os.path.join(ASSETS, f"{name}.svg"), "w", encoding="utf-8") as f:
            f.write(head + "".join(self.parts) + "</svg>")


def bar(s, x, y, w, value, vmax, color, label, val_text):
    s.text(x - 10, y + 15, label, size=14, anchor="end", color="#1A202C")
    s.rect(x, y, max(w * value / vmax, 2), 22, color, color, r=4, sw=1)
    s.text(x + max(w * value / vmax, 2) + 8, y + 16, val_text, size=14, weight="600", color="#1A202C")


# ---------------------------------------------------------------- d00
def d00():
    s = SVG(980, 64)
    s.legend(20, 26, ["user", "api", "data", "search", "ai", "store", "security", "infra"], cols=4, colw=240)
    s.save("d00_legend")


# ---------------------------------------------------------------- d01
def d01():
    s = SVG(960, 330)
    s.banner("Illustrative example", "note")
    s.box(20, 110, 190, 90, "You ask", ["“What is the leave", "policy?”"], "user", num=1)
    s.box(260, 50, 240, 210, "AnyDoc searches", ["100-page handbook,", "already split into", "~400 small chunks", "", "finds the 5 chunks that", "best match the question"], "search", num=2)
    s.box(550, 50, 170, 210, "LLM reads", ["only those 5", "chunks and writes", "an answer that", "cites them"], "ai", num=3)
    s.box(770, 80, 170, 150, "You get", ["“24 days of paid", "annual leave [1]”", "", "[1] handbook.pdf, p.12"], "user", num=4)
    s.arrow([(210, 155), (258, 155)])
    s.arrow([(500, 155), (548, 155)])
    s.arrow([(720, 155), (768, 155)])
    s.text(480, 305, "The answer comes from your document, and the citation lets you open the exact page to check it.", size=14, anchor="middle", italic=True, color="#4A5568")
    s.save("d01_handbook_example")


# ---------------------------------------------------------------- d02
def d02():
    s = SVG(1100, 640)
    s.text(20, 34, "A. INGESTION  (POST /ingest/file, POST /ingest/url)", size=15, weight="700", color="#1A202C")
    y, h, w = 58, 96, 118
    xs = [20, 158, 296, 434, 572, 710, 848]
    ing = [("Streamlit UI", ["app.py", "upload / URL"], "user"),
           ("FastAPI route", ["src/api/main.py"], "api"),
           ("Validation", ["size, magic bytes,", "SSRF checks"], "security"),
           ("Loader", ["pypdf, docx2txt,", "csv, WebBaseLoader"], "data"),
           ("Metadata", ["1 LLM call", "per file (Groq)"], "ai"),
           ("Chunker", ["recursive", "500 / 50 chars"], "data"),
           ("Embeddings", ["MiniLM-L6-v2", "384 numbers"], "ai")]
    for i, (t, sub, k) in enumerate(ing):
        s.box(xs[i], y, w, h, t, sub, k, num=i + 1, size=14, subsize=12)
        if i:
            s.arrow([(xs[i - 1] + w, y + h / 2), (xs[i] - 2, y + h / 2)])
    s.box(986, y, 100, h, "Index", ["Chroma +", "BM25 rebuild"], "store", num=8, size=14, subsize=12)
    s.arrow([(xs[-1] + w, y + h / 2), (984, y + h / 2)])
    # storage
    s.box(860, 238, 226, 110, "Stored knowledge", ["ChromaDB on disk ./chroma_db", "(text + vector + metadata)", "BM25 index in memory"], "store", size=14, subsize=12)
    s.arrow([(1036, y + h), (1036, 236)])
    s.text(20, 300, "B. QUESTION ANSWERING  (POST /query)", size=15, weight="700", color="#1A202C")
    y2 = 400
    q = [("Question", ["typed in Chat tab"], "user"),
         ("Rewrite", ["LLM makes a", "search query"], "ai"),
         ("BM25 + dense", ["15 candidates", "from each"], "search"),
         ("RRF fusion", ["rank-based", "k = 60"], "search"),
         ("Rerank", ["cross-encoder", "keeps top 5"], "ai"),
         ("Guardrails", ["injection +", "profanity regex"], "security"),
         ("LLM answer", ["Groq Llama 3.1 8B", "temperature 0"], "ai"),
         ("Citation check", ["[n] must point", "to a chunk"], "security")]
    xs2 = [20, 156, 292, 428, 564, 700, 836, 972]
    for i, (t, sub, k) in enumerate(q):
        s.box(xs2[i], y2, 114, 96, t, sub, k, num=9 + i, size=14, subsize=12)
        if i:
            s.arrow([(xs2[i - 1] + 114, y2 + 48), (xs2[i] - 2, y2 + 48)])
    s.arrow([(900, 348), (900, 372), (349, 372), (349, 398)], dash=True)
    s.text(620, 366, "retrieval reads the stored index", size=12.5, anchor="middle", color="#2D3748")
    s.box(700, 528, 386, 50, "Answer + numbered sources + timings back to the UI", [], "user", num=17, size=14)
    s.arrow([(1029, 496), (1029, 526)])
    s.legend(20, 610, ["user", "api", "data", "search", "ai", "store", "security"], cols=7, colw=153)
    s.save("d02_big_picture")


# ---------------------------------------------------------------- d03
def d03():
    s = SVG(980, 300)
    items = [("Word", ["“leave”"], "user"),
             ("Token", ["BM25: regex pieces", "“zx-4471”, “leave”", "Model: sub-words"], "data"),
             ("Chunk", ["≤ 500 characters of", "a document, with", "source + page"], "data"),
             ("Embedding", ["384 numbers, e.g.", "[0.0385, -0.0398, ...]", "one per chunk"], "ai"),
             ("Vector database", ["ChromaDB stores", "chunk + embedding", "+ metadata"], "store")]
    x = 15
    for i, (t, sub, k) in enumerate(items):
        s.box(x, 60, 175, 150, t, sub, k, num=i + 1, size=15, subsize=12.5)
        if i < 4:
            s.arrow([(x + 175, 135), (x + 192, 135)])
        x += 192
    s.text(490, 30, "From a word to a searchable record: each step builds on the previous one", size=15, anchor="middle", weight="600")
    s.text(490, 250, "Two different “token” ideas exist in AnyDoc: BM25 splits text with a regex (hybrid_search._tokenize);", size=13, anchor="middle", color="#4A5568")
    s.text(490, 270, "the embedding model splits text into sub-word tokens internally. Chunk size is counted in characters, not tokens.", size=13, anchor="middle", color="#4A5568")
    s.save("d03_word_to_vector")


# ---------------------------------------------------------------- d04
def d04():
    s = SVG(980, 360)
    cols = [("A. LLM alone", "error", ["Question → LLM", "", "LLM never saw your", "documents", "May guess or refuse", "No sources to check"]),
            ("B. RAG (AnyDoc)", "store", ["Question → search your", "documents → best chunks", "→ LLM answers from them", "", "Cites [1]..[5]", "New file = re-index only"]),
            ("C. Fine-tuning", "infra", ["Train the model weights", "on your documents", "", "Slow + costly to update", "No built-in citations", "Can still hallucinate"])]
    for i, (t, k, lines) in enumerate(cols):
        x = 20 + i * 320
        fill, stroke, _ = KINDS[k]
        s.rect(x, 20, 300, 300, fill, stroke)
        s.text(x + 150, 52, t, size=17, anchor="middle", weight="700", color=stroke)
        s.lines(x + 150, 92, lines, size=14.5, anchor="middle", gap=24)
    s.text(490, 348, "AnyDoc uses B: documents change often and answers must point back to their source.", size=14, anchor="middle", italic=True, color="#4A5568")
    s.save("d04_three_approaches")


# ---------------------------------------------------------------- d05
def d05():
    s = SVG(1000, 420)
    s.text(20, 30, "Phase A — Indexing (once per uploaded file or URL)", size=15, weight="700")
    a = [("File / URL", [], "user"), ("Extract text", ["loaders"], "data"), ("Split", ["chunks"], "data"), ("Embed", ["MiniLM"], "ai")]
    for i, (t, sub, k) in enumerate(a):
        s.box(20 + i * 170, 50, 140, 80, t, sub, k, num=i + 1)
        if i:
            s.arrow([(20 + (i - 1) * 170 + 140, 90), (20 + i * 170 - 2, 90)])
    s.box(720, 50, 260, 110, "Stored for later", ["Chroma: text + vector + metadata", "(persisted in ./chroma_db)", "BM25 rebuilt in memory"], "store", num=5, size=15, subsize=12.5)
    s.arrow([(640, 90), (718, 90)])
    s.text(20, 230, "Phase B — Question answering (every question)", size=15, weight="700")
    b = [("Question", [], "user"), ("Find chunks", ["BM25 + vectors", "RRF + rerank"], "search"), ("Prompt", ["question +", "5 chunks"], "data"), ("LLM", ["Groq"], "ai"), ("Answer", ["with [n]"], "user")]
    for i, (t, sub, k) in enumerate(b):
        s.box(20 + i * 170, 260, 140, 90, t, sub, k, num=6 + i)
        if i:
            s.arrow([(20 + (i - 1) * 170 + 140, 305), (20 + i * 170 - 2, 305)])
    s.arrow([(850, 160), (850, 244), (300, 244), (300, 258)], dash=True, label="Phase B reads what Phase A stored", lx=575, ly=238)
    s.text(500, 400, "Chunk embeddings are computed once at ingestion and reused; only the question is embedded at query time.", size=13.5, anchor="middle", italic=True, color="#4A5568")
    s.save("d05_two_phases")


# ---------------------------------------------------------------- d06
def d06():
    s = SVG(1000, 640)
    s.box(20, 20, 220, 60, "POST /ingest/file", ["multipart field \"file\""], "user", num=1)
    s.box(280, 20, 300, 60, "Read ≤ 10 MB + 1 byte", ["temp file named by extension only"], "api", num=2)
    s.arrow([(240, 50), (278, 50)])
    checks = [("Size ≤ 10 MB?", "400 File size exceeds..."),
              ("libmagic MIME allowed?", "400 File type not allowed"),
              ("MIME matches extension?", "400 does not match its extension")]
    for i, (c, err) in enumerate(checks):
        y = 120 + i * 80
        s.box(280, y, 300, 56, c, [], "security", num=3 + i)
        s.box(640, y + 6, 330, 44, err, [], "error", size=13.5)
        s.arrow([(580, y + 28), (638, y + 28)], label="no", lx=609, ly=y + 22)
        s.arrow([(430, y - 24 if i else 80), (430, y - 2)])
    s.text(440, 112, "yes", size=12.5, color="#2D3748")
    loaders = [("PDF", ["PyPDFLoader", "1 Document / page"]), ("DOCX", ["Docx2txtLoader", "1 Document"]),
               ("TXT", ["TextLoader", "utf-8-sig → latin-1"]), ("CSV", ["CSVLoader", "1 Document / row"])]
    for i, (t, sub) in enumerate(loaders):
        s.box(20 + i * 240, 390, 215, 76, t, sub, "data", size=15, subsize=12.5)
    s.arrow([(430, 352), (430, 372), (127, 372), (127, 388)])
    for xx in (367, 607, 847):
        s.arrow([(430, 372), (xx, 372), (xx, 388)])
    s.badge(20, 390, 6, KINDS["data"][1])
    s.box(20, 500, 300, 56, "Any non-blank text?", [], "security", num=7)
    s.box(20, 580, 300, 44, "422 No extractable text (no OCR)", [], "error", size=13.5)
    s.arrow([(170, 556), (170, 578)], label="no", lx=185, ly=572)
    s.box(380, 500, 590, 56, "source = filename → metadata (1 LLM call) → chunk → embed + store", [], "store", num=8, size=14)
    s.arrow([(320, 528), (378, 528)], label="yes", lx=349, ly=520)
    s.arrow([(500, 466), (500, 498)])
    s.box(640, 580, 330, 44, "Loader raises → 422 Could not extract text", [], "error", size=13.5)
    s.arrow([(955, 466), (985, 466), (985, 602), (972, 602)], dash=True)
    s.save("d06_file_ingestion")


# ---------------------------------------------------------------- d07
def d07():
    s = SVG(980, 300)
    s.text(240, 28, "PDF with a text layer", size=16, anchor="middle", weight="700")
    s.text(740, 28, "Scanned PDF (page images only)", size=16, anchor="middle", weight="700")
    s.box(40, 50, 170, 150, "Page", ["text is stored", "as characters", "“Error code", "ZX-4471...”"], "user")
    s.box(270, 80, 170, 90, "pypdf", ["extract_text()"], "data")
    s.arrow([(210, 125), (268, 125)])
    s.box(270, 200, 170, 70, "Document per page", ["page=2, page_label=“3”"], "store", size=13.5, subsize=12)
    s.arrow([(355, 170), (355, 198)])
    s.box(540, 50, 170, 150, "Page", ["only a picture", "of text", "(pixels)"], "user")
    s.box(770, 80, 170, 90, "pypdf", ["finds no text", "→ empty string"], "data")
    s.arrow([(710, 125), (768, 125)])
    s.box(770, 200, 170, 70, "422 response", ["OCR not implemented"], "error", size=13.5, subsize=12)
    s.arrow([(855, 170), (855, 198)])
    s.add('<line x1="490" y1="40" x2="490" y2="280" stroke="#CBD5E0" stroke-width="2" stroke-dasharray="6 6"/>')
    s.save("d07_pdf_text_vs_scanned")


# ---------------------------------------------------------------- d08
def d08():
    s = SVG(980, 280)
    s.text(150, 28, "inventory.csv (rows and columns)", size=15, anchor="middle", weight="700")
    rows = [["sku", "product", "warehouse", "quantity"], ["AR-100", "Gripper Arm", "Pune", "42"], ["AR-200", "Lidar Sensor", "Austin", "7"]]
    cw = [70, 100, 85, 65]
    for r, row in enumerate(rows):
        x = 0
        for c, cell in enumerate(row):
            fill = "#E8F0FE" if r == 0 else "#FFFFFF"
            s.rect(10 + x, 45 + r * 34, cw[c], 34, fill, "#A0AEC0", r=0, sw=1)
            s.text(10 + x + 6, 45 + r * 34 + 22, cell, size=13, weight="600" if r == 0 else "normal", mono=True)
            x += cw[c]
    s.arrow([(345, 95), (410, 95)], label="CSVLoader", lx=377, ly=86)
    s.text(690, 28, "One Document per data row", size=15, anchor="middle", weight="700")
    for i, (sku, prod, wh, q) in enumerate([("AR-100", "Gripper Arm", "Pune", "42"), ("AR-200", "Lidar Sensor", "Austin", "7")]):
        y = 45 + i * 105
        s.rect(420, y, 520, 92, "#E3F4F1", "#1F7A70")
        s.lines(436, y + 24, [f"sku: {sku}", f"product: {prod}", f"warehouse: {wh}   quantity: {q}"], size=13, mono=True, gap=20)
        s.text(925, y + 24, f"metadata row={i}", size=12, anchor="end", color="#1F7A70", mono=True)
    s.text(490, 268, "Each row becomes “header: value” text, so a row is searchable. Questions that need many rows at once (sums, counts) are not answered well.", size=12.5, anchor="middle", italic=True, color="#4A5568")
    s.save("d08_csv_rows")


# ---------------------------------------------------------------- d09
def d09():
    s = SVG(1000, 560)
    s.box(20, 20, 200, 60, "POST /ingest/url", ["{\"url\": \"https://...\"}"], "user", num=1, mono_sub=True)
    s.box(270, 20, 330, 60, "validate_url", ["http/https only; every resolved IP global"], "security", num=2)
    s.arrow([(220, 50), (268, 50)])
    s.box(650, 20, 320, 60, "400 Invalid scheme / internal IP", ["/ could not resolve"], "error", size=13.5)
    s.arrow([(600, 50), (648, 50)], label="fails", lx=624, ly=44)
    s.rect(270, 110, 700, 156, "#FFF7EE", "#C2601A", dash="6 5")
    s.text(285, 256, "resolve_safe_url  (manual redirects, max 5 hops)", size=13.5, weight="700", color="#C2601A")
    s.box(290, 150, 200, 90, "Validate hop", ["validate_url(current)"], "security", num=3)
    s.box(530, 150, 200, 90, "GET (no auto-redirect)", ["timeout 5 s"], "infra", num=4, size=14)
    s.box(770, 150, 180, 90, "3xx?", ["yes: next = Location", "no: final URL"], "security", num=5)
    s.arrow([(490, 195), (528, 195)])
    s.arrow([(730, 195), (768, 195)])
    s.arrow([(860, 150), (860, 140), (390, 140), (390, 148)], dash=True, label="redirect: check the new URL too", lx=625, ly=134)
    s.box(20, 300, 220, 80, "robots.txt", ["fetched via the same safe", "path; unreadable → skip"], "security", num=6, size=14, subsize=12)
    s.arrow([(950, 195), (985, 195), (985, 282), (130, 282), (130, 298)])
    s.box(280, 300, 250, 80, "WebBaseLoader", ["requests + BeautifulSoup", "raise_for_status=True"], "data", num=7, size=14, subsize=12)
    s.arrow([(240, 340), (278, 340)])
    s.box(570, 300, 400, 80, "get_text(): scripts/styles dropped,", ["nav and footer text kept (no boilerplate removal)"], "data", num=8, size=14, subsize=12)
    s.arrow([(530, 340), (568, 340)])
    s.box(20, 420, 450, 80, "Up to 5 links on the same host (depth 1)", ["each one repeats steps 2–8"], "search", num=9, size=14, subsize=12.5)
    s.arrow([(770, 380), (770, 400), (245, 400), (245, 418)])
    s.box(520, 420, 450, 80, "Documents → metadata → chunk → store", ["same path as files"], "store", num=10, size=14, subsize=12.5)
    s.arrow([(470, 460), (518, 460)])
    s.text(500, 540, "Not supported: JavaScript-rendered pages (no headless browser), recursive crawling, non-HTML URLs, response size limits.", size=13, anchor="middle", italic=True, color="#B83232")
    s.save("d09_url_ingestion")


# ---------------------------------------------------------------- d10
def d10():
    s = SVG(1000, 470)
    s.text(240, 28, "Without SSRF checks", size=16, anchor="middle", weight="700", color="#B83232")
    s.text(760, 28, "AnyDoc's checks", size=16, anchor="middle", weight="700", color="#2F7D3A")
    s.box(30, 50, 420, 60, "Attacker submits", ["http://169.254.169.254/latest/meta-data/"], "error", num=1, mono_sub=True, subsize=12)
    s.box(30, 140, 420, 60, "Server fetches it from inside the cloud", ["the attacker's browser could never reach it"], "infra", num=2, subsize=12.5)
    s.box(30, 230, 420, 60, "Cloud metadata answers", ["instance info, sometimes temporary credentials"], "error", num=3, subsize=12.5)
    s.box(30, 320, 420, 60, "Response is indexed", ["attacker asks the chatbot to read it back"], "error", num=4, subsize=12.5)
    for y in (110, 200, 290):
        s.arrow([(240, y), (240, y + 28)])
    s.add('<line x1="500" y1="40" x2="500" y2="400" stroke="#CBD5E0" stroke-width="2" stroke-dasharray="6 6"/>')
    s.box(550, 50, 420, 60, "validate_url resolves the host", ["getaddrinfo → every IPv4 and IPv6 address"], "security", num=1, subsize=12.5)
    s.box(550, 140, 420, 60, "169.254.169.254 is link-local", ["is_global = False → rejected"], "security", num=2, subsize=12.5)
    s.box(550, 230, 420, 60, "400 URL points to an internal/private IP", [], "error", num=3, size=14)
    s.box(550, 320, 420, 60, "Redirect trick also checked", ["public site 302 → internal URL: hop rejected"], "security", num=4, subsize=12.5)
    for y in (110, 200):
        s.arrow([(760, y), (760, y + 28)])
    s.text(500, 430, "Still open: DNS rebinding — a hostile DNS server can answer “public” during the check and “internal”", size=13.5, anchor="middle", color="#B83232")
    s.text(500, 452, "when requests connects a moment later. Fix (not implemented): pin the checked IP, or use an egress proxy.", size=13.5, anchor="middle", color="#B83232")
    s.save("d10_ssrf")


# ---------------------------------------------------------------- d11
def d11():
    e = EX["embedding"]
    s = SVG(960, 330)
    s.banner("2-D sketch, real similarities", "note")
    s.rect(20, 40, 470, 270, "#FAFBFD", "#CBD5E0", r=8, sw=1.2)
    s.text(255, 64, "Embedding space (384 dimensions, drawn in 2)", size=13.5, anchor="middle", color="#4A5568")
    pts = [(120, 140, "The dog is playing outside", "#2B6CB0"), (190, 200, "A puppy is running outdoors", "#2B6CB0"), (410, 270, "The quarterly invoice is overdue", "#C2601A")]
    s.add(f'<line x1="120" y1="140" x2="190" y2="200" stroke="#2F7D3A" stroke-width="2"/>')
    s.add(f'<line x1="190" y1="200" x2="410" y2="270" stroke="#B83232" stroke-width="1.5" stroke-dasharray="5 4"/>')
    for x, y, t, c in pts:
        s.add(f'<circle cx="{x}" cy="{y}" r="8" fill="{c}"/>')
    s.text(132, 132, "dog playing outside", size=13)
    s.text(204, 192, "puppy running outdoors", size=13)
    s.text(410, 296, "invoice overdue", size=13, anchor="middle")
    s.text(130, 182, f"{e['cosine'][0][1]:.3f}", size=13, weight="700", color="#2F7D3A")
    s.text(300, 228, f"{e['cosine'][1][2]:.3f}", size=13, weight="700", color="#B83232")
    s.text(520, 70, "Cosine similarity (real, all-MiniLM-L6-v2)", size=14.5, weight="700")
    labels = ["dog", "puppy", "invoice"]
    for i, l in enumerate(labels):
        s.text(660 + i * 90, 100, l, size=13.5, anchor="middle", weight="600")
        s.text(600, 132 + i * 34, l, size=13.5, anchor="end", weight="600")
        for j in range(3):
            v = e["cosine"][i][j]
            fill = "#C6F6D5" if (v > 0.5 and i != j) else ("#EDF2F7" if i == j else "#FFFFFF")
            s.rect(615 + j * 90, 112 + i * 34, 90, 30, fill, "#CBD5E0", r=0, sw=1)
            s.text(660 + j * 90, 132 + i * 34, f"{v:.3f}", size=13.5, anchor="middle", mono=True)
    s.lines(520, 242, ["1.0 = same direction; ~0 = unrelated.", f"Each vector has {e['dims']} numbers and length {e['norm']},", "so cosine ranking = L2-distance ranking in Chroma."], size=13, gap=20, color="#2D3748")
    s.save("d11_embedding_space")


# ---------------------------------------------------------------- d12
def d12():
    r = EX["chroma_record"]
    s = SVG(980, 470)
    s.banner("Real record from samples/acme_handbook.pdf", "note")
    s.text(20, 30, "One record in the Chroma collection “qa_chatbot”", size=16, weight="700")
    fields = [("id", "store", [r["id"][:40] + "...", "sha256(source | chunk_index | text)"]),
              ("document", "data", [r["document"].splitlines()[0], r["document"].splitlines()[1][:58] + "..."]),
              ("embedding", "ai", ["[" + ", ".join(f"{v}" for v in r["embedding_first4"]) + ", ...]", f"{r['embedding_len']} floats, unit length"]),
              ("metadata", "user", ["source: acme_handbook.pdf   page: 2 (0-based)   page_label: \"3\"",
                                    "chunk_index: 2   chunk_strategy: recursive   total_pages: 4",
                                    "producer, creator: PyPDF   (via the API also: extracted_title, extracted_summary,", "extracted_topics, document_type from the metadata LLM call)"])]
    y = 50
    for name, k, vals in fields:
        fill, stroke, _ = KINDS[k]
        h = 30 + 20 * len(vals)
        s.rect(20, y, 940, h, fill, stroke)
        s.text(36, y + 26, name, size=15, weight="700", color=stroke)
        s.lines(170, y + 26, vals, size=13, gap=20, mono=True)
        y += h + 10
    s.text(20, y + 22, "Collection metadata: embedding_model_name = sentence-transformers/all-MiniLM-L6-v2 · index: HNSW, space l2 · persisted to ./chroma_db", size=13, color="#4A5568")
    s.text(20, y + 44, "The original file is NOT stored — only chunk text, vectors and metadata. The extracted_* fields are informational: never embedded or sent to the LLM.", size=13, color="#4A5568")
    s.save("d12_chroma_record")


# ---------------------------------------------------------------- d13
def d13():
    b = EX["bm25_vs_dense"]
    s = SVG(980, 380)
    s.banner("Real scores from AnyDoc's code", "note")
    s.text(20, 30, f"Query: “{b['query']}”", size=15, weight="700")
    s.text(20, 54, "BM25 tokens: " + ", ".join(b["query_tokens"]), size=13, mono=True, color="#3949AB")
    docs = {"A": "A: payment gateway ... error code E1042", "B": "B: checkout failed ... bank unavailable", "C": "C: leave policy ... 18 annual leave days"}
    s.text(250, 95, "BM25 (keyword) score", size=14.5, anchor="middle", weight="700", color="#3949AB")
    s.text(740, 95, "Dense (embedding) cosine", size=14.5, anchor="middle", weight="700", color="#7B3FB5")
    for i, k in enumerate("ABC"):
        y = 115 + i * 52
        bar(s, 200, y, 220, b["bm25"][k], 1.8, "#7986CB", k, f"{b['bm25'][k]:.3f}")
        bar(s, 660, y, 220, b["dense_cosine"][k], 1.0, "#B39DDB", k, f"{b['dense_cosine'][k]:.3f}")
    s.lines(20, 290, [docs["A"], docs["B"], docs["C"]], size=12.5, gap=18, color="#4A5568")
    s.lines(470, 290, ["BM25 only scores A: the only document sharing query words",
                       "(payment, error, e1042). B and C share none → 0.",
                       "Dense also ranks A first, but gives B 0.513: “checkout",
                       "failed” means something similar to “payment error”."], size=12.5, gap=18, color="#2D3748")
    s.save("d13_bm25_vs_dense")


# ---------------------------------------------------------------- d14
def d14():
    s = SVG(1000, 330)
    s.box(20, 120, 150, 80, "Search query", ["(rewritten)"], "user", num=1)
    s.box(230, 40, 210, 90, "Dense search", ["Chroma k = 15", "nearest vectors"], "search", num=2)
    s.box(230, 190, 210, 90, "BM25 search", ["top 15 with", "score > 0"], "search", num=3)
    s.arrow([(170, 150), (228, 90)])
    s.arrow([(170, 170), (228, 230)])
    s.box(500, 115, 160, 90, "RRF", ["k = 60", "→ 15 fused"], "search", num=4)
    s.arrow([(440, 85), (498, 145)])
    s.arrow([(440, 235), (498, 175)])
    s.box(720, 115, 150, 90, "Cross-encoder", ["scores 15 pairs", "keeps top 5"], "ai", num=5)
    s.arrow([(660, 160), (718, 160)])
    s.box(900, 125, 85, 70, "Prompt", ["5 chunks"], "data", num=6, size=14)
    s.arrow([(870, 160), (898, 160)])
    s.text(500, 300, "candidate_n = top_n × 3 = 15 because a reranker is attached (HybridRetriever.__init__). Without one, both lists would be 5 long.", size=13, anchor="middle", color="#4A5568")
    s.save("d14_hybrid_pipeline")


# ---------------------------------------------------------------- d15
def d15():
    k = 60
    ranks = {"A": (1, 3), "B": (2, 1), "C": (5, 2), "D": (3, None)}
    sc = {d: sum(1 / (k + r) for r in rr if r) for d, rr in ranks.items()}
    order = sorted(sc, key=sc.get, reverse=True)
    s = SVG(980, 360)
    s.banner("Illustrative ranks, exact arithmetic", "note")
    s.text(20, 30, "RRF score = Σ 1 / (k + rank),  k = 60", size=16, weight="700")
    hdr = ["Doc", "BM25 rank", "Vector rank", "BM25 term", "Vector term", "RRF score"]
    cw = [60, 100, 110, 120, 120, 120]
    for c, h in enumerate(hdr):
        s.rect(20 + sum(cw[:c]), 50, cw[c], 32, "#E9ECFB", "#A0AEC0", r=0, sw=1)
        s.text(20 + sum(cw[:c]) + cw[c] / 2, 71, h, size=13, anchor="middle", weight="700")
    for i, d in enumerate("ABCD"):
        b, v = ranks[d]
        cells = [d, str(b), str(v) if v else "not returned", f"1/{k + b} = {1 / (k + b):.4f}", f"1/{k + v} = {1 / (k + v):.4f}" if v else "0", f"{sc[d]:.4f}"]
        for c, val in enumerate(cells):
            s.rect(20 + sum(cw[:c]), 82 + i * 32, cw[c], 32, "#FFFFFF", "#CBD5E0", r=0, sw=1)
            s.text(20 + sum(cw[:c]) + cw[c] / 2, 103 + i * 32, val, size=12.5, anchor="middle", mono=c >= 3, weight="700" if c == 5 else "normal")
    s.text(700, 70, "Fused ranking", size=15, weight="700")
    for i, d in enumerate(order):
        bar(s, 740, 85 + i * 40, 160, sc[d], 0.034, "#7986CB", d, f"{sc[d]:.4f}")
    s.lines(20, 260, ["B wins: rank 2 + rank 1 beats A's rank 1 + rank 3 by a hair — being near the top of BOTH lists matters most.",
                      "D appears in only one list, so it gets only one term and finishes last.",
                      "k = 60 flattens the curve: rank 1 → 0.0164, rank 10 → 0.0143. Raw BM25/vector scores are never compared."], size=13, gap=22, color="#2D3748")
    s.save("d15_rrf_worked")


# ---------------------------------------------------------------- d16
def d16():
    r = EX["rerank"]
    s = SVG(1000, 330)
    s.banner("Real run on samples/", "note")
    s.text(20, 30, f"Query: “{r['query']}”", size=14.5, weight="700")
    s.text(230, 64, "Hybrid (RRF) order", size=14.5, anchor="middle", weight="700", color="#3949AB")
    s.text(770, 64, "After cross-encoder", size=14.5, anchor="middle", weight="700", color="#7B3FB5")
    short = lambda t: t.split(" | ")[0]
    pos_before = {}
    for i, t in enumerate(r["hybrid_order"]):
        y = 80 + i * 44
        hl = "travel_policy" in t
        s.rect(20, y, 420, 36, "#E9ECFB" if not hl else "#FFF1E3", "#3949AB" if not hl else "#C2601A", r=6, sw=1.4)
        s.text(36, y + 24, f"{i + 1}. {short(t)}", size=13.5, weight="700" if hl else "normal")
        pos_before[short(t)] = y + 18
    for i, (t, score) in enumerate(r["reranked_order"]):
        y = 80 + i * 44
        hl = "travel_policy" in t
        s.rect(560, y, 420, 36, "#F1E9FB" if not hl else "#FFF1E3", "#7B3FB5" if not hl else "#C2601A", r=6, sw=1.4)
        s.text(576, y + 24, f"{i + 1}. {short(t)}", size=13.5, weight="700" if hl else "normal")
        s.text(965, y + 24, f"{score:+.2f}", size=13, anchor="end", mono=True)
        if short(t) in pos_before:
            s.arrow([(440, pos_before[short(t)]), (558, y + 18)], color="#A0AEC0")
    s.text(500, 315, "The travel policy (hotel limit 180 USD/night) moves from #2 to #1. Scores are raw logits: higher = more relevant, not a probability.", size=12.5, anchor="middle", italic=True, color="#4A5568")
    s.save("d16_rerank_before_after")


# ---------------------------------------------------------------- d17
def d17():
    s = SVG(980, 300)
    s.text(240, 28, "Bi-encoder (embedding search)", size=15.5, anchor="middle", weight="700", color="#3949AB")
    s.text(740, 28, "Cross-encoder (reranker)", size=15.5, anchor="middle", weight="700", color="#7B3FB5")
    s.box(30, 50, 170, 50, "Question", [], "user")
    s.box(280, 50, 170, 50, "Chunk", [], "data")
    s.box(30, 130, 170, 50, "MiniLM encoder", [], "ai", size=14)
    s.box(280, 130, 170, 50, "MiniLM encoder", [], "ai", size=14)
    s.arrow([(115, 100), (115, 128)])
    s.arrow([(365, 100), (365, 128)])
    s.box(130, 220, 220, 50, "cosine(vector, vector)", [], "search", size=14)
    s.arrow([(115, 180), (200, 218)])
    s.arrow([(365, 180), (280, 218)])
    s.add('<line x1="490" y1="40" x2="490" y2="290" stroke="#CBD5E0" stroke-width="2" stroke-dasharray="6 6"/>')
    s.box(560, 50, 360, 50, "[Question  +  Chunk]  together", [], "user", size=14)
    s.box(620, 130, 240, 50, "ms-marco cross-encoder", [], "ai", size=14)
    s.arrow([(740, 100), (740, 128)])
    s.box(650, 220, 180, 50, "relevance logit", [], "search", size=14)
    s.arrow([(740, 180), (740, 218)])
    s.text(240, 292, "Chunk vectors precomputed once → fast over the whole corpus", size=12.5, anchor="middle", color="#4A5568")
    s.text(740, 292, "One model run per pair → accurate but only for ~15 candidates", size=12.5, anchor="middle", color="#4A5568")
    s.save("d17_bi_vs_cross")


# ---------------------------------------------------------------- d18
def d18():
    s = SVG(1000, 360)
    s.box(20, 140, 160, 70, "User question", ["original text"], "user", num=1)
    s.box(230, 20, 220, 56, "Blank?", ["→ use original"], "security", size=14)
    s.box(230, 96, 220, 56, "Injection regex hit?", ["→ use original"], "security", size=14)
    s.box(230, 172, 220, 56, "LLM rewrite (Groq)", ["llama-3.1-8b-instant, temp 0"], "ai", size=14, subsize=12)
    s.box(230, 248, 220, 56, "Exception / empty?", ["→ use original"], "security", size=14)
    s.arrow([(180, 175), (228, 48)])
    s.arrow([(180, 175), (228, 124)])
    s.arrow([(180, 175), (228, 200)])
    s.arrow([(340, 228), (340, 246)])
    s.box(520, 60, 230, 90, "search_query", ["used for BM25, dense", "search AND reranking"], "search", num=2)
    s.arrow([(450, 200), (518, 110)])
    s.box(520, 200, 230, 90, "original question", ["used for guardrails,", "prompt and citations"], "data", num=3)
    s.arrow([(180, 190), (205, 330), (500, 330), (520, 260)], dash=True)
    s.box(800, 60, 180, 90, "Retrieval trace", ["shows the rewrite", "or “unchanged”"], "user", num=4, size=14)
    s.arrow([(750, 105), (798, 105)])
    s.text(500, 352, "No conversation memory: each question is rewritten on its own. The rewrite's effect on accuracy has not been measured.", size=12.5, anchor="middle", italic=True, color="#4A5568")
    s.save("d18_query_rewrite")


# ---------------------------------------------------------------- d19
def d19():
    s = SVG(1000, 420)
    s.box(20, 20, 300, 80, "Input guardrails (original question)", ["check_prompt_injection, check_profanity", "hit → fixed refusal, no LLM call"], "security", num=1, size=14, subsize=12)
    s.rect(380, 20, 360, 300, "#FAFBFD", "#4A5568")
    s.text(560, 46, "Prompt (qa_chain.py)", size=15, anchor="middle", weight="700")
    s.rect(398, 60, 324, 92, "#F3F4F8", "#A0AEC0", r=6, sw=1.2)
    s.lines(410, 80, ["Instructions: use ONLY the context;", "if not answerable output exactly", "“I cannot answer this based on the", "provided documents.”; cite as [n]"], size=12.5, gap=17)
    s.rect(398, 162, 324, 92, "#E3F4F1", "#1F7A70", r=6, sw=1.2)
    s.lines(410, 182, ["Document [1] (Source: acme_handbook.pdf):", "Section 3: Incident response ...", "Document [2] ... up to Document [5]", "(~2,500 characters in total)"], size=12.5, gap=17, mono=False)
    s.rect(398, 264, 324, 44, "#E8F0FE", "#2B6CB0", r=6, sw=1.2)
    s.text(410, 291, "Question: <the user's original question>", size=12.5)
    s.arrow([(320, 60), (378, 60)])
    s.box(800, 120, 180, 90, "Groq LLM", ["llama-3.1-8b-instant", "temperature 0"], "ai", num=2, size=14, subsize=12)
    s.arrow([(740, 165), (798, 165)])
    s.box(800, 250, 180, 110, "Output checks", ["profanity regex", "verify_citations:", "every [n] in 1..5"], "security", num=3, size=14, subsize=12)
    s.arrow([(890, 210), (890, 248)])
    s.box(380, 350, 360, 56, "Answer string → JSON response", [], "user", num=4, size=14)
    s.arrow([(800, 330), (740, 370)])
    s.text(20, 150, "Failure paths", size=14, weight="700", color="#B83232")
    s.box(20, 160, 300, 80, "LLM error", ["“An error occurred while generating", "the answer: <reason>.” (HTTP 200)"], "error", size=14, subsize=12)
    s.box(20, 270, 300, 80, "Check fails", ["fixed refusal string", "(UI shows refusal box)"], "error", size=14, subsize=12)
    s.save("d19_prompt_generation")


# ---------------------------------------------------------------- d20
def d20():
    s = SVG(980, 330)
    levels = [(40, 20, 900, 290, "#FDECEC", "#B83232", "3. The cited chunk actually supports the claim (entailment)", "NOT checked"),
              (100, 70, 780, 200, "#FFF7E6", "#C2601A", "2. The cited chunk is relevant to the question", "partly: reranker ordering only"),
              (170, 125, 640, 90, "#E6F4E7", "#2F7D3A", "1. Every [n] points to one of the supplied chunks", "CHECKED by verify_citations")]
    for x, y, w, h, fill, stroke, t, st in levels:
        s.rect(x, y, w, h, fill, stroke, r=14, sw=2)
        s.text(x + w / 2, y + 26, t, size=14.5, anchor="middle", weight="700", color=stroke)
        s.text(x + w / 2, y + 46, st, size=13, anchor="middle", color=stroke)
    s.text(490, 195, "regex \\[(\\d+)\\]  →  1 ≤ n ≤ number of chunks", size=13.5, anchor="middle", mono=True)
    s.save("d20_citation_levels")


# ---------------------------------------------------------------- sequence helper
def sequence(name, w, h, parts, msgs, notes=(), title=None):
    s = SVG(w, h)
    xs = {}
    n = len(parts)
    step = (w - 40) / n
    for i, (key, label, kind) in enumerate(parts):
        x = 20 + step * i + step / 2
        xs[key] = x
        s.box(x - step / 2 + 6, 20, step - 12, 52, label[0], label[1:], kind, size=13.5, subsize=11.5)
        s.add(f'<line x1="{x}" y1="72" x2="{x}" y2="{h - 20}" stroke="#A0AEC0" stroke-width="1.5" stroke-dasharray="4 4"/>')
    for i, m in enumerate(msgs):
        frm, to, y, label = m[:4]
        ret = len(m) > 4 and m[4]
        x1, x2 = xs[frm], xs[to]
        lw = len(label) * 6.4  # approximate rendered width at 12px
        if frm == to:
            s.arrow([(x1, y), (x1 + 40, y), (x1 + 40, y + 18), (x1 + 4, y + 18)])
            if x1 + 48 + lw > w - 5:
                s.text(x1 - 8, y + 13, label, size=12, anchor="end")
            else:
                s.text(x1 + 48, y + 13, label, size=12)
        else:
            s.arrow([(x1, y), (x2 - (6 if x2 > x1 else -6), y)], dash=ret)
            cx = (x1 + x2) / 2
            if cx - lw / 2 < 5:
                s.text(min(x1, x2) + 8, y - 6, label, size=12, anchor="start", color="#1A202C")
            elif cx + lw / 2 > w - 5:
                s.text(max(x1, x2) - 8, y - 6, label, size=12, anchor="end", color="#1A202C")
            else:
                s.text(cx, y - 6, label, size=12, anchor="middle", color="#1A202C")
    for (x, y, wd, ht, text_lines) in notes:
        s.rect(x, y, wd, ht, "#FFFBEA", "#A68A00", r=6, sw=1.2)
        s.lines(x + 10, y + 18, text_lines, size=12, gap=16, color="#5F4B00")
    s.save(name)


def d21():
    sequence("d21_seq_ingest_file", 1000, 520,
             [("ui", ["Streamlit UI", "app.py"], "user"), ("api", ["ingest_file", "main.py"], "api"),
              ("val", ["validate_file", "guardrails.py"], "security"), ("rdr", ["FileReader", "file_reader.py"], "data"),
              ("meta", ["Metadata", "Extractor (Groq)"], "ai"), ("chk", ["Chunker", "chunk.py"], "data"),
              ("st", ["EmbedStore", "Chroma"], "store"), ("bm", ["Hybrid", "Retriever (BM25)"], "search")],
             [("ui", "api", 110, "1 POST /ingest/file (multipart)"), ("api", "val", 150, "2 size/MIME/extension"),
              ("val", "api", 180, "ok / 400", True), ("api", "rdr", 220, "3 load(tmp_path)"),
              ("rdr", "api", 250, "Documents (or 422)", True), ("api", "meta", 290, "4 process_documents"),
              ("meta", "api", 320, "title/summary added", True), ("api", "chk", 360, "5 split_documents"),
              ("api", "st", 400, "6 add_documents(ids)"), ("st", "bm", 430, "7 callback: rebuild_index"),
              ("api", "ui", 480, "8 200 {\"message\": \"Successfully ingested N chunks...\"}", True)])


def d22():
    sequence("d22_seq_query", 1000, 560,
             [("ui", ["Streamlit UI", "Chat tab"], "user"), ("api", ["query_documents", "main.py"], "api"),
              ("rw", ["QueryRewriter", "Groq"], "ai"), ("hr", ["HybridRetriever", "BM25 + Chroma"], "search"),
              ("rr", ["Reranker", "cross-encoder"], "ai"), ("qa", ["QAGenerator", "qa_chain.py"], "ai")],
             [("ui", "api", 110, "1 POST /query {query}"), ("api", "rw", 150, "2 rewrite(query)"),
              ("rw", "api", 180, "search_query", True), ("api", "hr", 220, "3 get_relevant_documents"),
              ("hr", "hr", 240, "BM25 + dense + RRF"), ("hr", "rr", 290, "4 rerank(15 → 5)"),
              ("rr", "hr", 320, "5 docs + rerank_score", True), ("hr", "api", 350, "retrieved_docs", True),
              ("api", "qa", 390, "6 generate_answer(original, docs)"), ("qa", "qa", 410, "guardrails, Groq, citations"),
              ("qa", "api", 460, "answer string", True), ("api", "ui", 510, "7 200 {answer, sources, search_query, pipeline, timings}", True)],
             notes=[(20, 136, 150, 58, ["rewrite_ms", "= step 2"]), (20, 236, 150, 58, ["retrieval_ms", "= steps 3–5"]), (20, 380, 150, 58, ["gen_ms", "= step 6"])])


def d23():
    sequence("d23_seq_ui", 1000, 470,
             [("u", ["You", "browser"], "user"), ("st", ["Streamlit server", "app.py rerun"], "user"), ("api", ["FastAPI", "/query"], "api")],
             [("u", "st", 110, "1 type question + Enter"), ("st", "u", 150, "2 show question + spinner", True),
              ("st", "api", 190, "3 requests.post(..., timeout=170) — blocks this script run"),
              ("api", "st", 290, "4 JSON response (or error status)", True),
              ("st", "st", 320, "5 append to session_state.messages (max 40)"),
              ("st", "u", 390, "6 render answer / refusal box, source expanders, retrieval trace", True)],
             notes=[(620, 210, 340, 60, ["The UI waits synchronously: one request per", "question; the spinner covers rewrite + retrieval + LLM."])])


def d24():
    s = SVG(1000, 430)
    s.rect(20, 20, 640, 390, "#F7F8FA", "#5F6B76", dash="6 5")
    s.text(36, 46, "docker compose up --build  (one image from Dockerfile: python:3.11-slim + libmagic1)", size=13.5, weight="700", color="#5F6B76")
    s.box(50, 80, 260, 140, "ui container", ["streamlit run app.py", "port 8501", "API_URL=http://api:8000", "depends_on: api"], "user", size=15, subsize=12.5)
    s.box(370, 80, 260, 140, "api container", ["uvicorn src.api.main:app", "port 8000", "env_file: .env (GROQ_API_KEY)", "volume: chroma_data"], "api", size=15, subsize=12.5)
    s.arrow([(310, 150), (368, 150)], label="HTTP", lx=339, ly=142)
    s.box(370, 280, 260, 90, "volume chroma_data", ["mounted at /app/chroma_db", "survives container restarts"], "store", size=15, subsize=12.5)
    s.arrow([(500, 220), (500, 278)])
    s.box(50, 280, 260, 90, "Your browser", ["localhost:8501 (UI)", "localhost:8000/docs (API)"], "user", size=15, subsize=12.5)
    s.arrow([(180, 280), (180, 222)])
    s.box(700, 60, 280, 330, "GitHub Actions (ci.yml)", ["on push / PR to main", "", "ubuntu-latest", "Python 3.11 (pip cache)", "apt install libmagic1", "pip install -r requirements.txt", "pytest -v  (GROQ_API_KEY=dummy)", "", "Does NOT build an image", "and does NOT deploy"], "infra", size=15, subsize=12.5)
    s.save("d24_docker_ci")


def d25():
    s = SVG(1000, 520)
    s.box(20, 30, 160, 70, "Laptop", ["git push"], "user", num=1)
    s.box(230, 30, 170, 70, "GitHub", ["Tarunvarma07/AnyDoc_chat"], "infra", num=2, subsize=11.5)
    s.arrow([(180, 65), (228, 65)])
    s.box(450, 30, 220, 70, "Render Blueprint", ["reads render.yaml"], "infra", num=3)
    s.arrow([(400, 65), (448, 65)])
    s.box(720, 30, 260, 70, "Docker build ×2", ["same Dockerfile for both services"], "infra", num=4)
    s.arrow([(670, 65), (718, 65)])
    s.box(120, 170, 340, 130, "anydoc-api (free web service)", ["uvicorn ... --port $PORT", "healthCheckPath: /stats", "GROQ_API_KEY: set in dashboard (sync: false)"], "api", num=5, size=15, subsize=12.5)
    s.box(560, 170, 380, 130, "anydoc-ui (free web service)", ["streamlit run app.py --server.port $PORT", "API_URL = https://anydoc-api.onrender.com", "(edit if Render adds a name suffix)"], "user", num=6, size=15, subsize=12.5)
    s.arrow([(850, 100), (850, 130), (290, 130), (290, 168)])
    s.arrow([(850, 130), (750, 130), (750, 168)])
    s.arrow([(560, 235), (462, 235)], label="HTTPS", lx=511, ly=227)
    s.box(560, 340, 380, 70, "Visitor's browser", ["https://anydoc-ui.onrender.com"], "user", num=7)
    s.arrow([(750, 340), (750, 302)])
    s.rect(120, 330, 340, 160, "#FDECEC", "#B83232")
    s.text(290, 356, "Container filesystem (ephemeral)", size=14.5, anchor="middle", weight="700", color="#B83232")
    s.lines(290, 382, ["./chroma_db and the model cache live here", "Lost on redeploy, restart, or spin-down", "(free plan: no persistent disk)", "Idle 15 min → spins down; ~1 min wake-up", "Models re-download on every cold start"], size=12.5, gap=19, anchor="middle", color="#2D3748")
    s.arrow([(290, 300), (290, 328)])
    s.save("d25_render")


def d26():
    s = SVG(1060, 300)
    steps = [("Upload", "user"), ("Validate", "security"), ("Extract", "data"), ("Chunk", "data"), ("Embed + store", "store"),
             ("Ask", "user"), ("Rewrite", "ai"), ("BM25 + dense", "search"), ("RRF", "search"), ("Rerank", "ai"), ("LLM", "ai"), ("Cite check", "security")]
    for i, (t, k) in enumerate(steps):
        row, col = divmod(i, 6)
        x, y = 20 + col * 172, 40 + row * 130
        s.box(x, y, 150, 70, t, [], k, num=i + 1, size=14.5)
        if col:
            s.arrow([(x - 22, y + 35), (x - 2, y + 35)])
    s.arrow([(870, 110), (870, 140), (95, 140), (95, 168)], dash=True, label="questions search what ingestion stored", lx=480, ly=134)
    s.legend(20, 280, ["user", "security", "data", "store", "search", "ai"], cols=6, colw=172)
    s.save("d26_mental_model")


if __name__ == "__main__":
    for fn in [d00, d01, d02, d03, d04, d05, d06, d07, d08, d09, d10, d11, d12, d13, d14, d15, d16, d17, d18, d19, d20, d21, d22, d23, d24, d25, d26]:
        fn()
    print("diagrams written to", ASSETS)
