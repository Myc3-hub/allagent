"""会话状态机主循环:clarify → research → confirm → done。

单一入口 handle_message:处理客户消息,产出 SSE 事件流。
事件协议:(meta)→ (text)×N → (questions|research×N|requirement) → done / error
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncIterator

from app.agent import clarify
from app.agent.finalize import finalize_requirement
from app.config import settings
from app.llm.client import LLMError, chat_stream, json_call
from app.llm.prompts import (
    EMPTY_DOC_SKELETON,
    EXTRACT_PROMPT,
    JSON_RULES,
    KNOWN_PATHS,
    MERGE_PROMPT,
    NEXT_QUESTIONS_PROMPT,
    SYSTEM_PROMPT,
    TASK_CLASSIFY_PROMPT,
    TASK_MERGE_PROMPT,
    TASK_QUESTIONS_PROMPT,
    fill,
)
from app.models.schemas import (
    AnalysisState, FileRecord, Message, Project, RequirementDoc, Session,
    no_erasure_merge,
)
from app.research.researcher import run_research
from app.utils.text import safe_filename

logger = logging.getLogger(__name__)

Event = tuple[str, dict]

# 确认阶段的确认词
CONFIRM_WORDS = {"确认", "确认无误", "没问题", "可以", "好的", "ok", "OK"}

# 文件类型关键词(客户回复解析,确定性代码匹配)
_FILE_KEYWORDS = {
    "word": ("word", "报告"),
    "ppt": ("ppt", "演示", "幻灯片"),
    "excel": ("excel", "表格", "清单"),
    "pdf": ("pdf",),
}
_ALL_FILES_WORDS = ("全部", "都要", "都行", "都生成", "四个", "所有", "每样")


def _parse_file_choices(text: str) -> list[str]:
    """从客户回复中解析要导出的文件类型;返回空列表表示未识别。"""
    t = text.lower()
    if any(w in t for w in _ALL_FILES_WORDS):
        return ["word", "ppt", "excel", "pdf"]
    chosen = []
    for ftype, keywords in _FILE_KEYWORDS.items():
        if ftype not in chosen and any(k in t for k in keywords):
            chosen.append(ftype)
    return chosen


def _chunks(text: str, size: int = 3) -> list[str]:
    """把固定文本切成小段,模拟流式输出。"""
    return [text[i:i + size] for i in range(0, len(text), size)]


def _doc_json(doc: RequirementDoc) -> str:
    return json.dumps(doc.model_dump(by_alias=True), ensure_ascii=False)


def _recent_history(session: Session, n: int = 6) -> str:
    lines = []
    for msg in session.messages[-n:]:
        if msg.kind not in ("text", "questions"):
            continue
        who = "客户" if msg.role == "user" else "分析师"
        lines.append(f"{who}: {msg.content[:100]}")
    return "\n".join(lines)


async def handle_message(session: Session, text: str, kind: str = "message") -> AsyncIterator[Event]:
    """处理一条客户消息,产出 SSE 事件流。"""
    try:
        yield ("meta", {"phase": session.phase})

        # ---------- done:任务分类 → 执行任务或自由问答 ----------
        if session.phase == "done":
            classified = await asyncio.to_thread(_classify_task, session, text)
            if classified:
                async for ev in _task_start(session, classified):
                    yield ev
                yield ("done", {})
                return
            async for ev in _free_chat(session, text):
                yield ev
            yield ("done", {})
            return

        # ---------- task:任务执行中(回答补充提问) ----------
        if session.phase == "task":
            async for ev in _task_continue(session, text):
                yield ev
            yield ("done", {})
            return

        # ---------- confirm:确认词 → 询问导出文件;其余 → 修改意见 ----------
        if session.phase == "confirm":
            if kind == "message" and text.strip() in CONFIRM_WORDS:
                session.phase = "choose"
                msg = ("需求已确认。请问需要导出为哪些文件?可选:Word 报告 / PPT 演示 / "
                       "Excel 表格 / PDF 文档,回复名称即可(可多选),或回复“全部”。")
                for chunk in _chunks(msg):
                    yield ("text", {"delta": chunk})
                session.messages.append(
                    Message(role="assistant", content=msg, kind="file_choice",
                            payload={"options": ["word", "ppt", "excel", "pdf"]}))
                yield ("done", {})
                return
            async for ev in _revise(session, text):
                yield ev
            yield ("done", {})
            return

        # ---------- choose:解析客户选择的文件类型 → done ----------
        if session.phase == "choose":
            if kind == "message" and ("修改" in text or "调整" in text or "改一下" in text):
                session.phase = "confirm"
                async for ev in _revise(session, text):
                    yield ev
                yield ("done", {})
                return
            async for ev in _choose_files(session, text):
                yield ev
            yield ("done", {})
            return

        # ---------- clarify:首条消息先判任务,再走需求分析 ----------
        if session.state is None:
            classified = await asyncio.to_thread(_classify_task, session, text)
            if classified:
                async for ev in _task_start(session, classified):
                    yield ev
                yield ("done", {})
                return
            session.state = await asyncio.to_thread(_extract, text, session.api_key)
        else:
            await asyncio.to_thread(_merge_answer, session, text)

        req = session.state.requirement
        session.rounds += 1
        if clarify.should_finalize(req, session.state.field_states,
                                   session.asked_fields, session.rounds,
                                   session.questions_total):
            async for ev in _research_and_finalize(session):
                yield ev
            yield ("done", {})
            return

        # 生成下一轮提问
        targets = clarify.pick_targets(req, session.state.field_states,
                                       session.asked_fields,
                                       first_round=(session.rounds == 1))
        if not targets:  # 兜底:无目标字段则直接定稿
            async for ev in _research_and_finalize(session):
                yield ev
            yield ("done", {})
            return

        targets_desc = "\n".join(
            f"{i + 1}. {clarify.FIELD_LABELS[t]}({t})" for i, t in enumerate(targets)
        )
        qresult = json_call(
            "",
            fill(NEXT_QUESTIONS_PROMPT, TARGETS=targets_desc,
                 HISTORY=_recent_history(session), JSON_RULES=JSON_RULES),
            max_tokens=1024, api_key=session.api_key,
        )
        questions = qresult.get("questions") or []
        if not questions:  # 兜底:LLM 未产出问题 → 定稿
            async for ev in _research_and_finalize(session):
                yield ev
            yield ("done", {})
            return

        session.outstanding_questions = questions
        session.questions_total += len(questions)

        intro = "好的,为了把需求分析得更准确,我再向您确认几个问题:"
        for chunk in _chunks(intro):
            yield ("text", {"delta": chunk})
        session.messages.append(Message(role="assistant", content=intro, kind="text"))
        payload = {"questions": questions}
        session.messages.append(
            Message(role="assistant", content=json.dumps(questions, ensure_ascii=False),
                    kind="questions", payload=payload))
        yield ("questions", payload)
        yield ("done", {})
    except LLMError as exc:
        yield ("error", {"message": str(exc)})
    except Exception as exc:  # 兜底:不让事件流无声中断
        logger.exception("handle_message 异常")
        yield ("error", {"message": f"服务暂时不可用,请稍后重试({type(exc).__name__})"})


# --------------------------------------------------------------------- 内部步骤

def _extract(text: str, api_key: str | None = None) -> AnalysisState:
    result = json_call(
        "",
        fill(EXTRACT_PROMPT, SKELETON=EMPTY_DOC_SKELETON,
             KNOWN_PATHS=", ".join(KNOWN_PATHS), JSON_RULES=JSON_RULES),
        max_tokens=4096, api_key=api_key,
    )
    doc = RequirementDoc.model_validate(result.get("requirement") or {})
    state = AnalysisState(requirement=doc, field_states={})
    clarify.mark_confirmed(state.field_states, result.get("updated_fields") or [])
    return state


def _merge_answer(session: Session, text: str) -> None:
    merged = json_call(
        "",
        fill(MERGE_PROMPT,
             DOC=_doc_json(session.state.requirement),
             QUESTIONS=json.dumps(session.outstanding_questions or [], ensure_ascii=False),
             ANSWER=text,
             KNOWN_PATHS=", ".join(KNOWN_PATHS),
             JSON_RULES=JSON_RULES),
        max_tokens=8192, api_key=session.api_key,
    )
    # 代码级兜底:LLM 不得清空已有内容
    safe = no_erasure_merge(
        session.state.requirement.model_dump(by_alias=True),
        merged.get("requirement") or {},
    )
    session.state.requirement = RequirementDoc.model_validate(safe)
    updated = merged.get("updated_fields") or []
    clarify.mark_confirmed(session.state.field_states, updated)
    targets = [f for q in (session.outstanding_questions or []) for f in q.get("fields", [])]
    clarify.bump_asked(session.asked_fields, targets, updated)
    session.outstanding_questions = []


async def _research_stream(session: Session, requirement: RequirementDoc,
                           brief_holder: dict) -> AsyncIterator[Event]:
    """调研在线程中执行,进度经线程安全队列推送为 SSE research 事件;
    结果写入 brief_holder["brief"]。"""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def cb(status: str, payload: dict) -> None:
        loop.call_soon_threadsafe(q.put_nowait, (status, payload))

    task = asyncio.create_task(asyncio.to_thread(run_research, requirement, cb, session.api_key))
    while not task.done():
        try:
            status, payload = await asyncio.wait_for(q.get(), timeout=0.5)
            yield ("research", {"status": status, **payload})
        except asyncio.TimeoutError:
            continue
    brief_holder["brief"] = task.result()


async def _research_and_finalize(session: Session) -> AsyncIterator[Event]:
    intro = "需求已基本清晰,正在检索已公布的同类数据,以支撑分析…"
    for chunk in _chunks(intro):
        yield ("text", {"delta": chunk})
    session.messages.append(Message(role="assistant", content=intro, kind="text"))
    session.phase = "research"

    holder: dict = {}
    async for ev in _research_stream(session, session.state.requirement, holder):
        yield ev
    brief = holder.get("brief") or {}
    session.research_brief = brief

    summary, doc = await asyncio.to_thread(finalize_requirement, session.state, brief, session.api_key)
    session.state.requirement = doc
    session.phase = "confirm"

    card = {
        "requirement": doc.model_dump(by_alias=True),
        "summary_text": summary,
        "version": doc.meta.version,
        "references": [r.model_dump() for r in doc.references],
        "gaps": brief.get("gaps") or [],
    }
    session.messages.append(
        Message(role="assistant", content=summary, kind="requirement_card", payload=card))
    yield ("requirement", card)


async def _choose_files(session: Session, text: str) -> AsyncIterator[Event]:
    """解析客户选择的导出文件类型,成功则进入 done 阶段。"""
    from app.files.registry import FILE_TYPES

    chosen = _parse_file_choices(text)
    if not chosen:
        msg = ("没有识别到文件类型,请回复:Word 报告、PPT 演示、Excel 表格、PDF 文档"
               "(可多选),或回复“全部”。")
        for chunk in _chunks(msg):
            yield ("text", {"delta": chunk})
        session.messages.append(Message(role="assistant", content=msg, kind="text"))
        return
    session.requested_files = chosen
    session.phase = "done"
    labels = "、".join(FILE_TYPES[ft]["label"] for ft in chosen)
    msg = (f"好的,请点击下方按钮生成:{labels}。"
           "另外,我还能帮您生成各类实用文件,直接告诉我要做什么即可。")
    for chunk in _chunks(msg):
        yield ("text", {"delta": chunk})
    session.messages.append(Message(role="assistant", content=msg, kind="text"))


async def _revise(session: Session, comment: str) -> AsyncIterator[Event]:
    merged = json_call(
        "",
        fill(MERGE_PROMPT,
             DOC=_doc_json(session.state.requirement),
             QUESTIONS=json.dumps([{"text": "客户修改意见(可能涉及文档任意内容)"}],
                                  ensure_ascii=False),
             ANSWER=comment,
             KNOWN_PATHS=", ".join(KNOWN_PATHS),
             JSON_RULES=JSON_RULES),
        max_tokens=8192, api_key=session.api_key,
    )
    safe = no_erasure_merge(
        session.state.requirement.model_dump(by_alias=True),
        merged.get("requirement") or {},
    )
    session.state.requirement = RequirementDoc.model_validate(safe)
    updated = merged.get("updated_fields") or []
    clarify.mark_confirmed(session.state.field_states, updated)

    summary, doc = await asyncio.to_thread(
        finalize_requirement, session.state, session.research_brief or {}, session.api_key)
    session.state.requirement = doc
    session.phase = "confirm"

    card = {
        "requirement": doc.model_dump(by_alias=True),
        "summary_text": summary,
        "version": doc.meta.version,
        "references": [r.model_dump() for r in doc.references],
        "gaps": (session.research_brief or {}).get("gaps") or [],
    }
    session.messages.append(
        Message(role="assistant", content=summary, kind="requirement_card", payload=card))
    yield ("requirement", card)


# ------------------------------------------------------------------- 通用任务引擎

def _classify_task(session: Session, text: str) -> dict | None:
    """判断客户消息是否为内容创作任务;是则返回 {type, params}。

    仅识别明确的"写/生成/制作"类请求;LLM 失败返回 None(降级为普通流程)。
    """
    from app.tasks import TASK_TYPES

    try:
        result = json_call(
            "", fill(TASK_CLASSIFY_PROMPT, TEXT=text, JSON_RULES=JSON_RULES),
            max_tokens=1024, api_key=session.api_key,
        )
    except LLMError:
        return None
    task_name = (result or {}).get("task")
    if task_name not in TASK_TYPES:
        return None
    return {"type": task_name, "params": result.get("params") or {}}


async def _task_start(session: Session, classified: dict) -> AsyncIterator[Event]:
    """开始一个通用任务:主题缺失时先补一轮提问,否则直接生成。"""
    task = {
        "type": classified["type"],
        "params": classified.get("params") or {},
        "ask_count": 0,
    }
    session.task = task
    session.phase = "task"
    topic = (task["params"].get("topic") or "").strip()
    if not topic:
        async for ev in _task_ask_params(session, task):
            yield ev
        return
    async for ev in _task_generate(session):
        yield ev


async def _task_ask_params(session: Session, task: dict) -> AsyncIterator[Event]:
    """生成最多 2 个补充提问(优先主题)。"""
    from app.tasks import TASK_TYPES

    entry = TASK_TYPES[task["type"]]
    try:
        qresult = json_call(
            "", fill(TASK_QUESTIONS_PROMPT,
                     ACTION=entry["action"],
                     PARAMS=json.dumps(task.get("params") or {}, ensure_ascii=False),
                     JSON_RULES=JSON_RULES),
            max_tokens=1024, api_key=session.api_key,
        )
        questions = qresult.get("questions") or []
    except LLMError:
        questions = []
    if not questions:
        questions = [{"text": "请问内容主题是什么?(如:关于数字化转型的年会发言)",
                      "purpose": "了解主题"}]
    task["questions"] = questions
    session.task = task
    intro = f"好的!我先确认几个要点,让{entry['label']}更贴合您的需要:"
    for chunk in _chunks(intro):
        yield ("text", {"delta": chunk})
    session.messages.append(Message(role="assistant", content=intro, kind="text"))
    payload = {"questions": questions}
    session.messages.append(
        Message(role="assistant", content=json.dumps(questions, ensure_ascii=False),
                kind="questions", payload=payload))
    yield ("questions", payload)


async def _task_continue(session: Session, text: str) -> AsyncIterator[Event]:
    """任务补充提问的回答:合并参数后继续生成。"""
    task = session.task or {"type": "speech", "params": {}, "ask_count": 0}
    if task.get("questions"):
        try:
            merged = json_call(
                "", fill(TASK_MERGE_PROMPT,
                         PARAMS=json.dumps(task.get("params") or {}, ensure_ascii=False),
                         QUESTIONS=json.dumps(task.get("questions") or [], ensure_ascii=False),
                         ANSWER=text, JSON_RULES=JSON_RULES),
                max_tokens=2048, api_key=session.api_key,
            )
            task["params"] = {**(task.get("params") or {}), **(merged.get("params") or {})}
        except LLMError:
            pass
    session.task = task
    async for ev in _task_generate(session):
        yield ev


async def _task_generate(session: Session) -> AsyncIterator[Event]:
    """执行任务:可选调研 → LLM 生成 IR → 渲染文件 → task_file 事件。"""
    from app.tasks import TASK_TYPES

    task = session.task
    entry = TASK_TYPES[task["type"]]
    params = task.get("params") or {}
    topic = (params.get("topic") or "").strip()
    if not topic:
        task["ask_count"] = task.get("ask_count", 0) + 1
        if task["ask_count"] < 2:
            session.task = task
            async for ev in _task_ask_params(session, task):
                yield ev
            return
        msg = ("抱歉,还没有收到主题,本次任务先到这里。您可以重新提出,"
               "例如:帮我写一篇关于团队建设的中秋活动通知。")
        for chunk in _chunks(msg):
            yield ("text", {"delta": chunk})
        session.messages.append(Message(role="assistant", content=msg, kind="text"))
        session.phase = "done"
        session.task = None
        return

    # 可选:公开数据调研(报告/PPT 类任务)
    brief: dict = {}
    if entry.get("research"):
        holder: dict = {}
        async for ev in _research_stream(session, _task_requirement(params), holder):
            yield ev
        brief = holder.get("brief") or {}

    # 生成 IR
    writing = f"正在为您撰写《{topic}》{entry['label']},请稍候…"
    for chunk in _chunks(writing):
        yield ("text", {"delta": chunk})
    session.messages.append(Message(role="assistant", content=writing, kind="text"))

    user = fill(
        entry["prompt"],
        PARAMS=json.dumps(params, ensure_ascii=False),
        REFERENCES=json.dumps(brief.get("data_points") or [], ensure_ascii=False),
    )
    ir = await asyncio.to_thread(json_call, "", user, max_tokens=8192, schema=entry["ir"], api_key=session.api_key)

    # 日期字段由代码强制为今天(LLM 常填错)
    if hasattr(ir, "date_hint"):
        ir.date_hint = datetime.now().strftime("%Y年%m月%d日")

    # 渲染并记录(标签同样需要清洗:如"通知/公告"含路径分隔符)
    n = len(session.task_files) + 1
    filename = f"{safe_filename(topic[:24])}_{safe_filename(entry['label'])}_v{n}{entry['ext']}"
    out_dir = settings.output_dir / session.session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    await asyncio.to_thread(entry["render"], ir, out_path)

    record = FileRecord(file_type=entry["file_type"], filename=filename,
                        size_bytes=out_path.stat().st_size, version=n)
    session.task_files.append(record)
    session.phase = "done"
    session.task = None

    msg = (f"已为您生成《{topic}》{entry['label']},点击下方即可下载。"
           "需要调整内容、更换风格重新生成,或继续生成其他文件,直接告诉我就行。")
    for chunk in _chunks(msg):
        yield ("text", {"delta": chunk})
    session.messages.append(Message(role="assistant", content=msg, kind="text"))
    payload = {"file": record.model_dump(), "index": n - 1}
    session.messages.append(
        Message(role="assistant", content=filename, kind="task_file", payload=payload))
    yield ("task_file", payload)


def _task_requirement(params: dict) -> RequirementDoc:
    """从任务参数构造伪需求文档,复用调研模块(主题词提取/检索/门控)。"""
    goals = [g for g in [params.get("style"), params.get("length")] if g and g.strip()]
    return RequirementDoc(
        project=Project(
            title=(params.get("topic") or "").strip(),
            background=(params.get("requirements") or params.get("occasion") or "").strip(),
            goals=goals,
        ),
    )


async def _free_chat(session: Session, text: str) -> AsyncIterator[Event]:
    # 用户消息已由 stream 端点记录,此处只取历史交给 LLM
    history = [
        {"role": m.role, "content": m.content}
        for m in session.messages[-8:]
        if m.kind in ("text", "questions") and m.role in ("user", "assistant")
    ]

    full = ""
    for delta in await asyncio.to_thread(_stream_collect, SYSTEM_PROMPT, history, session.api_key):
        full += delta
        yield ("text", {"delta": delta})
    session.messages.append(Message(role="assistant", content=full, kind="text"))


def _stream_collect(system: str, history: list[dict], api_key: str | None = None) -> list[str]:
    """在线程中收集流式输出(避免阻塞事件循环)。"""
    return list(chat_stream(system, history, api_key=api_key))
