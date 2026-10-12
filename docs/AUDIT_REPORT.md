# AnyDoc — Code Audit, Fixes, and Verification Report

Audit of commit `3e8621c` (branch `main`) on Windows 11, Python 3.11.9, using the
existing `venv` (verified identical to `requirements.txt`, no PyTorch installed).

**Ground rules followed:** no live Groq calls were made (the repository owner declined
live testing; every run used a dummy key that overrides `.env`, so Groq requests were
rejected with 401 and fallbacks were exercised). Nothing was committed or pushed. SSRF
and redirect tests used mocks and local loopback servers only.

## A. Executive summary

The architecture described in the README is real: FastAPI + Streamlit, PDF/DOCX/TXT/CSV
and URL ingestion, recursive chunking, fastembed MiniLM embeddings in ChromaDB, BM25,
RRF fusion, ONNX cross-encoder reranking, LLM query rewriting, regex guardrails and
citation-index validation. The original 25 tests passed.

The audit found **one demo-breaking UI crash**, **four SSRF/file-handling security gaps**,
**a BM25 tokenizer bug that defeated exact-identifier matching**, and a set of input-handling
defects (HTTP 500s, misleading "0 chunks ingested" successes, duplicate chunks on
re-upload). All of these were fixed with small changes and covered by 23 new regression
tests plus one extended test; 20 of those 24 fail on the original code and all pass on the fixed code.
Test suite: **25 passed → 50 passed**. The original benchmark is unchanged (8/8 for both modes).

Not fixed, documented instead: DNS-rebinding TOCTOU, indirect prompt injection through
retrieved documents, index-only citation validation, no auth/rate limiting, and no OCR.
LLM output quality (answers, refusals, rewriting) is **unverified live**.

## B. Actual architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for diagrams, the upload→storage and
question→answer traces, and every parameter with its source location.

## C. Feature inventory

| Feature | Status | Evidence |
|---|---|---|
| PDF ingestion (text layer, per-page metadata) | Works | functional run; `test_query_returns_cited_sources_with_page_numbers` |
| Scanned/image-only PDF | Not supported (no OCR); now a clear 422 | `test_text_free_files_are_rejected_not_reported_as_success` |
| DOCX, TXT, CSV ingestion | Works (CSV = one document per row) | functional run, process smoke test |
| Non-UTF-8 TXT/CSV | Works after fix (Latin-1 fallback) | `test_txt_with_non_utf8_bytes_loads` |
| URL ingestion | Single page + ≤5 same-host links, static HTML, robots.txt | code trace; not a crawler |
| JS-rendered pages | Not supported | code trace (requests + BeautifulSoup) |
| SSRF protection | Works for schemes, private/loopback/link-local/CGNAT/IPv6, all resolved addresses, redirect hops, robots.txt | tests in `test_guardrails.py`, `test_ingestion.py` |
| DNS-rebinding protection | Missing | code trace |
| File validation (size, magic bytes, content↔extension) | Works | `test_guardrails.py`, `test_api.py` |
| Hybrid retrieval (dense + BM25 + RRF) | Works | `test_hybrid_search.py`, demo eval |
| Cross-encoder reranking | Works | demo eval (Hit@1 1.00 on demo set) |
| Query rewriting | Wired with fallback; output quality unverified live | `test_query_rewriter.py` (mocked) |
| Metadata extraction | Wired, one call per file; unverified live; not used by retrieval | `test_generation.py` (mocked) |
| Answer generation + citations | Wired; unverified live | `test_qa_chain_refusals` (mocked) |
| Prompt-injection guardrail | Regex on query + metadata preview only | `test_generation.py` |
| Citation validation | Index range only | `test_verify_citations` |
| Persistence across restart | Works (10 → 10 chunks) | process smoke test |
| Graceful shutdown | Works (uvicorn "Application shutdown complete", Streamlit exit 0) | process smoke test |
| Streamlit UI ↔ API | Works (all tabs; Chunking Lab after fix) | browser check, `test_ui.py` |
| `/evaluate` benchmark | Works (8/8, 8/8) | run before and after |
| Docker / Compose | Present; **not verified** (Docker Desktop not running) | — |
| CI (GitHub Actions) | Present; not run (no push) | — |

## D. Issues found and fixes made

Severity: P0 critical, P1 security/broken core workflow, P2 correctness/reliability, P3 cosmetic/docs.
No P0 issues were found.

| ID | Pri | Finding | Evidence | Fix |
|---|---|---|---|---|
| 1 | P1 | **Chunking Lab crashed** on its only button: `KeyError: 'total_chunks'` — the UI read keys that `compare_strategies()` never returns | Streamlit `AppTest` traceback at `app.py:580` | Use the real keys (`count`, `fragment_count`, `no_terminal_punct_count`) and honest labels |
| 2 | P1 | **Upload path traversal**: the client filename was embedded in the temp-file suffix (`suffix=f"_{file.filename}"`). On Windows, `x/../../../escaped.txt` created the file two directories above the temp dir (Windows normalizes `..` lexically; on Linux the bogus parent component makes it fail instead) | reproduced with `tempfile` exactly as `main.py` used it | Temp suffix is only the sanitized lowercase extension; stored `source` is the basename |
| 3 | P1 | **SSRF: shared address space not blocked** — `is_private` is False for 100.64.0.0/10, so `http://100.100.100.200/` (Alibaba Cloud metadata) passed `validate_url` | direct call returned `True` | Block every non-`is_global` address (plus multicast) |
| 4 | P1 | **SSRF: only the first IPv4 address was checked** (`gethostbyname`). A host with a public A record and a loopback AAAA record passed | mocked `getaddrinfo` → passed | Check every address from `getaddrinfo` (IPv4 + IPv6) |
| 5 | P1 | **SSRF via robots.txt**: `RobotFileParser.read()` uses urllib, which follows redirects without validation, so a public site could make the server GET an internal URL (blind SSRF). It also mutated the process-wide socket timeout from request threads | local redirector server: internal server received `GET /internal-admin/secret` | Fetch robots.txt through `resolve_safe_url` + `requests` with a per-request timeout; same status semantics as `read()` |
| 6 | P2 | **BM25 tokenizer kept punctuation**: `"ZX-4480?"` never matched `"zx-4480"` — the exact-ID case BM25 exists for | demo eval: BM25 missed 2/4 exact-keyword queries | Regex tokenizer keeping `-`/`.` inside identifiers. BM25 Hit@3 0.83→1.00, MRR 0.68→0.89; hybrid MRR 0.90→0.92; 105-doc benchmark unchanged |
| 7 | P2 | **Re-uploading a file duplicated every chunk** (random IDs), crowding top-k with copies and double-counting them in RRF | functional run: +1 chunk on re-ingest | Deterministic `sha256(source, chunk_index, text)` IDs; LangChain's Chroma wrapper upserts |
| 8 | P2 | **Spoofed extensions with an allowed MIME type**: a PDF renamed `.txt` was ingested as raw PDF syntax (4 garbage chunks); text renamed `.pdf` → HTTP 500 | functional run | MIME must match the extension (`EXTENSION_MIME_TYPES`) → 400 |
| 9 | P2 | Allowed MIME with unsupported extension (`.md`) → unhandled `ValueError` → 500 | functional run | Rejected in `validate_file` → 400 |
| 10 | P2 | Loader failures (non-UTF-8 TXT, malformed PDF) → 500 | functional run | UTF-8 → Latin-1 fallback for TXT/CSV; other loader errors → 422 with a stable message, details logged server-side |
| 11 | P2 | Scanned PDFs and whitespace-only files returned **200 "Successfully ingested 0 chunks"** (and still paid for an LLM metadata call) | functional run | 422 "No extractable text… OCR is not implemented", checked before the LLM call |
| 12 | P2 | Blank query ran the whole pipeline; no length limit | functional run | Pydantic `min_length=1`, `max_length=2000`, not-blank validator → 422 |
| 13 | P2 | Injection regex `bypass` refused ordinary questions ("How do I bypass the cache?") | functional run | Narrowed to "bypass … security/safety/filter/rules/…" |
| 14 | P2 | `WebBaseLoader` defaults to `raise_for_status=False`, so 404/500 pages were indexed | library signature | `raise_for_status=True` |
| 15 | P2 | Upload read fully into memory before the size check | code trace | Read at most 10 MB + 1 byte (note: Starlette still spools the full body to disk first; cap request size at a proxy for real DoS protection) |
| 16 | P2 | BM25 `docs` and `bm25` were replaced separately; a query concurrent with an ingest could pair new docs with old scores, and two concurrent rebuilds could finish out of order, publishing the older (incomplete) index | code trace (not reproduced under load) | Single `_snapshot` tuple read once per query; rebuilds serialized with a lock |
| 17 | P2 | `CSVLoader` used the OS default encoding (cp1252 on Windows, UTF-8 on Linux) | library signature | Explicit UTF-8 (BOM-stripped) with Latin-1 fallback |
| 18 | P3 | LLM text was interpolated unescaped into an `unsafe_allow_html` refusal box (HTML injection via a document-influenced answer) | code trace | `html.escape` |
| 19 | P3 | Guardrail refusals ("I cannot fulfill…") not styled as refusals | code trace | Shared `REFUSAL_PREFIXES` |
| 20 | P3 | `/stats` hard-coded `reranker_enabled: True`; source excerpts always ended in "..." ; no page numbers | code trace | Real value; ellipsis only when truncated; `page` (1-based) in sources and UI |
| 21 | P3 | README mismatches: "web crawler" (it is depth-1, ≤5 links), "Chunking Analysis tab" (crashed), SSRF list incomplete, "production-grade" | code trace | README corrected and linked to these docs |
| 23 | P3 | Chunking Lab rendered empty boxes (HTML card split across calls) and, at the fixed 500-char size, showed 1 chunk for both strategies on the sample text | user screenshot | One HTML block per card; chunk-size slider; "largest chunk vs limit" row (the character splitter can't split text without blank lines) |
| 24 | P2 | Generation failures showed only "An error occurred", hiding the cause | user report | `describe_llm_error` appends a safe reason; verified against a real Groq 401 |
| 22 | P3 | robots.txt comment said "if we can't read it, we assume we can fetch"; actual behaviour is fail-closed (`can_fetch` is False until read) | CPython `RobotFileParser.can_fetch` source | Comment corrected; fail-closed behaviour kept |

### Not fixed (documented, with the smallest appropriate fix)

| Pri | Issue | Exploit / impact | Proposed fix |
|---|---|---|---|
| P1 | DNS rebinding (validate-then-connect TOCTOU) | Attacker DNS answers public for the check, internal for the connection | Pin the validated IP in the HTTP connection, or force egress through a filtering proxy |
| P1 | Indirect prompt injection: retrieved chunks are not screened and the prompt does not mark them as untrusted | A document can instruct the model (`samples/injected_note.txt`) | Delimit context as data, instruct the model to ignore instructions inside it, screen chunks, evaluate with an injection set. **Not changed** because a prompt change can't be validated without live LLM runs |
| P2 | Citation validation checks index range only | Wrong-but-cited or uncited claims pass | Entailment/quote check per cited sentence |
| P2 | No auth, rate limiting or tenant isolation; `/evaluate` is expensive and public | Anyone can read/poison the shared corpus or exhaust memory | API keys/OAuth, per-tenant collections, rate limits, disable `/evaluate` in production |
| P2 | Groq failure returns HTTP 200 with an error sentence (it now names the cause: rejected key, unavailable model, rate limit, unreachable) | Clients can't distinguish failure from an answer by status code | 502/503 with a typed error |
| P2 | Changed file re-upload leaves stale chunks | Old and new versions both retrievable | Delete by `source` before upsert |
| P3 | No OCR, no table/layout extraction, no JS rendering, no boilerplate removal, no web response size cap | Coverage gaps | OCR (Tesseract/cloud) only if scanned docs are in scope; Playwright for JS; trafilatura for boilerplate |
| P3 | Models cached in the OS temp dir; first start needs internet | Surprise re-download | Set `FASTEMBED_CACHE_PATH` or bake into the Docker image |
| P3 | `langchain-community` and its `Chroma` class are deprecated (warnings) | Future breakage | Migrate to `langchain-chroma` |
| P3 | "Space Grotesk" font referenced but never loaded; app logging not configured | Cosmetic / observability | Load the font; `logging.basicConfig` |

## E. Tests run and actual results

| Run | Command | Result |
|---|---|---|
| Baseline suite | `pytest -v` (dummy key) | **25 passed**, 0 failed, 0 skipped, 2 warnings, 9.24 s |
| Final suite | `pytest -v` (dummy key) | **50 passed**, 0 failed, 0 skipped, 3 warnings, ~20 s |
| New tests vs original code | same tests in a temporary worktree of `HEAD` | 20 of 24 new/extended tests fail on the original (the 4 that pass guard behaviour that was already correct) |
| 105-doc benchmark | `python src/evaluation/evaluator.py` | before: dense 1.0, hybrid 1.0 (every target rank 1) — after: identical |
| Demo retrieval eval | `python src/evaluation/demo_retrieval_eval.py` | see table below |
| Functional matrix | 35 API calls via TestClient, before vs after | all intended changes observed; no regressions in the 4 file types, URL rejections or retrieval |
| Process smoke test | real uvicorn + Streamlit processes | API ready 9.1 s; ingest 4/1/1/4 chunks; spoofed file 400; scanned PDF 422; top source `acme_handbook.pdf` p. 3; Ctrl+Break graceful shutdown; restart persisted 10→10 chunks; Streamlit healthy 3.0 s, exit 0 |
| Browser check | built-in browser against the running UI | backend online, chat shows cited chunk with page, retrieval trace, Chunking Lab renders |

Warnings are deprecation notices from `langchain-community` and its `Chroma` class.

**Demo retrieval eval** (10 chunks; 12 answerable queries; k = 5; no query rewriting):

| Mode | Hit@1 | Hit@3 | Hit@5 | MRR@5 |
|---|---|---|---|---|
| dense | 0.75 | 1.00 | 1.00 | 0.88 |
| bm25 (before tokenizer fix) | 0.58 | 0.83 | 0.83 | 0.68 |
| bm25 (after) | 0.83 | 1.00 | 1.00 | 0.89 |
| hybrid RRF (before) | 0.83 | 0.92 | 1.00 | 0.90 |
| hybrid RRF (after) | 0.83 | 1.00 | 1.00 | 0.92 |
| hybrid + rerank | 1.00 | 1.00 | 1.00 | 1.00 |

No-answer queries: top rerank score −10.97 to −11.26 vs a minimum of −8.85 for answerable
ones. The set is far too small to choose a refusal threshold, so none was implemented.
These numbers are a wiring check on known cases, not evidence about performance at scale,
and nothing here measures answer correctness or hallucination rates.

## F. Demo readiness and blockers

Ready to demo from the local venv; runbook in [`DEMO.md`](DEMO.md).

Blockers to clear before the interview (owner action):
1. Run the live smoke test (DEMO.md §3) to confirm the Groq key, quota, and that
   `llama-3.1-8b-instant` is still served.
2. Start the backend once on the day so model weights are cached (needs internet).
3. Decide whether to commit these changes (nothing has been committed or pushed).

## G. Remaining risks and limitations

See "Not fixed" above and `ARCHITECTURE.md` §9. The biggest risks in a live
demo are the LLM provider (key, quota, model availability) and questions about
indirect prompt injection and citation faithfulness, which are known limitations.

## H. Interview guide

Kept outside version control at `interview_prep/INTERVIEW_GUIDE.md`
(excluded via `.git/info/exclude`).

## I. Commands

See [`DEMO.md`](DEMO.md) §0–§6.

## Files changed in this audit

Modified: `app.py`, `README.md`, `src/api/main.py`, `src/generation/guardrails.py`,
`src/ingestion/file_reader.py`, `src/ingestion/guardrails.py`,
`src/ingestion/link_reader.py`, `src/pipeline/embed_store.py`,
`src/retrieval/hybrid_search.py`, `tests/test_generation.py`, `tests/test_guardrails.py`,
`tests/test_hybrid_search.py`.

New: `docs/ARCHITECTURE.md`, `docs/DEMO.md`, `docs/AUDIT_REPORT.md`,
`samples/*` (synthetic files + generator + eval set), `src/evaluation/demo_retrieval_eval.py`,
`tests/test_api.py`, `tests/test_ingestion.py`, `tests/test_ui.py`.
No dependencies added. No secrets in any file.
