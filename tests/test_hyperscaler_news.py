import unittest

from scripts.fetch_hyperscaler_news import (
    dedupe_articles,
    is_hyperscaler_infra_related,
    merge_existing_articles,
    parse_html_links,
    parse_rss_feed,
    summarize_text,
)


class HyperscalerNewsTests(unittest.TestCase):
    def test_keyword_filter_keeps_data_center_investment_articles(self):
        self.assertTrue(
            is_hyperscaler_infra_related(
                "Microsoft adds 2GW AI datacenter capacity in Texas",
                "The project expands Azure capacity for AI cloud services.",
            )
        )
        self.assertTrue(
            is_hyperscaler_infra_related(
                "Hyperscale capex rises as data center buildouts accelerate",
                "Power and cooling constraints remain the key bottleneck.",
            )
        )

    def test_keyword_filter_rejects_generic_cloud_product_articles(self):
        self.assertFalse(
            is_hyperscaler_infra_related(
                "AWS launches a new developer tool",
                "The SDK update improves application observability.",
            )
        )
        self.assertFalse(
            is_hyperscaler_infra_related(
                "Google Workspace adds spreadsheet templates",
                "The release helps teams format weekly reports.",
            )
        )

    def test_summarize_text_strips_html_and_limits_length(self):
        summary = summarize_text(
            "<p>Meta announced a new AI data center campus with 1GW of capacity.</p><p>More text.</p>",
            72,
        )

        self.assertEqual(summary, "Meta announced a new AI data center campus with 1GW of capacity.")

    def test_parse_rss_feed_normalizes_card_fields(self):
        xml = b"""<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Google expands AI data center investment</title>
              <link>https://example.test/google-dc?utm_source=rss</link>
              <pubDate>Wed, 08 Jul 2026 01:02:03 GMT</pubDate>
              <description><![CDATA[<p>The company will add cloud region capacity for AI infrastructure.</p>]]></description>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss_feed(
            xml,
            {
                "id": "google_infrastructure",
                "name": "Google Infrastructure",
                "url": "https://example.test/feed",
                "type": "rss",
            },
        )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["headline"], "Google expands AI data center investment")
        self.assertEqual(articles[0]["source"], "Google Infrastructure")
        self.assertEqual(
            articles[0]["summary"],
            "The company will add cloud region capacity for AI infrastructure.",
        )
        self.assertEqual(articles[0]["published_at"], "2026-07-08T01:02:03+00:00")
        self.assertIn("Google Cloud", articles[0]["tags"])
        self.assertIn("Data Center", articles[0]["tags"])

    def test_parse_html_links_extracts_relevant_article_cards(self):
        html = b"""
        <html>
          <body>
            <a href="/articles/hyperscale-capex">Justifying the Explosive Growth in Hyperscale CAPEX</a>
            <a href="/contact">Contact Us</a>
            <a href="https://example.test/oracle-ai">Oracle AI data centers need skilled people</a>
          </body>
        </html>
        """

        articles = parse_html_links(
            html,
            {
                "id": "synergy_research",
                "name": "Synergy Research",
                "url": "https://example.test/articles",
                "type": "html_links",
            },
            "2026-07-09T00:00:00+00:00",
        )

        self.assertEqual([article["headline"] for article in articles], [
            "Justifying the Explosive Growth in Hyperscale CAPEX",
            "Oracle AI data centers need skilled people",
        ])
        self.assertEqual(articles[0]["url"], "https://example.test/articles/hyperscale-capex")
        self.assertIn("Capex", articles[0]["tags"])

    def test_dedupe_articles_uses_canonical_url(self):
        articles = [
            {
                "id": "old",
                "headline": "AI data center article",
                "url": "https://example.test/news?utm_source=x",
                "published_at": "2026-07-08T00:00:00+00:00",
            },
            {
                "id": "new",
                "headline": "AI data center article duplicate",
                "url": "https://example.test/news",
                "published_at": "2026-07-08T01:00:00+00:00",
            },
        ]

        deduped = dedupe_articles(articles)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], "new")

    def test_merge_existing_articles_preserves_translation_and_original_date(self):
        existing = [
            {
                "id": "same",
                "headline": "Oracle AI data center campus",
                "headline_ko": "Oracle AI 데이터센터 캠퍼스",
                "summary": "Oracle discusses AI infrastructure.",
                "summary_ko": "Oracle이 AI 인프라를 설명했다.",
                "tags": ["Oracle", "AI Infrastructure"],
                "tags_ko": ["Oracle", "AI 인프라"],
                "url": "https://example.test/oracle?utm_source=old",
                "source_id": "oracle_ai_data_centers",
                "published_at": "2026-07-01T00:00:00+00:00",
            }
        ]
        fresh = [
            {
                "id": "same",
                "headline": "Oracle AI data center campus",
                "summary": "Oracle discusses AI infrastructure.",
                "tags": ["Oracle", "AI Infrastructure"],
                "url": "https://example.test/oracle",
                "source_id": "oracle_ai_data_centers",
                "published_at": "2026-07-09T00:00:00+00:00",
            }
        ]

        merged = merge_existing_articles(fresh, existing, 80)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["headline_ko"], "Oracle AI 데이터센터 캠퍼스")
        self.assertEqual(merged[0]["summary_ko"], "Oracle이 AI 인프라를 설명했다.")
        self.assertEqual(merged[0]["published_at"], "2026-07-01T00:00:00+00:00")

    def test_merge_existing_articles_drops_existing_noise(self):
        existing = [
            {
                "id": "jobs",
                "headline": "Data Center Jobs: July 2026",
                "summary": "A jobs listing for data center operators.",
                "tags": ["Data Center"],
                "url": "https://example.test/jobs",
                "source_id": "data_center_frontier",
                "published_at": "2026-07-01T00:00:00+00:00",
            }
        ]

        merged = merge_existing_articles([], existing, 80)

        self.assertEqual(merged, [])


if __name__ == "__main__":
    unittest.main()
