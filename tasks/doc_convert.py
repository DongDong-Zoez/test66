from __future__ import annotations
import io, os, zipfile
from sqlalchemy.orm import sessionmaker
from models import TaskRun, File as FileRow, Artifact, Base
from s3util import load_s3_config, put_bytes
from loader import DocumentToImagesLoader, LoadOptions
from .base import BaseHandler

# 共享或各自 new 一個皆可
_loader = DocumentToImagesLoader()
_s3cfg = load_s3_config()

def _stem(filename: str) -> str:
    return os.path.splitext(filename)[0]

def _artifact_key(user_id: str, file_id: str, task_run_id: str, subpath: str) -> str:
    return f"{user_id}/artifacts/{file_id}/{task_run_id}/{subpath}"

class DocConvertHandler(BaseHandler):
    name = "doc_convert"

    def __init__(self, SessionLocal: sessionmaker):
        super().__init__()
        self.SessionLocal = SessionLocal

    def run(self, tr: TaskRun, f: FileRow, data: bytes) -> None:
        params = tr.params or {}
        dpi = int(params.get("dpi", 220))
        image_format = str(params.get("image_format", "PNG")).upper()
        max_side = params.get("max_side")

        images_bytes = _loader.load(
            data,
            LoadOptions(dpi=dpi, image_format=image_format, return_mode="BYTES", max_side=max_side)
        )
        if not images_bytes:
            raise RuntimeError("no images produced")

        ext = "jpg" if image_format == "JPEG" else image_format.lower()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, b in enumerate(images_bytes, 1):
                zf.writestr(f"page_{i:04d}.{ext}", b)
        buf.seek(0)

        stem = _stem(f.user_filename)
        zip_key = _artifact_key(f.owner_id, f.id, tr.id, f"zip/{stem}.images.zip")
        zip_uri = put_bytes(_s3cfg, zip_key, buf.getvalue(), "application/zip")

        with self.SessionLocal() as db:
            db.add(Artifact(
                file_id=f.id, task_run_id=tr.id, kind="images_zip",
                storage_uri=zip_uri, meta={"pages": len(images_bytes), "format": image_format}
            ))
            db.commit()
