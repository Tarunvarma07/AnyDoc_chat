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

MAX_TABLE_PAGES = 300  # table detection is the slow part of PDF ingestion


def _cell(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def extract_pdf_tables(file_path: str) -> List[Document]:
    """
    Finds ruled tables in a PDF (pdfplumber) and returns one Document per table
    in which every row names its columns:
        Product: Torque Sensor; SKU: AR-500; Unit price: 780 USD; Lead time: 12 days

    pypdf's page text flattens a table to bare values, so once a long table is
    split into chunks, later rows lose the header that says what each number
    means. Rows are separate lines, so the chunker splits between rows, never
    inside one. This is an addition to the page text, never a replacement, and
    any failure here only skips the tables: it must not fail the upload.
    """
    import pdfplumber

    docs = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page_index, page in enumerate(pdf.pages[:MAX_TABLE_PAGES]):
                for table_index, table in enumerate(page.extract_tables()):
                    rows = [[_cell(c) for c in row] for row in table if row and any(c for c in row)]
                    if len(rows) < 2 or max(len(r) for r in rows) < 2:
                        continue  # a header alone, or a single column, is not a useful table
                    header = [h or f"Column {i + 1}" for i, h in enumerate(rows[0])]
                    lines = [f"Table {table_index + 1} on page {page_index + 1} (columns: {', '.join(header)})"]
                    for row in rows[1:]:
                        pairs = [f"{h}: {v}" for h, v in zip(header, row) if v]
                        if pairs:
                            lines.append("; ".join(pairs))
                    docs.append(Document(page_content="\n".join(lines),
                                         metadata={"source": file_path, "page": page_index,
                                                   "content_type": "table", "table_index": table_index}))
    except Exception as e:
        logger.warning(f"Table extraction skipped for {file_path}: {e!r}")
    if docs:
        logger.info(f"Extracted {len(docs)} table(s) from {file_path}")
    return docs


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
        except Exception as e:
            logger.error(f"Failed to load document {file_path}: {e}")
            raise e
        if ext == '.pdf':
            docs.extend(extract_pdf_tables(file_path))
        return docs

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
