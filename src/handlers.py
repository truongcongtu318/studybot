"""Endpoint handlers — pure business logic, AWS Bedrock only.
With robust S3-text fallback when Bedrock Knowledge Base is not configured/synced.

Features:
  - Upload with hybrid PDF extraction (pypdf → Textract fallback)
  - RAG query via Bedrock Knowledge Base (with S3 fulltext fallback + multi-turn session chat)
  - Quiz generation (MCQ from uploaded docs)
  - Flashcard generation (key concept pairs)
  - Summary generation (1-page summary + 5 most testable concepts)
  - Study dashboard (stats, activity tracking, topic coverage)
  - Document deletion
  - Chat session management (create, list, delete, multi-turn history)
"""
import json
import logging
import re
import uuid
from typing import Optional

from src.utils.extraction import extract_text
from src.utils.chunking import smart_chunk

logger = logging.getLogger(__name__)


# ============================================================================
# Prompt templates
# ============================================================================

PROMPT_QUIZ = """You are an exam question generator. Based on the following lecture content,
generate exactly {num_questions} multiple-choice questions.

RULES:
1. Each question must have exactly 4 options labeled A, B, C, D.
2. Exactly one option must be the correct answer.
3. Questions should test understanding, not just memorization.
4. Cover different topics from the content, spread across the material.
5. Include a brief explanation for why the correct answer is right.
6. Generate the questions, options, and explanations in the SAME language as the provided content (e.g., if the content is in Vietnamese, generate in Vietnamese; if in English, generate in English).

CONTENT:
{content}

Respond in valid JSON format only. No markdown, no extra text.
The JSON must be a list of objects, each with these keys:
- "question": the question text
- "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}
- "correct": the letter of the correct answer (A, B, C, or D)
- "explanation": brief explanation of why the correct answer is correct

JSON:"""

PROMPT_FLASHCARDS = """You are a study aid generator. Based on the following lecture content,
create exactly {num_cards} flashcards for effective study and review.

RULES:
1. Each flashcard has a "front" (question/term/concept) and a "back" (answer/definition/explanation).
2. Focus on key concepts, definitions, important facts, and relationships.
3. Cards should be concise but informative.
4. Cover the most important topics from the content.
5. Vary the types: definitions, comparisons, cause-effect, applications.
6. Generate all flashcard text (front, back, topic) in the SAME language as the provided content (e.g., if the content is in Vietnamese, generate in Vietnamese; if in English, generate in English).

CONTENT:
{content}

Respond in valid JSON format only. No markdown, no extra text.
The JSON must be a list of objects, each with these keys:
- "front": the question or concept (short)
- "back": the answer or explanation (1-3 sentences)
- "topic": a short topic label for categorization

JSON:"""

PROMPT_SUMMARY = """You are an expert study summarizer. Based on the following lecture content,
create a comprehensive study summary.

TASKS:
1. Write a clear, well-structured summary of the entire content (aim for about 300-500 words).
2. Identify the 5 most testable/important concepts from this material.
3. For each testable concept, explain WHY it's likely to be tested and provide a one-sentence key takeaway.
4. Generate the entire response (summary, concept, why_testable, key_takeaway) in the SAME language as the provided content (e.g., if the content is in Vietnamese, generate in Vietnamese; if in English, generate in English).

CONTENT:
{content}

Respond in valid JSON format only. No markdown, no extra text.
The JSON must be an object with these keys:
- "summary": the full summary text (string, can include newlines)
- "testable_concepts": a list of exactly 5 objects, each with:
  - "concept": name of the concept
  - "why_testable": why this concept is important/likely tested
  - "key_takeaway": one-sentence takeaway for the student

JSON:"""


# ============================================================================
# Helper: safe JSON parse from AI response
# ============================================================================

def _parse_ai_json(raw_text: str) -> any:
    """Try to parse JSON from AI response, handling common formatting issues."""
    text = raw_text.strip()
    
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for pattern in [r'\[.*\]', r'\{.*\}']:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue
        logger.warning(f"Failed to parse AI JSON response: {text[:200]}")
        return None


# ============================================================================
# Helper: build S3 RAG context + citations from documents
# ============================================================================

def _build_context_with_citations(user_id: str, userstore, storage, max_chars: int = 30000, doc_id: Optional[str] = None, doc_ids: Optional[list] = None):
    """Iterate user's docs, load text from S3, build formatted context and citations list.
    
    Supports single doc_id filter OR multi-doc_ids list filter (both optional).
    """
    docs = userstore.list_docs(user_id)
    if doc_ids:
        docs = [d for d in docs if d.get("doc_id") in doc_ids]
    elif doc_id:
        docs = [d for d in docs if d.get("doc_id") == doc_id]
    docs = sorted(docs, key=lambda d: d.get("created_at", ""), reverse=True)

    context_parts = []
    citations = []
    total_len = 0
    
    # Fair allocation: each document gets at most max_chars / num_docs chars
    num_docs = len(docs)
    if num_docs == 0:
        return "", []
    max_per_doc = max(max_chars // num_docs, 5000)

    for doc in docs:
        d_id = doc.get("doc_id")
        filename = doc.get("filename", "")
        
        key_text = doc.get("extracted_text_key")
        if not key_text:
            key_text = f"{user_id}/{d_id}/{filename}.extracted.txt"

        try:
            text_bytes = storage.get(key_text)
            text_str = text_bytes.decode("utf-8", errors="replace").strip()
        except Exception:
            try:
                raw_key = f"{user_id}/{d_id}/{filename}"
                raw_bytes = storage.get(raw_key)
                text_str = raw_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                continue

        if not text_str:
            continue

        # Truncate each doc to its fair share to prevent one doc from dominating the context
        if len(text_str) > max_per_doc:
            text_str = text_str[:max_per_doc] + "\n[Content truncated due to length limits...]"

        if total_len + len(text_str) > max_chars:
            allowed = max_chars - total_len
            if allowed > 200:
                snippet = text_str[:allowed]
                context_parts.append(f"--- START DOCUMENT: {filename} ---\n{snippet}\n--- END DOCUMENT: {filename} ---")
                citations.append({"text": f"[{len(citations)+1}] {filename} (S3 source)", "filename": filename, "snippet": snippet[:200]})
            break
        
        context_parts.append(f"--- START DOCUMENT: {filename} ---\n{text_str}\n--- END DOCUMENT: {filename} ---")
        citations.append({"text": f"[{len(citations)+1}] {filename} (S3 source)", "filename": filename, "snippet": text_str[:200]})
        total_len += len(text_str)

    return "\n\n".join(context_parts), citations


# ============================================================================
# Core handlers
# ============================================================================

def handle_create_session(user_id: str, title: str, userstore) -> dict:
    session_id = str(uuid.uuid4())
    return userstore.create_session(user_id, session_id, title)


def handle_list_sessions(user_id: str, userstore) -> list:
    return userstore.get_user_sessions(user_id)


def handle_delete_session(user_id: str, session_id: str, userstore) -> dict:
    userstore.delete_session(user_id, session_id)
    return {"status": "success", "session_id": session_id}


def handle_upload(
    user_id: str,
    filename: str,
    data: bytes,
    storage,
    userstore,
    vector_store,
    storage_backend: str = "s3",
    aws_region: str = "us-east-1",
) -> dict:
    """Store file on S3, extract text (hybrid), chunk, record metadata in DynamoDB."""
    doc_id = str(uuid.uuid4())
    key = f"{user_id}/{doc_id}/{filename}"
    location = storage.put(key, data)
    
    # Hybrid extraction (pypdf → Textract fallback for scanned pages)
    extraction_result = extract_text(filename, data, aws_region=aws_region)
    text = extraction_result["text"]
    method = extraction_result["method"]
    density = extraction_result.get("density", 0)
    num_pages = extraction_result.get("pages", 1)
    
    # Smart chunking (Tăng chunk_size để giảm số lượng request gọi embedding, tránh Bedrock throttling và tăng tốc upload)
    chunks = smart_chunk(text, chunk_size=3000, chunk_overlap=400)
    
    # Ingest into custom S3-based vector store (generate embeddings in batch)
    try:
        vector_store.ingest_chunks(
            user_id=user_id,
            doc_id=doc_id,
            filename=filename,
            chunks=chunks,
            metadata={
                "extraction_method": method,
                "num_pages": num_pages
            }
        )
    except Exception as e:
        logger.error(f"Failed embedding ingestion for {filename}: {e}")
    
    # Save extracted text as helper file in S3 for fast fallback
    extracted_text_key = f"{user_id}/{doc_id}/{filename}.extracted.txt"
    try:
        storage.put(extracted_text_key, text.encode("utf-8"))
    except Exception as e:
        logger.warning(f"Could not save extracted text helper to S3: {e}")
    
    userstore.add_doc(
        user_id=user_id,
        doc_id=doc_id,
        metadata={
            "filename": filename,
            "size": len(data),
            "location": location,
            "chars": len(text),
            "extracted_text_key": extracted_text_key,
            "extraction_method": method,
            "text_density": int(density),
            "pages": num_pages,
            "num_chunks": len(chunks),
        },
    )
    
    userstore.log_study_event(
        user_id=user_id,
        event_type="upload",
        details={"doc_id": doc_id, "filename": filename, "chars": len(text)},
    )
    
    return {
        "doc_id": doc_id,
        "filename": filename,
        "size": len(data),
        "chars_extracted": len(text),
        "extraction_method": method,
        "text_density": int(density),
        "pages": num_pages,
        "num_chunks": len(chunks),
        "location": location,
    }


def handle_query(
    user_id: str,
    question: str,
    ai_client,
    userstore,
    vector_store,
    storage,
    session_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    doc_ids: Optional[list] = None,
) -> dict:
    """RAG Q&A via Bedrock KB with S3 fulltext fallback + multi-turn chat session memory."""
    answer = ""
    citations = []
    
    # Resolve session + load chat history
    chat_history = []
    if session_id:
        chat_history = userstore.get_chat_history(user_id, session_id)
        sessions = userstore.get_user_sessions(user_id)
        if not any(s.get("session_id") == session_id for s in sessions):
            title = question[:40] + "..." if len(question) > 40 else question
            userstore.create_session(user_id, session_id, title)
    
    history_context = ""
    if chat_history:
        for msg in chat_history[-10:]:
            role_lbl = "User" if msg.get("role") == "user" else "Assistant"
            history_context += f"{role_lbl}: {msg.get('content')}\n"
    
    # Build S3 document context with proper citations (respect doc_ids / doc_id filter)
    context, s3_citations = _build_context_with_citations(user_id, userstore, storage, doc_id=doc_id, doc_ids=doc_ids)
    
    # Calculate total characters of selected docs to decide between S3 full-text and Vector Search
    docs = userstore.list_docs(user_id)
    if doc_ids:
        docs = [d for d in docs if d.get("doc_id") in doc_ids]
    elif doc_id:
        docs = [d for d in docs if d.get("doc_id") == doc_id]
    total_chars = sum(d.get("chars", 0) for d in docs)

    # Execute the right RAG path
    # If the total character size is small (<= 35000 chars),
    # we prefer S3 full-text context. This provides 100% accuracy and covers ALL documents fully.
    # Otherwise, for larger collections, we use our S3 Semantic Vector Search.
    if total_chars <= 35000:
        logger.info(f"Using S3 fulltext RAG (total chars: {total_chars})")
        if context.strip():
            # Thêm danh sách file đang chọn vào prompt để AI nắm được cấu trúc
            docs_list_str = "\n".join([f"- {d.get('filename')} ({d.get('chars', 0)} chars)" for d in docs])
            enhanced_context = f"Selected Documents List:\n{docs_list_str}\n\n{context}"
            prompt = _build_rag_prompt(enhanced_context, question, history_context)
            answer = ai_client.invoke(prompt, max_tokens=2048)
            citations = s3_citations
        else:
            answer = "You haven't uploaded any study materials yet! Please upload a PDF, TXT or Markdown file first."
    else:
        # Custom S3-backed In-Memory Vector Search (Semantic RAG)
        try:
            logger.info(f"Using S3 Semantic Vector Search (total chars: {total_chars})")
            
            target_doc_ids = doc_ids if doc_ids else [d.get("doc_id") for d in docs if d.get("doc_id")]
            
            # Search top 15 most relevant chunks from the selected documents
            chunks = vector_store.search_docs(
                query=question,
                user_id=user_id,
                doc_ids=target_doc_ids,
                top_k=15
            )
            
            kb_context = "\n\n".join([f"--- DOCUMENT: {c.get('metadata', {}).get('filename', 'Vector chunk')} ---\n{c['text']}" for c in chunks]) if chunks else ""
            if chunks:
                for c in chunks:
                    meta = c.get("metadata", {})
                    fn = meta.get("filename", "Vector chunk")
                    chunk_idx = meta.get("chunk_idx")
                    label = f"{fn} (Part {chunk_idx + 1})" if chunk_idx is not None else fn
                    citations.append({
                        "text": f"[{len(citations)+1}] {label}",
                        "filename": label,
                        "snippet": c["text"][:200]
                    })
            else:
                # Fallback to S3 fulltext citations if vector search returned no results
                citations = s3_citations
            
            final_context = kb_context if kb_context.strip() else context
            if final_context.strip():
                # Bổ sung danh sách tài liệu được chọn vào prompt
                docs_list_str = "\n".join([f"- {d.get('filename')} ({d.get('chars', 0)} chars)" for d in docs])
                enhanced_context = f"Selected Documents List:\n{docs_list_str}\n\n{final_context}"
                prompt = _build_rag_prompt(enhanced_context, question, history_context)
                answer = ai_client.invoke(prompt, max_tokens=2048)
            else:
                answer = "No content found in your documents."
        except Exception as e:
            logger.error(f"S3 Semantic Search failed: {e}. Falling back to S3 fulltext...")
            if context.strip():
                prompt = _build_rag_prompt(context, question, history_context)
                answer = ai_client.invoke(prompt, max_tokens=2048)
                citations = s3_citations
            else:
                answer = f"Error: Vector search failed and no documents available."
    
    # Save to session history if session_id is set
    if session_id:
        userstore.save_chat_message(user_id, session_id, "user", question)
        userstore.save_chat_message(user_id, session_id, "assistant", answer)
    
    userstore.log_query(user_id=user_id, query=question, answer=answer)
    userstore.log_study_event(
        user_id=user_id,
        event_type="query",
        details={"question": question[:200], "num_citations": len(citations), "session_id": session_id},
    )
    return {"question": question, "answer": answer, "citations": citations, "session_id": session_id}


def _build_rag_prompt(context: str, question: str, history: str) -> str:
    history_part = f"Conversation History:\n{history}\n" if history else ""
    return (
        f"You are a professional, helpful study AI assistant. Your goal is to answer the user's question based ONLY on the provided document context below.\n\n"
        f"Context:\n{context}\n\n"
        f"{history_part}"
        f"Instructions:\n"
        f"1. Rely only on clear facts directly mentioned in the context. Do NOT assume, extrapolate, or bring in outside knowledge.\n"
        f"2. If the answer cannot be found in the context, politely state: 'I cannot find the answer to this question in the uploaded documents.'\n"
        f"3. Format your response beautifully using clean markdown (bolding, bullet points, headers, or code blocks where appropriate).\n"
        f"4. Cite the documents you use by appending inline tags like [1] or [2] (where [1] corresponds to the first document file mentioned in the context, [2] corresponds to the second, etc.) at the end of the sentences that refer to facts from those documents.\n"
        f"5. Answer in the SAME language as the user's question or the document context (e.g., if they ask in Vietnamese, reply in Vietnamese; if in English, reply in English).\n\n"
        f"User: {question}\n\n"
        f"Assistant:"
    )


def handle_quiz(
    user_id: str,
    doc_id: Optional[str],
    doc_ids: Optional[list],
    num_questions: int,
    ai_client,
    userstore,
    vector_store,
    storage,
) -> dict:
    """Generate MCQs from Bedrock KB or S3 fallback."""
    content = ""
    filter_kwargs = {"user_id": user_id}
    if doc_id:
        filter_kwargs["doc_id"] = doc_id
        
    chunks = vector_store.search("main topics key concepts definitions", top_k=20, filter=filter_kwargs)
    
    # Filter locally by doc_ids if present
    if doc_ids:
        chunks = [c for c in chunks if c.get("metadata", {}).get("doc_id") in doc_ids or c.get("doc_id") in doc_ids]
        
    if chunks:
        parts = []
        total = 0
        for c in chunks:
            if total + len(c["text"]) > 4000:
                break
            parts.append(c["text"])
            total += len(c["text"])
        content = "\n\n".join(parts)

    if not content.strip():
        content, _ = _build_context_with_citations(user_id, userstore, storage, max_chars=30000, doc_id=doc_id, doc_ids=doc_ids)

    if not content.strip():
        return {"error": "No study materials found. Please upload a document first.", "quiz_id": None, "questions": []}

    prompt = PROMPT_QUIZ.format(num_questions=num_questions, content=content)
    raw = ai_client.invoke(prompt, max_tokens=2048)
    questions = _parse_ai_json(raw)

    if questions is None:
        return {"error": "AI could not produce valid MCQ JSON.", "quiz_id": None, "questions": []}

    quiz_id = str(uuid.uuid4())
    quiz_data = questions if isinstance(questions, list) else [questions]
    userstore.save_quiz(user_id=user_id, quiz_id=quiz_id, doc_id=doc_id or "all", quiz_data=quiz_data)
    userstore.log_study_event(user_id=user_id, event_type="quiz_generated", details={"quiz_id": quiz_id, "num_questions": len(quiz_data)})

    return {"quiz_id": quiz_id, "doc_id": doc_id or "all", "doc_ids": doc_ids, "num_questions": len(quiz_data), "questions": quiz_data}


def handle_flashcards(
    user_id: str,
    doc_id: Optional[str],
    doc_ids: Optional[list],
    num_cards: int,
    ai_client,
    userstore,
    vector_store,
    storage,
) -> dict:
    """Generate flashcards from content."""
    content = ""
    filter_kwargs = {"user_id": user_id}
    if doc_id:
        filter_kwargs["doc_id"] = doc_id
        
    chunks = vector_store.search("important terms vocabulary definitions formula facts", top_k=20, filter=filter_kwargs)
    
    # Filter locally by doc_ids if present
    if doc_ids:
        chunks = [c for c in chunks if c.get("metadata", {}).get("doc_id") in doc_ids or c.get("doc_id") in doc_ids]
        
    if chunks:
        parts = []
        total = 0
        for c in chunks:
            if total + len(c["text"]) > 4000:
                break
            parts.append(c["text"])
            total += len(c["text"])
        content = "\n\n".join(parts)

    if not content.strip():
        content, _ = _build_context_with_citations(user_id, userstore, storage, max_chars=30000, doc_id=doc_id, doc_ids=doc_ids)

    if not content.strip():
        return {"error": "No study materials found. Please upload a document first.", "cards_id": None, "flashcards": []}

    prompt = PROMPT_FLASHCARDS.format(num_cards=num_cards, content=content)
    raw = ai_client.invoke(prompt, max_tokens=2048)
    cards = _parse_ai_json(raw)

    if cards is None:
        return {"error": "AI could not produce valid Flashcard JSON.", "cards_id": None, "flashcards": []}

    cards_id = str(uuid.uuid4())
    cards_data = cards if isinstance(cards, list) else [cards]
    userstore.save_flashcards(user_id=user_id, cards_id=cards_id, doc_id=doc_id or "all", flashcards_data=cards_data)
    userstore.log_study_event(user_id=user_id, event_type="flashcards_generated", details={"cards_id": cards_id, "num_cards": len(cards_data)})

    return {"cards_id": cards_id, "doc_id": doc_id or "all", "doc_ids": doc_ids, "num_cards": len(cards_data), "flashcards": cards_data}


def handle_summary(
    user_id: str,
    doc_id: Optional[str],
    doc_ids: Optional[list],
    ai_client,
    userstore,
    storage,
) -> dict:
    """Generate summary from content."""
    content, _ = _build_context_with_citations(user_id, userstore, storage, max_chars=30000, doc_id=doc_id, doc_ids=doc_ids)

    if not content.strip():
        return {"error": "No study materials found to summarize.", "summary": "No study materials found to summarize.", "testable_concepts": [], "doc_id": doc_id or "all", "doc_ids": doc_ids}

    prompt = PROMPT_SUMMARY.format(content=content)
    raw = ai_client.invoke(prompt, max_tokens=2048)
    
    # Fast extract fields if JSON fails
    data = _parse_ai_json(raw)
    if data is None:
        return {"summary": raw, "testable_concepts": [], "doc_id": doc_id or "all", "doc_ids": doc_ids}

    summary = data.get("summary", "")
    testable = data.get("testable_concepts", [])

    userstore.log_study_event(
        user_id=user_id,
        event_type="summary_generated",
        details={"doc_id": doc_id or "all", "testable_count": len(testable)},
    )
    return {"summary": summary, "testable_concepts": testable, "doc_id": doc_id or "all", "doc_ids": doc_ids}


def handle_dashboard(user_id: str, userstore) -> dict:
    """Build study dashboard with statistics and activity history."""
    docs = userstore.list_docs(user_id)
    queries = userstore.recent_queries(user_id, limit=50)
    events = userstore.get_study_events(user_id, limit=50)
    quizzes = userstore.get_quizzes(user_id)
    flashcards = userstore.get_flashcards(user_id)

    total_docs = len(docs)
    total_chars = sum(d.get("chars", 0) for d in docs)
    total_queries = len(queries)
    total_quizzes = len(quizzes)
    total_flashcard_sets = len(flashcards)
    total_flashcards = sum(len(f.get("flashcards_data", [])) for f in flashcards)
    total_quiz_questions = sum(len(q.get("quiz_data", [])) for q in quizzes)
    topics_studied = list({d.get("filename", "unknown") for d in docs})

    activity = []
    for event in events[:20]:
        activity.append({
            "type": event.get("event_type", "unknown"),
            "details": event.get("details", {}),
            "timestamp": event.get("created_at", ""),
        })

    event_dates = set()
    for event in events:
        created = event.get("created_at", "")
        if created:
            event_dates.add(created[:10])

    return {
        "user_id": user_id,
        "stats": {
            "total_documents": total_docs,
            "total_characters_studied": total_chars,
            "total_queries": total_queries,
            "total_quizzes_generated": total_quizzes,
            "total_quiz_questions": total_quiz_questions,
            "total_flashcard_sets": total_flashcard_sets,
            "total_flashcards": total_flashcards,
            "unique_study_days": len(event_dates),
        },
        "topics_studied": topics_studied,
        "recent_activity": activity,
        "documents": docs,
    }


def handle_list_docs(user_id: str, userstore) -> dict:
    return {"user_id": user_id, "docs": userstore.list_docs(user_id)}


def handle_delete_doc(user_id: str, doc_id: str, userstore, storage, vector_store) -> dict:
    """Delete document metadata and all associated storage assets."""
    doc = userstore.get_doc(user_id, doc_id)
    if not doc:
        return {"status": "not_found", "doc_id": doc_id}

    filename = doc.get("filename", "")

    # Delete raw file
    raw_key = f"{user_id}/{doc_id}/{filename}"
    try:
        storage.delete(raw_key)
    except Exception as e:
        logger.warning(f"Failed to delete raw file {raw_key}: {e}")

    # Delete extracted text helper
    ext_key = doc.get("extracted_text_key") or f"{user_id}/{doc_id}/{filename}.extracted.txt"
    try:
        storage.delete(ext_key)
    except Exception as e:
        logger.warning(f"Failed to delete extracted text {ext_key}: {e}")

    # Delete vector index from S3
    try:
        vector_store.delete_doc(user_id, doc_id)
    except Exception as e:
        logger.warning(f"Failed to delete vector index for doc_id {doc_id}: {e}")

    # Delete metadata from DynamoDB
    userstore.delete_doc(user_id, doc_id)

    userstore.log_study_event(
        user_id=user_id,
        event_type="delete_doc",
        details={"doc_id": doc_id, "filename": filename},
    )

    return {"status": "deleted", "doc_id": doc_id, "filename": filename}


def handle_recent_queries(user_id: str, userstore, limit: int = 10) -> dict:
    return {"user_id": user_id, "queries": userstore.recent_queries(user_id, limit=limit)}
