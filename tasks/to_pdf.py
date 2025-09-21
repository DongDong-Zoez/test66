from __future__ import annotations
import os
from sqlalchemy.orm import sessionmaker
from models import TaskRun, File as FileRow, Artifact
from s3util import load_s3_config, put_bytes
from loader import DocumentToImagesLoader, LoadOptions
from .base import BaseHandler

_loader = DocumentToImagesLoader()
_s3cfg = load_s3_config()

def _stem(filename: str) -> str:
    return os.path.splitext(filename)[0]

def _artifact_key(user_id: str, file_id: str, task_run_id: str, subpath: str) -> str:
    return f"{user_id}/artifacts/{file_id}/{task_run_id}/{subpath}"

class ToPdfHandler(BaseHandler):
    name = "to_pdf"

    def __init__(self, SessionLocal: sessionmaker):
        super().__init__()
        self.SessionLocal = SessionLocal

    def run(self, tr: TaskRun, f: FileRow, data: bytes) -> None:
        pdf_bytes = _loader.load(data, LoadOptions(return_mode="PDF_BYTES"))
        stem = _stem(f.user_filename)
        pdf_key = _artifact_key(f.owner_id, f.id, tr.id, f"to-pdf/{stem}.pdf")
        pdf_uri = put_bytes(_s3cfg, pdf_key, pdf_bytes, "application/pdf")

        with self.SessionLocal() as db:
            db.add(Artifact(
                file_id=f.id, task_run_id=tr.id, kind="pdf",
                storage_uri=pdf_uri, meta={"source": "to_pdf"}
            ))
            db.commit()
