from __future__ import annotations
import os
from datetime import datetime
from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, File as FileRow, TaskRun
from s3util import load_s3_config, s3_client, split_s3_uri
from tasks.manager import manager
from tasks import register_all  # 讓所有 handler 註冊進 manager

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
cel = Celery("worker", broker=BROKER_URL, backend=RESULT_BACKEND)
cel.conf.task_routes = {"worker.*": {"queue": "default"}}

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://llmops:llmops@localhost:5432/llmops")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base.metadata.create_all(engine)

# 註冊所有 handler（把 SessionLocal 注入）
register_all(SessionLocal)

s3cfg = load_s3_config()

def _mark(db, tr: TaskRun, status: str, err: str | None = None):
    tr.status = status
    now = datetime.utcnow()
    if status == "RUNNING" and not tr.started_at:
        tr.started_at = now
    if status in ("SUCCEEDED", "FAILED"):
        tr.finished_at = now
    tr.error = err
    db.add(tr); db.commit()

def _get_source_bytes(f: FileRow) -> bytes:
    bucket, key = split_s3_uri(f.storage_uri)
    obj = s3_client(s3cfg).get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()

@cel.task(name="worker.run_task", bind=True, max_retries=2)
def run_task(self, task_run_id: str):
    """
    單一 task_run 的執行入口：
      1) 讀取 TaskRun + File
      2) 標記 RUNNING
      3) 下載來源 bytes
      4) 交給 TaskManager（對應 handler）執行
      5) 更新狀態
    """
    with SessionLocal() as db:
        tr = db.get(TaskRun, task_run_id)
        if not tr:
            return
        f = db.get(FileRow, tr.file_id)
        if not f:
            _mark(db, tr, "FAILED", "file not found"); return

        _mark(db, tr, "RUNNING")
        try:
            data = _get_source_bytes(f)
            manager.run(tr, f, data)
            _mark(db, tr, "SUCCEEDED")
        except Exception as e:
            _mark(db, tr, "FAILED", str(e))
            raise
