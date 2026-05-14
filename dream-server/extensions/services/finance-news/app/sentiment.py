"""LLM-based sentiment / urgency tagging via LiteLLM (qwen3-4b).

Per AGENT-OPERATIONS.md §10:
  qwen3-4b is the warm-loaded fast model; classifying ~50 headlines
  per cycle with it is essentially free vs. waking up the 35B/122B.

Per AGENT-OPERATIONS.md §11 the dataset:
  sentiment ∈ [-1.0, +1.0]   (negative -> bearish, positive -> bullish)
  urgency   ∈ [ 0.0,  1.0]   (rumour vs. confirmed material event)

The function is graceful: if LiteLLM is unreachable or returns garbage,
it returns `None` for both fields and the row goes in unscored. The
news-event row in TimescaleDB / Qdrant is *always* written — we never
drop a headline because the LLM tripped.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Sequence

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-news.sentiment")


@dataclass
class LlmConfig:
    enabled: bool = field(default_factory=lambda: os.getenv("FINANCE_NEWS_USE_LLM", "true").lower() == "true")
    base_url: str = field(default_factory=lambda: os.getenv("LITELLM_URL", "http://litellm:4000/v1"))
    api_key: str | None = field(default_factory=lambda: os.getenv("LITELLM_API_KEY") or None)
    model: str = field(default_factory=lambda: os.getenv("FINANCE_NEWS_LLM_MODEL", "qwen3-4b"))
    batch: int = field(default_factory=lambda: int(os.getenv("FINANCE_NEWS_LLM_BATCH", "16")))
    timeout: int = 60


SYSTEM_PROMPT = (
    "You are a financial news classifier. For each numbered headline you receive, "
    "return one JSON object on a single line with fields:\n"
    '  {"i": <number>, "sentiment": <float -1..+1>, "urgency": <float 0..1>}\n'
    "sentiment: -1 = strongly bearish, 0 = neutral, +1 = strongly bullish.\n"
    "urgency:    0 = background/opinion, 1 = breaking material event.\n"
    "Return ONLY the JSON lines, no commentary, one per headline, in order."
)


def _build_user_prompt(items: Sequence[dict]) -> str:
    lines = []
    for i, ev in enumerate(items):
        title = (ev.get("title") or "").replace("\n", " ").strip()
        syms = ev.get("symbols") or []
        sym_hint = f" [{', '.join(syms[:5])}]" if syms else ""
        lines.append(f"{i}. {title}{sym_hint}")
    return "\n".join(lines)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=8),
       reraise=True)
def _call_litellm(cfg: LlmConfig, items: Sequence[dict]) -> list[dict]:
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(items)},
        ],
        "temperature": 0.0,
        "max_tokens": 64 * len(items),
    }
    r = requests.post(f"{cfg.base_url.rstrip('/')}/chat/completions",
                      json=payload, headers=headers, timeout=cfg.timeout)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]

    # Parse JSON lines tolerantly — qwen3-4b sometimes wraps in fences
    # or adds blank lines; we look for {…} blobs.
    out: list[dict] = []
    for m in re.finditer(r"\{[^{}]*\}", content):
        try:
            obj = json.loads(m.group(0))
        except Exception:
            continue
        if "i" in obj:
            out.append(obj)
    return out


def classify(items: list[dict], cfg: LlmConfig | None = None) -> None:
    """Mutates `items` in-place, adding 'sentiment' and 'urgency'.

    Items that already have sentiment != None are skipped (idempotent
    on re-runs)."""
    cfg = cfg or LlmConfig()
    if not cfg.enabled or not items:
        return

    todo = [ev for ev in items if ev.get("sentiment") is None]
    if not todo:
        return

    for batch_start in range(0, len(todo), cfg.batch):
        batch = todo[batch_start: batch_start + cfg.batch]
        try:
            results = _call_litellm(cfg, batch)
        except Exception as exc:  # noqa: BLE001
            log.warning("LiteLLM classification failed (%d items): %s — leaving unscored",
                        len(batch), exc)
            continue
        by_idx = {int(r["i"]): r for r in results if "i" in r}
        for i, ev in enumerate(batch):
            r = by_idx.get(i)
            if not r:
                continue
            try:
                s = float(r.get("sentiment"))
                u = float(r.get("urgency"))
            except (TypeError, ValueError):
                continue
            ev["sentiment"] = max(-1.0, min(1.0, s))
            ev["urgency"]   = max(0.0,  min(1.0, u))

