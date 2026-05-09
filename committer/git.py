"""Git subprocess operations and context building."""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Sequence

from committer.console import warn
from committer.constants import DIFF_EXCLUDE_PATTERNS
from committer.logger import log_debug


def run_git(*args: str) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    label = " ".join(args[:2]) if len(args) >= 2 else args[0] if args else "git"
    log_debug(f"git {label} → start")
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        log_debug(f"git {label} → exit {result.returncode}")
        return None
    log_debug(f"git {label} → ok ({len(result.stdout)} chars)")
    return result.stdout.strip() or ""


def has_staged_changes() -> bool:
    """Check if there are staged changes."""
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    return result.returncode != 0


def get_repo_root() -> str | None:
    """Get the repository root path, or None if not in a repo."""
    return run_git("rev-parse", "--show-toplevel")


def auto_stage(git_args: Sequence[str]) -> None:
    """Auto-stage all changes if nothing is staged and not amending."""
    if "--amend" in git_args:
        return
    if has_staged_changes():
        return
    subprocess.run(["git", "add", "-A"], capture_output=True, check=False)


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

    Reads from $XDG_CONFIG_HOME/committer/config.toml (defaults to
    ~/.config/committer/config.toml). Sets environment variables for
    COMMITTER_MODEL, COMMITTER_REASONING_EFFORT,
    COMMITTER_MAX_DIFF_CHARS, COMMITTER_TIMEOUT, and
    COMMITTER_BULK_THRESHOLD. Does not override existing environment
    variables.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
        "~/.config"
    )
    config_path = os.path.join(xdg_config_home, "committer", "config.toml")

    if not os.path.isfile(config_path):
        return

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        warn(f"config.toml is invalid ({exc}); using defaults")
        return
    except OSError:
        return

    mapping = {
        "model": "COMMITTER_MODEL",
        "reasoning_effort": "COMMITTER_REASONING_EFFORT",
        "max_diff_chars": "COMMITTER_MAX_DIFF_CHARS",
        "timeout": "COMMITTER_TIMEOUT",
        "bulk_threshold": "COMMITTER_BULK_THRESHOLD",
    }
    for toml_key, env_key in mapping.items():
        if toml_key in data and env_key not in os.environ:
            os.environ[env_key] = str(data[toml_key])


def load_context_file(path: str | None, repo_root: str) -> str:
    """Load context from a file, trying explicit path or .committer.md."""
    candidates = [path] if path else []
    candidates.append(os.path.join(repo_root, ".committer.md"))

    for candidate in candidates:
        try:
            with open(candidate, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
        except (OSError, UnicodeDecodeError):
            warn(f"cannot read context file {candidate}")
            return ""
    return ""


def truncate_diff(diff: str, max_chars: int) -> tuple[str, bool]:
    """Truncate diff at line boundary if needed. Returns (diff, was_truncated)."""
    if len(diff) <= max_chars:
        return diff, False

    chunk = diff[:max_chars]
    newline_idx = chunk.rfind("\n")
    if newline_idx > 0:
        chunk = chunk[:newline_idx]
    return chunk.rstrip(), True


def build_user_context(
    injected_context: str,
    branch_name: str,
    recent_commits: str,
    staged_files: list[str],
    staged_stat: str,
    staged_diff: str,
    truncated: bool,
) -> str:
    """Build the user context string for the AI prompt."""
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
