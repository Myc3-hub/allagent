"""文件生成与下载端点。生成端点同步执行(线程池),单会话文件按版本命名。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.files.registry import FILE_TYPES
from app.llm.client import LLMError, json_call
from app.models.schemas import FileRecord
from app.store import session_store
from app.utils.text import safe_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["files"])


@router.post("/{sid}/files/{ftype}")
def generate_file(sid: str, ftype: str,
                  x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
    session = _require(sid)
    if x_api_key and x_api_key.strip():
        session.api_key = x_api_key.strip()
    entry = FILE_TYPES.get(ftype)
    if not entry:
        raise HTTPException(404, "不支持的文件类型")
    if session.phase not in ("confirm", "done"):
        raise HTTPException(409, "请先完成需求确认")
    if not session.state:
        raise HTTPException(409, "会话尚未进行需求分析")

    doc = session.state.requirement
    doc_json = json.dumps(doc.model_dump(by_alias=True), ensure_ascii=False)
    user = (
        entry["prompt"]
        + "\n\n【输入材料】需求文档(JSON)。本文件允许引用的数据来源仅限其中 references "
          "数组,严禁新增或改写来源:\n" + doc_json
    )
    try:
        ir = json_call("", user, max_tokens=8192, schema=entry["ir"],
                       api_key=session.api_key)
    except LLMError as exc:
        raise HTTPException(502, str(exc))

    prev = session.files.get(ftype)
    version = (prev.version + 1) if prev else 1
    filename = f"{safe_filename(doc.short_title())}_{entry['suffix']}_v{version}{entry['ext']}"
    out_dir = settings.output_dir / sid
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    try:
        entry["render"](ir, out_path)
    except Exception:
        logger.exception("文件渲染失败 %s", ftype)
        raise HTTPException(500, "文件渲染失败,请重试")

    record = FileRecord(
        file_type=ftype, filename=filename,
        size_bytes=out_path.stat().st_size, version=version,
    )
    session.files[ftype] = record
    session_store.save_session(session)
    return {"file": record.model_dump()}


@router.get("/{sid}/files/{ftype}/download")
def download_file(sid: str, ftype: str) -> FileResponse:
    session = _require(sid)
    record = session.files.get(ftype)
    if not record:
        raise HTTPException(404, "文件尚未生成")
    path = settings.output_dir / sid / record.filename
    if not path.exists():
        raise HTTPException(404, "文件已丢失,请重新生成")
    return FileResponse(path, filename=record.filename,
                        media_type="application/octet-stream")


@router.get("/{sid}/task-files/{index}/download")
def download_task_file(sid: str, index: int) -> FileResponse:
    """通用任务生成文件的下载(发言稿/主题PPT/报告/通知)。"""
    session = _require(sid)
    try:
        record = session.task_files[index]
    except IndexError:
        raise HTTPException(404, "文件不存在")
    path = settings.output_dir / sid / record.filename
    if not path.exists():
        raise HTTPException(404, "文件已丢失,请重新生成")
    return FileResponse(path, filename=record.filename,
                        media_type="application/octet-stream")


def _require(sid: str):
    session = session_store.get_session(sid)
    if session is None:
        raise HTTPException(404, "会话不存在")
    return session
