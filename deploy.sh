#!/usr/bin/env bash
# ============================================================================
# StudyBot — One-click AWS Deployment Script
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh              # Build, deploy infra, upload frontend
#   ./deploy.sh destroy      # Tear down all AWS resources
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Destroy mode ──
if [[ "${1:-}" == "destroy" ]]; then
    info "Destroying all AWS resources..."
    cd terraform
    terraform destroy -auto-approve
    info "All resources destroyed."
    exit 0
fi

# ── Pre-flight checks ──
info "Pre-flight checks..."
command -v python >/dev/null 2>&1 || error "python not found"
command -v terraform >/dev/null 2>&1 || error "terraform not found"
command -v aws >/dev/null 2>&1 || error "AWS CLI not found"

# Check AWS credentials
aws sts get-caller-identity > /dev/null 2>&1 || error "AWS credentials not configured. Run 'aws configure' first."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
info "AWS Account: $ACCOUNT_ID"

# ── Step 2: Build Lambda package ──
info "Step 2: Building Lambda package..."
python package_lambda.py || error "Lambda build failed!"

# ── Step 3: Terraform init & apply ──
info "Step 3: Deploying infrastructure with Terraform..."
cd terraform
terraform init -upgrade
terraform apply -auto-approve

# ── Step 4: Capture outputs ──
API_URL=$(terraform output -raw api_gateway_url)
CF_DOMAIN=$(terraform output -raw cloudfront_domain)
FRONTEND_BUCKET=$(terraform output -raw s3_frontend_bucket)

info "API Gateway URL:    $API_URL"
info "CloudFront Domain:  $CF_DOMAIN"
info "Frontend Bucket:    $FRONTEND_BUCKET"

cd "$SCRIPT_DIR"

# ── Step 5: Inject API URL into frontend and upload ──
info "Step 5: Uploading frontend to S3..."

# Create temp version of index.html with correct API URL
mkdir -p build/frontend
sed "s|http://localhost:8000|${API_URL}|g" frontend/index.html > build/frontend/index.html

aws s3 sync build/frontend/ "s3://${FRONTEND_BUCKET}/" --delete

# ── Step 6: Invalidate CloudFront cache ──
CF_DIST_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='StudyBot Frontend'].Id" \
    --output text)

if [[ -n "$CF_DIST_ID" ]]; then
    info "Invalidating CloudFront cache ($CF_DIST_ID)..."
    aws cloudfront create-invalidation \
        --distribution-id "$CF_DIST_ID" \
        --paths "/*" > /dev/null
fi

# ── Step 7: Health check ──
info "Step 7: Health check..."
sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/health")
if [[ "$HTTP_CODE" == "200" ]]; then
    info "✅ API is live and healthy!"
else
    warn "API returned HTTP $HTTP_CODE — may need a few more seconds to warm up."
fi

# ── Done ──
echo ""
echo "============================================"
echo " 🎓 StudyBot deployed successfully!"
echo "============================================"
echo ""
echo " Frontend:  https://${CF_DOMAIN}"
echo " API:       ${API_URL}"
echo " Health:    ${API_URL}/health"
echo ""
echo " To tear down:  ./deploy.sh destroy"
echo "============================================"
