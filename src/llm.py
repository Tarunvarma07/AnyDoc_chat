"""
The one place that decides which Groq model AnyDoc uses (answers, query
rewriting and metadata extraction).

Providers retire models: Groq removed llama-3.1-8b-instant, which this project
used in three hard-coded places, so every LLM step started failing at once.
Set GROQ_MODEL to switch without a code change; check what Groq currently offers
at https://console.groq.com/docs/models.
"""
import os

DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"


def groq_model(name: str = None) -> str:
    return name or os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL
