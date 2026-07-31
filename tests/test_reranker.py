from unittest.mock import MagicMock, patch
from langchain_core.documents import Document
from src.retrieval.reranker import Reranker


def test_reranker_reorders_by_cross_encoder_score():
    docs = [
        Document(page_content="irrelevant chunk about cooking pasta"),
        Document(page_content="the exact answer about RRF fusion algorithms"),
        Document(page_content="somewhat related chunk about search"),
    ]

    mock_model = MagicMock()
    # Cross-encoders score more relevant pairs higher; make docs[1] win.
    mock_model.predict.return_value = [0.1, 0.9, 0.4]

    reranker = Reranker()
    with patch.object(reranker, "_get_model", return_value=mock_model):
        results = reranker.rerank("What is RRF fusion?", docs, top_n=2)

    assert len(results) == 2
    assert results[0].page_content.startswith("the exact answer")
    assert results[1].page_content.startswith("somewhat related")


def test_reranker_empty_documents_returns_empty():
    reranker = Reranker()
    assert reranker.rerank("query", [], top_n=5) == []


def test_reranker_model_loaded_lazily():
    reranker = Reranker()
    assert reranker._model is None


def test_hybrid_retriever_uses_reranker_when_provided(tmp_path):
    from src.pipeline.embed_store import EmbedStore
    from src.retrieval.hybrid_search import HybridRetriever

    db_path = str(tmp_path / "chroma_db_rerank")
    store = EmbedStore(persist_directory=db_path, model_name="all-MiniLM-L6-v2", collection_name="test_rerank")

    docs = [
        Document(page_content="Python is a programming language.", metadata={"chunk_index": 1}),
        Document(page_content="BM25 is a sparse retrieval algorithm.", metadata={"chunk_index": 2}),
    ]
    store.add_documents(docs)

    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [docs[1]]

    retriever = HybridRetriever(embed_store=store, top_n=1, reranker=mock_reranker)
    results = retriever.get_relevant_documents("BM25 algorithm")

    mock_reranker.rerank.assert_called_once()
    assert results == [docs[1]]


def test_hybrid_retriever_widens_candidate_pool_when_reranker_attached(tmp_path):
    from src.pipeline.embed_store import EmbedStore
    from src.retrieval.hybrid_search import HybridRetriever

    db_path = str(tmp_path / "chroma_db_rerank_candidates")
    store = EmbedStore(persist_directory=db_path, model_name="all-MiniLM-L6-v2", collection_name="test_rerank_candidates")

    mock_reranker = MagicMock()
    retriever = HybridRetriever(embed_store=store, top_n=5, reranker=mock_reranker)

    assert retriever.candidate_n == 15  # top_n * 3
