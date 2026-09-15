# Local-first coding delegation

When the `local-worker` MCP server and its `delegate_local` tool are available:

- For change/build requests with clear acceptance criteria, delegate routine, token-heavy execution to the local worker.
- Give the worker one complete task with the absolute working directory, constraints, and executable acceptance criteria. Do not micromanage it file by file.
- Keep consequential architecture, security-sensitive decisions, genuine escalations, and final review in Codex.
- After a local `PASS`, inspect the diff and verification evidence in proportion to risk. Do not request the worker's transcript.
- If the local endpoint is unavailable, continue with Codex and mention the fallback briefly.

