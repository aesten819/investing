import unittest

from scripts.fetch_memory_news import (
    dedupe_articles,
    is_memory_related,
    parse_rss_feed,
    summarize_text,
)


class MemoryNewsTests(unittest.TestCase):
    def test_keyword_filter_keeps_memory_semiconductor_articles(self):
        self.assertTrue(is_memory_related("HBM demand lifts DRAM outlook", "AI servers need more memory"))
        self.assertTrue(is_memory_related("Enterprise SSD cycle improves", "NAND pricing firms"))

    def test_keyword_filter_rejects_generic_semiconductor_articles(self):
        self.assertFalse(is_memory_related("Foundry node update", "Logic wafer yields improved"))
        self.assertFalse(is_memory_related("SiC MOSFETs enter production", "Infineon is supplying gate drivers"))

    def test_summarize_text_strips_html_and_limits_length(self):
        summary = summarize_text("<p>DRAM contract prices rose as HBM capacity stayed tight.</p><p>More text.</p>", 55)

        self.assertEqual(summary, "DRAM contract prices rose as HBM capacity stayed tight.")

    def test_parse_rss_feed_normalizes_card_fields(self):
        xml = b"""<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Samsung expands HBM portfolio</title>
              <link>https://example.test/hbm</link>
              <pubDate>Wed, 08 Jul 2026 01:02:03 GMT</pubDate>
              <description><![CDATA[<p>New HBM products target AI server memory demand.</p>]]></description>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss_feed(xml, {"id": "samsung", "name": "Samsung Semiconductor"})

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["headline"], "Samsung expands HBM portfolio")
        self.assertEqual(articles[0]["source"], "Samsung Semiconductor")
        self.assertEqual(articles[0]["summary"], "New HBM products target AI server memory demand.")
        self.assertEqual(articles[0]["published_at"], "2026-07-08T01:02:03+00:00")
        self.assertIn("HBM", articles[0]["tags"])

    def test_dedupe_articles_uses_canonical_url(self):
        articles = [
            {
                "id": "old",
                "headline": "HBM article",
                "url": "https://example.test/news?utm_source=x",
                "published_at": "2026-07-08T00:00:00+00:00",
            },
            {
                "id": "new",
                "headline": "HBM article duplicate",
                "url": "https://example.test/news",
                "published_at": "2026-07-08T01:00:00+00:00",
            },
        ]

        deduped = dedupe_articles(articles)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], "new")


if __name__ == "__main__":
    unittest.main()
