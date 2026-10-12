"""
Computes the worked examples used in the visual guide by running AnyDoc's own
components (tokenizer, BM25, embeddings, Chroma, reranker, chunker) on small
synthetic inputs. No LLM calls. Output: docs/guide_assets/examples.json

    python docs/guide_src/compute_examples.py
"""
import json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("GROQ_API_KEY", "not-used-offline")
import logging; logging.disable(logging.WARNING)
import numpy as np
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
from src.pipeline.chunk import Chunker
from src.pipeline.embed_store import EmbedStore
from src.retrieval.hybrid_search import HybridRetriever
from src.retrieval.reranker import Reranker
from src.ingestion.file_reader import FileReader

out = {}
tmp = tempfile.mkdtemp()
store = EmbedStore(persist_directory=os.path.join(tmp, "a"), collection_name="guide_examples")
emb = store.embeddings
cos = lambda a, b: float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

# 1. Embedding similarity
sents = ["The dog is playing outside", "A puppy is running outdoors", "The quarterly invoice is overdue"]
vecs = [np.array(emb.embed_query(s)) for s in sents]
out["embedding"] = {"dims": len(vecs[0]), "norm": round(float(np.linalg.norm(vecs[0])), 4),
                    "first5": [round(x, 4) for x in vecs[0][:5]], "sentences": sents,
                    "cosine": [[round(cos(a, b), 3) for b in vecs] for a in vecs]}

# 2. BM25 vs dense on the E1042 corpus
corpus = {"A": "The payment gateway returned error code E1042.",
          "B": "The checkout process failed because the bank service was unavailable.",
          "C": "The employee leave policy allows 18 annual leave days."}
q = "What happened to payment error E1042?"
hr = HybridRetriever.__new__(HybridRetriever)
toks = {k: hr._tokenize(v) for k, v in corpus.items()}
bm25 = BM25Okapi(list(toks.values()))
scores = bm25.get_scores(hr._tokenize(q))
qv = np.array(emb.embed_query(q))
dense = {k: cos(qv, np.array(emb.embed_query(v))) for k, v in corpus.items()}
out["bm25_vs_dense"] = {"query": q, "query_tokens": hr._tokenize(q), "corpus": corpus, "doc_tokens": toks,
                        "bm25": {k: round(float(s), 3) for k, s in zip(corpus, scores)},
                        "idf": {t: round(float(bm25.idf.get(t, 0)), 3) for t in hr._tokenize(q)},
                        "dense_cosine": {k: round(v, 3) for k, v in dense.items()},
                        "old_whitespace_tokens": q.lower().split()}

# 3. Chunk overlap on a real splitter run (small size so the overlap is visible)
text = ("Employees may work remotely up to three days per week. Remote work must be approved by a direct manager. "
        "Full-time staff receive 24 days of paid annual leave per year. Unused leave can be carried over until March.")
for size, ov in [(120, 30)]:
    ch = Chunker(strategy="recursive", chunk_size=size, chunk_overlap=ov).split_documents([Document(page_content=text)])
    out["chunking"] = {"text": text, "chunk_size": size, "overlap": ov, "chunks": [c.page_content for c in ch]}
prod = Chunker(strategy="recursive").split_documents([Document(page_content=text * 4)])
out["chunking"]["prod_500_50_lengths"] = [len(c.page_content) for c in prod]

# 4. Real ingestion of the sample PDF -> one Chroma record
docs = FileReader().load(os.path.join(ROOT, "samples", "acme_handbook.pdf"))
for d in docs: d.metadata["source"] = "acme_handbook.pdf"
t0 = time.perf_counter(); chunks = Chunker(strategy="recursive").split_documents(docs); t_chunk = time.perf_counter() - t0
t0 = time.perf_counter(); store.add_documents(chunks); t_embed = time.perf_counter() - t0
raw = store.vector_store._collection.get(include=["documents", "metadatas", "embeddings"], limit=10)
i = next(j for j, m in enumerate(raw["metadatas"]) if m.get("page") == 2)
out["chroma_record"] = {"id": raw["ids"][i], "document": raw["documents"][i], "metadata": raw["metadatas"][i],
                        "embedding_first4": [round(float(x), 4) for x in raw["embeddings"][i][:4]],
                        "embedding_len": len(raw["embeddings"][i]), "pages_loaded": len(docs), "chunks": len(chunks)}

# 5. Hybrid vs reranked order on the sample corpus, plus offline timings
for name in ["travel_policy.docx", "release_notes.txt", "inventory.csv"]:
    d2 = FileReader().load(os.path.join(ROOT, "samples", name))
    for d in d2: d.metadata["source"] = name
    store.add_documents(Chunker(strategy="recursive").split_documents(d2))
rr = Reranker()
plain = HybridRetriever(embed_store=store, top_n=5)
reranked = HybridRetriever(embed_store=store, top_n=5, reranker=rr)
rq = "What is the nightly accommodation allowance on business trips?"
reranked.get_relevant_documents(rq)  # warm-up (loads cross-encoder)
def label(d):
    p = d.metadata.get("page"); return d.metadata["source"] + (f" p.{p+1}" if isinstance(p, int) else "") + f" | {d.page_content[:60]}"
before = [label(d) for d in plain.get_relevant_documents(rq)]
after = [(label(d), round(d.metadata["rerank_score"], 2)) for d in reranked.get_relevant_documents(rq)]
out["rerank"] = {"query": rq, "hybrid_order": before, "reranked_order": after}

def timeit(fn, n=20):
    fn(); t0 = time.perf_counter()
    for _ in range(n): fn()
    return round((time.perf_counter() - t0) / n * 1000, 1)
out["timings_ms"] = {
    "corpus_chunks": len(store.get_all_documents()),
    "embed_one_query": timeit(lambda: emb.embed_query(rq)),
    "dense_top15": timeit(lambda: store.as_retriever(search_kwargs={"k": 15}).invoke(rq)),
    "bm25_score_all": timeit(lambda: plain._snapshot[1].get_scores(plain._tokenize(rq))),
    "hybrid_no_rerank": timeit(lambda: plain.get_relevant_documents(rq)),
    "hybrid_with_rerank": timeit(lambda: reranked.get_relevant_documents(rq), n=10),
    "chunk_handbook_pdf": round(t_chunk * 1000, 1),
    "embed_and_store_handbook_4_chunks": round(t_embed * 1000, 1),
}
json.dump(out, open(os.path.join(ROOT, "docs", "guide_assets", "examples.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
