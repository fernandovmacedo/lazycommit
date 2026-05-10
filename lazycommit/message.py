"""Structured commit-message validation and fallback assembly helpers."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, field_validator

from lazycommit.config import Config
from lazycommit.constants import MAX_SUBJECT_LEN, SCOPE_RE


class CommitMessage(BaseModel):
    """Structured commit message returned by the model."""

    type: Literal[
        "build", "chore", "ci", "docs", "feat", "fix",
        "perf", "refactor", "revert", "style", "test",
    ]
    scope: str
    subject: str
    body: str

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, value: str) -> str:
        scope = value.strip()
        if scope and not SCOPE_RE.match(scope):
            raise ValueError(
                "scope must be empty or contain lowercase letters, digits,"
                " '.', '_', '/', or '-'"
            )
        return scope


def _build_prefix(type_: str, scope: str) -> str:
    """Build the commit message prefix (type + scope)."""
    if scope:
        return f"{type_}({scope}): "
    return f"{type_}: "


def _truncate_subject(subject: str, max_len: int) -> str:
    """Truncate a subject at a word boundary when possible."""
    if len(subject) <= max_len:
        return subject
    cut = subject[:max_len]
    space = cut.rfind(" ")
    return cut[:space].rstrip() if space > 0 else cut.rstrip()


def assemble_message(payload: CommitMessage, config: Config) -> str:
    """Assemble the final commit message from validated model output."""
    type_ = config.type if config.type is not None else payload.type
    scope = config.scope if config.scope is not None else payload.scope
    subject = payload.subject.strip()
    body = "" if config.no_body else payload.body.strip()

    prefix = _build_prefix(type_, scope)
    max_subject_len = max(1, MAX_SUBJECT_LEN - len(prefix))
    subject = _truncate_subject(subject, max_subject_len)
    subject = subject or "update project files"

    header = prefix + subject
    if body:
        return f"{header}\n\n{body}"
    return header


def build_fallback_message(staged_files: list[str]) -> str:
    """Build a deterministic Conventional Commit from staged file paths."""
    if not staged_files:
        return "chore: update project files"

    paths = [line.split("\t")[-1] for line in staged_files]
    lower_paths = [p.lower() for p in paths]

    if all("test" in p or "spec" in p for p in lower_paths):
        type_ = "test"
    elif all(p.endswith((".md", ".rst", ".txt")) for p in lower_paths):
        type_ = "docs"
    else:
        type_ = "chore"

    dirs = [p.split("/")[0] for p in paths if "/" in p]
    scope = Counter(dirs).most_common(1)[0][0] if dirs else ""

    if len(paths) > 1:
        if len(paths) >= 10:
            subject = f"bulk update across {len(paths)} files"
        else:
            subject = f"update {scope or 'project'} with staged changes"
    else:
        subject = f"update {paths[0]}"

    prefix = _build_prefix(type_, scope)
    max_subject_len = max(1, MAX_SUBJECT_LEN - len(prefix))
    subject = _truncate_subject(subject, max_subject_len)
    subject = subject or "update project files"
    return prefix + subject
