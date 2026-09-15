# Codex Local Bridge

Codex Local Bridge lets Codex act as the high-level engineering lead while a local model performs the token-heavy coding work. It exposes DeepSeek Harness as one MCP tool that can inspect a repository, edit files, run tests, fix failures, and return only a short final report to Codex.

```text
You → Codex → delegate_local → DeepSeek Harness → local model
                         ← short PASS/ESCALATE report ←
```

The local model keeps its exploration, command output, and repair loops in its own Harness process. Codex receives the final result and can review the resulting diff without ingesting the worker's full transcript.

> [!WARNING]
> DeepSeek Harness is currently a developer preview and may make compatibility-breaking changes. The local worker can execute commands and modify files with your user permissions. Use source control and review its changes.

## Have your coding agent set it up

Copy and paste this into Codex or another coding agent running on the computer where your local model is hosted:

```text
Set up Codex Local Bridge for me from:
https://github.com/CalebCurry/local-ai-bridge

Work autonomously and verify the complete Codex → MCP → DeepSeek Harness → local-model path.

1. Inspect my OS, shell, Python, Node.js, Codex, DeepSeek Harness, and local model runtimes before changing anything.
2. Clone the repository into an appropriate development directory, read its README, create a Python virtual environment, and install the package.
3. If DeepSeek Harness is missing, install it using its current official instructions. Do not overwrite existing Harness settings, credentials, sessions, or model-provider configuration.
4. Find my existing local OpenAI-compatible model endpoint and model ID when possible. If no working endpoint/model can be identified, ask me one concise question for those values instead of guessing or downloading a large model.
5. Configure DeepSeek Harness so its headless profile uses the local model. Confirm a harmless headless prompt succeeds.
6. Create ~/.config/local-bridge/config.toml with the correct dsh_command. Keep the other defaults unless my environment requires different values.
7. Run local-bridge doctor and fix any failures.
8. Register the bridge in Codex as the local-worker STDIO MCP server. Preserve unrelated ~/.codex/config.toml settings. Configure startup_timeout_sec = 10, tool_timeout_sec = 7200, enable only delegate_local, and set its output_token_limit = 5000.
9. Merge the repository's templates/AGENTS.md guidance into my global ~/.codex/AGENTS.md without overwriting existing instructions.
10. Run an end-to-end, read-only delegation smoke test from a fresh Codex session. Do not modify a real project during the smoke test.
11. Report what you installed or changed, exact config paths, test results, and anything I still need to do. Never print secrets or credential-file contents.
```

The agent should only need your input when it cannot identify a working local endpoint and model automatically.

## Quickstart

You need Python 3.11+, Node.js, Codex, a local OpenAI-compatible model endpoint, and Git.

### 1. Install and configure DeepSeek Harness

The official Harness quickstart uses `npx`:

```bash
npx @deepseek-ai/dsh web
```

This opens the Harness UI. In its model settings, add your local provider and select its model as the default. The exact URL and model ID come from your runtime—for example, LM Studio often uses `http://127.0.0.1:1234/v1`, while a llama.cpp server uses the address you chose when starting it.

Required Harness state:

- An OpenAI-compatible model server is running and reachable.
- Harness has a provider pointing to that server.
- Harness has a default model selected.
- The shipped `headless` profile can complete a task.

Verify Harness before installing the bridge:

```bash
npx @deepseek-ai/dsh --profile headless "Reply with exactly: LOCAL_OK"
```

See the [DeepSeek Harness repository](https://github.com/deepseek-ai/deepseek-harness) for its current installation and safety guidance.

### 2. Install Local Bridge

```bash
git clone https://github.com/CalebCurry/local-ai-bridge.git local-ai-bridge
cd local-ai-bridge
python3 -m venv .venv
./.venv/bin/pip install .
mkdir -p ~/.config/local-bridge
cp config.example.toml ~/.config/local-bridge/config.toml
```

If you run Harness through `npx`, edit `~/.config/local-bridge/config.toml` to use:

```toml
[local_bridge]
dsh_command = "npx @deepseek-ai/dsh"
```

If `dsh` is already installed globally and available on `PATH`, the included `dsh_command = "dsh"` setting works as-is.

Check the installation:

```bash
./.venv/bin/local-bridge doctor
```

### 3. Connect Codex

From the repository directory, register the bridge as a local STDIO MCP server:

```bash
codex mcp add local-worker -- "$PWD/.venv/bin/local-bridge" serve
```

Then open `~/.codex/config.toml` and add the timeout and tool restrictions inside the generated `[mcp_servers.local-worker]` table:

```toml
[mcp_servers.local-worker]
command = "/absolute/path/to/local-bridge/.venv/bin/local-bridge"
args = ["serve"]
startup_timeout_sec = 10
tool_timeout_sec = 7200
enabled_tools = ["delegate_local"]

[mcp_servers.local-worker.tools.delegate_local]
output_token_limit = 5000
```

The long tool timeout matters: local-model coding loops commonly take more than Codex's default MCP tool timeout.

Restart Codex or begin a new Codex session, then verify the server with:

```bash
codex mcp get local-worker
```

Ask Codex to try it:

> Use `local-worker` to inspect this repository and run a harmless read-only smoke test. Do not modify files.

That is the minimum working setup.

## Configuration

Local Bridge reads `~/.config/local-bridge/config.toml`. Set `LOCAL_BRIDGE_CONFIG` to use another path:

```bash
export LOCAL_BRIDGE_CONFIG=/absolute/path/to/config.toml
```

No Local Bridge configuration file is required if all defaults fit your environment. The task and absolute working directory are required on each MCP tool call; Codex supplies those automatically.

```toml
[local_bridge]
dsh_command = "dsh"
profile = "headless"
default_timeout_minutes = 30
max_result_characters = 16000
```

| Setting | Required? | Default | Purpose |
|---|---:|---|---|
| `dsh_command` | Optional | `dsh` | Command used to start Harness. It may include arguments, such as `npx @deepseek-ai/dsh`, or be an absolute executable path. |
| `profile` | Optional | `headless` | Harness profile used for each one-shot delegated task. The shipped `headless` profile is recommended. |
| `default_timeout_minutes` | Optional | `30` | Default wall-clock limit for one delegated task. Codex may request a different value, capped at 120 minutes. |
| `max_result_characters` | Optional | `16000` | Maximum final-answer characters returned to Codex. Successful Harness reasoning and tool logs are discarded. |

External requirements that configuration cannot replace:

| Requirement | Required? |
|---|---:|
| Python 3.11 or newer | Required |
| A working `dsh` or `npx @deepseek-ai/dsh` command | Required |
| A running local OpenAI-compatible model endpoint | Required |
| A Harness provider and default model | Required |
| Global local-first Codex instructions | Optional |

Print the effective configuration:

```bash
local-bridge print-config
```

Validate the Harness executable and profile configuration:

```bash
local-bridge doctor
```

## Make Codex prefer the local worker

Installing the MCP server makes delegation available; it does not force every Codex session to use it. For an explicit one-off request, say:

> Delegate routine implementation and verification to `local-worker`. Keep architecture and final review in Codex.

For a persistent preference, merge [`templates/AGENTS.md`](templates/AGENTS.md) into `~/.codex/AGENTS.md`. Do not overwrite an existing global instruction file without reviewing and combining the contents.

Codex loads global `AGENTS.md` guidance and MCP configuration at the beginning of a new session, so restart after changing either one. See the official [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) and [AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## How delegation behaves

Each `delegate_local` call receives:

- `task` — required, self-contained instructions and acceptance criteria.
- `workdir` — required, an absolute repository or workspace directory.
- `max_minutes` — optional, the per-task timeout.

The worker is instructed to explore, implement, test, fix failures, and review its own diff. Its successful response is limited to:

```text
STATUS: PASS or ESCALATE
FILES: changed paths, or none
TESTS: concise results
SUMMARY: at most five short lines
BLOCKER: only when escalation is required
```

Harness reasoning is written to its stderr stream and is intentionally excluded from successful MCP results. Diagnostics are returned only when Harness fails or times out.

## Development

Install the package in editable mode and run the dependency-free test suite:

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .
./.venv/bin/python -m unittest discover -s tests -v
```

The tests exercise configuration validation and MCP framing without downloading Harness or loading a model.

## Uninstall

```bash
codex mcp remove local-worker
```

Then remove the virtual environment or repository. If you merged the optional policy into `~/.codex/AGENTS.md`, remove those lines manually while preserving your other global instructions.

## License

MIT
