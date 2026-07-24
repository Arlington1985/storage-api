#!/bin/bash
# Script to deploy the Photo Storage API to the DEVELOPMENT Cloud Run environment
# Using Google Secret Manager for secrets and a DEDICATED Service Account

set -e

echo "--- Deploying Photo Storage API to DEVELOPMENT Environment ---"

# --- Configuration ---
ENV_FILE=".env" # Contains ONLY NON-SECRETS for development
PROJECT_ID="wolt-456507"
REGION="europe-west4"
REPOSITORY="wolt-bolt-integrations"
IMAGE_NAME="storage-api"
SERVICE_NAME="storage-api-dev" # DEVELOPMENT service name
SERVICE_ACCOUNT_EMAIL="storage-api-dev-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# --- Load NON-SECRET Development Environment Variables ---
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: Environment file '$ENV_FILE' not found!"
    exit 1
fi
echo "Loading NON-SECRET environment variables from $ENV_FILE..."
while IFS='=' read -r k v; do
  [[ "$k" =~ ^\s*# ]] && continue
  [[ -z "$k" ]] && continue
  v_cleaned=$(echo "$v" | sed -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//')
  export "$k=$v_cleaned"
done < <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$')

if [ -z "$R2_ENDPOINT_URL" ] || [ -z "$R2_BUCKET" ]; then
    echo "ERROR: Failed to load essential non-secret variables from $ENV_FILE."
    exit 1
fi

# --- Define Image Tag ---
GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)
IMAGE_TAG_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}"
IMAGE_TAG="${IMAGE_TAG_BASE}:dev-${GIT_HASH}"
echo "Using Image Tag: ${IMAGE_TAG}"

# --- Build & Push Docker Image ---
echo "Building Docker image for linux/amd64..."
docker buildx build --platform linux/amd64 -t ${IMAGE_TAG} --load .
echo "Pushing Docker image to Artifact Registry..."
docker push ${IMAGE_TAG}
echo "Docker image pushed successfully."

# --- Deploy to Cloud Run (Development Service) ---
echo "Deploying to Cloud Run service: ${SERVICE_NAME} using SA: ${SERVICE_ACCOUNT_EMAIL}"

NON_SECRET_ENV_VARS="APP_ENV=${APP_ENV:-development}"
NON_SECRET_ENV_VARS+=",R2_ENDPOINT_URL=${R2_ENDPOINT_URL}"
NON_SECRET_ENV_VARS+=",R2_BUCKET=${R2_BUCKET}"
NON_SECRET_ENV_VARS+=",R2_PUBLIC_BASE_URL=${R2_PUBLIC_BASE_URL}"

SECRET_VARS="INTERNAL_API_KEY=storage-internal-api-key-dev:latest"
SECRET_VARS+=",R2_ACCESS_KEY_ID=r2-access-key-id-dev:latest"
SECRET_VARS+=",R2_SECRET_ACCESS_KEY=r2-secret-access-key-dev:latest"

gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_TAG}" \
    --region="${REGION}" \
    --platform=managed \
    --allow-unauthenticated \
    --port=8080 \
    --service-account="${SERVICE_ACCOUNT_EMAIL}" \
    --set-env-vars="${NON_SECRET_ENV_VARS}" \
    --set-secrets="${SECRET_VARS}" \
    --project="${PROJECT_ID}"

echo "Cloud Run service deployed."
echo "--- DEVELOPMENT Deployment Script Finished ---"
