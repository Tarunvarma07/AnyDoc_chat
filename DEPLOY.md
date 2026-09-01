# Deploying AnyDoc to Render

This repo includes a [`render.yaml`](render.yaml) Blueprint that deploys two services from the same Dockerfile:

- **`anydoc-api`** — the FastAPI backend (`/ingest/url`, `/ingest/file`, `/query`, `/stats`)
- **`anydoc-ui`** — the Streamlit dashboard, configured to call `anydoc-api`

## Steps

1. **Sign up at [render.com](https://render.com)** using "Sign in with GitHub" (recommended, since it's the same account that owns this repo).
2. In the Render dashboard: **New +** → **Blueprint** → select the `AnyDoc_chat` repository. Render will detect `render.yaml` automatically.
3. When prompted for environment variables, enter your **`GROQ_API_KEY`** for the `anydoc-api` service (get one at [console.groq.com](https://console.groq.com) if you don't have one — never commit this key).
4. Click **Apply** and wait for both services to build. The first build installs ChromaDB, LangChain, and fastembed (ONNX runtime, no PyTorch), so expect a few minutes.
5. Once `anydoc-api` is live, check its public URL in the Render dashboard. If it's not exactly `https://anydoc-api.onrender.com` (Render appends a suffix if that name was taken), go to `anydoc-ui` → **Environment** → update `API_URL` to the real URL → **Manual Deploy** to redeploy the UI pointed at the right backend.
6. Open the `anydoc-ui` service's URL, ingest a document, and try a query.

## Known limitations on Render's free tier

- **No persistent disk**: `render.yaml` doesn't attach a disk, so ChromaDB's local storage is wiped on every redeploy or restart. Fine for a live demo where you ingest a doc and try it; not fine for data you need to keep. To fix, add a `disk` block to the `anydoc-api` service in `render.yaml` and upgrade it off the free plan (disks require a paid instance).
- **Cold starts**: free web services spin down after 15 minutes of inactivity. The next request triggers a rebuild-free but still slow cold start, since it re-downloads/loads the embedding model (and the reranker, on first query) — expect the first request after idle to take significantly longer than subsequent ones.
- **Memory (`anydoc-api`)**: originally OOM'd on Render's 512MB free tier (`sentence-transformers` pulls in PyTorch, which alone pushed the process past 512MB before handling a single request). Rewritten onto `fastembed` (ONNX runtime, no PyTorch) for both the embedding model and the cross-encoder reranker. Measured peak RSS in a clean environment matching this repo's `requirements.txt`: ~245MB after loading the embedding model, ~365MB after the reranker also loads on first query — comfortably under 512MB for normal ingest/query traffic.
- **Memory (`anydoc-ui`)**: was crash-looping with repeated OOM restarts. Root cause: the Evaluation tab's "Run Evaluation Benchmark" button spawned a **subprocess that loaded a second, independent copy of the embedding model** directly inside the Streamlit process, on top of Streamlit's own baseline (pandas/pyarrow/Altair). Fixed by moving that computation to a new `POST /evaluate` endpoint on `anydoc-api`, which the UI now calls over HTTP like every other operation, instead of running it locally. Measured separately: embedding the full 105-document benchmark corpus is itself a real ~350MB operation even when reusing an already-loaded model (Chroma's per-call temporary collection appears not to fully release memory between calls) — so the dashboard now shows the last-measured, committed results by default and only calls `/evaluate` live if you explicitly expand "Re-run live" and click through. If `anydoc-api` OOMs specifically while `/evaluate` is running, that's this known cost, not a regression — avoid triggering it repeatedly on the free tier, or upgrade the plan if you need to.
