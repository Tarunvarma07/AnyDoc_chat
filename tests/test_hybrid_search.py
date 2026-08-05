import pytest
import os
from unittest.mock import patch
from langchain_core.documents import Document
from src.pipeline.embed_store import EmbedStore
from src.retrieval.hybrid_search import HybridRetriever

def test_embed_store_consistency(tmp_path):
    # Test valid init
    db_path = str(tmp_path / "chroma_db")
    store = EmbedStore(persist_directory=db_path, model_name="sentence-transformers/all-MiniLM-L6-v2", collection_name="test")
    
    # Add a doc
    doc = Document(page_content="test document", metadata={"chunk_index": 0})
    store.add_documents([doc])
    
    # Test init again with same model
    store2 = EmbedStore(persist_directory=db_path, model_name="sentence-transformers/all-MiniLM-L6-v2", collection_name="test")
    docs = store2.get_all_documents()
    assert len(docs) == 1
    
    # Test init with wrong model - should fail consistency check
    # We mock FastEmbedEmbeddings so it doesn't try to download the fake model
    with patch("src.pipeline.embed_store.FastEmbedEmbeddings"):
        with pytest.raises(ValueError, match="Embedding model mismatch"):
            EmbedStore(persist_directory=db_path, model_name="different-model-v1", collection_name="test")

def test_hybrid_search(tmp_path):
    db_path = str(tmp_path / "chroma_db_2")
    store = EmbedStore(persist_directory=db_path, model_name="sentence-transformers/all-MiniLM-L6-v2", collection_name="test2")
    
    docs = [
        Document(page_content="The quick brown fox jumps over the lazy dog.", metadata={"chunk_index": 1}),
        Document(page_content="Python is a programming language.", metadata={"chunk_index": 2}),
        Document(page_content="BM25 is a sparse retrieval algorithm for exact keyword matching.", metadata={"chunk_index": 3}),
        Document(page_content="Vector databases store dense embeddings for semantic search.", metadata={"chunk_index": 4})
    ]
    store.add_documents(docs)
    
    retriever = HybridRetriever(embed_store=store, top_n=2)
    
    # Exact keyword match for BM25
    results_sparse = retriever.get_relevant_documents("BM25 exact keyword matching")
    assert len(results_sparse) > 0
    assert "BM25" in results_sparse[0].page_content
    
    # Semantic match for dense
    results_dense = retriever.get_relevant_documents("code and software development")
    assert len(results_dense) > 0
    assert "Python" in results_dense[0].page_content or "programming" in results_dense[0].page_content

def test_hybrid_search_dynamic_rebuild(tmp_path):
    db_path = str(tmp_path / "chroma_db_3")
    store = EmbedStore(persist_directory=db_path, model_name="sentence-transformers/all-MiniLM-L6-v2", collection_name="test3")
    
    # Init empty retriever
    retriever = HybridRetriever(embed_store=store, top_n=2)
    assert retriever.bm25 is None
    
    # Add a document dynamically
    docs = [Document(page_content="UniqueKeyword123 is very unique.", metadata={"chunk_index": 1})]
    store.add_documents(docs)
    
    # The callback should have rebuilt the index
    assert retriever.bm25 is not None
    assert len(retriever.docs) == 1
    
    # Test that we can retrieve it
    results = retriever.get_relevant_documents("UniqueKeyword123")
    assert len(results) == 1
    assert "UniqueKeyword123" in results[0].page_content
