"""
S3 upload utility for persisting training/eval results.

Reads S3_BUCKET, S3_PREFIX, and AWS_REGION from environment variables
(injected by the Helm configmap). Uses boto3 with IRSA credentials
(no explicit keys needed when running on EKS with the r2egym-sa service account).

Usage:
    from tinker_r2egym.s3_sync import S3Sync

    s3 = S3Sync()  # reads config from env vars
    s3.upload_file("/data/training/metrics.jsonl")
    s3.sync_dir("/data/training/")
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Sync:
    def __init__(
        self,
        bucket: str | None = None,
        prefix: str | None = None,
        region: str | None = None,
    ):
        self.bucket = bucket or os.environ.get("S3_BUCKET", "")
        self.prefix = prefix or os.environ.get("S3_PREFIX", "r2egym-trajectories")
        region = region or os.environ.get("AWS_REGION", "us-east-1")

        if not self.bucket:
            logger.warning("S3_BUCKET not set — S3 uploads will be skipped")
            self._client = None
            return

        self._client = boto3.client("s3", region_name=region)
        logger.info(f"S3Sync ready: s3://{self.bucket}/{self.prefix}/")

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self.bucket)

    def _s3_key(self, local_path: Path, base_dir: Path) -> str:
        rel = local_path.relative_to(base_dir)
        return f"{self.prefix}/{rel}"

    def upload_file(self, local_path: str | Path, base_dir: str | Path | None = None) -> bool:
        """Upload a single file to S3. Returns True on success."""
        if not self.enabled:
            return False

        local_path = Path(local_path)
        if not local_path.is_file():
            logger.warning(f"File not found, skipping upload: {local_path}")
            return False

        if base_dir is None:
            base_dir = local_path.parent
        key = self._s3_key(local_path, Path(base_dir))

        try:
            self._client.upload_file(str(local_path), self.bucket, key)
            logger.info(f"Uploaded {local_path} -> s3://{self.bucket}/{key}")
            return True
        except ClientError as e:
            logger.error(f"S3 upload failed for {local_path}: {e}")
            return False

    def sync_dir(self, local_dir: str | Path) -> int:
        """Upload all files in a directory to S3. Returns count of files uploaded."""
        if not self.enabled:
            return 0

        local_dir = Path(local_dir)
        if not local_dir.is_dir():
            logger.warning(f"Directory not found, skipping sync: {local_dir}")
            return 0

        count = 0
        for path in sorted(local_dir.rglob("*")):
            if path.is_file():
                if self.upload_file(path, base_dir=local_dir):
                    count += 1
        logger.info(f"Synced {count} files from {local_dir} to s3://{self.bucket}/{self.prefix}/")
        return count
