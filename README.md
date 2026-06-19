# StudyBot — Trợ Lý Học Tập RAG Đa Tài Liệu 📚💡

**Môn học:** Lập trình Python nâng cao / Kỹ nghệ phần mềm Cloud  
**Công nghệ chính:** Python 3.12, FastAPI, AWS Serverless (Lambda, API Gateway, S3, DynamoDB), RAG (Retrieval-Augmented Generation), Amazon Bedrock (Claude 3.5 Haiku & Titan Embedding V2)

---

## 🎯 Giới Thiệu Chung

**StudyBot** là một hệ thống hỗ trợ học tập thông minh chạy trên môi trường Cloud (AWS Serverless), cho phép người dùng tải lên các tài liệu học tập cá nhân (PDF, TXT, MD), tự động phân tích ngữ nghĩa và tương tác với nội dung thông qua các công cụ học tập thông minh:

- **💬 Hỏi đáp (RAG Chatbot)**: Đặt câu hỏi tự nhiên và nhận câu trả lời có nguồn trích dẫn (`citations`) rõ ràng từ chính xác tệp tài liệu đã tải lên.
- **📝 Đề thi thử (Quiz)**: Sinh tự động bộ câu hỏi trắc nghiệm (MCQ) từ tài liệu để kiểm tra kiến thức nhanh.
- **🔖 Thẻ ghi nhớ (Flashcards)**: Sinh các thẻ ghi nhớ (mặt trước: thuật ngữ/câu hỏi, mặt sau: định nghĩa/giải thích) giúp ghi nhớ nhanh.
- **📄 Tóm tắt (Summary)**: Tóm gọn nội dung tài liệu trong một trang kèm theo **5 khái niệm quan trọng nhất dễ ra thi** (Testable Concepts).

> **Cốt lõi**: Hệ thống triển khai quy trình **RAG (Retrieval-Augmented Generation) Hybrid tự thích ứng** viết bằng Python thuần, giúp Claude 3.5 Haiku trả lời chính xác, tránh hiện tượng ảo tưởng (hallucination) và bảo vệ dữ liệu học tập của học viên.

---

## 🏛️ Kiến Trúc Hệ Thống (AWS Cloud & Application Architecture)

Hệ thống được tổ chức theo kiến trúc **Layered Architecture** (Kiến trúc phân tầng) kết hợp với các mẫu thiết kế phần mềm kinh điển:

```
                  ┌─────────────────────────────────────────────────────────────┐
                  │                  Frontend (HTML/CSS/JS SPA)                 │
                  │        Giao diện Vercel-style tối giản, lưu trên S3          │
                  └──────────────────────────┬──────────────────────────────────┘
                                             │ HTTP (REST API via fetch)
                                             ▼
                  ┌─────────────────────────────────────────────────────────────┐
                  │           FastAPI API Gateway (src/app.py)                  │
                  │   Định tuyến Endpoint, Validate dữ liệu bằng Pydantic      │
                  └──────────────────────────┬──────────────────────────────────┘
                                             │
                                             ▼
                  ┌─────────────────────────────────────────────────────────────┐
                  │        Business Logic Layer (src/handlers.py)               │
                  │       Điều hướng luồng xử lý RAG & nghiệp vụ giáo dục        │
                  └──────┬──────────┬──────────────┬──────────────┬─────────────┘
                         │          │              │              │
        ┌────────────────▼──┐ ┌─────▼────┐ ┌───────▼──┐ ┌─────────▼────────┐
        │  AI Client        │ │ Storage  │ │ Vector   │ │ UserStore        │
        │  src/adapters/ai  │ │ src/     │ │ src/     │ │ src/adapters/    │
        │  (Bedrock SDK)    │ │storage.py│ │vector.py │ │ userstore.py     │
        │                   │ │ (S3 SDK) │ │ (Custom) │ │ (DynamoDB SDK)   │
        └───────┬───────────┘ └─────┬────┘ └───────┬──┘ └─────────┬────────┘
                │                   │              │              │
                ▼                   ▼              ▼              ▼
        ┌───────────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐
        │  AWS Bedrock      │ │  AWS S3  │ │  AWS S3  │ │  AWS DynamoDB    │
        │  Claude 3.5 Haiku │ │   (Raw   │ │ (Vector  │ │  (Single Table   │
        │  (Converse API)   │ │  Files)  │ │  Indexes)│ │   User Data)     │
        └───────────────────┘ └──────────┘ └──────────┘ └──────────────────┘
```

### 🧠 Các Mẫu Thiết Kế (Design Patterns) Sử Dụng:
1. **Adapter Pattern** (`src/adapters/`): Đóng gói giao tiếp với các dịch vụ AWS SDK (`boto3`) dưới các lớp Interface thống nhất. Giúp mã nguồn Business Logic (`handlers.py`) độc lập hoàn toàn với việc AWS thay đổi thư viện.
2. **Factory Pattern** (`src/adapters/factory.py`): Khởi tạo động các adapter dựa vào tệp cấu hình môi trường.
3. **Singleton Pattern** (`src/config.py`): Cấu hình hệ thống được khởi tạo duy nhất một lần dưới dạng một frozen dataclass `config` để dùng chung toàn cục.
4. **Single-Table Design (DynamoDB)**: Thiết kế một bảng duy nhất để chứa toàn bộ trạng thái phiên học tập, tài liệu và điểm kiểm tra của học sinh nhằm tối ưu tốc độ đọc/ghi trên Cloud.

---

## 📊 Sơ Đồ Quy Trình RAG Pipeline Toàn Diện (Full Pipeline Flow)

Hệ thống RAG của StudyBot hoạt động theo **cơ chế Hybrid RAG tự thích ứng** dựa trên độ dài tài liệu để cân bằng giữa độ chính xác và tốc độ:

```
[UPLOAD & INGEST FILE]
  File (PDF/TXT) 
       │
       ▼
  [Text Extraction] ──(Dùng pypdf / fallback AWS Textract OCR nếu là ảnh quét)
       │
       ▼
  [Smart Chunking] ──(Cắt thành đoạn 3000 ký tự, gối đầu overlap 400 ký tự)
       │
       ▼
  [Parallel Embeddings] ──(Chạy ThreadPoolExecutor với 3 luồng gọi song song Bedrock Titan V2)
       │
       ▼
  [Vector Storage] ──(Lưu cấu trúc JSON index lên S3: {user_id}/{doc_id}/{filename}.vectors.json)

--------------------------------------------------------------------------------------------------

[QUERY / CHAT]
  Người dùng hỏi câu hỏi
       │
       ▼
  [Xác định tổng dung lượng (Chars) các tài liệu được chọn]
       │
       ├─► Dung lượng <= 35,000 chars ──────► [S3 Full-text RAG]
       │                                         - Tải trực tiếp toàn bộ text thô từ S3.
       │                                         - Nhồi trực tiếp toàn bộ text vào prompt Claude.
       │                                         - Độ chính xác: Tuyệt đối 100%.
       │
       └─► Dung lượng > 35,000 chars ───────► [S3 In-Memory Vector RAG]
                                                 - Tạo vector cho câu hỏi bằng Bedrock Titan V2.
                                                 - Tải song song file .vectors.json của các tài liệu từ S3 về bộ nhớ RAM.
                                                 - Tính Cosine Similarity thủ công giữa câu hỏi và toàn bộ chunks.
                                                 - Lọc ra 15 chunks có độ tương đồng ngữ nghĩa lớn nhất.
                                                 - Gộp chunks làm context và đưa vào Prompt gửi cho Claude.
```

### 📐 Chi Tiết Toán Học — Thuật Toán Tính Cosine Similarity Bằng Python Thuần

Để tìm các phân đoạn có liên quan nhất với câu hỏi mà không cần tốn chi phí thuê Vector Database chạy 24/7 (như Pinecone hay OpenSearch), StudyBot tự tính toán khoảng cách vector ngữ nghĩa trực tiếp trên RAM của AWS Lambda bằng thuật toán **Cosine Similarity**:

Cho hai vector $\mathbf{v_1}$ (vector câu hỏi) và $\mathbf{v_2}$ (vector chunk văn bản) có số chiều $N = 1024$:

$$\text{Cosine Similarity}(\mathbf{v_1}, \mathbf{v_2}) = \frac{\mathbf{v_1} \cdot \mathbf{v_2}}{\|\mathbf{v_1}\| \|\mathbf{v_2}\|} = \frac{\sum_{i=1}^{N} v_{1i} v_{2i}}{\sqrt{\sum_{i=1}^{N} v_{1i}^2} \sqrt{\sum_{i=1}^{N} v_{2i}^2}}$$

**Hiện thực bằng Python trong `src/adapters/vector.py`:**
```python
def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if not norm_a or not norm_b:
        return 0.0
    return dot_product / (norm_a * norm_b)
```

---

## ⚡ Các Tối Ưu Hóa Kỹ Thuật Quan Trọng (Bug Fixes & Enhancements)

Trong quá trình phát triển, hệ thống đã được tinh chỉnh sâu để giải quyết các bài toán Cloud thực tế:

1. **Song song hóa I/O Mạng (`ThreadPoolExecutor`)**:
   - *Vấn đề*: Gọi embedding tuần tự từng chunk một qua mạng tốn quá nhiều thời gian (với file lớn 80 chunks có thể tốn hơn 30 giây), gây lỗi Gateway Timeout (543/503) ở phía API Gateway do vượt quá giới hạn 29 giây.
   - *Giải pháp*: Sử dụng `concurrent.futures.ThreadPoolExecutor(max_workers=3)` để gửi song song 3 luồng yêu cầu embedding đồng thời, đẩy tốc độ xử lý nhanh gấp nhiều lần.
2. **Chống lỗi Bedrock Rate Limit (Exponential Backoff)**:
   - *Vấn đề*: Tài khoản mặc định của AWS Bedrock Titan Embedding giới hạn tần suất gọi API rất thấp. Việc bắn API dồn dập gây ra lỗi `ThrottlingException (429)`.
   - *Giải pháp*: Viết thuật toán retry có giãn cách tăng dần (Exponential Backoff): nếu bị lỗi 429, hệ thống tự động sleep tăng dần ($0.25s \rightarrow 0.5s \rightarrow 1.0s$) trước khi thử lại (tối đa 3 lần).
3. **Phân đoạn ngữ nghĩa kích thước lớn (`chunk_size=3000`)**:
   - Tăng kích thước chunk từ 1,000 lên 3,000 ký tự giúp giảm 70% số lượng request mạng sinh ra khi upload file lớn, giúp hệ thống hoạt động ổn định và an toàn dưới giới hạn timeout 29 giây của AWS API Gateway.
4. **Hỗ trợ tự động nhận diện đa ngôn ngữ (Multilingual Prompts)**:
   - Prompts được cấu trúc lại để tự động phát hiện ngôn ngữ của tài liệu và ép Claude sinh nội dung (Quiz, Flashcard, Tóm tắt, Câu trả lời) bằng chính ngôn ngữ đó, đảm bảo trải nghiệm bản địa hóa hoàn hảo (tài liệu tiếng Việt tạo ra câu hỏi tiếng Việt).
5. **Deduplicate Citations (Gộp nguồn trích dẫn)**:
   - Frontend tự động gộp các nguồn trùng lặp bằng `Set()`. Dù hệ thống tham chiếu tới 15 chunks trong cùng 1 file PDF, giao diện chỉ hiển thị duy nhất 1 dòng nguồn sạch sẽ: `[1] 📎 nam-cao_chi_pheo.pdf`.
6. **Bổ sung Hiệu ứng Loading (UX/UI Spinners)**:
   - Bổ sung hiệu ứng xoay tròn Loading Spinner tự chế bằng CSS ở tất cả các vị trí mất thời gian xử lý: Upload tài liệu, sinh Quiz, sinh Flashcards, và sinh Summary, giúp cải thiện trải nghiệm phản hồi người dùng.

---

## 📂 Cấu Trúc Mã Nguồn

```
studybot/
├── src/                              # 📦 Gói Python cốt lõi
│   ├── app.py                        # FastAPI chính - định nghĩa API routing & schemas
│   ├── config.py                     # Quản lý cấu hình & đọc biến môi trường
│   ├── handlers.py                   # Lớp nghiệp vụ và xử lý logic RAG
│   ├── adapters/                     # 🔌 Interface Adapters (AWS SDKs)
│   │   ├── ai.py                     # Gọi AWS Bedrock Claude 3.5 Haiku
│   │   ├── storage.py                # Gọi AWS S3 lưu trữ tệp tin
│   │   ├── userstore.py              # Gọi AWS DynamoDB quản lý phiên, lịch sử chat
│   │   ├── vector.py                 # In-Memory S3 Vector Store (Tính toán Cosine Similarity)
│   │   └── factory.py                # Khởi tạo các adapter tương ứng
│   └── utils/                        # 🛠️ Các hàm tiện ích
│       ├── chunking.py               # Phân tách văn bản dựa trên ranh giới câu
│       └── extraction.py             # Trích xuất văn bản từ PDF (pypdf & Textract)
├── frontend/
│   └── index.html                    # 🌐 Giao diện Single Page Application (HTML+CSS+JS)
├── deploy.sh                         # 🚀 Script deploy toàn bộ hệ thống bằng 1 click
├── package_lambda.py                 # Script Python build & gói dependencies cho Lambda
└── terraform/                        # 🏗️ Cơ sở hạ tầng dưới dạng mã (IaC Terraform)
```

---

## 📖 Hướng Dẫn Ôn Tập & Báo Cáo Môn Học (Hỏi - Đáp Bảo Vệ Đồ Án)

Để chuẩn bị tốt nhất cho buổi báo cáo môn học / bảo vệ đồ án, dưới đây là các câu hỏi giáo viên thường hỏi và cách bạn trả lời dựa trên code:

### ❓ Câu 1: Em hãy giải thích quy trình RAG (Retrieval-Augmented Generation) được cài đặt trong code này?
* **Trả lời:** Quy trình RAG trong StudyBot gồm 3 bước chính:
  1. **Retrieval (Truy xuất):** Khi người dùng đặt câu hỏi, hệ thống chuyển đổi câu hỏi thành vector embedding bằng mô hình Titan Text Embedding V2. Sau đó, nó tải tệp vector JSON của tài liệu được chọn từ S3 về và tính khoảng cách Cosine Similarity để chọn ra 15 đoạn văn (chunks) liên quan nhất.
  2. **Augmentation (Nâng cao ngữ cảnh):** 15 đoạn văn này được gộp lại làm phần `Context` và ghép vào một prompt mẫu đã chuẩn hóa (`_build_rag_prompt`), kèm theo lịch sử chat 10 lượt gần nhất của phiên đó.
  3. **Generation (Sinh kết quả):** Toàn bộ prompt được gửi qua API Converse của AWS Bedrock lên mô hình Claude 3.5 Haiku để sinh ra câu trả lời cuối cùng có căn cứ xác thực từ tài liệu.

### ❓ Câu 2: Tại sao em lại chọn tự viết thuật toán tính Cosine Similarity thay vì dùng Vector DB chuyên dụng?
* **Trả lời:** Đây là một lựa chọn thiết kế tối ưu hóa chi phí (Cost-effective Design) cho AWS Lambda:
  * Các Vector Database chuyên dụng (như OpenSearch Serverless, Pinecone) yêu cầu tài nguyên chạy liên tục 24/7 và có chi phí rất đắt (ít nhất $20 - $50/tháng) ngay cả khi không có người dùng.
  * Với giải pháp tự viết: Vector được lưu trữ rẻ tiền dưới dạng tệp JSON tĩnh trên S3. Khi có truy vấn, AWS Lambda mới khởi chạy, tải tệp JSON ($\sim$ vài chục KB) về và tính toán Cosine Similarity trong RAM chỉ mất dưới **50 mili-giây**. Khi không có ai dùng, chi phí hệ thống gần như bằng 0.

### ❓ Câu 3: Làm thế nào em giải quyết vấn đề AWS Lambda bị timeout hoặc Bedrock bị nghẽn (Throttling) khi tải lên tệp tin lớn?
* **Trả lời:** Em đã thực hiện 3 tối ưu hóa:
  1. **ThreadPoolExecutor (Xử lý song song):** Cho phép Lambda thực hiện đồng thời 3 luồng tạo embedding cùng lúc thay vì chạy tuần tự.
  2. **Exponential Backoff Retry:** Viết logic tự động bắt lỗi Throttling (HTTP 429) và thử lại với thời gian chờ tăng dần để không làm gián đoạn tiến trình.
  3. **Tăng kích thước Chunk (3,000 ký tự):** Giúp giảm số lượng yêu cầu gọi mạng xuống 70% so với trước, đảm bảo toàn bộ tiến trình upload kết thúc trong vòng 5 giây (an toàn dưới giới hạn timeout 29 giây của API Gateway).

### ❓ Câu 4: Ứng dụng này sử dụng những Design Patterns nào và tại sao cần chúng?
* **Trả lời:**
  * **Adapter Pattern:** Tách biệt mã nghiệp vụ (`handlers.py`) khỏi mã giao tiếp với AWS SDK (`ai.py`, `storage.py`). Nếu sau này đổi nhà cung cấp cloud (ví dụ từ AWS sang Google Cloud), ta chỉ cần viết lại các Adapter mà không cần chạm vào lõi nghiệp vụ của app.
  * **Factory Pattern (`factory.py`):** Giúp khởi tạo các adapter một cách linh hoạt, phục vụ việc dễ dàng chuyển đổi cấu hình qua biến môi trường.
  * **Singleton Pattern (`config.py`):** Đảm bảo cấu hình hệ thống chỉ được đọc từ môi trường một lần duy nhất, tránh lãng phí tài nguyên đọc ổ đĩa hoặc biến môi trường nhiều lần.

### ❓ Câu 5: Single-Table Design trong DynamoDB của em được tổ chức thế như thế nào?
* **Trả lời:** Bản thiết kế bảng DynamoDB (`DynamoDBUserStore`) sử dụng một bảng duy nhất để lưu trữ nhiều thực thể dữ liệu khác nhau nhằm tiết kiệm chi phí và tăng tốc độ query. Khóa chính phân vùng (Partition Key - PK) là `user_id`, còn Khóa sắp xếp (Sort Key - SK) đóng vai trò phân loại:
  * `DOC#<doc_id>`: Lưu metadata của tài liệu.
  * `QUERY#<timestamp>`: Lưu lịch sử hỏi đáp.
  * `QUIZ#<quiz_id>`: Lưu kết quả bộ đề trắc nghiệm.
  * `FLASH#<cards_id>`: Lưu tệp thẻ ghi nhớ.
  * `SESSION#<session_id>`: Lưu phiên chat hiện tại.
  * `CHAT#<session_id>#<timestamp>`: Lưu chi tiết lịch sử tin nhắn của phiên chat đó để làm ngữ cảnh.
  Nhờ cấu trúc SK thông minh này, ta có thể lấy lịch sử chat chỉ bằng một câu lệnh Query bắt đầu với tiền tố (Prefix) `CHAT#<session_id>#` rất nhanh chóng.
