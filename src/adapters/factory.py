"""Factory: read env config + instantiate concrete AWS adapters."""
from src.config import config
from src.adapters import ai, storage, userstore, vector


def make_ai():
    if config.ai_backend == "bedrock":
        return ai.BedrockAI(region=config.aws_region, model_id=config.ai_model_id)
    raise ValueError(f"Unknown AI_BACKEND: {config.ai_backend!r} (expected 'bedrock')")


def make_storage():
    if config.storage_backend == "s3":
        return storage.S3Storage(bucket=config.storage_bucket, region=config.aws_region)
    raise ValueError(f"Unknown STORAGE_BACKEND: {config.storage_backend!r} (expected 's3')")


def make_userstore():
    backend = config.userstore_backend
    if backend == "dynamodb":
        return userstore.DynamoDBUserStore(table_name=config.userstore_table, region=config.aws_region)
    if backend == "postgres":
        return userstore.PostgresUserStore(url=config.userstore_postgres_url)
    if backend == "documentdb":
        return userstore.DocumentDBUserStore(
            url=config.userstore_mongo_url,
            db_name=config.userstore_mongo_db,
            tls_ca_file=config.userstore_mongo_tls_ca,
        )
    if backend == "mysql":
        return userstore.MySQLUserStore(url=config.userstore_mysql_url)
    raise ValueError(f"Unknown USERSTORE_BACKEND: {backend!r} (expected dynamodb|postgres|documentdb|mysql)")


def make_vector():
    # Always use the custom S3VectorStore for lightweight local semantic search
    return vector.S3VectorStore(bucket_name=config.storage_bucket, region=config.aws_region)
