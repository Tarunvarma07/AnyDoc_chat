import logging
from typing import List
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class Reranker:
    """
    Cross-encoder reranker that re-scores a candidate document set against
    the query. Unlike dense/sparse retrieval, which score query and document
    independently, a cross-encoder scores the (query, document) pair jointly,
    which is slower but noticeably more precise for the final top-N cut.

    Runs on fastembed's ONNX runtime rather than sentence-transformers/torch -
    same underlying model, but without pulling in a multi-hundred-MB PyTorch
    dependency. That difference is the whole reason this class exists in its
    current form: the torch-based version reliably OOM'd on a 512MB instance.

    The model is loaded lazily on first use, so constructing a Reranker (or a
    HybridRetriever with one attached) never triggers a network download or
    slows down app startup - only the first real query pays that cost.
    """

    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            logger.info(f"Loading cross-encoder reranker model: {self.model_name}")
            self._model = TextCrossEncoder(model_name=self.model_name)
        return self._model

    def rerank(self, query: str, documents: List[Document], top_n: int) -> List[Document]:
        """
        Re-scores `documents` against `query` and returns the top_n most relevant.
        Each returned Document gets a `rerank_score` metadata field (raw cross-encoder
        logit; higher is more relevant) so callers can surface it without a second pass.
        """
        if not documents:
            return []

        model = self._get_model()
        doc_texts = [doc.page_content for doc in documents]
        scores = list(model.rerank(query, doc_texts))

        scored_docs = list(zip(documents, scores))
        scored_docs.sort(key=lambda pair: pair[1], reverse=True)

        top_docs = []
        for doc, score in scored_docs[:top_n]:
            doc.metadata["rerank_score"] = float(score)
            top_docs.append(doc)

        return top_docs
