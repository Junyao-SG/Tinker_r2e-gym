#!/usr/bin/env bash
set -euo pipefail

# One-time cluster setup: EKS cluster, OIDC, ECR, secrets
# Usage: ./scripts/setup-cluster.sh

CLUSTER_NAME="${CLUSTER_NAME:-tinker-r2egym}"
REGION="${AWS_REGION:-us-east-1}"
ECR_REPO="${ECR_REPO:-tinker-r2egym}"

echo "=== Creating EKS cluster ==="
eksctl create cluster -f cluster/cluster.yaml

echo "=== Creating ECR repositories ==="
aws ecr create-repository --repository-name "${ECR_REPO}" --region "${REGION}" 2>/dev/null || echo "ECR repo already exists"
aws ecr create-repository --repository-name "${ECR_REPO}-proxy" --region "${REGION}" 2>/dev/null || echo "ECR proxy repo already exists"

echo "=== Creating secrets ==="
echo "Create the tinker-credentials secret manually:"
echo ""
echo "  kubectl create secret generic tinker-credentials \\"
echo "    --from-literal=TINKER_API_KEY=<your-key> \\"
echo "    --from-literal=WANDB_API_KEY=<your-key> \\"
echo "    --from-literal=HF_TOKEN=<your-token>"
echo ""
echo "Or from .env file:"
echo "  kubectl create secret generic tinker-credentials --from-env-file=.env"

echo ""
echo "=== Cluster ready ==="
echo "Next steps:"
echo "  1. Create secrets (see above)"
echo "  2. make build push"
echo "  3. make deploy"
