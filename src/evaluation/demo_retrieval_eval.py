"""
Retrieval-quality evaluation over the synthetic documents in samples/.

Ingests the sample files through the real FileReader -> Chunker -> EmbedStore
path (into a temporary Chroma collection, never the live one) and compares four
retrieval modes on samples/demo_eval_set.json:

    dense     - Chroma vector search only
    bm25      - BM25 keyword search only
    hybrid    - dense + BM25 fused with RRF (no reranker)
    reranked  - hybrid + cross-encoder rerank (what /query uses)

Reports Hit@1/@3/@5 and MRR@5 for answerable queries, and the top cross-encoder
score for no-answer queries. LLM-based stages (query rewriting, metadata
extraction, generation) are NOT exercised, so this needs no API key:

    python src/evaluation/demo_retrieval_eval.py

The corpus is tiny (a few dozen chunks), so these numbers show that each stage is
wired correctly on known cases - not how the system performs at scale.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.ingestion.file_reader import FileReader
from src.pipeline.chunk import Chunker
from src.pipeline.embed_store import EmbedStore
from src.retrieval.hybrid_search import HybridRetriever
from src.retrieval.reranker import Reranker

SAMPLES = os.path.join(ROOT, "samples")
K = 5


def is_relevant(doc, item):
    return (doc.metadata.get("source") == item["expected_source"]
            and item["expected_substring"].lower() in doc.page_content.lower())


def first_relevant_rank(docs, item):
    for rank, doc in enumerate(docs, start=1):
        if is_relevant(doc, item):
            return rank
    return None


def bm25_search(retriever, query, k):
    docs, bm25 = retriever._snapshot
    scores = bm25.get_scores(retriever._tokenize(query))
    ranked = sorted((pair for pair in zip(docs, scores) if pair[1] > 0), key=lambda p: p[1], reverse=True)
    return [doc for doc, _ in ranked[:k]]


def run(eval_path=os.path.join(SAMPLES, "demo_eval_set.json")):
    with open(eval_path, encoding="utf-8") as f:
        spec = json.load(f)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = EmbedStore(persist_directory=tmp, collection_name="demo_eval")
        chunker = Chunker(strategy="recursive")
        for name in spec["corpus"]:
            docs = FileReader().load(os.path.join(SAMPLES, name))
            for d in docs:
                d.metadata["source"] = name
            store.add_documents(chunker.split_documents(docs))
        n_chunks = len(store.get_all_documents())

        hybrid = HybridRetriever(embed_store=store, top_n=K)
        reranker = Reranker()
        reranked = HybridRetriever(embed_store=store, top_n=K, reranker=reranker)
        modes = {
            "dense": lambda q: store.as_retriever(search_kwargs={"k": K}).invoke(q),
            "bm25": lambda q: bm25_search(hybrid, q, K),
            "hybrid": hybrid.get_relevant_documents,
            "reranked": reranked.get_relevant_documents,
        }

        answerable = [q for q in spec["queries"] if q["expected_source"]]
        unanswerable = [q for q in spec["queries"] if not q["expected_source"]]
        results = {"corpus_chunks": n_chunks, "answerable_queries": len(answerable),
                   "no_answer_queries": len(unanswerable), "modes": {}, "per_query": []}

        ranks = {mode: [] for mode in modes}
        for item in answerable:
            row = {"category": item["category"], "query": item["query"]}
            for mode, search in modes.items():
                rank = first_relevant_rank(search(item["query"]), item)
                ranks[mode].append(rank)
                row[mode] = rank
            results["per_query"].append(row)

        for mode, rs in ranks.items():
            n = len(rs)
            results["modes"][mode] = {
                "hit@1": sum(1 for r in rs if r and r <= 1) / n,
                "hit@3": sum(1 for r in rs if r and r <= 3) / n,
                "hit@5": sum(1 for r in rs if r and r <= 5) / n,
                "mrr@5": sum(1 / r for r in rs if r) / n,
            }

        # A no-answer query still returns top-k chunks; the cross-encoder score is
        # the only signal in the pipeline that could tell "nothing relevant" apart.
        def top_score(q):
            docs = reranked.get_relevant_documents(q)
            return max(d.metadata["rerank_score"] for d in docs) if docs else None

        results["top_rerank_score"] = {
            "answerable_min": min(top_score(q["query"]) for q in answerable),
            "no_answer": {q["query"]: top_score(q["query"]) for q in unanswerable},
        }
        return results


def main():
    r = run()
    print(f"Corpus: {r['corpus_chunks']} chunks | {r['answerable_queries']} answerable + "
          f"{r['no_answer_queries']} no-answer queries | k={K}\n")
    print(f"{'mode':10} {'hit@1':>6} {'hit@3':>6} {'hit@5':>6} {'mrr@5':>6}")
    for mode, m in r["modes"].items():
        print(f"{mode:10} {m['hit@1']:6.2f} {m['hit@3']:6.2f} {m['hit@5']:6.2f} {m['mrr@5']:6.2f}")
    print("\nRank of first relevant chunk per query (None = not in top 5):")
    for row in r["per_query"]:
        ranks = "  ".join(f"{m}={row[m]}" for m in ("dense", "bm25", "hybrid", "reranked"))
        print(f"  [{row['category']:14}] {row['query'][:58]:58} {ranks}")
    s = r["top_rerank_score"]
    print(f"\nLowest top-1 rerank score among answerable queries: {s['answerable_min']:.2f}")
    for q, score in s["no_answer"].items():
        print(f"Top rerank score for no-answer query {q!r}: {score:.2f}")


if __name__ == "__main__":
    main()
