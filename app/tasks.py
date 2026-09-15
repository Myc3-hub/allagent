"""通用任务引擎:发言稿 / 主题PPT / 报告方案 / 通知公告。

复用需求分析的文件 IR 与渲染器(WordDocIR/PptDocIR → render_word/render_ppt),
任务参数(topic/audience/occasion/style/length/requirements)由 LLM 提取与补充。
"""
from __future__ import annotations

from app.files import render_ppt, render_word
from app.llm.prompts import TASK_FILE_PROMPTS
from app.models.intermediates import PptDocIR, WordDocIR

# task 类型 → 配置;file_type 用于 FileRecord 与下载路径(复用 word/ppt)
TASK_TYPES: dict[str, dict] = {
    "speech": {
        "label": "发言稿",
        "action": "撰写发言稿",
        "ir": WordDocIR,
        "prompt": TASK_FILE_PROMPTS["speech"],
        "render": render_word.render,
        "ext": ".docx",
        "file_type": "word",
        "research": False,   # 是否需要公开数据调研
    },
    "ppt": {
        "label": "主题PPT",
        "action": "制作主题演示文稿",
        "ir": PptDocIR,
        "prompt": TASK_FILE_PROMPTS["ppt"],
        "render": render_ppt.render,
        "ext": ".pptx",
        "file_type": "ppt",
        "research": True,
    },
    "report": {
        "label": "报告/方案",
        "action": "撰写报告或方案",
        "ir": WordDocIR,
        "prompt": TASK_FILE_PROMPTS["report"],
        "render": render_word.render,
        "ext": ".docx",
        "file_type": "word",
        "research": True,
    },
    "notice": {
        "label": "通知/公告",
        "action": "撰写通知或公告",
        "ir": WordDocIR,
        "prompt": TASK_FILE_PROMPTS["notice"],
        "render": render_word.render,
        "ext": ".docx",
        "file_type": "word",
        "research": False,
    },
}

TASK_LABELS = {key: cfg["label"] for key, cfg in TASK_TYPES.items()}
