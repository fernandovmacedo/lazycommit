"""Git subprocess helpers, XDG config loading, and prompt context assembly."""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Sequence

from lazycommit.console import warn
from lazycommit.constants import DIFF_EXCLUDE_PATTERNS, GIT_TIMEOUT_S
from lazycommit.logger import log_debug, log_warning


def run_git(*args: str) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    label = " ".join(args[:2]) if len(args) >= 2 else args[0] if args else "git"
    log_debug(f"git {label} → start")
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        log_debug(f"git {label} → timeout after {GIT_TIMEOUT_S}s")
        return None
    if result.returncode != 0:
        log_debug(f"git {label} → exit {result.returncode}")
        return None
    log_debug(f"git {label} → ok ({len(result.stdout)} chars)")
    return result.stdout.strip() or ""


def has_staged_changes() -> bool:
    """Check if there are staged changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode != 0


def get_repo_root() -> str | None:
    """Get the repository root path, or None if not in a repo."""
    return run_git("rev-parse", "--show-toplevel")


def auto_stage(git_args: Sequence[str]) -> bool:
    """Stage all changes only when nothing is staged and ``--amend`` is absent."""
    if "--amend" in git_args:
        return True
    if has_staged_changes():
        return True
    try:
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        msg = f"git add -A timed out after {GIT_TIMEOUT_S}s"
        log_warning(msg)
        warn(f"{msg}; commit was not created")
        return False
    return True


def get_staged_diff() -> str:
    """Get the staged diff, excluding lockfiles."""
    diff = run_git(
        "diff",
        "--cached",
        "--",
        ".",
        *DIFF_EXCLUDE_PATTERNS,
    )
    if diff is None:
        return ""
    lines = [line for line in diff.splitlines() if not line.startswith("Binary files ")]
    return "\n".join(lines).strip()


def get_staged_files() -> list[str]:
    """Get list of staged files with status."""
    raw = run_git("diff", "--cached", "--name-status")
    if not raw:
        return []
    return [line for line in raw.splitlines() if line.strip()]


def get_staged_stat() -> str:
    """Get diff stats for staged changes."""
    stat = run_git("diff", "--cached", "--stat")
    numstat = run_git("diff", "--cached", "--numstat")
    if stat and numstat:
        return f"{stat}\n\n{numstat}".strip()
    return stat or numstat or ""


def get_branch_name() -> str:
    """Get the current branch name."""
    branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
    return branch or "(detached)"


def get_recent_commits() -> str:
    """Get recent commit messages for style reference."""
    result = run_git("log", "--oneline", "-5")
    return result or ""


def load_xdg_config() -> None:
    """Load config from XDG config directory if available.

    Reads from $XDG_CONFIG_HOME/lazycommit/config.toml (defaults to
    ~/.config/lazycommit/config.toml). Sets environment variables for
    LAZYCOMMIT_MODEL, LAZYCOMMIT_REASONING_EFFORT,
    LAZYCOMMIT_MAX_DIFF_CHARS, LAZYCOMMIT_TIMEOUT, and
    LAZYCOMMIT_BULK_THRESHOLD. Does not override existing environment
    variables.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
        "~/.config"
    )
    config_path = os.path.join(xdg_config_home, "lazycommit", "config.toml")

    if not os.path.isfile(config_path):
        return

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        warn(f"config.toml is invalid ({exc}); using defaults")
        return
    except OSError as exc:
        warn(f"config.toml is unreadable ({exc}); using defaults")
        return

    mapping = {
        "model": "LAZYCOMMIT_MODEL",
        "reasoning_effort": "LAZYCOMMIT_REASONING_EFFORT",
        "max_diff_chars": "LAZYCOMMIT_MAX_DIFF_CHARS",
        "timeout": "LAZYCOMMIT_TIMEOUT",
        "bulk_threshold": "LAZYCOMMIT_BULK_THRESHOLD",
    }
    for toml_key, env_key in mapping.items():
        if toml_key in data and env_key not in os.environ:
            os.environ[env_key] = str(data[toml_key])


def load_context_file(path: str | None, repo_root: str) -> str:
    """Load context from an explicit file or fall back to ``.lazycommit.md``."""
    candidates = [path] if path else []
    candidates.append(os.path.join(repo_root, ".lazycommit.md"))

    for candidate in candidates:
        try:
            with open(candidate, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
        except UnicodeDecodeError as exc:
            warn(
                f"cannot read context file {candidate}:"
                f" not valid UTF-8 ({exc.reason})"
            )
            return ""
        except OSError as exc:
            warn(f"cannot read context file {candidate}: {exc.strerror}")
            return ""
    return ""


def truncate_diff(diff: str, max_chars: int) -> tuple[str, bool]:
    """Truncate a diff at a line boundary and return ``(diff, was_truncated)``."""
    if len(diff) <= max_chars:
        return diff, False

    chunk = diff[:max_chars]
    newline_idx = chunk.rfind("\n")
    if newline_idx > 0:
        chunk = chunk[:newline_idx]
    return chunk.rstrip("\n"), True


def build_user_context(
    injected_context: str,
    branch_name: str,
    recent_commits: str,
    staged_files: list[str],
    staged_stat: str,
    staged_diff: str,
    truncated: bool,
) -> str:
    """Build the user message sent to the structured-output model."""
    recent = recent_commits or "(none - new repository)"
    staged_files_block = "\n".join(staged_files) if staged_files else "(none)"
    stat_block = staged_stat or "(none)"
    diff_label = "Diff (truncated):" if truncated else "Diff:"

    core = (
        f"Branch: {branch_name}\n\n"
        f"Recent commits (style reference):\n{recent}\n\n"
        f"Staged files:\n{staged_files_block}\n\n"
        f"Diff stats:\n{stat_block}\n\n"
        f"{diff_label}\n{staged_diff}"
    )

    if not injected_context:
        return core
    return f"{injected_context}\n---\n\n{core}"
