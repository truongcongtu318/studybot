"""Vector store adapter — In-Memory S3-based Vector RAG.

This adapter chunks text, calls Bedrock Titan Embedding V2 to generate embeddings,
saves vectors as JSON files in S3, and retrieves/searches them on the fly
by computing Cosine Similarity directly in Lambda memory.
"""
import json
import logging
import math
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if not norm_a or not norm_b:
        return 0.0
    return dot_product / (norm_a * norm_b)


class S3VectorStore:
    """S3-backed In-Memory Vector Store.
    
    Generates Titan Embeddings and stores vector representations as JSON on S3,
    performing lightweight cosine similarity searches in Lambda memory.
    """

    def __init__(self, bucket_name: str, region: str):
        import boto3
        self.bucket_name = bucket_name
        self.region = region
        self.s3 = boto3.client("s3", region_name=region)
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)

    def _get_embedding(self, text: str) -> List[float]:
        """Call Amazon Bedrock Titan Text Embeddings V2 with exponential backoff retry."""
        import time
        max_retries = 3
        base_delay = 0.25  # seconds

        body = json.dumps({
            "inputText": text,
            "dimensions": 1024,
            "normalize": True
        })

        for attempt in range(max_retries):
            try:
                resp = self.bedrock.invoke_model(
                    body=body,
                    modelId="amazon.titan-embed-text-v2:0",
                    accept="application/json",
                    contentType="application/json"
                )
                resp_body = json.loads(resp["body"].read())
                return resp_body.get("embedding", [])
            except Exception as e:
                err_msg = str(e)
                # Check for throttling exception or rate limits
                if "Throttling" in err_msg or "RateLimit" in err_msg or "429" in err_msg or "TooManyRequests" in err_msg:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Embedding throttled. Retrying in {delay:.2f}s (Attempt {attempt + 1}/{max_retries})...")
                    time.sleep(delay)
                else:
                    logger.error(f"Error calling Bedrock Titan Embedding: {e}")
                    break

        # Return zero vector on failure
        return [0.0] * 1024

    def ingest_chunks(self, user_id: str, doc_id: str, filename: str, chunks: List[str], metadata: Optional[Dict[str, Any]] = None) -> None:
        """Generate embeddings for all chunks in parallel and save them as a single JSON file on S3."""
        if not chunks:
            return

        logger.info(f"Ingesting vector index for {filename} ({len(chunks)} chunks) in parallel...")

        valid_chunks = []
        for i, chunk in enumerate(chunks):
            chunk_text = chunk.strip()
            if chunk_text:
                valid_chunks.append((i, chunk_text))

        if not valid_chunks:
            return

        from concurrent.futures import ThreadPoolExecutor
        import time

        def process_chunk(item):
            idx, chunk_text = item
            vector = self._get_embedding(chunk_text)

            chunk_metadata = {
                "user_id": user_id,
                "doc_id": doc_id,
                "filename": filename,
                "chunk_idx": idx
            }
            if metadata:
                chunk_metadata.update(metadata)

            time.sleep(0.01)  # small gap

            return {
                "text": chunk_text,
                "vector": vector,
                "metadata": chunk_metadata
            }

        # Request embeddings in parallel (light concurrency to avoid Bedrock throttling)
        with ThreadPoolExecutor(max_workers=3) as executor:
            vector_data = list(executor.map(process_chunk, valid_chunks))

        # Save to S3: {user_id}/{doc_id}/{filename}.vectors.json
        key = f"{user_id}/{doc_id}/{filename}.vectors.json"
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(vector_data, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json"
            )
            logger.info(f"Successfully saved {len(vector_data)} vectors to S3: {key}")
        except Exception as e:
            logger.error(f"Failed to save vectors to S3 for {filename}: {e}")

    def delete_doc(self, user_id: str, doc_id: str) -> None:
        """Delete all vector files for this doc_id on S3."""
        prefix = f"{user_id}/{doc_id}/"
        try:
            list_resp = self.s3.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            for obj in list_resp.get("Contents", []):
                if obj["Key"].endswith(".vectors.json"):
                    self.s3.delete_object(Bucket=self.bucket_name, Key=obj["Key"])
                    logger.info(f"Deleted vector file from S3: {obj['Key']}")
        except Exception as e:
            logger.error(f"Failed to delete vector files for doc_id {doc_id} on S3: {e}")

    def search(self, query: str, top_k: int = 5, filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search vectors matching a query and filters (used by quiz/flashcard generators)."""
        if not filter or "user_id" not in filter:
            return []

        user_id = filter["user_id"]
        doc_id = filter.get("doc_id")

        if doc_id:
            doc_ids = [doc_id]
        else:
            try:
                list_resp = self.s3.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=f"{user_id}/"
                )
                keys = [obj["Key"] for obj in list_resp.get("Contents", []) if obj["Key"].endswith(".vectors.json")]
                doc_ids = list(set(key.split("/")[1] for key in keys if len(key.split("/")) >= 2))
            except Exception as e:
                logger.error(f"Error listing user doc prefixes on S3: {e}")
                return []

        return self.search_docs(query=query, user_id=user_id, doc_ids=doc_ids, top_k=top_k)

    def search_docs(self, query: str, user_id: str, doc_ids: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        """Search across specific documents for this user using Cosine Similarity."""
        if not doc_ids:
            return []

        # Get query embedding
        query_vector = self._get_embedding(query)
        if not any(query_vector):
            return []

        all_matches = []

        for doc_id in doc_ids:
            # We need to find the filename for this doc_id
            # However, since the key format is {user_id}/{doc_id}/{filename}.vectors.json,
            # we can list S3 objects in prefix {user_id}/{doc_id}/ to find the .vectors.json file.
            prefix = f"{user_id}/{doc_id}/"
            try:
                list_resp = self.s3.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=prefix
                )
                keys = [obj["Key"] for obj in list_resp.get("Contents", []) if obj["Key"].endswith(".vectors.json")]
                if not keys:
                    logger.warning(f"No vector file found on S3 for doc_id {doc_id}")
                    continue

                # Load vectors.json
                vector_key = keys[0]
                obj_resp = self.s3.get_object(Bucket=self.bucket_name, Key=vector_key)
                vector_data = json.loads(obj_resp["Body"].read().decode("utf-8"))

                # Compute similarities
                for entry in vector_data:
                    sim = cosine_similarity(query_vector, entry["vector"])
                    all_matches.append({
                        "text": entry["text"],
                        "doc_id": doc_id,
                        "score": sim,
                        "metadata": entry["metadata"]
                    })
            except Exception as e:
                logger.error(f"Error searching vectors of doc_id {doc_id} on S3: {e}")
                continue

        # Sort matches by cosine similarity score descending
        all_matches = sorted(all_matches, key=lambda x: x["score"], reverse=True)
        return all_matches[:top_k]
