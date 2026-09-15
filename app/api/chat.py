"""会话 CRUD + SSE 流端点 + 确认端点。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.orchestrator import handle_message
from app.models.schemas import Message, Session
from app.store import session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class StreamRequest(BaseModel):
    kind: str = "message"       # message | revise
    text: str = ""


def _public_session(session: Session) -> dict:
    return {
        "session_id": session.session_id,
        "title": session.title,
        "phase": session.phase,
        "requirement": session.state.requirement.model_dump(by_alias=True) if session.state else None,
        "version": session.state.requirement.meta.version if session.state and session.state.requirement else None,
        "research_brief": session.research_brief,
        "messages": [m.model_dump() for m in session.messages],
        "files": {k: v.model_dump() for k, v in session.files.items()},
        "requested_files": session.requested_files,
        "task_files": [r.model_dump() for r in session.task_files],
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


@router.post("")
def create_session() -> dict:
    session = session_store.create_session()
    return {"session_id": session.session_id, "title": session.title,
            "created_at": session.created_at}


@router.get("")
def list_sessions() -> list[dict]:
    return [
        {"session_id": s.session_id, "title": s.title, "phase": s.phase,
         "updated_at": s.updated_at}
        for s in session_store.list_sessions()
    ]


@router.get("/{sid}")
def get_session(sid: str) -> dict:
    session = _require(sid)
    return _public_session(session)


@router.delete("/{sid}", status_code=204)
def delete_session(sid: str) -> None:
    if not session_store.delete_session(sid):
        raise HTTPException(404, "会话不存在")


@router.post("/{sid}/stream")
def stream(sid: str, body: StreamRequest,
           x_api_key: str | None = Header(None, alias="X-API-Key")) -> StreamingResponse:
    """SSE 流端点:承载 clarify 问答、confirm 修改意见、done 自由聊天。

    客户端在 X-API-Key 请求头中携带使用者的 DeepSeek Key(仅存内存,不落盘)。
    """
    session = _require(sid)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "内容不能为空")
    if x_api_key and x_api_key.strip():
        session.api_key = x_api_key.strip()

    if session.title in ("新会话", ""):
        session.title = text.strip()[:20]
    session.messages.append(Message(role="user", content=text, kind="text"))
    session_store.save_session(session)

    async def event_source():
        try:
            async for event, payload in handle_message(session, text, body.kind):
                yield _sse(event, payload)
        except Exception:
            logger.exception("SSE 流异常")
            yield _sse("error", {"message": "服务暂时不可用,请重试"})
        finally:
            session_store.save_session(session)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{sid}/confirm")
def confirm(sid: str,
            x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
    session = _require(sid)
    if x_api_key and x_api_key.strip():
        session.api_key = x_api_key.strip()
    if session.phase != "confirm":
        raise HTTPException(409, "当前阶段不可确认")
    session.phase = "choose"
    ask = ("需求已确认。请问需要导出为哪些文件?可选:Word 报告 / PPT 演示 / Excel 表格 / "
           "PDF 文档,回复名称即可(可多选),或回复“全部”。")
    session.messages.append(Message(role="assistant", content=ask, kind="file_choice",
                                    payload={"options": ["word", "ppt", "excel", "pdf"]}))
    session_store.save_session(session)
    return {"phase": "choose"}


def _require(sid: str) -> Session:
    session = session_store.get_session(sid)
    if session is None:
        raise HTTPException(404, "会话不存在")
    return session


def _sse(event: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"
