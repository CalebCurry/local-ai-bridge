"""Command-line entry point for Local Bridge."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from . import __version__
from .config import Config, load_config
from .server import serve


@dataclass(frozen=True)
class CapabilityAudit:
    filesystem: bool
    workspace_write: bool
    shell: bool
    web_fetch: bool
    web_search: bool
    web_search_detail: str
    subagents: bool
    permission_mode: str
    approval_detail: str


def _plugin_blocks(document: str) -> dict[str, str]:
    """Return composed profile rows keyed by plugin id."""
    matches = list(re.finditer(r"(?m)^- id:\s*([^\s#]+)\s*$", document))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        blocks[match.group(1)] = document[match.start() : end]
    return blocks


def _enabled(blocks: dict[str, str], plugin_id: str) -> bool:
    block = blocks.get(plugin_id)
    return block is not None and re.search(r"(?m)^\s+disabled:\s*true\s*$", block) is None


def _field(block: str, name: str) -> str | None:
    match = re.search(rf"(?m)^\s+{re.escape(name)}:\s*['\"]?([^\s'\"]+)", block)
    return match.group(1) if match else None


def _permission_mode(blocks: dict[str, str]) -> str:
    override = os.environ.get("DSH_PERMISSION_MODE")
    if override:
        return override
    block = blocks.get("sandbox-policy", "")
    literal = re.search(
        r"(?m)^\s+mode:\s*(read-only|workspace-write|danger-full-access)\s*$", block
    )
    if literal:
        return literal.group(1)
    fallback = re.search(
        r"DSH_PERMISSION_MODE\s*\?\?\s*['\"]([^'\"]+)['\"]", block
    )
    return fallback.group(1) if fallback else "unknown"


def _credential_present(name: str, dsh_home: Path | None = None) -> bool:
    if os.environ.get(name):
        return True
    home = dsh_home or Path(os.environ.get("DSH_HOME", "~/.dsh")).expanduser()
    path = home / ".credentials.yaml"
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        re.search(rf"(?m)^\s*{re.escape(name)}\s*:\s*\S+\s*$", contents)
        is not None
    )


def inspect_capabilities(document: str) -> CapabilityAudit:
    blocks = _plugin_blocks(document)
    mode = _permission_mode(blocks)
    filesystem = _enabled(blocks, "tool-fs") and _enabled(blocks, "fs-sandbox")
    shell_id = "tool-pwsh" if os.name == "nt" else "tool-bash"
    shell_executor = "pwsh-sandbox" if os.name == "nt" else "bash-sandbox"
    shell = _enabled(blocks, shell_id) and _enabled(blocks, shell_executor)
    tool_web = _enabled(blocks, "tool-web")
    web_fetch = tool_web and _enabled(blocks, "web-fetch-http")
    search_provider = _field(blocks.get("web", ""), "searchProvider")
    search_plugin = _enabled(blocks, "web-search-deepseek")
    if not tool_web or not search_provider:
        web_search = False
        web_search_detail = "no search tool/provider in the composed profile"
    elif search_provider == "deepseek-official" and search_plugin:
        credential_name = _field(
            blocks.get("web-search-deepseek", ""), "apiKeyEnv"
        ) or "DEEPSEEK_API_KEY"
        web_search = _credential_present(credential_name)
        web_search_detail = (
            f"credential {credential_name} is configured"
            if web_search
            else f"missing {credential_name}; llama.cpp does not provide hosted search"
        )
    else:
        web_search = True
        web_search_detail = f"provider {search_provider} is configured"
    subagents = (
        _enabled(blocks, "subagent")
        and _enabled(blocks, "subagent-spawn-in-process")
        and _enabled(blocks, "tool-subagent")
    )
    approval_detail = (
        "not needed in danger-full-access mode"
        if mode == "danger-full-access"
        else "unavailable in one-shot headless mode; approval-required actions fail closed"
    )
    return CapabilityAudit(
        filesystem=filesystem,
        workspace_write=filesystem and mode in {"workspace-write", "danger-full-access"},
        shell=shell,
        web_fetch=web_fetch,
        web_search=web_search,
        web_search_detail=web_search_detail,
        subagents=subagents,
        permission_mode=mode,
        approval_detail=approval_detail,
    )


def _status(label: str, passed: bool, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"{'PASS' if passed else 'UNAVAILABLE'}: {label}{suffix}")


def _live_probe_prompt(include_web_search: bool) -> str:
    search_step = (
        """
5. Call web_search for the official Python website. If it returns at least one source URL,
   use a filesystem tool to write that URL to web-search-proof.txt.
"""
        if include_web_search
        else ""
    )
    return f"""Run a Local AI Bridge capability test in this temporary workspace.
You must actually use the named tools; do not merely claim success.

1. Use a filesystem tool to write exactly FS_OK to fs-proof.txt.
2. Use the shell tool to write exactly SHELL_OK to shell-proof.txt.
3. Call web_fetch for https://example.com/. If the fetched page contains Example Domain,
   use a filesystem tool to write exactly WEB_FETCH_OK to web-fetch-proof.txt.
4. Call the spawn subagent tool in the foreground with a self-contained request to reply
   exactly SUBAGENT_OK. Only if its returned result contains SUBAGENT_OK, use a filesystem
   tool to write exactly SUBAGENT_OK to subagent-proof.txt.
{search_step}
Attempt every step even if an earlier one fails. Finish with a concise summary.
"""


def run_live_probes(
    command: list[str], profile: str, timeout_seconds: int, include_web_search: bool
) -> bool:
    print("Live probes: starting one local-agent run in an isolated temporary workspace")
    with tempfile.TemporaryDirectory(prefix="local-bridge-doctor-") as directory:
        try:
            result = subprocess.run(
                [*command, "--profile", profile, _live_probe_prompt(include_web_search)],
                cwd=directory,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"FAIL: live capability probes could not complete: {exc}")
            return False

        root = Path(directory)
        proofs = {
            "Filesystem tool": ("fs-proof.txt", "FS_OK"),
            "Shell tool": ("shell-proof.txt", "SHELL_OK"),
            "Public web fetch": ("web-fetch-proof.txt", "WEB_FETCH_OK"),
            "Spawn subagent": ("subagent-proof.txt", "SUBAGENT_OK"),
        }
        if include_web_search:
            proofs["Hosted web search"] = ("web-search-proof.txt", None)

        passed = result.returncode == 0
        for label, (filename, expected) in proofs.items():
            try:
                value = (root / filename).read_text(encoding="utf-8").strip()
            except OSError:
                value = ""
            proof_passed = bool(value) if expected is None else value == expected
            _status(
                label,
                proof_passed,
                "live proof file verified" if proof_passed else "proof missing",
            )
            passed = passed and proof_passed

        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            print(
                f"FAIL: Harness live probe exited with code {result.returncode}: "
                f"{details[-2000:]}"
            )
        return passed


def doctor(
    config: Config,
    *,
    live: bool = False,
    web_search: bool = False,
    timeout_seconds: int = 300,
) -> int:
    command = shlex.split(config.dsh_command)
    executable = shutil.which(command[0]) if command else None
    print(f"Config: dsh_command={config.dsh_command!r}")
    print(f"Config: profile={config.profile!r}")
    print(f"Config: default_timeout_minutes={config.default_timeout_minutes}")
    print(f"Config: max_result_characters={config.max_result_characters}")
    if executable is None:
        attempted = command[0] if command else "(empty)"
        print(f"FAIL: executable not found: {attempted}")
        if attempted == "dsh":
            print(
                'HINT: replace dsh_command = "dsh" with '
                'dsh_command = "npx --offline --yes @deepseek-ai/dsh" in '
                "~/.config/local-bridge/config.toml"
            )
        elif attempted == "npx":
            print("HINT: install Node.js/npm so npx is available, or use an absolute npx path")
        return 1
    print(f"PASS: executable found: {executable}")
    try:
        result = subprocess.run(
            [*command, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: could not run Harness: {exc}")
        return 1
    version_output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        print(f"FAIL: Harness exited with code {result.returncode}: {version_output}")
        return 1
    print(f"PASS: DeepSeek Harness responds: {version_output}")
    try:
        profile_result = subprocess.run(
            [*command, "--profile", config.profile, "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: could not inspect Harness profile {config.profile!r}: {exc}")
        return 1
    if profile_result.returncode != 0:
        details = (profile_result.stdout or profile_result.stderr).strip()
        print(
            f"FAIL: Harness profile {config.profile!r} is unavailable "
            f"(exit {profile_result.returncode}): {details}"
        )
        return 1
    print(f"PASS: Harness profile is available: {config.profile}")
    try:
        dump_result = subprocess.run(
            [*command, "--profile", config.profile, "--dump-config"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: could not inspect composed Harness capabilities: {exc}")
        return 1
    if dump_result.returncode != 0:
        details = (dump_result.stdout or dump_result.stderr).strip()
        print(f"FAIL: Harness configuration dump failed: {details}")
        return 1

    audit = inspect_capabilities(dump_result.stdout)
    print("Capabilities declared by the composed profile:")
    _status("Filesystem read", audit.filesystem)
    _status("Workspace write", audit.workspace_write)
    _status("Shell", audit.shell)
    _status("Public web fetch", audit.web_fetch)
    _status("Hosted web search", audit.web_search, audit.web_search_detail)
    _status("Spawn subagents", audit.subagents)
    print(f"INFO: Permission mode — {audit.permission_mode}")
    print(f"INFO: Approval channel — {audit.approval_detail}")

    essential = audit.filesystem and audit.workspace_write and audit.shell
    if not essential:
        print("FAIL: the selected profile lacks an essential coding capability")
        return 1
    if web_search and not live:
        print("FAIL: --web-search requires --live")
        return 2
    if web_search and not audit.web_search:
        print(f"FAIL: cannot probe hosted web search: {audit.web_search_detail}")
        return 1
    if live and not run_live_probes(command, config.profile, timeout_seconds, web_search):
        return 1
    if not live:
        print("INFO: Add --live to verify tool execution with the configured local model")
    return 0


def print_config(config: Config) -> None:
    print(
        json.dumps(
            {
                "dsh_command": config.dsh_command,
                "profile": config.profile,
                "default_timeout_minutes": config.default_timeout_minutes,
                "max_result_characters": config.max_result_characters,
            },
            indent=2,
        )
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="local-bridge",
        description="Expose a DeepSeek Harness coding agent to a parent agent over MCP.",
    )
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument(
        "--config",
        help="TOML config path (default: $LOCAL_BRIDGE_CONFIG or ~/.config/local-bridge/config.toml)",
    )
    subcommands = result.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="Run the STDIO MCP server")
    doctor_parser = subcommands.add_parser(
        "doctor", help="Audit Harness configuration and local-agent capabilities"
    )
    doctor_parser.add_argument(
        "--live",
        action="store_true",
        help="Run filesystem, shell, public-fetch, and subagent probes with the configured model",
    )
    doctor_parser.add_argument(
        "--web-search",
        action="store_true",
        help="Also run hosted web search (requires --live and may incur provider usage)",
    )
    doctor_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Timeout for the combined live probe (default: 300)",
    )
    subcommands.add_parser("print-config", help="Print effective configuration")
    subcommands.add_parser("jobs", help="List background delegation jobs")
    status_parser = subcommands.add_parser("job-status", help="Inspect a background job")
    status_parser.add_argument("job_id")
    result_parser = subcommands.add_parser("job-result", help="Print a background job result")
    result_parser.add_argument("job_id")
    cancel_parser = subcommands.add_parser("job-cancel", help="Cancel a background job")
    cancel_parser.add_argument("job_id")
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"local-bridge: configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.command in (None, "serve"):
        serve(config)
    elif args.command == "doctor":
        if args.timeout_seconds <= 0:
            parser().error("--timeout-seconds must be positive")
        raise SystemExit(
            doctor(
                config,
                live=args.live,
                web_search=args.web_search,
                timeout_seconds=args.timeout_seconds,
            )
        )
    elif args.command == "print-config":
        print_config(config)
    elif args.command in {"jobs", "job-status", "job-result", "job-cancel"}:
        from .jobs import cancel_job, job_result, job_status, list_jobs

        try:
            if args.command == "jobs":
                print(json.dumps(list_jobs(), indent=2))
            elif args.command == "job-status":
                print(json.dumps(job_status(args.job_id), indent=2))
            elif args.command == "job-result":
                output, is_error = job_result(config, args.job_id)
                print(output)
                if is_error:
                    raise SystemExit(1)
            else:
                print(json.dumps(cancel_job(args.job_id), indent=2))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"local-bridge: job error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
