"""
Chooses the evidence-gate threshold (MIN_RERANK_SCORE) from questions that are
NOT in the answer evaluation set, so the evaluation is not tuned to itself.

For each calibration question it records the best cross-encoder score among the
retrieved passages, then suggests a threshold between the lowest score of an
answerable question and the highest score of an unanswerable one. No LLM calls.

    python src/evaluation/calibrate_gate.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.evaluation.answer_eval import build_index  # noqa: E402
from src.retrieval.hybrid_search import HybridRetriever  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402

# Unanswerable questions used only here (the answer eval set has its own).
EXTRA_UNANSWERABLE = [
    "What is the refund policy for customers?",
    "Where is the company headquartered?",
    "What programming language is FleetOS written in?",
    "How many vacation days do contractors get?",
    "What time does the cafeteria open?",
    "Which cloud provider hosts the customer portal?",
]


def main():
    retrieval_set = json.load(open(os.path.join(ROOT, "samples", "demo_eval_set.json"), encoding="utf-8"))
    answer_set = json.load(open(os.path.join(ROOT, "samples", "answer_eval_set.json"), encoding="utf-8"))
    held_out = {q["question"] for q in answer_set["questions"]}
    questions = [(q["query"], bool(q["expected_source"])) for q in retrieval_set["queries"]]
    questions += [(q, False) for q in EXTRA_UNANSWERABLE]
    assert not held_out & {q for q, _ in questions}, "calibration must not reuse evaluation questions"

    _, store = build_index()
    retriever = HybridRetriever(embed_store=store, top_n=5, reranker=Reranker())
    scored = []
    for question, answerable in questions:
        docs, _ = retriever.retrieve(question)
        top = max(d.metadata["rerank_score"] for d in docs)
        scored.append((top, answerable, question))
        print(f"{'answerable  ' if answerable else 'no answer   '} {top:7.2f}  {question}")

    lowest_answerable = min(s for s, a, _ in scored if a)
    highest_unanswerable = max(s for s, a, _ in scored if not a)
    print(f"\nlowest answerable top score:   {lowest_answerable:.2f}")
    print(f"highest unanswerable top score: {highest_unanswerable:.2f}")
    if highest_unanswerable < lowest_answerable:
        threshold = round((lowest_answerable + highest_unanswerable) / 2, 1)
        print(f"separable; suggested MIN_RERANK_SCORE = {threshold}")
    else:
        # Near-topic questions without an answer score like real ones, so no
        # threshold separates them. The gate can only safely skip the LLM for
        # clearly off-topic questions: stay just below every answerable score.
        threshold = round(lowest_answerable - 0.5, 1)
        print("NOT separable: near-topic unanswerable questions score like answerable ones.")
        print(f"conservative MIN_RERANK_SCORE = {threshold} (no answerable calibration question refused)")
    caught = [q for s, a, q in scored if not a and s < threshold]
    print(f"it refuses {len(caught)}/{sum(not a for _, a, _ in scored)} unanswerable calibration questions without an LLM call; "
          "the rest rely on the LLM's own refusal")


if __name__ == "__main__":
    main()
