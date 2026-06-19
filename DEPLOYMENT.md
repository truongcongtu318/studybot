# StudyBot — AWS Deployment Guide (Terraform & CI/CD Shell Script)

Tài liệu này hướng dẫn chi tiết quy trình đóng gói và triển khai ứng dụng **StudyBot** lên đám mây AWS bằng công cụ Terraform (Infrastructure as Code) kết hợp với script tự động hóa `./deploy.sh`.

---

## 🏛️ Sơ Đồ Hạ Tầng AWS Deploy (Production Architecture)

Hệ thống được cấu trúc chạy hoàn toàn serverless để tối ưu chi phí và tăng tốc hiệu năng:

```
                  ┌──────────────────────┐
                  │  Web Browser (User)  │
                  └──────────┬───────────┘
                             │ HTTPS
                             ▼
                  ┌──────────────────────┐
                  │  AWS CloudFront CDN  │ ◄─── Chứa Frontend tĩnh (S3)
                  └──────────┬───────────┘
                             │
            ┌────────────────┴────────────────┐
            │ /api/*                          │ / (Frontend Assets)
            ▼                                 ▼
┌──────────────────────────┐      ┌──────────────────────────┐
│ AWS API Gateway (v2 HTTP)│      │    S3 Frontend Bucket    │
└───────────┬──────────────┘      └──────────────────────────┘
            │ proxy integration
            ▼
┌──────────────────────────┐
│ AWS Lambda (Python 3.12) │ ◄─── Runtime API (FastAPI + Mangum)
└─────┬─────┬───────────┬──┘
      │     │           │
      │     │           └───────► Amazon Bedrock (Claude 3.5 Haiku & Titan Embedding V2)
      │     ▼
      │   ┌──────────────────────────┐
      ├──►│   S3 Documents Bucket    │ ◄─── Lưu file tài liệu học tập (*.pdf) và vector (*.json)
      │   └──────────────────────────┘
      ▼
┌──────────────────────────┐
│  AWS DynamoDB Database   │ ◄─── Lưu trữ Single-Table (Phiên chat, Quiz, Flashcards, Logs)
└──────────────────────────┘
```

* **Serverless Network**: Lambda function chạy trong mạng quản trị mặc định của AWS (No VPC) giúp truy cập tốc độ cao trực tiếp sang S3, Bedrock, và DynamoDB thông qua bộ SDK của AWS (`boto3`) mà không cần NAT Gateway hay VPC Endpoint đắt đỏ.

---

## 📋 Điều Kiện Cần (Prerequisites)

### 1. Cấu hình thông tin tài khoản AWS CLI
Đảm bảo máy tính đã cài đặt AWS CLI và cấu hình tài khoản IAM có đủ quyền Admin/PowerUser:
```bash
aws configure
# AWS Access Key ID: [Nhập Access Key ID của bạn]
# AWS Secret Access Key: [Nhập Secret Key của bạn]
# Default region name: us-east-1 (Bedrock Titan Embedding & Claude Haiku khả dụng nhất tại đây)
# Default output format: json
```

### 2. Kích hoạt quyền truy cập Model trên Amazon Bedrock
**Bước này cực kỳ quan trọng và phải thực hiện trước khi deploy**:
1. Đăng nhập vào AWS Management Console.
2. Tìm kiếm dịch vụ **Amazon Bedrock**.
3. Tại menu bên trái, cuộn xuống chọn **Model access**.
4. Chọn **Manage model access** bên góc phải.
5. Tích chọn kích hoạt truy cập cho các mô hình sau:
   * ✅ **Anthropic / Claude 3.5 Haiku**
   * ✅ **Amazon / Titan Text Embeddings V2**
6. Nhấp **Save changes** và đợi vài phút để AWS chuyển trạng thái sang **Access granted**.

### 3. Cài đặt Terraform & Python
* **Python**: Yêu cầu phiên bản **Python 3.12+** cùng trình quản lý gói `pip`.
* **Terraform**: Đảm bảo lệnh `terraform` có sẵn trong PATH:
  ```bash
  terraform --version  # Kiểm tra tính sẵn sàng
  ```

---

## 🚀 Quy Trình Deploy Tự Động (Một Click)

Tất cả các khâu phức tạp từ đóng gói Lambda, khởi tạo hạ tầng AWS, cập nhật API endpoint, đồng bộ frontend lên S3 cho đến xóa cache CloudFront đều được thực hiện tự động bằng script **`deploy.sh`**.

Từ thư mục gốc của project, bạn chỉ cần chạy:

### Triển khai hệ thống:
```bash
chmod +x deploy.sh
./deploy.sh
```

### Script `deploy.sh` sẽ thực hiện tuần tự:
1. **Pre-flight checks**: Xác minh các công cụ (Python, Terraform, AWS CLI, credential hoạt động).
2. **Lambda Build (`package_lambda.py`)**: Tự động tải xuống các thư viện wheel Linux tương thích, đóng gói mã nguồn `src/` và các dependency thành tệp tin lưu tại `build/lambda.zip`.
3. **Terraform Apply**: Khởi tạo, so sánh trạng thái và tự động cập nhật hạ tầng AWS theo mô tả IaC trong thư mục `terraform/`.
4. **API Endpoint Injection**: Trích xuất URL API từ Terraform outputs, tự động thay thế `http://localhost:8000` thành API Gateway Gateway URL thực tế trên AWS rồi ghi đè vào tệp build frontend.
5. **Sync Frontend**: Đồng bộ tệp giao diện lên S3 Bucket tĩnh.
6. **CloudFront Invalidation**: Tạo lệnh xóa cache trên CDN CloudFront để cập nhật giao diện ngay lập tức cho khách hàng.
7. **Health Check**: Tự động test endpoint `/health` xem API Lambda đã live ổn định chưa.

---

## 🛠️ Quy Trình Deploy Thủ Công (Từng bước)

Nếu bạn không muốn sử dụng script tự động hoặc đang sửa đổi chi tiết hạ tầng:

### Bước 1: Đóng gói Lambda
```bash
python package_lambda.py
```
*Tệp tin zip đầu ra sẽ được lưu tại `build/lambda.zip`.*

### Bước 2: Khởi tạo & Triển khai hạ tầng Terraform
```bash
cd terraform
terraform init
terraform apply -auto-approve
```
*Đợi khoảng 60s để Terraform tạo xong: S3, DynamoDB, Lambda, API Gateway và CloudFront CDN.*

### Bước 3: Đẩy giao diện tĩnh lên S3 Frontend Bucket
1. Copy tệp `frontend/index.html` sang thư mục build.
2. Mở file `index.html` vừa copy và tìm biến `API_BASE`, thay thế giá trị Localhost bằng **`api_gateway_url`** (được hiển thị ở đầu ra output của Terraform).
3. Đẩy file lên S3 bằng lệnh:
   ```bash
   aws s3 sync build/frontend/ "s3://[TÊN_FRONTEND_BUCKET_TRONG_TERRAFORM_OUTPUT]/" --delete
   ```
4. Xóa cache CDN của CloudFront:
   ```bash
   aws cloudfront create-invalidation --distribution-id [DISTRIBUTION_ID_CỦA_BẠN] --paths "/*"
   ```

---

## 📋 Kiểm Tra & Giám Sát Sau Khi Deploy

### 1. Kiểm tra API Health
Truy cập URL API từ Terraform output:
```bash
curl https://[API_GATEWAY_URL]/health
```
*Kết quả trả về phải dạng JSON có trạng thái `"status": "ok"`.*

### 2. Xem Logs thời gian thực (Real-time CloudWatch Logs)
Khi gặp lỗi (Ví dụ: HTTP 503, Bedrock bị nghẽn mạng), bạn có thể kiểm tra logs của Lambda bằng lệnh CLI hoặc truy cập trực tiếp bảng điều khiển AWS CloudWatch:
```bash
# Lọc logs lỗi Lambda trong 10 phút gần đây nhất
aws logs filter-log-events --log-group-name "/aws/lambda/studybot-app-prod-api-ba72738d" --region us-east-1 --start-time $(( (Get-Date).AddMinutes(-10).Ticks )) --query "events[*].message" --output text
```

---

## 🗑️ Hủy Bỏ Toàn Bộ Tài Nguyên (Tear Down)

Để tránh phát sinh chi phí AWS ngoài ý muốn sau khi hoàn thành buổi báo cáo môn học, hãy xóa sạch mọi tài nguyên trên Cloud:

```bash
# Cách 1: Sử dụng script deploy
./deploy.sh destroy

# Cách 2: Chạy trực tiếp qua Terraform
cd terraform
terraform destroy -auto-approve
```
*Toàn bộ cơ sở hạ tầng đã tạo sẽ được gỡ bỏ sạch sẽ khỏi tài khoản AWS của bạn.*
