"""会话存储:内存 dict + 线程锁 + 变更时写 data/sessions.json(重启恢复)。"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import uuid
from datetime import datetime

from app.config import settings
from app.models.schemas import Session

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sessions: dict[str, Session] = {}

_STORE_FILE = settings.data_dir / "sessions.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _persist() -> None:
    try:
        settings.ensure_dirs()
        with _lock:
            # api_key 为使用者的密钥,严禁落盘
            data = {sid: s.model_dump(exclude={"api_key"}) for sid, s in _sessions.items()}
        _STORE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("会话持久化失败(不影响本次运行)")


def create_session(first_text: str = "") -> Session:
    sid = uuid.uuid4().hex[:12]
    title = (first_text.strip()[:20] or "新会话")
    session = Session(session_id=sid, title=title)
    with _lock:
        _sessions[sid] = session
    _persist()
    return session


def get_session(sid: str) -> Session | None:
    with _lock:
        return _sessions.get(sid)


def list_sessions() -> list[Session]:
    with _lock:
        return sorted(_sessions.values(), key=lambda s: s.updated_at, reverse=True)


def save_session(session: Session) -> None:
    """保存会话状态(更新时间戳 + 持久化)。"""
    session.updated_at = _now()
    with _lock:
        _sessions[session.session_id] = session
    _persist()


def delete_session(sid: str) -> bool:
    with _lock:
        existed = _sessions.pop(sid, None) is not None
    if existed:
        shutil.rmtree(settings.output_dir / sid, ignore_errors=True)
        _persist()
    return existed


def load_all() -> int:
    """启动时从 data/sessions.json 恢复会话。"""
    if not _STORE_FILE.exists():
        return 0
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        count = 0
        for sid, payload in raw.items():
            try:
                with _lock:
                    _sessions[sid] = Session.model_validate(payload)
                count += 1
            except Exception:
                logger.warning("会话 %s 恢复失败,已跳过", sid)
        return count
    except Exception:
        logger.exception("会话文件读取失败")
        return 0
