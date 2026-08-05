# AnyDoc - Universal RAG Agent Architecture

This document outlines the complete architectural journey of building a production-grade Universal RAG Agent, detailing the security, performance, and UI decisions made across development.

A short technical report (architecture, evaluation methodology/results, related work) is available at [`docs/AnyDoc_Technical_Report.pdf`](docs/AnyDoc_Technical_Report.pdf).

Want a live deployment instead of running locally? See [`DEPLOY.md`](DEPLOY.md) for a Render Blueprint that deploys both services from the existing Dockerfile.

## 🏗️ Phase 1 & 2: Base Infrastructure & Chunking

I began by establishing a robust document ingestion pipeline capable of parsing PDFs, TXT, CSV, and DOCX files. 
- **Chunking Strategy**: Rather than relying on simple character splits which often result in mid-sentence cuts and orphaned fragments, I implemented `RecursiveCharacterTextSplitter`.
- **Validation**: I built a visual comparison tool (available in the Chunking Analysis tab) to prove that my recursive strategy drastically reduces fragments and preserves semantic boundaries compared to naive splitting.

## 🛡️ Phase 3 & 4: Security & SSRF Protection

A major architectural focus was securing the web crawler. Naive web ingestors are highly vulnerable to Server-Side Request Forgery (SSRF).
- **Guardrails**: I built a custom DNS resolution and IP validation layer.
- **Fail-Close Architecture**: The system proactively blocks private IPs (10.x.x.x, 127.x.x.x, 192.168.x.x), AWS metadata endpoints (169.254.169.254), and prevents redirects from traversing back into internal networks (`resolve_safe_url`).

> [!WARNING]
> Security in RAG isn't just about prompt injection. If your agent can scrape URLs, it is a vector for SSRF. My explicit IP resolution prevents the agent from being weaponized against internal infrastructure.

## 🧠 Phase 5: Hybrid Search & Index Consistency

Dense vector embeddings (like `all-MiniLM-L6-v2`) are powerful but can struggle with exact keyword matching at scale. 
- **Dual-Engine Retrieval**: I implemented a Hybrid Search architecture, pairing ChromaDB (Semantic/Dense) with a local BM25 index (Keyword/Sparse).
- **Reciprocal Rank Fusion (RRF)**: To combine these distinct scoring systems, I implemented RRF, which normalizes ranks and pushes the most universally relevant documents to the top.
- **Observer Pattern**: A subtle but critical bug in many RAG systems is state drift. I implemented an Observer pattern so that anytime a new document is added to ChromaDB, the BM25 index is automatically invalidated and rebuilt, ensuring the two engines never go out of sync.
- **Cross-Encoder Reranking**: Hybrid fusion widens recall but doesn't jointly score (query, document) pairs. When a `Reranker` is attached (`src/retrieval/reranker.py`), the retriever pulls a 3x wider RRF-fused candidate pool and re-scores it with a `ms-marco-MiniLM-L-6-v2` cross-encoder before returning the final top-N — trading a small amount of latency for materially better precision on the final cut. The model loads lazily on first query, so it never slows down app startup. Runs on [fastembed](https://github.com/qdrant/fastembed)'s ONNX runtime rather than sentence-transformers/PyTorch - see [Deployment & Memory Footprint](#-deployment--memory-footprint) below for why.
- **Query Rewriting**: Before retrieval, `QueryRewriter` (`src/retrieval/query_rewriter.py`) asks the LLM to rewrite the user's raw question into a keyword-enriched search query — resolving vague references and surfacing likely synonyms/technical variants — while the *original* question is still what's used for answer generation and citation. If rewriting fails or the input trips the prompt-injection guardrail, it falls back to the original query untouched.

## 📊 Phase 6: Evaluation & Observability

To prove the efficacy of the system, I built an isolated, reproducible evaluation harness (`src/evaluation/evaluator.py`).
- **The Experiment**: A heavily adversarial 105-document test corpus containing 8 exact-match "needle" facts (transaction IDs, error codes, version numbers, ticket numbers, config values) buried alongside 90 aggressive semantic distractors designed to confuse dense-only retrieval.
- **The Result** (reproducible via `python src/evaluation/evaluator.py`):

  | Retrieval Mode | Hit Rate | Notes |
  |---|---|---|
  | Dense-only (vector search) | 8/8 (100%) | Target ranked #1 or #2 on every query |
  | Hybrid (Dense + BM25, RRF-fused) | 8/8 (100%) | No regression vs. dense-only |

  At this corpus size, `all-MiniLM-L6-v2` alone is already strong enough that both modes saturate — which is itself the useful finding: the evaluation proves the Hybrid architecture is correctly wired and introduces zero regression versus dense-only, and is positioned to pay off at larger scale, where dense vector dilution and exact-match misses (IDs, codes, version strings) become more common. The harness is intentionally corpus-swappable, so this is the first thing to scale up if extending this project further.

## 🎨 Final Polish: Dashboard-Grade UI

I stripped away the generic "neon AI demo" aesthetic in favor of a clean, minimal SaaS dashboard built in Streamlit.
- **Light-First Typography**: Utilizing Space Grotesk and a calming muted teal accent.
- **Transparency**: Citations and timing metrics (`retrieval_ms`, `gen_ms`) are exposed as monospace metadata tags on every assistant response.
- **Calm Refusals**: When the agent triggers a hallucination guardrail (e.g., "I cannot answer this based on the provided documents"), it is styled cleanly as a system warning, not a catastrophic error.

## 🐳 Containerization & CI

- **Docker**: `Dockerfile` builds a single image (FastAPI backend + Streamlit UI share the same image, differing only in the container `command`). `docker-compose.yml` runs both services together, wires the UI to the API over the Docker network (`API_URL=http://api:8000`), and persists the Chroma index in a named volume. `.dockerignore` explicitly excludes `.env`, `venv/`, and `chroma_db/` so secrets and local state never end up baked into an image layer.
- **CI**: `.github/workflows/ci.yml` runs the full `pytest` suite on every push/PR to `main` (Ubuntu, Python 3.11, with `libmagic1` installed for the file-validation guardrail tests).

## 🧮 Deployment & Memory Footprint

Deploying `anydoc-api` to Render's free tier (512MB RAM) initially OOM-crashed on every deploy, before handling a single request. Root cause: `sentence-transformers` pulls in PyTorch as a dependency, and PyTorch's baseline memory footprint (C++ runtime, tensor allocator, etc.) alone was enough to exceed the limit once combined with FastAPI, ChromaDB, and the rest of the app.

Fix: both the embedding model and the cross-encoder reranker were moved onto [fastembed](https://github.com/qdrant/fastembed) (Qdrant's ONNX-runtime-based library) instead of sentence-transformers/PyTorch - same underlying model weights (`sentence-transformers/all-MiniLM-L6-v2` for embeddings, an ONNX export of `cross-encoder/ms-marco-MiniLM-L-6-v2` for reranking via `langchain_community.embeddings.FastEmbedEmbeddings` and `fastembed.rerank.cross_encoder.TextCrossEncoder`), just without the multi-hundred-MB PyTorch runtime.

**Measured peak RSS** in a clean environment matching `requirements.txt` (not the contaminated local dev venv - see below):

| Stage | RSS |
|---|---|
| After all imports (FastAPI, ChromaDB, LangChain, fastembed) | ~88 MB |
| After the embedding model loads | ~241 MB |
| After the reranker also loads (first query) | ~364 MB |

Comfortably under 512MB with headroom for request handling.

One debugging note worth documenting: an early full-app measurement showed ~718MB - alarming, and wrong. `langchain-groq` and `langchain-text-splitters` were transitively importing PyTorch/`transformers`/`sentence-transformers` from *leftover packages still installed in the local dev venv* from before this migration, even though no code imports them anymore. A clean venv built strictly from `requirements.txt` (which no longer lists any of those three) never installs them in the first place, so the transitive import can't happen - matching what Render's Docker build actually does. Lesson: when profiling memory/dependencies, profile a clean install, not a dev environment that's accumulated packages over time.

---

## 🚀 How to Run Locally

### Option A: Docker Compose (recommended)

```bash
git clone https://github.com/Tarunvarma07/AnyDoc_chat.git
cd AnyDoc_chat
cp .env.example .env   # then add your GROQ_API_KEY
docker compose up --build
```

Backend: `http://localhost:8000` · Dashboard: `http://localhost:8501`

### Option B: Run directly

To run the AnyDoc Universal RAG Agent on your own machine:

1. **Clone the repository**
   ```bash
   git clone https://github.com/Tarunvarma07/AnyDoc_chat.git
   cd AnyDoc_chat
   ```

2. **Set up your environment**
   ```bash
   # Create a virtual environment
   python -m venv venv
   
   # Activate it (Windows)
   .\venv\Scripts\activate
   # Activate it (Mac/Linux)
   # source venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

3. **Configure API Keys**
   - Rename `.env.example` to `.env`
   - Add your Groq API key: `GROQ_API_KEY=your_key_here`

4. **Boot the Backend & Frontend**
   Open two separate terminal windows (ensure your virtual environment is active in both).
   
   *Terminal 1 (FastAPI Backend):*
   ```bash
   # Add project root to Python path and start the server
   $env:PYTHONPATH="."
   python -m uvicorn src.api.main:app --port 8000
   ```
   
   *Terminal 2 (Streamlit UI):*
   ```bash
   $env:PYTHONPATH="."
   streamlit run app.py --server.port 8501
   ```

5. **Access the Dashboard**
   Navigate to `http://localhost:8501` in your browser.
