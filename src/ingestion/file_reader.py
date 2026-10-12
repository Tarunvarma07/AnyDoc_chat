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

        # We know from magic bytes that the content matches the extension, but we
        # still need to pick the right LangChain loader based on extension.
        if ext in ('.txt', '.csv'):
            return self._load_text(file_path, ext)
        if ext == '.pdf':
            loader = PyPDFLoader(file_path)
        elif ext == '.docx':
            loader = Docx2txtLoader(file_path)
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        try:
            docs = loader.load()
            return docs
        except Exception as e:
            logger.error(f"Failed to load document {file_path}: {e}")
            raise e

    def _load_text(self, file_path: str, ext: str) -> List[Document]:
        """
        Loads TXT/CSV as UTF-8 (BOM stripped), falling back to Latin-1 - which
        decodes any byte sequence - for legacy single-byte files instead of
        failing the upload. CSVLoader would otherwise use the OS default
        encoding, which differs between Windows and Linux.
        """
        last_error = None
        for encoding in ('utf-8-sig', 'latin-1'):
            loader = CSVLoader(file_path, encoding=encoding) if ext == '.csv' else TextLoader(file_path, encoding=encoding)
            try:
                return loader.load()
            except Exception as e:
                # Both loaders wrap UnicodeDecodeError in a RuntimeError.
                if not isinstance(e, UnicodeDecodeError) and not isinstance(e.__cause__, UnicodeDecodeError):
                    logger.error(f"Failed to load document {file_path}: {e}")
                    raise
                logger.warning(f"{file_path} is not valid {encoding}; retrying with a fallback encoding.")
                last_error = e
        raise last_error
