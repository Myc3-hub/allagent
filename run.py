"""启动入口:uvicorn app.main:app

注意:会话存储为内存 + JSON 持久化,必须单 worker 运行。
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.port,
        workers=1,
    )
