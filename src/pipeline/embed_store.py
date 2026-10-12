import os
import hashlib
import logging
from typing import List
from langchain_core.documents import Document
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma

logger = logging.getLogger(__name__)

class EmbedStore:
    def __init__(self, persist_directory: str = "./chroma_db", model_name: str = "sentence-transformers/all-MiniLM-L6-v2", collection_name: str = "qa_chatbot", embeddings=None):
        self.persist_directory = persist_directory
        self.model_name = model_name
        self.collection_name = collection_name

        # Initialize embeddings (runs locally, ONNX runtime via fastembed - no
        # torch/CUDA dependency, which matters a lot on memory-constrained
        # hosts. Same underlying model weights as the original HuggingFace/
        # sentence-transformers path, just a much lighter runtime.)
        #
        # An already-constructed embeddings object can be passed in to reuse
        # an already-loaded model instead of loading a second copy into
        # memory - e.g. the /evaluate endpoint builds a temporary, isolated
        # EmbedStore for its benchmark corpus but should reuse the production
        # embed_store's warm model rather than instantiating a duplicate ONNX
        # session, which mattered on a memory-constrained host (see Case 1 in
        # the technical report; this pattern prevents the same class of bug
        # recurring in a different code path).
        self.embeddings = embeddings if embeddings is not None else FastEmbedEmbeddings(model_name=self.model_name)
        
        # Initialize Chroma
        self.vector_store = Chroma(
            collection_name=self.collection_name,
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory
        )
        
        # Consistency Check: Validate embedding model matches what is stored
        self._check_model_consistency()
        
        # Callbacks for systems that need to know when the store updates (like BM25)
        self.on_document_added_callbacks = []
        
    def _check_model_consistency(self):
        """
        Ensures the embedding model used during initialization matches
        the model that was originally used to create the collection.
        This prevents silent scoring failures where query and docs are embedded differently.
        """
        collection = self.vector_store._collection
        stored_model_name = collection.metadata.get("embedding_model_name") if collection.metadata else None
        
        if stored_model_name is None:
            # Collection is likely new or metadata wasn't set. We set it now.
            new_metadata = collection.metadata or {}
            new_metadata["embedding_model_name"] = self.model_name
            collection.modify(metadata=new_metadata)
            logger.info(f"Initialized new Chroma collection with embedding model: {self.model_name}")
        elif stored_model_name != self.model_name:
            raise ValueError(
                f"Embedding model mismatch! Configured: '{self.model_name}', "
                f"but collection was created with: '{stored_model_name}'. "
                "You must use the same model for both ingestion and querying, or clear the database."
            )
        else:
            logger.info(f"Embedding model consistency check passed: {self.model_name}")

    def register_callback(self, callback):
        """Registers a function to be called whenever new documents are added."""
        self.on_document_added_callbacks.append(callback)

    def add_documents(self, documents: List[Document]):
        """Embeds and stores documents in ChromaDB."""
        if not documents:
            return

        # Deterministic IDs make re-ingesting the same file/URL idempotent:
        # LangChain's Chroma wrapper upserts by ID, so identical chunks replace
        # themselves instead of piling up as duplicates that then crowd the
        # top-k results. chunk_index keeps IDs unique within one batch.
        ids = [self._chunk_id(doc) for doc in documents]
        self.vector_store.add_documents(documents, ids=ids)
        logger.info(f"Added {len(documents)} documents to vector store.")
        
        # Notify listeners that the index has changed
        for cb in self.on_document_added_callbacks:
            cb()

    @staticmethod
    def _chunk_id(doc: Document) -> str:
        key = f"{doc.metadata.get('source', '')}|{doc.metadata.get('chunk_index', '')}|{doc.page_content}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def as_retriever(self, search_kwargs=None):
        """Returns a vector store retriever."""
        return self.vector_store.as_retriever(search_kwargs=search_kwargs)

    def get_all_documents(self) -> List[Document]:
        """Utility to retrieve all documents, useful for rebuilding BM25 index."""
        results = self.vector_store.get()
        
        docs = []
        for i in range(len(results['ids'])):
            docs.append(Document(
                page_content=results['documents'][i],
                metadata=results['metadatas'][i]
            ))
        return docs
