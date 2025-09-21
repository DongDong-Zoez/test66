from __future__ import annotations
import hashlib
import os
from dataclasses import dataclass
from typing import Optional, Tuple
import boto3

@dataclass
class S3Config:
    endpoint_url: str
    region: str
    access_key: str
    secret_key: str
    bucket: str

def load_s3_config() -> S3Config:
    return S3Config(
        endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000"),
        region=os.getenv("S3_REGION", "us-east-1"),
        access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        bucket=os.getenv("S3_BUCKET", "llmops-bucket"),
    )

def s3_client(cfg: S3Config):
    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        region_name=cfg.region,
    )

def put_bytes(cfg: S3Config, key: str, data: bytes, content_type: Optional[str] = None) -> str:
    s3_client(cfg).put_object(Bucket=cfg.bucket, Key=key, Body=data, ContentType=content_type)
    return f"s3://{cfg.bucket}/{key}"

def get_bytes(cfg: S3Config, key: str) -> bytes:
    return s3_client(cfg).get_object(Bucket=cfg.bucket, Key=key)["Body"].read()

def split_s3_uri(uri: str) -> Tuple[str, str]:
    assert uri.startswith("s3://")
    _, rest = uri.split("s3://", 1)
    bucket, key = rest.split("/", 1)
    return bucket, key

def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256(); h.update(data); return h.hexdigest()
