# committer

AI-powered git commit message generator that auto-stages, generates a Conventional Commit message, and commits immediately. It also includes a `rewrite` subcommand for rewriting existing history into Conventional Commit format.

## Features

- Smart staging: preserves partial staging; otherwise runs `git add -A`
- Conventional Commit output (`feat:`, `fix:`, and related types)
- Deterministic fallback when AI is unavailable, times out, or returns invalid output
- Custom fallback message support with `--fallback`
- Bulk-change guardrail with `--bulk-threshold` and `--force-ai`
- `--dry-run` preview mode for both commit and rewrite flows
- Optional `--push` after commit or `--force-with-lease` after rewrite
- Token, cached-token, reasoning-token, and cost reporting
- XDG config support (`~/.config/committer/config.toml`)
- Optional `.committer.md` prompt context injection
- Silent mode for scripting (`-S, --silent`)
- Verbose mode for debugging (`-v, --verbose`)
- Rich-backed stdout/stderr handling

## Install

```bash
uv tool install --editable .
```

Or run without installing:

```bash
uv run python -m committer --dry-run
```

Tip: if can use `gg` as a shell alias for quick commits:

```bash
alias gg='committer'
```

## Usage

### Commit command

```bash
committer [options] [-- <git-commit-args>]
```

Options:

- `-C, --directory DIR` change to `DIR` before running
- `-n, --dry-run` generate and print the message without committing
- `-p, --push` run `git push` after a successful commit
- `-q, --silent` suppress stdout output
- `-v, --verbose` show model, prompt context, diff, and API details
- `-m, --model MODEL` OpenRouter model to use
- `-r, --reasoning-effort LEVEL` reasoning control for OpenRouter (default `none`)
- `-b, --no-body` strip the commit body
- `-d, --max-diff-chars N` maximum diff characters sent to the model (default `12000`)
- `-T, --timeout SECS` API timeout in seconds (default `10.0`)
- `-f, --fallback MESSAGE` use a custom fallback message when AI generation fails
- `-B, --bulk-threshold N` skip AI when staged files exceed `N` (`0` disables the limit, default `50`)
- `-F, --force-ai` force AI generation even when the bulk threshold is exceeded
- `-t, --type TYPE` override the commit type
- `-s, --scope SCOPE` override the commit scope
- `-c, --context FILE` prepend a context file to the AI prompt

Pass extra `git commit` flags after `--`:

```bash
committer -- --no-verify
committer -- --amend
```

If the staged file count is above `--bulk-threshold`, committer skips the AI call and uses the deterministic fallback message unless `--force-ai` is set.

### Rewrite subcommand

Rewrite existing commit messages into Conventional Commit format:

```bash
committer rewrite [options] [SHA]
```

Modes (mutually exclusive):

- (default) `-N, --non-conventional` rewrite only commits whose first line is not already a Conventional Commit
- `-a, --all` rewrite the full history
- `-u, --unpushed` rewrite commits in `@{u}..HEAD`
- `SHA` rewrite from that commit through `HEAD`

Options:

- `-C, --directory DIR` change to `DIR` before running
- `-n, --dry-run` preview rewritten messages without changing history
- `-p, --push` run `git push --force-with-lease` after rewrite
- `-q, --silent` suppress stdout output
- `-v, --verbose` show model, prompt context, diff, and API details
- `-m, --model MODEL` OpenRouter model to use
- `-r, --reasoning-effort LEVEL` reasoning control for OpenRouter (default `none`)
- `-b, --no-body` strip commit bodies in rewritten messages
- `-d, --max-diff-chars N` maximum diff characters sent to the model
- `-T, --timeout SECS` API timeout in seconds
- `-f, --fallback MESSAGE` use a custom fallback message when AI generation fails

Examples:

```bash
# Preview rewriting only non-conventional commits
committer rewrite -n

# Rewrite commits that have not been pushed yet
committer rewrite -u

# Rewrite all commits and force-push
committer rewrite -a -p

# Rewrite from a specific commit
committer rewrite abc123
```

`rewrite` requires `git-filter-repo`:

```bash
pip install git-filter-repo
# or: apt install git-filter-repo
# or: brew install git-filter-repo
```

## Configuration

Create a config file at `~/.config/committer/config.toml`:

```toml
# ~/.config/committer/config.toml
# model = "google/gemini-3.1-flash-lite"
# reasoning_effort = "none"
# max_diff_chars = 12000
# timeout = 10.0
# bulk_threshold = 50
```

Set the API key in your shell environment instead:

```bash
export OPENROUTER_API_KEY="sk-or-your-key-here"
```

Or use `$XDG_CONFIG_HOME/committer/config.toml` if `XDG_CONFIG_HOME` is set.

| TOML key | Environment variable |
|---|---|
| `model` | `COMMITTER_MODEL` |
| `reasoning_effort` | `COMMITTER_REASONING_EFFORT` |
| `max_diff_chars` | `COMMITTER_MAX_DIFF_CHARS` |
| `timeout` | `COMMITTER_TIMEOUT` |
| `bulk_threshold` | `COMMITTER_BULK_THRESHOLD` |

Precedence: CLI flag > environment variable > XDG config > hardcoded default.

## Context Injection

If `.committer.md` exists at the repo root, its contents are prepended to the AI prompt. Override that path with `--context path/to/file.md`.

## Quality Checks

```bash
uv run --group dev pytest tests/ -v
uv run --group dev ruff check committer/ tests/
uv run --group dev mypy committer/
```

## Dependencies

Runtime dependencies:

- `litellm`
- `instructor`
- `pydantic`
- `rich`
