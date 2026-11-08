"""Thin client for the NYT Top Stories API plus article normalization.

Only the Top Stories API is used, because that is the endpoint the project's
API key is provisioned for. Stdlib only -- no third-party dependencies.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

API_ROOT = "https://api.nytimes.com/svc/topstories/v2"

# Sections accepted by the Top Stories API.
VALID_SECTIONS = frozenset({
    "arts", "automobiles", "books", "business", "fashion", "food", "health",
    "home", "insider", "magazine", "movies", "nyregion", "obituaries",
    "opinion", "politics", "realestate", "science", "sports", "sundayreview",
    "technology", "theater", "t-magazine", "travel", "upshot", "us", "world",
})


class NYTError(RuntimeError):
    """Any failure talking to (or interpreting) the NYT API."""


@dataclass(frozen=True)
class Article:
    title: str
    abstract: str
    byline: str
    url: str
    section: str
    subsection: str
    published: datetime | None
    facets: tuple[str, ...] = field(default_factory=tuple)

    @property
    def haystack(self) -> str:
        """Lowercased text used for keyword categorization."""
        return f"{self.title}\n{self.abstract}\n{' / '.join(self.facets)}".lower()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_articles(payload: dict) -> list[Article]:
    out: list[Article] = []
    for raw in payload.get("results", []):
        if raw.get("item_type") and raw["item_type"].lower() != "article":
            continue
        out.append(Article(
            title=(raw.get("title") or "").strip(),
            abstract=(raw.get("abstract") or "").strip(),
            byline=(raw.get("byline") or "").strip(),
            url=raw.get("url") or raw.get("short_url") or "",
            section=(raw.get("section") or "").strip(),
            subsection=(raw.get("subsection") or "").strip(),
            published=_parse_dt(raw.get("published_date")),
            facets=tuple(raw.get("des_facet") or ()),
        ))
    return out


class TopStoriesClient:
    def __init__(self, api_key: str | None, *, timeout: float = 20.0):
        if not api_key:
            raise NYTError(
                "No NYT API key. Set the NYT_API_KEY environment variable or "
                "pass --api-key. Create a key at https://developer.nytimes.com/ "
                "and enable the 'Top Stories API' for your app."
            )
        self.api_key = api_key
        self.timeout = timeout

    def fetch(self, section: str) -> dict:
        section = section.lower().strip()
        if section not in VALID_SECTIONS:
            raise NYTError(
                f"Unknown section {section!r}. Valid sections: "
                + ", ".join(sorted(VALID_SECTIONS))
            )
        url = f"{API_ROOT}/{section}.json?" + urllib.parse.urlencode({"api-key": self.api_key})
        req = urllib.request.Request(url, headers={"User-Agent": "markets-briefing/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read(500).decode("utf-8", "replace")
            if exc.code in (401, 403):
                raise NYTError(
                    f"NYT rejected the API key (HTTP {exc.code}). Confirm the "
                    f"'Top Stories API' is enabled for your app. Response: {body}"
                ) from exc
            if exc.code == 429:
                raise NYTError(
                    "NYT rate limit hit (HTTP 429). The free tier allows ~5 "
                    "requests/minute; wait a moment and retry."
                ) from exc
            raise NYTError(f"NYT request failed (HTTP {exc.code}): {body}") from exc
        except urllib.error.URLError as exc:
            raise NYTError(f"Could not reach the NYT API: {exc.reason}") from exc

        if payload.get("status") != "OK":
            raise NYTError(f"Unexpected NYT response: {payload!r}")
        return payload
