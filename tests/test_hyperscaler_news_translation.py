import json
import unittest

from scripts.translate_hyperscaler_news import (
    build_translation_messages,
    merge_translation,
    parse_translation_content,
    translate_articles,
    translation_cache_key,
)


class HyperscalerNewsTranslationTests(unittest.TestCase):
    def sample_article(self):
        return {
            "id": "abc123",
            "headline": "AWS files for a 1.2GW AI data center campus",
            "summary": "The project would expand cloud capacity as hyperscaler capex rises.",
            "tags": ["AWS", "Data Center", "AI Infrastructure", "Capex"],
        }

    def test_prompt_keeps_core_infrastructure_terms_in_english(self):
        messages = build_translation_messages(self.sample_article())
        prompt = json.dumps(messages, ensure_ascii=False)

        self.assertIn("AWS", prompt)
        self.assertIn("Azure", prompt)
        self.assertIn("Google Cloud", prompt)
        self.assertIn("capex", prompt)
        self.assertIn("JSON", prompt)

    def test_parse_translation_content_accepts_plain_or_fenced_json(self):
        content = """```json
        {
          "headline_ko": "AWS, 1.2GW AI 데이터센터 캠퍼스 신청",
          "summary_ko": "hyperscaler capex가 증가하는 가운데 해당 프로젝트는 cloud capacity 확대를 목표로 한다.",
          "tags_ko": ["AWS", "데이터센터", "AI 인프라", "capex"]
        }
        ```"""

        parsed = parse_translation_content(content)

        self.assertEqual(parsed["headline_ko"], "AWS, 1.2GW AI 데이터센터 캠퍼스 신청")
        self.assertEqual(parsed["tags_ko"], ["AWS", "데이터센터", "AI 인프라", "capex"])

    def test_merge_translation_adds_korean_fields_without_losing_originals(self):
        merged = merge_translation(
            self.sample_article(),
            {
                "headline_ko": "AWS, 1.2GW AI 데이터센터 캠퍼스 신청",
                "summary_ko": "hyperscaler capex가 증가하는 가운데 cloud capacity 확대를 추진한다.",
                "tags_ko": ["AWS", "데이터센터", "AI 인프라", "capex"],
            },
        )

        self.assertEqual(merged["headline"], self.sample_article()["headline"])
        self.assertEqual(merged["headline_ko"], "AWS, 1.2GW AI 데이터센터 캠퍼스 신청")
        self.assertEqual(
            merged["summary_ko"],
            "hyperscaler capex가 증가하는 가운데 cloud capacity 확대를 추진한다.",
        )

    def test_translate_articles_uses_cache_before_client(self):
        article = self.sample_article()
        key = translation_cache_key(article)
        cache = {
            key: {
                "headline_ko": "캐시 제목",
                "summary_ko": "캐시 요약",
                "tags_ko": ["캐시"],
            }
        }

        def fail_client(_article):
            raise AssertionError("client should not be called for cached translations")

        translated, updated_cache, stats = translate_articles([article], cache, fail_client)

        self.assertEqual(translated[0]["headline_ko"], "캐시 제목")
        self.assertEqual(updated_cache, cache)
        self.assertEqual(stats["cached"], 1)
        self.assertEqual(stats["translated"], 0)


if __name__ == "__main__":
    unittest.main()
