"""Configuration model for commit and rewrite command execution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from autocommit.constants import ALLOWED_TYPES, SCOPE_RE

DEFAULT_MODEL = "google/gemini-3.1-flash-lite"
DEFAULT_REASONING_EFFORT = "none"
REASONING_EFFORT_CHOICES = ("none", "minimal", "low", "medium", "high", "xhigh")


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key, str(default))
    try:
        return int(val)
    except ValueError:
        from autocommit.console import die

        die(f"invalid value for {key}: {val!r} (expected integer)")


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key, str(default))
    try:
        return float(val)
    except ValueError:
        from autocommit.console import die

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
        default_factory=lambda: os.environ.get("AUTOCOMMIT_MODEL", DEFAULT_MODEL)
    )
    reasoning_effort: str = field(
        default_factory=lambda: os.environ.get(
            "AUTOCOMMIT_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
        )
    )
    max_diff_chars: int = field(
        default_factory=lambda: _env_int("AUTOCOMMIT_MAX_DIFF_CHARS", 12000)
    )
    timeout: float = field(
        default_factory=lambda: _env_float("AUTOCOMMIT_TIMEOUT", 10.0)
    )
    bulk_threshold: int = field(
        default_factory=lambda: _env_int("AUTOCOMMIT_BULK_THRESHOLD", 50)
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

    def __post_init__(self) -> None:
        from autocommit.console import die

        if not self.model or not self.model.strip():
            die("model cannot be empty; check AUTOCOMMIT_MODEL or --model")
        if self.reasoning_effort not in REASONING_EFFORT_CHOICES:
            die(
                f"invalid reasoning_effort {self.reasoning_effort!r};"
                f" must be one of: {', '.join(REASONING_EFFORT_CHOICES)}"
            )
        if self.max_diff_chars < 0:
            die("max_diff_chars must be >= 0")
        if self.timeout <= 0:
            die("timeout must be > 0")
        if self.bulk_threshold < 0:
            die("bulk_threshold must be >= 0")
        if self.type is not None:
            self.type = self.type.strip()
            if not self.type or self.type not in ALLOWED_TYPES:
                die(
                    f"invalid commit type {self.type!r};"
                    f" must be one of: {', '.join(sorted(ALLOWED_TYPES))}"
                )
        if self.scope is not None:
            self.scope = self.scope.strip()
            if self.scope and not SCOPE_RE.match(self.scope):
                die(
                    f"invalid commit scope {self.scope!r};"
                    " use lowercase letters, digits, '.', '_', '/', or '-'"
                )
