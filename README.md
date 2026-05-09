# committer

[![CI](https://github.com/fernandovmacedo/committer/actions/workflows/ci.yml/badge.svg)](https://github.com/fernandovmacedo/committer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`committer` is a Python CLI that stages changes, generates Conventional Commit messages through OpenRouter structured outputs, and runs `git commit` in one command. It also includes a `rewrite` subcommand for batch-rewriting existing history into Conventional Commit format.

When AI generation is unavailable, times out, returns invalid structured output, or is intentionally skipped for bulk changes, `committer` falls back to a deterministic message generator so the command still completes.

## Why

`committer` is built for the middle of AI-assisted coding sessions, where you want fast, cheap, predictable commits without spending a larger model call on commit generation itself.

Compared with asking a general coding agent to commit for you, it is narrower on purpose: one CLI, one job, Conventional Commit output, a deterministic fallback, and a rewrite mode for cleaning up existing history.

## Quick Start

Requirements:

- Python 3.11+
- `uv`
- `git`
- `OPENROUTER_API_KEY` in your environment

Install locally from the repo:

```bash
uv tool install --editable .
export OPENROUTER_API_KEY="sk-or-your-key-here"
```

Preview a message without committing:

```bash
committer --dry-run
```

Create a commit:

```bash
committer
```

Enable shell completion after installing the CLI:

```bash
eval "$(register-python-argcomplete committer)"
```

Pass raw `git commit` flags after `--`:

```bash
committer -- --no-verify
committer -- --amend
```

## Install and Requirements

If you do not want to install the CLI into your tool environment, you can run it directly from the repo:

```bash
uv run python -m committer --dry-run
```

Optional shell alias:

```bash
alias gg='committer'
```

Shell completion is supported for Bash and Zsh through `argcomplete`. After
installing the package, register completion in your shell:

```bash
# Bash
eval "$(register-python-argcomplete committer)"

# Zsh
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete committer)"
```

The `rewrite` subcommand also requires `git-filter-repo`, which is not installed by `uv tool install`:

```bash
uv tool install git-filter-repo
# or: pip install git-filter-repo
# or: apt install git-filter-repo
# or: brew install git-filter-repo
```

## Common Workflows

Standard commit:

```bash
committer
```

Preview the generated message:

```bash
committer -n
```

Commit and push:

```bash
committer -p
```

Force a type and scope:

```bash
committer -t feat -s cli
```

Provide extra prompt context:

```bash
committer -c .committer.md
```

If staged files exceed the bulk threshold, `committer` skips the AI request and uses the deterministic fallback unless `--force-ai` is set.

## Rewrite Existing History

Use `rewrite` to regenerate commit messages in Conventional Commit format:

```bash
committer rewrite [options] [SHA]
```

Common rewrite modes:

- Default behavior rewrites only non-Conventional commit subjects.
- `committer rewrite -u` rewrites commits in `@{u}..HEAD`.
- `committer rewrite -a` rewrites the full history.
- `committer rewrite abc123` rewrites from a specific commit through `HEAD`.

Examples:

```bash
committer rewrite -n
committer rewrite -u
committer rewrite -a -p
committer rewrite abc123
```

Non-dry-run rewrites require a clean worktree before commit collection begins.

## Usage Reference

Commit command:

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

Rewrite command:

```bash
committer rewrite [options] [SHA]
```

Rewrite options:

- `-a, --all` rewrite the full history
- `-u, --unpushed` rewrite commits in `@{u}..HEAD`
- `-N, --non-conventional` rewrite only commits whose subject line is not already Conventional Commit formatted
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

If `.committer.md` exists at the repository root, its contents are prepended to the generated user prompt. Use `--context path/to/file.md` to point at a different UTF-8 file.

## Similar Projects

Manual `git commit` is still the right choice when you already know the exact message you want and do not need AI help or rewrite support.

Asking a general coding agent to commit for you is useful when commit generation is part of a larger agent workflow, but it is usually slower, broader, and more expensive than a dedicated CLI.

Other AI commit message tools may generate a subject line, but `committer` is opinionated about a narrower workflow:

- Conventional Commit output is the default contract.
- Deterministic fallback keeps the command usable when AI generation fails or is skipped.
- Bulk changes can bypass AI automatically.
- `rewrite` can clean up older commit history, not just the next commit.

Choose `committer` when you want a small tool focused on reliable Conventional Commits rather than a general-purpose coding assistant.

## Development

Run the local checks with `uv`:

```bash
uv run --group dev pytest tests/ -v
uv run --group dev ruff check committer/ tests/
uv run --group dev mypy committer/
```

Runtime dependencies:

- `litellm`
- `instructor`
- `pydantic`
- `rich`

## License

[MIT](LICENSE)
