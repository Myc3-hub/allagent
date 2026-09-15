"""文本处理工具:JSON 清洗、截断、宽度估算、HTML→纯文本、编码探测。"""
import json
import re


def strip_json_fences(text: str) -> str:
    """剥掉 ```json ... ``` 代码围栏,返回围栏内的内容;无围栏时原样返回。"""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    return text.strip()


def extract_json_object(text: str) -> dict | None:
    """从文本中提取第一个 JSON 对象(容错:从首个 { 到匹配的最后一个 })。"""
    cleaned = strip_json_fences(text)
    start = cleaned.find("{")
    if start == -1:
        return None
    try:
        return json.loads(cleaned[start:])
    except json.JSONDecodeError:
        # 逐层回退:从右向左找最后一个 },尝试截取
        for end in (cleaned.rfind("}") + 1,):
            if end > start:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass
        return None


def safe_filename(name: str) -> str:
    """把任意文本清理为可用的文件名(去非法字符、限长)。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]', "_", (name or "").strip())
    return cleaned[:40] or "文件"


def truncate(s: str, max_len: int) -> str:
    """超长截断,加省略号。"""
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def cjk_width(s: str) -> int:
    """显示宽度:CJK 字符按 2 计,其余按 1 计(用于 Excel 列宽估算)。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in (s or ""))


def html_to_text(html: str) -> str:
    """HTML → 纯文本:去除 script/style 等标签,压缩空白。"""
    if not html:
        return ""
    try:
        from lxml import html as lxml_html

        doc = lxml_html.document_fromstring(html)
        for bad in doc.xpath("//script | //style | //noscript | //template"):
            bad.getparent().remove(bad)
        text = doc.text_content()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


_CHARSET_RE = re.compile(rb"charset=[\"']?([\w-]+)", re.IGNORECASE)


def decode_bytes(data: bytes) -> str:
    """按 BOM/声明/默认顺序探测编码,兼容 gbk/utf-8 站点。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    head = data[:2048]
    m = _CHARSET_RE.search(head)
    encodings = []
    if m:
        encodings.append(m.group(1).decode("ascii", errors="ignore"))
    encodings += ["utf-8", "gbk", "gb18030"]
    for enc in encodings:
        try:
            return data.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")
