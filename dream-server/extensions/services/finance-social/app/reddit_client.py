"""Reddit fetcher (PRAW, read-only).

PRAW handles OAuth, retries, and rate-limiting automatically. Free
tier with a registered "script" app gives ~100 QPM authenticated which
is more than enough for our 15-minute cadence pulling new() from a
handful of subreddits.

If the credentials are missing or invalid the module surfaces
configured=False so the orchestrator can short-circuit without
crashing — that's the same posture as finance-news for empty feeds.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
from dataclasses import dataclass, field

import praw
import prawcore

log = logging.getLogger("finance-social.reddit")

# Curated default subreddit list. Heavy bias toward tickers + crypto;
# the pure-DD subs (SecurityAnalysis) are quieter but the signal is
# usually higher quality.
DEFAULT_SUBREDDITS: list[str] = [
    "wallstreetbets",
    "stocks",
    "investing",
    "StockMarket",
    "CryptoCurrency",
    "SecurityAnalysis",
]


@dataclass
class RedditConfig:
    client_id:     str = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_ID", "").strip())
    client_secret: str = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_SECRET", "").strip())
    user_agent:    str = field(default_factory=lambda: os.getenv(
        "REDDIT_USER_AGENT",
        "DreamServer-FinanceSocial/0.1 (by u/anonymous)",
    ).strip())
    min_score: int = field(default_factory=lambda: int(os.getenv("FINANCE_SOCIAL_MIN_SCORE", "1")))

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def configured_subreddits() -> list[str]:
    raw = os.getenv("FINANCE_SOCIAL_SUBREDDITS", "").strip()
    if not raw:
        return list(DEFAULT_SUBREDDITS)
    return [s.strip().lstrip("r/").lstrip("/") for s in raw.split(",") if s.strip()]


_client: praw.Reddit | None = None


def get_client(cfg: RedditConfig) -> praw.Reddit | None:
    global _client
    if not cfg.configured:
        return None
    if _client is None:
        _client = praw.Reddit(
            client_id=cfg.client_id,
            client_secret=cfg.client_secret,
            user_agent=cfg.user_agent,
            check_for_async=False,
            ratelimit_seconds=10,
        )
        # Read-only mode is the default when no username/password is
        # passed. Force-set so PRAW does not try a user-flow refresh.
        _client.read_only = True
        log.info("Reddit client initialised (read-only)")
    return _client


def _stable_id(sub: str, post_id: str) -> str:
    return hashlib.sha1(f"reddit\n{sub}\n{post_id}".encode("utf-8")).hexdigest()


def fetch_subreddit(cfg: RedditConfig, sub: str, max_items: int) -> list[dict]:
    """Fetch the latest `max_items` posts from /r/<sub>.

    Returns normalized event dicts (no symbols / sentiment yet — the
    orchestrator fills those after the fetch).
    """
    client = get_client(cfg)
    if client is None:
        return []

    out: list[dict] = []
    try:
        subreddit = client.subreddit(sub)
        for post in subreddit.new(limit=max_items):
            score = int(getattr(post, "score", 0) or 0)
            if score < cfg.min_score:
                continue
            created = float(getattr(post, "created_utc", 0) or 0)
            ts = (
                dt.datetime.fromtimestamp(created, dt.timezone.utc)
                if created
                else dt.datetime.now(dt.timezone.utc)
            )
            title = (getattr(post, "title", "") or "").strip()
            selftext = (getattr(post, "selftext", "") or "").strip()
            if len(selftext) > 1500:
                selftext = selftext[:1500] + "…"
            url = getattr(post, "url", None) or f"https://reddit.com{getattr(post, 'permalink', '')}"
            author = None
            try:
                a = post.author
                if a is not None:
                    author = str(a)
            except Exception:  # noqa: BLE001
                author = None

            out.append({
                "id":           _stable_id(sub, post.id),
                "ts":           ts,
                "source":       "reddit",
                "channel":      f"r/{sub}",
                "author":       author,
                "score":        score,
                "num_comments": int(getattr(post, "num_comments", 0) or 0),
                "title":        title,
                "url":          url,
                "payload": {
                    "post_id":   post.id,
                    "permalink": getattr(post, "permalink", None),
                    "selftext":  selftext,
                    "subreddit": sub,
                    "flair":     getattr(post, "link_flair_text", None),
                    "is_self":   bool(getattr(post, "is_self", False)),
                    "over_18":   bool(getattr(post, "over_18", False)),
                    "domain":    getattr(post, "domain", None),
                },
            })
    except prawcore.exceptions.ResponseException as exc:
        # 401/403 = bad creds. Surface, don't crash.
        log.warning("subreddit %s response error: %s", sub, exc)
        return []
    except prawcore.exceptions.RequestException as exc:
        log.warning("subreddit %s request error: %s", sub, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning("subreddit %s unexpected error: %s", sub, exc)
        return []

    return out

