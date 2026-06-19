"""AI adapter — AWS Bedrock only. Converse API for direct LLM invocation."""
from typing import Any


class BedrockAI:
    """Production Amazon Bedrock client using Converse API."""

    def __init__(self, region: str, model_id: str):
        import boto3
        self.region = region
        self.model_id = model_id
        self.runtime = boto3.client("bedrock-runtime", region_name=region)

    def invoke(self, prompt: str, **kwargs: Any) -> str:
        max_tokens = kwargs.get("max_tokens", 1024)
        temperature = kwargs.get("temperature", 0.2)
        resp = self.runtime.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        )
        return resp["output"]["message"]["content"][0]["text"]
