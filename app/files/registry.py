"""文件类型注册表:ftype → {IR 模型, 生成 prompt, 渲染函数, 后缀, 名称后缀}。"""
from __future__ import annotations

from app.files import render_excel, render_pdf, render_ppt, render_word
from app.llm.prompts import FILE_PROMPTS
from app.models.intermediates import ExcelDocIR, PdfDocIR, PptDocIR, WordDocIR

FILE_TYPES: dict[str, dict] = {
    "word": {
        "label": "Word 报告",
        "ir": WordDocIR,
        "prompt": FILE_PROMPTS["word"],
        "render": render_word.render,
        "ext": ".docx",
        "suffix": "需求分析报告",
    },
    "ppt": {
        "label": "PPT 演示",
        "ir": PptDocIR,
        "prompt": FILE_PROMPTS["ppt"],
        "render": render_ppt.render,
        "ext": ".pptx",
        "suffix": "需求汇报",
    },
    "excel": {
        "label": "Excel 表格",
        "ir": ExcelDocIR,
        "prompt": FILE_PROMPTS["excel"],
        "render": render_excel.render,
        "ext": ".xlsx",
        "suffix": "需求清单与预算",
    },
    "pdf": {
        "label": "PDF 文档",
        "ir": PdfDocIR,
        "prompt": FILE_PROMPTS["pdf"],
        "render": render_pdf.render,
        "ext": ".pdf",
        "suffix": "需求规格说明书",
    },
}
