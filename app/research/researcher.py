"""调研编排:检索词生成 → 搜索 → 权威排序抓取 → LLM 数据点提取(来源绑定)→ 简报。

铁律:数据点 URL 只能来自搜索/抓取元数据;LLM 返回的 URL 不在允许清单内一律丢弃。
任何环节失败都优雅降级,绝不虚构数据补位。
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.config import settings
from app.llm.client import LLMError, json_call
from app.llm.prompts import DATA_EXTRACT_PROMPT, JSON_RULES, QUERY_GEN_PROMPT, fill
from app.models.schemas import RequirementDoc
from app.research.fetcher import fetch_page
from app.research.search import web_search
from app.research.sources import authority_rank, source_name_for

logger = logging.getLogger(__name__)

TODAY = datetime.now().strftime("%Y-%m-%d")

EMPTY_BRIEF = {"key_findings": [], "data_points": [], "gaps": []}


# 常见修饰前缀:剥离后得到可检索的核心主题词
_LEAD_MODIFIERS = ("员工", "企业", "公司", "校园", "工厂", "学校", "医院",
                   "集团", "门店", "店铺", "商超", "连锁", "团队", "中小",
                   "小微", "大型", "数字化", "智能化", "信息化", "一体化",
                   "标准化", "新一代", "移动", "智能", "智慧", "在线", "云")
_PRODUCT_RE = re.compile(r"([一-龥A-Za-z0-9]{2,8})(系统|软件|平台|应用|小程序|工具)")


def _core_token(raw: str) -> str:
    """提取可检索的核心主题词,如"XX公司员工考勤系统" → "考勤系统"。

    搜索引擎对"员工考勤系统"常错误切词为"员工"(返回词语释义),
    核心词"考勤系统"检索效果显著更好。
    """
    t = re.sub(r"[（(].*?[)）]", "", raw or "").strip()
    t = re.sub(r"(需求分析|分析报告|解决方案|建议书|项目方案|项目).*$", "", t).strip()
    t = re.sub(r"^[一-龥A-Za-z0-9]{1,10}公司", "", t)
    # 并列结构取前项:"考勤与请假审批系统" → "考勤系统"
    if any(c in t for c in "与和及"):
        first = re.split(r"[与和及]", t, maxsplit=1)[0]
        suffix = re.search(r"(系统|软件|平台|应用|小程序|工具)$", t)
        t = first + (suffix.group(1) if suffix else "")
    # 先循环剥离修饰前缀(避免产品名正则贪婪吞字)
    t = _strip_modifiers(t)
    # 提取产品名:"……系统/软件/平台/应用/小程序/工具"
    m = _PRODUCT_RE.search(t)
    if m:
        t = m.group(1) + m.group(2)
    # 产品名可能带出 "XX集团/公司" 前缀,再去一次修饰
    t = re.sub(r"^[A-Za-z0-9]{1,6}(集团|公司|企业)", "", t)
    t = _strip_modifiers(t)
    return t[:12] if len(t) >= 3 else ""


def _strip_modifiers(t: str) -> str:
    """循环剥离修饰前缀,直到没有可剥的。

    同时处理"中小型企业"被剥成"型企业"的残留单字情况。
    """
    changed = True
    while changed and len(t) > 3:
        changed = False
        # 残留单字 + 机构词组合(如"型企业"、"和集团")
        m2 = re.match(r"^[一-龥A-Za-z0-9]{0,2}(企业|公司|集团|团队|门店|工厂|学校|医院|园区|单位)", t)
        if m2 and len(t) - len(m2.group(0)) > 2:
            t = t[len(m2.group(0)):]
            changed = True
            continue
        for mod in _LEAD_MODIFIERS:
            if t.startswith(mod) and len(t) > len(mod) + 1:
                t = t[len(mod):]
                changed = True
                break
    return t


def _topic_token(requirement: RequirementDoc) -> str:
    """从需求中提取项目核心主题词(代码确定性,防止检索跑题)。

    优先级:项目标题 → 功能模块名 → 背景/目标中的产品名扫描 → 空。
    返回空时调研将被跳过(宁可无数据,不可混入无关数据)。
    """
    title = (requirement.project.title or "").strip()
    for cand in [title] + [fr.module.strip() for fr in requirement.functional_requirements]:
        core = _core_token(cand)
        if core:
            return core
    for text in ([requirement.project.background or ""]
                 + list(requirement.project.goals)):
        m = re.search(r"([一-龥A-Za-z0-9]{2,8})(系统|软件|平台|应用|小程序|工具)", text)
        if m:
            core = _core_token(m.group(1) + m.group(2))
            if core:
                return core
    return ""


def _build_queries(requirement: RequirementDoc) -> list[str]:
    """确定性主题检索词:主题词 + 行业报告/供应商案例/招标价格。"""
    topic = _topic_token(requirement)
    if not topic:
        return []
    return [
        f"{topic} 行业报告 市场规模",
        f"{topic} 供应商 案例 价格",
        f"{topic} 招标 报价",
    ]


def _on_topic(query: str, requirement: RequirementDoc) -> bool:
    """LLM 候选检索词必须包含项目主题词(或其一半以上字符),否则丢弃。"""
    return _page_relevant(query, requirement)


def _page_relevant(text: str, requirement: RequirementDoc) -> bool:
    """相关性门控:文本必须包含主题词,或命中其一半以上双字片段**且含首双字**。

    首双字(修饰剥离后的核心概念,如"考勤")是区分性最强的片段——
    手机等无关页面即使含有"移动/管理/系统"等通用词也无法通过。
    """
    token = _topic_token(requirement)
    if not token:
        return True
    if token in text:
        return True
    if len(token) < 4:
        return False
    bigrams = [token[i:i + 2] for i in range(len(token) - 1)]
    hits = sum(1 for b in bigrams if b in text)
    head_hit = bigrams[0] in text or bigrams[1] in text
    return head_hit and hits >= max(2, len(bigrams) // 2)


def run_research(requirement: RequirementDoc, progress_cb=None,
                 api_key: str | None = None) -> dict:
    """执行一次公开数据调研,返回 research_brief。

    progress_cb(status, payload):status ∈ started/progress/done,用于 SSE 推送。
    """
    def _progress(status: str, payload: dict | None = None) -> None:
        if progress_cb:
            try:
                progress_cb(status, payload or {})
            except Exception:
                pass

    if not settings.research_enabled:
        return {**EMPTY_BRIEF, "gaps": ["数据调研已关闭"]}

    _progress("started", {})

    # 1. 生成检索词:确定性主题词(代码)+ LLM 候选(必须通过主题校验)
    doc_json = json.dumps(requirement.model_dump(by_alias=True), ensure_ascii=False)
    queries = _build_queries(requirement)
    if not queries:
        return {**EMPTY_BRIEF, "gaps": ["未能从需求中识别项目主题词,已跳过公开数据调研(防止无关数据混入)"]}
    try:
        query_result = json_call(
            "", fill(QUERY_GEN_PROMPT, DOC=doc_json, JSON_RULES=JSON_RULES),
            max_tokens=1024, api_key=api_key,
        )
        for q in (query_result.get("queries") or []):
            if len(queries) >= settings.max_queries:
                break
            q = str(q).strip()[:24]
            if not q or q in queries:
                continue
            if _on_topic(q, requirement):
                queries.append(q)
    except LLMError:
        pass  # LLM 候选失败不影响确定性检索词
    if not queries:
        return {**EMPTY_BRIEF, "gaps": ["未能生成检索词"]}
    _progress("progress", {"stage": "searching", "queries": queries})

    # 2. 逐词搜索,合并去重,按权威度排序(同域名最多 2 条,保证来源多样性)
    seen: dict[str, dict] = {}
    for q in queries:
        for item in web_search(q):
            url = item["url"]
            if url in seen:
                continue
            item["query"] = q
            seen[url] = item
    domain_count: dict[str, int] = {}
    candidates = []
    for item in sorted(seen.values(), key=lambda it: (authority_rank(it["url"]), it["url"])):
        domain = (item["url"].split("/")[2] if "//" in item["url"] else "").lower()
        if domain_count.get(domain, 0) >= 2:
            continue
        domain_count[domain] = domain_count.get(domain, 0) + 1
        candidates.append(item)
        if len(candidates) >= 12:  # 尝试池比成功目标大,部分站点抓不到时继续尝试后面的
            break
    if not candidates:
        return {**EMPTY_BRIEF, "gaps": ["公开搜索未能获取到任何结果(网络或站点不可用)"]}

    # 3. 分批并发抓取正文,直到凑够目标页数或候选耗尽
    #    (相关性门控:正文与主题无关的页面丢弃)
    def _grab(cand: dict) -> dict | None:
        page = fetch_page(cand["url"])
        if not page:
            return None
        combined = (page["title"] or "") + " " + (page["text"] or "")[:3000]
        if not _page_relevant(combined, requirement):
            logger.info("相关性门控丢弃: %s", cand["url"])
            return None
        return {
            "source_name": source_name_for(page["url"]),
            "source_url": page["url"],
            "retrieved_at": TODAY,
            "snippet": cand.get("snippet", ""),
            "text": page["text"],
        }

    pages: list[dict] = []
    for batch_start in range(0, len(candidates), 6):
        batch = candidates[batch_start:batch_start + 6]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for grabbed in pool.map(_grab, batch):
                if grabbed:
                    pages.append(grabbed)
                    _progress("progress", {"stage": "fetching", "url": grabbed["source_url"]})
        if len(pages) >= settings.max_pages_fetch:
            break
    if not pages:
        return {**EMPTY_BRIEF, "gaps": ["搜索结果与项目主题无关或无法打开正文(站点不可达/被拦截)"]}

    # 4. LLM 数据点提取,来源 URL 白名单校验
    pages_json = json.dumps(pages, ensure_ascii=False)
    try:
        extracted = json_call(
            "",  # 提取规则已内嵌在 user 模板中
            fill(DATA_EXTRACT_PROMPT, PAGES=pages_json, JSON_RULES=JSON_RULES),
            max_tokens=4096, api_key=api_key,
        )
    except LLMError as exc:
        return {**EMPTY_BRIEF, "gaps": [f"数据提取失败:{exc}"]}
    # 来源元数据以代码为准(LLM 只提供 claim 与 confidence,杜绝来源名/URL 被改写)
    allowed = {p["source_url"]: p for p in pages}
    url_count: dict[str, int] = {}

    data_points = []
    for dp in extracted.get("data_points") or []:
        url = (dp.get("source_url") or "").strip()
        claim = (dp.get("claim") or "").strip()
        if url not in allowed or not claim:
            logger.warning("丢弃编造/无效数据点: %s", dp)
            continue
        if url_count.get(url, 0) >= 2:
            continue  # 同一来源最多引用 2 条
        url_count[url] = url_count.get(url, 0) + 1
        meta = allowed[url]
        data_points.append({
            "id": f"ref-{len(data_points) + 1:02d}",
            "claim": claim[:60],
            "source_name": meta["source_name"],
            "source_url": url,
            "retrieved_at": meta["retrieved_at"],
            "confidence": dp.get("confidence") if dp.get("confidence") in ("high", "medium", "low") else "medium",
        })

    brief = {
        "key_findings": [str(k)[:100] for k in extracted.get("key_findings") or []][:6],
        "data_points": data_points,
        "gaps": [str(g)[:100] for g in extracted.get("gaps") or []][:5],
    }
    _progress("done", {"sources_found": len(data_points)})
    return brief
