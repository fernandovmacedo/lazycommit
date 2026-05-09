from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import committer
from committer import Config, flows
from committer import api as api_module
from committer import git as git_module
from committer import logger as logger_module
from committer import rewrite as rewrite_module
from committer.config import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from committer.message import CommitMessage

_FAKE_COMMIT = CommitMessage(type="feat", scope="", subject="add x", body="")
_CUSTOM_MODEL = "google/gemini-3.1-flash-lite"


def _fake_commit_response(
    *_a: object, **_kw: object
) -> tuple[CommitMessage, committer.UsageStats | None]:
    """Mock return value for generate_commit_json."""
    return _FAKE_COMMIT, None


def parsed_args(**overrides: object) -> Config:
    """Create a Config for commit subcommand with defaults."""
    defaults = {
        "subcommand": "commit",
        "dry_run": False,
        "push": False,
        "silent": False,
        "verbose": False,
        "model": DEFAULT_MODEL,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "no_body": False,
        "max_diff_chars": 12000,
        "timeout": 10.0,
        "bulk_threshold": 50,
        "force_ai": False,
        "directory": None,
        "type": None,
        "scope": None,
        "context": None,
        "git_args": (),
    }
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


def parsed_rewrite_args(**overrides: object) -> Config:
    """Create a Config for rewrite subcommand with defaults."""
    defaults = {
        "subcommand": "rewrite",
        "sha": None,
        "all_commits": False,
        "non_conventional": True,
        "unpushed": False,
        "dry_run": False,
        "push": False,
        "silent": False,
        "verbose": False,
        "model": DEFAULT_MODEL,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "no_body": False,
        "max_diff_chars": 12000,
        "timeout": 10.0,
        "bulk_threshold": 50,
        "force_ai": False,
        "directory": None,
    }
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


def test_assemble_message_no_scope() -> None:
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="", subject="add thing", body=""),
        parsed_args(),
    )
    assert msg == "feat: add thing"


def test_assemble_message_with_scope() -> None:
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="api", subject="add thing", body=""),
        parsed_args(),
    )
    assert msg == "feat(api): add thing"


def test_assemble_message_with_body() -> None:
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="", subject="add thing", body="why"),
        parsed_args(),
    )
    assert msg == "feat: add thing\n\nwhy"


def test_assemble_message_no_body_flag() -> None:
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="", subject="add thing", body="why"),
        parsed_args(no_body=True),
    )
    assert msg == "feat: add thing"


def test_assemble_message_type_override() -> None:
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="", subject="add thing", body=""),
        parsed_args(type="fix"),
    )
    assert msg == "fix: add thing"


def test_assemble_message_empty_type_override() -> None:
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="", subject="add thing", body=""),
        parsed_args(type=""),
    )
    assert msg == ": add thing"


def test_assemble_message_scope_override() -> None:
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="", subject="add thing", body=""),
        parsed_args(scope="db"),
    )
    assert msg == "feat(db): add thing"


def test_assemble_message_truncates_header_to_72() -> None:
    long_subject = "a" * 200
    msg = committer.assemble_message(
        CommitMessage(type="feat", scope="api", subject=long_subject, body=""),
        parsed_args(),
    )
    assert len(msg.split("\n", 1)[0]) <= 72


def test_build_fallback_empty() -> None:
    assert committer.build_fallback_message([]) == "chore: update project files"


def test_build_fallback_test_files() -> None:
    msg = committer.build_fallback_message(
        ["M\ttests/test_api.py", "A\tspec/auth_spec.py"]
    )
    assert msg.startswith("test:") or msg.startswith("test(")


def test_build_fallback_doc_files() -> None:
    msg = committer.build_fallback_message(["M\tREADME.md", "A\tdocs/guide.rst"])
    assert msg.startswith("docs:") or msg.startswith("docs(")


def test_build_fallback_mixed() -> None:
    msg = committer.build_fallback_message(["M\tREADME.md", "A\tsrc/app.py"])
    assert msg.startswith("chore:") or msg.startswith("chore(")


def test_build_fallback_scope_from_dir() -> None:
    msg = committer.build_fallback_message(
        ["M\tsrc/app.py", "A\tsrc/api.py", "A\tdocs/x.md"]
    )
    assert msg.startswith("chore(src):")


def test_build_fallback_header_fits_72() -> None:
    msg = committer.build_fallback_message(["M\tsrc/" + ("x" * 200) + ".py"])
    assert len(msg) <= 72


def test_truncate_diff_short() -> None:
    diff = "line1\nline2"
    out, truncated = committer.truncate_diff(diff, 12000)
    assert out == diff
    assert truncated is False


def test_truncate_diff_long() -> None:
    diff = "a\n" * 100
    out, truncated = committer.truncate_diff(diff, 30)
    assert truncated is True
    assert len(out) <= 30
    assert not out.endswith("\n")


def test_load_context_file_explicit(tmp_path: Path) -> None:
    f = tmp_path / "ctx.md"
    f.write_text("hello", encoding="utf-8")
    assert committer.load_context_file(str(f), str(tmp_path)) == "hello"


def test_load_context_file_auto_discovery(tmp_path: Path) -> None:
    f = tmp_path / ".committer.md"
    f.write_text("auto", encoding="utf-8")
    assert committer.load_context_file(None, str(tmp_path)) == "auto"


def test_load_context_file_missing(tmp_path: Path) -> None:
    assert committer.load_context_file(None, str(tmp_path)) == ""


def test_load_context_file_explicit_takes_priority(tmp_path: Path) -> None:
    explicit = tmp_path / "my.md"
    auto = tmp_path / ".committer.md"
    explicit.write_text("explicit", encoding="utf-8")
    auto.write_text("auto", encoding="utf-8")
    assert committer.load_context_file(str(explicit), str(tmp_path)) == "explicit"


def test_build_user_context_no_context() -> None:
    ctx = committer.build_user_context(
        "", "main", "c1", ["M\ta.py"], "stat", "diff", False
    )
    assert "---" not in ctx
    assert ctx.startswith("Branch: main")


def test_build_user_context_with_context() -> None:
    ctx = committer.build_user_context(
        "project rules", "main", "c1", ["M\ta.py"], "stat", "diff", False
    )
    assert ctx.startswith("project rules\n---\n\nBranch: main")


def test_has_staged_changes_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1),
    )
    assert committer.has_staged_changes() is True


def test_run_git_uses_replace_for_invalid_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        captured_kwargs.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok\n")

    monkeypatch.setattr(git_module.subprocess, "run", fake_run)
    assert committer.run_git("status", "--porcelain") == "ok"
    assert captured_kwargs["encoding"] == "utf-8"
    assert captured_kwargs["errors"] == "replace"


def test_has_staged_changes_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0),
    )
    assert committer.has_staged_changes() is False


def test_auto_stage_stages_when_nothing_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        if cmd[:3] == ["git", "diff", "--cached"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(git_module.subprocess, "run", fake_run)
    committer.auto_stage([])
    assert ["git", "add", "-A"] in calls


def test_auto_stage_skips_when_already_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        if cmd[:3] == ["git", "diff", "--cached"]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(git_module.subprocess, "run", fake_run)
    committer.auto_stage([])
    assert ["git", "add", "-A"] not in calls


def test_generate_commit_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        _hidden_params={},
    )
    captured: dict[str, object] = {}

    class FakeCompletions:
        @staticmethod
        def create_with_completion(**kwargs: object) -> tuple[CommitMessage, object]:
            return _FAKE_COMMIT, fake_completion

    class FakeInstructorClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    def fake_from_litellm(_fn: object, **kwargs: object) -> FakeInstructorClient:
        captured.update(kwargs)
        return FakeInstructorClient()

    monkeypatch.setattr(api_module.instructor, "from_litellm", fake_from_litellm)

    commit_msg, stats = committer.generate_commit_json(
        "k", "m", DEFAULT_REASONING_EFFORT, "sp", CommitMessage, "ctx", 1.0
    )
    assert commit_msg.type == "feat"
    assert stats is not None
    assert stats.prompt_tokens == 100
    assert stats.completion_tokens == 50
    assert captured["mode"] is api_module.instructor.Mode.OPENROUTER_STRUCTURED_OUTPUTS


def test_generate_commit_json_passes_model_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    fake_completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
        _hidden_params={},
    )

    class FakeCompletions:
        @staticmethod
        def create_with_completion(**kwargs: object) -> tuple[CommitMessage, object]:
            captured.update(kwargs)
            return _FAKE_COMMIT, fake_completion

    class FakeInstructorClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(
        api_module.instructor,
        "from_litellm",
        lambda _fn, **_kwargs: FakeInstructorClient(),
    )

    committer.generate_commit_json(
        "k",
        _CUSTOM_MODEL,
        DEFAULT_REASONING_EFFORT,
        "sp",
        CommitMessage,
        "ctx",
        1.0,
    )

    assert captured["model"] == f"openrouter/{_CUSTOM_MODEL}"
    assert captured["extra_body"]["reasoning"] == {"effort": DEFAULT_REASONING_EFFORT}
    assert captured["response_model"] is CommitMessage


def test_generate_commit_json_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompletions:
        @staticmethod
        def create_with_completion(**kwargs: object) -> None:
            raise TimeoutError("timeout")

    class FakeInstructorClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(
        api_module.instructor,
        "from_litellm",
        lambda _fn, **_kwargs: FakeInstructorClient(),
    )

    with pytest.raises(TimeoutError):
        committer.generate_commit_json(
            "k", "m", DEFAULT_REASONING_EFFORT, "sp", CommitMessage, "ctx", 1.0
        )


def test_usage_stats_add_accumulates_cost_from_none() -> None:
    stats = committer.UsageStats(1, 2)

    stats.add(committer.UsageStats(3, 4, 0.25))

    assert stats.cost == 0.25


def test_commit_changes_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        flows.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0),
    )
    assert committer.commit_changes("msg", ()) == 0


def test_commit_changes_hook_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        flows.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1),
    )
    assert committer.commit_changes("msg", ()) == 1


def test_main_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(committer, "parse_args", lambda: parsed_args(dry_run=True))
    monkeypatch.setattr(flows, "auto_stage", lambda git_args: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(
        flows,
        "generate_commit_json",
        _fake_commit_response,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer.main()
    out = capsys.readouterr().out
    assert code == 0
    assert "feat: add x" in out


def test_main_verbose_shows_full_api_messages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(
        committer, "parse_args", lambda: parsed_args(dry_run=True, verbose=True)
    )
    monkeypatch.setattr(flows, "auto_stage", lambda git_args: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(
        flows,
        "generate_commit_json",
        _fake_commit_response,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer.main()
    out = capsys.readouterr().out
    assert code == 0
    assert "model:" in out
    assert "--- system prompt ---" in out
    assert "--- user message ---" in out
    assert "--- response ---" in out


def test_verbose_truncation_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(
        committer,
        "parse_args",
        lambda: parsed_args(dry_run=True, verbose=True, max_diff_chars=5),
    )
    monkeypatch.setattr(flows, "auto_stage", lambda git_args: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "abcdef\nghij")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(
        flows,
        "generate_commit_json",
        _fake_commit_response,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer.main()
    out = capsys.readouterr().out
    assert code == 0
    assert "truncated from" in out


def test_main_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(committer, "parse_args", lambda: parsed_args())
    monkeypatch.setattr(flows, "auto_stage", lambda git_args: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tREADME.md"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    commit_mock = Mock(return_value=0)
    monkeypatch.setattr(flows, "commit_changes", commit_mock)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    code = committer.main()
    assert code == 0
    assert commit_mock.called


def test_main_push_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(committer, "parse_args", lambda: parsed_args(push=True))
    monkeypatch.setattr(flows, "auto_stage", lambda git_args: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(
        flows,
        "generate_commit_json",
        _fake_commit_response,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(flows, "commit_changes", lambda msg, args: 0)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(flows.subprocess, "run", fake_run)

    code = committer.main()
    assert code == 0
    assert ["git", "push"] in calls


def test_main_push_skipped_on_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(
        committer, "parse_args", lambda: parsed_args(dry_run=True, push=True)
    )
    monkeypatch.setattr(flows, "auto_stage", lambda git_args: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(
        flows,
        "generate_commit_json",
        _fake_commit_response,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(flows.subprocess, "run", fake_run)

    code = committer.main()
    assert code == 0
    assert ["git", "push"] not in calls


def test_load_xdg_config_ignores_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "committer"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('api_key = "abc"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    committer.load_xdg_config()

    assert os.environ.get("OPENROUTER_API_KEY") is None


def test_load_xdg_config_leaves_existing_api_key_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "committer"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('api_key = "fromfile"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "existing")

    committer.load_xdg_config()

    assert os.environ.get("OPENROUTER_API_KEY") == "existing"


def test_load_xdg_config_defaults_to_home_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / ".config" / "committer"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.toml"
    config_file.write_text('model = "test-model"\n', encoding="utf-8")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("COMMITTER_MODEL", raising=False)

    committer.load_xdg_config()

    assert os.environ.get("COMMITTER_MODEL") == "test-model"


def test_load_xdg_config_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "committer"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('reasoning_effort = "none"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("COMMITTER_REASONING_EFFORT", raising=False)

    committer.load_xdg_config()

    assert os.environ.get("COMMITTER_REASONING_EFFORT") == "none"


def test_load_xdg_config_handles_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    # Should not raise, just return silently
    committer.load_xdg_config()

    assert os.environ.get("OPENROUTER_API_KEY") is None


def test_load_xdg_config_handles_invalid_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "committer"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text("invalid toml [[[\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    warn_mock = Mock()
    monkeypatch.setattr(git_module, "warn", warn_mock)

    committer.load_xdg_config()

    assert os.environ.get("OPENROUTER_API_KEY") is None
    warn_mock.assert_called_once()
    assert "config.toml is invalid" in warn_mock.call_args[0][0]


def test_load_xdg_config_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "committer"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('model = "test-model"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    warn_mock = Mock()
    monkeypatch.setattr(git_module, "warn", warn_mock)

    real_open = open

    def fake_open(path: object, *args: object, **kwargs: object) -> object:
        if str(path) == str(config_file):
            raise PermissionError("permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)

    committer.load_xdg_config()

    warn_mock.assert_called_once()
    assert "config.toml is unreadable" in warn_mock.call_args[0][0]


def test_config_invalid_env_var(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COMMITTER_MAX_DIFF_CHARS", "abc")

    with pytest.raises(SystemExit) as exc:
        Config(subcommand="commit")

    assert exc.value.code == 1
    assert "invalid value for COMMITTER_MAX_DIFF_CHARS" in capsys.readouterr().err


def test_load_xdg_config_converts_numbers_to_strings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "committer"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        "max_diff_chars = 5000\ntimeout = 15.5\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("COMMITTER_MAX_DIFF_CHARS", raising=False)
    monkeypatch.delenv("COMMITTER_TIMEOUT", raising=False)

    committer.load_xdg_config()

    assert os.environ.get("COMMITTER_MAX_DIFF_CHARS") == "5000"
    assert os.environ.get("COMMITTER_TIMEOUT") == "15.5"


def test_main_nothing_to_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(committer, "parse_args", lambda: parsed_args())
    monkeypatch.setattr(flows, "auto_stage", lambda git_args: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: False)

    assert committer.main() == 0
    assert "nothing to commit" in capsys.readouterr().out


def test_main_not_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(committer, "parse_args", lambda: parsed_args())
    monkeypatch.setattr(flows, "get_repo_root", lambda: None)
    with pytest.raises(SystemExit) as exc:
        committer.main()
    assert exc.value.code == 1


def test_is_conventional_true() -> None:
    assert committer._is_conventional("feat: add x")
    assert committer._is_conventional("fix(api): patch timeout")
    assert committer._is_conventional("chore!: drop old flow")
    assert committer._is_conventional("revert: rollback release")


def test_is_conventional_false() -> None:
    assert not committer._is_conventional("update stuff")
    assert not committer._is_conventional("wip: try things")
    assert not committer._is_conventional("just text")


def test_get_rewrite_shas_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rewrite_module,
        "run_git",
        lambda *args: "a1\nb2\nc3"
        if args == ("log", "--format=%H", "--reverse")
        else "",
    )
    out = committer._get_rewrite_shas(
        None, all_commits=True, non_conventional=False, unpushed=False
    )
    assert out == ["a1", "b2", "c3"]


def test_get_rewrite_shas_from_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="b2\nc3\n")

    monkeypatch.setattr(rewrite_module.subprocess, "run", fake_run)
    out = committer._get_rewrite_shas(
        "b2", all_commits=False, non_conventional=False, unpushed=False
    )
    assert out == ["b2", "c3"]
    assert ["git", "log", "--format=%H", "--reverse", "b2~..HEAD"] in calls


def test_check_filter_repo_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*args: object, **kwargs: object) -> SimpleNamespace:
        raise PermissionError("permission denied")

    monkeypatch.setattr(rewrite_module.subprocess, "run", fail_run)

    with pytest.raises(SystemExit) as exc:
        rewrite_module._check_filter_repo()

    assert exc.value.code == 1


def test_get_rewrite_shas_non_conventional(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_git(*args: str) -> str | None:
        if args == ("log", "--format=%H", "--reverse"):
            return "a1\nb2\nc3"
        if args == ("show", "-s", "--format=%s", "a1"):
            return "feat: done"
        if args == ("show", "-s", "--format=%s", "b2"):
            return "update docs"
        if args == ("show", "-s", "--format=%s", "c3"):
            return "fix(api): patch"
        return None

    monkeypatch.setattr(rewrite_module, "run_git", fake_run_git)
    out = committer._get_rewrite_shas(
        None, all_commits=False, non_conventional=True, unpushed=False
    )
    assert out == ["b2"]


def test_get_rewrite_shas_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rewrite_module, "run_git", lambda *args: None)
    out = committer._get_rewrite_shas(
        None, all_commits=False, non_conventional=True, unpushed=False
    )
    assert out == []


def test_get_rewrite_shas_unpushed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="a1\nb2\n")

    monkeypatch.setattr(rewrite_module.subprocess, "run", fake_run)
    out = committer._get_rewrite_shas(
        None, all_commits=False, non_conventional=False, unpushed=True
    )
    assert out == ["a1", "b2"]
    assert ["git", "rev-list", "--reverse", "@{u}..HEAD"] in calls


def test_get_rewrite_shas_unpushed_no_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=128, stdout="")

    monkeypatch.setattr(rewrite_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        rewrite_module, "die", lambda msg: (_ for _ in ()).throw(SystemExit(msg))
    )
    with pytest.raises(SystemExit, match="no upstream configured"):
        committer._get_rewrite_shas(
            None, all_commits=False, non_conventional=False, unpushed=True
        )


def test_get_rewrite_shas_unpushed_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(rewrite_module.subprocess, "run", fake_run)
    out = committer._get_rewrite_shas(
        None, all_commits=False, non_conventional=False, unpushed=True
    )
    assert out == []


def test_build_commit_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_git(*args: str) -> str | None:
        if args == ("show", "-s", "--format=%B", "abc123"):
            return "old message"
        if args == (
            "show",
            "abc123",
            "--",
            ".",
            ":(exclude)*.lock",
            ":(exclude)*lock.json",
        ):
            return "diff --git a/x b/x\n+line"
        if args == ("show", "--stat", "abc123"):
            return "1 file changed"
        if args == ("show", "--name-status", "--format=", "abc123"):
            return "M\tsrc/app.py"
        return None

    monkeypatch.setattr(rewrite_module, "run_git", fake_run_git)
    ctx = committer._build_commit_context("abc123", "main", 12000)
    assert "Rewriting existing commit." in ctx
    assert "Current message:\nold message" in ctx
    assert "Branch: main" in ctx
    assert "Staged files:\nM\tsrc/app.py" in ctx


def test_apply_filter_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    callback_paths: list[Path] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        callback_arg = cmd[-1]
        callback_paths.append(Path(callback_arg.removeprefix("@")))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rewrite_module.subprocess, "run", fake_run)
    committer._apply_filter_repo({"abc123": "feat: add x"})

    assert calls
    assert calls[0][:4] == ["git", "filter-repo", "--force", "--commit-callback"]
    assert not callback_paths[0].exists()


def test_apply_filter_repo_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rewrite_module.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=1),
    )
    monkeypatch.setattr(
        rewrite_module, "die", lambda msg: (_ for _ in ()).throw(SystemExit(msg))
    )

    with pytest.raises(SystemExit, match=r"git filter-repo failed \(exit 1\)"):
        committer._apply_filter_repo({"abc123": "feat: add x"})


def test_rewrite_flow_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(flows, "_check_filter_repo", lambda: None)
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(flows, "_get_rewrite_shas", lambda *_a, **_k: ["a1"])
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "_build_commit_context", lambda *_a, **_k: "ctx")
    monkeypatch.setattr(
        flows, "run_git", lambda *args: "M\tsrc/app.py" if args[0] == "show" else None
    )
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    apply_called = {"value": False}
    def mark_applied(_message_map: dict[str, str]) -> None:
        apply_called["value"] = True

    monkeypatch.setattr(
        flows, "_apply_filter_repo", mark_applied
    )

    code = committer._rewrite_flow(parsed_rewrite_args(dry_run=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "a1" in out
    assert "Token usage: total=0 input=0 (+ 0 cached) output=0 (reasoning 0)" in out
    assert apply_called["value"] is False


def test_rewrite_flow_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flows, "_check_filter_repo", lambda: None)
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(flows, "_get_rewrite_shas", lambda *_a, **_k: ["a1", "b2"])
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "_build_commit_context", lambda *_a, **_k: "ctx")
    monkeypatch.setattr(
        flows, "run_git", lambda *args: "M\tsrc/app.py" if args[0] == "show" else None
    )
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    captured: dict[str, str] = {}

    def capture_map(message_map: dict[str, str]) -> None:
        captured.update(message_map)

    monkeypatch.setattr(flows, "_apply_filter_repo", capture_map)

    code = committer._rewrite_flow(parsed_rewrite_args())
    assert code == 0
    assert captured == {"a1": "feat: add x", "b2": "feat: add x"}


def test_rewrite_flow_nothing_to_rewrite(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(flows, "_check_filter_repo", lambda: None)
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(flows, "_get_rewrite_shas", lambda *_a, **_k: [])

    code = committer._rewrite_flow(parsed_rewrite_args())
    out = capsys.readouterr().out
    assert code == 0
    assert "nothing to rewrite" in out
    assert "Cost:" not in out
    assert "Token usage: total=0 input=0 (+ 0 cached) output=0 (reasoning 0)" in out


def test_rewrite_flow_api_failure_omits_cost(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(flows, "_check_filter_repo", lambda: None)
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(flows, "_get_rewrite_shas", lambda *_a, **_k: ["a1"])
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "_build_commit_context", lambda *_a, **_k: "ctx")
    monkeypatch.setattr(
        flows, "run_git", lambda *args: "M\tsrc/app.py" if args[0] == "show" else None
    )
    def fail_generate_commit_json(**_kwargs: object) -> tuple[CommitMessage, None]:
        raise TimeoutError("timeout")

    monkeypatch.setattr(flows, "generate_commit_json", fail_generate_commit_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer._rewrite_flow(parsed_rewrite_args(dry_run=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "Cost:" not in out
    assert "Token usage: total=0 input=0 (+ 0 cached) output=0 (reasoning 0)" in out


def test_rewrite_flow_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flows, "_check_filter_repo", lambda: None)
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(flows, "_get_rewrite_shas", lambda *_a, **_k: ["a1"])
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "_build_commit_context", lambda *_a, **_k: "ctx")
    monkeypatch.setattr(
        flows, "run_git", lambda *args: "M\tsrc/app.py" if args[0] == "show" else None
    )
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setattr(flows, "_apply_filter_repo", lambda message_map: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(flows.subprocess, "run", fake_run)
    code = committer._rewrite_flow(parsed_rewrite_args(push=True))
    assert code == 0
    assert ["git", "push", "--force-with-lease"] in calls


def test_commit_flow_warns_on_push_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "auto_stage", lambda *_a: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setattr(flows, "commit_changes", lambda message, git_args: 0)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    warnings: list[str] = []
    log_warnings: list[str] = []
    monkeypatch.setattr(flows, "warn", lambda msg: warnings.append(msg))
    monkeypatch.setattr(flows, "log_warning", lambda msg: log_warnings.append(msg))
    monkeypatch.setattr(
        flows.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=1, stderr=b"remote rejected"),
    )

    code = committer._commit_flow(parsed_args(push=True))

    assert code == 0
    assert warnings == ["git push failed"]
    assert any("remote rejected" in msg for msg in log_warnings)


def test_rewrite_flow_warns_on_push_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(flows, "_check_filter_repo", lambda: None)
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "_get_rewrite_shas", lambda *_a, **_k: ["a1"])
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "_build_commit_context", lambda *_a, **_k: "ctx")
    monkeypatch.setattr(
        flows, "run_git", lambda *args: "M\tsrc/app.py" if args[0] == "show" else None
    )
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setattr(flows, "_apply_filter_repo", lambda message_map: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    warnings: list[str] = []
    log_warnings: list[str] = []
    monkeypatch.setattr(flows, "warn", lambda msg: warnings.append(msg))
    monkeypatch.setattr(flows, "log_warning", lambda msg: log_warnings.append(msg))
    monkeypatch.setattr(
        flows.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=1, stderr=b"lease rejected"),
    )

    code = committer._rewrite_flow(parsed_rewrite_args(push=True))

    assert code == 0
    assert warnings == ["git push --force-with-lease failed"]
    assert any("lease rejected" in msg for msg in log_warnings)


def test_commit_flow_passes_custom_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "auto_stage", lambda *_a: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(flows, "commit_changes", lambda message, git_args: 0)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    captured: dict[str, object] = {}

    def fake_generate_commit_json(**kwargs: object) -> tuple[CommitMessage, None]:
        captured.update(kwargs)
        return _FAKE_COMMIT, None

    monkeypatch.setattr(flows, "generate_commit_json", fake_generate_commit_json)

    code = committer._commit_flow(parsed_args(dry_run=True, model=_CUSTOM_MODEL))

    assert code == 0
    assert captured["model"] == _CUSTOM_MODEL


def test_rewrite_flow_passes_custom_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(flows, "_check_filter_repo", lambda: None)
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "_get_rewrite_shas", lambda *_a, **_k: ["a1"])
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "_build_commit_context", lambda *_a, **_k: "ctx")
    monkeypatch.setattr(
        flows, "run_git", lambda *args: "M\tsrc/app.py" if args[0] == "show" else None
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    captured: dict[str, object] = {}

    def fake_generate_commit_json(**kwargs: object) -> tuple[CommitMessage, None]:
        captured.update(kwargs)
        return _FAKE_COMMIT, None

    monkeypatch.setattr(flows, "generate_commit_json", fake_generate_commit_json)

    code = committer._rewrite_flow(
        parsed_rewrite_args(dry_run=True, model=_CUSTOM_MODEL)
    )

    assert code == 0
    assert captured["model"] == _CUSTOM_MODEL


def test_parse_directory_commit(tmp_path: Path) -> None:
    """Test that -C flag is parsed correctly for commit subcommand."""
    sys.argv = ["committer", "-C", str(tmp_path)]
    config = committer.parse_args()
    assert config.directory == str(tmp_path)


def test_parse_directory_rewrite(tmp_path: Path) -> None:
    """Test that -C flag is parsed correctly for rewrite subcommand."""
    sys.argv = ["committer", "rewrite", "-C", str(tmp_path)]
    config = committer.parse_args()
    assert config.directory == str(tmp_path)


def test_parse_model_commit_cli_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMMITTER_MODEL", "anthropic/claude-sonnet")
    sys.argv = ["committer", "--model", _CUSTOM_MODEL]

    config = committer.parse_args()

    assert config.model == _CUSTOM_MODEL


def test_parse_model_rewrite_cli_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMMITTER_MODEL", "anthropic/claude-sonnet")
    sys.argv = ["committer", "rewrite", "--model", _CUSTOM_MODEL]

    config = committer.parse_args()

    assert config.model == _CUSTOM_MODEL


def test_parse_reasoning_effort_commit_cli_override() -> None:
    sys.argv = ["committer", "--reasoning-effort", "minimal"]

    config = committer.parse_args()

    assert config.reasoning_effort == "minimal"


def test_parse_reasoning_effort_rewrite_cli_override() -> None:
    sys.argv = ["committer", "rewrite", "--reasoning-effort", "high"]

    config = committer.parse_args()

    assert config.reasoning_effort == "high"


def test_parse_silent_short_flag_commit() -> None:
    sys.argv = ["committer", "-q"]

    config = committer.parse_args()

    assert config.silent is True


def test_parse_reasoning_effort_short_flag_commit() -> None:
    sys.argv = ["committer", "-r", "minimal"]

    config = committer.parse_args()

    assert config.reasoning_effort == "minimal"


def test_parse_bulk_threshold_short_flag_commit() -> None:
    sys.argv = ["committer", "-B", "10"]

    config = committer.parse_args()

    assert config.bulk_threshold == 10


def test_parse_force_ai_short_flag_commit() -> None:
    sys.argv = ["committer", "-F"]

    config = committer.parse_args()

    assert config.force_ai is True


def test_parse_all_short_flag_rewrite() -> None:
    sys.argv = ["committer", "rewrite", "-a"]

    config = committer.parse_args()

    assert config.all_commits is True


def test_parse_non_conventional_short_flag_rewrite() -> None:
    sys.argv = ["committer", "rewrite", "-N"]

    config = committer.parse_args()

    assert config.non_conventional is True


def test_parse_unpushed_short_flag_rewrite() -> None:
    sys.argv = ["committer", "rewrite", "-u"]

    config = committer.parse_args()

    assert config.unpushed is True


def test_parse_removed_silent_short_flag_rejected() -> None:
    sys.argv = ["committer", "-S"]

    with pytest.raises(SystemExit):
        committer.parse_args()


def test_parse_negative_max_diff_chars_rejected() -> None:
    sys.argv = ["committer", "--max-diff-chars", "-1"]

    with pytest.raises(SystemExit) as exc:
        committer.parse_args()

    assert exc.value.code == 2


def test_parse_negative_timeout_rejected() -> None:
    sys.argv = ["committer", "--timeout", "-1"]

    with pytest.raises(SystemExit) as exc:
        committer.parse_args()

    assert exc.value.code == 2


def test_parse_zero_timeout_rejected() -> None:
    sys.argv = ["committer", "--timeout", "0"]

    with pytest.raises(SystemExit) as exc:
        committer.parse_args()

    assert exc.value.code == 2


def test_parse_empty_type_rejected() -> None:
    sys.argv = ["committer", "--type", ""]

    with pytest.raises(SystemExit) as exc:
        committer.parse_args()

    assert exc.value.code == 2


def test_version_exposed() -> None:
    assert committer.__version__ == "1.0.0"


def test_commit_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    sys.argv = ["committer", "--version"]

    with pytest.raises(SystemExit) as exc:
        committer.parse_args()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "committer 1.0.0"


def test_rewrite_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    sys.argv = ["committer", "rewrite", "--version"]

    with pytest.raises(SystemExit) as exc:
        committer.parse_args()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "committer rewrite 1.0.0"


def test_logger_falls_back_to_nullhandler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    logger = logger_module.logging.getLogger("committer-test")
    logger.handlers.clear()
    monkeypatch.setattr(
        logger_module.logging, "getLogger", lambda name="": logger
    )

    def fail_handler(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(logger_module, "RotatingFileHandler", fail_handler)

    built = logger_module._make_logger()

    assert built is logger
    assert any(
        isinstance(handler, logger_module.logging.NullHandler)
        for handler in logger.handlers
    )
    assert "could not set up log file: disk full" in capsys.readouterr().err


def test_parse_rewrite_rejects_bulk_threshold_flag() -> None:
    """Rewrite parser should not expose commit-only bulk-change flags."""
    sys.argv = ["committer", "rewrite", "--bulk-threshold", "10"]

    with pytest.raises(SystemExit):
        committer.parse_args()


def test_parse_rewrite_rejects_force_ai_flag() -> None:
    """Rewrite parser should not expose commit-only bulk-change flags."""
    sys.argv = ["committer", "rewrite", "--force-ai"]

    with pytest.raises(SystemExit):
        committer.parse_args()


def test_main_chdir_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that main() calls os.chdir with the directory from config."""
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(
        committer, "parse_args", lambda: parsed_args(directory=str(tmp_path))
    )

    chdir_calls: list[str] = []
    monkeypatch.setattr(os, "chdir", lambda path: chdir_calls.append(path))

    # Mock the flow to avoid further execution
    monkeypatch.setattr(committer, "_commit_flow", lambda config: 0)

    code = committer.main()
    assert code == 0
    assert chdir_calls == [str(tmp_path)]


def test_main_directory_not_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that main() exits with error if directory does not exist."""
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(
        committer, "parse_args", lambda: parsed_args(directory="/nonexistent/xyz")
    )

    with pytest.raises(SystemExit) as exc:
        committer.main()
    assert exc.value.code == 1


def test_main_chdir_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(committer, "load_xdg_config", lambda: None)
    monkeypatch.setattr(
        committer, "parse_args", lambda: parsed_args(directory=str(tmp_path))
    )

    def fail_chdir(_path: str) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(os, "chdir", fail_chdir)

    with pytest.raises(SystemExit) as exc:
        committer.main()

    assert exc.value.code == 1


def test_main_returns_130_on_keyboard_interrupt_during_load_xdg_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_keyboard_interrupt() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(committer, "load_xdg_config", raise_keyboard_interrupt)

    assert committer.main() == 130


# ── Meta-timeout tests ─────────────────────────────────────────────────────


def test_meta_timeout_arms_and_disarms_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Context manager arms alarm on enter and disarms on exit."""
    alarm_calls: list[int] = []

    monkeypatch.setattr(flows.signal, "alarm", lambda s: alarm_calls.append(s) or 0)
    monkeypatch.setattr(flows.signal, "signal", lambda *a: signal.SIG_DFL)

    with flows._ApiMetaTimeout(10.0):
        pass

    assert len(alarm_calls) == 2
    assert alarm_calls[0] == 25  # 10 * 2 + 5
    assert alarm_calls[1] == 0  # disarmed


def test_meta_timeout_restores_previous_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Context manager restores the previous signal handler on exit."""
    original = signal.SIG_IGN
    calls: list[object] = []

    def fake_signal(signum: int, handler: object) -> object:
        calls.append(handler)
        return original

    monkeypatch.setattr(flows.signal, "signal", fake_signal)
    monkeypatch.setattr(flows.signal, "alarm", lambda s: 0)

    with flows._ApiMetaTimeout(10.0):
        pass

    assert len(calls) == 2
    assert calls[1] is original  # restored


def test_meta_timeout_skips_on_non_main_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Context manager is a no-op when not on the main thread."""
    alarm_calls: list[int] = []

    monkeypatch.setattr(flows.signal, "alarm", lambda s: alarm_calls.append(s) or 0)
    monkeypatch.setattr(
        flows.threading,
        "current_thread",
        lambda: SimpleNamespace(name="Thread-1"),
    )

    with flows._ApiMetaTimeout(10.0):
        pass

    assert alarm_calls == []


def test_meta_timeout_handler_raises_timeout_error() -> None:
    """The signal handler raises TimeoutError."""
    with pytest.raises(TimeoutError, match="meta-timeout"):
        flows._meta_timeout_handler(signal.SIGALRM, None)


def test_commit_flow_meta_timeout_falls_back(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When meta-timeout fires, _commit_flow falls back to deterministic message."""
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "auto_stage", lambda *_a: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: ["M\tsrc/app.py"])
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "1 file changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(flows, "commit_changes", lambda msg, args: 0)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    monkeypatch.setattr(
        flows,
        "generate_commit_json",
        lambda **kw: (_ for _ in ()).throw(
            TimeoutError("API call exceeded meta-timeout deadline")
        ),
    )

    code = committer._commit_flow(parsed_args(dry_run=True))
    captured = capsys.readouterr()
    assert code == 0
    assert "[fallback]" in captured.err


# ---------------------------------------------------------------------------
# Bulk-change detection tests
# ---------------------------------------------------------------------------

def _many_files(n: int) -> list[str]:
    """Generate n staged-file entries for bulk tests."""
    return [f"M\tsrc/file_{i}.py" for i in range(n)]


def test_bulk_detection_uses_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When staged files exceed threshold, fallback is used without API call."""
    api_called = False

    def _assert_not_called(**kw: object) -> None:
        nonlocal api_called
        api_called = True

    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "auto_stage", lambda *_a: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: _many_files(60))
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "60 files changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(flows, "commit_changes", lambda msg, args: 0)
    monkeypatch.setattr(flows, "generate_commit_json", _assert_not_called)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer._commit_flow(parsed_args(dry_run=True))
    captured = capsys.readouterr()
    assert code == 0
    assert not api_called
    assert "bulk change: 60 files" in captured.out
    assert "[fallback]" in captured.err


def test_bulk_detection_force_ai_overrides(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--force-ai bypasses bulk detection and calls the API."""
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "auto_stage", lambda *_a: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: _many_files(60))
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "60 files changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(flows, "commit_changes", lambda msg, args: 0)
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer._commit_flow(parsed_args(dry_run=True, force_ai=True))
    captured = capsys.readouterr()
    assert code == 0
    assert "feat: add x" in captured.out
    assert "bulk change" not in captured.out


def test_bulk_threshold_zero_disables(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """bulk_threshold=0 disables bulk detection entirely."""
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "auto_stage", lambda *_a: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: _many_files(200))
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "200 files changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(flows, "commit_changes", lambda msg, args: 0)
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer._commit_flow(
        parsed_args(dry_run=True, bulk_threshold=0)
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "feat: add x" in captured.out
    assert "bulk change" not in captured.out


def test_bulk_detection_custom_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bulk detection respects a custom threshold."""
    monkeypatch.setattr(flows, "get_repo_root", lambda: "/repo")
    monkeypatch.setattr(flows, "auto_stage", lambda *_a: None)
    monkeypatch.setattr(flows, "has_staged_changes", lambda: True)
    monkeypatch.setattr(flows, "get_staged_files", lambda: _many_files(15))
    monkeypatch.setattr(flows, "get_staged_stat", lambda: "15 files changed")
    monkeypatch.setattr(flows, "get_staged_diff", lambda: "diff")
    monkeypatch.setattr(flows, "get_branch_name", lambda: "main")
    monkeypatch.setattr(flows, "get_recent_commits", lambda: "abc chore: x")
    monkeypatch.setattr(flows, "load_context_file", lambda path, root: "")
    monkeypatch.setattr(flows, "commit_changes", lambda msg, args: 0)
    monkeypatch.setattr(flows, "generate_commit_json", _fake_commit_response)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    code = committer._commit_flow(
        parsed_args(dry_run=True, bulk_threshold=10)
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "bulk change: 15 files" in captured.out
    assert "[fallback]" in captured.err


def test_build_fallback_bulk_subject() -> None:
    """When >= 10 files, fallback uses 'bulk update across N files'."""
    files = _many_files(20)
    msg = committer.build_fallback_message(files)
    assert "bulk update across 20 files" in msg


def test_parse_bulk_threshold() -> None:
    """bulk_threshold reads from COMMITTER_BULK_THRESHOLD env var."""
    os.environ["COMMITTER_BULK_THRESHOLD"] = "25"
    try:
        cfg = Config(subcommand="commit")
        assert cfg.bulk_threshold == 25
    finally:
        del os.environ["COMMITTER_BULK_THRESHOLD"]


def test_parse_reasoning_effort_default() -> None:
    """reasoning_effort reads from COMMITTER_REASONING_EFFORT env var."""
    os.environ["COMMITTER_REASONING_EFFORT"] = "minimal"
    try:
        cfg = Config(subcommand="commit")
        assert cfg.reasoning_effort == "minimal"
    finally:
        del os.environ["COMMITTER_REASONING_EFFORT"]


def test_parse_force_ai() -> None:
    """--force-ai flag sets force_ai=True on Config."""
    cfg = Config(subcommand="commit", force_ai=True)
    assert cfg.force_ai is True


def test_load_xdg_config_bulk_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bulk_threshold in TOML sets COMMITTER_BULK_THRESHOLD env var."""
    config_dir = tmp_path / "committer"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('bulk_threshold = 30\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("COMMITTER_BULK_THRESHOLD", raising=False)

    git_module.load_xdg_config()

    assert os.environ.get("COMMITTER_BULK_THRESHOLD") == "30"
