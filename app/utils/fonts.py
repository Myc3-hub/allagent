"""中文字体辅助:reportlab 注册、docx/pptx 东亚字体设置。

Windows 字体路径由 config.settings 提供;若字体文件缺失(非 Windows 环境),
注册函数降级为空操作并记录警告,避免启动失败。
"""
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_registered = False


def _resolve_font(win_path) -> str:
    """Windows 字体存在则用之,否则回退到打包的思源黑体(Linux 部署)。"""
    path = Path(str(win_path))
    if path.exists():
        return str(path)
    bundled = Path(str(settings.bundled_font))
    if bundled.exists():
        return str(bundled)
    return str(path)


def register_pdf_fonts() -> None:
    """注册 reportlab 中文字体(启动时调用一次)。

    TTC 集合必须指定 subfontIndex:msyh.ttc 索引 0 为常规体,simsun.ttc 索引 0 为常规体。
    Linux 环境全部回退到思源黑体(标题/正文共用,可移植)。
    注册后全文禁止使用 Helvetica 等未含 CJK 的字体(会渲染成黑块)。
    """
    global _registered
    if _registered:
        return
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        registered = set()
        for name, win_path, index in [
            ("MSYH", settings.font_msyh, 0),
            ("SimSun", settings.font_simsun, 0),
            ("SimHei", settings.font_simhei, None),
        ]:
            resolved = _resolve_font(win_path)
            if not Path(resolved).exists():
                logger.warning("字体文件不存在,跳过注册: %s", resolved)
                continue
            font = (TTFont(name, resolved, subfontIndex=index) if index is not None
                    else TTFont(name, resolved))
            # 回退到同一文件时避免重复注册同名字体
            if name in registered:
                continue
            pdfmetrics.registerFont(font)
            registered.add(name)
        # 显式声明粗体映射(回退字体无独立粗体,统一用常规体,避免 reportlab 报错)
        for family, bold in (("MSYH", "MSYH"), ("SimSun", "SimHei"), ("SimHei", "SimHei")):
            pdfmetrics.registerFontFamily(family, normal=family, bold=bold,
                                          italic=family, boldItalic=bold)
        _registered = True
        logger.info("PDF 中文字体注册完成(源: %s)", _resolve_font(settings.font_msyh))
    except ImportError:
        logger.warning("reportlab 未安装,跳过 PDF 字体注册")


def set_run_font_docx(run, east: str = "宋体", latin: str = "Times New Roman",
                      size: float | None = None, bold: bool | None = None,
                      color_hex: str | None = None) -> None:
    """设置 Word run 的西文与东亚字体(必须成对设置,否则中文回退默认字体)。"""
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    run.font.name = latin
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.get_or_add_rFonts()
    r_fonts.set(qn("w:eastAsia"), east)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color_hex is not None:
        run.font.color.rgb = RGBColor.from_string(color_hex)


def set_run_font_pptx(run, east: str = "微软雅黑", latin: str = "Arial",
                      size: float | None = None, bold: bool | None = None,
                      color_hex: str | None = None) -> None:
    """设置 PPT run 的西文与东亚字体。

    python-pptx 的 font.name 只写 <a:latin>,东亚字体需手工写 <a:ea typeface="..."/>。
    """
    from pptx.oxml.ns import qn
    from pptx.util import Pt
    from pptx.dml.color import RGBColor

    run.font.name = latin
    r_pr = run._r.get_or_add_rPr()
    ea = r_pr.find(qn("a:ea"))
    if ea is None:
        ea = r_pr.makeelement(qn("a:ea"), {})
        r_pr.append(ea)
    ea.set("typeface", east)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color_hex is not None:
        run.font.color.rgb = RGBColor.from_string(color_hex)


from pathlib import Path  # noqa: E402  (供 register_pdf_fonts 使用)
