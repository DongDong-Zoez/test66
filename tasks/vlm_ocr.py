# tasks/vlm_ocr.py
from __future__ import annotations
import os
import json
import mimetypes
import tempfile
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from loguru import logger

from models import TaskRun, File as FileRow, Artifact
from s3util import load_s3_config, put_bytes
from loader import DocumentToImagesLoader, LoadOptions
from .base import BaseHandler

# MinerU
from mineru.cli.common import prepare_env
from mineru.backend.vlm.vlm_analyze import doc_analyze as vlm_doc_analyze
from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make
from mineru.utils.enum_class import MakeMode
from mineru.utils.draw_bbox import draw_layout_bbox

_loader = DocumentToImagesLoader()
_s3cfg = load_s3_config()

def _stem(filename: str) -> str:
    return os.path.splitext(filename)[0]

def _artifact_prefix(user_id: str, file_id: str, task_run_id: str, subdir: str) -> str:
    # e.g. alice/artifacts/<file_id>/<task_run_id>/vlm/md
    return f"{user_id}/artifacts/{file_id}/{task_run_id}/vlm/{subdir}"

def _guess_content_type(p: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(p))
    return ctype or "application/octet-stream"

def _upload_dir_recursive(local_dir: Path, s3_prefix: str) -> list[str]:
    """
    遞迴上傳 local_dir 內所有檔案到 S3（維持相對路徑），回傳相對路徑清單。
    S3 key = f"{s3_prefix}/{relative_path}"
    """
    uploaded: list[str] = []
    for p in local_dir.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(local_dir)).replace("\\", "/")
            key = f"{s3_prefix}/{rel}"
            put_bytes(_s3cfg, key, p.read_bytes(), _guess_content_type(p))
            uploaded.append(rel)
    return uploaded

class VlmOcrHandler(BaseHandler):
    name = "vlm_ocr"
    # 模型路徑，可用環境變數覆蓋
    model_path = os.getenv("MINERU_MODEL_PATH", "/home/dongdong/MinerU2.5-2509-1.2B")

    def __init__(self, SessionLocal: sessionmaker):
        super().__init__()
        self.SessionLocal = SessionLocal

    def run(self, tr: TaskRun, f: FileRow, data: bytes) -> None:
        # 1) 確保是 PDF bytes（不是 PDF 就先轉）
        try:
            if not (len(data) > 4 and data[:4] == b"%PDF"):
                pdf_bytes = _loader.load(data, LoadOptions(return_mode="PDF_BYTES"))
            else:
                pdf_bytes = data
        except Exception as e:
            raise RuntimeError(f"to-pdf failed: {e}")

        stem = _stem(f.user_filename)

        with tempfile.TemporaryDirectory(prefix="vlm-") as tmpdir:
            tmpdir = Path(tmpdir)
            image_dir, md_dir = prepare_env(str(tmpdir), stem, "vlm")
            image_dir = Path(image_dir)
            md_dir = Path(md_dir)

            # 2) 執行 VLM 解析
            middle_json, infer_result = vlm_doc_analyze(
                pdf_bytes,
                image_writer=None,
                backend="transformers",          # 視你的部署
                server_url=None,
                model_path=self.model_path,
                enable_formula=True,
                enable_table=True,
            )
            pdf_info = middle_json.get("pdf_info", middle_json)

            # 3) 產出 layout.pdf
            layout_file = md_dir / f"{stem}_layout.pdf"
            try:
                draw_layout_bbox(pdf_info, pdf_bytes, str(md_dir), layout_file.name)
            except Exception as e:
                logger.warning(f"draw_layout_bbox failed: {e}")

            # 4) 其他輸出
            (md_dir / f"{stem}_origin.bin").write_bytes(pdf_bytes)

            image_dir_name = os.path.basename(image_dir)
            md_content_str = vlm_union_make(pdf_info, MakeMode.MM_MD, image_dir_name)
            (md_dir / f"{stem}.md").write_text(md_content_str, encoding="utf-8")

            content_list = vlm_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir_name)
            (md_dir / f"{stem}_content_list.json").write_text(
                json.dumps(content_list, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (md_dir / f"{stem}_middle.json").write_text(
                json.dumps(middle_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (md_dir / f"{stem}_model_output.txt").write_text(str(infer_result), encoding="utf-8")

            # 5) 上傳 md/images 資料夾（不壓縮）
            md_prefix = _artifact_prefix(f.owner_id, f.id, tr.id, "extract")
            img_prefix = _artifact_prefix(f.owner_id, f.id, tr.id, "images")

            md_files    = _upload_dir_recursive(md_dir, md_prefix)
            image_files = _upload_dir_recursive(image_dir, img_prefix)

            # 6) 如果有 layout.pdf，單獨上傳並建 artifact
            layout_uri = None
            if layout_file.exists():
                layout_key = f"{md_prefix}/{layout_file.name}"
                layout_uri = put_bytes(_s3cfg, layout_key, layout_file.read_bytes(), "application/pdf")

        # 7) DB 寫入（manifest + layout 單獨 artifact）
        with self.SessionLocal() as db:
            db.add(Artifact(
                file_id=f.id,
                task_run_id=tr.id,
                kind="vlm_md_manifest",
                storage_uri=f"s3://{_s3cfg.bucket}/{md_prefix}/",
                meta={"files": md_files}
            ))
            db.add(Artifact(
                file_id=f.id,
                task_run_id=tr.id,
                kind="vlm_images_manifest",
                storage_uri=f"s3://{_s3cfg.bucket}/{img_prefix}/",
                meta={"files": image_files}
            ))
            if layout_uri:
                db.add(Artifact(
                    file_id=f.id,
                    task_run_id=tr.id,
                    kind="vlm_layout_pdf",
                    storage_uri=layout_uri,
                    meta={"filename": layout_file.name}
                ))
            db.commit()
