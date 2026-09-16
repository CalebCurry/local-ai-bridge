"""Persistent background-job support for local Harness delegations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any
from uuid import UUID, uuid4

from .config import Config
from .server import trim, worker_prompt


TERMINAL_STATUSES = {"passed", "failed", "timed_out", "cancelled"}
_RUNNERS: dict[int, subprocess.Popen[bytes]] = {}
_RUNNERS_LOCK = threading.Lock()


def _reap_runner(process: subprocess.Popen[bytes]) -> None:
    process.wait()
    with _RUNNERS_LOCK:
        _RUNNERS.pop(process.pid, None)


def jobs_root() -> Path:
    configured = os.environ.get("LOCAL_BRIDGE_JOBS_DIR")
    return Path(configured or "~/.local/state/local-bridge/jobs").expanduser()


def _job_directory(job_id: str) -> Path:
    try:
        canonical = str(UUID(job_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("job_id must be a valid UUID") from exc
    if canonical != job_id.lower():
        raise ValueError("job_id must be a canonical UUID")
    return jobs_root() / canonical


def _metadata_path(directory: Path) -> Path:
    return directory / "job.json"


def read_metadata(job_id: str) -> tuple[Path, dict[str, Any]]:
    directory = _job_directory(job_id)
    try:
        with _metadata_path(directory).open(encoding="utf-8") as handle:
            return directory, json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"unknown job_id: {job_id}") from exc


def write_metadata(directory: Path, metadata: dict[str, Any]) -> None:
    path = _metadata_path(directory)
    temporary = directory / "job.json.tmp"
    temporary.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _process_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _runner_pid(directory: Path, metadata: dict[str, Any]) -> int | None:
    pid = metadata.get("runner_pid")
    if isinstance(pid, int) and pid > 0:
        return pid
    try:
        return int((directory / "runner.pid").read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _reconcile(directory: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata.get("status") not in {"starting", "running"}:
        return metadata
    pid = _runner_pid(directory, metadata)
    if _process_alive(pid):
        return metadata
    metadata["status"] = "cancelled" if (directory / "cancel_requested").exists() else "failed"
    metadata["finished_at"] = time.time()
    metadata["detail"] = (
        "Cancellation completed."
        if metadata["status"] == "cancelled"
        else "Background runner exited before recording a result."
    )
    write_metadata(directory, metadata)
    return metadata


def _token_usage(stdout: str, stderr: str) -> dict[str, Any]:
    text = stdout + "\n" + stderr
    usage: dict[str, Any] = {}
    patterns = {
        "input_tokens": r'(?i)["\']?input[_ ]tokens["\']?\s*[:=]\s*(\d+)',
        "output_tokens": r'(?i)["\']?output[_ ]tokens["\']?\s*[:=]\s*(\d+)',
        "total_tokens": r'(?i)["\']?total[_ ]tokens["\']?\s*[:=]\s*(\d+)',
    }
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            usage[key] = int(matches[-1])
    generated = re.findall(r"\bn_gen\s*=\s*(\d+)", text)
    prompt = re.findall(r"prompt processing,\s*n_tokens\s*=\s*(\d+)", text)
    if generated and "output_tokens" not in usage:
        usage["output_tokens"] = int(generated[-1])
    if prompt and "input_tokens" not in usage:
        usage["input_tokens"] = int(prompt[-1])
    if "total_tokens" not in usage and {"input_tokens", "output_tokens"} <= usage.keys():
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return {"available": bool(usage), **usage}


def _read_log(directory: Path, name: str) -> str:
    try:
        return (directory / name).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _read_log_tail(directory: Path, name: str, limit: int = 256_000) -> str:
    try:
        with (directory / name).open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _log_size(directory: Path, name: str) -> int:
    try:
        return (directory / name).stat().st_size
    except FileNotFoundError:
        return 0


def _workspace_activity(workdir: str, started_at: float) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", workdir, "status", "--short"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0:
        return result.stdout.splitlines()[:50]

    root = Path(workdir)
    changed: list[str] = []
    try:
        for path in root.rglob("*"):
            if not path.is_file() or {".git", "node_modules"} & set(path.parts):
                continue
            try:
                if path.stat().st_mtime >= started_at:
                    changed.append(str(path.relative_to(root)))
            except OSError:
                continue
            if len(changed) == 50:
                break
    except OSError:
        pass
    return sorted(changed)


def start_job(config: Config, arguments: dict[str, Any]) -> dict[str, Any]:
    task = arguments.get("task")
    workdir = arguments.get("workdir")
    max_minutes = arguments.get("max_minutes", config.default_timeout_minutes)
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if not isinstance(workdir, str) or not os.path.isabs(workdir):
        raise ValueError("workdir must be an absolute path")
    directory = Path(workdir).resolve()
    if not directory.is_dir():
        raise ValueError(f"workdir is not a directory: {directory}")
    if not isinstance(max_minutes, int) or isinstance(max_minutes, bool):
        raise ValueError("max_minutes must be an integer")

    timeout_minutes = min(max(max_minutes, 1), config.max_timeout_minutes)
    job_id = str(uuid4())
    root = jobs_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    job_directory = root / job_id
    job_directory.mkdir(mode=0o700)
    (job_directory / "prompt.txt").write_text(worker_prompt(task), encoding="utf-8")
    started_at = time.time()
    metadata: dict[str, Any] = {
        "job_id": job_id,
        "status": "starting",
        "workdir": str(directory),
        "profile": config.profile,
        "timeout_minutes": timeout_minutes,
        "started_at": started_at,
    }
    write_metadata(job_directory, metadata)

    command = [
        sys.executable,
        "-m",
        "local_bridge.job_runner",
        "--job-directory",
        str(job_directory),
        "--dsh-command",
        config.dsh_command,
        "--profile",
        config.profile,
        "--timeout-minutes",
        str(timeout_minutes),
    ]
    popen_options: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
    runner = subprocess.Popen(
        command,
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_options,
    )
    with _RUNNERS_LOCK:
        _RUNNERS[runner.pid] = runner
    threading.Thread(target=_reap_runner, args=(runner,), daemon=True).start()
    (job_directory / "runner.pid").write_text(f"{runner.pid}\n", encoding="utf-8")
    return {
        "job_id": job_id,
        "status": "running",
        "message": "Local worker started in the background. Do not block or busy-poll; remain available to the user and check status when useful.",
    }


def job_status(job_id: str) -> dict[str, Any]:
    directory, metadata = read_metadata(job_id)
    metadata = _reconcile(directory, metadata)
    stdout_tail = _read_log_tail(directory, "stdout.log")
    stderr_tail = _read_log_tail(directory, "stderr.log")
    finished_at = metadata.get("finished_at")
    elapsed = max(0, (finished_at or time.time()) - float(metadata["started_at"]))
    return {
        "job_id": job_id,
        "status": metadata["status"],
        "elapsed_seconds": round(elapsed, 1),
        "timeout_minutes": metadata["timeout_minutes"],
        "workdir": metadata["workdir"],
        "runner_pid": _runner_pid(directory, metadata),
        "stdout_bytes": _log_size(directory, "stdout.log"),
        "diagnostic_bytes": _log_size(directory, "stderr.log"),
        "token_usage": _token_usage(stdout_tail, stderr_tail),
        "workspace_activity": _workspace_activity(
            metadata["workdir"], float(metadata["started_at"])
        ),
        "detail": metadata.get("detail"),
    }


def list_jobs() -> list[dict[str, Any]]:
    root = jobs_root()
    if not root.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    directories = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for directory in directories:
        try:
            status = job_status(directory.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        summaries.append(
            {
                "job_id": status["job_id"],
                "status": status["status"],
                "elapsed_seconds": status["elapsed_seconds"],
                "workdir": status["workdir"],
            }
        )
    return summaries


def job_result(config: Config, job_id: str) -> tuple[str, bool]:
    directory, metadata = read_metadata(job_id)
    metadata = _reconcile(directory, metadata)
    if metadata["status"] not in TERMINAL_STATUSES:
        return json.dumps(job_status(job_id), indent=2), False
    stdout = _read_log(directory, "stdout.log")
    stderr_tail = _read_log_tail(directory, "stderr.log")
    usage = _token_usage(stdout, stderr_tail)
    receipt = json.dumps(
        {
            "job_id": job_id,
            "status": metadata["status"],
            "elapsed_seconds": round(
                float(metadata.get("finished_at", time.time()))
                - float(metadata["started_at"]),
                1,
            ),
            "token_usage": usage,
        },
        indent=2,
    )
    if metadata["status"] == "passed" and stdout.strip():
        return f"{trim(stdout, config.max_result_characters)}\n\nRECEIPT:\n{receipt}", False
    diagnostics = trim(stderr_tail, config.max_error_characters)
    output = trim(stdout, config.max_error_characters)
    return (
        f"Local Harness status: {metadata['status']}.\n"
        f"{metadata.get('detail', '')}\n"
        f"Partial final output:\n{output}\n"
        f"Diagnostics:\n{diagnostics}\n\nRECEIPT:\n{receipt}",
        True,
    )


def cancel_job(job_id: str) -> dict[str, Any]:
    directory, metadata = read_metadata(job_id)
    metadata = _reconcile(directory, metadata)
    if metadata["status"] in TERMINAL_STATUSES:
        return {"job_id": job_id, "status": metadata["status"], "message": "Job is already finished."}
    (directory / "cancel_requested").write_text("requested\n", encoding="utf-8")
    pid = _runner_pid(directory, metadata)
    if pid is None:
        return {"job_id": job_id, "status": "cancelling", "message": "Cancellation was recorded before the runner initialized."}
    try:
        if os.name == "posix":
            os.killpg(int(pid), signal.SIGTERM)
        else:
            os.kill(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    return {"job_id": job_id, "status": "cancelling", "message": "Cancellation signal sent to the worker process group."}
