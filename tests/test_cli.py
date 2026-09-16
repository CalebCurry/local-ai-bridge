from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from local_bridge.cli import (
    _credential_present,
    _live_probe_prompt,
    _plugin_blocks,
    doctor,
    inspect_capabilities,
    run_live_probes,
)
from local_bridge.config import Config


PROFILE = """
- id: sandbox-policy
  name: '@deepseek-ai/dsh-sandbox-policy'
  config:
    mode: !!js process.env.DSH_PERMISSION_MODE ?? 'workspace-write'
- id: bash-sandbox
  name: '@deepseek-ai/dsh-bash-sandbox'
- id: tool-bash
  name: '@deepseek-ai/dsh-tool-bash'
- id: fs-sandbox
  name: '@deepseek-ai/dsh-fs-sandbox'
- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'
- id: subagent
  name: '@deepseek-ai/dsh-subagent'
- id: subagent-spawn-in-process
  name: '@deepseek-ai/dsh-subagent-spawn-in-process'
- id: tool-subagent
  name: '@deepseek-ai/dsh-tool-subagent'
- id: web
  name: '@deepseek-ai/dsh-web'
  config:
    searchProvider: deepseek-official
- id: web-search-deepseek
  name: '@deepseek-ai/dsh-web-search-deepseek'
  config:
    apiKeyEnv: TEST_DEEPSEEK_KEY
- id: web-fetch-http
  name: '@deepseek-ai/dsh-web-fetch-http'
- id: tool-web
  name: '@deepseek-ai/dsh-tool-web'
"""


class CapabilityTests(unittest.TestCase):
    @patch("local_bridge.cli.shutil.which", return_value=None)
    def test_doctor_explains_legacy_dsh_command(self, which: Mock) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = doctor(Config(dsh_command="dsh"))
        self.assertEqual(result, 1)
        self.assertIn(
            'dsh_command = "npx --offline --yes @deepseek-ai/dsh"',
            output.getvalue(),
        )

    def test_plugin_blocks_honors_literal_disable(self) -> None:
        blocks = _plugin_blocks("- id: one\n  disabled: true\n- id: two\n")
        self.assertIn("disabled: true", blocks["one"])
        self.assertNotIn("disabled: true", blocks["two"])

    def test_inspects_shipped_capabilities_without_search_key(self) -> None:
        with patch.dict("os.environ", {"TEST_DEEPSEEK_KEY": ""}, clear=False):
            audit = inspect_capabilities(PROFILE)
        self.assertTrue(audit.filesystem)
        self.assertTrue(audit.workspace_write)
        self.assertTrue(audit.shell)
        self.assertTrue(audit.web_fetch)
        self.assertFalse(audit.web_search)
        self.assertTrue(audit.subagents)
        self.assertEqual(audit.permission_mode, "workspace-write")

    def test_search_key_can_come_from_dsh_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".credentials.yaml").write_text(
                "TEST_DEEPSEEK_KEY: secret-not-printed\n", encoding="utf-8"
            )
            self.assertTrue(_credential_present("TEST_DEEPSEEK_KEY", Path(directory)))

    def test_read_only_mode_disables_workspace_write(self) -> None:
        with patch.dict("os.environ", {"DSH_PERMISSION_MODE": "read-only"}):
            audit = inspect_capabilities(PROFILE)
        self.assertTrue(audit.filesystem)
        self.assertFalse(audit.workspace_write)

    def test_live_prompt_only_adds_paid_search_when_requested(self) -> None:
        self.assertNotIn("web-search-proof.txt", _live_probe_prompt(False))
        self.assertIn("web-search-proof.txt", _live_probe_prompt(True))

    @patch("local_bridge.cli.subprocess.run")
    def test_live_probes_require_verified_files(self, run: Mock) -> None:
        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            root = Path(str(kwargs["cwd"]))
            for filename, value in {
                "fs-proof.txt": "FS_OK",
                "shell-proof.txt": "SHELL_OK",
                "web-fetch-proof.txt": "WEB_FETCH_OK",
                "subagent-proof.txt": "SUBAGENT_OK",
            }.items():
                (root / filename).write_text(value, encoding="utf-8")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        run.side_effect = fake_run
        with redirect_stdout(io.StringIO()):
            self.assertTrue(run_live_probes(["dsh"], "headless", 30, False))


if __name__ == "__main__":
    unittest.main()
