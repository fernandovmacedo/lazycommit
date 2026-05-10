# lazycommit

[![CI](https://github.com/fernandovmacedo/lazycommit/actions/workflows/ci.yml/badge.svg)](https://github.com/fernandovmacedo/lazycommit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`lazycommit` is a Python CLI that stages changes, generates Conventional Commit messages through OpenRouter structured outputs, and runs `git commit` in one command. It also includes a `rewrite` subcommand for batch-rewriting existing history into Conventional Commit format.

When AI generation is unavailable, times out, returns invalid structured output, or is intentionally skipped for bulk changes, `lazycommit` falls back to a deterministic message generator so the command still completes.

## Why

`lazycommit` is built for the middle of AI-assisted coding sessions, where you want fast, cheap, predictable commits without spending a larger model call on commit generation itself.

Compared with asking a general coding agent to commit for you, it is narrower on purpose: one CLI, one job, Conventional Commit output, a deterministic fallback, and a rewrite mode for cleaning up existing history.

## Default AI Model

By default, `lazycommit` uses `google/gemini-3.1-flash-lite`.

That is the hardcoded default because it fits the tool's goal well: short commit-generation requests benefit more from low latency and low cost than from a larger, slower model. In practice, this keeps commit generation fast and cheap while still handling structured outputs reliably.

The model is customizable. You can override the default with `-m, --model`, `LAZYCOMMIT_MODEL`, or `model = "..."` in `~/.config/lazycommit/config.toml`.

`lazycommit` also defaults `reasoning_effort` to `none`. For commit generation, extra reasoning usually adds cost and latency more than it adds value, so reasoning is turned off by default to keep requests cheaper and faster. You can override that with `-r, --reasoning-effort`, `LAZYCOMMIT_REASONING_EFFORT`, or `reasoning_effort = "..."` in config.

At the time of writing, Google lists Gemini 3.1 Flash-Lite at `$0.25 / 1M input tokens` and `$1.50 / 1M output tokens`:

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
lcm --dry-run
```

Create a commit:

```bash
lcm
```

Enable shell completion after installing the CLI:

```bash
eval "$(register-python-argcomplete lcm)"
```

Pass raw `git commit` flags after `--`:

```bash
lcm -- --no-verify
lcm -- --amend
```

## Install and Requirements

If you do not want to install the CLI into your tool environment, you can run it directly from the repo:

```bash
uv run python -m lazycommit --dry-run
```

Shell completion is supported for Bash and Zsh through `argcomplete`. After
installing the package, register completion in your shell:

```bash
# Bash
eval "$(register-python-argcomplete lcm)"

# Zsh
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete lcm)"
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
lcm
```

Preview the generated message:

```bash
lcm -n
```

Commit and push:

```bash
lcm -p
```

Force a type and scope:

```bash
lcm -t feat -s cli
```

Provide extra prompt context:

```bash
lcm -c .lazycommit.md
```

If staged files exceed the bulk threshold, `lazycommit` skips the AI request and uses the deterministic fallback unless `--force-ai` is set.

## Rewrite Existing History

Use `rewrite` to regenerate commit messages in Conventional Commit format:

```bash
lcm rewrite [options] [SHA]
```

Common rewrite modes:

- Default behavior rewrites only non-Conventional commit subjects.
- `lcm rewrite -u` rewrites commits in `@{u}..HEAD`.
- `lcm rewrite -a` rewrites the full history.
- `lcm rewrite abc123` rewrites from a specific commit through `HEAD`.

Examples:

```bash
lcm rewrite -n
lcm rewrite -u
lcm rewrite -a -p
lcm rewrite abc123
```

Non-dry-run rewrites require a clean worktree before commit collection begins.

## Usage Reference

Commit command:

```bash
lcm [options] [-- <git-commit-args>]
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
lcm rewrite [options] [SHA]
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

Create `~/.config/lazycommit/config.toml` or `$XDG_CONFIG_HOME/lazycommit/config.toml`:

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
| `model` | `LAZYCOMMIT_MODEL` |
| `reasoning_effort` | `LAZYCOMMIT_REASONING_EFFORT` |
| `max_diff_chars` | `LAZYCOMMIT_MAX_DIFF_CHARS` |
| `timeout` | `LAZYCOMMIT_TIMEOUT` |
| `bulk_threshold` | `LAZYCOMMIT_BULK_THRESHOLD` |

If `.lazycommit.md` exists at the repository root, its contents are prepended to the generated user prompt. Use `--context path/to/file.md` to point at a different UTF-8 file.

## Alternatives

Manual `git commit` is still the right choice when you already know the exact message you want and do not need AI help or rewrite support.

Asking a general coding agent to commit for you is useful when commit generation is part of a larger agent workflow, but it is usually slower, broader, and more expensive than a dedicated CLI.

There is also [`KartikLabhshetwar/lazycommit`](https://github.com/KartikLabhshetwar/lazycommit), an npm package with a similar goal: generate commit messages from staged changes with AI.

The main differences are:

- This project is a Python CLI installed with `uv` or `pip`; that project is a Node.js CLI installed with `npm`.
- This project uses OpenRouter structured outputs and treats Conventional Commit formatting as the default contract; the npm package uses Groq and offers Conventional Commits as an optional mode.
- This project has a deterministic fallback path, so commit generation still completes when AI is unavailable, times out, or is skipped for bulk changes; the npm package focuses more on interactive generation, review/edit/confirm, and generating multiple suggestions.

Other AI commit message tools may generate a subject line, but this `lazycommit` is opinionated about a narrower workflow:

- Conventional Commit output is the default contract.
- Deterministic fallback keeps the command usable when AI generation fails or is skipped.
- Bulk changes can bypass AI automatically.
- `rewrite` can clean up older commit history, not just the next commit.

Choose `lazycommit` when you want a small tool focused on reliable Conventional Commits rather than a general-purpose coding assistant. You can also add it to hooks in your agent to save tokens.

## Development

Run the local checks with `uv`:

```bash
uv run --group dev pytest tests/ -v
uv run --group dev ruff check lazycommit/ tests/
uv run --group dev mypy lazycommit/
```

## Releases

Release artifacts are built automatically by GitHub Actions when you push an
annotated semver tag in the form `vX.Y.Z`.

Release process:

```bash
# 1. Bump both version strings to the same value.
$EDITOR pyproject.toml lazycommit/__init__.py

# 2. Commit the version bump.
git add pyproject.toml lazycommit/__init__.py
git commit -m "chore: release v1.0.0"

# 3. Create and push the annotated release tag.
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin master
git push origin v1.0.0
```

The release workflow verifies that the tag version matches both
`pyproject.toml` and `lazycommit.__version__`, builds the wheel and source
distribution with `uv build`, creates or updates the GitHub Release, uploads
the files from `dist/` as release assets, and publishes the same distributions
to PyPI via Trusted Publishing.

Before the first PyPI release, create the `lazycommit` project on PyPI and add
a Trusted Publisher for this repository's `.github/workflows/release.yml`
workflow. The publish job uses the `pypi` GitHub Actions environment and
requires PyPI-side configuration to trust that workflow identity.

For the current package version, create tag `v1.0.0` from the commit where both
version declarations are `1.0.0`.

Runtime dependencies:

- `litellm`
- `instructor`
- `pydantic`
- `rich`

## License

[MIT](LICENSE)
