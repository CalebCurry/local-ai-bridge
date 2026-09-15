"""Command-line entry point for Local Bridge."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys

from . import __version__
from .config import Config, load_config
from .server import serve


def doctor(config: Config) -> int:
    command = shlex.split(config.dsh_command)
    executable = shutil.which(command[0]) if command else None
    print(f"Config: dsh_command={config.dsh_command!r}")
    print(f"Config: profile={config.profile!r}")
    print(f"Config: default_timeout_minutes={config.default_timeout_minutes}")
    print(f"Config: max_result_characters={config.max_result_characters}")
    if executable is None:
        print(f"FAIL: executable not found: {command[0] if command else '(empty)'}")
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
        description="Expose a DeepSeek Harness coding agent to Codex over MCP.",
    )
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument(
        "--config",
        help="TOML config path (default: $LOCAL_BRIDGE_CONFIG or ~/.config/local-bridge/config.toml)",
    )
    subcommands = result.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="Run the STDIO MCP server")
    subcommands.add_parser("doctor", help="Validate configuration and the Harness command")
    subcommands.add_parser("print-config", help="Print effective configuration")
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
        raise SystemExit(doctor(config))
    elif args.command == "print-config":
        print_config(config)


if __name__ == "__main__":
    main()
