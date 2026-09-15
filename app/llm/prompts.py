"""全部提示词模板。所有结构化输出 prompt 的硬约束:

- 只输出一个 JSON 对象,不含 Markdown 围栏、不含任何解释文字;
- 定量论断要么引用给定的 references,要么显式标注"估算/假设";
- 严禁编造数据与来源(URL 只能原样复制自输入材料)。
"""
from __future__ import annotations

import json

from app.agent.clarify import FIELD_LABELS, P0_FIELDS, P1_FIELDS
from app.models.intermediates import (
    ExcelDocIR, PdfDocIR, PptDocIR, WordDocIR,
)
from app.models.schemas import RequirementDoc


def fill(template: str, **kw) -> str:
    """{{key}} 占位符替换(模板内 JSON 花括号不受影响)。"""
    out = template
    for key, value in kw.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


def _skeleton(model) -> str:
    """从 Pydantic JSON Schema 生成示例骨架:必填字段留空值、数组给一个示例项,
    帮助 LLM 按结构填空(解决 IR 模型有必填字段、无法实例化空对象的问题)。"""

    def build(props_schema: dict, defs: dict) -> dict:
        out: dict = {}
        for key, prop in props_schema.get("properties", {}).items():
            if "$ref" in prop:
                ref = defs.get(prop["$ref"].rsplit("/", 1)[-1], {})
                out[key] = build(ref, defs)
            elif "anyOf" in prop:  # 可选字段(str|null 等)
                types = {o.get("type") for o in prop["anyOf"] if "type" in o}
                if "string" in types:
                    out[key] = ""
                elif "integer" in types:
                    out[key] = 0
                elif "array" in types:
                    out[key] = []
                elif "object" in types:
                    out[key] = {}
                else:
                    out[key] = None
            elif prop.get("type") == "array":
                items = prop.get("items") or {}
                if "$ref" in items:
                    # 始终给一个示例项,让 LLM 看到条目结构
                    ref = defs.get(items["$ref"].rsplit("/", 1)[-1], {})
                    out[key] = [build(ref, defs)]
                else:
                    out[key] = []
            elif prop.get("type") == "object":
                out[key] = {}
            elif "enum" in prop:
                out[key] = prop["enum"][0]
            elif prop.get("type") == "string":
                out[key] = ""
            elif prop.get("type") == "integer":
                out[key] = 0
            elif prop.get("type") == "boolean":
                out[key] = False
            else:
                out[key] = None
        return out

    schema = model.model_json_schema(by_alias=True)
    return json.dumps(build(schema, schema.get("$defs", {})), ensure_ascii=False, indent=2)


EMPTY_DOC_SKELETON = _skeleton(RequirementDoc)
KNOWN_PATHS = sorted(set(list(FIELD_LABELS.keys()) + [
    "project.title",
    "stakeholders.customer",
    "stakeholders.decision_makers",
    "non_functional_requirements.reliability",
    "non_functional_requirements.usability",
    "non_functional_requirements.compatibility",
    "non_functional_requirements.scalability",
    "constraints.organizational",
    "constraints.other",
    "timeline.expected_start",
    "timeline.urgency",
    "timeline.milestones",
]))

JSON_RULES = """【输出格式铁律】
1. 只输出一个 JSON 对象,不要 Markdown 代码围栏,不要任何解释文字。
2. 所有字段名必须与给定结构完全一致,字符串使用简体中文。
3. 定量数字要么来自输入材料中明确给出的数据,要么标注"估算"二字,严禁编造数字。
4. 来源 URL 只能原样复制自输入材料,严禁编造任何网址。"""

# ---------------------------------------------------------------- 聊天系统提示词

SYSTEM_PROMPT = """你是一位资深需求分析师,负责与客户对话、澄清客户需求。
你的方法论:5W2H(背景/目标/范围/干系人/周期/预算)+ 功能与非功能需求 + 约束 + 优先级 + 风险。
行为规则:
1. 每次最多提出 3 个问题,用客户能听懂的口语,不出现"非功能需求"这类术语(改问"系统要支撑多少人同时用")。
2. 不知道的信息不要编造,必要时说明将按假设处理。
3. 回答简洁,不客套,不输出 JSON,不输出长篇大论。
4. 全部使用简体中文。
5. 数据与事实以调研取得的公开资料为准,拿不准的明确说"公开资料未查到"。"""

# ---------------------------------------------------------------- 首条消息提取

EXTRACT_PROMPT = """你是需求分析师。根据客户的最初需求描述,提取已经明确的信息,填写结构化需求文档。

只填写客户明确表达或可确凿推断的字段;未提及的字段保持空值/空数组/null。禁止为了填满结构而编造内容。
functional_requirements 的每个条目必须是对象(含 id/module/description/priority/acceptance_criteria 字段),严禁写成纯字符串列表。
project.title:客户未给项目命名时,根据需求拟一个不超过 16 字的暂定项目名(如"员工考勤系统"),并在 updated_fields 中列入 project.title。严禁填写"待补充/待定/未定/暂无"等占位词,拟不出就留空。

已知可用的字段路径(updated_fields 只能从中选择):
{{KNOWN_PATHS}}

文档结构(空模板,在此结构上填写):
{{SKELETON}}

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"requirement": {...填写后的文档...}, "updated_fields": ["project.goals", ...]}

其中 updated_fields 列出你在 requirement 中实际填写了内容的字段路径(路径只能来自上面的已知路径列表)。"""

# ---------------------------------------------------------------- 澄清提问生成

NEXT_QUESTIONS_PROMPT = """你是需求分析师,正在与客户澄清需求。这是**唯一的一轮提问**(本轮之后不再追问),请提出最多 3 个问题,直击需求核心。

本轮需要询问的字段(按顺序):{{TARGETS}}

最近对话(最多6条,按时间顺序):
{{HISTORY}}

提问规则:
1. 最多 3 个问题,**必须覆盖本轮列出的全部目标字段**——一个问题的 fields 可以包含多个字段(如背景与目标合并为一问)。
2. 问题直击核心、具体可答,不要求客户自己分析;用客户能听懂的口语。
3. 每个问题不超过 35 字,可附带选项引导,如"大致 10 万以内/10~30 万/30 万以上"。
4. 不得重复询问客户已经回答过的字段。
5. 问题按目标字段的列出顺序组织,最重要的字段(功能需求/预算/周期)优先。

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"questions": [{"text": "问题内容", "fields": ["budget.amount"], "purpose": "了解预算区间"}]}"""

# ---------------------------------------------------------------- 回答合并

MERGE_PROMPT = """你是需求分析师。把客户的新回答合并进现有的结构化需求文档。

现有文档(JSON):
{{DOC}}

本轮提问(客户是在回答这些问题):
{{QUESTIONS}}

客户的最新回答:
{{ANSWER}}

合并规则:
1. 只更新客户回答中明确涉及的字段;回答未涉及的字段**必须原样保留,严禁清空或删除已有内容**。
2. updated_fields 列出本次实际更新的字段路径(只能从已知路径列表中选择)。
3. 客户说的模糊量级用区间表述(如"10~30万");客户没说的信息不得凭空补全。
4. 客户的一句话可能同时回答多个问题,都要吸收。
5. functional_requirements 的每个条目必须是对象(含 id/module/description/priority/acceptance_criteria 字段),严禁写成纯字符串列表;已有条目保持原 id 不变。
6. project.title 保持已有值不变;若原为空,基于需求拟一个简短项目名(如"员工考勤系统"),严禁填写"待补充/待定"等占位词。

已知字段路径:
{{KNOWN_PATHS}}

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"requirement": {...合并后的完整文档...}, "updated_fields": ["budget.amount"]}"""

# ---------------------------------------------------------------- 检索词生成

QUERY_GEN_PROMPT = """你是行业研究员。根据客户需求,生成用于检索"已公开同类数据"的中文检索词。

客户需求摘要(JSON):
{{DOC}}

目标:找到已公布的行业报告、市场规模、政策标准、标杆案例、价格区间等公开资料。

检索词规则:
1. 生成 3 个检索词,每个不超过 20 字。
2. 每个检索词**必须包含客户项目的核心主题词**(从需求中提取的产品/系统/服务名称,如"考勤系统"、"打卡软件"),形式为"主题词 + 行业报告/市场规模/供应商案例/招标价格",如"考勤系统 市场规模 行业报告"、"考勤系统 供应商 案例"。
3. 严禁泛化为宏观经济或产业政策类检索(如"中小企业政策"),必须紧扣本项目主题。
4. 不要包含"我/我的/我们"等第一人称词;不要带引号。
5. 优先检索:行业数据与报告 > 供应商案例与价格 > 政策与标准。

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"queries": ["检索词1", "检索词2", "检索词3"], "industry": "推断的行业名称"}"""

# ---------------------------------------------------------------- 数据点提取

DATA_EXTRACT_PROMPT = """你是数据核实员。从抓取到的公开网页正文中提取可引用的数据点。

材料列表(每条含来源元数据与正文摘要):
{{PAGES}}

提取规则(铁律):
1. claim 中的数据、数字、结论必须真实出现在该材料的 text 中,严禁根据常识或记忆补充。
2. source_name 与 source_url 必须原样复制自该材料的元数据,严禁编造网址;retrieved_at 原样复制。
3. 每条 claim 不超过 60 字,是一句可独立引用的数据事实(含数字或明确结论)。
4. confidence:high=官方机构发布;medium=行业媒体/公司发布;low=自媒体或个人言论。
5. 某条材料没有可引用的数据就跳过;全部没有就输出空数组。宁缺毋滥。
6. gaps 列出:本应查到但未找到的数据类型(如"未找到该行业平均单价数据")。

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"key_findings": ["整体发现1", "整体发现2"], "data_points": [{"claim": "...", "source_name": "...", "source_url": "...", "retrieved_at": "...", "confidence": "high|medium|low"}], "gaps": ["..."]}"""

# ---------------------------------------------------------------- 定稿

FINALIZE_PROMPT = """你是资深需求分析师。基于澄清结果与公开资料调研,输出定稿的需求分析。

已收集的需求文档(JSON,部分字段为空):
{{DOC}}

字段状态(confirmed=客户确认;missing=未回答;assumed=将按假设处理):
{{FIELD_STATES}}

公开资料调研简报:
{{RESEARCH}}

定稿规则:
1. 补全文档中所有缺失字段:客户确认过的内容原样保留;缺失内容给出专业、合理的取值,并在 assumptions 中逐条列出"该取值基于假设"。
2. 生成 priority_analysis(必须项/可选项/二期建议,可引用功能需求编号)、risks(至少 3 条,每条必须含 id、description、likelihood、impact、mitigation)、open_questions(未决问题及当前处理方式)。
3. timeline.milestones 每条必须是对象(含 name/date/deliverable 字段),严禁写成纯字符串列表。
4. references 只保留调研简报 data_points 中出现的引用,原样复制其 id/claim/source_name/source_url/retrieved_at/confidence,严禁新增或改写来源。
5. 所有定量论断:有公开数据支撑的引用 references(在文本中标注 [ref-01] 等);无公开数据的显式写"估算"或"假设"。
6. meta 字段:version 在现有基础上 +1;updated_at 填今天日期;research_note 简述调研方法与检索日期。
7. summary_text:350~500 字要点式摘要,按 背景/目标/范围/核心功能/非功能要点/预算/周期/关键风险与建议/数据来源 分组,每组一行要点,引用数据处标注 [ref-XX]。

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"summary_text": "...", "requirement": {...定稿后的完整文档...}}"""

# ---------------------------------------------------------------- 文件生成(共用骨架)

FILE_COMMON_RULES = """生成规则:
1. 内容必须严格依据给定需求文档,不得新增需求文档中没有的信息。
2. 定量数据只能来自 references 并保留 [ref-XX] 标注;无据数字一律标注"估算";禁止新增任何来源。
3. 条例清晰、要点式表达:短句、动词开头、层级分明、每节信息密度适中,不写客套话。
4. 全部使用简体中文。"""


def _file_prompt(ir_model, extra_rules: str, doc_label: str = "需求文档") -> str:
    return f"""你是资深文档专家,为客户生成{doc_label}。目标受众:客户方决策者与项目干系人。

{extra_rules}

{FILE_COMMON_RULES}

{JSON_RULES}

请输出 JSON 对象,结构必须与以下 Schema 完全一致:
{_skeleton(ir_model)}
"""


WORD_FILE_PROMPT = _file_prompt(
    WordDocIR,
    """Word 需求分析报告格式要求:
1. 固定骨架(不超过 7 节):背景与目标 / 需求范围 / 功能需求 / 非功能与约束 / 预算与周期 / 风险与建议 / 下一步计划。功能需求节必须带 table 表格(列:编号|功能|优先级|验收标准,每条功能需求一行)。
2. summary_block 为执行摘要,不超过 8 条,每条不超过 40 字。
3. 每节要点 bullets 每条不超过 40 字、单句成行;章节导语 lead 不超过 60 字,可省略。
4. 表格不超过 8 列 × 40 行,单元格不超过 30 字。
5. 层级最多两级(sections → subsections),不要三级嵌套。
6. 定量数据必须带 [ref-XX] 标注;预算区间如为客户确认值则如实写。
7. references 原样复制自需求文档的 references,不得改写。""",
    "Word 需求分析报告",
)

PPT_FILE_PROMPT = _file_prompt(
    PptDocIR,
    """PPT 需求汇报格式要求:
1. 总页数 10~14 页,骨架:cover(封面) / agenda(目录) / section(章节页) / content(内容页 3~4 页) / stats(关键数字页) / table(功能需求表格页) / content(总结与下一步) / closing(数据来源) / closing(致谢)。
2. content 页要点不超过 5 条、每条不超过 20 字;标题不超过 16 字。
3. stats 页 3~4 个数字卡片,数字必须来自 references 或标注"估算",label 简短。
4. table 页不超过 6 列 × 8 行,列:编号|功能|优先级|验收要点。
5. 数据来源页(closing)标题为"数据来源",bullets 列出每条引用的"来源名 + 检索日期"。
6. 每页要点动词开头、信息密度适中,数字尽量量化。""",
    "PPT 需求汇报演示文稿",
)

EXCEL_FILE_PROMPT = _file_prompt(
    ExcelDocIR,
    """Excel 需求清单格式要求:
1. 必须 3 张表,顺序固定:需求清单(kind=list)/ 预算分配(kind=budget)/ 说明与假设(kind=notes)。
2. 需求清单表:列(不超过 7 列)建议为 编号|模块|功能描述|优先级|验收标准|备注;行不超过 40 行,单元格不超过 30 字。
3. 预算分配表:按 阶段/项目/内容/预算占比/说明 列组织,只能给"预算分配建议"(占比或区间),严禁编造精确单价;表尾说明"预算分配建议,具体报价需商务确认"。
4. 说明与假设表(kind=notes):内容分三段——报价与商务说明、假设清单(逐行)、数据来源清单(逐行,来源名+检索日期)。
5. workbook_title 不超过 30 字;每张表 title_row 为大标题。""",
    "Excel 需求清单与预算表",
)

PDF_FILE_PROMPT = _file_prompt(
    PdfDocIR,
    """PDF 需求规格说明书格式要求:
1. 正式条款语气,不超过 8 节,标题带编号,如"1. 文档说明 / 2. 功能需求说明 / 3. 非功能需求 / 4. 验收标准与里程碑 / 5. 假设与开放问题 / 6. 参考数据与来源"。
2. 功能需求节用 requirement_items 逐条列出 FR 条款(含验收标准);其余节用 paragraphs,每条不超过 80 字。
3. doc_no 形如"REQ-2026-001";version 形如"V1.0";date 填今天日期。
4. 条款式、无口语化;每条定量条款要么引用 [ref-XX] 要么标注"估算"。
5. references 原样复制自需求文档的 references,不得改写。""",
    "PDF 需求规格说明书",
)

FILE_PROMPTS = {
    "word": WORD_FILE_PROMPT,
    "ppt": PPT_FILE_PROMPT,
    "excel": EXCEL_FILE_PROMPT,
    "pdf": PDF_FILE_PROMPT,
}

# ---------------------------------------------------------------- 通用任务引擎

TASK_CLASSIFY_PROMPT = """你是综合性 AI 运营助手。判断客户消息是否在请求生成某种文件/内容,并提取任务参数。

客户消息:
{{TEXT}}

任务类型:speech(发言稿/演讲稿/致辞)、ppt(主题演示文稿)、report(报告/方案/总结/策划)、notice(通知/公告/函)。

判定规则:
1. 只有客户明确请求"写/生成/制作/起草/帮我写/帮我做"某类内容时才判为对应任务;
   需求描述、咨询、闲聊、修改意见一律 task=none。
2. params 只填消息中明确出现的信息,未提及的字段填空字符串,严禁编造。
3. topic 是核心字段:内容主题/标题/场合主题。

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"task": "speech|ppt|report|notice|none", "params": {"topic": "", "audience": "", "occasion": "", "style": "", "length": "", "requirements": ""}}"""

TASK_QUESTIONS_PROMPT = """你是综合性 AI 运营助手,正在为客户{{ACTION}}。为了产出高质量、贴合需要的内容,请补充询问必要信息。

当前已知的任务参数(JSON,空字符串表示未知):
{{PARAMS}}

提问规则:
1. 最多 2 个问题,只问对质量影响最大的缺失信息(优先 topic 主题;其次 audience 受众、occasion 场合、style 风格、length 篇幅)。
2. 口语化,每个问题不超过 35 字,可附选项引导。
3. 已有信息不重复问。

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"questions": [{"text": "问题内容", "purpose": "了解什么"}]}"""

TASK_MERGE_PROMPT = """把客户的最新回答合并进任务参数。

当前参数(JSON,空字符串表示未知):
{{PARAMS}}

客户回答(针对以下提问):
{{QUESTIONS}}

客户的最新回答:
{{ANSWER}}

规则:只更新客户回答中明确涉及的字段;未涉及的字段原样保留;回答中没有的信息不得凭空补全。

{{JSON_RULES}}

请输出 JSON 对象,格式为:
{"params": {"topic": "...", "audience": "...", "occasion": "...", "style": "...", "length": "...", "requirements": "..."}}"""


def _task_file_prompt(ir_model, label: str, extra_rules: str) -> str:
    return f"""你是资深{label}专家,为客户完成内容创作。

任务参数(JSON):
{{{{PARAMS}}}}

可用参考数据(JSON 数组,每条含 claim/source_name/source_url/retrieved_at;仅引用与主题相关的数据,
引用处在文中标注 [ref-01] 等;无相关数据则忽略):
{{{{REFERENCES}}}}

{extra_rules}

{FILE_COMMON_RULES}

{JSON_RULES}

请输出 JSON 对象,结构必须与以下 Schema 完全一致:
{_skeleton(ir_model)}
"""


TASK_FILE_PROMPTS = {
    "speech": _task_file_prompt(
        WordDocIR, "发言稿撰写",
        """发言稿写作要求:
1. 结构:sections 依次为 开场(称呼+问候+切入主题)→ 正文(2~4 个要点节,每节 3~5 条要点)→ 结尾(总结升华+致谢)。
2. 语言口语化、庄重得体;结合 audience/occasion 定制称呼与语气(如年会、项目启动会、培训开班)。
3. 每条要点不超过 40 字、单句成行;不写套话空话,内容具体、有感染力。
4. title 用《{topic}发言稿》格式,subtitle 填场合,date_hint 填今天日期。
5. summary_block、subsections、table 全部留空。""",
    ),
    "ppt": _task_file_prompt(
        PptDocIR, "演示文稿设计",
        """主题 PPT 制作要求:
1. 总页数 10~14 页,骨架:cover(封面)/ agenda(目录)/ section(章节页)/ content(内容页 3~5 页)/ stats(关键数字页)/ table(对比表,可选)/ content(总结)/ closing(数据来源)/ closing(致谢)。
2. 内容围绕 topic 展开,条理清晰;content 页要点不超过 5 条、每条不超过 20 字;标题不超过 16 字。
3. stats 页数字必须来自参考数据(标注)或明确标注"估算";无可用数据时该页改用结论要点。
4. 数据来源页(closing)标题为"数据来源",列出引用来源名与检索日期。
5. 每页要点动词开头、信息密度适中。""",
    ),
    "report": _task_file_prompt(
        WordDocIR, "报告撰写",
        """报告/方案写作要求:
1. 结构:sections 依次为 背景与现状 / 目标与需求 / 分析与建议(核心,2~3 节)/ 实施步骤 / 风险与保障 / 下一步。
2. summary_block 为执行摘要,不超过 8 条,每条不超过 40 字。
3. 每条要点不超过 40 字、单句成行;关键数据用表格呈现(不超过 8 列 × 40 行)。
4. 引用参考数据处标注 [ref-XX];无公开数据支撑的定量表述一律标注"估算"。
5. title 用《{topic}》格式,subtitle 填文档类型,date_hint 填今天日期。""",
    ),
    "notice": _task_file_prompt(
        WordDocIR, "公文写作",
        """通知/公告写作要求:
1. 公文格式:title 用《关于{topic}的通知》格式;sections 依次为 主送对象(标题下第一行,如"各部门:")→ 正文(缘由+事项条款)→ 落款说明(单位与日期写在 lead 或末条要点)。
2. 正文条款式表达,每条不超过 40 字,简明扼要、语气正式,不写口语。
3. 涉及时间、地点、要求的具体信息必须明确;未提供的信息在条文中标注"另行通知"或"详见附件"。
4. summary_block、subsections、table 全部留空。""",
    ),
}
