from pathlib import Path
import tempfile
import unittest

from local_bridge.config import Config, load_config


class ConfigTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self) -> None:
        config = load_config("/definitely/missing/local-bridge.toml")
        self.assertEqual(config, Config())
        self.assertEqual(config.dsh_command, "npx --yes @deepseek-ai/dsh")

    def test_reads_supported_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                """[local_bridge]
dsh_command = "npx @deepseek-ai/dsh"
profile = "headless"
default_timeout_minutes = 45
max_result_characters = 9000
""",
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(config.dsh_command, "npx @deepseek-ai/dsh")
        self.assertEqual(config.default_timeout_minutes, 45)
        self.assertEqual(config.max_result_characters, 9000)

    def test_rejects_unknown_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[local_bridge]\nunknown = true\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown"):
                load_config(path)

    def test_rejects_timeout_above_hard_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                "[local_bridge]\ndefault_timeout_minutes = 121\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "cannot exceed"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
