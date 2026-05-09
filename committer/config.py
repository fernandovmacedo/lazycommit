"""Configuration model for commit and rewrite command execution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_MODEL = "google/gemini-3.1-flash-lite"
DEFAULT_REASONING_EFFORT = "none"
REASONING_EFFORT_CHOICES = ("none", "minimal", "low", "medium", "high", "xhigh")


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key, str(default))
    try:
        return int(val)
    except ValueError:
        from committer.console import die

        die(f"invalid value for {key}: {val!r} (expected integer)")


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key, str(default))
    try:
        return float(val)
    except ValueError:
        from committer.console import die

        die(f"invalid value for {key}: {val!r} (expected float)")


@dataclass
class Config:
    """Unified configuration for commit and rewrite subcommands."""

    subcommand: Literal["commit", "rewrite"]

    # Shared flags
    dry_run: bool = False
    push: bool = False
    silent: bool = False
    verbose: bool = False
    no_body: bool = False

    # Shared options loaded from CLI, env, or XDG config.
    model: str = field(
        default_factory=lambda: os.environ.get("COMMITTER_MODEL", DEFAULT_MODEL)
    )
    reasoning_effort: str = field(
        default_factory=lambda: os.environ.get(
            "COMMITTER_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
        )
    )
    max_diff_chars: int = field(
        default_factory=lambda: _env_int("COMMITTER_MAX_DIFF_CHARS", 12000)
    )
    timeout: float = field(
        default_factory=lambda: _env_float("COMMITTER_TIMEOUT", 10.0)
    )
    bulk_threshold: int = field(
        default_factory=lambda: _env_int("COMMITTER_BULK_THRESHOLD", 50)
    )
    force_ai: bool = False

    directory: str | None = None

    # Commit-only options
    type: str | None = None
    scope: str | None = None
    context: str | None = None
    git_args: tuple[str, ...] = ()

    # Rewrite-only options
    sha: str | None = None
    all_commits: bool = False
    non_conventional: bool = False
    unpushed: bool = False

    # Shared fallback behavior.
    fallback: str | None = None
