# PYTHON_ARGCOMPLETE_OK
"""
Committer CLI for AI-assisted Conventional Commit generation and rewrites.

This package provides a CLI for generating Conventional Commit messages and
rewriting existing history via OpenRouter-backed structured outputs, with a
deterministic fallback when the AI path is unavailable.
"""

from __future__ import annotations

import argparse
import os
import sys

import argcomplete

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
from committer.constants import ALLOWED_TYPES, SCOPE_RE, SYSTEM_PROMPT
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
    _ensure_clean_worktree,
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
    "_ensure_clean_worktree",
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
    """Deprecated parser namespace kept for tests and older imports."""
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
    """Deprecated rewrite parser namespace kept for tests and older imports."""
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


class ParsedRootArgs(argparse.Namespace):
    """Internal parser namespace for the unified root parser."""
    command: str | None
    directory: str | None
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
    bulk_threshold: int
    force_ai: bool
    type: str | None
    scope: str | None
    context: str | None
    sha: str | None
    all_commits: bool
    non_conventional: bool
    unpushed: bool


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


def _env_non_negative_int(key: str, default: int) -> int:
    """Read an environment integer default with the same rules as the CLI."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return _non_negative_int(value)
    except argparse.ArgumentTypeError as exc:
        die(f"invalid value for {key}: {value!r} ({exc})")


def _env_positive_float(key: str, default: float) -> float:
    """Read an environment float default with the same rules as the CLI."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return _positive_float(value)
    except argparse.ArgumentTypeError as exc:
        die(f"invalid value for {key}: {value!r} ({exc})")


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
    parser.add_argument(
        "-q",
        "--silent",
        action="store_true",
        help="Suppress stdout output",
    )
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
        help="OpenRouter model slug",
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
        help="Omit the commit body",
    )
    parser.add_argument(
        "-d",
        "--max-diff-chars",
        type=_non_negative_int,
        default=_env_non_negative_int("COMMITTER_MAX_DIFF_CHARS", 12000),
        help="Maximum diff characters sent to the model",
    )
    parser.add_argument(
        "-T",
        "--timeout",
        type=_positive_float,
        default=_env_positive_float("COMMITTER_TIMEOUT", 10.0),
        help="Per-call API timeout in seconds",
    )
    parser.add_argument(
        "-f",
        "--fallback",
        metavar="MESSAGE",
        default=None,
        help="Fallback message to use when AI generation fails",
    )
    if not rewrite:
        parser.add_argument(
            "-B",
            "--bulk-threshold",
            type=_non_negative_int,
            default=_env_non_negative_int("COMMITTER_BULK_THRESHOLD", 50),
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


def _add_commit_args(parser: argparse.ArgumentParser) -> None:
    """Add commit-only arguments to a parser."""
    parser.set_defaults(command="commit")
    parser.add_argument("-t", "--type", help="Override commit type")
    parser.add_argument("-s", "--scope", help="Override commit scope")
    parser.add_argument("-c", "--context", help="Path to an extra context file")


def _add_rewrite_args(parser: argparse.ArgumentParser) -> None:
    """Add rewrite-only arguments to a parser."""
    parser.set_defaults(command="rewrite")
    parser.add_argument("sha", nargs="?", help="Rewrite from this SHA through HEAD")
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
        help="Rewrite commits not yet pushed to the upstream branch",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the unified root parser with rewrite as a real subcommand."""
    parser = argparse.ArgumentParser(
        prog="committer",
        description="Generate Conventional Commit messages and run git commit",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    _add_common_args(parser)
    _add_commit_args(parser)

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="{rewrite}",
    )
    rewrite_parser = subparsers.add_parser(
        "rewrite",
        description="Rewrite commit history into Conventional Commit format",
        help="Rewrite existing commit messages into Conventional Commit format",
    )
    rewrite_parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    _add_common_args(rewrite_parser, rewrite=True)
    _add_rewrite_args(rewrite_parser)

    return parser


def _validate_commit_args(
    parser: argparse.ArgumentParser,
    args: ParsedRootArgs,
    git_args: tuple[str, ...],
) -> Config:
    """Validate parsed commit arguments and convert them to Config."""
    # Validate fallback
    fallback = args.fallback.strip() if args.fallback else None
    if args.fallback is not None and not fallback:
        parser.error("--fallback cannot be empty or whitespace-only")
    if args.type is not None and not args.type.strip():
        parser.error("--type cannot be empty or whitespace-only")
    if args.type is not None and args.type.strip() not in ALLOWED_TYPES:
        parser.error(
            "--type must be one of: " + ", ".join(sorted(ALLOWED_TYPES))
        )
    if args.scope is not None:
        scope = args.scope.strip()
        if scope and not SCOPE_RE.match(scope):
            parser.error(
                "--scope must be empty or contain lowercase letters, digits,"
                " '.', '_', '/', or '-'"
            )

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
        scope=args.scope.strip() if args.scope is not None else None,
        context=args.context,
        git_args=git_args,
        fallback=fallback,
    )


def _validate_rewrite_args(
    parser: argparse.ArgumentParser,
    args: ParsedRootArgs,
) -> Config:
    """Validate parsed rewrite arguments and convert them to Config."""
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


def _split_git_args(argv: list[str]) -> tuple[list[str], tuple[str, ...]]:
    """Split commit passthrough args from argv."""
    if "--" not in argv:
        return argv, ()
    separator = argv.index("--")
    return argv[:separator], tuple(argv[separator + 1 :])


def _enable_completion(parser: argparse.ArgumentParser) -> None:
    """Enable argcomplete on the parser."""
    argcomplete.autocomplete(parser)


def parse_args() -> Config:
    """Parse command-line arguments and return a Config object."""
    argv, git_args = _split_git_args(sys.argv[1:])
    parser = _build_parser()
    _enable_completion(parser)
    args = parser.parse_args(argv, namespace=ParsedRootArgs())

    if args.command == "rewrite":
        if git_args:
            parser.error("git commit arguments after -- are only supported for commit")
        return _validate_rewrite_args(parser, args)

    return _validate_commit_args(parser, args, git_args)


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
