from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import String, Text, BigInteger, JSON, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

def gen_uuid() -> str:
    return str(uuid4())

class Base(DeclarativeBase):
    pass

class File(Base):
    __tablename__ = "file"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    owner_id: Mapped[str] = mapped_column(String(36), default="user-anon")
    user_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255))
    byte_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)  # s3://bucket/key
    status: Mapped[str] = mapped_column(String(20), default="READY")  # READY/LOCKED/DELETED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    runs: Mapped[list["TaskRun"]] = relationship(back_populates="file", cascade="all,delete")

class TaskRun(Base):
    __tablename__ = "task_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    file_id: Mapped[str] = mapped_column(ForeignKey("file.id"))
    name: Mapped[str] = mapped_column(String(64))  # 'doc_convert','ocr_to_md',...
    params: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error: Mapped[Optional[str]] = mapped_column(Text)

    file: Mapped["File"] = relationship(back_populates="runs")

class Artifact(Base):
    __tablename__ = "artifact"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    file_id: Mapped[str] = mapped_column(ForeignKey("file.id"))
    task_run_id: Mapped[str] = mapped_column(ForeignKey("task_run.id"))
    kind: Mapped[str] = mapped_column(String(32))   # 'pdf','images_zip','image','md','jsonl'
    storage_uri: Mapped[str] = mapped_column(Text)
    meta: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
