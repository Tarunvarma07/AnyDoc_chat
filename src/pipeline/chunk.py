import logging
import statistics
from typing import List, Dict, Any

from langchain_core.documents import Document
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    CharacterTextSplitter
)

logger = logging.getLogger(__name__)

class Chunker:
    def __init__(self, strategy: str = "recursive", chunk_size: int = 500, chunk_overlap: int = 50):
        """
        Initializes the chunker with the specified strategy.
        strategy: 'recursive' or 'character'
        """
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        if strategy == "recursive":
            self.splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                is_separator_regex=False,
            )
        elif strategy == "character":
            self.splitter = CharacterTextSplitter(
                separator="\n\n",
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                is_separator_regex=False,
            )
        else:
            raise ValueError(f"Unknown chunking strategy: {strategy}")

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """Splits a list of documents into chunks."""
        if not documents:
            return []
        
        chunks = self.splitter.split_documents(documents)
        
        # Attach a unique chunk index to metadata
        for i, chunk in enumerate(chunks):
            # Split_documents usually copies metadata, but we ensure it's explicitly tracked
            chunk.metadata["chunk_index"] = i
            chunk.metadata["chunk_strategy"] = self.strategy
            
        return chunks


class ChunkQualityReporter:
    def __init__(self, min_length_threshold: int = 50):
        self.min_length_threshold = min_length_threshold
        # Common terminal punctuation marks. A lack of these often implies a mid-sentence hard cut.
        self.terminal_punctuation = {'.', '!', '?', '"', "'", '\n', ':', ';'}

    def evaluate(self, chunks: List[Document]) -> Dict[str, Any]:
        """
        Evaluates a list of chunks and returns a quality report.
        """
        if not chunks:
            return {
                "count": 0,
                "min_length": 0,
                "max_length": 0,
                "avg_length": 0.0,
                "fragment_count": 0,
                "no_terminal_punct_count": 0
            }

        lengths = [len(c.page_content) for c in chunks]
        
        fragment_count = sum(1 for length in lengths if length < self.min_length_threshold)
        
        no_terminal_punct_count = 0
        for c in chunks:
            content = c.page_content.strip()
            if content and content[-1] not in self.terminal_punctuation:
                no_terminal_punct_count += 1
                
        report = {
            "count": len(chunks),
            "min_length": min(lengths),
            "max_length": max(lengths),
            "avg_length": round(statistics.mean(lengths), 2),
            "fragment_count": fragment_count,
            "no_terminal_punct_count": no_terminal_punct_count
        }
        
        return report

def compare_strategies(doc: Document, strategies: List[str] = None, chunk_size: int = 500, chunk_overlap: int = 50) -> Dict[str, Dict[str, Any]]:
    """
    Runs multiple chunking strategies on the exact same document 
    and returns a side-by-side quality report for numerical comparison.
    """
    if strategies is None:
        strategies = ["recursive", "character"]
        
    results = {}
    reporter = ChunkQualityReporter()
    
    for strat in strategies:
        try:
            chunker = Chunker(strategy=strat, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            chunks = chunker.split_documents([doc])
            results[strat] = reporter.evaluate(chunks)
        except Exception as e:
            logger.error(f"Failed to evaluate strategy {strat}: {e}")
            results[strat] = {"error": str(e)}
            
    return results
