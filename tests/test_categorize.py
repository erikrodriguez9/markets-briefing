import unittest
from datetime import datetime, timezone

from mb.categorize import OTHER, categorize, group
from mb.nyt import Article


def make(title="", abstract="", facets=(), subsection="", published=None):
    return Article(
        title=title, abstract=abstract, byline="By A. Reporter",
        url=f"https://example.com/{abs(hash((title, abstract)))}",
        section="business", subsection=subsection, published=published,
        facets=tuple(facets),
    )


class CategorizeTests(unittest.TestCase):
    def test_facet_wins_markets(self):
        a = make("Shares slip", facets=["Stocks and Bonds"])
        self.assertEqual(categorize(a), "Markets & Investing")

    def test_keyword_fallback_markets(self):
        a = make("The Nasdaq climbed to a record", abstract="Wall Street cheered.")
        self.assertEqual(categorize(a), "Markets & Investing")

    def test_priority_markets_before_economy(self):
        # Matches both an economy keyword and a markets facet -> markets first.
        a = make("Inflation worries hit the S&P 500", facets=["Stocks and Bonds", "Inflation (Economics)"])
        self.assertEqual(categorize(a), "Markets & Investing")

    def test_economy_bucket(self):
        a = make("Fed signals a rate cut", facets=["Federal Reserve System"])
        self.assertEqual(categorize(a), "Economy & Policy")

    def test_deals_bucket(self):
        a = make("Widget Co. to acquire Gadget Inc.", facets=["Mergers, Acquisitions and Divestitures"])
        self.assertEqual(categorize(a), "Companies & Deals")

    def test_subsection_match(self):
        a = make("Dealbook item", subsection="dealbook")
        self.assertEqual(categorize(a), "Companies & Deals")

    def test_unmatched_falls_through(self):
        a = make("A profile of a museum director", abstract="Art and culture.")
        self.assertEqual(categorize(a), OTHER)

    def test_group_sorts_newest_first_and_drops_empty(self):
        old = make("Old stocks story", facets=["Stocks and Bonds"],
                   published=datetime(2026, 1, 1, tzinfo=timezone.utc))
        new = make("New stocks story", facets=["Stocks and Bonds"],
                   published=datetime(2026, 6, 1, tzinfo=timezone.utc))
        buckets = group([old, new])
        self.assertEqual(list(buckets), ["Markets & Investing"])
        self.assertEqual([a.title for a in buckets["Markets & Investing"]],
                         ["New stocks story", "Old stocks story"])


if __name__ == "__main__":
    unittest.main()
