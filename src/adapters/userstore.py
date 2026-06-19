"""User state DB adapter — AWS DynamoDB (production only).

Single-table design:
  - Partition Key (PK): `user_id`
  - Sort Key (SK): 
      * DOC#<doc_id>          -> Document metadata
      * QUERY#<timestamp>     -> Q&A history logs
      * QUIZ#<quiz_id>        -> Generated MCQ quizzes
      * FLASH#<cards_id>      -> Generated flashcards
      * EVENT#<timestamp>     -> Study activity timeline logs
      * VEC#<doc_id>#<idx>    -> Document chunk embeddings (managed by vector adapter)
"""
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DynamoDBUserStore:
    def __init__(self, table_name: str, region: str):
        import boto3
        if not table_name:
            raise ValueError("USERSTORE_TABLE must be set for DynamoDB backend")
        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def add_doc(self, user_id: str, doc_id: str, metadata: dict) -> None:
        self.table.put_item(
            Item={
                "user_id": user_id,
                "sk": f"DOC#{doc_id}",
                "doc_id": doc_id,
                "created_at": _now(),
                **metadata,
            }
        )

    def list_docs(self, user_id: str) -> list:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with("DOC#")
        )
        return resp.get("Items", [])

    def log_query(self, user_id: str, query: str, answer: str) -> None:
        ts = _now()
        self.table.put_item(
            Item={
                "user_id": user_id,
                "sk": f"QUERY#{ts}",
                "query": query,
                "answer": answer[:1000],
                "created_at": ts,
            }
        )

    def recent_queries(self, user_id: str, limit: int = 10) -> list:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with("QUERY#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return resp.get("Items", [])

    def save_quiz(self, user_id: str, quiz_id: str, doc_id: str, quiz_data: list) -> None:
        self.table.put_item(
            Item={
                "user_id": user_id,
                "sk": f"QUIZ#{quiz_id}",
                "quiz_id": quiz_id,
                "doc_id": doc_id,
                "quiz_data": quiz_data,
                "created_at": _now(),
            }
        )

    def get_quizzes(self, user_id: str, doc_id: Optional[str] = None) -> list:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with("QUIZ#")
        )
        items = resp.get("Items", [])
        if doc_id:
            items = [item for item in items if item.get("doc_id") == doc_id]
        return items

    def save_flashcards(self, user_id: str, cards_id: str, doc_id: str, flashcards_data: list) -> None:
        self.table.put_item(
            Item={
                "user_id": user_id,
                "sk": f"FLASH#{cards_id}",
                "cards_id": cards_id,
                "doc_id": doc_id,
                "flashcards_data": flashcards_data,
                "created_at": _now(),
            }
        )

    def get_flashcards(self, user_id: str, doc_id: Optional[str] = None) -> list:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with("FLASH#")
        )
        items = resp.get("Items", [])
        if doc_id:
            items = [item for item in items if item.get("doc_id") == doc_id]
        return items

    def log_study_event(self, user_id: str, event_type: str, details: dict) -> None:
        ts = _now()
        self.table.put_item(
            Item={
                "user_id": user_id,
                "sk": f"EVENT#{ts}",
                "event_type": event_type,
                "details": details,
                "created_at": ts,
            }
        )

    def get_study_events(self, user_id: str, limit: int = 20) -> list:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with("EVENT#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return resp.get("Items", [])

    def get_doc(self, user_id: str, doc_id: str) -> Optional[dict]:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").eq(f"DOC#{doc_id}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None

    def delete_doc(self, user_id: str, doc_id: str) -> None:
        self.table.delete_item(
            Key={"user_id": user_id, "sk": f"DOC#{doc_id}"}
        )

    # === Chat Session Methods ===
    def create_session(self, user_id: str, session_id: str, title: str) -> dict:
        ts = _now()
        item = {
            "user_id": user_id,
            "sk": f"SESSION#{session_id}",
            "session_id": session_id,
            "title": title,
            "created_at": ts,
        }
        self.table.put_item(Item=item)
        return item

    def get_user_sessions(self, user_id: str) -> list:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with("SESSION#")
        )
        items = resp.get("Items", [])
        return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)

    def delete_session(self, user_id: str, session_id: str) -> None:
        from boto3.dynamodb.conditions import Key
        # 1. Delete session metadata
        self.table.delete_item(
            Key={"user_id": user_id, "sk": f"SESSION#{session_id}"}
        )
        # 2. Delete all chat messages in this session
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with(f"CHAT#{session_id}#")
        )
        messages = resp.get("Items", [])
        with self.table.batch_writer() as batch:
            for msg in messages:
                batch.delete_item(Key={"user_id": user_id, "sk": msg["sk"]})

    def save_chat_message(self, user_id: str, session_id: str, role: str, content: str) -> None:
        ts = _now()
        # We append timestamp to guarantee uniqueness and sorting order
        self.table.put_item(
            Item={
                "user_id": user_id,
                "sk": f"CHAT#{session_id}#{ts}",
                "session_id": session_id,
                "role": role,
                "content": content,
                "created_at": ts,
            }
        )

    def get_chat_history(self, user_id: str, session_id: str, limit: int = 50) -> list:
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id) & Key("sk").begins_with(f"CHAT#{session_id}#"),
            Limit=limit
        )
        items = resp.get("Items", [])
        return sorted(items, key=lambda x: x.get("created_at", ""))

