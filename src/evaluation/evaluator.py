import json
from src.retrieval.hybrid_search import HybridRetriever

class Evaluator:
    def __init__(self, retriever: HybridRetriever, eval_file: str = "eval_set.json"):
        self.retriever = retriever
        with open(eval_file, "r") as f:
            self.eval_set = json.load(f)

    def calculate_hit_rate(self) -> dict:
        """
        Calculates the Hit Rate for Dense (Vector only) vs Hybrid Retrieval.
        A 'hit' is when the expected substring is present in at least one of the retrieved chunks.
        """
        dense_hits = 0
        hybrid_hits = 0
        total = len(self.eval_set)

        for item in self.eval_set:
            query = item["query"]
            expected = item["expected_substring"].lower()
            
            # 1. Test Dense Only
            # Retrieve top 5 to see the actual rank for debugging
            dense_retriever = self.retriever.embed_store.as_retriever(search_kwargs={"k": 5})
            dense_docs = dense_retriever.invoke(query)
            
            rank = -1
            for idx, doc in enumerate(dense_docs):
                if expected in doc.page_content.lower():
                    rank = idx + 1
                    break
                    
            print(f"Query: '{query}' | Dense Rank: {rank if rank != -1 else 'Not in top 5'}")
            
            dense_hit = rank != -1 and rank <= 2
            if dense_hit:
                dense_hits += 1
                
            # 2. Test Hybrid
            self.retriever.top_n = 2
            hybrid_docs = self.retriever.get_relevant_documents(query)
            hybrid_hit = any(expected in doc.page_content.lower() for doc in hybrid_docs)
            if hybrid_hit:
                hybrid_hits += 1

        return {
            "total_queries": total,
            "dense_hit_rate": dense_hits / total if total > 0 else 0.0,
            "hybrid_hit_rate": hybrid_hits / total if total > 0 else 0.0
        }

if __name__ == "__main__":
    import tempfile
    from langchain_core.documents import Document
    from src.pipeline.embed_store import EmbedStore
    
    # 1. Setup an ephemeral isolated database for evaluation.
    # ignore_cleanup_errors=True works around a Windows-specific issue where
    # Chroma's underlying sqlite connection isn't released before the temp
    # directory is torn down, which otherwise raises PermissionError here
    # even though the evaluation itself completed successfully.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        store = EmbedStore(persist_directory=temp_dir, collection_name="eval_collection")
        
        # 2. Ingest fixed, known test documents designed to stress-test Hybrid Search
        test_docs = [
            # Semantic matches (easy for both)
            Document(page_content="Reciprocal Rank Fusion (RRF) is an algorithm that combines multiple result sets.", metadata={"chunk_index": 0}),

            # Keyword test 1: Error Code
            Document(page_content="When the system crashes unexpectedly during the startup sequence, you might see a fatal error. This indicates a connection failure.", metadata={"chunk_index": 1}), # Semantic distractor
            Document(page_content="Error Code XJ-992 specifically indicates a database timeout.", metadata={"chunk_index": 2}), # Target

            # Keyword test 2: Version number
            Document(page_content="The latest update to the routing engine introduces a new load balancing algorithm that dramatically reduces latency. Highly recommended.", metadata={"chunk_index": 3}), # Semantic distractor
            Document(page_content="The routing engine upgrade in v1.4.2 fixed the latency bug.", metadata={"chunk_index": 4}), # Target

            # Keyword test 3: Specific ID
            Document(page_content="A user's transaction history shows the total spent across all accounts, grouped by merchant and timestamp.", metadata={"chunk_index": 5}), # Semantic distractor
            Document(page_content="Transaction TXN-8819 was declined due to insufficient funds.", metadata={"chunk_index": 6}), # Target

            # Keyword test 4: Order ID
            Document(page_content="When an order ships same-day via a premium carrier, customers may see faster delivery windows depending on region and courier availability.", metadata={"chunk_index": 7}), # Semantic distractor
            Document(page_content="Order #ORD-45213 was shipped via express courier on the same day.", metadata={"chunk_index": 8}), # Target

            # Keyword test 5: Rate limit value
            Document(page_content="APIs commonly throttle client requests to protect backend services from being overwhelmed during traffic spikes.", metadata={"chunk_index": 9}), # Semantic distractor
            Document(page_content="The API enforces a rate limit of 120 requests per minute per API key.", metadata={"chunk_index": 10}), # Target

            # Keyword test 6: Support ticket ID
            Document(page_content="Customer support teams often escalate unresolved issues to specialized teams when initial troubleshooting doesn't resolve the underlying problem.", metadata={"chunk_index": 11}), # Semantic distractor
            Document(page_content="Support ticket #SUP-77021 was escalated to Tier 2 after 48 hours.", metadata={"chunk_index": 12}), # Target

            # Keyword test 7: Config value
            Document(page_content="Network configuration files typically define various timeout thresholds to prevent hanging connections from consuming resources indefinitely.", metadata={"chunk_index": 13}), # Semantic distractor
            Document(page_content="The default connection timeout is set to 30 seconds in config.yaml.", metadata={"chunk_index": 14}), # Target
        ]

        # 2b. Generate heavy semantic distractors (10 per category, 9 categories = 90 total)
        for i in range(10):
            test_docs.append(Document(page_content=f"When the application routing engine encounters a bottleneck in version {i}.x, the latency spikes significantly, causing the load balancer to fail. Many software updates attempt to fix this.", metadata={"chunk_index": 100+i}))
            test_docs.append(Document(page_content=f"Error code ABC-{i} indicates a generic software crash during the boot sequence, often due to network connection timeouts or database unavailability.", metadata={"chunk_index": 110+i}))
            test_docs.append(Document(page_content=f"User transaction history for account {i} shows a declined payment due to insufficient funds at the merchant terminal during checkout.", metadata={"chunk_index": 120+i}))
            test_docs.append(Document(page_content=f"A popular ranking algorithm for search engines relies on combining multiple scores to find the best result set. It is widely used in information retrieval.", metadata={"chunk_index": 130+i}))
            test_docs.append(Document(page_content=f"Security vulnerabilities like Cross-Site Scripting (XSS) and SQL Injection are common web application attacks that need input validation, similar to forging requests.", metadata={"chunk_index": 140+i}))
            test_docs.append(Document(page_content=f"Warehouse #{i} regularly processes bulk shipments and coordinates with regional couriers to optimize same-day delivery routes.", metadata={"chunk_index": 150+i}))
            test_docs.append(Document(page_content=f"Backend service {i} applies request throttling and circuit breakers to stay within its allocated infrastructure quota during peak load.", metadata={"chunk_index": 160+i}))
            test_docs.append(Document(page_content=f"Ticket queue {i} tracks unresolved customer issues and reassigns them across support tiers based on severity and age.", metadata={"chunk_index": 170+i}))
            test_docs.append(Document(page_content=f"Deployment profile {i} defines resource limits and retry policies to keep long-running network calls from hanging indefinitely.", metadata={"chunk_index": 180+i}))

        store.add_documents(test_docs)
        
        # 3. Initialize retriever on the fixed database
        retriever = HybridRetriever(embed_store=store)
        
        # 4. Run evaluation
        evaluator = Evaluator(retriever)
        results = evaluator.calculate_hit_rate()
        print("Evaluation Results:", results)
