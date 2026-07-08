import unittest
import re
from pathlib import Path


class GitHubWorkflowTests(unittest.TestCase):
    def test_daily_memory_news_refresh_workflow_uses_secret_and_deploys_pages(self):
        workflow = Path(".github/workflows/refresh-memory-news.yml")

        self.assertTrue(workflow.exists(), "daily refresh workflow should exist")
        text = workflow.read_text(encoding="utf-8")

        self.assertIn("schedule:", text)
        self.assertIn("cron:", text)
        self.assertIn("DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}", text)
        self.assertIn("python3 scripts/fetch_memory_news.py", text)
        self.assertIn("python3 scripts/translate_memory_news.py", text)
        self.assertIn("npm test", text)
        self.assertIn("npm run build", text)
        self.assertIn("actions/upload-pages-artifact", text)
        self.assertIn("actions/deploy-pages", text)
        self.assertIn("git commit", text)

    def test_workflows_do_not_commit_literal_deepseek_key(self):
        workflow_dir = Path(".github/workflows")
        for workflow in workflow_dir.glob("*.yml"):
            text = workflow.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{20,}", text))


if __name__ == "__main__":
    unittest.main()
