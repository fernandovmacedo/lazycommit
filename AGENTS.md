# AGENTS.md

This file provides guidance to AI Agents when working with code in this repository.

## Project Purpose

**Lazycommit** is a Python CLI that stages changes, generates Conventional Commit messages through OpenRouter-backed structured outputs, and commits in one command. It also includes a `rewrite` subcommand for batch-rewriting history into Conventional Commit format. When AI generation is unavailable, invalid, timed out, or intentionally skipped for bulk changes, it falls back to a deterministic message generator so the command still completes.

## Commands

All commands use `uv` (the project's package manager):

```bash
# Run all tests
uv run --group dev pytest tests/ -v

# Run a single test by name
uv run --group dev pytest tests/ -v -k "test_name"

# Lint
uv run --group dev ruff check lazycommit/ tests/

# Type-check (strict mypy)
uv run --group dev mypy lazycommit/

# Install as CLI tool (editable)
uv tool install --editable .

# Smoke test (dry run, no API needed)
uv run python -m lazycommit --dry-run
```

## Architecture

The application is structured as the `lazycommit/` package with the following modules:

```
lazycommit/
├── __init__.py      # main(), parse_args(), public re-exports
├── __main__.py      # python -m lazycommit support
├── constants.py     # SYSTEM_PROMPT, ALLOWED_TYPES, DIFF_EXCLUDE_PATTERNS, conventional regex
├── config.py        # Config dataclass (unified commit + rewrite configuration)
├── console.py       # Rich console singletons, out/err/warn/die, verbose printers  [INFRASTRUCTURE]
├── logger.py        # Persistent rotating file logger for post-mortem debugging    [INFRASTRUCTURE]
├── git.py           # all git subprocess ops, load_xdg_config, load_context_file, build_user_context
├── api.py           # LiteLLM/OpenRouter client helpers, UsageStats, generate_commit_json  [INFRASTRUCTURE]
├── message.py       # CommitMessage model, assemble_message, build_fallback_message
├── rewrite.py       # _is_conventional, _check_filter_repo, _ensure_clean_worktree, _get_rewrite_shas, _build_commit_context, _apply_filter_repo
└── flows.py         # _commit_flow, _rewrite_flow, commit_changes, _print_summary  [wiring layer]
```

Dependency graph (strict DAG, no circular imports):
```
constants  console  api  logger  (no internal deps)
config     → constants
git        → constants, console, logger
message    → constants, config
rewrite    → constants, git, console
flows      → config, console, constants, git, api, message, rewrite, logger
__init__   → all (re-exports + parse_args + main)
__main__   → __init__
```

### Infrastructure vs domain layer

`api.py`, `console.py`, and `logger.py` are **infrastructure**: they have zero imports from any other
`lazycommit.*` module and can be copied to a new project as-is. Everything else is
**domain** (Conventional Commits + git specific).

**Invariant:** `api.py`, `console.py`, and `logger.py` must never gain a `from lazycommit.*` import.
If one appears, the boundary has been broken.

**Wiring rule:** `flows.py` is the only module that connects the two layers. Domain
constants such as `SYSTEM_PROMPT` live in `constants.py` and are passed explicitly
into infrastructure functions at the `flows.py` call sites:

```python
# flows.py — domain constants injected here, never inside api.py or console.py
generate_commit_json(..., system_prompt=SYSTEM_PROMPT, ...)
_print_verbose_request(..., system_prompt=SYSTEM_PROMPT, ...)
```

Any new parameter that is domain-specific (a prompt, a schema, a template) must follow
this same pattern: defined in `constants.py`, passed in at the `flows.py` call site,
never imported inside `api.py` or `console.py`.

### Data flow (commit command)

```
main()
  ├─ load_xdg_config()           # load ~/.config/lazycommit/config.toml FIRST
  ├─ parse_args()                # dispatches to commit or rewrite flow
  ├─ auto_stage()                # git add -A unless already staged or --amend
  ├─ Collect git context         # diff, files, stats, branch, recent commits
  ├─ load_context_file()         # optional .lazycommit.md for project hints
  ├─ generate_commit_json()      # OpenRouter structured output call
  │    └─ on failure → build_fallback_message()
  ├─ assemble_message()          # converts structured response to final commit string
  ├─ commit_changes()            # git commit -F - (message via stdin)
  └─ _print_summary()            # timing + UsageStats output
```

### Data flow (rewrite subcommand)

```
main()
  ├─ load_xdg_config()           # load ~/.config/lazycommit/config.toml FIRST
  └─ _rewrite_flow()
       ├─ _check_filter_repo()        # verify git-filter-repo is installed
       ├─ _ensure_clean_worktree()    # require clean worktree for non-dry-run rewrites
       ├─ _get_rewrite_shas()         # collect commits based on mode (all/sha/non-conventional/unpushed)
       ├─ for each commit:
       │    ├─ _build_commit_context()  # diff + current message for context
       │    ├─ generate_commit_json()   # API call with existing message as hint
       │    └─ store in message_map
       ├─ if dry_run: print preview and exit
       ├─ _apply_filter_repo()        # batch rewrite via git-filter-repo callback
       └─ optional --push with --force-with-lease
```

### Key design decisions

- **Infrastructure/domain split.** `api.py` and `console.py` are domain-agnostic infrastructure with no internal imports; `flows.py` is the wiring layer that passes domain constants into them. See the "Infrastructure vs domain layer" section above.
- **At most two API attempts.** The OpenRouter client runs with `max_retries=1`, so failures still fall through quickly to the deterministic fallback.
- **Lockfiles excluded from diff.** `*.lock` and `*lock.json` are filtered before sending to the API to save tokens.
- **`--amend` awareness.** Auto-staging is skipped when `--amend` appears in passthrough args to preserve user intent.
- **Structured outputs.** `instructor` wraps LiteLLM with `OPENROUTER_STRUCTURED_OUTPUTS`, so responses are parsed directly into the `CommitMessage` model.
- **Diff truncated at line boundaries.** A 12k character limit (`LAZYCOMMIT_MAX_DIFF_CHARS`) is applied at the nearest newline to avoid partial diffs.
- **Bulk-change guardrail.** When staged files exceed `LAZYCOMMIT_BULK_THRESHOLD` (default `50`), the commit flow skips AI and uses the deterministic fallback unless `--force-ai` is set.
- **Usage tracking.** Every API call captures prompt/completion tokens, cached tokens, reasoning tokens, and cost; printed in execution summary.
- **Silent mode.** `-q, --silent` suppresses stdout while still showing warnings/errors on stderr.
- **Verbose mode.** `-v, --verbose` prints model details, prompt context, diff content, and raw structured responses for debugging.

### Logging and debugging

Lazycommit has a two-tier observability system: a persistent file logger for post-mortem analysis and console output modes for real-time feedback.

#### Persistent file logger (`lazycommit/logger.py`)

Every run writes to `~/.local/state/lazycommit/lazycommit.log` (respects `$XDG_STATE_HOME`). The file rotates at 2 MB with 3 backups. It never raises — setup failures silently fall back to a `NullHandler` so commits are never blocked.

**Log format:**
```
2026-04-01T14:32:05 pid=12345 LEVEL message
```

**What gets logged at each level:**

| Level | Used in | What it captures |
|---|---|---|
| `DEBUG` | `git.py` | Every `git` subprocess: command label, start, exit code, stdout size |
| `INFO` | `flows.py` | Flow start/end with timing, API call timing, auto-stage ops, bulk-change fallback decisions, git commit/push results, rewrite progress per SHA |
| `WARNING` | `flows.py`, `git.py` | Missing `OPENROUTER_API_KEY` (fallback triggered), meta-timeout fired, staging timeouts, git commit/push failures |
| `ERROR` | `flows.py` | API call exceptions (with `exc_info=True` for full traceback) |

**Common log patterns for debugging:**

- **API hang or timeout:** Look for `api_call start` without a matching `api_call end`, or `meta_timeout fired`. Check `elapsed=` values to see how long calls take.
- **Fallback triggered:** Search for `OPENROUTER_API_KEY not set`, `api_call failed`, or `bulk detected`. The `exc=` field shows the exception class when AI generation itself failed.
- **Git operation failure:** Search for `exit` with a non-zero code, or `git commit failed`. The `code=` field gives the exit status.
- **Rewrite progress:** Each SHA gets `rewrite sha=<short> start` and `end message=<preview>`, making it easy to find which commit failed.

#### Console output modes

| Flag | Effect |
|---|---|
| (default) | Normal output: commit message, summary, warnings |
| `-v, --verbose` | Adds: model name, diff content, full API request (system prompt + user context), structured response, timing |
| `-q, --silent` | Suppresses all stdout. Warnings and errors still appear on stderr. Verbose output is also suppressed. |

Verbose output is gated by `not config.silent and config.verbose`. The `_print_verbose_request()` and `_print_verbose_response()` helpers in `console.py` use Rich panels with syntax highlighting.

#### Quick diagnosis guide

```bash
# See what went wrong in the last run
tail -50 ~/.local/state/lazycommit/lazycommit.log

# Watch the log in real time while running
tail -f ~/.local/state/lazycommit/lazycommit.log &  uv run python -m lazycommit

# Debug an API issue: see the full request/response
uv run python -m lazycommit -v

# Debug with maximum detail: verbose + watch the log
uv run python -m lazycommit -v 2>&1 | tee /dev/stderr
```

### Fallback message generation (`build_fallback_message`)

When AI generation is unavailable, the fallback infers commit type and scope from staged paths. Test-only changes map to `test`, docs-only changes map to `docs`, and mixed changes default to `chore`. For 10 or more files it uses a bulk-update subject. It always produces a valid Conventional Commit.

### Rewrite functionality

The `rewrite` subcommand uses `git-filter-repo` (external dependency) to batch-rewrite commit messages. Three modes:
- **Default (`--non-conventional`)**: Only rewrite commits that don't already follow Conventional Commits
- **`--all`**: Rewrite entire history
- **`--unpushed`**: Rewrite commits in `@{u}..HEAD`
- **`<SHA>`**: Rewrite from a specific commit to HEAD

Rewriting sends each commit's diff and original message to the API, then applies all changes in a single `git filter-repo` pass.
Non-dry-run rewrites require a clean worktree before SHA collection or API calls begin.

## Configuration

XDG config file at `~/.config/lazycommit/config.toml` (or `$XDG_CONFIG_HOME/lazycommit/config.toml`):

```toml
# OpenRouter model slug used for commit and rewrite requests.
model = "google/gemini-3.1-flash-lite"

# Reasoning effort: none, minimal, low, medium, high, or xhigh.
reasoning_effort = "none"

# Maximum diff characters sent to the model. Use 0 to omit the diff.
max_diff_chars = 12000

# Per-call API timeout in seconds. Must be greater than 0.
timeout = 10.0

# Commit flow only: skip AI when staged files exceed this count.
# Use 0 to disable the bulk-change guardrail.
bulk_threshold = 50
```

Set `OPENROUTER_API_KEY` in your environment file instead of `config.toml`.

TOML keys map to environment variables:

| TOML key | Environment variable |
|---|---|
| `model` | `LAZYCOMMIT_MODEL` |
| `reasoning_effort` | `LAZYCOMMIT_REASONING_EFFORT` |
| `max_diff_chars` | `LAZYCOMMIT_MAX_DIFF_CHARS` |
| `timeout` | `LAZYCOMMIT_TIMEOUT` |
| `bulk_threshold` | `LAZYCOMMIT_BULK_THRESHOLD` |

Precedence: CLI flag > environment variable > XDG config > hardcoded default.

Runtime dependencies: `litellm`, `instructor`, `pydantic`, `rich`.

Optional `.lazycommit.md` in the repo root injects project-specific context into the prompt. Path can also be set via `--context`.

## Testing

Tests live in `tests/test_lazycommit.py`. All subprocess and AI client calls are mocked, so the suite does not require network access or a real git repository. Coverage includes message assembly, fallback logic, diff truncation, context loading, staging behavior, API integration, usage stats, bulk-change detection, rewrite flow, parser behavior, timeout handling, and end-to-end `main()` flows.
