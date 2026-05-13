import os
import unittest


os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")

import config


class ConfigParsingTests(unittest.TestCase):
    def test_parse_admin_ids_from_environment_style_value(self):
        self.assertEqual({1, 2, 3}, config._parse_admin_ids("1, 2,3"))

    def test_parse_admin_ids_ignores_invalid_entries(self):
        with self.assertLogs(config.logger, level="WARNING"):
            self.assertEqual({1, 3}, config._parse_admin_ids("1,bad,3"))


if __name__ == "__main__":
    unittest.main()
