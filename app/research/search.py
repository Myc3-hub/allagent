"""公开搜索页抓取(尽力而为):解析必应搜索结果页 HTML,失败优雅降级。

不依赖任何第三方搜索 API;页面改版或反爬导致解析失败时返回空列表,
由上层记录"未能获取公开数据"而不报错。
"""
from __future__ import annotations

import logging

import httpx
from lxml import html as lxml_html

from app.config import settings
from app.utils.text import decode_bytes

logger = logging.getLogger(__name__)

SEARCH_URL = "https://cn.bing.com/search?q={q}&count=10&setlang=zh-CN"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}


def web_search(query: str, limit: int = 8) -> list[dict]:
    """必应 + 搜狗 + 百度三源搜索(尽力而为),合并去重。任何异常都不抛出。"""
    results: dict[str, dict] = {}
    for item in _bing_search(query, limit) + _sogou_search(query, limit) + _baidu_search(query, limit):
        results.setdefault(item["url"], item)
    return list(results.values())[:limit * 2]


def _sogou_search(query: str, limit: int = 8) -> list[dict]:
    """搜狗搜索结果:跳转链接跟随重定向解析真实 URL。"""
    try:
        with httpx.Client(follow_redirects=True, timeout=settings.fetch_timeout,
                          headers=_HEADERS) as client:
            resp = client.get(f"https://www.sogou.com/web?query={query}")
        if resp.status_code != 200:
            return []
        doc = lxml_html.document_fromstring(decode_bytes(resp.content))
        results = []
        for h3 in doc.xpath("//h3[contains(@class,'vr-title') or contains(@class,'vrTitle')]"):
            a = h3.xpath(".//a")
            if not a:
                continue
            href = (a[0].get("href") or "").strip()
            if not href.startswith("http"):
                continue
            title = "".join(a[0].itertext()).strip()
            real = href
            if "/link?url=" in href or "sogou.com/link" in href:
                try:
                    with client.stream("GET", href) as r2:
                        next(r2.iter_bytes(1), b"")
                        real = str(r2.url)
                except Exception:
                    pass
            if not real.startswith("http") or "sogou.com" in real:
                continue
            results.append({"title": title, "url": real, "snippet": ""})
            if len(results) >= limit:
                break
        return results
    except Exception as exc:
        logger.warning("搜狗搜索失败(%s):%s", query, exc)
        return []


def _bing_search(query: str, limit: int = 8) -> list[dict]:
    try:
        with httpx.Client(follow_redirects=True, timeout=settings.fetch_timeout,
                          headers=_HEADERS) as client:
            resp = client.get(SEARCH_URL.format(q=query))
        if resp.status_code != 200:
            logger.warning("必应搜索返回 %s", resp.status_code)
            return []
        return _parse_bing(decode_bytes(resp.content), limit)
    except Exception as exc:
        logger.warning("必应搜索失败(%s):%s", query, exc)
        return []


def _baidu_search(query: str, limit: int = 8) -> list[dict]:
    """百度搜索结果(备用源):跳转链接跟随重定向解析真实 URL。"""
    try:
        with httpx.Client(follow_redirects=True, timeout=settings.fetch_timeout,
                          headers=_HEADERS) as client:
            resp = client.get(f"https://www.baidu.com/s?wd={query}&rn=20")
        if resp.status_code != 200:
            return []
        doc = lxml_html.document_fromstring(decode_bytes(resp.content))
        results = []
        for h3 in doc.xpath("//h3[contains(@class,'t') or contains(@class,'c-title')]"):
            a = h3.xpath(".//a")
            if not a:
                continue
            href = (a[0].get("href") or "").strip()
            if not href.startswith("http"):
                continue
            title = "".join(a[0].itertext()).strip()
            real = href
            if "baidu.com/link" in href:
                try:
                    with client.stream("GET", href) as r2:
                        next(r2.iter_bytes(1), b"")
                        real = str(r2.url)
                except Exception:
                    pass
            if not real.startswith("http") or "baidu.com" in real:
                continue
            results.append({"title": title, "url": real, "snippet": ""})
            if len(results) >= limit:
                break
        return results
    except Exception as exc:
        logger.warning("百度搜索失败(%s):%s", query, exc)
        return []


def _parse_bing(html_text: str, limit: int) -> list[dict]:
    doc = lxml_html.document_fromstring(html_text)
    results = []
    for li in doc.xpath('//li[contains(@class,"b_algo")]'):
        a = li.xpath(".//h2/a")
        if not a:
            continue
        url = (a[0].get("href") or "").strip()
        if not url.startswith("http") or "bing.com" in url or "microsoft.com" in url:
            continue
        title = "".join(a[0].itertext()).strip()
        snippet_nodes = li.xpath(".//p")
        snippet = " ".join("".join(p.itertext()) for p in snippet_nodes[:1]).strip()
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results
