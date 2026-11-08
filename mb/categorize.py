"""Bucket NYT articles into markets-briefing sections.

Each article lands in the FIRST section (in the order below) whose facet set or
keyword pattern it matches, so the output never duplicates a story. Anything
unmatched falls through to "Other Business".
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

from .nyt import Article

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Section:
    name: str
    facets: frozenset[str]
    keywords: re.Pattern | None

    def matches(self, article: Article) -> bool:
        if self.facets and self.facets.intersection(article.facets):
            return True
        if article.subsection.lower() in self.facets:
            return True
        if self.keywords and self.keywords.search(article.haystack):
            return True
        return False


def _kw(*words: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


SECTIONS: tuple[Section, ...] = (
    Section(
        "Markets & Investing",
        frozenset({
            "Stocks and Bonds", "Government Bonds", "Municipal Bonds",
            "Standard & Poor's 500-Stock Index", "Dow Jones Stock Average",
            "Nasdaq Composite Index", "Mutual Funds", "Exchange Traded Funds",
            "Futures and Options Trading", "Private Equity", "Hedge Funds",
            "Venture Capital", "Initial Public Offerings", "Prediction Markets",
            "Currency", "Yen (Currency)", "Euro (Currency)",
            "Bitcoin (Currency)", "Virtual Currency", "Stock Exchanges",
            "markets",
        }),
        _kw(
            r"stocks?", r"bonds?", r"equities", r"S&P 500", r"nasdaq", r"dow jones",
            r"treasury yields?", r"bond market", r"sell-?off", r"rally", r"rallied",
            r"IPO", r"initial public offering", r"crypto\w*", r"bitcoin", r"ether\w*",
            r"wall street",
        ),
    ),
    Section(
        "Economy & Policy",
        frozenset({
            "United States Economy", "Economic Conditions and Trends",
            "Inflation (Economics)", "Interest Rates", "Federal Reserve System",
            "Labor and Jobs", "Unemployment Insurance", "Gross Domestic Product",
            "Recession and Depression", "Customs (Tariff)",
            "International Trade and World Market", "Subprime Mortgage Crisis",
        }),
        _kw(
            r"inflation", r"federal reserve", r"the fed", r"rate cuts?", r"rate hikes?",
            r"interest rates?", r"tariffs?", r"trade war", r"jobs report", r"payrolls",
            r"unemployment", r"GDP", r"recession", r"consumer spending", r"the economy",
        ),
    ),
    Section(
        "Companies & Deals",
        frozenset({
            "Mergers, Acquisitions and Divestitures", "Company Reports",
            "Layoffs and Job Reductions", "Executive Compensation",
            "Corporate Governance", "Bankruptcies", "Stock Buybacks",
            "Corporate Taxes", "dealbook",
        }),
        _kw(
            r"earnings", r"revenue", r"profits?", r"merger", r"acquisitions?",
            r"acquires?", r"acquired", r"buyout", r"takeover", r"layoffs?",
            r"restructuring", r"funding round", r"valuation", r"bankruptcy",
        ),
    ),
    Section(
        "Tech & AI",
        frozenset({
            "Artificial Intelligence", "Computers and the Internet",
            "Data Centers", "Semiconductors", "Cloud Computing",
            "Driverless and Semiautonomous Vehicles", "Social Media",
            "Computer Chips",
        }),
        _kw(
            r"A\.?I\.?", r"artificial intelligence", r"chips?", r"semiconductors?",
            r"data centers?", r"cloud computing", r"large language model",
        ),
    ),
    Section(
        "Energy & Commodities",
        frozenset({
            "Oil (Petroleum) and Gasoline", "Natural Gas", "Coal",
            "Renewable Energy", "Electric Light and Power", "Gold",
            "Metals and Minerals",
        }),
        _kw(
            r"oil", r"crude", r"OPEC", r"natural gas", r"gasoline", r"gas prices?",
            r"commodit\w*", r"gold prices?", r"copper", r"lithium",
        ),
    ),
)

OTHER = "Other Business"


def categorize(article: Article) -> str:
    for section in SECTIONS:
        if section.matches(article):
            return section.name
    return OTHER


def group(articles: list[Article]) -> "OrderedDict[str, list[Article]]":
    buckets: OrderedDict[str, list[Article]] = OrderedDict(
        (s.name, []) for s in SECTIONS
    )
    buckets[OTHER] = []
    for article in articles:
        buckets[categorize(article)].append(article)
    for items in buckets.values():
        items.sort(key=lambda a: a.published or _OLDEST, reverse=True)
    return OrderedDict((k, v) for k, v in buckets.items() if v)
