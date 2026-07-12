import os
import logging
from typing import List
from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    CSVLoader,
    TextLoader,
)

from src.ingestion.guardrails import validate_file, SecurityError

logger = logging.getLogger(__name__)

class FileReader:
    def load(self, file_path: str, max_size_mb: int = 10) -> List[Document]:
        """
        Validates the file via guardrails (size & magic bytes) and loads it 
        using the appropriate LangChain loader.
        """
        try:
            validate_file(file_path, max_size_mb=max_size_mb)
        except SecurityError as e:
            logger.error(f"Security error while validating {file_path}: {e}")
            raise e
        except FileNotFoundError as e:
            logger.error(f"File not found: {file_path}")
            raise e

        _, ext = os.path.splitext(file_path.lower())
        
        # We know from magic bytes that the content type is allowed, but we still 
        # need to pick the right LangChain loader based on extension.
        if ext == '.pdf':
            loader = PyPDFLoader(file_path)
        elif ext == '.docx':
            loader = Docx2txtLoader(file_path)
        elif ext == '.csv':
            loader = CSVLoader(file_path)
        elif ext == '.txt':
            loader = TextLoader(file_path, encoding='utf-8')
        else:
            raise ValueError(f"Unsupported file extension: {ext}")
            
        try:
            docs = loader.load()
            return docs
        except Exception as e:
            logger.error(f"Failed to load document {file_path}: {e}")
            raise e
