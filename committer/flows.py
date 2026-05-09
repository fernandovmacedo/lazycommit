"""Main workflow orchestration for commit and rewrite operations."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from types import FrameType
from typing import Any, cast

from committer.api import UsageStats, generate_commit_json
from committer.config import Config
from committer.console import (
    _print_verbose_request,
    _print_verbose_response,
    err,
    out,
    warn,
)
from committer.constants import GIT_COMMIT_TIMEOUT_S, GIT_PUSH_TIMEOUT_S, SYSTEM_PROMPT
from committer.git import (
    auto_stage,
    build_user_context,
    get_branch_name,
    get_recent_commits,
    get_repo_root,
    get_staged_diff,
    get_staged_files,
    get_staged_stat,
    has_staged_changes,
    load_context_file,
    run_git,
    truncate_diff,
)
from committer.logger import log_error, log_info, log_warning
from committer.message import (
    CommitMessage,
    assemble_message,
    build_fallback_message,
)
from committer.rewrite import (
    _apply_filter_repo,
    _build_commit_context,
    _check_filter_repo,
    _ensure_clean_worktree,
    _get_rewrite_shas,
)

# Meta-timeout constants for the OS-level alarm that prevents hung AI calls.
# The multiplier accounts for max_retries=1 in api.py (up to 2 attempts).
_META_TIMEOUT_MULTIPLIER = 2
_META_TIMEOUT_OVERHEAD_S = 5  # seconds buffer for retries and overhead
_HAS_SIGALRM = hasattr(signal, "SIGALRM")


def _meta_timeout_handler(signum: int, frame: object) -> None:
    """SIGALRM handler — raises TimeoutError when the meta-deadline expires."""
    log_warning(f"meta_timeout fired: API call exceeded deadline (signal={signum})")
    raise TimeoutError("API call exceeded meta-timeout deadline")


class _ApiMetaTimeout:
    """OS-level meta-timeout for API calls via signal.SIGALRM.

    Arms a SIGALRM on enter and disarms on exit. If the alarm fires
    before the wrapped code completes, raises ``TimeoutError`` so that
    the existing ``except Exception`` handlers fall back to deterministic
    commit messages.
    """

    def __init__(self, api_timeout: float) -> None:
        self._seconds = (
            int(api_timeout) * _META_TIMEOUT_MULTIPLIER + _META_TIMEOUT_OVERHEAD_S
        )
        self._prev_handler: Callable[[int, FrameType | None], Any] | int | None = None

    @property
    def seconds(self) -> int:
        return self._seconds

    def __enter__(self) -> _ApiMetaTimeout:
        if not _HAS_SIGALRM:
            log_warning("meta_timeout skipped: SIGALRM unavailable")
            return self
        if threading.current_thread() is not threading.main_thread():
            log_warning("meta_timeout skipped: not on main thread")
            return self

        def handler(signum: int, frame: FrameType | None) -> None:
            log_warning(
                f"meta_timeout fired after {self._seconds}s"
                f" (signal={signum})"
            )
            raise TimeoutError(
                f"API call exceeded {self._seconds}s meta-timeout deadline"
            )

        self._prev_handler = signal.signal(signal.SIGALRM, handler)
        signal.alarm(self._seconds)
        return self

    def __exit__(self, *exc: object) -> None:
        if (
            not _HAS_SIGALRM
            or threading.current_thread() is not threading.main_thread()
        ):
            return
        signal.alarm(0)
        if self._prev_handler is not None:
            signal.signal(signal.SIGALRM, self._prev_handler)


def commit_changes(message: str, git_args: tuple[str, ...]) -> int:
    """Commit changes with the given message."""
    try:
        result = subprocess.run(
            ["git", "commit", *git_args, "-F", "-"],
            input=message.encode("utf-8"),
            check=False,
            timeout=GIT_COMMIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        log_warning(f"git_commit timed out after {GIT_COMMIT_TIMEOUT_S}s")
        warn(f"git commit timed out after {GIT_COMMIT_TIMEOUT_S}s")
        return 1
    return result.returncode


def _print_summary(elapsed: float, usage_stats: UsageStats | None) -> None:
    """Print execution summary with timing and optional usage stats."""
    elapsed_s = f"{elapsed:.2f}".rstrip("0").rstrip(".")
    parts = [f"Time: {elapsed_s}s"]
    if usage_stats is not None:
        cost = usage_stats.format_cost()
        if cost is not None:
            parts.append(f"Cost: {cost}")
        parts.append(f"Token usage: {usage_stats.format_tokens()}")
    out(" | ".join(parts))


def _commit_flow(config: Config) -> int:
    """Execute the commit workflow, including heuristic fallback paths."""
    from committer.console import die

    start = time.perf_counter()
    log_info(
        f"commit_flow start model={config.model}"
        f" timeout={config.timeout}s dry_run={config.dry_run}"
    )

    repo_root = get_repo_root()
    if not repo_root:
        die("not a git repository")

    log_info("auto_stage start")
    if auto_stage(config.git_args) is False:
        log_warning("commit_flow end: auto_stage failed")
        return 1
    log_info("auto_stage end")

    if not has_staged_changes():
        log_info("commit_flow end: nothing to commit")
        if not config.silent:
            out("nothing to commit")
        return 0

    staged_files = get_staged_files()
    staged_stat = get_staged_stat()
    staged_diff_raw = get_staged_diff()
    staged_diff, truncated = truncate_diff(staged_diff_raw, config.max_diff_chars)
    log_info(
        f"diff collected diff_chars={len(staged_diff)}"
        f" truncated={truncated} files={len(staged_files)}"
    )

    user_context = build_user_context(
        injected_context=load_context_file(config.context, repo_root),
        branch_name=get_branch_name(),
        recent_commits=get_recent_commits(),
        staged_files=staged_files,
        staged_stat=staged_stat,
        staged_diff=staged_diff,
        truncated=truncated,
    )
    if not config.silent and config.verbose:
        diff_info = f"diff: {len(staged_diff)} chars"
        if truncated:
            diff_info += f" (truncated from {len(staged_diff_raw)})"
        _print_verbose_request(
            diff_info=diff_info,
            context_path=config.context,
            model=config.model,
            system_prompt=SYSTEM_PROMPT,
            user_context=user_context,
        )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    fallback_used = False
    usage_stats: UsageStats | None = None

    file_count = len(staged_files)
    if (
        not config.force_ai
        and config.bulk_threshold > 0
        and file_count > config.bulk_threshold
    ):
        log_info(
            f"bulk detected files={file_count}"
            f" threshold={config.bulk_threshold}, using fallback"
        )
        if not config.silent:
            out(
                f"bulk change: {file_count} files"
                f" (threshold: {config.bulk_threshold}),"
                f" using heuristic (use --force-ai to override)"
            )
        message = config.fallback or build_fallback_message(staged_files)
        fallback_used = True
    elif not api_key:
        log_warning("OPENROUTER_API_KEY not set, using fallback")
        warn("OPENROUTER_API_KEY not set, using fallback")
        message = config.fallback or build_fallback_message(staged_files)
        fallback_used = True
    else:
        meta = _ApiMetaTimeout(config.timeout)
        api_start = time.perf_counter()
        log_info(
            f"api_call start model={config.model}"
            f" timeout={config.timeout}s meta_timeout={meta.seconds}s"
        )
        try:
            with meta:
                result, usage_stats = generate_commit_json(
                    api_key=api_key,
                    model=config.model,
                    reasoning_effort=config.reasoning_effort,
                    system_prompt=SYSTEM_PROMPT,
                    response_model=CommitMessage,
                    user_context=user_context,
                    timeout=config.timeout,
                )
            commit_msg = cast(CommitMessage, result)
            log_info(f"api_call end elapsed={time.perf_counter() - api_start:.2f}s")
            if not config.silent and config.verbose:
                _print_verbose_response(commit_msg.model_dump_json())
            message = assemble_message(commit_msg, config)
        except ValueError as exc:
            elapsed_api = time.perf_counter() - api_start
            log_warning(
                f"api_call invalid response elapsed={elapsed_api:.2f}s exc={exc}"
            )
            warn(f"invalid model response ({exc}), using fallback")
            message = config.fallback or build_fallback_message(staged_files)
            fallback_used = True
        except Exception as exc:  # pragma: no cover - depends on runtime/API failures.
            elapsed_api = time.perf_counter() - api_start
            log_error(
                f"api_call failed elapsed={elapsed_api:.2f}s exc={exc}", exc_info=True
            )
            warn(f"AI unavailable ({exc}), using fallback")
            message = config.fallback or build_fallback_message(staged_files)
            fallback_used = True

    if fallback_used:
        err("[fallback]")

    if config.dry_run:
        elapsed = time.perf_counter() - start
        log_info(f"commit_flow end dry_run elapsed={elapsed:.2f}s")
        if not config.silent:
            out(message)
            _print_summary(elapsed, usage_stats)
        return 0

    log_info(f"git_commit start message={message[:60]!r}")
    code = commit_changes(message, config.git_args)
    log_info(f"git_commit end code={code}")

    if code == 0:
        elapsed = time.perf_counter() - start
        log_info(f"commit_flow end elapsed={elapsed:.2f}s")
        if not config.silent:
            out(message)
            _print_summary(elapsed, usage_stats)
        if config.push:
            log_info("git_push start")
            try:
                push = subprocess.run(
                    ["git", "push"],
                    capture_output=True,
                    check=False,
                    timeout=GIT_PUSH_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired:
                log_warning(f"git_push timed out after {GIT_PUSH_TIMEOUT_S}s")
                warn(f"git push timed out after {GIT_PUSH_TIMEOUT_S}s")
                return 1
            log_info(f"git_push end code={push.returncode}")
            if push.returncode != 0:
                stderr = push.stderr.decode("utf-8", errors="replace").strip()
                if stderr:
                    log_warning(f"git_push stderr: {stderr}")
                warn("git push failed")
                return 1
    else:
        log_warning(f"commit_flow end: git commit failed code={code}")

    return code


def _rewrite_flow(config: Config) -> int:
    """Execute the commit-history rewrite workflow."""
    from committer.console import die

    start = time.perf_counter()
    log_info(
        f"rewrite_flow start model={config.model}"
        f" timeout={config.timeout}s dry_run={config.dry_run}"
    )
    _check_filter_repo()

    repo_root = get_repo_root()
    if not repo_root:
        die("not a git repository")
    if not config.dry_run:
        _ensure_clean_worktree()

    shas = _get_rewrite_shas(
        config.sha, config.all_commits, config.non_conventional, config.unpushed
    )
    if not shas:
        log_info("rewrite_flow end: nothing to rewrite")
        if not config.silent:
            out("nothing to rewrite")
            _print_summary(time.perf_counter() - start, None)
        return 0
    log_info(f"rewrite_flow commits={len(shas)}")
    if not config.silent and config.verbose:
        out(f"rewriting {len(shas)} commit(s) using {config.model}")

    branch = get_branch_name()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        log_warning("OPENROUTER_API_KEY not set, using fallback")
        warn("OPENROUTER_API_KEY not set, using fallback")

    message_map: dict[str, str] = {}
    usage_totals = UsageStats(0, 0)
    for i, sha in enumerate(shas):
        log_info(f"rewrite sha={sha[:8]} ({i + 1}/{len(shas)}) start")
        user_context = _build_commit_context(sha, branch, config.max_diff_chars)
        files_raw = run_git("show", "--name-status", "--format=", sha) or ""
        files = files_raw.splitlines()
        fallback_message = config.fallback or build_fallback_message(files)

        if not config.silent and config.verbose:
            diff_info = f"commit: {sha[:8]}"
            _print_verbose_request(
                diff_info=diff_info,
                context_path=None,
                model=config.model,
                system_prompt=SYSTEM_PROMPT,
                user_context=user_context,
            )

        message = fallback_message
        if api_key:
            api_start = time.perf_counter()
            meta = _ApiMetaTimeout(config.timeout)
            log_info(
                f"api_call sha={sha[:8]} start"
                f" meta_timeout={meta.seconds}s"
            )
            try:
                with meta:
                    result, stats = generate_commit_json(
                        api_key=api_key,
                        model=config.model,
                        reasoning_effort=config.reasoning_effort,
                        system_prompt=SYSTEM_PROMPT,
                        response_model=CommitMessage,
                        user_context=user_context,
                        timeout=config.timeout,
                    )
                commit_msg = cast(CommitMessage, result)
                usage_totals.add(stats)
                elapsed_api = time.perf_counter() - api_start
                log_info(f"api_call sha={sha[:8]} end elapsed={elapsed_api:.2f}s")
                if not config.silent and config.verbose:
                    _print_verbose_response(commit_msg.model_dump_json())
                message = assemble_message(commit_msg, config)
            except Exception as exc:  # pragma: no cover
                elapsed_api = time.perf_counter() - api_start
                log_error(
                    f"api_call sha={sha[:8]} failed"
                    f" elapsed={elapsed_api:.2f}s exc={exc}",
                    exc_info=True,
                )
                message = fallback_message

        message_map[sha] = message
        log_info(f"rewrite sha={sha[:8]} end message={message[:60]!r}")

    if not config.silent:
        for sha in shas:
            out(f"{sha[:8]} -> {message_map[sha]}")

    if config.dry_run:
        elapsed = time.perf_counter() - start
        log_info(f"rewrite_flow end dry_run elapsed={elapsed:.2f}s")
        if not config.silent:
            _print_summary(elapsed, usage_totals)
        return 0

    log_info(f"filter_repo start count={len(message_map)}")
    _apply_filter_repo(message_map)
    log_info("filter_repo end")

    exit_code = 0
    if config.push:
        log_info("git_push start force-with-lease")
        try:
            push = subprocess.run(
                ["git", "push", "--force-with-lease"],
                capture_output=True,
                check=False,
                timeout=GIT_PUSH_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            log_warning(
                f"git_push force-with-lease timed out after {GIT_PUSH_TIMEOUT_S}s"
            )
            warn(f"git push --force-with-lease timed out after {GIT_PUSH_TIMEOUT_S}s")
            return 1
        log_info(f"git_push end code={push.returncode}")
        if push.returncode != 0:
            stderr = push.stderr.decode("utf-8", errors="replace").strip()
            if stderr:
                log_warning(f"git_push stderr: {stderr}")
            warn("git push --force-with-lease failed")
            exit_code = 1

    elapsed = time.perf_counter() - start
    log_info(f"rewrite_flow end elapsed={elapsed:.2f}s")
    if not config.silent:
        _print_summary(elapsed, usage_totals)

    return exit_code
