"""结构化需求文档(RequirementDoc)、会话(Session)等核心数据模型。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.intermediates import Reference

FieldState = Literal["confirmed", "assumed", "missing"]

ANALYSIS_METHOD = "5W2H + 功能/非功能需求 + 约束 + 预算 + 周期 + 优先级 + 风险"

# 文档中所有列表类型的字段键(递归清理用)
_LIST_KEYS = {
    "acceptance_criteria", "goals", "in", "out", "included", "excluded",
    "technical", "regulatory", "organizational", "other", "milestones",
    "must_have", "nice_to_have", "phase2", "risks", "assumptions",
    "open_questions", "references",
}


def _fix_list_fields(node) -> None:
    """递归修复列表字段(LLM 常见输出习惯):
    空字符串 → 空列表;非空字符串 → 单元素列表。"""
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key in _LIST_KEYS and isinstance(value, str):
                node[key] = [value] if value.strip() else []
            else:
                _fix_list_fields(value)
    elif isinstance(node, list):
        for item in node:
            _fix_list_fields(item)


def no_erasure_merge(old: dict, new: dict) -> dict:
    """代码级兜底:LLM 的合并结果与旧文档做非降级合并。

    规则:LLM 可以新增、修改、扩展,但**永远不能清空已有内容**——
    被清空的字符串/列表回退为旧值;带 id 的对象列表按 id 逐项合并。
    防止 LLM 在"未提及字段原样保留"上犯错导致已有信息丢失。
    """
    out = dict(new)
    for key, old_value in old.items():
        if key not in out:
            out[key] = old_value
        else:
            out[key] = _merge_value(old_value, out[key])
    return out


def _merge_value(old_value, new_value):
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        return no_erasure_merge(old_value, new_value)
    if isinstance(old_value, list):
        if not isinstance(new_value, list) or not new_value:
            return old_value
        if old_value and isinstance(old_value[0], dict) and "id" in old_value[0]:
            new_map = {item.get("id"): item for item in new_value
                       if isinstance(item, dict) and item.get("id")}
            merged = []
            for item in old_value:
                if isinstance(item, dict) and item.get("id") in new_map:
                    merged.append(no_erasure_merge(item, new_map.pop(item["id"])))
                else:
                    merged.append(item)
            merged.extend(new_map.values())
            return merged
        return new_value
    if isinstance(new_value, str) and not new_value.strip():
        return old_value
    if new_value in (None, "") and old_value not in (None, "", [], {}):
        return old_value
    return new_value


# ---------------------------------------------------------------- RequirementDoc

class Scope(BaseModel):
    """项目范围。JSON 中键名为 in/out(alias)。"""
    included: list[str] = Field(default_factory=list, alias="in")
    excluded: list[str] = Field(default_factory=list, alias="out")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class Project(BaseModel):
    title: str | None = None
    background: str | None = None          # Why:为什么做这件事
    goals: list[str] = Field(default_factory=list)   # 2~5 条,尽量可量化
    scope: Scope = Field(default_factory=Scope)

    model_config = {"extra": "ignore"}

    @field_validator("title", mode="before")
    @classmethod
    def _v_title(cls, v):
        """清理 LLM 拟的标题:去括号说明、去'需求分析'等尾巴、截 16 字;
        占位词('待补充/待定'等)与过短标题一律视为空。"""
        if not isinstance(v, str):
            return v
        t = re.sub(r"[（(].*?[)）]", "", v).strip()
        t = re.sub(r"(需求分析|分析报告|解决方案|建议书|项目方案|项目).*$", "", t).strip()
        t = t[:16]
        if not t or len(t) < 4 or t.lower() in {"tbd", "none", "null", "暂无", "待定"} \
                or "待补充" in t or "待确认" in t or t in {"未命名", "未定", "无"}:
            return None
        return t


class Customer(BaseModel):
    name: str | None = None
    organization: str | None = None
    role: str | None = None

    model_config = {"extra": "ignore"}


class Stakeholders(BaseModel):
    customer: Customer = Field(default_factory=Customer)
    end_users: str | None = None           # 最终使用者及规模
    decision_makers: str | None = None     # 拍板人

    model_config = {"extra": "ignore"}


class FunctionalRequirement(BaseModel):
    id: str                                  # FR-01
    module: str = ""                         # 所属模块
    description: str                         # 一句话描述,动词开头
    priority: Literal["高", "中", "低"] = "中"
    acceptance_criteria: list[str] = Field(default_factory=list)  # 1~3 条可验收标准

    model_config = {"extra": "ignore"}

    @field_validator("priority", mode="before")
    @classmethod
    def _v_priority(cls, v):
        """LLM 常把枚举输出成空串或非预期词,降级为默认值。"""
        return v if v in ("高", "中", "低") else "中"


class NonFunctionalRequirements(BaseModel):
    performance: str | None = None          # 并发/响应时间/数据量
    security: str | None = None             # 权限/加密/合规
    reliability: str | None = None          # 可用性/容灾
    usability: str | None = None
    compatibility: str | None = None        # 设备/浏览器/系统
    scalability: str | None = None

    model_config = {"extra": "ignore"}


class Constraints(BaseModel):
    technical: list[str] = Field(default_factory=list)
    regulatory: list[str] = Field(default_factory=list)
    organizational: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class Budget(BaseModel):
    amount: str | None = None               # 区间表述,如 "10~15万"
    currency: str = "人民币"
    notes: str | None = None

    model_config = {"extra": "ignore"}


class Milestone(BaseModel):
    name: str
    date: str | None = None
    deliverable: str | None = None

    model_config = {"extra": "ignore"}


class Timeline(BaseModel):
    expected_start: str | None = None       # YYYY-MM 或 "未定"
    expected_delivery: str | None = None
    urgency: Literal["高", "中", "低"] | None = None
    milestones: list[Milestone] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @field_validator("urgency", mode="before")
    @classmethod
    def _v_urgency(cls, v):
        """空串/非法值 → None(可选字段)。"""
        return v if v in ("高", "中", "低") else None


class PriorityAnalysis(BaseModel):
    """定稿时由 LLM 分析推导,不向客户提问。"""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    phase2: list[str] = Field(default_factory=list)   # 二期建议

    model_config = {"extra": "ignore"}


class Risk(BaseModel):
    id: str                                  # R-01
    description: str
    likelihood: Literal["高", "中", "低"] = "中"
    impact: Literal["高", "中", "低"] = "中"
    mitigation: str = ""

    model_config = {"extra": "ignore"}

    @field_validator("likelihood", "impact", mode="before")
    @classmethod
    def _v_level(cls, v):
        return v if v in ("高", "中", "低") else "中"


class OpenQuestion(BaseModel):
    question: str
    impact: Literal["high", "medium", "low"] = "medium"
    note: str = ""                           # 当前采用的处理方式(假设/暂缓)

    model_config = {"extra": "ignore"}

    @field_validator("impact", mode="before")
    @classmethod
    def _v_impact(cls, v):
        return v if v in ("high", "medium", "low") else "medium"


class Meta(BaseModel):
    analysis_method: str = ANALYSIS_METHOD
    version: int = 1
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    research_note: str = ""                  # 调研方法与检索日期

    model_config = {"extra": "ignore"}


class RequirementDoc(BaseModel):
    project: Project = Field(default_factory=Project)
    stakeholders: Stakeholders = Field(default_factory=Stakeholders)
    functional_requirements: list[FunctionalRequirement] = Field(default_factory=list)
    non_functional_requirements: NonFunctionalRequirements = Field(default_factory=NonFunctionalRequirements)
    constraints: Constraints = Field(default_factory=Constraints)
    budget: Budget = Field(default_factory=Budget)
    timeline: Timeline = Field(default_factory=Timeline)
    priority_analysis: PriorityAnalysis = Field(default_factory=PriorityAnalysis)
    risks: list[Risk] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        """容错:LLM 常见结构错误 → 合法结构。

        - 列表字段输出为 "" → 空列表(递归)
        - functional_requirements 纯字符串条目 → 结构化对象(自动补 id 编号)
        - 列表字段误输出为单字符串 → 单元素列表
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        _fix_list_fields(data)

        frs = data.get("functional_requirements")
        if isinstance(frs, list):
            cleaned = [dict(fr) if isinstance(fr, dict) else
                       ({"description": fr.strip()} if isinstance(fr, str) and fr.strip() else None)
                       for fr in frs]
            cleaned = [fr for fr in cleaned if fr is not None]
            next_no = 1
            for fr in cleaned:
                m = re.match(r"FR-(\d+)", str(fr.get("id") or ""))
                if m:
                    next_no = max(next_no, int(m.group(1)) + 1)
            for fr in cleaned:
                if not fr.get("id"):
                    fr["id"] = f"FR-{next_no:02d}"
                    next_no += 1
            data["functional_requirements"] = cleaned

        for key in ("assumptions",):
            value = data.get(key)
            if isinstance(value, str):
                data[key] = [value] if value.strip() else []

        project = data.get("project")
        if isinstance(project, dict):
            goals = project.get("goals")
            if isinstance(goals, str):
                project["goals"] = [goals] if goals.strip() else []

        timeline = data.get("timeline")
        if isinstance(timeline, dict):
            ms = timeline.get("milestones")
            if isinstance(ms, list):
                timeline["milestones"] = [
                    {"name": m.strip()} if isinstance(m, str) and m.strip() else m
                    for m in ms
                    if isinstance(m, (str, dict))
                ]

        risks = data.get("risks")
        if isinstance(risks, list):
            cleaned = []
            for r in risks:
                if isinstance(r, str) and r.strip():
                    r = {"description": r.strip()}
                if isinstance(r, dict):
                    r = dict(r)
                    if not r.get("id"):
                        r["id"] = f"R-{len(cleaned) + 1:02d}"
                    cleaned.append(r)
            data["risks"] = cleaned

        oqs = data.get("open_questions")
        if isinstance(oqs, list):
            data["open_questions"] = [
                {"question": q.strip()} if isinstance(q, str) and q.strip() else q
                for q in oqs
                if isinstance(q, (str, dict))
            ]
        return data

    def short_title(self) -> str:
        return (self.project.title or "未命名项目").strip()[:30] or "未命名项目"


class AnalysisState(BaseModel):
    """部分需求文档 + 字段状态(澄清循环的驱动数据)。"""
    requirement: RequirementDoc = Field(default_factory=RequirementDoc)
    field_states: dict[str, FieldState] = Field(default_factory=dict)


# --------------------------------------------------------------------- Session

class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    kind: Literal["text", "questions", "requirement_card", "file_card", "file_choice",
                  "task_file", "system"] = "text"
    payload: dict | None = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    model_config = {"extra": "ignore"}


class FileRecord(BaseModel):
    file_type: Literal["word", "ppt", "excel", "pdf"]
    filename: str
    size_bytes: int = 0
    version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    model_config = {"extra": "ignore"}


class Session(BaseModel):
    session_id: str
    title: str
    phase: Literal["clarify", "research", "confirm", "choose", "task", "done"] = "clarify"
    state: AnalysisState | None = None
    research_brief: dict | None = None       # 调研简报:key_findings/data_points/gaps
    messages: list[Message] = Field(default_factory=list)
    files: dict[str, FileRecord] = Field(default_factory=dict)
    requested_files: list[str] = Field(default_factory=list)  # 客户选择要导出的文件类型
    task: dict | None = None                 # 通用任务上下文 {type, params, questions, ask_count}
    task_files: list[FileRecord] = Field(default_factory=list)  # 通用任务生成的交付文件
    api_key: str | None = None               # 使用者的 DeepSeek Key(仅内存,不落盘)
    outstanding_questions: list[dict] = Field(default_factory=list)
    asked_fields: dict[str, int] = Field(default_factory=dict)
    questions_total: int = 0
    rounds: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    model_config = {"extra": "ignore"}
