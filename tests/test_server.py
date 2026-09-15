import io
import json
import unittest

from local_bridge.config import Config
from local_bridge.server import response_for, serve, tool_definition, trim


class ServerTests(unittest.TestCase):
    def test_tool_schema_uses_configured_default(self) -> None:
        tool = tool_definition(Config(default_timeout_minutes=42))
        self.assertEqual(tool["inputSchema"]["properties"]["max_minutes"]["default"], 42)

    def test_lists_only_delegate_tool(self) -> None:
        response = response_for(
            Config(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert response is not None
        self.assertEqual(response["result"]["tools"][0]["name"], "delegate_local")

    def test_stdio_initialize(self) -> None:
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        output = io.StringIO()
        serve(Config(), io.StringIO(request + "\n"), output)
        response = json.loads(output.getvalue())
        self.assertEqual(response["result"]["serverInfo"]["name"], "local-deepseek-harness")

    def test_trim_is_bounded(self) -> None:
        self.assertEqual(trim("abcdef", 3), "abc\n...[truncated 3 characters]")


if __name__ == "__main__":
    unittest.main()

