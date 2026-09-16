# Local-first coding delegation

When the `local-worker` MCP server and its background delegation tools are available:

- Before the first delegation in a session, run `local-bridge doctor` and report its capability summary and any unavailable features to the user. If the doctor fails, do not delegate until the failure is resolved or the user accepts a fallback.
- During initial setup or when the user requests end-to-end validation, also run `local-bridge doctor --live` and report the result. Never add `--web-search` without explicit user approval because it can consume hosted provider usage.
- For change/build requests with clear acceptance criteria, call `delegate_local_start` to run routine, token-heavy execution in the background. Do not use the blocking `delegate_local` compatibility tool.
- Give the worker one complete task with the absolute working directory, constraints, and executable acceptance criteria. Do not micromanage it file by file.
- After starting a job, report its ID and remain available to the user. Do not busy-poll or block the conversation. Use `delegate_local_status` when the user asks, when progress information is useful, or before consuming a result.
- Use `delegate_local_result` after the status is terminal. Use `delegate_local_cancel` when the user cancels or when the job is clearly stuck. Never kill the shared local model server to cancel one job.
- Keep consequential architecture, security-sensitive decisions, genuine escalations, and final review in Codex.
- After a local `PASS`, inspect the diff and verification evidence in proportion to risk. Do not request the worker's transcript.
- If the local endpoint is unavailable, continue with Codex and mention the fallback briefly.
