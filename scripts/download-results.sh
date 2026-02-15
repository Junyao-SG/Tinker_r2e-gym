#!/usr/bin/env bash
set -euo pipefail

# Download results from S3
# Usage: ./scripts/download-results.sh [local-dir]

S3_BUCKET="${S3_BUCKET:?Set S3_BUCKET env var}"
S3_PREFIX="${S3_PREFIX:-r2egym-trajectories}"
LOCAL_DIR="${1:-./results}"

echo "=== Downloading results ==="
echo "From: s3://${S3_BUCKET}/${S3_PREFIX}/"
echo "To:   ${LOCAL_DIR}/"

mkdir -p "${LOCAL_DIR}"
aws s3 sync "s3://${S3_BUCKET}/${S3_PREFIX}/" "${LOCAL_DIR}/"

echo "=== Done ==="
echo "Results saved to ${LOCAL_DIR}/"
