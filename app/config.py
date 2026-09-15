"""全局配置:从 .env 读取,集中管理路径与行为参数。"""
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_env(name: str) -> str:
    return os.environ.get(name, "")


class Settings(BaseModel):
    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 服务
    port: int = 8000

    # 路径
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    output_dir: Path = PROJECT_ROOT / "output"
    static_dir: Path = PROJECT_ROOT / "static"

    # 字体:优先 Windows 系统字体,不存在时回退到随项目打包的思源黑体(Linux 部署)
    font_msyh: Path = Path(r"C:\Windows\Fonts\msyh.ttc")   # 微软雅黑(标题)
    font_simsun: Path = Path(r"C:\Windows\Fonts\simsun.ttc")  # 宋体(正文)
    font_simhei: Path = Path(r"C:\Windows\Fonts\simhei.ttf")  # 黑体
    bundled_font: Path = PROJECT_ROOT / "fonts" / "NotoSansSC-Regular.ttf"

    # 澄清行为:只提一轮问题(≤3 个,直击核心),回答后直接进入调研定稿
    max_clarify_rounds: int = 1          # 提问轮数上限(1 = 只问一轮)
    max_questions_total: int = 3         # 提问总数上限
    ask_twice_then_assume: int = 2       # 同一字段问 N 次未答 → assumed

    # 调研行为
    max_queries: int = 4                 # 检索词数量上限(3 个确定性主题词 + LLM 候选)
    max_pages_fetch: int = 5             # 抓取正文页数上限
    fetch_timeout: float = 10.0          # 单页抓取超时(秒)
    fetch_max_bytes: int = 300_000       # 单页大小上限(约 300KB)
    research_enabled: bool = True        # 调研总开关(断网时可关)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


settings = Settings(
    deepseek_api_key=_read_env("DEEPSEEK_API_KEY"),
    deepseek_base_url=_read_env("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
    deepseek_model=_read_env("DEEPSEEK_MODEL") or "deepseek-chat",
    port=int(_read_env("PORT") or 8000),
)
