"""DeepSeek LLM 调用封装(OpenAI SDK)。

json_call 三重防线:剥 Markdown 围栏 → Pydantic 校验 → 带错误信息重试。
所有结构化产出(需求提取/合并/定稿/文件 IR)必须走 json_call。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from pydantic import BaseModel

from app.config import settings
from app.utils.text import extract_json_object

logger = logging.getLogger(__name__)

_clients: dict[str, object] = {}


class LLMError(Exception):
    """对用户友好的 LLM 调用错误。"""


def get_client(api_key: str | None = None):
    """按 API Key 缓存 OpenAI 客户端。

    优先使用调用方传入的 key(使用者自己的 DeepSeek Key);
    未提供时回退到服务器 .env 配置的 key。两者都没有则报友好错误。
    """
    from openai import OpenAI

    key = (api_key or settings.deepseek_api_key or "").strip()
    if not key or key.startswith("sk-请填入"):
        raise LLMError("未配置 API Key:请点击左侧「设置 Key」输入您的 DeepSeek API Key")
    if key not in _clients:
        _clients[key] = OpenAI(
            api_key=key,
            base_url=settings.deepseek_base_url,
            timeout=90.0,
            max_retries=1,
        )
    return _clients[key]


def _friendly(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc)
    if "APIStatusError" in name or "status" in text.lower():
        return "接口返回异常"
    if "Connect" in name or "Timeout" in name or "APIConnection" in name:
        return "网络连接失败,请检查网络"
    if "Authentication" in name or "401" in text:
        return "API Key 无效"
    return f"{name}:{text[:120]}"


# ------------------------------------------------------------------- 聊天调用

def chat_stream(system: str, messages: list[dict], temperature: float = 0.7,
                api_key: str | None = None) -> Iterator[str]:
    """流式聊天,逐段产出文本 delta。"""
    try:
        client = get_client(api_key)
        full = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=full,
            stream=True,
            temperature=temperature,
        )
        for chunk in resp:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"模型服务调用失败:{_friendly(exc)}") from exc


def chat_once(system: str, messages: list[dict], temperature: float = 0.7,
              max_tokens: int = 2048, api_key: str | None = None) -> str:
    """非流式聊天,返回完整文本。"""
    try:
        client = get_client(api_key)
        full = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=full,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"模型服务调用失败:{_friendly(exc)}") from exc


# ------------------------------------------------------------------ 结构化调用

def json_call(system: str, user: str, *, temperature: float = 0.2,
              max_tokens: int = 4096, schema: type[BaseModel] | None = None,
              retries: int = 2, api_key: str | None = None) -> dict[str, Any] | BaseModel:
    """调用 LLM 输出单个 JSON 对象。

    提供 schema 时:校验通过返回模型实例,校验失败带错误信息重试;
    不提供 schema 时:返回原始 dict。失败重试时温度降至 0.1。
    """
    client = get_client(api_key)
    err_note = ""
    for attempt in range(retries + 1):
        prompt = user + err_note
        try:
            resp = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": prompt}],
                temperature=temperature if attempt == 0 else 0.1,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            # 部分网关不支持 response_format,降级为普通调用
            if attempt == 0 and "response_format" in str(exc):
                try:
                    resp = client.chat.completions.create(
                        model=settings.deepseek_model,
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": prompt}],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as exc2:
                    raise LLMError(f"模型服务调用失败:{_friendly(exc2)}") from exc2
            else:
                raise LLMError(f"模型服务调用失败:{_friendly(exc)}") from exc

        raw = resp.choices[0].message.content or ""
        data = extract_json_object(raw)
        if data is None:
            err_note = f"\n\n【注意】你上一次的输出不是合法 JSON(无法解析),请只输出一个 JSON 对象,不要输出任何解释文字。上一次输出片段:{raw[:200]}"
            logger.warning("json_call: 输出无法解析,第 %s 次重试", attempt + 1)
            continue

        if schema is not None:
            try:
                return schema.model_validate(data)
            except Exception as ve:
                err_note = f"\n\n【注意】你上一次的输出未通过校验,错误如下:\n{str(ve)[:500]}\n请修正字段后重新输出完整 JSON 对象。"
                logger.warning("json_call: 校验失败,第 %s 次重试", attempt + 1)
                continue
        return data

    raise LLMError("模型多次输出无效内容,请稍后重试")
