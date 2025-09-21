import os
import subprocess
from typing import Optional

def _which(program: str) -> Optional[str]:
    """尋找可執行檔路徑 (等同於 Linux 的 which)"""
    for path in os.environ.get("PATH", "").split(os.pathsep):
        exe_file = os.path.join(path, program)
        if os.path.isfile(exe_file) and os.access(exe_file, os.X_OK):
            return exe_file
    return None

def _run(cmd, timeout: int = 300):
    """執行命令列，並等待完成"""
    subprocess.run(cmd, check=True, timeout=timeout)

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


# ===== 範例用法 =====
if __name__ == "__main__":
    input_file = "/home/dongdong/runtimes/橘色白色模組化抽象策略簡報商務簡報.pptx"   # 你要轉換的檔案
    output_dir = "output_dir"   # 輸出 PDF 的資料夾
    os.makedirs(output_dir, exist_ok=True)

    pdf_file = _libreoffice_to_pdf(input_file, output_dir)
    print("✅ 已存檔 PDF：", pdf_file)
