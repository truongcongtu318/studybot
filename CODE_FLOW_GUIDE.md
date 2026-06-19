# Cẩm Nang Học & Đọc Hiểu Code StudyBot 🧠📖

Tài liệu này hướng dẫn chi tiết cách đọc, giải thích luồng chạy (flow) của các tính năng quan trọng trong ứng dụng **StudyBot**. Hãy đọc kỹ tài liệu này trước buổi báo cáo/vấn đáp môn học để nắm lòng cách code vận hành.

---

## 📂 1. Bản Đồ File (Các File Quan Trọng Nhất Cần Nhớ)

Khi thầy cô yêu cầu mở file xử lý logic, bạn cần biết ngay file đó nằm ở đâu:
* **`frontend/index.html`**: Toàn bộ giao diện SPA (Single Page Application). Chứa HTML, CSS, và các hàm JS gửi request `fetch` lên backend, nhận kết quả và render ra màn hình (bao gồm cả logic gộp nguồn trích dẫn và hiển thị loading spinner).
* **`src/app.py`**: Điểm đón nhận yêu cầu (API Router). Nơi FastAPI tiếp nhận HTTP requests từ frontend, định nghĩa các model validate dữ liệu đầu vào (Pydantic models) và gọi sang Handlers.
* **`src/handlers.py`**: Trái tim của ứng dụng (Business Logic). Chứa logic RAG, prompt templates cho Quiz/Cards/Summary, điều phối việc trích xuất văn bản, gọi AI và lưu trữ.
* **`src/adapters/vector.py`**: Bộ nhớ Vector tự viết. Nơi trích xuất vector embedding bằng Bedrock Titan V2, lưu index dạng JSON lên S3, và tự tính toán độ tương đồng toán học **Cosine Similarity**.
* **`src/adapters/userstore.py`**: Quản lý cơ sở dữ liệu DynamoDB. Chứa các câu lệnh SQL/NoSQL DynamoDB để lưu tài liệu, lịch sử chat session, quizzes.
* **`src/utils/chunking.py`**: Thuật toán cắt nhỏ văn bản dựa trên ranh giới dấu câu.
* **`src/utils/extraction.py`**: Hàm trích xuất chữ từ PDF dùng thư viện `pypdf` hoặc AWS Textract OCR.

---

## 🔄 2. Luồng 1: Upload & Tiền Xử Lý Tài Liệu (Document Ingestion Flow)

Đây là quy trình khi học sinh kéo thả hoặc chọn một tệp PDF/TXT để tải lên:

```
[HTML Input Click]
       │
       ▼ (gọi hàm JS)
[frontend/index.html: uploadFile()]
       │
       ▼ (gửi POST /upload kèm FormData)
[src/app.py: upload()]
       │
       ▼ (chuyển tiếp sang Handler)
[src/handlers.py: handle_upload()]
       │
       ├─► [src/utils/extraction.py: extract_text()] ───► Trích xuất văn bản từ PDF (OCR nếu là ảnh).
       │
       ├─► [src/utils/chunking.py: smart_chunk()] ──────► Cắt thành các chunks (3000 ký tự, overlap 400).
       │
       ├─► [src/adapters/vector.py: ingest_chunks()] ───► Sinh vector embeddings và lưu file JSON lên S3.
       │
       └─► [src/adapters/userstore.py: add_doc()] ──────► Lưu thông tin metadata của file vào DynamoDB.
```

### 🔍 Giải thích chi tiết code:
* **Smart Chunking (`src/utils/chunking.py:7` - `smart_chunk`)**:
  Hàm này sử dụng Regular Expression để tách văn bản thành các câu độc lập dựa vào các dấu kết thúc (`.`, `!`, `?`). Sau đó gộp các câu lại cho tới khi chạm ngưỡng `chunk_size` (3000 ký tự). Nhằm giữ ngữ cảnh liên mạch, hàm lấy một lượng câu gối đầu (`chunk_overlap=400` ký tự) đưa vào đầu chunk tiếp theo.
* **Parallel Embedding Ingestion (`src/adapters/vector.py:75` - `ingest_chunks`)**:
  Để tối ưu tốc độ mạng và tránh Lambda bị timeout, hàm này sử dụng lớp `ThreadPoolExecutor(max_workers=3)` của Python để gửi **3 requests đồng thời** lên API AWS Bedrock Titan Embedding. 
  Nếu AWS phản hồi lỗi Throttling (Quá giới hạn tần suất 429), phương thức `_get_embedding` tự động kích hoạt vòng lặp thử lại tối đa 3 lần có độ trễ nhân đôi (Exponential Backoff: $0.25s \rightarrow 0.5s \rightarrow 1.0s$).
  Sau khi hoàn tất, toàn bộ mảng JSON chứa `{"text": text, "vector": vector, "metadata": metadata}` được ghi trực tiếp lên S3 dưới dạng file cấu trúc `{user_id}/{doc_id}/{filename}.vectors.json`.

---

## 🔍 3. Luồng 2: Hỏi Đáp Ngữ Cảnh (RAG Query Flow)

Luồng xử lý khi người dùng nhập câu hỏi vào ô chat và nhấn gửi:

```
[Người dùng gửi câu hỏi]
       │
       ▼
[src/app.py: query()] ───(Validate X-User-Id header & Pydantic QueryRequest model)
       │
       ▼
[src/handlers.py: handle_query()]
       │
       ├─► [src/utils/extraction.py: _build_context_with_citations()] 
       │      │
       │      ├─► (Lấy text thô từ S3 của các tài liệu được chọn)
       │      └─► Tính tổng số ký tự (total_chars)
       │
       ├─► [NHÁNH A: total_chars <= 35,000] ──► S3 Full-text RAG (Nhét thẳng toàn bộ văn bản vào Prompt)
       │
       ├─► [NHÁNH B: total_chars > 35,000] ───► In-Memory Vector RAG
       │      │
       │      ├─► 1. Gọi Bedrock sinh vector cho câu hỏi.
       │      ├─► 2. Tải song song các file .vectors.json từ S3 về RAM Lambda.
       │      ├─► 3. Chạy hàm cosine_similarity() để tính điểm tương đồng.
       │      └─► 4. Chọn ra Top 15 chunks có điểm cao nhất làm Context.
       │
       ├─► [src/handlers.py: _build_rag_prompt()] ───► Ghép Context + History + Instructions
       │
       ├─► [src/adapters/ai.py: invoke()] ───────────► Gửi Prompt cho Claude 3.5 Haiku sinh câu trả lời
       │
       └─► Trả kết quả JSON kèm mảng citations về Frontend.
```

### 🔍 Giải thích chi tiết code:
* **Hàm tính tương đồng Cosine (`src/adapters/vector.py:15` - `cosine_similarity`)**:
  Hàm tính toán góc cosine giữa hai vector. Kết quả bằng `1.0` nghĩa là hai đoạn văn giống hệt nhau về mặt ngữ nghĩa, `0.0` là hoàn toàn không liên quan.
* **Lọc trùng trích dẫn trên Frontend (`frontend/index.html:704` - `citations.forEach`)**:
  Để giao diện không bị hiện lặp lại 15 dòng trùng tên file khi truy vấn vector, JavaScript sử dụng một `Set` đặt tên là `seen`. Nó duyệt qua mảng citations, cắt bỏ phần hậu tố phân đoạn (`(Part X)`) để lấy tên file gốc, và chỉ render các tên file duy nhất lên mục "Sources Referenced".

---

## 📝 4. Luồng 3: Sinh Đề Thi Thử & Flashcards (Quiz & Cards Flow)

Luồng xử lý khi người dùng chọn tab và nhấn "Generate Quiz" hoặc "Generate Flashcards":

```
[Frontend Click "Generate Quiz"]
       │
       ▼ (Hiện spinner loading và disable nút bấm)
[frontend/index.html: generateQuiz()]
       │
       ▼ (Gửi POST /quiz)
[src/app.py: quiz()]
       │
       ▼
[src/handlers.py: handle_quiz()]
       │
       ├─► [src/adapters/vector.py: search()] ───► Lọc các chunks ngữ nghĩa cốt lõi trong file vectors.json
       │                                            (Keyword: "main topics key concepts definitions")
       │
       ├─► Ghép nội dung chunks vào template PROMPT_QUIZ
       │
       ├─► Gọi Claude 3.5 Haiku sinh định dạng JSON thô
       │
       ├─► [src/handlers.py: _parse_ai_json()] ──► Tách khối code JSON (vượt qua markdown ```json)
       │
       ├─► [src/adapters/userstore.py: save_quiz()] ──► Lưu cấu trúc bộ câu hỏi vào DynamoDB
       │
       └─► Trả về danh sách câu hỏi dạng JSON cho Frontend render giao diện trắc nghiệm.
```

### 🔍 Giải thích chi tiết code:
* **Xử lý Đa ngôn ngữ (Multilingual Prompting)**:
  Trong `PROMPT_QUIZ` và `PROMPT_FLASHCARDS`, hệ thống ép mô hình phải tuân thủ luật: *"Generate the questions, options, and explanations in the SAME language as the provided content"* (Quy tắc số 6). Điều này đảm bảo khi người dùng tải lên tài liệu tiếng Việt, Claude sẽ đọc hiểu và trả về bộ Quiz hoàn toàn bằng tiếng Việt.
* **Hàm bóc tách JSON (`src/handlers.py:99` - `_parse_ai_json`)**:
  Mô hình AI thường trả về chuỗi bọc trong thẻ Markdown (ví dụ: ` ```json ... ``` `). Hàm này sử dụng biểu thức chính quy (Regex) để bóc tách phần text nằm giữa các thẻ này, sau đó gọi `json.loads` để chuyển đổi sang kiểu dữ liệu danh sách/tự điển trong Python một cách an toàn.

---

## 🗑️ 5. Luồng 4: Xóa Tài Liệu Sạch Sẽ (Document Deletion Flow)

Để tránh rò rỉ dung lượng lưu trữ trên S3, quy trình xóa tài liệu được cấu trúc dọn dẹp triệt để:

```
[Frontend click nút delete (x)]
       │
       ▼ (gọi hàm JS)
[frontend/index.html: removeDoc()]
       │
       ▼ (Gửi DELETE /docs/{doc_id})
[src/app.py: delete_doc()]
       │
       ▼
[src/handlers.py: handle_delete_doc()]
       │
       ├─► [storage.delete()] ────► Xóa tệp tài liệu gốc trên S3.
       ├─► [storage.delete()] ────► Xóa tệp trích xuất văn bản thô (.extracted.txt) trên S3.
       ├─► [vector_store.delete_doc()] ──► Tự quét tìm và xóa tệp vector (.vectors.json) trên S3.
       ├─► [userstore.delete_doc()] ─────► Xóa bản ghi thông tin file trong DynamoDB.
       │
       ▼ (Frontend nhận phản hồi)
Gọi resetTools() để xóa sạch các nội dung Summary/Quiz/Cards cũ khỏi màn hình.
```

---

## 🎓 6. Mẹo Bảo Vệ Đồ Án (Các câu hỏi vấn đáp thường gặp)

### ❓ Câu 1: Tại sao em lại cấu hình Lambda Timeout tới 180s mà API Gateway lại báo lỗi 503 sau 29 giây?
* **Trả lời:** Đây là giới hạn cứng của hạ tầng AWS. API Gateway chỉ cho phép thời gian chờ tối đa là **29 giây** cho một request và không thể tăng thêm. Nếu Lambda chạy xử lý lâu hơn 29 giây, API Gateway sẽ tự ngắt kết nối và trả về lỗi **HTTP 503**. 
* Do đó, em đã tối ưu hóa mã nguồn bằng cách tăng kích thước chunk lên 3,000 ký tự (giảm 70% số lượng request mạng sinh ra) và sử dụng xử lý luồng song song `ThreadPoolExecutor(max_workers=3)`. Hiện tại, thời gian xử lý file lớn nhất đã giảm xuống **dưới 5 giây**, đảm bảo an toàn tuyệt đối dưới hạn mức 29 giây của API Gateway.

### ❓ Câu 2: Em truyền lịch sử cuộc trò chuyện (Conversation History) vào LLM như thế nào?
* **Trả lời:** Trong hàm `handle_query` (file `handlers.py`), nếu người dùng gửi câu hỏi kèm theo `session_id`, hệ thống sẽ gọi DynamoDB (`userstore.get_chat_history`) lấy ra tối đa **10 tin nhắn gần nhất** của phiên đó.
* Các tin nhắn này được nối lại thành một chuỗi văn bản định dạng:
  `User: [Câu hỏi cũ] \n Assistant: [Câu trả lời cũ] \n`
  Chuỗi này được nhét vào biến `history` và truyền vào template prompt để Claude hiểu được ngữ cảnh hội thoại nhiều lượt (Multi-turn chat).

### ❓ Câu 3: Làm thế nào ứng dụng bảo vệ chống lại hiện tượng ảo tưởng (hallucination) của AI?
* **Trả lời:** Em đã thiết kế các chỉ dẫn nghiêm ngặt (System Prompt) trong hàm `_build_rag_prompt`:
  1. Yêu cầu mô hình chỉ trả lời dựa **duy nhất** trên ngữ cảnh tài liệu được cung cấp (`Rely only on clear facts directly mentioned in the context. Do NOT assume, extrapolate...`).
  2. Nếu không tìm thấy thông tin phù hợp, mô hình bắt buộc phải từ chối lịch sự bằng câu định sẵn: *"I cannot find the answer to this question in the uploaded documents."* thay vì tự bịa ra thông tin.

### ❓ Câu 4: Hãy giải thích thiết kế Single-Table trong DynamoDB của dự án này?
* **Trả lời:** DynamoDB là cơ sở dữ liệu NoSQL. Việc thiết kế Single-Table giúp ta gộp tất cả các loại thực thể dữ liệu học tập vào một bảng duy nhất nhằm tiết kiệm chi phí và tăng tốc độ đọc. Khóa chính phân vùng (Partition Key - PK) là `user_id`, còn Khóa sắp xếp (Sort Key - SK) đóng vai trò phân loại:
  * `DOC#<doc_id>`: Chứa metadata tài liệu.
  * `QUERY#<timestamp>`: Nhật ký câu hỏi.
  * `SESSION#<session_id>`: Metadata của phiên trò chuyện.
  * `CHAT#<session_id>#<timestamp>`: Lịch sử tin nhắn.
  * `QUIZ#<quiz_id>` và `FLASH#<cards_id>`: Chứa dữ liệu Quiz và Flashcards.
  Để lấy lịch sử chat của một session cụ thể, em chỉ cần thực hiện truy vấn với điều kiện `Key("user_id").eq(user_id) & Key("sk").begins_with("CHAT#<session_id>#")`.

---
*Chúc bạn có một buổi báo cáo đồ án thành công rực rỡ! Hãy tự tin giải thích mã nguồn dựa trên các luồng nghiệp vụ trên.*
