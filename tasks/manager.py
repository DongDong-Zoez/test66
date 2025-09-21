from __future__ import annotations
from typing import Dict
from models import File as FileRow, TaskRun
from .base import BaseHandler

class TaskManager:
    def __init__(self) -> None:
        self._handlers: Dict[str, BaseHandler] = {}

    def register(self, handler: BaseHandler) -> None:
        key = handler.name.strip().lower()
        if key in self._handlers:
            raise ValueError(f"handler already registered: {key}")
        self._handlers[key] = handler

    def run(self, tr: TaskRun, f: FileRow, data: bytes) -> None:
        key = tr.name.strip().lower()
        if key not in self._handlers:
            raise ValueError(f"unknown task: {key}")
        self._handlers[key].run(tr, f, data)

# 單例
manager = TaskManager()
