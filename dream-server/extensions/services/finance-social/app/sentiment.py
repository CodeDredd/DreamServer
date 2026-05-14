"""LLM-based sentiment / urgency tagging for Reddit posts.

Same pattern as finance-news/sentiment.py — LiteLLM `fast` alias
(qwen3-4b), batched, graceful failure leaves rows unscored rather than
dropping them.

The prompt differs slightly from news: Reddit posts can be sarcastic,
so we explicitly tell the model to score the post's MARKET POSITION
(would it cause a buy or a sell), not its tone.
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

log = logging.getLogger("finance-social.sentiment")


@dataclass
class LlmConfig:
    enabled: bool = field(default_factory=lambda: os.getenv("FINANCE_SOCIAL_USE_LLM", "true").lower() == "true")
    base_url: str = field(default_factory=lambda: os.getenv("LITELLM_URL", "http://litellm:4000/v1"))
    api_key: str | None = field(default_factory=lambda: os.getenv("LITELLM_API_KEY") or None)
    model: str = field(default_factory=lambda: os.getenv("FINANCE_SOCIAL_LLM_MODEL", "fast"))
    batch: int = field(default_factory=lambda: int(os.getenv("FINANCE_SOCIAL_LLM_BATCH", "16")))
    timeout: int = 60


SYSTEM_PROMPT = (
    "You are a finance social-media classifier. For each numbered Reddit post "
    "you receive, return one JSON object on a single line with fields:\n"
    '  {"i": <number>, "sentiment": <float -1..+1>, "urgency": <float 0..1>}\n'
    "sentiment: how would the AVERAGE retail trader trade after reading this? "
    "-1 = strongly bearish (sell), 0 = neutral / unclear, +1 = strongly bullish (buy). "
    "Score the implied market position, not the tone — sarcasm and memes count.\n"
    "urgency:    0 = chitchat / low conviction, 1 = breaking event / DD with strong call.\n"
    "Return ONLY the JSON lines, no commentary, one per post, in order."
)


def _build_user_prompt(items: Sequence[dict]) -> str:
    lines = []
    for i, ev in enumerate(items):
        title = (ev.get("title") or "").replace("\n", " ").strip()
        # Include a tiny bit of the body when present — Reddit titles
        # are often clickbaity, the first sentence of selftext gives
        # the model real signal. Keep it short to control token cost.
        body = (ev.get("payload") or {}).get("selftext") or ""
        body = body.replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"
        syms = ev.get("symbols") or []
        sym_hint = f" [{', '.join(syms[:5])}]" if syms else ""
        chan = ev.get("channel") or ""
        line = f"{i}. ({chan}){sym_hint} {title}"
        if body:
            line += f" — {body}"
        lines.append(line)
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

    Items already scored are skipped (idempotent on re-runs)."""
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

