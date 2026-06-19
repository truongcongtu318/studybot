"""AWS Production Configuration. Read all settings from env vars."""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Config:
    # AWS Settings (Defaults to Bedrock & S3)
    ai_backend: str = _env("AI_BACKEND", "bedrock")
    ai_model_id: str = _env("AI_MODEL_ID", "anthropic.claude-3-5-haiku-20241022-v1:0")
    aws_region: str = _env("AWS_REGION", "us-east-1")  # us-east-1 typically has bedrock models

    # Storage (Defaults to S3)
    storage_backend: str = _env("STORAGE_BACKEND", "s3")
    storage_bucket: str = _env("STORAGE_BUCKET", "")  # MUST BE SET IN ENV

    # UserStore (Defaults to DynamoDB)
    userstore_backend: str = _env("USERSTORE_BACKEND", "dynamodb")
    userstore_table: str = _env("USERSTORE_TABLE", "")  # MUST BE SET IN ENV
    userstore_postgres_url: str = _env("USERSTORE_POSTGRES_URL", "")

    # Vector (Defaults to Bedrock KB)
    vector_backend: str = _env("VECTOR_BACKEND", "bedrock_kb")
    vector_bedrock_kb_id: str = _env("VECTOR_BEDROCK_KB_ID", "")  # MUST BE SET IN ENV

    # Identity
    default_user_id: str = _env("DEFAULT_USER_ID", "test-user-001")

    # Logging
    log_level: str = _env("LOG_LEVEL", "INFO")

    # Frontend serving (Optional in AWS)
    serve_frontend: bool = _env("SERVE_FRONTEND", "true").lower() == "true"
    cors_origins: str = _env("CORS_ORIGINS", "*")


config = Config()
