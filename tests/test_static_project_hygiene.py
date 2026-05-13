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

    def test_production_api_service_uses_gunicorn(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

        self.assertIn("gunicorn==23.0.0", requirements)
        self.assertIn(
            'ExecStart=/www/wwwroot/webchat/venv/bin/gunicorn -k gthread -w 2 --threads 16 -b 127.0.0.1:5055 "api.app:create_app()"',
            operations,
        )

    def test_message_handlers_close_db_connections_and_log_download_failures(self):
        source = (ROOT / "bot" / "handlers" / "messages.py").read_text(encoding="utf-8")

        self.assertIn("import contextlib", source)
        self.assertIn("logger = logging.getLogger(__name__)", source)
        self.assertIn("with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:", source)
        self.assertNotIn('print(f"下载', source)
        self.assertGreaterEqual(source.count("logger.warning("), 4)
        self.assertIn("exc_info=True", source)


if __name__ == "__main__":
    unittest.main()
