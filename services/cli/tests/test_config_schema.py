"""Tests for `shepherd_cli.config_schema` — the validated ``shepherd.toml`` schema
(v6.4.2) — and the `shepherd config validate` CLI subcommand that wraps it.

Every assertion that exercises `shepherd_cli.config_schema` directly runs a
`${PY} -c "..."` snippet rather than importing `shepherd_cli` into the pytest
process — the same "never import shepherd_cli into the pytest process itself"
convention `conftest.resolve_fields` and `test_db_readonly.py` already
establish for testing a library function without a full CLI invocation.
`shepherd config validate` itself is driven as a real CLI subprocess, matching
`test_config.py`'s `run_config` pattern (duplicated here rather than imported
— small, intentional duplication, per this package's self-contained-module
convention, same rationale `config.py`'s own module docstring gives for
`_config_search_paths`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

from conftest import PY, REPO_ROOT, clean_env_dict

BUNDLED_MINIMAL_TOML = REPO_ROOT / "examples" / "minimal" / "shepherd.toml"
BUNDLED_RUST_SERVICE_TOML = REPO_ROOT / "examples" / "rust-service" / "shepherd.toml"
DOGFOOD_TOML = REPO_ROOT / ".claude" / "shepherd.toml"


# --------------------------------------------------------------------------
# Library-level helpers (subprocess, never an in-process import).
# --------------------------------------------------------------------------
def _validate_text(text: str, *, file_label: str = "test.toml") -> dict:
    """Run `validate_config_text(text, file_label=file_label)` in a fresh subprocess.

    Returns:
        `report_to_dict()`'s JSON-decoded shape: `{"file", "ok", "issues"}`.
    """
    code = (
        "import json\n"
        "from shepherd_cli.config_schema import validate_config_text, report_to_dict\n"
        f"report = validate_config_text({text!r}, file_label={file_label!r})\n"
        "print(json.dumps(report_to_dict(report)))\n"
    )
    proc = subprocess.run([PY, "-c", code], env=clean_env_dict(), capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"validate_config_text snippet failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def _validate_file(path: Path) -> dict:
    """Run `validate_config_file(path)` in a fresh subprocess.

    Returns:
        `report_to_dict()`'s JSON-decoded shape: `{"file", "ok", "issues"}`.
    """
    code = (
        "import json\n"
        "from shepherd_cli.config_schema import validate_config_file, report_to_dict\n"
        f"report = validate_config_file({str(path)!r})\n"
        "print(json.dumps(report_to_dict(report)))\n"
    )
    proc = subprocess.run([PY, "-c", code], env=clean_env_dict(), capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"validate_config_file snippet failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def run_config(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `${PY} -m shepherd_cli config <args>` under `cwd` (mirrors `test_config.py`)."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "config", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write_toml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# --------------------------------------------------------------------------
# Regression net — the repo's own real-world configs must validate clean.
# --------------------------------------------------------------------------
def test_dogfood_claude_shepherd_toml_validates_clean() -> None:
    """The repo's own self-hosted `.claude/shepherd.toml` — the config that
    exercises nearly every section — MUST validate clean. If this test ever
    fails after a schema edit, the schema is wrong, not the dogfood config:
    this file is real, load-bearing, and continuously exercised by this repo
    running shepherd on itself."""
    report = _validate_file(DOGFOOD_TOML)
    assert report["ok"] is True, report["issues"]
    assert report["issues"] == []


def test_examples_minimal_validates_clean() -> None:
    """The bundled `shctx config init` scaffold template must validate clean —
    every project this template gets copied into starts from a schema-valid
    file, including its several deliberately-empty (all-commented) section
    headers (`[dups]`, `[autorun]`, `[close]`, `[tmux]`, `[compaction]`,
    `[focus]`) — these are real, documented sections, not typos, and must NOT
    be flagged as unknown."""
    report = _validate_file(BUNDLED_MINIMAL_TOML)
    assert report["ok"] is True, report["issues"]
    assert report["issues"] == []


def test_examples_rust_service_validates_clean() -> None:
    """Bonus regression net beyond the two files the task requires: the
    fully-fleshed-out worked example (`[[gates.extra]]` as a real list of
    tables, `[dups]`, `[memory]`, `[compaction]`, `[focus]` all populated with
    real values) also validates clean."""
    report = _validate_file(BUNDLED_RUST_SERVICE_TOML)
    assert report["ok"] is True, report["issues"]
    assert report["issues"] == []


def test_defaults_only_config_validates_clean() -> None:
    """An empty file (every field falls to its documented default) is valid
    BY CONSTRUCTION — a single precedence tier is legitimately partial, and
    the all-tiers-absent case is exactly this: zero keys set anywhere."""
    report = _validate_text("", file_label="empty.toml")
    assert report["ok"] is True
    assert report["issues"] == []


def test_config_using_only_a_few_keys_validates_clean() -> None:
    """A realistic partial `shepherd.local.toml` overriding exactly one
    nested key, nothing else — the whole point of the 5-tier precedence
    chain — must not spuriously require sibling keys or sections."""
    report = _validate_text('[spawn]\nmax_parallel = 2\n', file_label="local.toml")
    assert report["ok"] is True
    assert report["issues"] == []


# --------------------------------------------------------------------------
# Unknown key / unknown section — did-you-mean.
# --------------------------------------------------------------------------
def test_unknown_key_reports_file_and_did_you_mean() -> None:
    report = _validate_text('[project]\nnaem = "x"\n', file_label="myproject/shepherd.toml")

    assert report["ok"] is False
    assert report["file"] == "myproject/shepherd.toml"
    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["kind"] == "unknown_key"
    assert issue["path"] == "[project].naem"
    assert issue["suggestion"] == "name"
    assert "naem" in issue["message"]
    assert "name" in issue["message"]


def test_unknown_key_with_no_close_match_gets_no_suggestion() -> None:
    report = _validate_text('[project]\nzzzzzzzzzzzz = "x"\n', file_label="t.toml")

    issue = report["issues"][0]
    assert issue["kind"] == "unknown_key"
    assert issue["suggestion"] is None
    assert "did you mean" not in issue["message"]


def test_unknown_section_reports_error() -> None:
    report = _validate_text('[bogus_section]\nfoo = 1\n', file_label="t.toml")

    assert report["ok"] is False
    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["kind"] == "unknown_section"
    assert issue["path"] == "[bogus_section]"
    assert "bogus_section" in issue["message"]


def test_unknown_section_with_close_match_gets_did_you_mean() -> None:
    report = _validate_text('[modles]\nroot = "opus"\n', file_label="t.toml")

    issue = report["issues"][0]
    assert issue["kind"] == "unknown_section"
    assert issue["suggestion"] == "models"


def test_nested_unknown_key_reports_dotted_section_path() -> None:
    report = _validate_text(
        "[stage_graph.intro_wave]\nparallell_max = 5\n",
        file_label="t.toml",
    )

    assert report["ok"] is False
    issue = report["issues"][0]
    assert issue["kind"] == "unknown_key"
    assert issue["path"] == "[stage_graph.intro_wave].parallell_max"
    assert issue["suggestion"] == "parallel_max"


def test_open_vocabulary_mcp_keys_are_never_flagged_unknown() -> None:
    """`[mcp]`/`[cli]` accept ANY server/binary name — a name shepherd has
    never heard of is not a typo, it's real project config."""
    report = _validate_text(
        '[mcp]\nsome_totally_new_mcp_server_nobody_has_heard_of = true\n',
        file_label="t.toml",
    )
    assert report["ok"] is True
    assert report["issues"] == []


# --------------------------------------------------------------------------
# Type / enum violations — allowed set.
# --------------------------------------------------------------------------
def test_wrong_enum_value_names_key_bad_value_and_allowed_set() -> None:
    report = _validate_text('[release]\ndriver = "githubworkflow"\n', file_label="t.toml")

    assert report["ok"] is False
    issue = report["issues"][0]
    assert issue["kind"] == "invalid_value"
    assert issue["path"] == "[release].driver"
    assert issue["bad_value"] == "'githubworkflow'"
    assert issue["allowed"] == ["conductor", "github-workflow", "operator"]
    assert "driver" in issue["message"]
    assert "githubworkflow" in issue["message"]
    assert "github-workflow" in issue["message"]


def test_wrong_type_reports_the_offending_key() -> None:
    report = _validate_text('[spawn]\nmax_parallel = "six"\n', file_label="t.toml")

    assert report["ok"] is False
    issue = report["issues"][0]
    assert issue["kind"] == "invalid_value"
    assert issue["path"] == "[spawn].max_parallel"
    assert issue["allowed"] is None


def test_list_of_literal_enum_violation_reports_allowed_set() -> None:
    """`[context].auto_refresh` is a `list[Literal[...]]` — the allowed-set
    lookup must unwrap the list, not just a bare `Optional[Literal[...]]`."""
    report = _validate_text('[context]\nauto_refresh = ["on-bogus-trigger"]\n', file_label="t.toml")

    assert report["ok"] is False
    issue = report["issues"][0]
    assert issue["kind"] == "invalid_value"
    assert "on-sprint-open" in issue["allowed"]


def test_gates_extra_entry_missing_required_field() -> None:
    report = _validate_text('[gates]\nextra = [{name = "only-name"}]\n', file_label="t.toml")

    assert report["ok"] is False
    issue = report["issues"][0]
    assert issue["kind"] == "missing_field"
    assert "cmd" in issue["message"]


def test_gates_extra_accepts_both_documented_shapes() -> None:
    """`[[gates.extra]]` as a list of `{name, cmd}` tables (docs +
    rust-service) AND `[gates.extra]` as a single name -> cmd string table
    (this repo's own dogfood config) both validate clean — see
    `GatesConfig.extra`'s docstring."""
    list_shape = _validate_text(
        '[gates]\nextra = [{name = "a", cmd = "echo a"}]\n', file_label="list.toml"
    )
    table_shape = _validate_text(
        '[gates.extra]\na = "echo a"\n', file_label="table.toml"
    )
    assert list_shape["ok"] is True
    assert table_shape["ok"] is True


def test_dogfood_language_markdown_extension_is_accepted() -> None:
    """`language = "markdown"` extends the documented rust|python|typescript|
    go|mixed enum specifically to keep the dogfood config validating clean."""
    report = _validate_text('[project]\nlanguage = "markdown"\n', file_label="t.toml")
    assert report["ok"] is True


# --------------------------------------------------------------------------
# Parse / read errors.
# --------------------------------------------------------------------------
def test_invalid_toml_syntax_reports_parse_error_not_a_crash() -> None:
    report = _validate_text("[project\nname = \"x\"\n", file_label="broken.toml")

    assert report["ok"] is False
    assert len(report["issues"]) == 1
    issue = report["issues"][0]
    assert issue["kind"] == "parse_error"
    assert "invalid TOML syntax" in issue["message"]


def test_unreadable_file_reports_read_error_not_a_crash(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist" / "shepherd.toml"
    report = _validate_file(missing)

    assert report["ok"] is False
    issue = report["issues"][0]
    assert issue["kind"] == "read_error"
    assert report["file"] == str(missing)


# --------------------------------------------------------------------------
# `shepherd config validate` — CLI integration + exit codes.
# --------------------------------------------------------------------------
def test_validate_exit_0_when_no_config_files_exist(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    (tmp_path / "xdg").mkdir()

    proc = run_config(["validate"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "no config files found" in proc.stdout


def test_validate_exit_0_when_every_existing_tier_is_clean(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    (tmp_path / "xdg").mkdir()
    _write_toml(work_dir / ".shepherd" / "shepherd.toml", '[project]\nname = "ok"\n')
    _write_toml(work_dir / ".claude" / "shepherd.toml", '[spawn]\nmax_parallel = 4\n')

    proc = run_config(["validate"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
    assert str(work_dir / ".shepherd" / "shepherd.toml") in proc.stdout
    assert str(work_dir / ".claude" / "shepherd.toml") in proc.stdout


def test_validate_exit_nonzero_and_names_the_specific_bad_tier(tmp_path: Path) -> None:
    """Two tier files exist, only one is broken — the report must say WHICH."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    (tmp_path / "xdg").mkdir()
    good = work_dir / ".shepherd" / "shepherd.toml"
    bad = work_dir / ".claude" / "shepherd.toml"
    _write_toml(good, '[project]\nname = "ok"\n')
    _write_toml(bad, '[project]\nnaem = "typo"\n')

    proc = run_config(["validate"], work_dir, env)

    assert proc.returncode != 0
    assert f"{good}: OK" in proc.stdout
    assert str(bad) in proc.stdout
    assert "naem" in proc.stdout
    assert "did you mean 'name'" in proc.stdout


def test_validate_json_output_shape(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    (tmp_path / "xdg").mkdir()
    _write_toml(work_dir / ".shepherd" / "shepherd.toml", '[project]\nnaem = "typo"\n')

    proc = run_config(["validate", "--json"], work_dir, env)

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert len(payload["files"]) == 1
    file_report = payload["files"][0]
    assert file_report["ok"] is False
    assert file_report["issues"][0]["kind"] == "unknown_key"
    assert file_report["issues"][0]["suggestion"] == "name"


def test_validate_against_the_real_dogfood_repo_config(tmp_path: Path) -> None:
    """End-to-end: running `shepherd config validate` FROM this repo's own
    root exercises the real `.claude/shepherd.toml` through the full CLI
    path (not just the library function) and must exit 0."""
    env = clean_env_dict()
    xdg = tmp_path / "xdg"  # isolated + empty — a populated host ~/.config must never leak in
    xdg.mkdir()
    env["XDG_CONFIG_HOME"] = str(xdg)
    proc = run_config(["validate"], REPO_ROOT, env)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert str(DOGFOOD_TOML) in proc.stdout
    assert "OK" in proc.stdout


# --------------------------------------------------------------------------
# v6.4.2 tracked-secret hygiene (operator directive, 2026-08-03)
# --------------------------------------------------------------------------
# `shepherd.toml` and `shepherd.<harness>.toml` are COMMITTED, so they carry
# only portable project/harness knobs. Credentials and env-var references --
# which shepherd never expands anyway -- belong in the gitignored
# `shepherd.local.toml`. The gate applies to tracked tiers ONLY: flagging
# `*.local.toml` would invert the contract, since that file is exactly where
# such values are supposed to live.


def test_harnesses_key_validates_clean() -> None:
    """`[project].harnesses` is a documented key, not an unknown one."""
    from shepherd_cli.config_schema import validate_config_text

    report = validate_config_text(
        '[project]\nname = "x"\nharnesses = ["claude-code", "codex"]\n',
        file_label="shepherd.toml",
    )
    assert report.ok, [i.message for i in report.issues]


def test_harnesses_accepts_an_unknown_harness_name() -> None:
    """An open list: a new harness must not fail validation on a repo naming it."""
    from shepherd_cli.config_schema import validate_config_text

    report = validate_config_text(
        '[project]\nharnesses = ["some-future-harness"]\n', file_label="shepherd.toml"
    )
    assert report.ok, [i.message for i in report.issues]


@pytest.mark.parametrize(
    "document",
    [
        '[gh]\napi_key = "abc123"\n',
        '[svc]\npassword = "hunter2"\n',
        '[svc]\nclient_secret = "x"\n',
        '[a]\nb = "ghp_AAAAAAAAAAAAAAAAAAAAAAAA"\n',
        '[a]\nb = "sk-AAAAAAAAAAAAAAAAAAAA"\n',
    ],
)
def test_tracked_file_rejects_credential_shapes(document: str, tmp_path: Path) -> None:
    """A credential in a COMMITTED config is a finding naming the fix."""
    from shepherd_cli.config_schema import validate_config_tier

    path = tmp_path / "shepherd.toml"
    path.write_text(document)
    report = validate_config_tier(str(path), tracked=True)

    assert not report.ok
    assert any(i.kind == "tracked_secret" for i in report.issues)
    assert any("shepherd.local.toml" in i.message for i in report.issues)


def test_tracked_file_rejects_env_var_reference(tmp_path: Path) -> None:
    """shepherd never expands `$VAR`, so one in a tracked file is a finding."""
    from shepherd_cli.config_schema import validate_config_tier

    path = tmp_path / "shepherd.toml"
    path.write_text('[gates]\ncheck = "cargo check --manifest ${HOME}/x"\n')
    report = validate_config_tier(str(path), tracked=True)

    assert not report.ok
    assert any(i.kind == "tracked_env_ref" for i in report.issues)


def test_local_file_allows_exactly_what_the_tracked_file_forbids(tmp_path: Path) -> None:
    """The same content is fine in `*.local.toml` — that is the whole point.

    This is the test that keeps the gate from being a blanket ban: the
    contract is about WHERE a machine-specific value lives, not that it may
    never exist. Uses a schema-VALID section so the only thing that can
    differ between the two files is the hygiene gate itself.
    """
    from shepherd_cli.config_schema import validate_config_tier

    document = '[gates]\ncheck = "cargo check --manifest ${HOME}/x"\n'
    tracked = tmp_path / "shepherd.toml"
    tracked.write_text(document)
    local = tmp_path / "shepherd.local.toml"
    local.write_text(document)

    tracked_report = validate_config_tier(str(tracked), tracked=True)
    assert not tracked_report.ok
    assert any(i.kind == "tracked_env_ref" for i in tracked_report.issues)

    assert validate_config_tier(str(local), tracked=False).ok


def test_scanner_never_echoes_the_secret_value(tmp_path: Path) -> None:
    """A finding must not duplicate the credential into a log or CI transcript."""
    from shepherd_cli.config_schema import validate_config_tier

    secret = "ghp_ZZZZZZZZZZZZZZZZZZZZZZZZ"
    path = tmp_path / "shepherd.toml"
    path.write_text(f'[a]\nb = "{secret}"\n')
    report = validate_config_tier(str(path), tracked=True)

    assert not report.ok
    for issue in report.issues:
        assert secret not in issue.message
        assert secret not in (issue.bad_value or "")
