"""
Committer - AI-powered git commit message generator.

This package provides a CLI for generating Conventional Commit messages
via OpenRouter-backed structured outputs, with deterministic fallback when the
AI path is unavailable.
"""

from __future__ import annotations

import argparse
import os
import sys

# Re-export for test mocking and backward-compatible imports.
from committer.api import (
    UsageStats,
    generate_commit_json,
)
from committer.config import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    REASONING_EFFORT_CHOICES,
    Config,
)
from committer.console import (
    _print_verbose_request,  # noqa: F401
    _print_verbose_response,  # noqa: F401
    die,
    err,
    out,
    warn,
)
from committer.constants import ALLOWED_TYPES, SYSTEM_PROMPT
from committer.flows import _commit_flow, _print_summary, _rewrite_flow, commit_changes
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
    load_xdg_config,
    run_git,
    truncate_diff,
)
from committer.message import (
    CommitMessage,
    assemble_message,
    build_fallback_message,
)
from committer.rewrite import (
    _apply_filter_repo,
    _build_commit_context,
    _check_filter_repo,
    _get_rewrite_shas,
    _is_conventional,
)

__version__ = "1.0.0"

__all__ = [
    # Public API
    "main",
    "Config",
    "UsageStats",
    "__version__",
    # Constants
    "ALLOWED_TYPES",
    "SYSTEM_PROMPT",
    # Console
    "out",
    "err",
    "warn",
    "die",
    # Git operations
    "run_git",
    "has_staged_changes",
    "get_repo_root",
    "auto_stage",
    "get_staged_diff",
    "get_staged_files",
    "get_staged_stat",
    "get_branch_name",
    "get_recent_commits",
    "load_xdg_config",
    "load_context_file",
    "truncate_diff",
    "build_user_context",
    # API
    "generate_commit_json",
    # Message handling
    "CommitMessage",
    "assemble_message",
    "build_fallback_message",
    # Rewrite
    "_is_conventional",
    "_check_filter_repo",
    "_get_rewrite_shas",
    "_build_commit_context",
    "_apply_filter_repo",
    # Flows
    "commit_changes",
    "_print_summary",
    "_rewrite_flow",
    # Backward compatibility
    "ParsedArgs",
    "ParsedRewriteArgs",
]


# Backward compatibility shims kept for tests and older imports.
class ParsedArgs(argparse.Namespace):
    """Deprecated: Use Config instead."""
    dry_run: bool
    push: bool
    silent: bool
    verbose: bool
    model: str
    reasoning_effort: str
    no_body: bool
    type: str | None
    scope: str | None
    max_diff_chars: int
    timeout: float
    context: str | None
    git_args: list[str]


class ParsedRewriteArgs(argparse.Namespace):
    """Deprecated: Use Config instead."""
    sha: str | None
    all_commits: bool
    non_conventional: bool
    unpushed: bool
    dry_run: bool
    push: bool
    silent: bool
    verbose: bool
    model: str
    reasoning_effort: str
    no_body: bool
    max_diff_chars: int
    timeout: float
    fallback: str | None
    directory: str | None


def _non_negative_int(value: str) -> int:
    """Argparse validator for integer options that allow zero."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"must be an integer, got {value!r}"
        ) from exc
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {number}")
    return number


def _positive_float(value: str) -> float:
    """Argparse validator for numeric options that must be positive."""
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"must be a number, got {value!r}"
        ) from exc
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {number}")
    return number


def _add_common_args(parser: argparse.ArgumentParser, *, rewrite: bool = False) -> None:
    """Add arguments shared by commit and rewrite commands."""
    parser.add_argument(
        "-C",
        "--directory",
        metavar="DIR",
        default=None,
        help="Change to DIR before running (like git -C)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help=(
            "Preview rewritten messages only"
            if rewrite
            else "Generate and print the message without committing"
        ),
    )
    parser.add_argument(
        "-p",
        "--push",
        action="store_true",
        help=(
            "Push rewritten history with --force-with-lease after rewrite"
            if rewrite
            else "Run git push after a successful commit"
        ),
    )
    parser.add_argument("-q", "--silent", action="store_true", help="No stdout output")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show model, prompt context, diff, and API details",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=os.environ.get("COMMITTER_MODEL", DEFAULT_MODEL),
        help="OpenRouter model",
    )
    parser.add_argument(
        "-r",
        "--reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=os.environ.get(
            "COMMITTER_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
        ),
        help="Reasoning effort sent to OpenRouter",
    )
    parser.add_argument(
        "-b",
        "--no-body",
        action="store_true",
        help="Strip commit body",
    )
    parser.add_argument(
        "-d",
        "--max-diff-chars",
        type=_non_negative_int,
        default=int(os.environ.get("COMMITTER_MAX_DIFF_CHARS", "12000")),
        help="Max diff characters sent to model",
    )
    parser.add_argument(
        "-T",
        "--timeout",
        type=_positive_float,
        default=float(os.environ.get("COMMITTER_TIMEOUT", "10.0")),
        help="API timeout in seconds",
    )
    parser.add_argument(
        "-f",
        "--fallback",
        metavar="MESSAGE",
        default=None,
        help="Custom fallback commit message when AI generation fails",
    )
    if not rewrite:
        parser.add_argument(
            "-B",
            "--bulk-threshold",
            type=_non_negative_int,
            default=int(os.environ.get("COMMITTER_BULK_THRESHOLD", "50")),
            help=(
                "Skip AI when staged files exceed this count "
                "(0 disables the limit, default: 50)"
            ),
        )
        parser.add_argument(
            "-F",
            "--force-ai",
            action="store_true",
            help="Force AI generation even when the bulk threshold is exceeded",
        )


def _parse_commit_args() -> Config:
    """Parse arguments for the commit subcommand."""
    parser = argparse.ArgumentParser(
        prog="committer", description="AI-powered git commit message generator"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    _add_common_args(parser)
    parser.add_argument("-t", "--type", help="Override commit type")
    parser.add_argument("-s", "--scope", help="Override commit scope")
    parser.add_argument("-c", "--context", help="Path to context file")
    parser.add_argument(
        "git_args",
        nargs=argparse.REMAINDER,
        help="Additional git commit arguments passed after --",
    )

    args = parser.parse_args(namespace=ParsedArgs())

    # Handle -- separator
    git_args = args.git_args
    if git_args and git_args[0] == "--":
        git_args = git_args[1:]

    # Validate fallback
    fallback = args.fallback.strip() if args.fallback else None
    if args.fallback is not None and not fallback:
        parser.error("--fallback cannot be empty or whitespace-only")
    if args.type is not None and not args.type.strip():
        parser.error("--type cannot be empty or whitespace-only")

    return Config(
        subcommand="commit",
        dry_run=args.dry_run,
        push=args.push,
        silent=args.silent,
        verbose=args.verbose,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        no_body=args.no_body,
        max_diff_chars=args.max_diff_chars,
        timeout=args.timeout,
        bulk_threshold=args.bulk_threshold,
        force_ai=args.force_ai,
        directory=args.directory,
        type=args.type,
        scope=args.scope,
        context=args.context,
        git_args=tuple(git_args),
        fallback=fallback,
    )


def _parse_rewrite_args() -> Config:
    """Parse arguments for the rewrite subcommand."""
    parser = argparse.ArgumentParser(
        prog="committer rewrite",
        description="Rewrite commit messages into Conventional Commit format",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("sha", nargs="?", help="Rewrite from this SHA to HEAD")
    parser.add_argument(
        "-a",
        "--all",
        dest="all_commits",
        action="store_true",
        help="Rewrite all commits in history",
    )
    parser.add_argument(
        "-N",
        "--non-conventional",
        action="store_true",
        help="Rewrite only non-conventional commit messages (default)",
    )
    parser.add_argument(
        "-u",
        "--unpushed",
        action="store_true",
        help="Rewrite commits not yet pushed to upstream",
    )
    _add_common_args(parser, rewrite=True)

    args = parser.parse_args(sys.argv[2:], namespace=ParsedRewriteArgs())

    # Validate mutually exclusive options
    mode_count = (
        int(bool(args.sha))
        + int(args.all_commits)
        + int(args.non_conventional)
        + int(args.unpushed)
    )
    if mode_count > 1:
        parser.error(
            "SHA, --all, --non-conventional, and --unpushed are mutually exclusive"
        )
    if mode_count == 0:
        args.non_conventional = True

    # Validate fallback
    fallback = args.fallback.strip() if args.fallback else None
    if args.fallback is not None and not fallback:
        parser.error("--fallback cannot be empty or whitespace-only")

    return Config(
        subcommand="rewrite",
        dry_run=args.dry_run,
        push=args.push,
        silent=args.silent,
        verbose=args.verbose,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        no_body=args.no_body,
        max_diff_chars=args.max_diff_chars,
        timeout=args.timeout,
        directory=args.directory,
        sha=args.sha,
        all_commits=args.all_commits,
        non_conventional=args.non_conventional,
        unpushed=args.unpushed,
        fallback=fallback,
    )


def parse_args() -> Config:
    """Parse command-line arguments and return a Config object."""
    if len(sys.argv) > 1 and sys.argv[1] == "rewrite":
        return _parse_rewrite_args()
    return _parse_commit_args()


def main() -> int:
    """Main entry point for the committer CLI."""
    try:
        # Load XDG config FIRST, before parsing args
        # This ensures env vars are available as CLI defaults
        load_xdg_config()
        config = parse_args()
    except KeyboardInterrupt:
        return 130

    if config.directory is not None:
        if not os.path.isdir(config.directory):
            die(f"cannot change directory: {config.directory!r} does not exist")
        try:
            os.chdir(config.directory)
        except OSError as exc:
            die(f"cannot change directory: {exc}")

    try:
        if config.subcommand == "rewrite":
            return _rewrite_flow(config)
        return _commit_flow(config)
    except KeyboardInterrupt:
        warn("interrupted")
        return 130
