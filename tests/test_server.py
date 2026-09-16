import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from local_bridge.config import Config
from local_bridge.jobs import cancel_job, job_result, job_status, start_job
from local_bridge.server import response_for, serve, tool_definition, trim


class ServerTests(unittest.TestCase):
    def test_tool_schema_uses_configured_default(self) -> None:
        tool = tool_definition(Config(default_timeout_minutes=42))
        self.assertEqual(tool["inputSchema"]["properties"]["max_minutes"]["default"], 42)

    def test_lists_async_tools_first_and_keeps_compatibility_tool(self) -> None:
        response = response_for(
            Config(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert response is not None
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(
            names,
            [
                "delegate_local_start",
                "delegate_local_status",
                "delegate_local_result",
                "delegate_local_cancel",
                "delegate_local",
            ],
        )

    def test_stdio_initialize(self) -> None:
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        output = io.StringIO()
        serve(Config(), io.StringIO(request + "\n"), output)
        response = json.loads(output.getvalue())
        self.assertEqual(response["result"]["serverInfo"]["name"], "local-deepseek-harness")

    def test_trim_is_bounded(self) -> None:
        self.assertEqual(trim("abcdef", 3), "abc\n...[truncated 3 characters]")

    def test_background_job_returns_immediately_and_collects_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            jobs = root / "jobs"
            workspace.mkdir()
            fake = root / "fake_harness.py"
            fake.write_text(
                "import pathlib, sys, time\n"
                "time.sleep(0.15)\n"
                "pathlib.Path('proof.txt').write_text('ok')\n"
                "print('STATUS: PASS\\nFILES: proof.txt\\nTESTS: pass\\nSUMMARY: done')\n"
                "print('{\"input_tokens\": 10, \"output_tokens\": 20, \"total_tokens\": 30}', file=sys.stderr)\n",
                encoding="utf-8",
            )
            config = Config(dsh_command=shlex.join([sys.executable, str(fake)]))
            with patch.dict(os.environ, {"LOCAL_BRIDGE_JOBS_DIR": str(jobs)}):
                started_at = time.monotonic()
                started = start_job(
                    config,
                    {"task": "create proof", "workdir": str(workspace), "max_minutes": 1},
                )
                self.assertLess(time.monotonic() - started_at, 1)
                job_id = started["job_id"]
                for _ in range(100):
                    status = job_status(job_id)
                    if status["status"] in {"passed", "failed"}:
                        break
                    time.sleep(0.05)
                self.assertEqual(status["status"], "passed")
                self.assertEqual(status["token_usage"]["total_tokens"], 30)
                self.assertIn("proof.txt", status["workspace_activity"])
                result, is_error = job_result(config, job_id)
                self.assertFalse(is_error)
                self.assertIn("STATUS: PASS", result)
                self.assertIn('"total_tokens": 30', result)

    def test_background_job_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            jobs = root / "jobs"
            workspace.mkdir()
            fake = root / "slow_harness.py"
            fake.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            config = Config(dsh_command=shlex.join([sys.executable, str(fake)]))
            with patch.dict(os.environ, {"LOCAL_BRIDGE_JOBS_DIR": str(jobs)}):
                started = start_job(config, {"task": "wait", "workdir": str(workspace)})
                response = cancel_job(started["job_id"])
                self.assertEqual(response["status"], "cancelling")
                for _ in range(100):
                    status = job_status(started["job_id"])
                    if status["status"] == "cancelled":
                        break
                    time.sleep(0.05)
                self.assertEqual(status["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
