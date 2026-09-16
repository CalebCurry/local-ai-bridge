"""STDIO MCP server that delegates complete coding tasks to DeepSeek Harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
from typing import Any, TextIO

from .config import Config


SERVER_NAME = "local-deepseek-harness"
SERVER_VERSION = "0.2.0"


def worker_prompt(task: str) -> str:
    return f"""You are the local implementation worker delegated by a parent coding agent.

TASK
{task.strip()}

OPERATING RULES
- Begin using repository tools immediately. Inspect briefly, create or edit the first useful file, then iterate; do not plan the entire implementation in prose before acting.
- Own routine execution end to end: inspect the repository, implement, run relevant checks, fix failures, and review your diff.
- Follow repository instructions and existing patterns. Preserve unrelated user changes.
- Do not ask the user ordinary implementation questions. Make conservative, reversible decisions.
- Do not escalate ordinary coding, test, type, lint, formatting, or build failures. Investigate and retry them yourself.
- Escalate only for genuinely ambiguous requirements with materially different outcomes, a consequential architecture/security decision, or a blocker that remains after three serious attempts.
- Stay inside the supplied working directory unless the task explicitly requires otherwise.
- Keep the final response compact. Do not include a tool transcript or chain of thought.

FINAL RESPONSE FORMAT
STATUS: PASS or ESCALATE
FILES: comma-separated changed paths, or none
TESTS: concise commands and pass/fail results
SUMMARY: at most 5 short lines
BLOCKER: only when STATUS is ESCALATE
"""


def trim(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} characters]"


def stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        return process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        return process.communicate()


def run_delegate(config: Config, arguments: dict[str, Any]) -> tuple[str, bool]:
    task = arguments.get("task")
    workdir = arguments.get("workdir")
    max_minutes = arguments.get("max_minutes", config.default_timeout_minutes)

    if not isinstance(task, str) or not task.strip():
        return "task must be a non-empty string", True
    if not isinstance(workdir, str) or not os.path.isabs(workdir):
        return "workdir must be an absolute path", True
    directory = Path(workdir).resolve()
    if not directory.is_dir():
        return f"workdir is not a directory: {directory}", True
    if not isinstance(max_minutes, int) or isinstance(max_minutes, bool):
        return "max_minutes must be an integer", True

    timeout_minutes = min(max(max_minutes, 1), config.max_timeout_minutes)
    command = [
        *shlex.split(config.dsh_command),
        "--profile",
        config.profile,
        worker_prompt(task),
    ]
    popen_options: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
    process = subprocess.Popen(
        command,
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_minutes * 60)
    except subprocess.TimeoutExpired:
        stdout, stderr = stop_process(process)
        return (
            f"Local Harness timed out after {timeout_minutes} minutes.\n"
            f"Partial final output:\n{trim(stdout, config.max_error_characters)}\n"
            f"Diagnostics:\n{trim(stderr, config.max_error_characters)}",
            True,
        )

    if process.returncode != 0:
        return (
            f"Local Harness exited with code {process.returncode}.\n"
            f"Final output:\n{trim(stdout, config.max_error_characters)}\n"
            f"Diagnostics:\n{trim(stderr, config.max_error_characters)}",
            True,
        )

    result = trim(stdout, config.max_result_characters)
    if not result:
        return "Local Harness completed without a final response.", True
    return result, False


def _task_schema(config: Config) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Self-contained task and executable acceptance criteria.",
            },
            "workdir": {
                "type": "string",
                "description": "Absolute repository or workspace directory.",
            },
            "max_minutes": {
                "type": "integer",
                "minimum": 1,
                "maximum": config.max_timeout_minutes,
                "default": config.default_timeout_minutes,
                "description": "Hard wall-clock limit for this delegation.",
            },
        },
        "required": ["task", "workdir"],
        "additionalProperties": False,
    }


def _job_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "format": "uuid",
                "description": "Job identifier returned by delegate_local_start.",
            }
        },
        "required": ["job_id"],
        "additionalProperties": False,
    }


def tool_definition(config: Config) -> dict[str, Any]:
    """Return the legacy blocking tool definition for compatibility."""
    return {
        "name": "delegate_local",
        "description": (
            "Compatibility-only blocking delegation. Prefer delegate_local_start so the parent "
            "remains responsive while the local worker runs."
        ),
        "inputSchema": _task_schema(config),
        "annotations": {
            "title": "Delegate to local coding worker",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }


def tool_definitions(config: Config) -> list[dict[str, Any]]:
    mutating = {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    read_only = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    return [
        {
            "name": "delegate_local_start",
            "description": (
                "Start a complete local coding task in the background and immediately return a "
                "job ID. Use this instead of the blocking compatibility tool. After starting, "
                "remain available to the user; do not busy-poll."
            ),
            "inputSchema": _task_schema(config),
            "annotations": {"title": "Start local coding worker", **mutating},
        },
        {
            "name": "delegate_local_status",
            "description": (
                "Quickly inspect a background local job: state, elapsed time, log growth, "
                "workspace activity, and token usage when the provider exposes it."
            ),
            "inputSchema": _job_schema(),
            "annotations": {"title": "Check local worker", **read_only},
        },
        {
            "name": "delegate_local_result",
            "description": "Retrieve the concise final result and usage receipt for a background local job.",
            "inputSchema": _job_schema(),
            "annotations": {"title": "Get local worker result", **read_only},
        },
        {
            "name": "delegate_local_cancel",
            "description": "Cancel a background local job and its entire worker process group.",
            "inputSchema": _job_schema(),
            "annotations": {"title": "Cancel local worker", **mutating},
        },
        tool_definition(config),
    ]


def response_for(config: Config, request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if request_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Use delegate_local_start for routine, token-heavy coding execution. It "
                    "returns immediately with a job ID so you remain responsive to the user. "
                    "Do not busy-poll; use delegate_local_status when useful and "
                    "delegate_local_result after completion. Keep ambiguous architecture and "
                    "security-sensitive judgment in the parent agent."
                ),
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tool_definitions(config)},
        }
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if name == "delegate_local":
                output, is_error = run_delegate(config, params.get("arguments") or {})
            else:
                from .jobs import cancel_job, job_result, job_status, start_job

                if name == "delegate_local_start":
                    output, is_error = json.dumps(start_job(config, arguments), indent=2), False
                elif name == "delegate_local_status":
                    output, is_error = json.dumps(job_status(arguments.get("job_id")), indent=2), False
                elif name == "delegate_local_result":
                    output, is_error = job_result(config, arguments.get("job_id"))
                elif name == "delegate_local_cancel":
                    output, is_error = json.dumps(cancel_job(arguments.get("job_id")), indent=2), False
                else:
                    output, is_error = f"Unknown tool: {name}", True
        except Exception as exc:
            output = f"Local delegation failed: {type(exc).__name__}: {exc}"
            is_error = True
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": output}],
                "isError": is_error,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve(config: Config, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
    for line in input_stream:
        try:
            request = json.loads(line)
            response = response_for(config, request)
            if response is not None:
                print(json.dumps(response, separators=(",", ":")), file=output_stream, flush=True)
        except Exception as exc:
            error = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }
            print(json.dumps(error, separators=(",", ":")), file=output_stream, flush=True)
