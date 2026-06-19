"""Vector store adapter — AWS Bedrock Knowledge Base only.

Interface:
    ingest(doc_id, text, metadata=None) -> None
    search(query, top_k=5, filter=None) -> list[dict]
"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class BedrockKBVector:
    """Production: Bedrock Knowledge Base abstracts the vector store backend.

    Note: Ingestion is done via AWS Bedrock Sync Job triggered when new files are
    uploaded to the S3 bucket.
    """

    def __init__(self, kb_id: str, region: str):
        import boto3
        if not kb_id:
            raise ValueError("VECTOR_BEDROCK_KB_ID must be set for Bedrock KB backend")
        self.kb_id = kb_id
        self.agent_runtime = boto3.client("bedrock-agent-runtime", region_name=region)

    def ingest(self, doc_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """KB ingestion is async and triggered by S3 file upload.
        
        This method is a no-op as the backend sync is managed on AWS.
        """
        pass

    def search(self, query: str, top_k: int = 5, filter: Optional[dict] = None) -> list:
        if not self.kb_id or self.kb_id == "ABCD1234":
            logger.warning("Using dummy VECTOR_BEDROCK_KB_ID 'ABCD1234'. Skipping KB search.")
            return []
            
        kwargs = {
            "knowledgeBaseId": self.kb_id,
            "retrievalQuery": {"text": query},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": top_k
                }
            },
        }
        if filter:
            kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"] = {
                "andAll": [{"equals": {"key": k, "value": v}} for k, v in filter.items()]
            }
        
        try:
            resp = self.agent_runtime.retrieve(**kwargs)
            return [
                {
                    "text": r.get("content", {}).get("text", ""),
                    "doc_id": r.get("metadata", {}).get("doc_id", ""),
                    "score": r.get("score", 0.0),
                    "metadata": r.get("metadata", {}),
                }
                for r in resp.get("retrievalResults", [])
            ]
        except Exception as e:
            logger.error(f"Error searching Bedrock KB: {e}")
            return []
