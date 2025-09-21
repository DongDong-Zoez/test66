#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 讀取 .env
if [[ -f .env ]]; then export $(grep -v '^#' .env | xargs); fi

echo "🧰 starting Postgres/Redis/MinIO via docker compose..."
docker compose up -d

# 等待 MinIO 起來
echo "⏳ waiting MinIO to be ready..."
until curl -sSf "${S3_ENDPOINT_URL:-http://localhost:9000}/minio/health/ready" >/dev/null; do
  sleep 1
done
echo "✅ MinIO ready"

# 用臨時 python 建立 bucket
python3 - <<'PY'
import os, boto3, botocore
endpoint=os.getenv("S3_ENDPOINT_URL","http://localhost:9000")
region=os.getenv("S3_REGION","us-east-1")
ak=os.getenv("S3_ACCESS_KEY","minioadmin")
sk=os.getenv("S3_SECRET_KEY","minioadmin")
bucket=os.getenv("S3_BUCKET","llmops-bucket")
s3=boto3.client("s3",endpoint_url=endpoint,aws_access_key_id=ak,aws_secret_access_key=sk,region_name=region)
try:
    s3.create_bucket(Bucket=bucket)
    print(f"✅ created bucket: {bucket}")
except botocore.exceptions.ClientError as e:
    if e.response["Error"]["Code"] in ("BucketAlreadyOwnedByYou","BucketAlreadyExists"):
        print(f"ℹ️  bucket exists: {bucket}")
    else:
        raise
PY

echo "🎉 infra is up. Open MinIO console at http://localhost:9001 (minioadmin/minioadmin)"
