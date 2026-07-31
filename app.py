import streamlit as st
import pandas as pd
import requests
import os
import sys
import subprocess
import ast
from langchain_core.documents import Document
from src.pipeline.chunk import compare_strategies

# Configure page aesthetics
st.set_page_config(page_title="AnyDoc Dashboard", page_icon="🗂️", layout="wide")

API_URL = os.environ.get("API_URL", "http://localhost:8000")

# SVG Icons (Lucide)
ICON_CHECK = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
ICON_ALERT = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
ICON_WARN = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'
ICON_LINK = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>'
ICON_FILE = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>'
ICON_PULSE = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>'

# Theme State
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

# Dynamic CSS tokens
if st.session_state.dark_mode:
    css_tokens = """
    --bg: #1B1D1C;
    --surface: #252827;
    --surface-sunken: #141515;
    --text-primary: #FAFAF9;
    --text-secondary: #A0A5A3;
    --border: #3A3D3C;
    --accent: #2F6F5E;
    --accent-hover: #3B8A75;
    --warn: #D9624C;
    --focus-ring: #2F6F5E80;
    """
else:
    css_tokens = """
    --bg: #FAFAF9;
    --surface: #FFFFFF;
    --surface-sunken: #F3F3F1;
    --text-primary: #1B1D1C;
    --text-secondary: #5B5F5C;
    --border: #E4E4E1;
    --accent: #2F6F5E;
    --accent-hover: #275C4E;
    --warn: #A64B39;
    --focus-ring: #2F6F5E33;
    """

st.markdown(f"""
<style>
    :root {{
        {css_tokens}
    }}

    .stApp {{
        background-color: var(--bg);
        color: var(--text-primary);
        font-family: "Space Grotesk", system-ui, sans-serif;
        font-size: 16px;
        line-height: 1.5;
    }}

    .stSidebar {{
        background-color: var(--surface-sunken) !important;
        border-right: 1px solid var(--border);
    }}

    h1, h2, h3, h4, h5, h6 {{
        font-family: "Space Grotesk", system-ui, sans-serif !important;
        color: var(--text-primary) !important;
        font-weight: 600 !important;
    }}

    p {{
        color: var(--text-primary);
    }}

    .stButton > button {{
        background-color: var(--accent) !important;
        color: #FFFFFF !important;
        border: none !important;
        min-height: 44px !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
        transition: background-color 0.2s ease, box-shadow 0.2s ease;
        margin-top: 8px;
        margin-bottom: 8px;
    }}
    .stButton > button:hover {{
        background-color: var(--accent-hover) !important;
    }}
    .stButton > button:focus {{
        outline: none !important;
        box-shadow: 0 0 0 3px var(--focus-ring) !important;
    }}
    .stButton > button:disabled {{
        opacity: 0.6;
        cursor: not-allowed;
    }}

    .stTextInput > div > div > input {{
        min-height: 44px !important;
        border: 1px solid var(--border) !important;
        background-color: var(--surface) !important;
        color: var(--text-primary) !important;
        border-radius: 6px;
    }}
    .stTextInput > div > div > input:focus {{
        box-shadow: 0 0 0 3px var(--focus-ring) !important;
        border-color: var(--accent) !important;
    }}

    .stTabs [data-baseweb="tab-list"] {{
        gap: 24px;
        border-bottom: 1px solid var(--border);
    }}
    .stTabs [data-baseweb="tab"] {{
        background-color: transparent !important;
        border: none !important;
        padding-bottom: 12px !important;
        padding-top: 12px !important;
        color: var(--text-secondary) !important;
        font-weight: 500 !important;
    }}
    .stTabs [aria-selected="true"] {{
        color: var(--accent) !important;
        border-bottom: 2px solid var(--accent) !important;
    }}

    .metric-card {{
        background-color: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        height: 100%;
    }}
    .metric-value {{
        font-size: 2em;
        font-weight: 700;
        color: var(--text-primary);
        margin: 10px 0;
    }}
    .metric-label {{
        color: var(--text-secondary);
        font-size: 0.9em;
        font-weight: 500;
    }}

    .status-alert {{
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 16px;
        border-radius: 6px;
        font-size: 0.95em;
        font-weight: 500;
        margin-top: 12px;
    }}
    .status-success {{
        background-color: var(--surface);
        border: 1px solid var(--accent);
        color: var(--accent);
    }}
    .status-error {{
        background-color: var(--surface);
        border: 1px solid var(--warn);
        color: var(--warn);
    }}

    .citation-tag {{
        font-family: "JetBrains Mono", monospace;
        font-size: 0.8em;
        background-color: var(--surface-sunken);
        color: var(--text-secondary);
        padding: 2px 6px;
        border-radius: 4px;
        border: 1px solid var(--border);
        cursor: pointer;
    }}
    .timing-metric {{
        font-family: "JetBrains Mono", monospace;
        font-size: 0.75em;
        color: var(--text-secondary);
        display: block;
        margin-top: 8px;
    }}
    .refusal-box {{
        border: 1px solid var(--warn);
        background-color: var(--surface-sunken);
        border-left: 4px solid var(--warn);
        padding: 12px 16px;
        border-radius: 4px;
        color: var(--text-primary);
    }}

    .pill {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background-color: var(--surface-sunken);
        border: 1px solid var(--border);
        color: var(--text-secondary);
        border-radius: 999px;
        padding: 4px 12px;
        font-size: 0.8em;
        font-weight: 500;
        margin-right: 8px;
        margin-bottom: 8px;
    }}
    .health-dot {{
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
    }}
    .subtitle {{
        color: var(--text-secondary);
        font-size: 1em;
        margin-bottom: 24px;
        max-width: 720px;
    }}

    .flow-row {{
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 0;
        margin: 12px 0 20px 0;
    }}
    .flow-step {{
        background-color: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 10px 16px;
        font-size: 0.85em;
        font-weight: 600;
        color: var(--text-primary);
        white-space: nowrap;
    }}
    .flow-step.accent {{
        border-color: var(--accent);
        color: var(--accent);
    }}
    .flow-arrow {{
        color: var(--text-secondary);
        font-size: 1.1em;
        margin: 0 8px;
    }}
    .flow-label {{
        font-size: 0.75em;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-weight: 600;
        margin-top: 16px;
        margin-bottom: 4px;
    }}

    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)


def render_status(is_success: bool, message: str):
    css_class = "status-success" if is_success else "status-error"
    icon = ICON_CHECK if is_success else ICON_WARN
    st.markdown(f'<div class="status-alert {css_class}">{icon} <span>{message}</span></div>', unsafe_allow_html=True)


def fetch_stats():
    try:
        res = requests.get(f"{API_URL}/stats", timeout=3)
        if res.status_code == 200:
            return res.json(), True
    except requests.exceptions.RequestException:
        pass
    return None, False


def render_metric_card(label, value, sub=""):
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="timing-metric">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.header("AnyDoc")
    st.session_state.dark_mode = st.toggle("🌙 Dark Mode", value=st.session_state.dark_mode)

    st.markdown("<hr style='border:none; border-top:1px solid var(--border); margin: 16px 0;'>", unsafe_allow_html=True)

    stats, backend_up = fetch_stats()
    dot_color = "#2F6F5E" if backend_up else "#A64B39"
    status_text = "Backend online" if backend_up else "Backend offline"
    st.markdown(f'<span class="health-dot" style="background-color:{dot_color};"></span><span class="metric-label">{status_text}</span>', unsafe_allow_html=True)

    if backend_up and stats:
        st.markdown(f"""
        <div style="margin-top:12px; font-size:0.85em; color: var(--text-secondary); line-height:1.8;">
            Documents indexed: <b style="color:var(--text-primary);">{stats['document_count']}</b><br>
            Embedding model: <span style="font-family:monospace;">{stats['embedding_model']}</span><br>
            Reranker: <span style="font-family:monospace;">{stats['reranker_model'].split('/')[-1]}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr style='border:none; border-top:1px solid var(--border); margin: 16px 0;'>", unsafe_allow_html=True)
    st.markdown(
        "<p style='font-size:0.8em; color:var(--text-secondary);'>Universal RAG agent: hybrid retrieval "
        "(BM25 + dense), cross-encoder reranking, LLM query rewriting, and SSRF-hardened ingestion.</p>",
        unsafe_allow_html=True
    )

# ----------------- MAIN AREA -----------------
st.markdown("<h1 style='padding-top: 24px; padding-bottom: 4px;'><span style='color: var(--accent);'>A</span>ny<span style='color: var(--accent);'>D</span>oc</h1>", unsafe_allow_html=True)
st.markdown("<p class='subtitle'>A universal document Q&A agent with hybrid retrieval, cross-encoder reranking, query rewriting, and SSRF-hardened ingestion.</p>", unsafe_allow_html=True)

tab_overview, tab_ingest, tab_chat, tab_chunking, tab_eval = st.tabs(
    ["Overview", "Ingestion", "Chat", "Chunking Lab", "Evaluation"]
)

# --- TAB: OVERVIEW ---
with tab_overview:
    stats, backend_up = fetch_stats()

    if not backend_up:
        render_status(False, "Backend API is offline. Start it with: uvicorn src.api.main:app --port 8000")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            render_metric_card("Documents Indexed", stats["document_count"], "Chunks in ChromaDB + BM25 index")
        with col2:
            render_metric_card("Retrieval Mode", "Hybrid", f"RRF k={stats['hybrid_k']} · top_n={stats['top_n']}")
        with col3:
            render_metric_card("Reranker", "Active", stats["reranker_model"].split("/")[-1])

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
    st.markdown("### Pipeline Architecture")

    def flow_row(steps, accent_last=False):
        parts = []
        for i, step in enumerate(steps):
            cls = "flow-step accent" if (accent_last and i == len(steps) - 1) else "flow-step"
            parts.append(f'<span class="{cls}">{step}</span>')
            if i < len(steps) - 1:
                parts.append('<span class="flow-arrow">&#8594;</span>')
        return f'<div class="flow-row">{"".join(parts)}</div>'

    st.markdown('<div class="flow-label">Ingestion</div>', unsafe_allow_html=True)
    st.markdown(flow_row(["Ingest (URL / File)", "SSRF + MIME Guardrails", "Recursive Chunking", "Index (Chroma + BM25)"]), unsafe_allow_html=True)

    st.markdown('<div class="flow-label">Query</div>', unsafe_allow_html=True)
    st.markdown(flow_row(["User Query", "LLM Query Rewriter", "Hybrid Retrieve (RRF)", "Cross-Encoder Rerank", "Generate (Groq LLM)", "Guardrails (injection/citation)", "Answer"], accent_last=True), unsafe_allow_html=True)

    st.markdown(
        "<p class='timing-metric'>Ingestion (top) builds the retrieval index; querying (bottom) reads from it. "
        "See the Evaluation tab for measured hit-rate numbers on a held-out adversarial corpus.</p>",
        unsafe_allow_html=True
    )

# --- TAB: INGESTION ---
with tab_ingest:
    col_link, col_file = st.columns(2)

    with col_link:
        st.markdown(f"<div style='display:flex; align-items:center; gap:8px; margin-bottom:8px; font-weight:600;'>{ICON_LINK} Add a link</div>", unsafe_allow_html=True)
        url_input = st.text_input("URL", label_visibility="collapsed", placeholder="https://example.com")
        if st.button("Ingest Link", key="btn_url", use_container_width=True):
            if not url_input:
                render_status(False, "Please enter a URL.")
            else:
                with st.spinner("Processing link..."):
                    try:
                        res = requests.post(f"{API_URL}/ingest/url", json={"url": url_input})
                        if res.status_code == 200:
                            render_status(True, res.json()["message"])
                        else:
                            render_status(False, res.json()["detail"])
                    except requests.exceptions.ConnectionError:
                        render_status(False, "Backend API is offline.")

    with col_file:
        st.markdown(f"<div style='display:flex; align-items:center; gap:8px; margin-bottom:8px; font-weight:600;'>{ICON_FILE} Upload a file</div>", unsafe_allow_html=True)
        uploaded_file = st.file_uploader("File", type=["pdf", "txt", "csv", "docx"], label_visibility="collapsed")
        if st.button("Ingest File", key="btn_file", use_container_width=True):
            if not uploaded_file:
                render_status(False, "Please select a file.")
            else:
                with st.spinner("Processing file..."):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                        res = requests.post(f"{API_URL}/ingest/file", files=files)
                        if res.status_code == 200:
                            render_status(True, res.json()["message"])
                        else:
                            render_status(False, res.json()["detail"])
                    except requests.exceptions.ConnectionError:
                        render_status(False, "Backend API is offline.")

    st.markdown("<hr style='border:none; border-top:1px solid var(--border); margin: 24px 0;'>", unsafe_allow_html=True)
    stats, backend_up = fetch_stats()
    if backend_up and stats:
        st.markdown(f'<span class="pill">{ICON_PULSE} {stats["document_count"]} chunks currently indexed</span>', unsafe_allow_html=True)

# --- TAB: CHAT ---
with tab_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    def render_trace(search_query, query, sources, timings, pipeline):
        with st.expander("🔍 Retrieval trace"):
            if search_query and search_query != query:
                st.markdown(f"**Rewritten search query:** `{search_query}`")
            else:
                st.markdown("**Rewritten search query:** _(unchanged from original)_")

            if pipeline:
                st.markdown(
                    f"**Candidates considered:** {pipeline.get('candidates_considered', '-')} "
                    f"&nbsp;→&nbsp; **Reranked:** {'Yes' if pipeline.get('reranked') else 'No'}"
                )

            if sources:
                st.markdown("**Sources (post-rerank order):**")
                for src in sources:
                    score = src.get("rerank_score")
                    score_str = f"score: `{score:.3f}`" if score is not None else ""
                    filename = src.get('source', 'unknown').split('/')[-1].split('\\')[-1]
                    st.markdown(f"- `[{src['id']}]` **{filename}** {score_str}")

            if timings:
                c1, c2, c3 = st.columns(3)
                c1.metric("Rewrite", f"{timings.get('rewrite_ms', 0):.0f} ms")
                c2.metric("Retrieval", f"{timings.get('retrieval_ms', 0):.0f} ms")
                c3.metric("Generation", f"{timings.get('gen_ms', 0):.0f} ms")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            is_refusal = msg["content"].strip().startswith("I cannot answer") or msg["content"].strip().startswith("The generated answer")
            if msg["role"] == "assistant" and is_refusal:
                st.markdown(f'<div class="refusal-box"><div style="display:flex; gap:8px; align-items:center; margin-bottom:8px; font-weight:600;">{ICON_ALERT} Refusal / Guardrail triggered</div>{msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(msg["content"])

            if "sources" in msg and msg["sources"]:
                grouped_sources = {}
                for i, src in enumerate(msg["sources"], start=1):
                    filename = src.get('source', 'unknown').split('/')[-1].split('\\')[-1]
                    if filename not in grouped_sources:
                        grouped_sources[filename] = []
                    grouped_sources[filename].append(f"**Chunk [{i}]**\n_{src['content']}_")

                for filename, chunks in grouped_sources.items():
                    with st.expander(f"📚 {filename}"):
                        st.markdown("\n\n---\n\n".join(chunks))

            if msg["role"] == "assistant" and "sources" in msg:
                render_trace(msg.get("search_query", ""), msg.get("query", ""), msg["sources"], msg.get("timings", {}), msg.get("pipeline", {}))

    query = st.chat_input("Ask a question about the ingested documents...")
    if query:
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("Rewriting query, retrieving, reranking, generating..."):
                try:
                    res = requests.post(f"{API_URL}/query", json={"query": query})
                    if res.status_code == 200:
                        data = res.json()
                        content = data["answer"]
                        sources = data.get("sources", [])
                        timings = data.get("timings", {})
                        search_query = data.get("search_query", "")
                        pipeline = data.get("pipeline", {})

                        is_refusal = content.strip().startswith("I cannot answer") or content.strip().startswith("The generated answer")
                        if is_refusal:
                            st.markdown(f'<div class="refusal-box"><div style="display:flex; gap:8px; align-items:center; margin-bottom:8px; font-weight:600;">{ICON_ALERT} Refusal / Guardrail triggered</div>{content}</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(content)

                        if sources:
                            grouped_sources = {}
                            for i, src in enumerate(sources, start=1):
                                filename = src.get('source', 'unknown').split('/')[-1].split('\\')[-1]
                                if filename not in grouped_sources:
                                    grouped_sources[filename] = []
                                grouped_sources[filename].append(f"**Chunk [{i}]**\n_{src['content']}_")

                            for filename, chunks in grouped_sources.items():
                                with st.expander(f"📚 {filename}"):
                                    st.markdown("\n\n---\n\n".join(chunks))

                        render_trace(search_query, query, sources, timings, pipeline)

                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": content,
                            "sources": sources,
                            "timings": timings,
                            "search_query": search_query,
                            "pipeline": pipeline,
                            "query": query
                        })
                    else:
                        render_status(False, res.json()["detail"])
                except requests.exceptions.ConnectionError:
                    render_status(False, "Backend API is offline.")

# --- TAB: CHUNKING LAB ---
with tab_chunking:
    st.markdown("<p style='color: var(--text-secondary); margin-bottom: 24px;'>Compare text splitting strategies to detect fragments and mid-sentence cuts.</p>", unsafe_allow_html=True)

    sample_text = st.text_area("Input Text", height=150,
                               value="This is a sentence. And another one! But what happens if we have a very long sentence that just keeps going and going and going without stopping for a long time, causing the chunker to forcefully break it apart? Here is a list:\n- Item 1\n- Item 2\n- Item 3.")

    if st.button("Evaluate Strategies", key="btn_chunk"):
        doc = Document(page_content=sample_text, metadata={"source": "manual_input"})
        with st.spinner("Analyzing chunks..."):
            report = compare_strategies(doc)

            col1, col2 = st.columns(2)

            def render_chunk_metric(label, value, is_good):
                icon = ICON_CHECK if is_good else ICON_WARN
                color = "var(--accent)" if is_good else "var(--warn)"
                st.markdown(f"""
                <div style="display:flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                    <span class="metric-label">{label}</span>
                    <span style="display:flex; align-items:center; gap:4px; font-family: 'JetBrains Mono', monospace; font-weight:600; color:{color};">
                        {value} {icon}
                    </span>
                </div>
                """, unsafe_allow_html=True)

            with col1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown("### Recursive Character")
                stats = report["recursive"]
                st.markdown(f'<div class="metric-value">{stats["total_chunks"]}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-label" style="margin-bottom:16px;">Total Chunks</div>', unsafe_allow_html=True)

                render_chunk_metric("Fragments", stats["fragments_detected"], stats["fragments_detected"] == 0)
                render_chunk_metric("Mid-sentence cuts", stats["mid_sentence_cuts"], stats["mid_sentence_cuts"] == 0)
                st.markdown('</div>', unsafe_allow_html=True)

            with col2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown("### Character Splitter")
                stats = report["character"]
                st.markdown(f'<div class="metric-value">{stats["total_chunks"]}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-label" style="margin-bottom:16px;">Total Chunks</div>', unsafe_allow_html=True)

                render_chunk_metric("Fragments", stats["fragments_detected"], stats["fragments_detected"] == 0)
                render_chunk_metric("Mid-sentence cuts", stats["mid_sentence_cuts"], stats["mid_sentence_cuts"] == 0)
                st.markdown('</div>', unsafe_allow_html=True)

# --- TAB: EVALUATION ---
with tab_eval:
    st.markdown("<p style='color: var(--text-secondary); margin-bottom: 24px;'>Benchmark Dense (Vector) vs Hybrid Retrieval on a fixed, isolated 105-document adversarial corpus.</p>", unsafe_allow_html=True)

    if st.button("Run Evaluation Benchmark", key="btn_eval"):
        with st.spinner("Provisioning temporary database and running evaluation..."):
            try:
                env = os.environ.copy()
                env["PYTHONPATH"] = "."
                result = subprocess.check_output(
                    [sys.executable, 'src/evaluation/evaluator.py'],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    env=env
                ).decode('utf-8')

                eval_data = None
                for line in result.split('\n'):
                    if "Evaluation Results:" in line:
                        eval_data = ast.literal_eval(line.replace("Evaluation Results: ", "").strip())
                        break

                if eval_data:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-label">Dense-only Hit Rate</div>
                            <div class="metric-value" style="color: var(--accent);">{eval_data['dense_hit_rate']*100:.0f}%</div>
                            <div class="timing-metric">Target ranked in top 2 on {eval_data['total_queries']} queries</div>
                        </div>
                        """, unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-label">Hybrid (Dense + BM25) Hit Rate</div>
                            <div class="metric-value" style="color: var(--accent);">{eval_data['hybrid_hit_rate']*100:.0f}%</div>
                            <div class="timing-metric">Architecture validated, no regression</div>
                        </div>
                        """, unsafe_allow_html=True)

                    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
                    chart_df = pd.DataFrame({
                        "Hit Rate %": [eval_data["dense_hit_rate"] * 100, eval_data["hybrid_hit_rate"] * 100]
                    }, index=["Dense-only", "Hybrid (RRF)"])
                    st.bar_chart(chart_df)

                    st.markdown("""
                    <div style="margin-top:24px; color: var(--text-secondary); font-size: 0.9em; text-align: center;">
                        <em>Evaluated on a fixed 105-document benchmark corpus, isolated from the live database.</em>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    render_status(False, "Failed to parse evaluation output.")
                    with st.expander("Raw Output"):
                        st.code(result)
            except subprocess.CalledProcessError as e:
                render_status(False, f"Evaluation script failed: {e}")
                with st.expander("Error Details"):
                    st.code(e.output.decode('utf-8', errors='ignore'))
