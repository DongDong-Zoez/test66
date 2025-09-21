from __future__ import annotations
import os
from typing import List, Optional
from uuid import uuid4

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from models import Base, File as FileRow, TaskRun
from models import Artifact
from loader import DocumentToImagesLoader, LoadOptions
from s3util import load_s3_config, put_bytes, sha256_bytes, split_s3_uri, s3_client
from botocore.exceptions import ClientError

from celery import Celery

# Celery
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
cel = Celery("docsvc", broker=BROKER_URL, backend=RESULT_BACKEND)
cel.conf.task_routes = {"worker.*": {"queue": "default"}}

# DB
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://llmops:llmops@localhost:5432/llmops")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base.metadata.create_all(engine)

app = FastAPI(title="LLMOps Doc Service (no batch id)", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

loader = DocumentToImagesLoader()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

class RunReq(BaseModel):
    file_ids: List[str]
    name: str                 # 'doc_convert' ...
    params: Optional[dict] = None

def _try_get_object_bytes(bucket: str, key: str) -> bytes | None:
    try:
        return s3_client(load_s3_config()).get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "NoSuchBucket"):
            return None
        raise

def _resolve_source_bytes_or_404(f: FileRow) -> bytes:
    """
    盡力從 S3 取回原始檔 bytes：
      1) 用 DB.storage_uri
      2) 失敗 → 試新規則 {owner_id}/source_files/{file_id}/{user_filename}
      3) 再失敗 → 試舊規則 uploads/{file_id}/{user_filename}
    任何一步成功就回 bytes，全失敗就丟 404，並附上嘗試的 key 列表方便排錯
    """
    cfg = load_s3_config()
    tried = []

    # 1) DB.storage_uri
    try:
        bkt, key = split_s3_uri(f.storage_uri)
        tried.append((bkt, key, "db.storage_uri"))
        data = _try_get_object_bytes(bkt, key)
        if data is not None:
            return data
    except Exception:
        pass

    # 2) 新規則
    new_key = f"{f.owner_id}/source_files/{f.id}/{f.user_filename}"
    tried.append((cfg.bucket, new_key, "new_rule"))
    data = _try_get_object_bytes(cfg.bucket, new_key)
    if data is not None:
        return data

    # 3) 舊規則
    old_key = f"uploads/{f.id}/{f.user_filename}"
    tried.append((cfg.bucket, old_key, "old_rule"))
    data = _try_get_object_bytes(cfg.bucket, old_key)
    if data is not None:
        return data

    # 全部失敗 → 404，列出嘗試過的 bucket/key
    detail = {
        "message": "source object not found in S3",
        "tried": [{"bucket": b, "key": k, "from": tag} for (b, k, tag) in tried],
        "hint": "確認 file.storage_uri、user_id、實際 S3 目錄一致；或檢查檔名是否含特殊字元/空白",
    }
    raise HTTPException(status_code=404, detail=detail)

@app.post("/files")
async def upload_files(
    files: List[UploadFile] = File(...),
    user_id: str = Form("user-anon"),                # <── 新增，預設匿名
    db: Session = Depends(get_db)
):
    if not files: raise HTTPException(400, "No files")
    s3cfg = load_s3_config()
    out_ids: List[str] = []
    for up in files:
        data = await up.read()
        if not data: continue
        file_id = str(uuid4())
        # ① 路徑改為 {user_id}/source_files/{file_id}/{檔名}
        key = f"{user_id}/source_files/{file_id}/{up.filename}"
        uri = put_bytes(s3cfg, key, data, up.content_type or "application/octet-stream")
        row = FileRow(
            id=file_id,
            owner_id=user_id,                          # <── 寫入 DB
            user_filename=up.filename,
            mime_type=up.content_type,
            byte_size=len(data),
            sha256=sha256_bytes(data),
            storage_uri=uri,
            status="READY"
        )
        db.add(row); db.commit()
        out_ids.append(file_id)
    if not out_ids: raise HTTPException(400, "All files empty")
    return {"file_ids": out_ids}

@app.post("/files:run")
def run_files(payload: RunReq, db: Session = Depends(get_db)):
    if not payload.file_ids: raise HTTPException(400, "file_ids empty")
    runs = []
    for fid in payload.file_ids:
        row = db.get(FileRow, fid)
        if not row or row.status == "DELETED": continue
        tr = TaskRun(file_id=fid, name=payload.name, params=payload.params or {}, status="PENDING")
        db.add(tr); db.commit()
        cel.send_task("worker.run_task", kwargs={"task_run_id": tr.id})
        runs.append({"task_run_id": tr.id, "file_id": fid})
    if not runs: raise HTTPException(400, "No valid files to run")
    return {"runs": runs}

@app.get("/runs/{task_run_id}")
def run_status(task_run_id: str, db: Session = Depends(get_db)):
    tr = db.get(TaskRun, task_run_id)
    if not tr: raise HTTPException(404, "task_run not found")
    return {
        "task_run_id": tr.id,
        "file_id": tr.file_id,
        "name": tr.name,
        "status": tr.status,
        "started_at": tr.started_at.isoformat() if tr.started_at else None,
        "finished_at": tr.finished_at.isoformat() if tr.finished_at else None,
        "error": tr.error,
    }

@app.post("/files/{file_id}/to-pdf")
def file_to_pdf(file_id: str, db: Session = Depends(get_db)):
    """
    將已上傳檔案解析為 PDF（不光柵化），同步回傳 PDF bytes，
    並將 PDF 存到 S3: {owner_id}/artifacts/{file_id}/{task_run_id}/to-pdf/{stem}.pdf
    也會寫入一筆 TaskRun 與 Artifact（方便追蹤，但不需要 batch id）
    """
    f = db.get(FileRow, file_id)
    if not f or f.status == "DELETED":
        raise HTTPException(404, "file not found")

    # 下載原始 bytes
    # bucket, key = split_s3_uri(f.storage_uri)
    # data = s3_client(load_s3_config()).get_object(Bucket=bucket, Key=key)["Body"].read()
    data = _resolve_source_bytes_or_404(f)

    # 建一筆 TaskRun（同步任務）
    tr = TaskRun(file_id=f.id, name="to_pdf", params={}, status="RUNNING")
    db.add(tr); db.commit()

    try:
        pdf_bytes = loader.load(data, LoadOptions(return_mode="PDF_BYTES"))
        stem = os.path.splitext(f.user_filename)[0]
        pdf_key = f"{f.owner_id}/artifacts/{f.id}/{tr.id}/to-pdf/{stem}.pdf"
        pdf_uri = put_bytes(load_s3_config(), pdf_key, pdf_bytes, "application/pdf")

        art = Artifact(file_id=f.id, task_run_id=tr.id, kind="pdf", storage_uri=pdf_uri, meta={"source":"to_pdf"})
        db.add(art)
        tr.status = "SUCCEEDED"
        db.add(tr); db.commit()

        # 同步回傳 PDF
        headers = {"Content-Disposition": f'attachment; filename="{stem}.pdf"'}
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

    except Exception as e:
        tr.status = "FAILED"; tr.error = str(e)
        db.add(tr); db.commit()
        raise

@app.get("/")
def root(): return {"ok": True}
