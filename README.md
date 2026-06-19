# StudyBot — Trợ Lý Học Tập RAG Đa Tài Liệu 📚💡

**Môn học:** Lập trình Python nâng cao  
**Công nghệ chính:** Python 3.11, FastAPI, RAG (Retrieval-Augmented Generation)

---

## 🎯 Giới Thiệu

**StudyBot** là một ứng dụng hỗ trợ học tập thông minh được xây dựng hoàn toàn bằng Python, cho phép người dùng tải lên tài liệu học tập (PDF/TXT) và tương tác với nội dung thông qua các tính năng:

- **💬 Hỏi đáp (Query)**: Đặt câu hỏi và nhận câu trả lời dựa trên nội dung tài liệu đã chọn.
- **📝 Tạo đề trắc nghiệm (Quiz)**: Sinh tự động bộ câu hỏi trắc nghiệm từ tài liệu.
- **🔖 Tạo Flashcard**: Sinh thẻ ghi nhớ để ôn tập nhanh.
- **📄 Tóm tắt (Summary)**: Tóm tắt nội dung tài liệu.

> **Cốt lõi**: Sử dụng kỹ thuật **RAG (Retrieval-Augmented Generation)** — trích xuất nội dung từ tài liệu, truy vấn và tổng hợp câu trả lời thông qua mô hình ngôn ngữ lớn, đảm bảo câu trả lời luôn có căn cứ từ tài liệu gốc.

---

## 🏛️ Kiến Trúc Phần Mềm (Python Architecture)

Hệ thống được tổ chức theo kiến trúc **Layered Architecture** kết hợp với **Adapter Pattern** để dễ dàng chuyển đổi giữa backend local (phát triển) và backend cloud (triển khai).

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (HTML/JS)                        │
│            Giao diện người dùng SPA tối giản                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (REST API via fetch)
┌──────────────────────────▼──────────────────────────────────┐
│              API Layer (src/app.py)                           │
│         FastAPI Application với các Route Endpoints           │
│    /health │ /upload │ /docs/list │ /query │ /quiz │ ...     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│           Business Logic Layer (src/handlers.py)              │
│   Xử lý RAG Pipeline: Extract → Ingest → Retrieve → Generate │
│   Quản lý user sessions, quiz generation, flashcard creation │
└──────┬──────────┬──────────────┬──────────────┬─────────────┘
       │          │              │              │
┌──────▼────┐ ┌──▼──────┐ ┌───▼─────┐ ┌──────▼──────────┐
│ AI Adapter│ │ Storage  │ │ Vector  │ │ UserStore       │
│ src/ai.py │ │ src/     │ │ src/    │ │ src/userstore.py│
│           │ │storage.py│ │vector.py│ │                 │
└───────────┘ └─────────┘ └─────────┘ └─────────────────┘
       │              │              │               │
┌──────▼────┐ ┌──▼──────┐ ┌───▼─────┐ ┌──────▼──────────┐
│  Claude   │ │  S3/    │ │Bedrock  │ │  DynamoDB/      │
│   Haiku   │ │ LocalFS │ │  KB /   │ │  SQLite/        │
│  (boto3)  │ │ (pathlib)│ │Keyword  │ │  Postgres       │
└───────────┘ └─────────┘ └─────────┘ └─────────────────┘
```

### 🧩 Factory Pattern — Trái Tim Của Tính Linh Hoạt

File `src/adapters/factory.py` sử dụng **Factory Pattern** để khởi tạo đúng adapter dựa trên biến môi trường:

```python
# src/adapters/factory.py
def create_ai_backend() -> AIBackend:
    match config.AI_BACKEND:
        case "bedrock": return BedrockAI()
        case "local":   return LocalAI()
        case _:         raise ValueError(f"Unknown AI backend: {config.AI_BACKEND}")

def create_storage_backend() -> StorageBackend:
    match config.STORAGE_BACKEND:
        case "s3":    return S3Storage()
        case "local": return LocalStorage()
        case _:       raise ValueError(f"Unknown storage backend: {config.STORAGE_BACKEND}")
```

Mỗi adapter kế thừa một **abstract base class** (ABC) định nghĩa interface chung:

| Abstract Class | Local Implementation | Cloud Implementation |
|:---|---:|---:|
| `AIBackend` | `LocalAI` (stub) | `BedrockAI` (boto3) |
| `StorageBackend` | `LocalStorage` (pathlib) | `S3Storage` (boto3) |
| `VectorBackend` | `LocalVector` (keyword index) | `BedrockKBVector` (boto3) |
| `UserStoreBackend` | `SQLiteUserStore` (sqlite3) | `DynamoDBUserStore` (boto3) |

---

## 📂 Cấu Trúc Mã Nguồn Python Chi Tiết

```
studybot/
├── src/                              # 📦 Core Python package
│   ├── __init__.py
│   ├── app.py                        # FastAPI app — routes, middleware, Pydantic models
│   ├── config.py                     # Cấu hình từ biến môi trường (pydantic-settings)
│   ├── handlers.py                   # Business logic — RAG pipeline xử lý câu hỏi
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── ai.py                     # AI backend: BedrockAI | LocalAI
│   │   ├── factory.py                # Factory pattern — chọn backend theo config
│   │   ├── storage.py                # Storage backend: S3Storage | LocalStorage
│   │   ├── userstore.py             # User store: DynamoDB | Postgres | SQLite
│   │   └── vector.py                # Vector store: Bedrock KB | Local keyword
│   └── utils/
│       ├── __init__.py
│       ├── chunking.py              # Chunking văn bản thành các đoạn nhỏ
│       └── extraction.py            # Trích xuất text từ PDF, TXT
├── frontend/
│   └── index.html                   # 🌐 Giao diện Single Page Application (HTML+CSS+JS)
├── sample_data/                     # 📚 Dữ liệu mẫu (5 Wikipedia articles)
├── requirements.txt                 # 📋 Dependencies Python
├── requirements-lambda.txt          # Dependencies cho AWS Lambda (rút gọn)
├── deploy.sh                        # Script deploy bằng shell
├── package_lambda.py                # Script Python đóng gói Lambda
└── terraform/                       # 🏗️ IaC (Terraform — dành cho triển khai cloud)
    ├── main.tf
    ├── variables.tf
    └── outputs.tf
```

---

## 🔬 Giải Thích Các Module Python Chính

### 1. `src/config.py` — Quản Lý Cấu Hình

Sử dụng thư viện `pydantic-settings` (tích hợp sẵn trong Pydantic v2) để load cấu hình từ biến môi trường:

```python
# src/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    AI_BACKEND: str = "local"               # local | bedrock
    AI_MODEL_ID: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    STORAGE_BACKEND: str = "local"          # local | s3
    STORAGE_BUCKET: str = ""
    USERSTORE_BACKEND: str = "sqlite"       # sqlite | dynamodb | postgres
    VECTOR_BACKEND: str = "local"           # local | bedrock_kb
    LOCAL_UPLOAD_DIR: str = "_data/uploads"
    LOCAL_DB_PATH: str = "_data/studybot.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

config = Settings()  # Singleton
```

**Điểm mạnh Python:**
- Kế thừa `BaseSettings` cho phép tự động đọc từ `.env` và biến môi trường.
- Kiểm tra kiểu dữ liệu (type checking) tự động.
- Giá trị mặc định giúp chạy local không cần config.

### 2. `src/app.py` — FastAPI Application & Pydantic Models

```python
# src/app.py (trích đoạn)
from fastapi import FastAPI, UploadFile, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="StudyBot API")

class QueryRequest(BaseModel):
    question: str
    doc_ids: Optional[list[str]] = None       # 🆕 Multi-select documents

class QuizRequest(BaseModel):
    num_questions: int = 5
    doc_ids: Optional[list[str]] = None

@app.post("/query")
async def handle_query(req: QueryRequest, x_user_id: str = Header(...)):
    return handle_query_business(req, x_user_id)
```

**Điểm mạnh Python:**
- Sử dụng `Pydantic BaseModel` để validate dữ liệu đầu vào tự động (type hints + runtime validation).
- `FastAPI` hỗ trợ async/await, tận dụng I/O non-blocking cho các calls đến Bedrock/S3.
- `Union` / `Optional` cho phép API tương thích ngược (client cũ chỉ gửi `doc_id` string).

### 3. `src/handlers.py` — RAG Pipeline Logic

Luồng xử lý câu hỏi (RAG Pipeline) được triển khai hoàn toàn bằng Python:

```
[1] Extract text từ tài liệu đã chọn (S3 / Local filesystem)
         │
[2] Chunk văn bản thành các đoạn nhỏ (src/utils/chunking.py)
         │
[3] Retrieve các chunk liên quan nhất (Local keyword / Bedrock KB)
         │
[4] Build context + Prompt gửi tới LLM (Claude Haiku)
         │
[5] Parse response → Extract citations → Trả về frontend
```

```python
# src/handlers.py (trích đoạn — xử lý query với multi-document)
async def handle_query(req, user_id):
    # Lấy danh sách tài liệu
    docs = await storage.list_documents(user_id)
    if req.doc_ids:
        docs = [d for d in docs if d["doc_id"] in req.doc_ids]

    # Trích xuất nội dung
    contexts = []
    for doc in docs:
        text = await storage.get_document(user_id, doc["doc_id"])
        chunks = chunk_text(text)
        contexts.extend(chunks[:3])  # Top chunks

    # Build prompt với citations
    prompt = build_prompt_with_citations(contexts, docs)

    # Gọi LLM
    response = await ai.generate(prompt, system_prompt=SYSTEM_PROMPT)
    return response
```

### 4. `src/adapters/ai.py` — BedrockAI Adapter

```python
# src/adapters/ai.py (trích đoạn)
import boto3

class BedrockAI(AIBackend):
    def __init__(self):
        self.client = boto3.client("bedrock-runtime")

    async def generate(self, prompt: str, **kwargs) -> dict:
        response = self.client.converse(
            modelId=config.AI_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.7},
        )
        return self._parse_response(response)

    def _parse_response(self, response: dict) -> dict:
        """Parse response trả về citations cho frontend."""
        text = response["output"]["message"]["content"][0]["text"]
        citations = self._extract_citations(text)
        return {"answer": text, "citations": citations}
```

### 5. `src/utils/extraction.py` — Trích Xuất Văn Bản

Hỗ trợ trích xuất từ nhiều định dạng tài liệu:

```python
# src/utils/extraction.py
def extract_text(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    match ext:
        case ".txt":   return Path(file_path).read_text(encoding="utf-8")
        case ".pdf":   return _extract_pdf(file_path)       # pypdf
        case ".md":    return Path(file_path).read_text(encoding="utf-8")
        case _:        raise ValueError(f"Unsupported format: {ext}")
```

---

## ✨ Tính Năng Nâng Cao (Original Python Code)

### 🗂️ 1. Multi-select Documents (Lọc Nhiều Tài Liệu)

**Vấn đề:** API truyền thống chỉ nhận một `doc_id` duy nhất. Người dùng muốn so sánh hoặc hỏi trên nhiều tài liệu cùng lúc.

**Giải pháp Python:**
- Backend nhận tham số `doc_ids: Optional[list[str]]` trong Pydantic models.
- Frontend quản lý mảng `selectedDocIds` và gửi qua `JSON.stringify()`.
- Backend lọc danh sách document dựa trên mảng này trước khi xây dựng context.

```python
# Backend: lọc tài liệu dựa trên mảng doc_ids
if req.doc_ids:
    documents = [doc for doc in all_docs if doc["doc_id"] in req.doc_ids]
```

### 📚 2. Citation Legend (Danh Sách Trích Dẫn)

**Vấn đề:** AI có thể trả lời sai hoặc "ảo tưởng" (hallucination). Người dùng cần biết câu trả lời dựa trên nguồn nào.

**Giải pháp Python:**
- Backend trả về thêm trường `citations` bên cạnh `answer`.
- Mỗi citation là một object `{"index": 1, "title": "filename.pdf", "doc_id": "..."}`.
- Frontend hiển thị box **"📚 Sources Referenced"** tự động bên dưới mỗi tin nhắn.

```python
# Backend citations format
response = {
    "answer": "Quang hợp là quá trình... [1]... ",
    "citations": [
        {"index": 1, "title": "Photosynthesis.txt", "doc_id": "abc123"},
        {"index": 2, "title": "Biology_101.pdf", "doc_id": "def456"}
    ]
}
```

### 🎨 3. Giao Diện Tối Giản Vercel Style

Giao diện frontend sử dụng HTML/CSS/JS thuần, thiết kế theo phong cách tối giản:
- **Font**: Geist (sans-serif) & Geist Mono (code).
- **Màu sắc**: Achromatic — trắng `#ffffff`, chữ đen `#171717`, viền xám `#e5e5e5`.
- **Responsive**: Tương thích mobile và desktop.

---

## 🚀 Hướng Dẫn Chạy Local (Python Development)

### Yêu cầu
- Python 3.11+
- pip (Python package manager)

### Cài đặt

```bash
# Bước 1: Clone repository
git clone <repo-url>
cd studybot

# Bước 2: Tạo virtual environment (Python best practice)
python -m venv .venv

# Bước 3: Kích hoạt venv
# Trên Linux/macOS:
source .venv/bin/activate
# Trên Windows:
.venv\Scripts\activate

# Bước 4: Cài đặt dependencies
pip install -r requirements.txt
```

### Cấu hình

Sao chép file `.env.example` thành `.env` (mặc định chạy local, không cần AWS):

```bash
cp .env.example .env
```

Nội dung `.env.example`:
```
AI_BACKEND=local
STORAGE_BACKEND=local
USERSTORE_BACKEND=sqlite
VECTOR_BACKEND=local
```

### Chạy ứng dụng

```bash
# Khởi động FastAPI server với hot-reload (dành cho phát triển)
uvicorn src.app:app --reload --port 8000
```

Mở trình duyệt tại `http://localhost:8000` để sử dụng giao diện.

---

## 🧪 Kiểm Thử API (Ví dụ với curl)

```bash
# 1. Kiểm tra health
curl http://localhost:8000/health

# 2. Upload tài liệu
curl -X POST http://localhost:8000/upload \
  -H "X-User-Id: student_01" \
  -F "file=@sample_data/wiki_01_computer.txt"

# 3. Liệt kê tài liệu
curl http://localhost:8000/docs/list -H "X-User-Id: student_01"

# 4. Hỏi đáp — sử dụng tất cả tài liệu
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-User-Id: student_01" \
  -d '{"question": "Máy tính là gì?"}'

# 5. Hỏi đáp — lọc theo tài liệu cụ thể (multi-select)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-User-Id: student_01" \
  -d '{
    "question": "So sánh máy tính và internet?",
    "doc_ids": ["doc_uuid_1", "doc_uuid_2"]
  }'

# 6. Sinh quiz
curl -X POST http://localhost:8000/quiz \
  -H "Content-Type: application/json" \
  -H "X-User-Id: student_01" \
  -d '{"num_questions": 5}'
```

---

## 📦 Thư Viện Python Sử Dụng

| Thư viện | Phiên bản | Mục đích |
|:---|---:|:---|
| `fastapi` | ≥0.115 | Web framework async, tự động generate OpenAPI docs |
| `uvicorn` | ≥0.34 | ASGI server để chạy FastAPI |
| `pydantic` | ≥2.0 | Data validation bằng Python type hints |
| `pydantic-settings` | ≥2.0 | Quản lý cấu hình từ `.env` |
| `boto3` | ≥1.35 | AWS SDK cho Python (Bedrock, S3, DynamoDB) |
| `mangum` | ≥0.19 | Adapter chạy FastAPI trên AWS Lambda |
| `python-multipart` | ≥0.0.18 | Xử lý file upload |
| `pypdf` | ≥5.0 | Trích xuất text từ file PDF |
| `python-dotenv` | ≥1.0 | Load biến môi trường từ `.env` |

---

## 🧠 Design Patterns Trong Python

### 1. Factory Pattern (`src/adapters/factory.py`)
Cho phép chọn backend implementation lúc runtime dựa trên config string:
```python
storage = create_storage_backend()  # Trả về S3Storage hoặc LocalStorage
```

### 2. Adapter Pattern (`src/adapters/ai.py`, `storage.py`, ...)
Mỗi backend implement cùng interface (Abstract Base Class):
```python
class AIBackend(ABC):
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> dict: ...
```

### 3. Singleton Pattern (`src/config.py`)
`Settings` chỉ được khởi tạo một lần, dùng chung toàn bộ ứng dụng.

### 4. Dependency Injection (qua Factory)
Backend adapters được inject vào handler thông qua factory, không hardcode.

---

## 📊 Sơ Đồ Luồng Xử Lý Câu Hỏi (Query Flow)

```
Người dùng gửi câu hỏi
       │
       ▼
┌──────────────────┐
│  FastAPI Route   │  ← Xác thực user qua X-User-Id header
│  POST /query     │
└──────┬───────────┘
       │ Pydantic validation (question + doc_ids)
       ▼
┌──────────────────┐
│  handlers.py     │  ← Business logic
│  handle_query()  │
└──────┬───────────┘
       │
  ┌────┴────┐
  │         │
  ▼         ▼
Storage  Vector DB
(Lấy text  (Tìm chunk
 tài liệu)  liên quan)
  │         │
  └────┬────┘
       │ Build context + Prompt
       ▼
┌──────────────────┐
│  AI Backend      │  ← Claude Haiku / Local stub
│  generate()      │
└──────┬───────────┘
       │ Response + Citations
       ▼
┌──────────────────┐
│  Trả về JSON     │  ← {answer, citations, ...}
│  cho Frontend    │
└──────────────────┘
```

---

## 📝 Ghi Chú Phát Triển

- **Type Hints**: Toàn bộ code sử dụng Python type hints để tăng tính rõ ràng và hỗ trợ IDE.
- **Async/Await**: Tận dụng `async def` và `await` cho I/O-bound operations (gọi API, đọc file, truy vấn DB).
- **Error Handling**: Sử dụng try/except + HTTPException cho API errors.
- **Config-driven**: Mọi thứ đều có thể cấu hình qua biến môi trường — không hardcode.
- **Separation of Concerns**: Routes (app.py) ↔ Business Logic (handlers.py) ↔ Data Access (adapters/).
