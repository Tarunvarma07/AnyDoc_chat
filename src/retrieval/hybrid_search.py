import logging
import time
from typing import List, Dict, Tuple
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from src.pipeline.embed_store import EmbedStore

logger = logging.getLogger(__name__)

class HybridRetriever:
    def __init__(self, embed_store: EmbedStore, k: int = 60, top_n: int = 5):
        self.embed_store = embed_store
        self.k = k # RRF constant
        self.top_n = top_n
        
        # Build the initial BM25 index from all stored documents
        self.docs = []
        self.bm25 = None
        self.rebuild_index()
        
        # Register for future updates so we don't go stale
        self.embed_store.register_callback(self.rebuild_index)
        
    def rebuild_index(self):
        """Pulls all documents from the vector store and rebuilds the BM25 index."""
        all_docs = self.embed_store.get_all_documents()
        self.docs = all_docs
        
        if all_docs:
            tokenized_corpus = [self._tokenize(doc.page_content) for doc in all_docs]
            self.bm25 = BM25Okapi(tokenized_corpus)
            logger.info(f"Built BM25 index over {len(all_docs)} documents.")
        else:
            self.bm25 = None
            logger.warning("No documents found in store to build BM25 index.")

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenizer for BM25. Converts to lowercase and splits on whitespace."""
        return text.lower().split()

    def _rrf(self, dense_results: List[Document], sparse_results: List[Document]) -> List[Document]:
        """Applies Reciprocal Rank Fusion to merge dense and sparse results."""
        rrf_scores = {}
        
        # We use a tuple (page_content, chunk_index) as a unique key for Documents
        def doc_key(doc: Document) -> tuple:
            return (doc.page_content, str(doc.metadata.get('chunk_index', '')))
            
        doc_map = {}
        
        # Rank dense results
        for rank, doc in enumerate(dense_results, start=1):
            key = doc_key(doc)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (self.k + rank)
            doc_map[key] = doc
            
        # Rank sparse results
        for rank, doc in enumerate(sparse_results, start=1):
            key = doc_key(doc)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (self.k + rank)
            doc_map[key] = doc
            
        # Sort by RRF score descending
        sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        
        # Return top N
        fused_docs = [doc_map[key] for key in sorted_keys[:self.top_n]]
        return fused_docs

    def get_relevant_documents(self, query: str) -> List[Document]:
        """Runs the hybrid search and returns the top fused results."""
        start_time = time.time()
        if not self.docs or not self.bm25:
            logger.warning("HybridRetriever has no documents. Returning empty list.")
            return []
            
        # 1. Sparse Search (BM25)
        tokenized_query = self._tokenize(query)
        # Get top N candidates from sparse
        sparse_scores = self.bm25.get_scores(tokenized_query)
        
        # Filter and sort docs by score
        scored_docs = [(doc, score) for doc, score in zip(self.docs, sparse_scores) if score > 0]
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        sparse_results = [doc for doc, score in scored_docs[:self.top_n]]
        
        # 2. Dense Search (Chroma)
        retriever = self.embed_store.as_retriever(search_kwargs={"k": self.top_n})
        dense_results = retriever.invoke(query)
        
        # 3. Fuse
        fused_results = self._rrf(dense_results, sparse_results)
        return fused_results
