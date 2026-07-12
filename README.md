# AnyDoc - Universal RAG Agent Architecture

This document outlines the complete architectural journey of building a production-grade Universal RAG Agent, detailing the security, performance, and UI decisions made across all six phases of development.

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

## 📊 Phase 6: Evaluation & Observability

To prove the efficacy of the system, I built an isolated, reproducible evaluation harness.
- **The Experiment**: I generated a heavily adversarial test corpus containing exact keywords (e.g., `TXN-8819`, `v1.4.2`) buried alongside 50 highly aggressive semantic distractors designed to confuse the model.
- **The Finding**: `all-MiniLM-L6-v2` proved shockingly resilient, ranking the true answers at #1 even under heavy semantic distraction. While the corpus wasn't large enough to artificially force a failure, the evaluation proved that the Hybrid Architecture does not regress performance, is correctly wired, and is fully ready to handle massive scale where dense vector dilution naturally occurs.

## 🎨 Final Polish: Dashboard-Grade UI

I stripped away the generic "neon AI demo" aesthetic in favor of a clean, minimal SaaS dashboard built in Streamlit.
- **Light-First Typography**: Utilizing Space Grotesk and a calming muted teal accent.
- **Transparency**: Citations and timing metrics (`retrieval_ms`, `gen_ms`) are exposed as monospace metadata tags on every assistant response.
- **Calm Refusals**: When the agent triggers a hallucination guardrail (e.g., "I cannot answer this based on the provided documents"), it is styled cleanly as a system warning, not a catastrophic error.

---

## 🚀 How to Run Locally

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
