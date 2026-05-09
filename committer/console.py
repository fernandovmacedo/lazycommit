"""Console output utilities with Rich support."""

from __future__ import annotations

import json
from typing import NoReturn

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

# Singleton consoles for stdout and stderr
_STDOUT = Console(markup=False, highlight=False, soft_wrap=True)
_STDERR = Console(stderr=True, markup=False, highlight=False, soft_wrap=True)


def out(msg: str) -> None:
    """Print to stdout."""
    _STDOUT.print(msg)


def err(msg: str) -> None:
    """Print to stderr."""
    _STDERR.print(msg)


def warn(msg: str) -> None:
    """Print a warning to stderr."""
    err(f"warning: {msg}")


def die(msg: str) -> NoReturn:
    """Print an error to stderr and exit with code 1."""
    err(f"error: {msg}")
    raise SystemExit(1)


def _print_verbose_request(
    *,
    diff_info: str,
    context_path: str | None,
    model: str,
    system_prompt: str,
    user_context: str,
) -> None:
    """Print verbose request details for debugging."""
    _STDOUT.rule("--- request ---")
    _STDOUT.print(Text(diff_info, style="cyan"))
    if context_path:
        _STDOUT.print(Text(f"context: {context_path}", style="cyan"))
    _STDOUT.print(Text(f"model: {model}", style="cyan"))
    _STDOUT.rule("--- system prompt ---")
    _STDOUT.print(Panel(Syntax(system_prompt, "markdown", word_wrap=True)))
    _STDOUT.rule("--- user message ---")
    _STDOUT.print(Panel(Syntax(user_context, "markdown", word_wrap=True)))
    _STDOUT.rule("--- end ---")


def _print_verbose_response(raw_response: str) -> None:
    """Print verbose response details for debugging."""
    _STDOUT.rule("--- response ---")
    payload = raw_response.strip()
    try:
        parsed = json.loads(payload)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        _STDOUT.print(Panel(Syntax(pretty, "json", word_wrap=True)))
    except json.JSONDecodeError:
        _STDOUT.print(Panel(Text(payload)))
    _STDOUT.rule("--- end ---")
