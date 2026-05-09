"""Commit history rewriting functionality."""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from contextlib import suppress

from committer.console import die
from committer.constants import _CONVENTIONAL_RE, DIFF_EXCLUDE_PATTERNS
from committer.git import build_user_context, run_git, truncate_diff


def _is_conventional(message: str) -> bool:
    """Check if a message follows Conventional Commits format."""
    first_line = message.splitlines()[0] if message else ""
    return bool(_CONVENTIONAL_RE.match(first_line))


def _check_filter_repo() -> None:
    """Verify git-filter-repo is installed."""
    try:
        result = subprocess.run(
            ["git", "filter-repo", "--version"], capture_output=True, check=False
        )
    except OSError:
        result = None

    if result is None or result.returncode != 0:
        die(
            "git-filter-repo is required. Install with:\n"
            "  pip install git-filter-repo\n"
            "  (or: apt install git-filter-repo / brew install git-filter-repo)"
        )


def _get_rewrite_shas(
    sha: str | None,
    all_commits: bool,
    non_conventional: bool,
    unpushed: bool,
) -> list[str]:
    """Get list of commit SHAs to rewrite based on mode."""
    if sha:
        ranged = subprocess.run(
            ["git", "log", "--format=%H", "--reverse", f"{sha}~..HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if ranged.returncode == 0:
            return [line for line in ranged.stdout.splitlines() if line.strip()]

        all_history = [
            line
            for line in (run_git("log", "--format=%H", "--reverse") or "").splitlines()
            if line
        ]
        if sha not in all_history:
            die(f"unknown commit: {sha}")
        return all_history[all_history.index(sha) :]

    if unpushed:
        # Get commits in HEAD but not in upstream
        result = subprocess.run(
            ["git", "rev-list", "--reverse", "@{u}..HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            die("no upstream configured for current branch")
        return [line for line in result.stdout.splitlines() if line.strip()]

    shas = [
        line
        for line in (run_git("log", "--format=%H", "--reverse") or "").splitlines()
        if line
    ]
    if all_commits:
        return shas
    if non_conventional:
        filtered: list[str] = []
        for commit_sha in shas:
            subject = run_git("show", "-s", "--format=%s", commit_sha)
            if subject and not _is_conventional(subject):
                filtered.append(commit_sha)
        return filtered
    return shas


def _build_commit_context(sha: str, branch: str, max_diff_chars: int) -> str:
    """Build context for rewriting a specific commit."""
    current_msg = run_git("show", "-s", "--format=%B", sha) or ""
    diff_raw = run_git(
        "show", sha, "--", ".", *DIFF_EXCLUDE_PATTERNS
    )
    diff_lines = [
        line
        for line in (diff_raw or "").splitlines()
        if not line.startswith("Binary files ")
    ]
    diff = "\n".join(diff_lines).strip()
    diff, truncated = truncate_diff(diff, max_diff_chars)
    stat = run_git("show", "--stat", sha) or ""
    files_raw = run_git("show", "--name-status", "--format=", sha) or ""

    return build_user_context(
        injected_context=f"Rewriting existing commit.\nCurrent message:\n{current_msg}",
        branch_name=branch,
        recent_commits="",
        staged_files=files_raw.splitlines(),
        staged_stat=stat,
        staged_diff=diff,
        truncated=truncated,
    )


def _apply_filter_repo(message_map: dict[str, str]) -> None:
    """Apply commit message rewrites using git-filter-repo."""
    encoded_map = {
        sha: base64.b64encode((message.rstrip() + "\n").encode("utf-8")).decode("ascii")
        for sha, message in message_map.items()
    }
    map_lines = [f'    b"{sha}": "{encoded}",' for sha, encoded in encoded_map.items()]
    callback = (
        "import base64\n\n"
        "_MAP = {\n"
        + "\n".join(map_lines)
        + "\n}\n\n"
        "if commit.original_id in _MAP:\n"
        "    commit.message = base64.b64decode(_MAP[commit.original_id])\n"
    )

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(callback)
            tmp_path = tmp.name

        result = subprocess.run(
            ["git", "filter-repo", "--force", "--commit-callback", f"@{tmp_path}"],
            check=False,
        )
        if result.returncode != 0:
            die(f"git filter-repo failed (exit {result.returncode})")
    finally:
        if tmp_path:
            with suppress(OSError):
                os.unlink(tmp_path)
