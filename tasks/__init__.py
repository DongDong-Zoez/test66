from __future__ import annotations
from sqlalchemy.orm import sessionmaker
from .manager import manager
from .doc_convert import DocConvertHandler
from .to_pdf import ToPdfHandler
from .vlm_ocr import VlmOcrHandler

def register_all(SessionLocal: sessionmaker):
    """
    由 worker 啟動時呼叫，注入共用 SessionLocal，並註冊所有 handler。
    之後要新增任務，只要：
      1) 新建 tasks/<your_task>.py（繼承 BaseHandler）
      2) 在這裡 import 你的 Handler 並 manager.register(YourHandler(SessionLocal))
    """
    manager.register(DocConvertHandler(SessionLocal))
    manager.register(ToPdfHandler(SessionLocal))
    manager.register(VlmOcrHandler(SessionLocal))
