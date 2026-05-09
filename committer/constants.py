"""Constants and schemas for committer."""

from __future__ import annotations

import re

ALLOWED_TYPES: frozenset[str] = frozenset({
    "feat",
    "fix",
    "refactor",
    "chore",
    "docs",
    "test",
    "style",
    "perf",
    "ci",
    "build",
    "revert",
})

_ALLOWED_TYPES_STR = "|".join(sorted(ALLOWED_TYPES))

SYSTEM_PROMPT = f"""You are a git commit message generator.
Respond ONLY with a valid JSON object - no explanation, no markdown, no code fences.

Schema:
{{
  "type": "{_ALLOWED_TYPES_STR}",
  "scope": "kebab-case scope or empty string",
  "subject": "imperative mood, lowercase start, no trailing period",
  "body": "optional multiline explanation, empty string if not needed"
}}

Rules:
- Use the branch name as a scope hint.
- Match the style of recent commits.
- Subject: imperative mood ("add", "fix", "remove" - not "added", "fixes").
- The assembled header (type + scope + subject) must be <=72 characters total.
- Body: include only for non-obvious changes.
- Language: infer the natural language of the project from the diff (comments,
  strings, identifiers, documentation). Write subject and body in that language.
  If the injected context names a language explicitly, use it. If uncertain,
  default to English. The Conventional Commits type/scope keywords always stay
  in English regardless of project language.
"""

# Patterns to exclude from git diffs (lockfiles)
DIFF_EXCLUDE_PATTERNS = (":(exclude)*.lock", ":(exclude)*lock.json")

# Regex for conventional commit format: type(scope)!?: subject
_CONVENTIONAL_RE = re.compile(
    r"^(" + "|".join(sorted(ALLOWED_TYPES)) + r")(\([^)]*\))?!?:\s"
)
