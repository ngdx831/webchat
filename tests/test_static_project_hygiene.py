from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StaticProjectHygieneTests(unittest.TestCase):
    def test_api_get_conn_does_not_run_expired_cleanup(self):
        source = (ROOT / "api" / "db_helpers.py").read_text(encoding="utf-8")

        self.assertNotIn("from .cleanup import cleanup_expired_once", source)
        self.assertNotIn("cleanup_expired_once(conn)", source)

    def test_gitignore_excludes_local_runtime_artifacts(self):
        entries = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

        self.assertIn(".venv*/", entries)
        self.assertIn("tmp*/", entries)
        self.assertIn("*.sqlite*", entries)

    def test_frontend_posts_session_token_with_messages(self):
        source = (ROOT / "public" / "chat.js").read_text(encoding="utf-8")

        self.assertIn("token: streamToken", source)

    def test_existing_session_message_path_checks_access_token(self):
        source = (ROOT / "api" / "routes" / "messages.py").read_text(encoding="utf-8")
        existing_branch = source[source.index("existing_session = dbm.session_get"):]
        create_call_at = existing_branch.index("created = dbm.session_create_if_missing")
        guarded_prefix = existing_branch[:create_call_at]

        self.assertIn("session_access_error", guarded_prefix)

    def test_readme_quick_start_mentions_cleanup_worker(self):
        source = (ROOT / "README.md").read_text(encoding="utf-8")
        quick_start = source[source.index("## 快速开始"):source.index("## 用户角色与权限")]

        self.assertIn("python -m api.cleanup_worker", quick_start)
        self.assertIn("docs/OPERATIONS.md", quick_start)


if __name__ == "__main__":
    unittest.main()
