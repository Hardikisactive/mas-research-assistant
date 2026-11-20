#!/usr/bin/env bash
# =============================================================================
# Google Cloud Run Deployment Script
# Multi-Agent Research Assistant
# =============================================================================
# Usage:
#   export GCP_PROJECT_ID=your-project-id
#   export GCP_REGION=us-central1          # optional, defaults to us-central1
#   export GOOGLE_API_KEY=your-api-key
#   chmod +x deployment/cloud_run_deploy.sh
#   ./deployment/cloud_run_deploy.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="mas-research-assistant"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
SECRET_NAME="google-api-key"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT_ID environment variable is required."
  echo "  export GCP_PROJECT_ID=your-gcp-project-id"
  exit 1
fi

if [[ -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "ERROR: GOOGLE_API_KEY environment variable is required to store in Secret Manager."
  exit 1
fi

echo "===> Project: ${PROJECT_ID}"
echo "===> Region:  ${REGION}"
echo "===> Image:   ${IMAGE_NAME}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Authenticate and set project
# ---------------------------------------------------------------------------
echo "===> [1/6] Setting gcloud project..."
gcloud config set project "${PROJECT_ID}"

# ---------------------------------------------------------------------------
# Step 2: Enable required APIs
# ---------------------------------------------------------------------------
echo "===> [2/6] Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  containerregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  --quiet

# ---------------------------------------------------------------------------
# Step 3: Store API key in Secret Manager
# ---------------------------------------------------------------------------
echo "===> [3/6] Storing GOOGLE_API_KEY in Secret Manager..."
if gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "     Secret '${SECRET_NAME}' already exists. Adding new version..."
  echo -n "${GOOGLE_API_KEY}" | gcloud secrets versions add "${SECRET_NAME}" --data-file=-
else
  echo "     Creating new secret '${SECRET_NAME}'..."
  echo -n "${GOOGLE_API_KEY}" | gcloud secrets create "${SECRET_NAME}" \
    --data-file=- \
    --replication-policy=automatic \
    --project="${PROJECT_ID}"
fi

# ---------------------------------------------------------------------------
# Step 4: Build Docker image
# ---------------------------------------------------------------------------
echo "===> [4/6] Building Docker image..."
docker build \
  --tag "${IMAGE_NAME}:latest" \
  --tag "${IMAGE_NAME}:$(git rev-parse --short HEAD 2>/dev/null || echo 'manual')" \
  .

# ---------------------------------------------------------------------------
# Step 5: Push image to Container Registry
# ---------------------------------------------------------------------------
echo "===> [5/6] Pushing image to GCR..."
# Configure docker auth for gcr.io
gcloud auth configure-docker gcr.io --quiet
docker push "${IMAGE_NAME}:latest"

# ---------------------------------------------------------------------------
# Step 6: Deploy to Cloud Run
# ---------------------------------------------------------------------------
echo "===> [6/6] Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_NAME}:latest" \
  --platform managed \
  --region "${REGION}" \
  --set-secrets="GOOGLE_API_KEY=${SECRET_NAME}:latest" \
  --set-env-vars="APP_ENV=production,LOG_LEVEL=INFO,CREWAI_LLM_MODEL=gemini/gemini-1.5-flash,ADK_MODEL=gemini-1.5-flash" \
  --memory=2Gi \
  --cpu=2 \
  --concurrency=4 \
  --min-instances=0 \
  --max-instances=3 \
  --port=8501 \
  --timeout=300 \
  --allow-unauthenticated \
  --quiet

# ---------------------------------------------------------------------------
# Output service URL
# ---------------------------------------------------------------------------
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format='value(status.url)')

echo ""
echo "============================================================"
echo "  Deployment Complete!"
echo "  Service URL: ${SERVICE_URL}"
echo "============================================================"
echo ""
echo "To view logs:"
echo "  gcloud run services logs read ${SERVICE_NAME} --region ${REGION} --limit 50"
echo ""
echo "To update (re-deploy after code changes):"
echo "  docker build -t ${IMAGE_NAME}:latest . && docker push ${IMAGE_NAME}:latest"
echo "  gcloud run deploy ${SERVICE_NAME} --image ${IMAGE_NAME}:latest --region ${REGION}"

