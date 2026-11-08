import unittest
from datetime import datetime, timedelta, timezone

from mb.rss import FeedItem, SourceResult, _clean, recent, render_section

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def item(title="story", hours_old=1.0, dated=True):
    published = NOW - timedelta(hours=hours_old) if dated else None
    return FeedItem(
        source="FT", title=title, summary="", link="https://x/y", published=published,
    )


class CleanTests(unittest.TestCase):
    def test_strips_tags_and_entities(self):
        self.assertEqual(_clean("<p>Yen &amp; yuan  jump</p>"), "Yen & yuan jump")

    def test_none_is_empty(self):
        self.assertEqual(_clean(None), "")


class RecentTests(unittest.TestCase):
    def test_keeps_only_items_within_window(self):
        items = [item("fresh", 2), item("stale", 30)]
        kept = recent(items, now=NOW, max_age_hours=24.0)
        self.assertEqual([i.title for i in kept], ["fresh"])

    def test_drops_undated_items(self):
        kept = recent([item("no date", dated=False)], now=NOW)
        self.assertEqual(kept, [])

    def test_sorted_newest_first(self):
        items = [item("older", 10), item("newer", 1)]
        self.assertEqual([i.title for i in recent(items, now=NOW)], ["newer", "older"])


class RenderSectionTests(unittest.TestCase):
    def test_labels_source_and_lists_items(self):
        res = SourceResult("The Economist", "https://e/rss.xml", [item("Rates in focus", 3)], None)
        out = render_section(res, now=NOW)
        self.assertIn("SOURCE: THE ECONOMIST — RSS, last 24h", out)
        self.assertIn("Rates in focus", out)

    def test_empty_source_still_labeled(self):
        res = SourceResult("The Economist", None, [], "HTTP 403")
        out = render_section(res, now=NOW)
        self.assertIn("SOURCE: THE ECONOMIST", out)
        self.assertIn("No items in the last 24 hours.", out)
        self.assertIn("HTTP 403", out)


if __name__ == "__main__":
    unittest.main()
