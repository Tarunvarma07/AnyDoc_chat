import os
import logging
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from src.generation.guardrails import check_prompt_injection

logger = logging.getLogger(__name__)


class QueryRewriter:
    """
    Rewrites a user's natural-language question into a single retrieval-optimized
    search query before it hits the hybrid retriever: expands vague references,
    and surfaces likely keyword/synonym variants (error codes, IDs, version
    numbers) so both the dense and sparse (BM25) sides of hybrid search have
    more to match against. The original question is always still used for
    answer generation and citation - only retrieval sees the rewritten query.
    """

    def __init__(self, model_name: str = "llama-3.1-8b-instant"):
        if "GROQ_API_KEY" not in os.environ:
            logger.warning("GROQ_API_KEY not found in environment. Query rewriting will fail.")

        self.llm = ChatGroq(model_name=model_name, temperature=0)

        self.prompt = PromptTemplate(
            template="""You rewrite user questions into a single, retrieval-optimized search query.

Rules:
1. Preserve the original meaning and intent exactly. Never answer the question.
2. Resolve vague pronouns/references using context already present in the question.
3. Add likely keyword synonyms or technical variants (e.g., error codes, version numbers, IDs) that would help a keyword search engine, without inventing facts not implied by the question.
4. Output ONLY the rewritten query on a single line. No explanation, no quotes, no preamble.

Original question:
{question}

Rewritten search query:""",
            input_variables=["question"],
        )
        self.chain = self.prompt | self.llm

    def rewrite(self, query: str) -> str:
        """
        Returns a retrieval-optimized rewrite of `query`, or the original query
        unchanged if rewriting is unsafe, empty, or fails.
        """
        if not query or not query.strip():
            return query

        # Never send flagged input to the LLM for rewriting; retrieval just
        # falls back to the raw query, and the QA guardrails still reject it
        # before generation regardless.
        if check_prompt_injection(query):
            logger.warning("Query rewrite skipped: prompt injection detected in input.")
            return query

        try:
            response = self.chain.invoke({"question": query})
            rewritten = response.content.strip().strip('"')
            return rewritten if rewritten else query
        except Exception as e:
            logger.error(f"Query rewrite failed, falling back to original query: {e}")
            return query
