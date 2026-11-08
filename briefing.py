#!/usr/bin/env python3
"""Generate a daily NYT markets briefing from the Top Stories API.

Examples:
    export NYT_API_KEY=...        # key must have the "Top Stories API" enabled
    ./briefing.py                                  # business section, to stdout
    ./briefing.py --section business technology    # merge two sections
    ./briefing.py --max-age 24 --limit 5          # last day, 5 per bucket
    ./briefing.py --format markdown --output briefing.md
    ./briefing.py --audio                          # --summary + audio/briefing_<date>.mp3
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from mb import __version__
from mb.categorize import group
from mb.nyt import NYTError, TopStoriesClient, parse_articles
from mb.render import render
from mb.rss import RSS_MAX_AGE_HOURS, RSSError
from mb.rss import collect as collect_rss
from mb.rss import render_section as render_rss_section


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
SUMMARY_MODEL = "claude-sonnet-5"

AUDIO_DIR = "audio"

SUMMARY_SYSTEM_PROMPT = """\
You are the writer and editor for a daily spoken-word markets briefing that a \
presenter reads aloud on air.

You are given the day's collected briefing: news stories drawn from several \
outlets (the New York Times, the Financial Times, and The Economist) and \
labeled by source. Where outlets cover the same event, treat that as \
corroboration rather than repeating it. Do the following:

1. Select only the stories with genuine relevance to financial markets, the \
economy, or global finance. Ignore pure human-interest, media or entertainment, \
personality, and tech-lifestyle or gadget stories, even when they appear in the \
briefing.

2. Write one connected summary of roughly 400 words that ties the selected \
stories to markets: what they imply for interest rates, equities and specific \
sectors, credit, commodities, currencies, and the broader economic outlook. \
Draw the connections explicitly rather than restating headlines.

3. Write it as spoken-word copy for a presenter to read aloud: flowing prose in \
complete sentences with natural transitions between topics. No bullet points, no \
headings, no markdown, no section labels, no source citations or URLs. Return \
only the script text.
"""


class SummaryError(Exception):
    """Raised when the Claude summarization request cannot be completed."""


class AudioError(Exception):
    """Raised when the text-to-speech conversion cannot be completed."""


def summarize_for_markets(
    briefing_text: str,
    *,
    model: str = SUMMARY_MODEL,
    timeout: float = 120.0,
) -> str:
    """Send the collected briefing to the Claude API and return a spoken-style
    markets summary. Auth comes from the ANTHROPIC_API_KEY environment variable.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SummaryError("ANTHROPIC_API_KEY is not set")

    body = json.dumps(
        {
            "model": model,
            "max_tokens": 4096,
            "system": SUMMARY_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": f"Here is today's collected briefing:\n\n{briefing_text}",
                }
            ],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise SummaryError(f"Claude API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SummaryError(f"could not reach the Claude API: {exc.reason}") from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise SummaryError(f"unexpected Claude API response: {exc}") from exc

    if payload.get("stop_reason") == "refusal":
        raise SummaryError("Claude declined to summarize this briefing")

    text = "\n".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    ).strip()
    if not text:
        raise SummaryError("Claude API returned no text content")
    return text


def build_briefing_text(nyt_output: str, *, now: datetime) -> str:
    """Combine the NYT briefing with the FT and Economist RSS feeds into one
    source-labeled text for :func:`summarize_for_markets`. RSS problems are
    non-fatal: they are reported to stderr and that source is left out or
    marked unavailable, so ``--summary`` / ``--audio`` keep working on the NYT
    material alone.
    """
    parts = [
        "=" * 60,
        "SOURCE: NYT TOP STORIES",
        "=" * 60,
        "",
        nyt_output.strip(),
        "",
    ]

    try:
        results = collect_rss(now, max_age_hours=RSS_MAX_AGE_HOURS)
    except RSSError as exc:
        print(f"warning: skipping RSS sources — {exc}", file=sys.stderr)
        results = []

    for result in results:
        if not result.items:
            print(
                f"warning: {result.label}: no RSS items in the last "
                f"{RSS_MAX_AGE_HOURS:g}h ({result.note})",
                file=sys.stderr,
            )
        elif result.note:
            print(f"note: {result.label}: {result.note}", file=sys.stderr)
        parts.append(render_rss_section(result, now=now))
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _say_to_mp3(text: str, path: str) -> bool:
    """Render ``text`` with the macOS ``say`` command and encode it to mp3 with
    ffmpeg or lame. Returns True on success, or False when ``say`` / an encoder
    is missing or the conversion fails. ``say`` cannot stream to a pipe, so it
    writes a temporary AIFF that the encoder then reads.
    """
    if not shutil.which("say"):
        return False
    encoder = shutil.which("ffmpeg") or shutil.which("lame")
    if not encoder:
        return False

    txt_fd, txt_path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(txt_fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    aiff_fd, aiff_path = tempfile.mkstemp(suffix=".aiff")
    os.close(aiff_fd)

    try:
        subprocess.run(
            ["say", "-f", txt_path, "-o", aiff_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if os.path.basename(encoder) == "ffmpeg":
            cmd = [encoder, "-y", "-i", aiff_path,
                   "-codec:a", "libmp3lame", "-qscale:a", "4", path]
        else:  # lame
            cmd = [encoder, "--silent", aiff_path, path]
        subprocess.run(
            cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    finally:
        for tmp in (txt_path, aiff_path):
            try:
                os.unlink(tmp)
            except OSError:
                pass

    return os.path.exists(path) and os.path.getsize(path) > 0


def _gtts_to_mp3(text: str, path: str) -> bool:
    """Fallback text-to-speech using gTTS (needs network). Returns True on
    success, or False when gTTS is not installed or the request fails.
    """
    try:
        from gtts import gTTS
    except ImportError:
        return False
    try:
        gTTS(text=text).save(path)
    except Exception:
        return False
    return os.path.exists(path) and os.path.getsize(path) > 0


def text_to_speech(
    summary_text: str,
    *,
    out_dir: str = AUDIO_DIR,
    now: datetime | None = None,
) -> str:
    """Convert the markets summary to speech and save it as
    ``<out_dir>/briefing_<YYYY-MM-DD>.mp3``. Prefers the macOS ``say`` command
    with an mp3 encoder (ffmpeg or lame); falls back to gTTS when ``say`` or an
    encoder is unavailable. Returns the path to the mp3.
    """
    if not (summary_text and summary_text.strip()):
        raise AudioError("no summary text to convert to speech")

    now = now or datetime.now(timezone.utc)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise AudioError(f"could not create {out_dir}: {exc.strerror or exc}") from exc

    path = os.path.join(out_dir, f"briefing_{now:%Y-%m-%d}.mp3")

    if _say_to_mp3(summary_text, path) or _gtts_to_mp3(summary_text, path):
        return path

    raise AudioError(
        "text-to-speech failed: need the macOS `say` command plus an mp3 "
        "encoder (ffmpeg or lame) on PATH, or install gTTS (pip install gTTS)"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="briefing.py",
        description="Daily NYT markets digest built on the Top Stories API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--section", "-s", nargs="+", default=["business"], metavar="NAME",
        help="Top Stories section(s) to pull (default: business).",
    )
    p.add_argument(
        "--format", "-f", choices=("text", "markdown"), default=None,
        help="Output format. Default: markdown when --output ends in .md, else text.",
    )
    p.add_argument(
        "--output", "-o", metavar="FILE",
        help="Write the briefing to FILE instead of stdout.",
    )
    p.add_argument(
        "--limit", "-n", type=int, default=6, metavar="N",
        help="Max stories per section, 0 for unlimited (default: 6).",
    )
    p.add_argument(
        "--max-age", type=float, default=None, metavar="HOURS",
        help="Drop stories older than HOURS (default: no age filter).",
    )
    p.add_argument(
        "--all", action="store_true",
        help="Shorthand for --limit 0 with no age filter.",
    )
    p.add_argument(
        "--summary", action="store_true",
        help="Also send the briefing to the Claude API (claude-sonnet-5) for a "
             "spoken-style markets summary, printed to the console. Needs "
             "ANTHROPIC_API_KEY.",
    )
    p.add_argument(
        "--audio", action="store_true",
        help="Run --summary, then convert the summary to speech and save it as "
             f"{AUDIO_DIR}/briefing_<date>.mp3 (macOS `say` + ffmpeg/lame, or "
             "gTTS as a fallback).",
    )
    p.add_argument(
        "--api-key", default=None,
        help="NYT API key (overrides the NYT_API_KEY environment variable).",
    )
    p.add_argument("--version", action="version", version=f"markets-briefing {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(timezone.utc)

    if args.audio:
        args.summary = True

    limit = 0 if args.all else max(0, args.limit)
    max_age = None if args.all else args.max_age

    fmt = args.format
    if fmt is None:
        fmt = "markdown" if (args.output or "").lower().endswith(".md") else "text"

    api_key = args.api_key or os.environ.get("NYT_API_KEY")

    try:
        client = TopStoriesClient(api_key)
        articles = []
        seen: set[str] = set()
        last_updated: datetime | None = None
        for section in args.section:
            payload = client.fetch(section)
            lu = payload.get("last_updated")
            if lu:
                try:
                    dt = datetime.fromisoformat(lu.replace("Z", "+00:00"))
                    last_updated = max(last_updated, dt) if last_updated else dt
                except ValueError:
                    pass
            for art in parse_articles(payload):
                key = art.url or art.title
                if key in seen:
                    continue
                seen.add(key)
                articles.append(art)
    except NYTError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    total_fetched = len(articles)

    if max_age is not None:
        cutoff = now - timedelta(hours=max_age)
        articles = [a for a in articles if a.published and a.published >= cutoff]

    groups = group(articles)

    if limit:
        groups = type(groups)(
            (name, items[:limit]) for name, items in groups.items()
        )

    shown = sum(len(v) for v in groups.values())
    lu_txt = f"{last_updated:%Y-%m-%d %H:%M} (UTC{last_updated:%z})" if last_updated else "unknown"
    source_line = (
        f"Source: NYT Top Stories ({', '.join(args.section)}) · "
        f"updated {lu_txt} · {shown} of {total_fetched} stories"
    )
    if max_age is not None:
        source_line += f" · last {max_age:g}h"

    output = render(groups, {"source_line": source_line}, fmt=fmt, now=now)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(output)
        except OSError as exc:
            print(f"error: could not write {args.output}: {exc.strerror or exc}", file=sys.stderr)
            return 2
        print(f"wrote {shown} stories to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    summary: str | None = None
    if args.summary:
        briefing_text = build_briefing_text(output, now=now)
        try:
            summary = summarize_for_markets(briefing_text)
        except SummaryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("\n" + "=" * 60)
        print("MARKETS SUMMARY (claude-sonnet-5)")
        print("=" * 60)
        print(summary)

    if args.audio:
        try:
            audio_path = text_to_speech(summary or "", now=now)
        except AudioError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"wrote audio to {audio_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
