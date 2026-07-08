import unittest

from scripts.fetch_memory_news import (
    dedupe_articles,
    is_memory_related,
    merge_existing_articles,
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

    def test_merge_existing_articles_preserves_old_source_when_fetch_fails(self):
        existing = [
            {
                "id": "sk-old",
                "headline": "SK hynix HBM update",
                "summary": "HBM demand remains strong.",
                "url": "https://example.test/sk",
                "source_id": "sk_hynix",
                "published_at": "2026-07-08T00:00:00+00:00",
            }
        ]
        fresh = [
            {
                "id": "samsung-new",
                "headline": "Samsung SSD update",
                "summary": "SSD demand improves.",
                "url": "https://example.test/samsung",
                "source_id": "samsung_semiconductor",
                "published_at": "2026-07-09T00:00:00+00:00",
            }
        ]

        merged = merge_existing_articles(fresh, existing, 80)

        self.assertEqual([article["id"] for article in merged], ["samsung-new", "sk-old"])

    def test_merge_existing_articles_carries_existing_translation_for_refetched_article(self):
        existing = [
            {
                "id": "same",
                "headline": "Samsung SSD update",
                "headline_ko": "삼성 SSD 업데이트",
                "summary": "SSD demand improves.",
                "summary_ko": "SSD 수요가 개선됐다.",
                "tags": ["SSD"],
                "tags_ko": ["SSD"],
                "url": "https://example.test/samsung?utm_source=old",
                "source_id": "samsung_semiconductor",
                "published_at": "2026-07-09T00:00:00+00:00",
            }
        ]
        fresh = [
            {
                "id": "same",
                "headline": "Samsung SSD update",
                "summary": "SSD demand improves.",
                "tags": ["SSD"],
                "url": "https://example.test/samsung",
                "source_id": "samsung_semiconductor",
                "published_at": "2026-07-09T00:00:00+00:00",
            }
        ]

        merged = merge_existing_articles(fresh, existing, 80)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["headline_ko"], "삼성 SSD 업데이트")
        self.assertEqual(merged[0]["summary_ko"], "SSD 수요가 개선됐다.")


if __name__ == "__main__":
    unittest.main()
