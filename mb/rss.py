"""Supplementary RSS sources for the briefing: the Financial Times and The
Economist, fetched with ``feedparser``.

The base tool is stdlib-only; ``feedparser`` is imported lazily so importing
this module never hard-fails. Call sites get an :class:`RSSError` when the
dependency is missing and can carry on with just the NYT material.

Feeds:

* Financial Times -- https://www.ft.com/rss/home
* The Economist   -- "The World in Brief" daily digest, falling back to the
                    markets-focused "Finance & economics" feed when the digest
                    feed is unavailable (it is bot-gated and often returns 403).

Items are filtered to the last ~24 hours with the same rule the NYT path uses:
an item is kept only when it has a parseable timestamp inside the window;
undated items are dropped.
"""

from __future__ import annotations

import calendar
import html
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

RSS_MAX_AGE_HOURS = 24.0

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# Source label -> feed URLs tried in order; the first that yields items wins.
SOURCE_FEEDS: "dict[str, tuple[str, ...]]" = {
    "Financial Times (FT)": (
        "https://www.ft.com/rss/home",
    ),
    "The Economist": (
        "https://www.economist.com/the-world-in-brief/rss.xml",
        "https://www.economist.com/finance-and-economics/rss.xml",
    ),
}


class RSSError(RuntimeError):
    """Raised when the optional ``feedparser`` dependency is not installed."""


@dataclass(frozen=True)
class FeedItem:
    source: str
    title: str
    summary: str
    link: str
    published: datetime | None


@dataclass(frozen=True)
class SourceResult:
    label: str
    feed_url: str | None          # URL that actually produced the items
    items: "list[FeedItem]"
    note: str | None              # fallback / failure detail, if any


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """Strip HTML tags and collapse whitespace in a feed title/summary."""
    return _WS_RE.sub(" ", _TAG_RE.sub("", html.unescape(text or ""))).strip()


def _entry_dt(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    return None


def _fetch(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "application/rss+xml, application/atom+xml, "
                      "application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse(raw: bytes, label: str) -> "list[FeedItem]":
    import feedparser  # lazy: keeps the base tool import stdlib-only

    parsed = feedparser.parse(raw)
    items: list[FeedItem] = []
    for entry in parsed.entries:
        items.append(
            FeedItem(
                source=label,
                title=_clean(entry.get("title", "")),
                summary=_clean(entry.get("summary", "")),
                link=(entry.get("link") or "").strip(),
                published=_entry_dt(entry),
            )
        )
    return items


def fetch_source(
    label: str,
    urls: "tuple[str, ...]",
    *,
    timeout: float = 20.0,
) -> SourceResult:
    """Try each feed URL in order and return the first that yields any items."""
    try:
        import feedparser  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on env
        raise RSSError("feedparser is not installed (pip install feedparser)") from exc

    errors: list[str] = []
    for i, url in enumerate(urls):
        try:
            items = _parse(_fetch(url, timeout), label)
        except urllib.error.HTTPError as exc:
            errors.append(f"{url}: HTTP {exc.code}")
            continue
        except (urllib.error.URLError, OSError) as exc:
            errors.append(f"{url}: {getattr(exc, 'reason', exc)}")
            continue
        if not items:
            errors.append(f"{url}: no entries")
            continue
        note = None
        if i > 0:
            note = "primary feed unavailable (" + "; ".join(errors) + f") — used {url}"
        return SourceResult(label, url, items, note)

    return SourceResult(label, None, [], "; ".join(errors) or "no feeds configured")


def recent(
    items: "list[FeedItem]",
    *,
    now: datetime,
    max_age_hours: float = RSS_MAX_AGE_HOURS,
) -> "list[FeedItem]":
    """Filter to the last ``max_age_hours`` — same logic as the NYT ``--max-age``
    path: drop undated items and anything older than the cutoff, newest first.
    """
    cutoff = now - timedelta(hours=max_age_hours)
    kept = [it for it in items if it.published and it.published >= cutoff]
    kept.sort(key=lambda it: it.published, reverse=True)
    return kept


def collect(
    now: datetime,
    *,
    max_age_hours: float = RSS_MAX_AGE_HOURS,
    timeout: float = 20.0,
) -> "list[SourceResult]":
    """Fetch every configured source and age-filter its items. Raises
    :class:`RSSError` if ``feedparser`` is missing.
    """
    out: list[SourceResult] = []
    for label, urls in SOURCE_FEEDS.items():
        res = fetch_source(label, urls, timeout=timeout)
        out.append(
            SourceResult(
                res.label,
                res.feed_url,
                recent(res.items, now=now, max_age_hours=max_age_hours),
                res.note,
            )
        )
    return out


def render_section(
    result: SourceResult,
    *,
    now: datetime,
    max_age_hours: float = RSS_MAX_AGE_HOURS,
) -> str:
    """Render one source as a labeled plain-text block for the combined
    briefing text handed to the summarizer.
    """
    from .render import humanize_age  # reuse the NYT age formatter

    lines = [
        "=" * 60,
        f"SOURCE: {result.label.upper()} — RSS, last {max_age_hours:g}h",
        "=" * 60,
    ]
    if result.feed_url:
        lines.append(f"feed: {result.feed_url}")
    if result.note:
        lines.append(f"note: {result.note}")
    lines.append("")

    if not result.items:
        lines.append("No items in the last 24 hours.")
        return "\n".join(lines) + "\n"

    for it in result.items:
        lines.append(f"  • {it.title}")
        if it.summary:
            lines.append(f"    {it.summary}")
        stamp = f"{it.published:%Y-%m-%d %H:%M UTC}" if it.published else ""
        age = humanize_age(it.published, now)
        meta = " · ".join(b for b in (stamp, age) if b)
        if meta:
            lines.append(f"    {meta}")
        if it.link:
            lines.append(f"    {it.link}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
