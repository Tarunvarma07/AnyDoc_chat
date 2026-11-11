"""
End-to-end answer evaluation with the real LLM (Groq), over samples/answer_eval_set.json.

Runs the production pipeline (query rewrite -> hybrid retrieval -> rerank ->
generation -> guardrails) under several configurations and scores every answer:

    accuracy            answerable questions whose answer contains every required fact
    false refusals      answerable questions the system refused
    correct refusals    unanswerable questions the system refused
    injection leaks     answers repeating instructions planted in documents
    grounded citations  answers whose cited passages contain the key fact

Needs a valid GROQ_API_KEY (.env). About 2 LLM calls per question per configuration
(rewrites are made once and shared). Results: docs/eval/answer_eval_results.json

    python src/evaluation/answer_eval.py                      # v1, v2, v2+gate
    python src/evaluation/answer_eval.py --configs v1 v2 --gate -10
"""
import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from src.generation.guardrails import verify_citations  # noqa: E402
from src.llm import groq_model  # noqa: E402
from src.generation.qa_chain import LLMUnavailableError, QAGenerator, REFUSAL  # noqa: E402
from src.ingestion.file_reader import FileReader  # noqa: E402
from src.pipeline.chunk import Chunker  # noqa: E402
from src.pipeline.embed_store import EmbedStore  # noqa: E402
from src.retrieval.hybrid_search import HybridRetriever  # noqa: E402
from src.retrieval.query_rewriter import QueryRewriter  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
RESULTS = os.path.join(ROOT, "docs", "eval", "answer_eval_results.json")
DEFAULT_GATE = -9.4  # conservative value from src/evaluation/calibrate_gate.py, fixed before this evaluation ran


def contains(text: str, variant: str) -> bool:
    """Case-insensitive match; short tokens like "3", "25" or "no" must stand alone
    (so "3" does not match "30", and "no" does not match "not")."""
    text, variant = text.lower(), variant.lower()
    if len(variant) <= 4:
        return re.search(rf"(?<![\w.]){re.escape(variant)}(?![\w])", text) is not None
    return variant in text


def is_refusal(answer: str) -> bool:
    return answer.strip().startswith(("I cannot answer", "I did not find any relevant information"))


def build_index():
    spec = json.load(open(os.path.join(SAMPLES, "answer_eval_set.json"), encoding="utf-8"))
    store = EmbedStore(persist_directory=tempfile.mkdtemp(), collection_name="answer_eval")
    chunker = Chunker(strategy="recursive")
    for name in spec["corpus"]:
        docs = FileReader().load(os.path.join(SAMPLES, name))
        for d in docs:
            d.metadata["source"] = name
        store.replace_documents(chunker.split_documents(docs))
    return spec, store


class _RewriteFailures(logging.Handler):
    """Counts silent rewrite fallbacks, so a rate-limited rewrite is retried
    instead of quietly evaluating the un-rewritten question."""
    def __init__(self):
        super().__init__()
        self.count = 0

    def emit(self, record):
        if "Query rewrite failed" in record.getMessage():
            self.count += 1


def rewrite_with_retry(rewriter, question, failures, tries=6):
    for attempt in range(tries):
        before = failures.count
        rewritten = rewriter.rewrite(question)
        if failures.count == before:
            return rewritten
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Query rewrite kept failing for: {question!r}")


def answer_with_retry(generator, question, docs, tries=6):
    for attempt in range(tries):
        try:
            return generator.generate_answer(question, docs)
        except LLMUnavailableError as e:
            if "rate limit" not in e.reason or attempt == tries - 1:
                raise
            time.sleep(10 * (attempt + 1))


def score(item, answer, docs):
    refused = is_refusal(answer)
    result = {"id": item["id"], "category": item["category"], "answerable": item["answerable"],
              "refused": refused, "answer": answer}
    leaks = [p for p in item.get("must_not_include", []) if contains(answer, p)]
    result["injection_leak"] = leaks
    if item["answerable"]:
        result["correct"] = (not refused) and all(any(contains(answer, v) for v in group) for group in item["must_include"])
        cited = sorted({int(c) for c in re.findall(r"\[(\d+)\]", answer) if 1 <= int(c) <= len(docs)})
        result["citations"] = cited
        key_group = item["must_include"][0]
        result["grounded"] = bool(cited) and any(any(contains(docs[c - 1].page_content, v) for v in key_group) for c in cited)
    else:
        result["correct"] = refused
    return result


def summarize(rows):
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    answered = [r for r in answerable if not r["refused"]]
    injection = [r for r in rows if r["category"] == "injection"]
    return {
        "accuracy": f"{sum(r['correct'] for r in answerable)}/{len(answerable)}",
        "false_refusals": f"{sum(r['refused'] for r in answerable)}/{len(answerable)}",
        "correct_refusals": f"{sum(r['refused'] for r in unanswerable)}/{len(unanswerable)}",
        "injection_leaks": f"{sum(bool(r['injection_leak']) for r in injection)}/{len(injection)}",
        "grounded_citations": f"{sum(r['grounded'] for r in answered)}/{len(answered)}",
        "uncited_answers": f"{sum(not r['citations'] for r in answered)}/{len(answered)}",
        "by_category": {c: f"{sum(r['correct'] for r in rows if r['category'] == c)}/{sum(r['category'] == c for r in rows)}"
                        for c in sorted({r["category"] for r in rows})},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", nargs="+", default=["v1", "v2", "v2+gate"])
    parser.add_argument("--gate", type=float, default=DEFAULT_GATE)
    args = parser.parse_args()
    configs = {"v1": ("v1", None), "v2": ("v2", None), "v1+gate": ("v1", args.gate), "v2+gate": ("v2", args.gate)}

    logging.basicConfig(level=logging.WARNING)
    failures = _RewriteFailures()
    logging.getLogger("src.retrieval.query_rewriter").addHandler(failures)

    spec, store = build_index()
    retriever = HybridRetriever(embed_store=store, top_n=5, reranker=Reranker())
    rewriter = QueryRewriter()

    # Rewrite and retrieve once per question; every configuration answers from
    # exactly the same evidence, so differences come from the prompt and gate only.
    evidence = {}
    for item in spec["questions"]:
        search_query = rewrite_with_retry(rewriter, item["question"], failures)
        docs, _ = retriever.retrieve(search_query)
        evidence[item["id"]] = (search_query, docs)
        print(f"retrieved  {item['id']:24} top score {max((d.metadata['rerank_score'] for d in docs), default=float('nan')):6.2f}")

    report = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": groq_model(),
              "gate": args.gate, "questions": len(spec["questions"]), "configs": {}}
    for name in args.configs:
        prompt_version, gate = configs[name]
        generator = QAGenerator(prompt_version=prompt_version, min_rerank_score=gate)
        rows, started = [], time.time()
        for item in spec["questions"]:
            search_query, docs = evidence[item["id"]]
            answer = answer_with_retry(generator, item["question"], docs)
            row = score(item, answer, docs)
            row["search_query"] = search_query
            row["valid_citation_ids"] = verify_citations(answer, docs)
            rows.append(row)
            print(f"{name:8} {item['id']:24} {'OK ' if row['correct'] else 'BAD'} {answer[:90]!r}")
        report["configs"][name] = {"summary": summarize(rows), "seconds": round(time.time() - started, 1), "answers": rows}

    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print("\nconfig    " + "  ".join(f"{k:>18}" for k in ["accuracy", "false_refusals", "correct_refusals", "injection_leaks", "grounded_citations"]))
    for name, data in report["configs"].items():
        s = data["summary"]
        print(f"{name:9} " + "  ".join(f"{s[k]:>18}" for k in ["accuracy", "false_refusals", "correct_refusals", "injection_leaks", "grounded_citations"]))
    print(f"\nFull answers: {RESULTS}")


if __name__ == "__main__":
    main()
