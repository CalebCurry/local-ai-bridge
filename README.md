# Local AI Bridge

Local AI Bridge lets Codex, Claude Code, or another MCP-capable coding agent act as the high-level engineering lead while a local model performs the token-heavy work. It exposes DeepSeek Harness as one MCP tool that can inspect a repository, edit files, run tests, fix failures, and return only a short final report.

```text
You → Codex or Claude Code → delegate_local → DeepSeek Harness → local model
                                      ← short PASS/ESCALATE report ←
```

The bridge is not tied to Codex. Its runtime speaks standard MCP over stdio; only the MCP registration and instruction files differ between Codex and Claude Code. Delegation is opt-in per repository, so installing the bridge does not change how the parent agent behaves in unrelated projects. The local model keeps its exploration, command output, and repair loops in its own Harness process, while the parent agent receives the result and reviews the diff without ingesting the worker's full transcript.

> [!WARNING]
> DeepSeek Harness is currently a developer preview and may make compatibility-breaking changes. The local worker can execute commands and modify files with your user permissions. Use source control and review its changes.

## Have your agent set it up

Choose your parent agent and paste the matching prompt into it. Each prompt installs the same bridge and local worker.

### Codex setup prompt

```text
Set up Local AI Bridge for me, using Codex as the parent agent, from:
https://github.com/CalebCurry/local-ai-bridge

Work autonomously and verify the complete Codex → MCP → DeepSeek Harness → local-model path. Enable delegation only for the project repository where I invoked you, not globally for every Codex project.

1. Inspect my OS, shell, Python, Node.js, Codex, DeepSeek Harness, and local model runtimes before changing anything.
2. Clone the repository into an appropriate development directory, read its README, create a Python virtual environment, and install the package.
3. If DeepSeek Harness is missing, install it using its current official instructions. Do not overwrite existing Harness settings, credentials, sessions, or model-provider configuration.
4. Prefer llama.cpp as the local inference runtime. First look for an existing llama.cpp server and compatible local GGUF coding model. If llama.cpp is not installed and no suitable runtime is already working, install it using its current official instructions. Start it on localhost with an OpenAI-compatible endpoint, tool calling enabled, and a stable model alias.
5. LM Studio and Ollama are supported alternatives. If I already have a healthy LM Studio or Ollama endpoint and model, preserve and use it instead of forcing a migration. If llama.cpp is unsuitable for my platform, offer LM Studio first and Ollama second.
6. Never download a large model without asking me first. If no working endpoint/model can be identified, ask me one concise question that includes the llama.cpp recommendation and the LM Studio/Ollama alternatives.
7. Configure DeepSeek Harness so its headless profile uses the chosen local model. Confirm a harmless headless prompt succeeds.
8. Create ~/.config/local-bridge/config.toml with the correct dsh_command. Keep the other defaults unless my environment requires different values.
9. Run local-bridge doctor, then local-bridge doctor --live, and fix any failures. Do not run the optional hosted web-search probe unless I explicitly approve possible provider usage.
10. Register the bridge only in this project's .codex/config.toml as the local-worker STDIO MCP server. Preserve unrelated project settings. Configure startup_timeout_sec = 10, tool_timeout_sec = 7200, enable only delegate_local, and set its output_token_limit = 5000. Do not add it to ~/.codex/config.toml.
11. Merge the bridge repository's templates/AGENTS.md guidance into this project's root AGENTS.md without overwriting existing project instructions. Do not modify ~/.codex/AGENTS.md.
12. Run an end-to-end, read-only delegation smoke test from a fresh Codex session. Do not modify a real project during the smoke test.
13. Report what you installed or changed, exact config paths, selected runtime/endpoint/model, test results, and anything I still need to do. Never print secrets or credential-file contents.
```

### Claude Code setup prompt

```text
Set up Local AI Bridge for me, using Claude Code as the parent agent, from:
https://github.com/CalebCurry/local-ai-bridge

Work autonomously and verify the complete Claude Code → MCP → DeepSeek Harness → local-model path. Enable delegation only for the project repository where I invoked you, not globally for every Claude Code project.

1. Inspect my OS, shell, Python, Node.js, Claude Code, DeepSeek Harness, and local model runtimes before changing anything.
2. Clone the repository into an appropriate development directory, read its README, create a Python virtual environment, and install the package.
3. If DeepSeek Harness is missing, install it using its current official instructions. Do not overwrite existing Harness settings, credentials, sessions, or model-provider configuration.
4. Prefer llama.cpp as the local inference runtime. First look for an existing llama.cpp server and compatible local GGUF coding model. If llama.cpp is not installed and no suitable runtime is already working, install it using its current official instructions. Start it on localhost with an OpenAI-compatible endpoint, tool calling enabled, and a stable model alias.
5. LM Studio and Ollama are supported alternatives. If I already have a healthy LM Studio or Ollama endpoint and model, preserve and use it instead of forcing a migration. If llama.cpp is unsuitable for my platform, offer LM Studio first and Ollama second.
6. Never download a large model without asking me first. If no working endpoint/model can be identified, ask me one concise question that includes the llama.cpp recommendation and the LM Studio/Ollama alternatives.
7. Configure DeepSeek Harness so its headless profile uses the chosen local model. Confirm a harmless headless prompt succeeds.
8. Create ~/.config/local-bridge/config.toml with the correct dsh_command. Keep the other defaults unless my environment requires different values.
9. Run local-bridge doctor, then local-bridge doctor --live, and fix any failures. Do not run the optional hosted web-search probe unless I explicitly approve possible provider usage.
10. Register the bridge in Claude Code as a project-scoped local-worker STDIO MCP server. Preserve all unrelated entries in this project's .mcp.json. Do not register it at user scope.
11. Merge the bridge repository's templates/CLAUDE.md guidance into this project's root CLAUDE.md without overwriting existing project instructions. Do not modify ~/.claude/CLAUDE.md.
12. Run an end-to-end, read-only delegation smoke test from a fresh Claude Code session. Do not modify a real project during the smoke test.
13. Report what you installed or changed, exact config paths, selected runtime/endpoint/model, test results, and anything I still need to do. Never print secrets or credential-file contents.
```

The agent should only need your input when it cannot identify a working local endpoint and model automatically, or before downloading a large model.

## Quickstart

You need Python 3.11+, Node.js, Git, either Codex or Claude Code, and a local OpenAI-compatible model endpoint.

### 1. Start a local model server

#### Recommended: llama.cpp

[llama.cpp](https://github.com/ggml-org/llama.cpp) is the default recommendation because it is lightweight, cross-platform, supports GGUF models, exposes OpenAI-compatible endpoints, and supports tool calling. Install it using [llama.cpp's current installation options](https://github.com/ggml-org/llama.cpp#quick-start), then start a server with a local GGUF model:

```bash
llama serve \
  --model /absolute/path/to/model.gguf \
  --alias local-coder \
  --host 127.0.0.1 \
  --port 8080 \
  --jinja
```

You can also let llama.cpp fetch a compatible GGUF model from Hugging Face:

```bash
llama serve \
  -hf <organization>/<model-repository>:<quantization> \
  --alias local-coder \
  --host 127.0.0.1 \
  --port 8080 \
  --jinja
```

For example, choose a GPT-OSS 20B GGUF quantization that fits your hardware. Model downloads can be large, so select the model and quantization intentionally.

Harness values:

- Base URL: `http://127.0.0.1:8080/v1`
- Model ID: `local-coder`
- API type: OpenAI-compatible chat completions
- API key: a non-secret placeholder if Harness requires one

The `--jinja` flag enables OpenAI-style function/tool calling for compatible model templates. Keep the server bound to `127.0.0.1` unless you intentionally secure and expose it to a network.

#### Alternative: LM Studio

Load a tool-capable coding model in LM Studio, then enable the server from its Developer tab or run:

```bash
lms server start --port 1234
```

Harness values:

- Base URL: `http://127.0.0.1:1234/v1`
- Model ID: the identifier shown by LM Studio for the loaded model
- API type: OpenAI-compatible chat completions

See [LM Studio's local server documentation](https://lmstudio.ai/docs/developer/core/server).

#### Alternative: Ollama

Install Ollama, pull a tool-capable coding model, and ensure its server is running:

```bash
ollama pull gpt-oss:20b
ollama serve
```

Harness values:

- Base URL: `http://127.0.0.1:11434/v1`
- Model ID: `gpt-oss:20b` or the model you pulled
- API type: OpenAI-compatible chat completions
- API key: `ollama` if Harness requires one; Ollama ignores it locally

See Ollama's [OpenAI compatibility documentation](https://docs.ollama.com/api/openai-compatibility).

Whichever runtime you use, verify its model list before continuing:

```bash
curl http://127.0.0.1:8080/v1/models   # llama.cpp
curl http://127.0.0.1:1234/v1/models   # LM Studio
curl http://127.0.0.1:11434/v1/models  # Ollama
```

Only one of these servers is required.

### 2. Install and configure DeepSeek Harness

The official Harness quickstart uses `npx`:

```bash
npx @deepseek-ai/dsh web
```

This opens the Harness UI. In its model settings, add the llama.cpp provider using the values above and select its model as the default. If you chose LM Studio or Ollama, use that alternative's URL and model ID instead.

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

### 3. Install Local Bridge

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

Inspect the effective Harness profile and its declared capabilities:

```bash
./.venv/bin/local-bridge doctor
```

Then make the configured local model prove that it can use filesystem, shell, public web-fetch, and spawn-subagent tools. The command uses and removes an isolated temporary workspace:

```bash
./.venv/bin/local-bridge doctor --live
```

Hosted `web_search` is separate from free public URL fetching. Its shipped provider requires `DEEPSEEK_API_KEY` and may consume paid provider usage, so it is never called by the ordinary live probe. Test it only when intended:

```bash
./.venv/bin/local-bridge doctor --live --web-search
```

### 4. Connect your parent agent

Choose one option. You do not need to configure both. Run these steps in the project where you want delegation enabled, not in the Local AI Bridge checkout:

```bash
cd /absolute/path/to/your-project
```

The bridge stays installed once, while each project opts in separately.

#### Option A: Codex

Create `.codex/config.toml` in the target project and add the following. If the file already exists, merge this table without replacing its other settings:

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

Do not add this table to `~/.codex/config.toml`. Codex loads project-scoped `.codex/config.toml` only for trusted projects. The long tool timeout matters because local-model coding loops commonly exceed the default MCP timeout.

Start a fresh Codex session from the target project, then verify the server with:

```bash
codex mcp get local-worker
```

Ask Codex to try it:

> Use `local-worker` to inspect this repository and run a harmless read-only smoke test. Do not modify files.

#### Option B: Claude Code

From the target project, register the bridge at project scope:

```bash
claude mcp add --transport stdio --scope project local-worker -- \
  /absolute/path/to/local-ai-bridge/.venv/bin/local-bridge serve
```

This writes the server entry to the project's `.mcp.json`. Because the example uses a machine-specific absolute path, review it before committing it. Do not use `--scope user` unless you intentionally want the tool available in every project.

Verify the registration:

```bash
claude mcp get local-worker
```

Start a fresh Claude Code session and run `/mcp` to check the server status. Then ask Claude Code to try it:

> Use `local-worker` to inspect this repository and run a harmless read-only smoke test. Do not modify files.

That is the minimum MCP setup. Add the repository-level delegation policy below so the parent agent knows when to use the tool.

## Configuration

Local Bridge reads `~/.config/local-bridge/config.toml`. Set `LOCAL_BRIDGE_CONFIG` to use another path:

```bash
export LOCAL_BRIDGE_CONFIG=/absolute/path/to/config.toml
```

No Local Bridge configuration file is required if all defaults fit your environment. The task and absolute working directory are required on each MCP tool call; the parent agent supplies those automatically.

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
| `default_timeout_minutes` | Optional | `30` | Default wall-clock limit for one delegated task. The parent agent may request a different value, capped at 120 minutes. |
| `max_result_characters` | Optional | `16000` | Maximum final-answer characters returned to the parent agent. Successful Harness reasoning and tool logs are discarded. |

External requirements that configuration cannot replace:

| Requirement | Required? |
|---|---:|
| Python 3.11 or newer | Required |
| A working `dsh` or `npx @deepseek-ai/dsh` command | Required |
| A running local OpenAI-compatible model endpoint | Required |
| A Harness provider and default model | Required |
| Repository-level local-first instructions | Recommended |

Print the effective configuration:

```bash
local-bridge print-config
```

Audit the Harness executable, composed profile, tool availability, permission mode, approval channel, and hosted-search credential without invoking the model:

```bash
local-bridge doctor
```

Run an end-to-end capability test through the configured model:

```bash
local-bridge doctor --live
```

The live check requires proof files created by the filesystem tool, shell, public `web_fetch`, and a foreground child subagent. It removes the temporary workspace afterward. Use `--timeout-seconds <seconds>` to change its five-minute limit. Add `--web-search` only when a hosted search credential is configured and provider usage is acceptable.

## Enable delegation in a project

MCP registration makes the tool available in that repository; project instructions tell the parent agent when to use it. Keep this policy at repository scope so unrelated projects are unaffected. The supplied templates also require the parent agent to run `local-bridge doctor` before its first delegation in a session and report the results to the user; live and hosted-search probes remain explicitly controlled.

### Codex

For an explicit one-off request, say:

> Delegate routine implementation and verification to `local-worker`. Keep architecture and final review in Codex.

Merge [`templates/AGENTS.md`](templates/AGENTS.md) into `AGENTS.md` at the target repository root. If that file already exists, combine the guidance instead of overwriting it. Do not copy this policy to `~/.codex/AGENTS.md`.

Codex discovers root and nested project `AGENTS.md` files when a session starts, so begin a fresh session from the target repository after changing it. See the official [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) and [AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

### Claude Code

For an explicit one-off request, say:

> Delegate routine implementation and verification to `local-worker`. Keep architecture and final review in Claude Code.

Merge [`templates/CLAUDE.md`](templates/CLAUDE.md) into `CLAUDE.md` at the target repository root. If that file already exists, combine the guidance instead of overwriting it. Do not copy this policy to `~/.claude/CLAUDE.md`.

Claude Code loads project `CLAUDE.md` guidance when a session starts, so begin a fresh session from the target repository after changing it. See the official [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp) and [Claude Code memory documentation](https://code.claude.com/docs/en/memory).

Commit the project instruction file if the whole team should use delegation. Otherwise, leave the policy change uncommitted.

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

Remove the server from the parent agent you configured.

For Codex:

Remove the `[mcp_servers.local-worker]` and `[mcp_servers.local-worker.tools.delegate_local]` tables from the target project's `.codex/config.toml`.

For Claude Code:

```bash
claude mcp remove local-worker --scope project
```

Remove the delegation policy from the target project's `AGENTS.md` or `CLAUDE.md` while preserving its other project instructions. Removing the shared Local AI Bridge installation is optional and affects every project that points to it.

## License

MIT
