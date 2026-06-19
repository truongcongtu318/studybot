"""FastAPI app — production cloud-only (AWS Lambda via Mangum).

Env vars required:
  AWS_REGION              e.g. us-east-1
  AI_BACKEND              bedrock (only supported)
  AI_MODEL_ID             e.g. anthropic.claude-3-5-haiku-20241022-v1:0
  STORAGE_BACKEND         s3 (only supported)
  STORAGE_BUCKET          e.g. studybot-uploads-123456789
  USERSTORE_BACKEND       dynamodb (only supported for production)
  USERSTORE_TABLE         e.g. studybot-users
  VECTOR_BACKEND          bedrock_kb (only supported)
  VECTOR_BEDROCK_KB_ID    e.g. ABCD1234-xxxx-yyyy-zzzz
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Mangum must be imported before FastAPI models to work in Lambda
try:
    from mangum import Mangum
except ImportError:
    Mangum = None

# Pydantic models
from pydantic import BaseModel

# Local imports
from src import handlers
from src.adapters import factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Schemas
# ============================================================================

class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    doc_id: Optional[str] = None
    doc_ids: Optional[List[str]] = None

class SessionCreateRequest(BaseModel):
    title: str

class QuizRequest(BaseModel):
    doc_id: Optional[str] = None
    doc_ids: Optional[List[str]] = None
    num_questions: int = 5

class FlashcardRequest(BaseModel):
    doc_id: Optional[str] = None
    doc_ids: Optional[List[str]] = None
    num_cards: int = 10

class SummaryRequest(BaseModel):
    doc_id: Optional[str] = None
    doc_ids: Optional[List[str]] = None


# FastAPI app
# ============================================================================

app = FastAPI(
    title="StudyBot API",
    description="AI Study Buddy — RAG Q&A, Quiz, Flashcards, Summary, Dashboard",
    version="1.0.0",
)

# CORS — allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _user_id(x_user_id: Optional[str] = Header(None)) -> str:
    """Extract user ID from X-User-Id header."""
    return x_user_id or os.getenv("DEFAULT_USER_ID", "test-user-001")


def _adapters():
    """Build and cache adapter instances (singleton per cold start)."""
    return {
        "ai": factory.make_ai(),
        "storage": factory.make_storage(),
        "userstore": factory.make_userstore(),
        "vector": factory.make_vector(),
    }


# ============================================================================
# Routes
# ============================================================================

@app.get("/health")
def health():
    try:
        adapters = _adapters()
        return {
            "status": "ok",
            "backends": {
                "ai": os.getenv("AI_BACKEND", "bedrock"),
                "storage": os.getenv("STORAGE_BACKEND", "s3"),
                "userstore": os.getenv("USERSTORE_BACKEND", "dynamodb"),
                "vector": os.getenv("VECTOR_BACKEND", "bedrock_kb"),
            }
        }
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/")
def root():
    return {"service": "StudyBot API", "version": "1.0.0", "endpoints": list(app.routes)}


@app.post("/upload")
async def upload(
    request: Request,
    x_user_id: Optional[str] = Header(None),
):
    """Upload a file: store in S3, extract text, chunk, log in DynamoDB, sync to Bedrock KB."""
    user_id = _user_id(x_user_id)
    try:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")
        
        filename = file.filename or "untitled"
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty file")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Upload parse error")
        raise HTTPException(status_code=400, detail=str(e))
    
    try:
        adapters = _adapters()
        result = handlers.handle_upload(
            user_id=user_id,
            filename=filename,
            data=data,
            storage=adapters["storage"],
            userstore=adapters["userstore"],
            vector_store=adapters["vector"],
            storage_backend=os.getenv("STORAGE_BACKEND", "s3"),
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
        )
        return result
    except Exception as e:
        logger.exception("Upload handler error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query")
def query(req: QueryRequest, x_user_id: Optional[str] = Header(None)):
    """RAG Q&A via Bedrock Knowledge Base."""
    user_id = _user_id(x_user_id)
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    try:
        adapters = _adapters()
        result = handlers.handle_query(
            user_id=user_id,
            question=req.question.strip(),
            ai_client=adapters["ai"],
            userstore=adapters["userstore"],
            vector_store=adapters["vector"],
            vector_backend=os.getenv("VECTOR_BACKEND", "bedrock_kb"),
            bedrock_kb_id=os.getenv("VECTOR_BEDROCK_KB_ID", ""),
            storage=adapters["storage"],
            session_id=req.session_id,
            doc_id=req.doc_id,
            doc_ids=req.doc_ids,
        )
        return result
    except Exception as e:
        logger.exception("Query error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quiz")
def quiz(req: QuizRequest, x_user_id: Optional[str] = Header(None)):
    """Generate MCQ quiz from uploaded documents (via Bedrock KB content)."""
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        result = handlers.handle_quiz(
            user_id=user_id,
            doc_id=req.doc_id,
            doc_ids=req.doc_ids,
            num_questions=min(max(req.num_questions, 1), 20),
            ai_client=adapters["ai"],
            userstore=adapters["userstore"],
            vector_store=adapters["vector"],
            vector_backend=os.getenv("VECTOR_BACKEND", "bedrock_kb"),
            storage=adapters["storage"],
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Quiz error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/flashcards")
def flashcards(req: FlashcardRequest, x_user_id: Optional[str] = Header(None)):
    """Generate interactive flashcards from document content."""
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        result = handlers.handle_flashcards(
            user_id=user_id,
            doc_id=req.doc_id,
            doc_ids=req.doc_ids,
            num_cards=min(max(req.num_cards, 1), 30),
            ai_client=adapters["ai"],
            userstore=adapters["userstore"],
            vector_store=adapters["vector"],
            vector_backend=os.getenv("VECTOR_BACKEND", "bedrock_kb"),
            storage=adapters["storage"],
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Flashcard error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/summary")
def summary(req: SummaryRequest, x_user_id: Optional[str] = Header(None)):
    """Generate 1-page summary + 5 testable concepts."""
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        result = handlers.handle_summary(
            user_id=user_id,
            doc_id=req.doc_id,
            doc_ids=req.doc_ids,
            ai_client=adapters["ai"],
            userstore=adapters["userstore"],
            vector_store=adapters["vector"],
            vector_backend=os.getenv("VECTOR_BACKEND", "bedrock_kb"),
            storage=adapters["storage"],
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Summary error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboard")
def dashboard(x_user_id: Optional[str] = Header(None)):
    """Study dashboard: stats, activity timeline, topic coverage."""
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return handlers.handle_dashboard(user_id=user_id, userstore=adapters["userstore"])
    except Exception as e:
        logger.exception("Dashboard error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/docs/list")
def list_docs(x_user_id: Optional[str] = Header(None)):
    """List all documents for the current user."""
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return handlers.handle_list_docs(user_id=user_id, userstore=adapters["userstore"])
    except Exception as e:
        logger.exception("List docs error")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/docs/{doc_id}")
def delete_doc(doc_id: str, x_user_id: Optional[str] = Header(None)):
    """Delete a document and its associated storage assets."""
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return handlers.handle_delete_doc(
            user_id=user_id,
            doc_id=doc_id,
            userstore=adapters["userstore"],
            storage=adapters["storage"],
            vector_store=adapters["vector"],
        )
    except Exception as e:
        logger.exception("Delete doc error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions")
def create_session(req: SessionCreateRequest, x_user_id: Optional[str] = Header(None)):
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return handlers.handle_create_session(user_id=user_id, title=req.title, userstore=adapters["userstore"])
    except Exception as e:
        logger.exception("Create session error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions")
def list_sessions(x_user_id: Optional[str] = Header(None)):
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return handlers.handle_list_sessions(user_id=user_id, userstore=adapters["userstore"])
    except Exception as e:
        logger.exception("List sessions error")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str, x_user_id: Optional[str] = Header(None)):
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return handlers.handle_delete_session(user_id=user_id, session_id=session_id, userstore=adapters["userstore"])
    except Exception as e:
        logger.exception("Delete session error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
def get_session_history(session_id: str, x_user_id: Optional[str] = Header(None)):
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return adapters["userstore"].get_chat_history(user_id=user_id, session_id=session_id)
    except Exception as e:
        logger.exception("Get session history error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queries/recent")
def recent_queries(
    x_user_id: Optional[str] = Header(None),
    limit: int = Query(default=10, ge=1, le=50),
):
    user_id = _user_id(x_user_id)
    try:
        adapters = _adapters()
        return handlers.handle_recent_queries(user_id=user_id, userstore=adapters["userstore"], limit=limit)
    except Exception as e:
        logger.exception("Recent queries error")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Lambda entry point (must be last)
# ============================================================================

if Mangum:
    handler = Mangum(app)
elif os.getenv("AWS_EXECUTION_ENV"):
    raise RuntimeError("Running in Lambda but Mangum is not installed!")