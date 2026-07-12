import os
import logging
from typing import List
from langchain_core.documents import Document
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from src.generation.guardrails import check_prompt_injection

logger = logging.getLogger(__name__)

class DocumentMetadata(BaseModel):
    title: str = Field(description="A concise, accurate title for the document")
    summary: str = Field(description="A 2-3 sentence summary of the main points")
    topics: List[str] = Field(description="list of 3-5 relevant tags")
    document_type: str = Field(description="The type of document")

class MetadataExtractor:
    # NOTE FOR PHASE 4 (Prompt Injection Guardrails):
    # Untrusted web/file content is sent directly to the LLM in this class.
    # When prompt injection defenses are built in Phase 4, they MUST be applied 
    # to this extraction call, not just the final QA generation step.
    
    def __init__(self, model_name: str = "llama-3.1-8b-instant"):
        if "GROQ_API_KEY" not in os.environ:
            logger.warning("GROQ_API_KEY not found in environment. Metadata extraction will fail.")
        
        # Use a fast/cheap model for metadata extraction
        self.llm = ChatGroq(model_name=model_name, temperature=0)
        
        self.parser = JsonOutputParser()
        
        self.prompt = PromptTemplate(
            template="""You are an expert document analyzer. Read the following document content and extract structured metadata.
            
Ensure the output is strictly valid JSON matching this schema:
{{
  "title": "A concise, accurate title for the document",
  "summary": "A 2-3 sentence summary of the main points",
  "topics": ["list", "of", "3-5", "relevant", "tags"],
  "document_type": "The type of document (e.g., 'API Documentation', 'News Article', 'Legal Contract', 'Report')"
}}

Do not include any other text or markdown formatting outside the JSON object.

Document Content:
{content}
""",
            input_variables=["content"],
        )
        self.chain = self.prompt | self.llm | self.parser
        self.llm_structured = self.llm.with_structured_output(DocumentMetadata)

    def extract_for_document(self, doc: Document) -> Document:
        """
        Runs the LLM over the document content to extract metadata.
        For very large documents, we only pass the first 4000 characters to save tokens/time,
        as the title/summary can usually be derived from the introduction.
        """
        # Guardrail: Check for prompt injection before sending to LLM
        if check_prompt_injection(doc.page_content):
            logger.warning("Prompt injection detected in document. Skipping metadata extraction to protect LLM.")
            doc.metadata["extraction_skipped"] = "prompt_injection_detected"
            return doc

        content_preview = doc.page_content[:4000]
        try:
            extracted_meta = self.chain.invoke({"content": content_preview})
            
            # Merge extracted metadata with existing metadata
            doc.metadata["extracted_title"] = extracted_meta.get("title", "Unknown Title")
            doc.metadata["extracted_summary"] = extracted_meta.get("summary", "")
            topics = extracted_meta.get("topics", [])
            doc.metadata["extracted_topics"] = ", ".join(topics) if topics else "None"
            doc.metadata["document_type"] = extracted_meta.get("document_type", "Unknown")
            
        except Exception as e:
            logger.error(f"Failed to extract metadata: {e}")
            # Ensure keys exist even on failure
            doc.metadata["extracted_title"] = "Unknown Title (Extraction Failed)"
            doc.metadata["extracted_summary"] = ""
            doc.metadata["extracted_topics"] = "None"
            doc.metadata["document_type"] = "Unknown"
            
        return doc

    def process_documents(self, docs: List[Document]) -> List[Document]:
        """Processes a list of documents."""
        processed_docs = []
        for d in docs:
            processed_docs.append(self.extract_for_document(d))
        return processed_docs
