"""Detached runner used by Local Bridge background jobs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time
from typing import Any

from .jobs import write_metadata


_cancelled = False


def _mark_cancelled(_signum: int, _frame: object) -> None:
    global _cancelled
    _cancelled = True


def _terminate_group() -> None:
    if os.name == "posix":
        os.killpg(os.getpgrp(), signal.SIGTERM)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--job-directory", required=True)
    result.add_argument("--dsh-command", required=True)
    result.add_argument("--profile", required=True)
    result.add_argument("--timeout-minutes", required=True, type=int)
    return result


def main() -> int:
    args = parser().parse_args()
    directory = Path(args.job_directory)
    metadata_path = directory / "job.json"
    metadata: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
    prompt = (directory / "prompt.txt").read_text(encoding="utf-8")
    signal.signal(signal.SIGTERM, _mark_cancelled)
    signal.signal(signal.SIGINT, _mark_cancelled)
    metadata["runner_pid"] = os.getpid()
    if (directory / "cancel_requested").exists():
        metadata["status"] = "cancelled"
        metadata["finished_at"] = time.time()
        metadata["detail"] = "Cancelled before Harness started."
        write_metadata(directory, metadata)
        return 0
    metadata["status"] = "running"
    write_metadata(directory, metadata)
    command = [*shlex.split(args.dsh_command), "--profile", args.profile, prompt]

    with (directory / "stdout.log").open("w", encoding="utf-8") as stdout, (
        directory / "stderr.log"
    ).open("w", encoding="utf-8") as stderr:
        try:
            process = subprocess.Popen(
                command,
                cwd=metadata["workdir"],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                text=True,
            )
        except OSError as exc:
            print(f"Could not start Harness: {exc}", file=stderr, flush=True)
            metadata["status"] = "failed"
            metadata["finished_at"] = time.time()
            metadata["detail"] = f"Could not start Harness: {exc}"
            write_metadata(directory, metadata)
            return 1
        metadata["worker_pid"] = process.pid
        write_metadata(directory, metadata)
        timed_out = False
        try:
            process.wait(timeout=args.timeout_minutes * 60)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_group()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    metadata["finished_at"] = time.time()
    metadata["returncode"] = process.returncode
    if (directory / "cancel_requested").exists():
        metadata["status"] = "cancelled"
        metadata["detail"] = "Cancelled by the parent or user."
    elif timed_out:
        metadata["status"] = "timed_out"
        metadata["detail"] = f"Exceeded the {args.timeout_minutes}-minute hard limit."
    elif _cancelled:
        metadata["status"] = "cancelled"
        metadata["detail"] = "Cancelled because the parent process sent a termination signal."
    elif process.returncode == 0:
        metadata["status"] = "passed"
        metadata["detail"] = "Harness exited successfully."
    else:
        metadata["status"] = "failed"
        metadata["detail"] = f"Harness exited with code {process.returncode}."
    write_metadata(directory, metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
