import os
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CustomerBotPollingStaticTests(unittest.TestCase):
    def test_customer_bots_use_public_start_polling_api(self):
        source = (ROOT / "bot" / "customer_bots.py").read_text(encoding="utf-8")
        self.assertNotIn("._polling", source)
        self.assertNotIn("from .runtime import dp", source)
        self.assertIn("Dispatcher", source)
        self.assertIn("start_polling", source)
        self.assertIn("handle_signals=False", source)

    def test_relay_does_not_construct_unregistered_customer_bot(self):
        source = (ROOT / "bot" / "relay.py").read_text(encoding="utf-8")
        branch = source[source.index("customer_bot = CUSTOMER_BOTS_BY_BINDING_ID"):]
        self.assertNotIn("customer_bot = Bot(", branch)
        self.assertIn("logger.warning", branch)

    def test_handlers_import_without_main_bot_token(self):
        env = os.environ.copy()
        env["WEBCHAT_BOT_TOKEN"] = ""
        env.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")
        env.setdefault("WEBCHAT_INTERNAL_TOKEN", "test-internal-token")

        result = subprocess.run(
            [sys.executable, "-c", "import bot.handlers; print('ok')"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
