"""PDF 渲染器:reportlab Platypus,中文字体(标题微软雅黑/正文宋体)、页码页眉、
封面独立页、参考数据与来源节。全文档禁用 Helvetica(未注册 CJK 字体渲染黑块)。
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.models.intermediates import PdfDocIR
from app.utils.fonts import register_pdf_fonts
from app.utils.text import truncate

PRIMARY = colors.HexColor("#1F4E79")
GRAY = colors.HexColor("#808080")
LINE = colors.HexColor("#BFBFBF")


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(ir: PdfDocIR, out_path: Path) -> None:
    register_pdf_fonts()

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2.8 * cm, bottomMargin=2.5 * cm,
        title=ir.title,
    )

    title_style = ParagraphStyle("CoverTitle", fontName="MSYH", fontSize=22,
                                 leading=30, alignment=1, textColor=PRIMARY)
    meta_style = ParagraphStyle("CoverMeta", fontName="SimSun", fontSize=11,
                                leading=18, alignment=1, textColor=GRAY)
    h1 = ParagraphStyle("H1", fontName="MSYH", fontSize=15, leading=20,
                        textColor=PRIMARY, spaceBefore=16, spaceAfter=8)
    h2 = ParagraphStyle("H2", fontName="MSYH", fontSize=12, leading=16,
                        textColor=colors.HexColor("#333333"), spaceBefore=10,
                        spaceAfter=4)
    body = ParagraphStyle("Body", fontName="SimSun", fontSize=10.5, leading=17,
                          firstLineIndent=21, spaceAfter=4)
    bullet = ParagraphStyle("Bullet", parent=body, firstLineIndent=0,
                            leftIndent=16, spaceAfter=3)
    ref_style = ParagraphStyle("Ref", parent=body, firstLineIndent=0,
                               leftIndent=16, spaceAfter=3, fontSize=9.5)

    story = _cover(ir, title_style, meta_style) + [PageBreak()]

    for sec in ir.sections[:8]:
        story.append(Paragraph(_esc(truncate(sec.heading, 40)), h1))
        for para in sec.paragraphs:
            story.append(Paragraph(_esc(truncate(para, 80)), body))
        if sec.requirement_items:
            for item in sec.requirement_items:
                text = (f'<font name="SimHei">{_esc(item.id)}</font>  '
                        f'{_esc(truncate(item.text, 80))}')
                if item.acceptance:
                    text += f"(验收标准:{_esc(truncate(item.acceptance, 60))})"
                story.append(Paragraph(text, body))
        if sec.table:
            story.append(_pdf_table(sec.table))

    if ir.references:
        story.append(Paragraph("参考数据与来源", h1))
        for ref in ir.references:
            story.append(Paragraph(
                f"•  {_esc(ref.claim)}(来源:{_esc(ref.source_name)},"
                f"检索于 {_esc(ref.retrieved_at)})", ref_style))

    doc.build(story, onFirstPage=_blank, onLaterPages=_on_page(ir))


def _cover(ir: PdfDocIR, title_style, meta_style) -> list:
    cover = [Spacer(1, 6.5 * cm),
             Paragraph(_esc(ir.title), title_style),
             Spacer(1, 1.2 * cm)]
    if ir.doc_no:
        cover.append(Paragraph(f"文档编号:{_esc(ir.doc_no)}", meta_style))
    cover.append(Paragraph(f"版本:{_esc(ir.version)}", meta_style))
    if ir.date:
        cover.append(Paragraph(f"日期:{_esc(ir.date)}", meta_style))
    return cover


def _pdf_table(table_ir) -> Table:
    headers = table_ir.headers[:8]
    rows = [row[:8] for row in table_ir.rows[:40]]
    data = [[Paragraph(f'<font name="MSYH" color="white"><b>{_esc(h)}</b></font>',
                       ParagraphStyle("th", fontName="MSYH", fontSize=9, leading=12))
             for h in headers]]
    cell_style = ParagraphStyle("td", fontName="SimSun", fontSize=9, leading=12)
    for row in rows:
        data.append([Paragraph(_esc(truncate(c, 30)), cell_style) for c in row])
    table = Table(data, colWidths=[doc_width(len(headers))] * len(headers))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def doc_width(ncols: int) -> float:
    """内容区宽度(A4 宽 21cm - 左右边距 5cm)按列数均分。"""
    return (A4[0] - 5 * cm) / max(ncols, 1)


def _on_page(ir: PdfDocIR):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("SimSun", 8.5)
        canvas.setFillColor(GRAY)
        canvas.drawString(2.5 * cm, A4[1] - 1.6 * cm, _esc(ir.title)[:40])
        canvas.setStrokeColor(LINE)
        canvas.line(2.5 * cm, A4[1] - 1.8 * cm, A4[0] - 2.5 * cm, A4[1] - 1.8 * cm)
        canvas.drawCentredString(A4[0] / 2, 1.4 * cm, f"第 {doc.page - 1} 页")
        canvas.restoreState()
    return draw


def _blank(canvas, doc):
    pass
