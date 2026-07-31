import pytest
from langchain_core.documents import Document
from src.pipeline.chunk import Chunker, ChunkQualityReporter, compare_strategies

def test_chunker_strategies():
    # Long text with paragraphs and sentences
    text = (
        "This is the first sentence. This is the second sentence.\n\n"
        "Here is a new paragraph. It has some more text that makes it longer. "
        "We want to see how the splitters handle this differently. "
        "The recursive splitter should try to keep sentences together if possible."
    )
    doc = Document(page_content=text, metadata={"source": "test.txt"})
    
    # Test CharacterTextSplitter
    # Our CharacterTextSplitter is configured to split on "\n\n"
    char_chunker = Chunker(strategy="character", chunk_size=100, chunk_overlap=0)
    char_chunks = char_chunker.split_documents([doc])
    
    # Test RecursiveCharacterTextSplitter
    rec_chunker = Chunker(strategy="recursive", chunk_size=100, chunk_overlap=0)
    rec_chunks = rec_chunker.split_documents([doc])
    
    assert len(char_chunks) > 0
    assert len(rec_chunks) > 0
    
    # Check that metadata is preserved and injected
    assert char_chunks[0].metadata["source"] == "test.txt"
    assert "chunk_index" in char_chunks[0].metadata
    assert char_chunks[0].metadata["chunk_strategy"] == "character"
    
    assert rec_chunks[0].metadata["chunk_strategy"] == "recursive"


def test_chunk_quality_reporter():
    reporter = ChunkQualityReporter(min_length_threshold=50)
    
    # Construct a list of chunks of varying quality
    good_chunk = Document(page_content="This is a perfectly fine chunk with good length and punctuation.")
    fragment_chunk = Document(page_content="Too short.") # Length 10 < 50
    no_punct_chunk = Document(page_content="This chunk just ends abruptly without any terminal punctuation") # No punctuation
    
    chunks = [good_chunk, fragment_chunk, no_punct_chunk]
    
    report = reporter.evaluate(chunks)
    
    assert report["count"] == 3
    assert report["fragment_count"] == 1
    assert report["no_terminal_punct_count"] == 1
    assert report["max_length"] == len(good_chunk.page_content)

def test_compare_strategies():
    text = (
        "This is the first sentence. This is the second sentence.\n\n"
        "Here is a new paragraph. It has some more text that makes it longer. "
        "We want to see how the splitters handle this differently. "
        "The recursive splitter should try to keep sentences together if possible."
    )
    doc = Document(page_content=text, metadata={"source": "test.txt"})
    
    results = compare_strategies(doc, chunk_size=100, chunk_overlap=0)
    
    assert "recursive" in results
    assert "character" in results
    
    # Both should have produced some chunks
    assert results["recursive"]["count"] > 0
    assert results["character"]["count"] > 0
