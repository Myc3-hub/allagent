"""澄清优先级规则(纯代码,确定性):判断哪些字段缺失、还需要问什么。

缺失判定与提问节奏全部由代码决定;LLM 只负责把目标字段翻译成口语化问题。
"""
from __future__ import annotations

from app.config import settings
from app.models.schemas import RequirementDoc

# P0:必须向客户问清;P1:应问(受提问预算约束);P2:不问,定稿时写假设
P0_FIELDS = [
    "project.background",
    "project.goals",
    "functional_requirements",
    "budget.amount",
    "timeline.expected_delivery",
]
P1_FIELDS = [
    "project.scope",
    "stakeholders.end_users",
    "non_functional_requirements.performance",
    "non_functional_requirements.security",
    "constraints.technical",
    "constraints.regulatory",
]

FIELD_LABELS = {
    "project.background": "项目背景",
    "project.goals": "项目目标",
    "functional_requirements": "功能需求",
    "budget.amount": "预算",
    "timeline.expected_delivery": "期望交付时间",
    "project.scope": "项目范围",
    "stakeholders.end_users": "使用人群",
    "non_functional_requirements.performance": "性能要求",
    "non_functional_requirements.security": "安全要求",
    "constraints.technical": "技术约束",
    "constraints.regulatory": "合规要求",
}


def _value_at(req: RequirementDoc, path: str):
    """按点路径取字段值。"""
    obj = req
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _is_filled(req: RequirementDoc, path: str) -> bool:
    value = _value_at(req, path)
    if value is None:
        return False
    if isinstance(value, list):
        # scope 结构特殊:in/out 任一非空视为已说明范围
        if path == "project.scope":
            return bool(getattr(value, "included", None) or getattr(value, "excluded", None))
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    return True


def get_missing_fields(req: RequirementDoc, field_states: dict, asked_fields: dict) -> list[str]:
    """返回仍可追问的缺失字段路径,按 P0→P1 顺序。

    规则:已 confirmed 的不问;已问过 2 次仍未答的转为定稿假设,不再追问。
    """
    missing = []
    for path in P0_FIELDS + P1_FIELDS:
        if field_states.get(path) == "confirmed":
            continue
        if asked_fields.get(path, 0) >= settings.ask_twice_then_assume:
            continue
        if not _is_filled(req, path):
            missing.append(path)
    return missing


def pick_targets(req: RequirementDoc, field_states: dict, asked_fields: dict,
                 first_round: bool = True) -> list[str]:
    """本轮提问的目标字段:单轮模式,最多 3 个(按 P0→P1 优先级)。"""
    missing = get_missing_fields(req, field_states, asked_fields)
    return missing[:3]


def should_finalize(req: RequirementDoc, field_states: dict, asked_fields: dict,
                    rounds: int, questions_total: int) -> bool:
    """澄清是否结束:已提问过一轮(rounds > 上限),或缺失清零,或提问数达上限。

    单轮模式:首条消息提取后提问一次(rounds=1),客户回答后(rounds=2)直接定稿,
    未答字段由定稿阶段写入假设。
    """
    if rounds > settings.max_clarify_rounds:
        return True
    if questions_total >= settings.max_questions_total:
        return True
    return not get_missing_fields(req, field_states, asked_fields)


def mark_confirmed(field_states: dict, updated_fields: list[str]) -> dict:
    """LLM 返回 updated_fields 列表后,由代码置 confirmed(LLM 不得直接写状态)。

    只接受已知字段路径,忽略 LLM 编造出的路径。
    """
    for path in updated_fields or []:
        if path in FIELD_LABELS:
            field_states[path] = "confirmed"
    return field_states


def bump_asked(asked_fields: dict, targets: list[str], updated_fields: list[str]) -> dict:
    """本轮未被回答的目标字段,提问次数 +1。"""
    answered = set(updated_fields or [])
    for path in targets:
        if path not in answered:
            asked_fields[path] = asked_fields.get(path, 0) + 1
    return asked_fields
