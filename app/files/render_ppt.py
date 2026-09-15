"""PPT 渲染器:python-pptx,16:9 深蓝商务风格。

设计规范:深蓝 #1F4E79 主色 + 白底内容页 + 灰 #404040 正文;封面/结尾深底、中间浅底;
标题下不用装饰线/色条;每页必须有视觉元素(编号圆块、大数字卡片、表格);
要点用文本前缀 "▪ "(空白文本框无继承项目符号,且不与 buChar 混用)。
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from app.models.intermediates import PptDocIR
from app.utils.fonts import set_run_font_pptx
from app.utils.text import truncate

PRIMARY = RGBColor.from_string("1F4E79")
BODY = RGBColor.from_string("404040")
LIGHT_TINT = RGBColor.from_string("EAF1F8")
WHITE = RGBColor.from_string("FFFFFF")
GRAY = RGBColor.from_string("808080")

SW, SH = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.7)


def render(ir: PptDocIR, out_path: Path) -> None:
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    blank = prs.slide_layouts[6]

    section_no = 0
    for slide_ir in ir.slides:
        slide = prs.slides.add_slide(blank)
        kind = slide_ir.kind
        if kind == "cover":
            _cover(slide, slide_ir, ir)
        elif kind == "agenda":
            _agenda(slide, slide_ir)
        elif kind == "section":
            section_no += 1
            _section(slide, slide_ir, section_no)
        elif kind == "content":
            _content(slide, slide_ir)
        elif kind == "stats":
            _stats(slide, slide_ir)
        elif kind == "table":
            _table_slide(slide, slide_ir)
        elif kind == "closing":
            _closing(slide, slide_ir)

    prs.save(str(out_path))


# ------------------------------------------------------------------ 组件

def _bg(slide, color: RGBColor) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False


def _box(slide, x, y, w, h):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    return tf


def _para(tf, text: str, *, size: float = 16, bold: bool = False,
          color: RGBColor = BODY, align=PP_ALIGN.LEFT, first: bool = False,
          space_after: float = 6) -> None:
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(space_after)
    run = p.add_run()
    run.text = text
    set_run_font_pptx(run, east="微软雅黑", size=size, bold=bold, color_hex=str(color))


def _num_circle(slide, x, y, number: int) -> None:
    """编号圆块:深蓝圆 + 白色数字。"""
    d = Inches(0.5)
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, d, d)
    shape.fill.solid()
    shape.fill.fore_color.rgb = PRIMARY
    shape.line.fill.background()
    shape.shadow.inherit = False
    tf = shape.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = str(number)
    set_run_font_pptx(run, east="微软雅黑", size=16, bold=True, color_hex="FFFFFF")


def _title(slide, text: str, y: Inches = Inches(0.55)) -> None:
    tf = _box(slide, MARGIN, y, SW - 2 * MARGIN, Inches(0.8))
    _para(tf, truncate(text, 16), size=30, bold=True, color=PRIMARY, first=True, space_after=0)


# ------------------------------------------------------------------ 页面类型

def _cover(slide, slide_ir, ir: PptDocIR) -> None:
    _bg(slide, PRIMARY)
    tf = _box(slide, Inches(1.2), Inches(2.4), SW - Inches(2.4), Inches(1.6))
    _para(tf, truncate(slide_ir.title or ir.title, 20), size=36, bold=True,
          color=WHITE, align=PP_ALIGN.CENTER, first=True, space_after=10)
    if slide_ir.bullets:
        _para(tf, truncate(slide_ir.bullets[0], 30), size=18, color=LIGHT_TINT,
              align=PP_ALIGN.CENTER, space_after=0)


def _agenda(slide, slide_ir) -> None:
    _title(slide, slide_ir.title or "目录")
    items = [b for b in slide_ir.bullets[:6]]
    y = Inches(1.9)
    for i, item in enumerate(items, start=1):
        _num_circle(slide, Inches(1.2), y + Inches(0.08), i)
        tf = _box(slide, Inches(2.0), y, Inches(9.5), Inches(0.7))
        _para(tf, truncate(item, 30), size=18, color=BODY, first=True, space_after=0)
        y += Inches(0.85)


def _section(slide, slide_ir, number: int) -> None:
    tf = _box(slide, MARGIN, Inches(2.2), Inches(3.0), Inches(1.6))
    _para(tf, f"{number:02d}", size=54, bold=True, color=PRIMARY, first=True,
          space_after=0)
    tf2 = _box(slide, Inches(3.6), Inches(2.5), Inches(9.0), Inches(1.0))
    _para(tf2, truncate(slide_ir.title, 16), size=32, bold=True, color=BODY,
          first=True, space_after=0)
    if slide_ir.bullets:
        tf3 = _box(slide, Inches(3.6), Inches(3.5), Inches(9.0), Inches(1.0))
        _para(tf3, truncate(slide_ir.bullets[0], 40), size=14, color=GRAY,
              first=True, space_after=0)


def _content(slide, slide_ir) -> None:
    _title(slide, slide_ir.title)
    tf = _box(slide, Inches(1.0), Inches(1.6), SW - Inches(2.0), Inches(5.4))
    bullets = [truncate(b, 20) for b in slide_ir.bullets[:5]]
    for i, bullet in enumerate(bullets):
        _para(tf, f"▪  {bullet}", size=16, color=BODY, first=(i == 0), space_after=14)


def _stats(slide, slide_ir) -> None:
    _title(slide, slide_ir.title)
    items = (slide_ir.stats or [])[:4]
    gap = Inches(0.35)
    card_w = (SW - 2 * Inches(1.0) - 3 * gap) / 4
    x = Inches(1.0)
    y = Inches(2.1)
    for item in items:
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, card_w, Inches(2.6))
        card.fill.solid()
        card.fill.fore_color.rgb = LIGHT_TINT
        card.line.fill.background()
        card.shadow.inherit = False
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.25)
        tf.margin_right = Inches(0.25)
        tf.margin_top = Inches(0.45)
        _para(tf, truncate(item.value, 9), size=30, bold=True, color=PRIMARY,
              first=True, space_after=8)
        _para(tf, truncate(item.label, 10), size=14, color=BODY, space_after=0)
        x += card_w + gap


def _table_slide(slide, slide_ir) -> None:
    _title(slide, slide_ir.title)
    table_ir = slide_ir.table
    if not table_ir:
        return
    headers = table_ir.headers[:6]
    rows = [row[:6] for row in table_ir.rows[:8]]
    if not headers:
        return
    n_rows = 1 + len(rows)
    n_cols = len(headers)
    total_w = Inches(11.9)
    col_w = total_w // n_cols
    shape = slide.shapes.add_table(n_rows, n_cols, Inches(0.7), Inches(1.7),
                                   total_w, Inches(0.5) * n_rows)
    table = shape.table
    table.columns[0].width = Inches(1.4)
    for c in range(1, n_cols):
        table.columns[c].width = col_w
    for c, text in enumerate(headers):
        _cell_text(table.cell(0, c), text, size=14, bold=True, color=WHITE,
                   fill=PRIMARY)
    for r, row in enumerate(rows, start=1):
        fill = LIGHT_TINT if r % 2 == 0 else WHITE
        for c in range(n_cols):
            text = row[c] if c < len(row) else ""
            _cell_text(table.cell(r, c), truncate(text, 30), size=12, bold=False,
                       color=BODY, fill=fill)


def _cell_text(cell, text: str, *, size: float, bold: bool, color: RGBColor,
               fill: RGBColor) -> None:
    cell.fill.solid()
    cell.fill.fore_color.rgb = fill
    tf = cell.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER if bold else PP_ALIGN.LEFT
    run = p.add_run()
    run.text = text
    set_run_font_pptx(run, east="微软雅黑", size=size, bold=bold, color_hex=str(color))


def _closing(slide, slide_ir) -> None:
    _bg(slide, PRIMARY)
    tf = _box(slide, Inches(1.2), Inches(2.2), SW - Inches(2.4), Inches(1.0))
    _para(tf, truncate(slide_ir.title, 16), size=32, bold=True, color=WHITE,
          align=PP_ALIGN.CENTER, first=True, space_after=0)
    if slide_ir.bullets:
        tf2 = _box(slide, Inches(1.6), Inches(3.4), SW - Inches(3.2), Inches(3.2))
        for i, bullet in enumerate(slide_ir.bullets[:8]):
            _para(tf2, f"•  {truncate(bullet, 50)}", size=14, color=LIGHT_TINT,
                  first=(i == 0), space_after=8)
