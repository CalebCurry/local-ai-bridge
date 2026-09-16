"""Configuration loading for Local Bridge."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib


DEFAULT_CONFIG_PATH = Path("~/.config/local-bridge/config.toml").expanduser()


@dataclass(frozen=True)
class Config:
    dsh_command: str = "npx --yes @deepseek-ai/dsh"
    profile: str = "headless"
    default_timeout_minutes: int = 30
    max_result_characters: int = 16_000
    max_timeout_minutes: int = 120
    max_error_characters: int = 6_000


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def load_config(path: str | Path | None = None) -> Config:
    """Load config, returning defaults when the optional file does not exist."""
    selected = Path(
        path or os.environ.get("LOCAL_BRIDGE_CONFIG", DEFAULT_CONFIG_PATH)
    ).expanduser()
    if not selected.exists():
        return Config()

    with selected.open("rb") as handle:
        document = tomllib.load(handle)
    raw = document.get("local_bridge", {})
    if not isinstance(raw, dict):
        raise ValueError("[local_bridge] must be a TOML table")

    allowed = {
        "dsh_command",
        "profile",
        "default_timeout_minutes",
        "max_result_characters",
    }
    unknown = set(raw) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown local_bridge config option(s): {names}")

    dsh_command = raw.get("dsh_command", "npx --yes @deepseek-ai/dsh")
    profile = raw.get("profile", "headless")
    if not isinstance(dsh_command, str) or not dsh_command.strip():
        raise ValueError("dsh_command must be a non-empty string")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("profile must be a non-empty string")

    default_timeout_minutes = _positive_int(
        raw.get("default_timeout_minutes", 30), "default_timeout_minutes"
    )
    if default_timeout_minutes > Config.max_timeout_minutes:
        raise ValueError(
            f"default_timeout_minutes cannot exceed {Config.max_timeout_minutes}"
        )

    return Config(
        dsh_command=dsh_command.strip(),
        profile=profile.strip(),
        default_timeout_minutes=default_timeout_minutes,
        max_result_characters=_positive_int(
            raw.get("max_result_characters", 16_000), "max_result_characters"
        ),
    )
