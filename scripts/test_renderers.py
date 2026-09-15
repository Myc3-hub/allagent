"""渲染器自检:用手写 IR fixture 生成四类文件(不含 LLM),人工打开检查排版。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.files.registry import FILE_TYPES
from app.models.intermediates import (
    ExcelDocIR, PdfDocIR, PptDocIR, Reference, SheetIR, SlideIR,
    StatItem, SubSection, TableIR, WordDocIR, WordSection, PdfSectionIR,
    RequirementItemIR,
)

OUT = settings.output_dir / "_test"
OUT.mkdir(parents=True, exist_ok=True)

REF = Reference(
    id="ref-01", claim="2025 年中国考勤系统市场规模约 45 亿元,年增速 12%",
    source_name="艾瑞咨询", source_url="https://example.com/report",
    retrieved_at="2026-09-15", confidence="medium",
)

# ---- Word
word_ir = WordDocIR(
    title="XX公司员工考勤系统 需求分析报告", subtitle="客户需求分析与解决方案建议",
    date_hint="2026年9月",
    summary_block=["为约 50 人规模团队建设考勤系统,覆盖打卡、请假、报表三大模块。",
                   "预算 10~15 万元,期望 3 个月内上线。", "建议分两期实施,一期核心打卡功能。"],
    sections=[
        WordSection(heading="一、背景与目标",
                    lead="公司目前使用纸质签到,统计效率低。",
                    bullets=["目标:实现全员电子打卡,统计效率提升 80%。",
                             "目标:请假审批线上化,审批周期缩短至 1 天。"]),
        WordSection(heading="二、功能需求",
                    bullets=["核心功能按以下清单实施。"],
                    table=TableIR(headers=["编号", "功能", "优先级", "验收标准"],
                                  rows=[["FR-01", "人脸识别打卡", "高", "识别准确率≥99%"],
                                        ["FR-02", "请假审批流程", "高", "支持三级审批"],
                                        ["FR-03", "月度考勤报表", "中", "一键导出 Excel"]]),
                    subsections=[SubSection(heading="打卡模块",
                                            bullets=["支持手机定位打卡与门禁打卡两种方式。"])]),
        WordSection(heading="三、预算与周期",
                    bullets=[f"预算:{'10~15 万元'}(客户确认)", "周期:3 个月内上线(客户确认)",
                             "行业参考:[ref-01]"]),
    ],
    references=[REF],
)

# ---- PPT
ppt_ir = PptDocIR(
    title="XX公司员工考勤系统 需求汇报",
    slides=[
        SlideIR(kind="cover", title="XX公司员工考勤系统", bullets=["需求汇报 · 2026年9月"]),
        SlideIR(kind="agenda", title="目录", bullets=["项目背景与目标", "核心功能需求", "预算与周期", "风险与下一步"]),
        SlideIR(kind="section", title="项目背景与目标"),
        SlideIR(kind="content", title="为什么要做考勤系统",
                bullets=["纸质签到效率低,统计耗时", "请假审批靠口头,难追溯", "考勤数据人工核算易出错"]),
        SlideIR(kind="stats", title="关键数字",
                stats=[StatItem(value="50人", label="使用规模"), StatItem(value="10~15万", label="预算(估算)"),
                       StatItem(value="3个月", label="期望周期"), StatItem(value="80%", label="效率提升目标")]),
        SlideIR(kind="table", title="核心功能清单",
                table=TableIR(headers=["编号", "功能", "优先级", "验收要点"],
                              rows=[["FR-01", "人脸识别打卡", "高", "准确率≥99%"],
                                    ["FR-02", "请假审批", "高", "三级审批"],
                                    ["FR-03", "考勤报表", "中", "导出 Excel"]])),
        SlideIR(kind="content", title="风险与建议",
                bullets=["打卡并发峰值需压测", "建议二期增加排班功能", "数据隐私需合规评估"]),
        SlideIR(kind="closing", title="数据来源", bullets=[f"{REF.claim} — {REF.source_name}({REF.retrieved_at})"]),
        SlideIR(kind="closing", title="谢谢", bullets=["期待与贵司进一步沟通"]),
    ],
    references=[REF],
)

# ---- Excel
excel_ir = ExcelDocIR(
    workbook_title="XX公司员工考勤系统 需求清单与预算",
    sheets=[
        SheetIR(name="需求清单", kind="list", title_row="功能需求清单",
                headers=["编号", "模块", "功能描述", "优先级", "验收标准", "备注"],
                rows=[["FR-01", "打卡", "人脸识别打卡,支持定位", "高", "识别准确率≥99%", ""],
                      ["FR-02", "审批", "请假审批,三级流转", "高", "审批周期≤1天", ""],
                      ["FR-03", "报表", "月度考勤报表导出", "中", "一键导出Excel", ""]]),
        SheetIR(name="预算分配", kind="budget", title_row="预算分配建议",
                headers=["阶段", "项目", "内容", "预算占比", "说明"],
                rows=[["一期", "打卡模块", "人脸识别+定位打卡", "40%", "核心功能"],
                      ["一期", "审批模块", "请假审批流程", "30%", ""],
                      ["二期", "报表模块", "考勤统计报表", "30%", "可后置"]]),
        SheetIR(name="说明与假设", kind="notes", title_row="说明与假设",
                headers=["说明"],
                rows=[["报价说明:本表为预算分配建议,具体报价需商务环节确认。"],
                      ["假设:服务器与网络由客户方提供。"],
                      ["数据来源:行业市场规模参考 艾瑞咨询(检索于 2026-09-15)。"]]),
    ],
    references=[REF],
)

# ---- PDF
pdf_ir = PdfDocIR(
    title="XX公司员工考勤系统 需求规格说明书", doc_no="REQ-2026-001", version="V1.0",
    date="2026-09-15",
    sections=[
        PdfSectionIR(heading="1. 文档说明",
                     paragraphs=["本文档描述 XX 公司员工考勤系统的需求规格,作为开发与验收依据。"]),
        PdfSectionIR(heading="2. 功能需求说明",
                     requirement_items=[
                         RequirementItemIR(id="FR-01", text="系统支持人脸识别打卡。", acceptance="识别准确率不低于 99%。"),
                         RequirementItemIR(id="FR-02", text="系统支持请假审批流程。", acceptance="支持三级审批,审批周期不超过 1 天。")]),
        PdfSectionIR(heading="3. 预算与里程碑",
                     paragraphs=["预算区间 10~15 万元(客户确认,具体报价以商务确认为准)。",
                                 "期望交付:2026 年 12 月(客户确认)。"],
                     table=TableIR(headers=["里程碑", "时间", "交付物"],
                                   rows=[["M1 需求确认", "2026-10", "需求规格说明书"],
                                         ["M2 系统上线", "2026-12", "可运行系统"]])),
        PdfSectionIR(heading="4. 假设与开放问题",
                     paragraphs=["假设:服务器与网络由客户方提供。", "开放问题:打卡设备型号未定,暂按通用摄像头适配。"]),
    ],
    references=[REF],
)

for key, ir in [("word", word_ir), ("ppt", ppt_ir), ("excel", excel_ir), ("pdf", pdf_ir)]:
    entry = FILE_TYPES[key]
    out = OUT / f"test_{key}{entry['ext']}"
    entry["render"](ir, out)
    print(f"[ok] {out.name}  {out.stat().st_size} bytes")
print("全部渲染完成,请打开 output/_test/ 目录人工检查")
