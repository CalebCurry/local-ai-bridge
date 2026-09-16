# Local-first coding delegation

When the `local-worker` MCP server and its `delegate_local` tool are available:

- Before the first delegation in a session, run `local-bridge doctor` and report its capability summary and any unavailable features to the user. If the doctor fails, do not delegate until the failure is resolved or the user accepts a fallback.
- During initial setup or when the user requests end-to-end validation, also run `local-bridge doctor --live` and report the result. Never add `--web-search` without explicit user approval because it can consume hosted provider usage.
- For change/build requests with clear acceptance criteria, delegate routine, token-heavy execution to the local worker.
- Give the worker one complete task with the absolute working directory, constraints, and executable acceptance criteria. Do not micromanage it file by file.
- Keep consequential architecture, security-sensitive decisions, genuine escalations, and final review in Claude Code.
- After a local `PASS`, inspect the diff and verification evidence in proportion to risk. Do not request the worker's transcript.
- If the local endpoint is unavailable, continue with Claude Code and mention the fallback briefly.
