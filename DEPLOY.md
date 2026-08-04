# Deploying AnyDoc to Render

This repo includes a [`render.yaml`](render.yaml) Blueprint that deploys two services from the same Dockerfile:

- **`anydoc-api`** — the FastAPI backend (`/ingest/url`, `/ingest/file`, `/query`, `/stats`)
- **`anydoc-ui`** — the Streamlit dashboard, configured to call `anydoc-api`

## Steps

1. **Sign up at [render.com](https://render.com)** using "Sign in with GitHub" (recommended, since it's the same account that owns this repo).
2. In the Render dashboard: **New +** → **Blueprint** → select the `AnyDoc_chat` repository. Render will detect `render.yaml` automatically.
3. When prompted for environment variables, enter your **`GROQ_API_KEY`** for the `anydoc-api` service (get one at [console.groq.com](https://console.groq.com) if you don't have one — never commit this key).
4. Click **Apply** and wait for both services to build. The first build installs PyTorch, sentence-transformers, and ChromaDB, so expect ~5-10 minutes.
5. Once `anydoc-api` is live, check its public URL in the Render dashboard. If it's not exactly `https://anydoc-api.onrender.com` (Render appends a suffix if that name was taken), go to `anydoc-ui` → **Environment** → update `API_URL` to the real URL → **Manual Deploy** to redeploy the UI pointed at the right backend.
6. Open the `anydoc-ui` service's URL, ingest a document, and try a query.

## Known limitations on Render's free tier

- **No persistent disk**: `render.yaml` doesn't attach a disk, so ChromaDB's local storage is wiped on every redeploy or restart. Fine for a live demo where you ingest a doc and try it; not fine for data you need to keep. To fix, add a `disk` block to the `anydoc-api` service in `render.yaml` and upgrade it off the free plan (disks require a paid instance).
- **Cold starts**: free web services spin down after 15 minutes of inactivity. The next request triggers a rebuild-free but still slow cold start, since it re-downloads/loads the embedding model (and the reranker, on first query) — expect the first request after idle to take significantly longer than subsequent ones.
- **Memory risk**: free instances have 512MB RAM. PyTorch + sentence-transformers + the cross-encoder reranker can get close to that ceiling, especially once the reranker loads on first query. If `anydoc-api` crashes with an OOM, upgrade it to the Starter plan (more RAM) in the Render dashboard — no code changes needed.
