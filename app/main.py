"""FastAPI 应用入口:路由注册、静态文件、启动时恢复会话。"""
import logging
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Windows 控制台中文日志显示(GBK 终端下避免乱码)
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from app.api import chat, files
from app.config import settings
from app.store import session_store
from app.utils.fonts import register_pdf_fonts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("main")

settings.ensure_dirs()
register_pdf_fonts()
restored = session_store.load_all()
if restored:
    logger.info("已恢复 %s 个历史会话", restored)

app = FastAPI(title="客户需求分析智能体", version="0.1.0")

app.include_router(chat.router)
app.include_router(files.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "sessions": len(session_store.list_sessions())}


app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
