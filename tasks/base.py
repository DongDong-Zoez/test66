from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional
from models import File as FileRow, TaskRun

class BaseHandler(ABC):
    """
    每個任務繼承 BaseHandler，實作：
      - name: 任務名稱（例如 'doc_convert'）
      - run(tr, f, data): 核心邏輯
    """
    name: str = ""

    def __init__(self) -> None:
        if not self.name:
            raise ValueError("Handler must define a non-empty `name`")

    @abstractmethod
    def run(self, tr: TaskRun, f: FileRow, data: bytes) -> None:
        """執行任務。需自行寫入 Artifact／更新資料等。"""
        raise NotImplementedError
