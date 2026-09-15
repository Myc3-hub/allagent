"""Word 渲染器:python-docx,中文排版(标题黑体/正文宋体/表格/页码/参考来源节)。"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.models.intermediates import WordDocIR
from app.utils.fonts import set_run_font_docx

PRIMARY = "1F4E79"      # 深蓝(标题)
HEADER_FILL = "D9E2F3"  # 表头底纹


def render(ir: WordDocIR, out_path: Path) -> None:
    doc = Document()

    # 页面:A4,上下 2.54cm、左右 2.8cm
    section = doc.sections[0]
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.8)
    section.right_margin = Cm(2.8)

    _setup_styles(doc)
    _cover(doc, ir)
    doc.add_page_break()

    # 执行摘要
    if ir.summary_block:
        _heading(doc, "执行摘要", level=1)
        for line in ir.summary_block[:8]:
            _bullet(doc, line)

    # 正文章节
    for sec in ir.sections:
        _heading(doc, sec.heading, level=1)
        if sec.lead:
            _para(doc, sec.lead)
        for bullet in sec.bullets:
            _bullet(doc, bullet)
        if sec.subsections:
            for sub in sec.subsections:
                _heading(doc, sub.heading, level=2)
                for bullet in sub.bullets:
                    _bullet(doc, bullet)
        if sec.table:
            _table(doc, sec.table)

    # 参考数据与来源
    if ir.references:
        _heading(doc, "参考数据与来源", level=1)
        for ref in ir.references:
            _bullet(doc, f"{ref.claim}(来源:{ref.source_name},{ref.source_url},检索于 {ref.retrieved_at})")

    _page_number_footer(section)
    doc.save(str(out_path))


# ------------------------------------------------------------------ 基础组件

def _setup_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.paragraph_format.line_spacing = 1.5

    for name, east, size, color in [
        ("Heading 1", "黑体", 16, PRIMARY),
        ("Heading 2", "黑体", 13, PRIMARY),
    ]:
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        r_pr = style.element.get_or_add_rPr()
        r_fonts = r_pr.get_or_add_rFonts()
        r_fonts.set(qn("w:eastAsia"), east)


def _cover(doc: Document, ir: WordDocIR) -> None:
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(ir.title)
    set_run_font_docx(run, east="黑体", latin="Times New Roman", size=22, bold=True,
                      color_hex=PRIMARY)
    if ir.subtitle:
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run2 = p2.add_run(ir.subtitle)
        set_run_font_docx(run2, east="黑体", size=14, color_hex="404040")
    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run3 = p3.add_run(ir.date_hint or "")
    set_run_font_docx(run3, east="宋体", size=12, color_hex="808080")


def _heading(doc: Document, text: str, level: int) -> None:
    doc.add_heading(text, level=level)


def _para(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Pt(24)
    run = p.add_run(text)
    set_run_font_docx(run, east="宋体", size=12)


def _bullet(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    run = p.add_run(text)
    set_run_font_docx(run, east="宋体", size=12)


def _table(doc: Document, table_ir) -> None:
    headers = table_ir.headers[:8]
    rows = [row[:8] for row in table_ir.rows[:40]]
    if not headers:
        return
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, text in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        set_run_font_docx(run, east="黑体", size=10.5, bold=True)
        _shade(cell, HEADER_FILL)
    for r, row in enumerate(rows, start=1):
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            cell.text = ""
            run = cell.paragraphs[0].add_run((text or "")[:30])
            set_run_font_docx(run, east="宋体", size=10.5)
    # 表头跨页重复
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tr_pr.append(tbl_header)


def _shade(cell, color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def _page_number_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE \\* MERGEFORMAT")
    r = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    r_fonts = OxmlElement("w:rFonts")
    r_fonts.set(qn("w:eastAsia"), "宋体")
    r_pr.append(r_fonts)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "18")
    r_pr.append(sz)
    r.append(r_pr)
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    p._p.append(fld)
