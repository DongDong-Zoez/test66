#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc2images_magika.py
- 文件 → 圖片（每頁）
- 以 Google Magika 進行內容類型偵測（支援 bytes 與 path）
- 輸入：路徑或 bytes
- 輸出：PIL 物件列表 / 每頁 image bytes / 儲存路徑 / ZIP bytes / PDF bytes（新）

依賴：
  pip install magika pymupdf pillow
  # (選用) HTML→PDF：pip install weasyprint  (需要 cairo/pango)
  # (選用) HTML 後備：安裝 google-chrome 或 chromium
  # (選用) Office→PDF：安裝 libreoffice（有 soffice 指令）

使用範例見最下方 __main__。
"""

from __future__ import annotations
import io
import os
import shutil
import subprocess
import tempfile
import mimetypes
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union, Literal

# --- 必要依賴 ---
try:
    from magika import Magika
except Exception as e:
    raise RuntimeError("缺少 Magika：請先 `pip install magika`") from e

try:
    import fitz  # PyMuPDF
except Exception as e:
    raise RuntimeError("缺少 PyMuPDF：請先 `pip install pymupdf`") from e

try:
    from PIL import Image
except Exception as e:
    raise RuntimeError("缺少 Pillow：請先 `pip install pillow`") from e

# --- 選用：HTML → PDF ---
try:
    from weasyprint import HTML  # type: ignore
except Exception:
    HTML = None  # 用 Chrome/Chromium 當後備

BytesLike = Union[bytes, bytearray, io.BytesIO, memoryview]
PathLike = Union[str, os.PathLike]
DocInput = Union[PathLike, BytesLike]
ReturnMode = Literal["PIL", "BYTES", "PATHS", "ZIP_BYTES", "PDF_BYTES"]


# -------------------------
# 小工具
# -------------------------
def _is_path(x: DocInput) -> bool:
    return isinstance(x, (str, os.PathLike))


def _read_all(b: BytesLike) -> bytes:
    if isinstance(b, (bytes, bytearray)):
        return bytes(b)
    if isinstance(b, memoryview):
        return b.tobytes()
    if isinstance(b, io.BytesIO):
        return b.getvalue()
    raise TypeError(f"Unsupported bytes-like object: {type(b)}")


def _ext_lower(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 300) -> None:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({' '.join(cmd)}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


# -------------------------
# 類型偵測（Magika 優先）
# -------------------------
_magika = Magika()

def _detect_type(doc: DocInput) -> Tuple[str, Optional[str], str]:
    """
    回傳 (label_or_mime, path_if_any, source)
    - 若 source == 'magika'，第一個值是 label（如 'pdf','docx','png','html'...）
    - 若 source != 'magika'，第一個值多半是 mimetype（e.g. 'application/pdf'）
    """
    if _is_path(doc):
        path = str(doc)
        # 1) Magika（path）
        try:
            res = _magika.identify_path(path)
            return res.output.label, path, "magika"
        except Exception:
            pass
        # 2) mimetypes 後備
        mime, _ = mimetypes.guess_type(path)
        return (mime or "application/octet-stream"), path, "mimetypes"

    # bytes 輸入
    data = _read_all(doc)
    # 1) Magika（bytes）
    try:
        res = _magika.identify_bytes(data)
        return res.output.label, None, "magika"
    except Exception:
        pass

    # 2) 簡單 magic sniff（常見影像 / PDF）
    if data[:4] == b"%PDF":
        return "application/pdf", None, "sniff"
    if data[:8].startswith(b"\x89PNG"):
        return "image/png", None, "sniff"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", None, "sniff"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff", None, "sniff"
    if data[:12] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", None, "sniff"

    return "application/octet-stream", None, "sniff"


# -------------------------
# 轉檔輔助
# -------------------------
def _libreoffice_to_pdf(input_path: str, out_dir: str, timeout: int = 300) -> str:
    soffice = _which("soffice") or _which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice 未安裝，無法將 Office 轉為 PDF。請安裝 libreoffice。")
    _run([soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir, input_path], timeout=timeout)
    base = os.path.splitext(os.path.basename(input_path))[0]
    pdf_path = os.path.join(out_dir, base + ".pdf")
    if not os.path.exists(pdf_path):
        cands = [p for p in os.listdir(out_dir) if p.lower().endswith(".pdf")]
        if len(cands) == 1:
            pdf_path = os.path.join(out_dir, cands[0])
    if not os.path.exists(pdf_path):
        raise RuntimeError("LibreOffice 轉換成功但找不到輸出 PDF。")
    return pdf_path


def _html_to_pdf(input_path: str, out_pdf: str, timeout: int = 300) -> str:
    if HTML is not None:
        HTML(filename=input_path).write_pdf(out_pdf)
        return out_pdf
    chrome = _which("google-chrome") or _which("chromium") or _which("chromium-browser")
    if not chrome:
        raise RuntimeError("缺少 HTML 渲染器（WeasyPrint 或 Chrome/Chromium）。")
    tmpdir = tempfile.mkdtemp(prefix="html2pdf-")
    try:
        pdf_tmp = os.path.join(tmpdir, "out.pdf")
        _run([chrome, "--headless", f"--print-to-pdf={pdf_tmp}", input_path], timeout=timeout)
        shutil.copy2(pdf_tmp, out_pdf)
        return out_pdf
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _open_pdf_as_images(
    pdf_input: Union[str, bytes],
    dpi: int = 200,
    max_side: Optional[int] = None,
    bg: Optional[Tuple[int, int, int, int]] = None,
) -> List["Image.Image"]:
    scale = dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    doc = fitz.open(stream=pdf_input, filetype="pdf") if isinstance(pdf_input, (bytes, bytearray)) else fitz.open(pdf_input)
    images: List[Image.Image] = []
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=True)
            im = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
            if bg is not None and im.mode == "RGBA":
                base = Image.new("RGBA", im.size, bg)
                base.paste(im, mask=im.split()[-1])
                im = base.convert("RGB")
            if max_side is not None:
                w, h = im.size
                m = max(w, h)
                if m > max_side:
                    r = max_side / float(m)
                    im = im.resize((int(w * r), int(h * r)), Image.Resampling.LANCZOS)
            images.append(im)
    finally:
        doc.close()
    return images


# -------------------------
# 公開 API
# -------------------------
@dataclass
class LoadOptions:
    dpi: int = 200
    max_side: Optional[int] = None
    background_rgba: Optional[Tuple[int, int, int, int]] = None
    save: bool = False
    output_dir: Optional[str] = None
    filename_prefix: str = "page"
    image_format: str = "PNG"  # PNG/JPEG/WEBP/TIFF
    return_mode: ReturnMode = "PIL"  # PIL | BYTES | PATHS | ZIP_BYTES | PDF_BYTES
    zip_name_in_zip: Optional[str] = None  # 自訂 zip 內檔名（會自動帶頁碼）


class DocumentToImagesLoader:
    """
    使用：
        loader = DocumentToImagesLoader()
        pages = loader.load(bytes_or_path, LoadOptions(...))
    """

    OFFICE_LABELS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "odp", "ods", "rtf"}
    IMAGE_LABELS  = {"png", "jpeg", "jpg", "webp", "tiff", "bmp"}
    HTML_LABELS   = {"html", "htm"}

    OFFICE_MIMES = {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/rtf",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.oasis.opendocument.spreadsheet",
    }

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp"}
    HTML_EXTS  = {".html", ".htm"}

    # ---- helpers ----
    def _images_to_bytes(self, images: List["Image.Image"], fmt: str) -> List[bytes]:
        out: List[bytes] = []
        for im in images:
            bio = io.BytesIO()
            to_save = im.convert("RGB") if fmt.upper() in ("JPG", "JPEG") and im.mode != "RGB" else im
            to_save.save(bio, format=fmt.upper())
            out.append(bio.getvalue())
        return out

    def _images_to_zip_bytes(self, images: List["Image.Image"], fmt: str, prefix: str, name_hint: Optional[str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, im in enumerate(images, 1):
                bio = io.BytesIO()
                to_save = im.convert("RGB") if fmt.upper() in ("JPG", "JPEG") and im.mode != "RGB" else im
                to_save.save(bio, format=fmt.upper())
                bio.seek(0)
                if name_hint:
                    root, ext = os.path.splitext(name_hint)
                    entry = f"{root}_{i:04d}{ext or '.'+fmt.lower()}"
                else:
                    entry = f"{prefix}_{i:04d}.{fmt.lower()}"
                zf.writestr(entry, bio.read())
        return buf.getvalue()

    def _images_to_pdf_bytes(self, images: List["Image.Image"], dpi: int) -> bytes:
        """
        將多張影像組成一份 PDF（每張圖一頁）。
        使用 PyMuPDF 以像素→點數換算：points = pixels / dpi * 72
        """
        pdf = fitz.open()
        try:
            for im in images:
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                w_px, h_px = im.size
                w_pt = w_px / float(dpi) * 72.0
                h_pt = h_px / float(dpi) * 72.0
                page = pdf.new_page(width=w_pt, height=h_pt)

                bio = io.BytesIO()
                im.save(bio, format="PNG")  # 用 PNG 以保真；若要更小可改 JPEG
                bio.seek(0)

                rect = fitz.Rect(0, 0, w_pt, h_pt)
                page.insert_image(rect, stream=bio.read())
            out = pdf.tobytes()
        finally:
            pdf.close()
        return out

    # ---- main ----
    def load(self, doc: DocInput, options: Optional[LoadOptions] = None) -> Union[
        List["Image.Image"], List[bytes], List[str], bytes
    ]:
        options = options or LoadOptions()
        fmt = options.image_format
        prefix = options.filename_prefix

        label_or_mime, path, src = _detect_type(doc)
        ext = _ext_lower(path) if path else None
        label = label_or_mime if src == "magika" else None
        mime  = None if src == "magika" else label_or_mime

        with tempfile.TemporaryDirectory(prefix="doc2img-") as work:
            # 將 bytes 寫到暫存檔（非 path 情形）
            data_bytes: Optional[bytes] = None
            src_path: str
            if _is_path(doc):
                src_path = os.path.abspath(str(doc))
            else:
                data_bytes = _read_all(doc)
                guessed = {
                    "application/pdf": ".pdf",
                    "text/html": ".html",
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "image/tiff": ".tiff",
                    "image/webp": ".webp",
                }.get(mime if mime else "", ".bin")
                src_path = os.path.join(work, f"input{guessed}")
                with open(src_path, "wb") as f:
                    f.write(data_bytes)
                if not ext:
                    ext = _ext_lower(src_path)

            # ---- 路由邏輯：優先依 Magika label，其次 MIME/副檔名 ----
            images: List[Image.Image]

            is_pdf = (label == "pdf") or (mime == "application/pdf") or (ext == ".pdf")
            is_office = (label in self.OFFICE_LABELS) or (mime in self.OFFICE_MIMES)
            is_html = (label in self.HTML_LABELS) or (mime == "text/html") or (ext in self.HTML_EXTS if ext else False)
            is_image = (label in self.IMAGE_LABELS) or (mime and str(mime).startswith("image/")) or (ext in self.IMAGE_EXTS if ext else False)

            # ===== 若要求 PDF_BYTES，盡可能避免光柵化（直接回傳 PDF bytes）=====
            if options.return_mode == "PDF_BYTES":
                if is_pdf:
                    if data_bytes is not None:
                        return bytes(data_bytes)
                    else:
                        with open(src_path, "rb") as f:
                            return f.read()
                elif is_office:
                    pdf_path = _libreoffice_to_pdf(src_path, out_dir=work)
                    with open(pdf_path, "rb") as f:
                        return f.read()
                elif is_html:
                    pdf_path = os.path.join(work, "from_html.pdf")
                    _html_to_pdf(src_path, pdf_path)
                    with open(pdf_path, "rb") as f:
                        return f.read()
                # 影像或其他：落到既有流程產生 images，最後再組成 PDF bytes

            # ===== 既有影像路徑（非 PDF_BYTES 或影像/其他需要光柵化）=====
            if is_pdf:
                images = _open_pdf_as_images(
                    data_bytes if data_bytes and data_bytes[:4] == b"%PDF" else src_path,
                    dpi=options.dpi, max_side=options.max_side, bg=options.background_rgba
                )

            elif is_office:
                pdf_path = _libreoffice_to_pdf(src_path, out_dir=work)
                images = _open_pdf_as_images(pdf_path, dpi=options.dpi, max_side=options.max_side, bg=options.background_rgba)

            elif is_html:
                pdf_path = os.path.join(work, "from_html.pdf")
                _html_to_pdf(src_path, pdf_path)
                images = _open_pdf_as_images(pdf_path, dpi=options.dpi, max_side=options.max_side, bg=options.background_rgba)

            elif is_image:
                im = Image.open(src_path).convert("RGBA")
                if options.background_rgba is not None:
                    base = Image.new("RGBA", im.size, options.background_rgba)
                    base.paste(im, mask=im.split()[-1])
                    im = base.convert("RGB")
                if options.max_side is not None:
                    w, h = im.size
                    m = max(w, h)
                    if m > options.max_side:
                        r = options.max_side / float(m)
                        im = im.resize((int(w * r), int(h * r)), Image.Resampling.LANCZOS)
                images = [im]

            else:
                # 最後一搏：嘗試用 LibreOffice 轉 PDF（如果有副檔名能處理）
                if ext and ext not in (".bin",):
                    pdf_path = _libreoffice_to_pdf(src_path, out_dir=work)
                    images = _open_pdf_as_images(pdf_path, dpi=options.dpi, max_side=options.max_side, bg=options.background_rgba)
                else:
                    raise ValueError(f"Unsupported or unknown document type: label={label} mime={mime} ext={ext} src={src}")

            # ---- 存檔（可選）----
            saved_paths: List[str] = []
            if options.save:
                out_dir = options.output_dir or os.path.join(os.getcwd(), "doc_images")
                os.makedirs(out_dir, exist_ok=True)
                for i, im in enumerate(images, 1):
                    fname = f"{prefix}_{i:04d}.{fmt.lower()}"
                    fp = os.path.join(out_dir, fname)
                    to_save = im.convert("RGB") if fmt.upper() in ("JPEG", "JPG") and im.mode != "RGB" else im
                    to_save.save(fp, format=fmt.upper())
                    saved_paths.append(fp)

            # ---- 回傳模式 ----
            if options.return_mode == "PIL":
                return images
            elif options.return_mode == "BYTES":
                return self._images_to_bytes(images, fmt)
            elif options.return_mode == "PATHS":
                if not saved_paths:
                    # 若未設定 save=True 但指定 PATHS，則自動寫到預設資料夾
                    out_dir = options.output_dir or os.path.join(os.getcwd(), "doc_images")
                    os.makedirs(out_dir, exist_ok=True)
                    for i, im in enumerate(images, 1):
                        fp = os.path.join(out_dir, f"{prefix}_{i:04d}.{fmt.lower()}")
                        to_save = im.convert("RGB") if fmt.upper() in ("JPEG","JPG") and im.mode != "RGB" else im
                        to_save.save(fp, format=fmt.upper())
                        saved_paths.append(fp)
                return saved_paths
            elif options.return_mode == "ZIP_BYTES":
                return self._images_to_zip_bytes(images, fmt, prefix, options.zip_name_in_zip)
            elif options.return_mode == "PDF_BYTES":
                # 走到這裡代表來源不是 PDF/Office/HTML（或明確要求影像流程），把 images 打包為單一 PDF
                return self._images_to_pdf_bytes(images, options.dpi)
            else:
                raise ValueError(f"Unknown return_mode: {options.return_mode}")


# -------------------------
# 範例
# -------------------------
if __name__ == "__main__":
    loader = DocumentToImagesLoader()

    # 1) 路徑/bytes → 直接回傳 PDF bytes（對 PDF/Office/HTML 不光柵化）
    try:
        with open("./test.pdf", "rb") as f:
            pdf_bytes = f.read()
        pdf_out = loader.load(pdf_bytes, LoadOptions(return_mode="PDF_BYTES"))
        with open("copy_from_bytes.pdf", "wb") as f:
            f.write(pdf_out)
        print("PDF_BYTES (PDF 來源) OK")
    except FileNotFoundError:
        print("示例：找不到 DINO 系列模型深入報告.pdf，略過 PDF_BYTES 測試。")

    # 2) DOCX → 直接轉 PDF 回傳 bytes（保持可選文字）
    if os.path.exists("2025_04_12.docx"):
        pdfb = loader.load("2025_04_12.docx", LoadOptions(return_mode="PDF_BYTES"))
        with open("2025_04_12.pdf", "wb") as f:
            f.write(pdfb)
        print("PDF_BYTES (DOCX 來源) OK")

    # 3) PPTX → 直接轉 PDF 回傳 bytes
    if os.path.exists("橘色白色模組化抽象策略簡報商務簡報.pptx"):
        pdfb = loader.load("橘色白色模組化抽象策略簡報商務簡報.pptx", LoadOptions(return_mode="PDF_BYTES"))
        with open("橘色白色模組化抽象策略簡報商務簡報.pdf", "wb") as f:
            f.write(pdfb)
        print("PDF_BYTES (PPTX 來源) OK")

    # 4) 單張圖片 → 合成單頁 PDF
    if os.path.exists("photo.jpg"):
        pdfb = loader.load("photo.jpg", LoadOptions(return_mode="PDF_BYTES", max_side=1600))
        with open("photo.pdf", "wb") as f:
            f.write(pdfb)
        print("PDF_BYTES (影像來源) OK")

    # 5) 原本的圖片輸出流程仍可用
    if os.path.exists("photo.jpg"):
        out_bytes = loader.load("photo.jpg", LoadOptions(max_side=1600, image_format="WEBP", return_mode="BYTES"))
        print(f"Image pages: {len(out_bytes)}")
