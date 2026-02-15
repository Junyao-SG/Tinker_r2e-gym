#!/usr/bin/env bash
set -euo pipefail

# Build and push Docker images to ECR
# Usage: ./scripts/build-and-push.sh

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
ECR_REPO="${ECR_REPO:-tinker-r2egym}"
TAG="${TAG:-latest}"
R2EGYM_REF="${R2EGYM_REF:-main}"

echo "=== Logging in to ECR ==="
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

echo "=== Building orchestrator image ==="
docker build \
  -f docker/Dockerfile.orchestrator \
  --build-arg R2EGYM_REF="${R2EGYM_REF}" \
  -t "${ECR_REGISTRY}/${ECR_REPO}:${TAG}" \
  .

echo "=== Pushing orchestrator image ==="
docker push "${ECR_REGISTRY}/${ECR_REPO}:${TAG}"

echo "=== Building proxy image ==="
docker build \
  -f docker/Dockerfile.proxy \
  -t "${ECR_REGISTRY}/${ECR_REPO}-proxy:${TAG}" \
  .

echo "=== Pushing proxy image ==="
docker push "${ECR_REGISTRY}/${ECR_REPO}-proxy:${TAG}"

echo "=== Done ==="
echo "Orchestrator: ${ECR_REGISTRY}/${ECR_REPO}:${TAG}"
echo "Proxy:        ${ECR_REGISTRY}/${ECR_REPO}-proxy:${TAG}"
