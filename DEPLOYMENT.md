# StudyBot — AWS Deployment Guide (Terraform, No VPC)

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│   Frontend   │────▶│  API Gateway     │────▶│  AWS Lambda         │
│   (Browser)  │     │  (HTTP API)      │     │  Python 3.11        │
│              │     │  CORS enabled    │     │  FastAPI + Mangum   │
└──────────────┘     └──────────────────┘     └──────┬──────────────┘
                                                     │
                          ┌──────────────────────────┼──────────────────┐
                          │                          │                  │
                          ▼                          ▼                  ▼
                   ┌─────────────┐          ┌──────────────┐   ┌──────────────┐
                   │  S3 Bucket  │          │  DynamoDB    │   │  Bedrock     │
                   │  (uploads)  │          │  (userstore) │   │  Claude 3.5  │
                   └─────────────┘          └──────────────┘   │  Haiku       │
                                                               └──────────────┘
```

**No VPC** — Lambda runs in AWS-managed networking. Direct access to S3,
DynamoDB, and Bedrock via AWS SDK (boto3). No NAT Gateway or VPC
Endpoints needed. Simpler, cheaper, faster cold starts.

---

## Prerequisites

### 1. AWS CLI configured
```bash
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: ap-southeast-1
# Default output format: json
```

### 2. Terraform installed
```bash
# Windows (winget)
winget install HashiCorp.Terraform

# macOS
brew install terraform

# Linux
sudo apt-get install terraform
# or download from https://developer.hashicorp.com/terraform/downloads

# Verify
terraform --version
```

### 3. Enable Bedrock Model Access
**This must be done BEFORE deploying.** Go to AWS Console:

1. Navigate to **Amazon Bedrock** → **Model access** (left sidebar)
2. Click **Manage model access**
3. Enable these models:
   - ✅ **Anthropic Claude 3.5 Haiku** (`anthropic.claude-3-5-haiku-20241022-v1:0`)
   - ✅ **Amazon Titan Text Embeddings V2** (optional, for future vector search)
4. Click **Save changes** and wait for "Access granted"

### 4. Python 3.11+ installed
```bash
python --version  # Should be 3.11+
pip --version
```

---

## Deployment Steps

### Step 1: Package Lambda

From the `studybot/` root directory:

```bash
python package_lambda.py
```

This creates `lambda_package.zip` (~3.5 MB) containing:
- FastAPI application (`src/`)
- Mangum Lambda adapter
- All Python dependencies (minus boto3, which Lambda provides)

### Step 2: Initialize Terraform

```bash
cd terraform
terraform init
```

Expected output:
```
Terraform has been successfully initialized!
```

### Step 3: Review the Plan

```bash
terraform plan
```

This shows what will be created:
- 1 S3 bucket (`studybot-competition-uploads`)
- 1 DynamoDB table (`studybot-competition-userstore`)
- 1 Lambda function (`studybot-competition-backend`)
- 1 API Gateway HTTP API (`studybot-competition-api`)
- IAM roles and policies
- CloudWatch log group

### Step 4: Deploy

```bash
terraform apply
```

Type `yes` when prompted. Takes ~60 seconds.

Output:
```
api_endpoint = "https://xxxxxxxxxx.execute-api.ap-southeast-1.amazonaws.com"
s3_bucket_name = "studybot-competition-uploads"
```

**Save the `api_endpoint` URL** — this is your backend.

### Step 5: Test the API

```bash
# Health check
curl https://YOUR_API_ENDPOINT/health

# Upload a document
curl -X POST https://YOUR_API_ENDPOINT/upload \
  -H "X-User-Id: test-user-001" \
  -F "file=@sample_lecture.txt"

# Ask a question
curl -X POST https://YOUR_API_ENDPOINT/query \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test-user-001" \
  -d '{"question": "What is photosynthesis?"}'

# Generate a quiz
curl -X POST https://YOUR_API_ENDPOINT/quiz \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test-user-001" \
  -d '{"num_questions": 5}'
```

### Step 6: Connect Frontend

Open `frontend/index.html` in your browser with the API URL:

```
frontend/index.html?api=https://YOUR_API_ENDPOINT
```

Or set `window.API_BASE` in the HTML file directly.

---

## Customizing the Deployment

### Change AWS Region
```bash
terraform apply -var="aws_region=us-east-1"
```

### Change Project Name (affects all resource names)
```bash
terraform apply -var="project_name=my-studybot"
```

### Update Lambda Code
```bash
# Re-package
python package_lambda.py

# Re-deploy (only Lambda function updates)
terraform apply
```

---

## Cost Estimate (48h hackathon)

| Service | Usage | Cost |
|---------|-------|------|
| Lambda | 500 invocations × 256MB × 5s | ~$0.01 |
| API Gateway HTTP | 1000 requests | ~$0.001 |
| Bedrock Haiku | 500K input + 100K output tokens | ~$1.30 |
| DynamoDB (on-demand) | 1000R + 500W | ~$0.002 |
| S3 | 100MB stored + 500 ops | ~$0.01 |
| CloudWatch Logs | 100MB | ~$0.05 |
| **Total** | | **~$1.40** |

Well under the $100 hard cap.

---

## Tear Down

```bash
cd terraform
terraform destroy
```

Type `yes`. All resources deleted. No lingering costs.

---

## Troubleshooting

### "AccessDeniedException" on Bedrock calls
→ You haven't enabled model access. Go to Bedrock Console → Model access → Enable Claude 3.5 Haiku.

### Lambda timeout (30s)
→ Quiz/Summary generation with large documents may take 10-20s. If hitting 30s limit:
```bash
# In main.tf, increase timeout:
timeout = 60
```

### "Task timed out" on first invocation
→ Cold start. Lambda needs to load Python dependencies. Second invocation will be fast.

### S3 bucket name already taken
→ S3 bucket names are globally unique. Change `project_name`:
```bash
terraform apply -var="project_name=studybot-YOUR-NAME"
```
