"""定稿:基于澄清结果与调研简报,生成数据支撑的完整需求文档 + 要点摘要。"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from app.llm.client import LLMError, json_call
from app.llm.prompts import FINALIZE_PROMPT, JSON_RULES, fill
from app.models.intermediates import Reference
from app.models.schemas import AnalysisState, RequirementDoc, no_erasure_merge

logger = logging.getLogger(__name__)


def finalize_requirement(state: AnalysisState, research_brief: dict,
                        api_key: str | None = None) -> tuple[str, RequirementDoc]:
    """返回 (summary_text, 定稿需求文档)。

    references 由代码强制写入调研简报中的数据点,LLM 无法新增或篡改来源;
    version/updated_at 也由代码维护。
    """
    user = fill(
        FINALIZE_PROMPT,
        DOC=json.dumps(state.requirement.model_dump(by_alias=True), ensure_ascii=False),
        FIELD_STATES=json.dumps(state.field_states, ensure_ascii=False),
        RESEARCH=json.dumps(research_brief or {}, ensure_ascii=False),
        JSON_RULES=JSON_RULES,
    )
    try:
        result = json_call("", user, max_tokens=8192, api_key=api_key)
    except LLMError:
        raise

    # 代码级兜底:定稿同样不得清空客户已确认的内容
    req_dict = no_erasure_merge(
        state.requirement.model_dump(by_alias=True),
        result.get("requirement") or {},
    )
    doc = RequirementDoc.model_validate(req_dict)

    # 代码强制:引用只能来自调研简报(防 LLM 编造来源)
    brief_points = (research_brief or {}).get("data_points") or []
    doc.references = [Reference(**dp) for dp in brief_points]

    # 代码强制:版本与时间戳
    doc.meta.version = (state.requirement.meta.version or 0) + 1
    doc.meta.updated_at = datetime.now().isoformat(timespec="seconds")
    if not doc.meta.research_note and brief_points:
        doc.meta.research_note = (
            f"公开资料检索(检索日期 {datetime.now():%Y-%m-%d}),"
            f"共引用已公布数据 {len(brief_points)} 条,详见文末参考数据与来源。"
        )
    elif not brief_points:
        doc.meta.research_note = "本次未能获取到可引用的公开数据,定量论断均为估算或假设。"

    return (result.get("summary_text") or "").strip(), doc
