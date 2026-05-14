"""Thin LiteLLM client wrapper.

Strategies that need an LLM call (currently only news_sentiment for
batched reasoning) go through here so model alias + auth + retry
behaviour stay consistent across the codebase.

Per AGENT-OPERATIONS.md §10:
  * Use the routing alias ('fast', 'default', 'reasoning'), NEVER
    the underlying Lemonade model name.
  * The bridge `LITELLM_API_KEY=${LITELLM_KEY:-}` is set in compose.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import CFG

log = logging.getLogger("finance-guru.llm")


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=8), reraise=True)
def chat(messages: list[dict], *, model: str | None = None,
         max_tokens: int = 256, temperature: float = 0.0) -> str:
    """Returns the assistant message content as a string. Raises on
    transport / HTTP errors after 2 attempts."""
    headers = {"Content-Type": "application/json"}
    if CFG.llm_api_key:
        headers["Authorization"] = f"Bearer {CFG.llm_api_key}"
    payload = {
        "model": model or CFG.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(f"{CFG.llm_url.rstrip('/')}/chat/completions",
                      json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def chat_json(messages: list[dict], **kwargs) -> Any:
    """Like chat() but extracts the first JSON value (object or array)
    from the response — qwen3-4b sometimes wraps in ``` fences or
    appends commentary."""
    raw = chat(messages, **kwargs)
    # Try a strict parse first.
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Fall back to the first {...} or [...] blob.
    m = re.search(r"(\[.*\]|\{.*\})", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in LLM reply: {raw[:200]!r}")
    return json.loads(m.group(1))

