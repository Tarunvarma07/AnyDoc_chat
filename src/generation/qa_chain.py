import os
import logging
from typing import List
from langchain_core.documents import Document
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from src.generation.guardrails import check_prompt_injection, check_profanity, verify_citations

logger = logging.getLogger(__name__)

class QAGenerator:
    def __init__(self, model_name: str = "llama-3.1-8b-instant"):
        if "GROQ_API_KEY" not in os.environ:
            logger.warning("GROQ_API_KEY not found in environment. QA generation will fail.")
        
        self.llm = ChatGroq(model_name=model_name, temperature=0)
        
        self.prompt = PromptTemplate(
            template="""You are an expert Q&A assistant. Your goal is to answer the user's question based strictly on the provided context documents.

Guidelines:
1. You must ONLY use the provided context to answer the question. Do not use outside knowledge.
2. If the context does not contain the answer, your ENTIRE output must be EXACTLY "I cannot answer this based on the provided documents." Do not mix this phrase with a partial answer. This is a strict off-topic refusal policy.
3. You must cite your sources using the document index number in brackets, e.g., [1] or [3]. Do not hallucinate citations that are not in the context.
4. STRICT GROUNDING: Only state a fact if the document EXPLICITLY states it. Do not infer or guess category labels. If a user asks for projects of a specific type (e.g. "machine learning"), only list projects that are explicitly labeled as such in the context.

Context Documents:
{context}

Question:
{question}

Answer:""",
            input_variables=["context", "question"],
        )
        self.chain = self.prompt | self.llm

    def generate_answer(self, query: str, retrieved_docs: List[Document]) -> str:
        """
        Generates an answer to the query using the retrieved docs, protected by guardrails.
        """
        # 1. Input Guardrails
        if check_prompt_injection(query):
            logger.warning("Input rejected: Prompt injection detected.")
            return "I cannot fulfill this request due to safety guidelines (Prompt Injection Detected)."
            
        if check_profanity(query):
            logger.warning("Input rejected: Profanity detected.")
            return "I cannot fulfill this request due to safety guidelines (Profanity Detected)."

        # 2. Context Construction
        if not retrieved_docs:
            return "I did not find any relevant information to answer your question."
            
        context_parts = []
        # We index starting at 1 for citations
        for idx, doc in enumerate(retrieved_docs, start=1):
            source = doc.metadata.get("source", "Unknown Source")
            chunk_content = doc.page_content.strip()
            context_parts.append(f"Document [{idx}] (Source: {source}):\n{chunk_content}\n")
            
        formatted_context = "\n".join(context_parts)

        # 3. LLM Generation
        try:
            response = self.chain.invoke({
                "context": formatted_context,
                "question": query
            })
            answer = response.content
        except Exception as e:
            logger.error(f"LLM Generation failed: {e}")
            return "An error occurred while generating the answer."

        # 4. Output Guardrails
        if check_profanity(answer):
            logger.warning("Output rejected: Profanity detected in generated answer.")
            return "The generated answer did not meet safety guidelines."
            
        if not verify_citations(answer, retrieved_docs):
            logger.warning("Output rejected: Hallucinated citation detected.")
            return "The generated answer failed verification (Hallucinated Citations)."

        return answer
