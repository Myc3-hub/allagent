"""四类文件的内容中间表示(IR)与数据引用模型。

LLM 按此 Schema 输出 JSON → Pydantic 严格校验 → 渲染器渲染为最终文件。
字数/数量上限是 prompt 硬约束;渲染器再做截断兜底。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Reference(BaseModel):
    """一条已公布数据的引用。URL 只能来自搜索/抓取元数据,LLM 禁止编造。"""
    id: str                                  # ref-01
    claim: str                               # 数据点一句话
    source_name: str                         # 来源机构/网站
    source_url: str
    retrieved_at: str                        # 检索日期
    confidence: Literal["high", "medium", "low"] = "medium"

    model_config = {"extra": "ignore"}

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return v if v in ("high", "medium", "low") else "medium"


class TableIR(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ------------------------------------------------------------------------ Word

class SubSection(BaseModel):
    heading: str = ""
    bullets: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class WordSection(BaseModel):
    heading: str                              # 一级标题
    lead: str | None = None                   # 章节导语,可空
    bullets: list[str] = Field(default_factory=list)
    subsections: list[SubSection] | None = None
    table: TableIR | None = None

    model_config = {"extra": "ignore"}


class WordDocIR(BaseModel):
    title: str
    subtitle: str = ""
    date_hint: str | None = None
    summary_block: list[str] = Field(default_factory=list)   # 执行摘要,≤8 条
    sections: list[WordSection] = Field(default_factory=list)  # ≤7 节
    references: list[Reference] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ------------------------------------------------------------------------- PPT

class StatItem(BaseModel):
    value: str                               # 如 "10~15万"
    label: str                               # 如 "预算"

    model_config = {"extra": "ignore"}


class SlideIR(BaseModel):
    kind: Literal["cover", "agenda", "section", "content", "stats", "table", "closing"]
    title: str = ""                          # ≤16 字
    bullets: list[str] = Field(default_factory=list)   # content 页 ≤5 条,每条 ≤20 字
    stats: list[StatItem] | None = None      # stats 页 ≤4 个
    table: TableIR | None = None             # table 页 ≤6 列 × 8 行

    model_config = {"extra": "ignore"}


class PptDocIR(BaseModel):
    title: str
    slides: list[SlideIR] = Field(default_factory=list)   # 9~13 页
    references: list[Reference] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ----------------------------------------------------------------------- Excel

class SheetIR(BaseModel):
    name: str                                # ≤12 字
    title_row: str = ""                      # 表内大标题
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    col_widths: list[int] | None = None
    kind: Literal["list", "budget", "notes"] = "list"

    model_config = {"extra": "ignore"}


class ExcelDocIR(BaseModel):
    workbook_title: str
    sheets: list[SheetIR] = Field(default_factory=list)   # 3 张
    references: list[Reference] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ------------------------------------------------------------------------- PDF

class RequirementItemIR(BaseModel):
    id: str                                  # FR-01
    text: str
    acceptance: str = ""

    model_config = {"extra": "ignore"}


class PdfSectionIR(BaseModel):
    heading: str                             # 编号条款标题,如 "2. 功能需求说明"
    paragraphs: list[str] = Field(default_factory=list)    # 条款正文,每条 ≤80 字
    requirement_items: list[RequirementItemIR] | None = None
    table: TableIR | None = None

    model_config = {"extra": "ignore"}


class PdfDocIR(BaseModel):
    title: str
    doc_no: str = ""
    version: str = "V1.0"
    date: str = ""
    sections: list[PdfSectionIR] = Field(default_factory=list)   # ≤8 节
    references: list[Reference] = Field(default_factory=list)

    model_config = {"extra": "ignore"}
