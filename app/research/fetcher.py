"""公开网页抓取:浏览器 UA、超时、大小上限、编码自适应、HTML→纯文本。"""
from __future__ import annotations

import logging
import re

import httpx

from app.config import settings
from app.utils.text import decode_bytes, html_to_text

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}
_TITLE_RE = re.compile(r"<title[^>]*>([^<]{0,120})", re.IGNORECASE)

PAGE_TEXT_LIMIT = 8000  # 每页交给 LLM 的正文长度上限


def fetch_page(url: str) -> dict | None:
    """抓取一个公开页面,返回 {url, title, text};失败返回 None(不抛出)。

    SSL 证书校验失败时降级为不校验重试一次(部分机器证书环境异常,
    抓取的均为公开页面,可接受;商业部署可换正式搜索/抓取服务)。
    """
    for verify in (True, False):
        try:
            with httpx.Client(follow_redirects=True, timeout=settings.fetch_timeout,
                              headers=_HEADERS, verify=verify) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        return None
                    ctype = resp.headers.get("content-type") or ""
                    if "html" not in ctype and "text" not in ctype:
                        return None
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= settings.fetch_max_bytes:
                            break
                    final_url = str(resp.url)
                    data = b"".join(chunks)
            text = decode_bytes(data)
            title_match = _TITLE_RE.search(text)
            title = title_match.group(1).strip() if title_match else ""
            plain = html_to_text(text)[:PAGE_TEXT_LIMIT]
            if len(plain) < 100:
                return None
            return {"url": final_url, "title": title, "text": plain}
        except Exception as exc:
            if verify and "SSL" in str(exc):
                continue  # 证书环境异常,降级重试
            logger.info("抓取失败 %s: %s", url, exc)
            return None
    return None
