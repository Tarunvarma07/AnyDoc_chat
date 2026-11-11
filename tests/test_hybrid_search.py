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


def test_bm25_tokenizer_strips_punctuation_but_keeps_identifiers(tmp_path):
    store = EmbedStore(persist_directory=str(tmp_path / "db_tok"), collection_name="test_tok")
    retriever = HybridRetriever(embed_store=store)
    # Whitespace splitting produced "zx-4471?", which never matched "zx-4471".
    assert retriever._tokenize("What is ZX-4471?") == ["what", "is", "zx-4471"]
    assert retriever._tokenize("Fixed in v1.4.2 (see config.yaml).") == ["fixed", "in", "v1.4.2", "see", "config.yaml"]


def test_bm25_matches_identifier_followed_by_question_mark(tmp_path):
    store = EmbedStore(persist_directory=str(tmp_path / "db_id"), collection_name="test_id")
    store.add_documents([
        Document(page_content="Error code ZX-4480 indicates battery overheating.", metadata={"chunk_index": 0}),
        Document(page_content="The cafeteria opens at eight in the morning.", metadata={"chunk_index": 1}),
        # A third document: with N=2, BM25Okapi's IDF for a term in 1 of 2 docs
        # is log(1.5/1.5) = 0, which zeroes every score.
        Document(page_content="Parking for visitors is in lot C.", metadata={"chunk_index": 2}),
    ])
    retriever = HybridRetriever(embed_store=store, top_n=1)
    docs, bm25 = retriever._snapshot
    scores = bm25.get_scores(retriever._tokenize("What should I do about ZX-4480?"))
    best = max(zip(docs, scores), key=lambda pair: pair[1])
    assert best[1] > 0
    assert "ZX-4480" in best[0].page_content


def test_reingesting_same_chunks_is_idempotent(tmp_path):
    store = EmbedStore(persist_directory=str(tmp_path / "db_dup"), collection_name="test_dup")
    chunks = [
        Document(page_content="Version 3.8.1 fixed the battery drain bug.", metadata={"source": "notes.txt", "chunk_index": 0}),
        Document(page_content="Version 3.8.1 fixed the battery drain bug.", metadata={"source": "notes.txt", "chunk_index": 1}),
    ]
    store.add_documents(chunks)
    store.add_documents(chunks)  # same file ingested a second time
    # Identical text at two positions is kept twice; the second ingest adds nothing.
    assert len(store.get_all_documents()) == 2


def test_retrieve_returns_per_call_stats_even_when_empty(tmp_path):
    # last_run_stats used to keep the previous query's numbers when the index
    # was empty, and is shared between concurrent requests; retrieve() returns
    # the stats of this call alongside its documents.
    store = EmbedStore(persist_directory=str(tmp_path / "db_stats"), collection_name="test_stats")
    retriever = HybridRetriever(embed_store=store, top_n=2)
    retriever.last_run_stats = {"candidates_considered": 99}
    docs, stats = retriever.retrieve("anything")
    assert docs == [] and stats["candidates_considered"] == 0 and stats["reranked"] is False

    store.add_documents([Document(page_content="Lidar sensors are stocked in Austin.", metadata={"source": "a.txt", "chunk_index": 0})])
    docs, stats = retriever.retrieve("lidar sensors")
    assert len(docs) == 1 and stats["candidates_considered"] == 1


def test_replace_documents_removes_the_previous_version(tmp_path):
    store = EmbedStore(persist_directory=str(tmp_path / "db_replace"), collection_name="test_replace")
    retriever = HybridRetriever(embed_store=store, top_n=5)
    v1 = [Document(page_content=f"Old policy line {i}.", metadata={"source": "policy.txt", "chunk_index": i}) for i in range(3)]
    other = [Document(page_content="Unrelated note.", metadata={"source": "other.txt", "chunk_index": 0})]
    store.add_documents(v1 + other)

    v2 = [Document(page_content="New policy: remote work three days.", metadata={"source": "policy.txt", "chunk_index": 0})]
    removed = store.replace_documents(v2)

    texts = sorted(d.page_content for d in store.get_all_documents())
    assert removed == 3
    assert texts == ["New policy: remote work three days.", "Unrelated note."]
    assert len(retriever.docs) == 2  # BM25 rebuilt after the replace


def test_list_and_delete_sources(tmp_path):
    store = EmbedStore(persist_directory=str(tmp_path / "db_list"), collection_name="test_list")
    retriever = HybridRetriever(embed_store=store, top_n=5)
    store.add_documents([
        Document(page_content="Page one.", metadata={"source": "hb.pdf", "page": 0, "chunk_index": 0}),
        Document(page_content="Page two.", metadata={"source": "hb.pdf", "page": 1, "chunk_index": 1}),
        Document(page_content="A row.", metadata={"source": "inv.csv", "chunk_index": 2}),
    ])
    rows = {r["source"]: r for r in store.list_sources()}
    assert rows["hb.pdf"]["chunks"] == 2 and rows["hb.pdf"]["pages"] == 2
    assert rows["inv.csv"]["chunks"] == 1 and rows["inv.csv"]["pages"] is None

    assert store.delete_source("hb.pdf") == 2
    assert store.delete_source("hb.pdf") == 0
    assert [r["source"] for r in store.list_sources()] == ["inv.csv"]
    assert len(retriever.docs) == 1  # BM25 rebuilt after the delete
