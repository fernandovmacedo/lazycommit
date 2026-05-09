# committer

`committer` is a Python CLI that stages changes, generates a Conventional Commit message through OpenRouter structured outputs, and runs `git commit` in one command. It also includes a `rewrite` subcommand for batch-rewriting existing history into Conventional Commit format.

When AI generation is unavailable, times out, returns invalid structured output, or is skipped for bulk changes, `committer` falls back to a deterministic message generator so the command still completes.

## Why

You can always ask your coding agent to commit for you, but agent models are often slower and more expensive than they need to be for this step. `committer` is meant for the middle of AI-assisted coding sessions, where you want to keep moving and still produce clean Conventional Commits.

Instead of spending a larger model call on commit generation, `committer` lets you use fast, cheap models to auto-commit work in one command. That keeps the commit step lightweight without giving up structured messages or a reliable fallback path.

## Features

- Auto-staging that preserves partial staging and skips `git add -A` for `--amend`
- Conventional Commit output with optional `--type` and `--scope` overrides
- Deterministic fallback with optional `--fallback MESSAGE`
- Bulk-change guardrail via `--bulk-threshold` and `--force-ai`
- `--dry-run` preview mode for both commit and rewrite workflows
- Optional `--push` after commit or `git push --force-with-lease` after rewrite
- Clean-worktree protection before non-dry-run history rewrites
- XDG config loading from `~/.config/committer/config.toml`
- Optional `.committer.md` or `--context FILE` prompt injection
- Summary output with elapsed time, token usage, cached tokens, reasoning tokens, and cost when available
- `-q, --silent` for script-friendly stdout suppression and `-v, --verbose` for prompt/response debugging

## Install

```bash
uv tool install --editable .
```

Run without installing:

```bash
uv run python -m committer --dry-run
```

Optional shell alias:

```bash
alias gg='committer'
```

## Usage

### Commit workflow

```bash
committer [options] [-- <git-commit-args>]
```

Common options:

- `-C, --directory DIR` run inside `DIR` first, similar to `git -C`
- `-n, --dry-run` print the generated message without committing
- `-p, --push` run `git push` after a successful commit
- `-q, --silent` suppress stdout; warnings and errors still go to stderr
- `-v, --verbose` show model choice, prompt context, diff details, and structured responses
- `-m, --model MODEL` choose the OpenRouter model slug
- `-r, --reasoning-effort LEVEL` set reasoning effort: `none`, `minimal`, `low`, `medium`, `high`, or `xhigh`
- `-b, --no-body` omit the commit body
- `-d, --max-diff-chars N` cap diff characters sent to the model; `0` means send no diff
- `-T, --timeout SECONDS` set the per-call API timeout
- `-f, --fallback MESSAGE` use this message when AI generation falls back
- `-B, --bulk-threshold N` skip AI when staged files exceed `N`; `0` disables the limit
- `-F, --force-ai` bypass the bulk-change guardrail
- `-t, --type TYPE` force a Conventional Commit type
- `-s, --scope SCOPE` force a scope using lowercase letters, digits, `.`, `_`, `/`, or `-`
- `-c, --context FILE` load additional prompt context from a file

Pass raw `git commit` flags after `--`:

```bash
committer -- --no-verify
committer -- --amend
```

If staged files exceed `--bulk-threshold`, `committer` skips the AI request and uses the deterministic fallback unless `--force-ai` is set.

### Rewrite workflow

```bash
committer rewrite [options] [SHA]
```

Modes are mutually exclusive:

- default `-N, --non-conventional`: rewrite only commits whose subject line is not already Conventional Commit formatted
- `-a, --all`: rewrite the full history
- `-u, --unpushed`: rewrite commits in `@{u}..HEAD`
- `SHA`: rewrite from that commit through `HEAD`

Rewrite options:

- `-C, --directory DIR` run inside `DIR` first
- `-n, --dry-run` preview rewritten messages without changing history
- `-p, --push` run `git push --force-with-lease` after rewriting
- `-q, --silent` suppress stdout; warnings and errors still go to stderr
- `-v, --verbose` show model choice, prompt context, diff details, and structured responses
- `-m, --model MODEL` choose the OpenRouter model slug
- `-r, --reasoning-effort LEVEL` set reasoning effort
- `-b, --no-body` omit rewritten commit bodies
- `-d, --max-diff-chars N` cap diff characters sent to the model
- `-T, --timeout SECONDS` set the per-call API timeout
- `-f, --fallback MESSAGE` use this message whenever a rewrite falls back from AI generation

Examples:

```bash
committer rewrite -n
committer rewrite -u
committer rewrite -a -p
committer rewrite abc123
```

`rewrite` requires `git-filter-repo`:

```bash
pip install git-filter-repo
# or: apt install git-filter-repo
# or: brew install git-filter-repo
```

Non-dry-run rewrites require a clean worktree before commit collection begins.

## Configuration

Create `~/.config/committer/config.toml` or `$XDG_CONFIG_HOME/committer/config.toml`:

```toml
# OpenRouter model slug used for commit and rewrite requests.
# model = "google/gemini-3.1-flash-lite"
#
# Reasoning effort: none, minimal, low, medium, high, or xhigh.
# reasoning_effort = "none"
#
# Maximum diff characters sent to the model. Use 0 to omit the diff.
# max_diff_chars = 12000
#
# Per-call API timeout in seconds. Must be greater than 0.
# timeout = 10.0
#
# Commit flow only: skip AI when staged files exceed this count.
# Use 0 to disable the bulk-change guardrail.
# bulk_threshold = 50
```

Set the API key in your environment instead of the config file:

```bash
export OPENROUTER_API_KEY="sk-or-your-key-here"
```

Config precedence is CLI flag > environment variable > XDG config > hardcoded default.

| TOML key | Environment variable |
|---|---|
| `model` | `COMMITTER_MODEL` |
| `reasoning_effort` | `COMMITTER_REASONING_EFFORT` |
| `max_diff_chars` | `COMMITTER_MAX_DIFF_CHARS` |
| `timeout` | `COMMITTER_TIMEOUT` |
| `bulk_threshold` | `COMMITTER_BULK_THRESHOLD` |

## Context Injection

If `.committer.md` exists at the repository root, its contents are prepended to the generated user prompt. Use `--context path/to/file.md` to point at a different UTF-8 file.

## Quality Checks

```bash
uv run --group dev pytest tests/ -v
uv run --group dev ruff check committer/ tests/
uv run --group dev mypy committer/
```

## Runtime Dependencies

- `litellm`
- `instructor`
- `pydantic`
- `rich`
