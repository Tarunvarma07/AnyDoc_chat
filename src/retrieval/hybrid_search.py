import logging
import re
import threading
import time
from typing import List, Dict, Tuple
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from src.pipeline.embed_store import EmbedStore

logger = logging.getLogger(__name__)

# A word, optionally joined to more words by "-" or "." - so identifiers such as
# "ZX-4471", "v1.4.2" and "config.yaml" stay single tokens, while surrounding
# punctuation ("ZX-4471?", "(see 3.8.1)") is dropped.
_TOKEN_PATTERN = re.compile(r"\w+(?:[-.]\w+)*")

class HybridRetriever:
    def __init__(self, embed_store: EmbedStore, k: int = 60, top_n: int = 5, reranker=None, candidate_n: int = None):
        self.embed_store = embed_store
        self.k = k # RRF constant
        self.top_n = top_n
        self.reranker = reranker
        # When a reranker is attached, pull a wider candidate pool from dense/sparse
        # search before fusing, so the cross-encoder has more than top_n documents
        # to re-score. Without a reranker, behavior is unchanged from before.
        self.candidate_n = candidate_n or (top_n * 3 if reranker else top_n)
        self.last_run_stats = {}

        # Build the initial BM25 index from all stored documents
        self._rebuild_lock = threading.Lock()
        self.docs = []
        self.bm25 = None
        self.rebuild_index()
        
        # Register for future updates so we don't go stale
        self.embed_store.register_callback(self.rebuild_index)
        
    def rebuild_index(self):
        """Pulls all documents from the vector store and rebuilds the BM25 index."""
        # Serialized: two ingests rebuilding in parallel could otherwise finish
        # out of order, leaving the older read (missing the other ingest's
        # chunks) as the published index.
        with self._rebuild_lock:
            all_docs = self.embed_store.get_all_documents()

            bm25 = None
            if all_docs:
                tokenized_corpus = [self._tokenize(doc.page_content) for doc in all_docs]
                bm25 = BM25Okapi(tokenized_corpus)
                logger.info(f"Built BM25 index over {len(all_docs)} documents.")
            else:
                logger.warning("No documents found in store to build BM25 index.")

            # Queries read the (docs, index) pair through this single attribute, so
            # one running concurrently in another request thread during an ingest
            # never pairs the new docs list with the old index's scores.
            self._snapshot = (all_docs, bm25)
            self.docs, self.bm25 = all_docs, bm25

    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenizer for BM25: lowercase word/identifier tokens. Splitting on
        whitespace alone left punctuation attached, so the query "What is
        ZX-4471?" produced the token "zx-4471?", which never matched the
        document's "zx-4471" - the exact-match case BM25 is here for.
        """
        return _TOKEN_PATTERN.findall(text.lower())

    def _rrf(self, dense_results: List[Document], sparse_results: List[Document], top_n: int = None) -> List[Document]:
        """Applies Reciprocal Rank Fusion to merge dense and sparse results."""
        n = top_n if top_n is not None else self.top_n
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
        fused_docs = [doc_map[key] for key in sorted_keys[:n]]
        return fused_docs

    def get_relevant_documents(self, query: str) -> List[Document]:
        """Runs the hybrid search, optionally reranks, and returns the top results."""
        start_time = time.time()
        docs, bm25 = self._snapshot
        if not docs or not bm25:
            logger.warning("HybridRetriever has no documents. Returning empty list.")
            return []

        fetch_n = self.candidate_n

        # 1. Sparse Search (BM25)
        tokenized_query = self._tokenize(query)
        # Get top candidates from sparse
        sparse_scores = bm25.get_scores(tokenized_query)

        # Filter and sort docs by score
        scored_docs = [(doc, score) for doc, score in zip(docs, sparse_scores) if score > 0]
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        sparse_results = [doc for doc, score in scored_docs[:fetch_n]]

        # 2. Dense Search (Chroma)
        retriever = self.embed_store.as_retriever(search_kwargs={"k": fetch_n})
        dense_results = retriever.invoke(query)

        # 3. Fuse
        fused_results = self._rrf(dense_results, sparse_results, top_n=fetch_n)
        candidates_considered = len(fused_results)

        # 4. Optional cross-encoder rerank narrows the candidate pool to top_n.
        # Without a reranker, fetch_n == top_n so this is just a no-op slice.
        if self.reranker is not None:
            fused_results = self.reranker.rerank(query, fused_results, top_n=self.top_n)
        else:
            fused_results = fused_results[:self.top_n]

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        # Exposed for callers (e.g. the API layer) that want to surface pipeline
        # internals - e.g. an inspectable retrieval trace in the UI - without
        # changing this method's return type.
        self.last_run_stats = {
            "candidates_considered": candidates_considered,
            "reranked": self.reranker is not None,
            "elapsed_ms": elapsed_ms,
        }
        logger.debug(f"Hybrid retrieval completed in {elapsed_ms}ms (reranked={self.reranker is not None})")
        return fused_results
