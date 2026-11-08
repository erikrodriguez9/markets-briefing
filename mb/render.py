"""Render grouped articles as a plain-text or Markdown briefing."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from .nyt import Article


def humanize_age(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return ""
    seconds = (now - dt).total_seconds()
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    return f"{int(days)}d ago"


def _byline_line(article: Article, now: datetime) -> str:
    byline = article.byline or ""
    if byline.lower().startswith("by "):
        byline = byline[3:]
    age = humanize_age(article.published, now)
    bits = [b for b in (byline, age) if b]
    return " · ".join(bits)


def render_text(
    groups: "OrderedDict[str, list[Article]]",
    meta: dict,
    *,
    now: datetime,
) -> str:
    lines: list[str] = []
    title = f"NYT MARKETS BRIEFING — {now:%A, %B %-d, %Y}"
    lines.append(title)
    lines.append("=" * len(title))
    lines.append(meta["source_line"])
    lines.append("")

    if not groups:
        lines.append("No stories matched the current filters.")
        return "\n".join(lines) + "\n"

    for section, items in groups.items():
        lines.append(section.upper())
        lines.append("-" * len(section))
        for art in items:
            lines.append(f"  • {art.title}")
            if art.abstract:
                lines.append(f"    {art.abstract}")
            meta_line = _byline_line(art, now)
            if meta_line:
                lines.append(f"    {meta_line}")
            if art.url:
                lines.append(f"    {art.url}")
            lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_markdown(
    groups: "OrderedDict[str, list[Article]]",
    meta: dict,
    *,
    now: datetime,
) -> str:
    lines: list[str] = []
    lines.append(f"# NYT Markets Briefing — {now:%A, %B %-d, %Y}")
    lines.append("")
    lines.append(f"_{meta['source_line']}_")
    lines.append("")

    if not groups:
        lines.append("No stories matched the current filters.")
        return "\n".join(lines) + "\n"

    for section, items in groups.items():
        lines.append(f"## {section}")
        lines.append("")
        for art in items:
            link = f"[{art.title}]({art.url})" if art.url else art.title
            lines.append(f"- **{link}**")
            if art.abstract:
                lines.append(f"  {art.abstract}")
            meta_line = _byline_line(art, now)
            if meta_line:
                lines.append(f"  _{meta_line}_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render(groups, meta, *, fmt: str, now: datetime) -> str:
    if fmt == "markdown":
        return render_markdown(groups, meta, now=now)
    return render_text(groups, meta, now=now)
