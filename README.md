# autocommit

[![CI](https://github.com/fernandovmacedo/autocommit/actions/workflows/ci.yml/badge.svg)](https://github.com/fernandovmacedo/autocommit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`autocommit` is a Python CLI that stages changes, generates Conventional Commit messages through OpenRouter structured outputs, and runs `git commit` in one command. It also includes a `rewrite` subcommand for batch-rewriting existing history into Conventional Commit format.

When AI generation is unavailable, times out, returns invalid structured output, or is intentionally skipped for bulk changes, `autocommit` falls back to a deterministic message generator so the command still completes.

## Why

`autocommit` is built for the middle of AI-assisted coding sessions, where you want fast, cheap, predictable commits without spending a larger model call on commit generation itself.

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
autocommit --dry-run
```

Create a commit:

```bash
autocommit
```

Enable shell completion after installing the CLI:

```bash
eval "$(register-python-argcomplete autocommit)"
```

Pass raw `git commit` flags after `--`:

```bash
autocommit -- --no-verify
autocommit -- --amend
```

## Install and Requirements

If you do not want to install the CLI into your tool environment, you can run it directly from the repo:

```bash
uv run python -m autocommit --dry-run
```

Optional shell alias:

```bash
alias gg='autocommit'
```

Shell completion is supported for Bash and Zsh through `argcomplete`. After
installing the package, register completion in your shell:

```bash
# Bash
eval "$(register-python-argcomplete autocommit)"

# Zsh
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete autocommit)"
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
autocommit
```

Preview the generated message:

```bash
autocommit -n
```

Commit and push:

```bash
autocommit -p
```

Force a type and scope:

```bash
autocommit -t feat -s cli
```

Provide extra prompt context:

```bash
autocommit -c .autocommit.md
```

If staged files exceed the bulk threshold, `autocommit` skips the AI request and uses the deterministic fallback unless `--force-ai` is set.

## Rewrite Existing History

Use `rewrite` to regenerate commit messages in Conventional Commit format:

```bash
autocommit rewrite [options] [SHA]
```

Common rewrite modes:

- Default behavior rewrites only non-Conventional commit subjects.
- `autocommit rewrite -u` rewrites commits in `@{u}..HEAD`.
- `autocommit rewrite -a` rewrites the full history.
- `autocommit rewrite abc123` rewrites from a specific commit through `HEAD`.

Examples:

```bash
autocommit rewrite -n
autocommit rewrite -u
autocommit rewrite -a -p
autocommit rewrite abc123
```

Non-dry-run rewrites require a clean worktree before commit collection begins.

## Usage Reference

Commit command:

```bash
autocommit [options] [-- <git-commit-args>]
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
autocommit rewrite [options] [SHA]
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

Create `~/.config/autocommit/config.toml` or `$XDG_CONFIG_HOME/autocommit/config.toml`:

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
| `model` | `AUTOCOMMIT_MODEL` |
| `reasoning_effort` | `AUTOCOMMIT_REASONING_EFFORT` |
| `max_diff_chars` | `AUTOCOMMIT_MAX_DIFF_CHARS` |
| `timeout` | `AUTOCOMMIT_TIMEOUT` |
| `bulk_threshold` | `AUTOCOMMIT_BULK_THRESHOLD` |

If `.autocommit.md` exists at the repository root, its contents are prepended to the generated user prompt. Use `--context path/to/file.md` to point at a different UTF-8 file.

## Similar Projects

Manual `git commit` is still the right choice when you already know the exact message you want and do not need AI help or rewrite support.

Asking a general coding agent to commit for you is useful when commit generation is part of a larger agent workflow, but it is usually slower, broader, and more expensive than a dedicated CLI.

Other AI commit message tools may generate a subject line, but `autocommit` is opinionated about a narrower workflow:

- Conventional Commit output is the default contract.
- Deterministic fallback keeps the command usable when AI generation fails or is skipped.
- Bulk changes can bypass AI automatically.
- `rewrite` can clean up older commit history, not just the next commit.

Choose `autocommit` when you want a small tool focused on reliable Conventional Commits rather than a general-purpose coding assistant.

## Development

Run the local checks with `uv`:

```bash
uv run --group dev pytest tests/ -v
uv run --group dev ruff check autocommit/ tests/
uv run --group dev mypy autocommit/
```

## Releases

Release artifacts are built automatically by GitHub Actions when you push an
annotated semver tag in the form `vX.Y.Z`.

Release process:

```bash
# 1. Bump both version strings to the same value.
$EDITOR pyproject.toml autocommit/__init__.py

# 2. Commit the version bump.
git add pyproject.toml autocommit/__init__.py
git commit -m "chore: release v1.0.0"

# 3. Create and push the annotated release tag.
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin master
git push origin v1.0.0
```

The release workflow verifies that the tag version matches both
`pyproject.toml` and `autocommit.__version__`, builds the wheel and source
distribution with `uv build`, creates or updates the GitHub Release, and uploads
the files from `dist/` as release assets.

For the current package version, create tag `v1.0.0` from the commit where both
version declarations are `1.0.0`.

Runtime dependencies:

- `litellm`
- `instructor`
- `pydantic`
- `rich`

## License

[MIT](LICENSE)
