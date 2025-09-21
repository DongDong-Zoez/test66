import os
import json
from pathlib import Path
from typing import List, Optional
from loguru import logger

from mineru.cli.common import prepare_env
from mineru.backend.vlm.vlm_analyze import doc_analyze as vlm_doc_analyze
from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make
from mineru.utils.enum_class import MakeMode
from mineru.utils.draw_bbox import draw_layout_bbox

def _backend_alias(backend: str) -> str:
    b = backend.strip().lower()
    if b.startswith("vlm-"):
        b = b.replace("vlm-", "")
    return b


class _FileWriter:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def write(self, filename: str, data: bytes):
        out = Path(self.base_dir) / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            f.write(data)

    def write_string(self, filename: str, text: str, encoding: str = "utf-8"):
        out = Path(self.base_dir) / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding=encoding) as f:
            f.write(text)


class ImageVLMParser:
    def __init__(
        self,
        output_dir: str,
        backend: str = "vlm-transformers",
        server_url: Optional[str] = None,
        model_path: Optional[str] = None,
        enable_formula: bool = True,
        enable_table: bool = True,
    ):
        self.output_dir = output_dir
        self.backend = backend
        self.server_url = server_url
        self.model_path = model_path
        self.enable_formula = enable_formula
        self.enable_table = enable_table

    def parse(self, pdf_bytes_list: List[bytes], pdf_file_names: List[str]):
        for idx, pdf_bytes in enumerate(pdf_bytes_list):
            pdf_file_name = pdf_file_names[idx]

            # 建立輸出目錄
            local_image_dir, local_md_dir = prepare_env(self.output_dir, pdf_file_name, "vlm")
            image_writer, md_writer = _FileWriter(local_image_dir), _FileWriter(local_md_dir)

            # 呼叫 VLM 推理
            middle_json, infer_result = vlm_doc_analyze(
                pdf_bytes,
                image_writer=image_writer,
                backend=_backend_alias(self.backend),
                server_url=self.server_url,
                model_path=self.model_path,
                enable_formula=self.enable_formula,
                enable_table=self.enable_table,
            )

            pdf_info = middle_json.get("pdf_info", middle_json)

            # 1) 畫 layout bbox（對影像）
            try:
                draw_layout_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_layout.pdf")
            except Exception as e:
                logger.warning(f"draw_layout_bbox failed: {e}")

            # 2) 輸出原始影像
            md_writer.write(f"{pdf_file_name}_origin.png", pdf_bytes)

            # 3) 多模態 Markdown
            image_dir_name = os.path.basename(local_image_dir)
            md_content_str = vlm_union_make(pdf_info, MakeMode.MM_MD, image_dir_name)
            md_writer.write_string(f"{pdf_file_name}.md", md_content_str)

            # 4) content_list
            content_list = vlm_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir_name)
            md_writer.write_string(
                f"{pdf_file_name}_content_list.json",
                json.dumps(content_list, ensure_ascii=False, indent=2),
            )

            # 5) 中介 JSON
            md_writer.write_string(
                f"{pdf_file_name}_middle.json",
                json.dumps(middle_json, ensure_ascii=False, indent=2),
            )

            # 6) 模型原始輸出
            if isinstance(infer_result, (list, tuple)):
                model_output = ("\n" + "-" * 50 + "\n").join(map(str, infer_result))
            else:
                model_output = str(infer_result)
            md_writer.write_string(f"{pdf_file_name}_model_output.txt", model_output)

            logger.info(f"✅ Done: {pdf_file_name} → {local_md_dir}")

if __name__ == "__main__":
    from loader import DocumentToImagesLoader, LoadOptions
    loader = DocumentToImagesLoader()

    # 1) 路徑/bytes → 直接回傳 PDF bytes（對 PDF/Office/HTML 不光柵化）
    with open("./2025_04_12.docx", "rb") as f:
        pdf_bytes = f.read()
    pdf_out = loader.load(pdf_bytes, LoadOptions(return_mode="PDF_BYTES"))

    from pathlib import Path

    # 載入圖片 bytes
    bytes = [pdf_out]
    names = ["test"]

    parser = ImageVLMParser(
        output_dir="output_images",
        backend="vlm-transformers",   # 或 vlm-transformers / vlm-http-client
        model_path="/home/dongdong/MinerU2.5-2509-1.2B",
    )
    parser.parse(bytes, names)