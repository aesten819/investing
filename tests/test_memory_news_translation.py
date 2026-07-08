import json
import unittest

from scripts.translate_memory_news import (
    build_translation_messages,
    merge_translation,
    parse_translation_content,
    translate_articles,
    translation_cache_key,
)


class MemoryNewsTranslationTests(unittest.TestCase):
    def sample_article(self):
        return {
            "id": "abc123",
            "headline": "AI server demand supports DRAM and HBM prices",
            "summary": "Memory contract prices rose as HBM capacity remained tight.",
            "tags": ["AI Server", "DRAM", "HBM", "Pricing"],
        }

    def test_prompt_keeps_core_memory_terms_in_english(self):
        messages = build_translation_messages(self.sample_article())
        prompt = json.dumps(messages, ensure_ascii=False)

        self.assertIn("HBM", prompt)
        self.assertIn("DRAM", prompt)
        self.assertIn("NAND", prompt)
        self.assertIn("JSON", prompt)

    def test_parse_translation_content_accepts_plain_or_fenced_json(self):
        content = """```json
        {
          "headline_ko": "AI 서버 수요가 DRAM과 HBM 가격을 지지",
          "summary_ko": "HBM 공급이 타이트해 메모리 계약 가격이 상승했다.",
          "tags_ko": ["AI 서버", "DRAM", "HBM", "가격"]
        }
        ```"""

        parsed = parse_translation_content(content)

        self.assertEqual(parsed["headline_ko"], "AI 서버 수요가 DRAM과 HBM 가격을 지지")
        self.assertEqual(parsed["tags_ko"], ["AI 서버", "DRAM", "HBM", "가격"])

    def test_merge_translation_adds_korean_fields_without_losing_originals(self):
        merged = merge_translation(
            self.sample_article(),
            {
                "headline_ko": "AI 서버 수요가 DRAM과 HBM 가격을 지지",
                "summary_ko": "HBM 공급이 타이트해 메모리 계약 가격이 상승했다.",
                "tags_ko": ["AI 서버", "DRAM", "HBM", "가격"],
            },
        )

        self.assertEqual(merged["headline"], self.sample_article()["headline"])
        self.assertEqual(merged["headline_ko"], "AI 서버 수요가 DRAM과 HBM 가격을 지지")
        self.assertEqual(merged["summary_ko"], "HBM 공급이 타이트해 메모리 계약 가격이 상승했다.")

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
