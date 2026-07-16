"""Subprocess parity tests for ``shepherd audit`` (lint -> doctor -> status pipeline + ``insert``).

Bash parity target: ``skills/context/scripts/cmd_audit.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli audit ...``),
exactly like ``test_sync.py`` — never by importing ``shepherd_cli`` into
the pytest process.

Two independent halves, tested separately:

1. **The pipeline** (bare ``shepherd audit`` / ``shepherd audit
   --verbose``) shells out to three sibling scripts (``cmd_lint.sh``,
   ``cmd_doctor.sh``, ``cmd_status.sh``) and touches no database of its
   own. Driving the REAL sibling scripts from a gate test would violate
   the "deterministic, local, free, <2s, never flaky" gate-test contract
   (CLAUDE.md) — ``cmd_doctor.sh`` in particular resolves its namespace/
   project.json checks against the AMBIENT repo state (not
   ``SHCTX_DB``-scoped), so it is neither hermetic nor fast. Exactly like
   ``test_sync.py``, this suite builds a throwaway "fake plugin root"
   (:func:`_make_fake_plugin_root`) containing tiny, fully-scripted
   stand-ins for all three sibling scripts — each one logs its invocation
   to ``$CALL_LOG`` and exits with a caller-controlled code (via
   ``FAKE_RC_*`` env vars) — and points ``CLAUDE_PLUGIN_ROOT`` at it.
2. **``insert``** DOES touch a real fixture database (built the same way
   every other DB-backed suite in this package builds one —
   ``conftest.build_full_schema_db`` + ``conftest.insert_project``) and is
   tested against it directly, with stdin fed via a raw ``subprocess.run``
   call (``conftest.run_cli`` has no ``input=`` passthrough, since no
   other ported command reads stdin yet).
"""

from __future__ import annotations

import json
import sqlite3
import stat
import subprocess
import time
from pathlib import Path

import pytest
from conftest import CLI_ROOT, PY, build_full_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Fake sibling scripts — deterministic stand-ins for cmd_lint.sh,
# cmd_doctor.sh, cmd_status.sh (pipeline path only; `insert` never touches
# these).
# --------------------------------------------------------------------------

_STUB_PREAMBLE = '#!/usr/bin/env bash\necho "{name} $*" >> "$CALL_LOG"\n'

_FAKE_SCRIPTS: dict[str, str] = {
    "cmd_lint.sh": _STUB_PREAMBLE.format(name="cmd_lint.sh")
    + ('echo "stdout:cmd_lint.sh"\necho "stderr:cmd_lint.sh" >&2\nexit "${FAKE_RC_LINT:-0}"\n'),
    "cmd_doctor.sh": _STUB_PREAMBLE.format(name="cmd_doctor.sh")
    + ('echo "stdout:cmd_doctor.sh"\necho "stderr:cmd_doctor.sh" >&2\nexit "${FAKE_RC_DOCTOR:-0}"\n'),
    "cmd_status.sh": _STUB_PREAMBLE.format(name="cmd_status.sh")
    + ('echo "stdout:cmd_status.sh"\necho "stderr:cmd_status.sh" >&2\nexit "${FAKE_RC_STATUS:-0}"\n'),
}


def _make_fake_plugin_root(tmp_path: Path) -> Path:
    """Build a throwaway ``CLAUDE_PLUGIN_ROOT`` tree with fully-scripted sibling commands.

    Layout mirrors the real plugin just enough for
    :func:`shepherd_cli.resolution.find_bash_shctx` to resolve it:
    ``skills/context/scripts/{shctx, cmd_lint.sh, cmd_doctor.sh,
    cmd_status.sh}``.

    Args:
        tmp_path: The pytest-provided per-test temp directory.

    Returns:
        The fake plugin root directory (the ``CLAUDE_PLUGIN_ROOT`` value),
        three levels above ``skills/context/scripts``.
    """
    scripts_dir = tmp_path / "fake-plugin-root" / "skills" / "context" / "scripts"
    scripts_dir.mkdir(parents=True)

    shctx_path = scripts_dir / "shctx"
    shctx_path.write_text("#!/usr/bin/env bash\nexit 0\n")
    shctx_path.chmod(shctx_path.stat().st_mode | stat.S_IEXEC)

    for name, content in _FAKE_SCRIPTS.items():
        script_path = scripts_dir / name
        script_path.write_text(content)
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    return scripts_dir.parent.parent.parent


def audit_env(
    fake_plugin_root: Path,
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd audit`` pipeline test.

    Args:
        fake_plugin_root: The fake plugin root from
            :func:`_make_fake_plugin_root`.
        call_log: Path the fake sibling scripts append one line to per
            invocation (``$CALL_LOG``).
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_DOCTOR": "2"}``.

    Returns:
        A full subprocess environment. Deliberately does NOT need a real
        ``SHCTX_DB`` — the pipeline path never opens a database connection
        (a throwaway path is set anyway purely so ``cli_env`` has
        something to point at; it is never actually opened).
    """
    env = cli_env(fake_plugin_root / "unused.db")
    env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
    env["CALL_LOG"] = str(call_log)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


def read_calls(call_log: Path) -> list[str]:
    """Read back every logged stage invocation, in call order."""
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


@pytest.fixture
def fake_plugin_root(tmp_path: Path) -> Path:
    return _make_fake_plugin_root(tmp_path)


@pytest.fixture
def call_log(tmp_path: Path) -> Path:
    return tmp_path / "calls.log"


# ==========================================================================
# Pipeline path.
# ==========================================================================


# --------------------------------------------------------------------------
# Bare invocation (no subcommand) — bash parity: runs the full pipeline
# immediately, verbose=0. NOT a usage screen.
# --------------------------------------------------------------------------


def test_bare_invocation_runs_full_pipeline_all_green(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx audit:" in proc.stdout
    assert "  lint:   ok" in proc.stdout
    assert "  doctor: ok" in proc.stdout
    assert "  status: ok" in proc.stdout

    # doctor is invoked TWICE (once silently for rc, once more unredirected
    # at the end); lint and status exactly once each.
    calls = read_calls(call_log)
    assert calls == [
        "cmd_lint.sh",
        "cmd_doctor.sh",
        "cmd_status.sh",
        "cmd_doctor.sh",
    ]


def test_bare_invocation_non_verbose_suppresses_lint_and_status_output(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:cmd_lint.sh" not in proc.stdout
    assert "stderr:cmd_lint.sh" not in proc.stderr
    assert "stdout:cmd_status.sh" not in proc.stdout
    assert "stderr:cmd_status.sh" not in proc.stderr
    assert "───" not in proc.stdout  # no "─── name ───" headers at all


def test_doctor_output_always_printed_once_regardless_of_verbose(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """doctor's FIRST (rc-capturing) call is always silent; its SECOND
    (final) call always inherits stdout/stderr — independent of
    --verbose. Its output appears exactly once, and never behind a
    "─── doctor ───" header (doctor never goes through run_stage)."""
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("stdout:cmd_doctor.sh") == 1
    assert proc.stderr.count("stderr:cmd_doctor.sh") == 1
    assert "─── doctor ───" not in proc.stdout

    # doctor's own output appears BEFORE the summary block.
    doctor_pos = proc.stdout.index("stdout:cmd_doctor.sh")
    summary_pos = proc.stdout.index("shctx audit:")
    assert doctor_pos < summary_pos


def test_verbose_streams_lint_and_status_output_with_headers_but_not_doctor(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── lint ───" in proc.stdout
    assert "─── status ───" in proc.stdout
    assert "─── doctor ───" not in proc.stdout
    assert "stdout:cmd_lint.sh" in proc.stdout
    assert "stderr:cmd_lint.sh" in proc.stderr
    assert "stdout:cmd_status.sh" in proc.stdout
    # doctor's output still appears exactly once (from its always-inherited
    # final call), not duplicated by --verbose.
    assert proc.stdout.count("stdout:cmd_doctor.sh") == 1


def test_verbose_short_flag_is_equivalent(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "-v"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── lint ───" in proc.stdout


def test_multiple_verbose_flags_are_idempotent(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "-v", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── lint ───" in proc.stdout


# --------------------------------------------------------------------------
# doctor's three-state summary (ok / warn / fail) vs. lint/status's
# two-state summary (ok / fail).
# --------------------------------------------------------------------------


def test_doctor_warn_only_exits_2_and_summarizes_warn(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log, rc={"FAKE_RC_DOCTOR": "2"})
    proc = run_cli(["audit"], env)

    assert proc.returncode == 2
    assert "  lint:   ok" in proc.stdout
    assert "  doctor: warn" in proc.stdout
    assert "  status: ok" in proc.stdout


def test_doctor_hard_fail_exits_1_and_summarizes_fail_with_rc(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = audit_env(fake_plugin_root, call_log, rc={"FAKE_RC_DOCTOR": "1"})
    proc = run_cli(["audit"], env)

    assert proc.returncode == 1
    assert "  doctor: fail (rc=1)" in proc.stdout


def test_doctor_arbitrary_nonzero_rc_summarizes_fail_with_that_rc(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """An rc other than 0/1/2 renders "fail (rc=N)" in the summary — but the
    aggregate exit is 0, matching cmd_audit.sh line 98 exactly: it forces exit 1
    only on `rc_doctor == 1` (not any non-zero), exit 2 only on `rc_doctor == 2`;
    every other doctor rc (7 here) falls through to `exit 0` despite the "fail"
    label. A bash quirk, reproduced faithfully."""
    env = audit_env(fake_plugin_root, call_log, rc={"FAKE_RC_DOCTOR": "7"})
    proc = run_cli(["audit"], env)

    assert proc.returncode == 0
    assert "  doctor: fail (rc=7)" in proc.stdout


def test_lint_failure_exits_1(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log, rc={"FAKE_RC_LINT": "5"})
    proc = run_cli(["audit"], env)

    assert proc.returncode == 1
    assert "  lint:   fail (rc=5)" in proc.stdout
    assert "  doctor: ok" in proc.stdout
    assert "  status: ok" in proc.stdout


def test_status_failure_exits_1(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log, rc={"FAKE_RC_STATUS": "3"})
    proc = run_cli(["audit"], env)

    assert proc.returncode == 1
    assert "  status: fail (rc=3)" in proc.stdout


def test_every_stage_runs_even_when_an_earlier_one_fails(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """Bash parity: each rc_* is captured independently — a failed early
    stage does NOT short-circuit later stages."""
    env = audit_env(fake_plugin_root, call_log, rc={"FAKE_RC_LINT": "1", "FAKE_RC_STATUS": "1"})
    proc = run_cli(["audit"], env)

    assert proc.returncode == 1
    calls = read_calls(call_log)
    assert calls == ["cmd_lint.sh", "cmd_doctor.sh", "cmd_status.sh", "cmd_doctor.sh"]


def test_lint_fail_and_doctor_warn_together_exit_1_not_2(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """The hard-fail branch (lint/status nonzero, or doctor==1) is checked
    BEFORE the doctor==2 warn branch — a lint failure wins even when
    doctor only warned."""
    env = audit_env(fake_plugin_root, call_log, rc={"FAKE_RC_LINT": "1", "FAKE_RC_DOCTOR": "2"})
    proc = run_cli(["audit"], env)

    assert proc.returncode == 1
    assert "  lint:   fail (rc=1)" in proc.stdout
    assert "  doctor: warn" in proc.stdout


# --------------------------------------------------------------------------
# -h / --help.
# --------------------------------------------------------------------------

_HELP_TEXT = (
    "shctx audit [--verbose]\n"
    "shctx audit insert --concern=<c> --severity=<s> --hypothesis=<h>\n"
    "                   [--falsification=<f>] [--confidence=<low|medium|high>]\n"
    "                   [--evidence=<json>] [--gh-issue=<n>] [--sprint=<branch>]\n"
    "                   < finding-body.md\n"
    "\n"
    "Read-only validation: lint → doctor → status.\n"
    "Exits 0 if all green, 1 if any FAIL, 2 if only WARNs (matches doctor).\n"
    "\n"
    "v5.1.7+: `insert` subverb writes a structured row into audit_findings."
)


def test_help_long_flag_prints_verbatim_bash_usage_and_exits_0(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "--help"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _HELP_TEXT
    assert read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _HELP_TEXT
    assert read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_verbose(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "--verbose", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _HELP_TEXT
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "--bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"
    assert read_calls(call_log) == []


def test_positional_token_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "bogus-subcommand"], env)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: bogus-subcommand"
    assert read_calls(call_log) == []


def test_insert_not_in_first_position_is_unknown_arg(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """Bash checks the LITERAL first token (``${1:-}" == "insert"``)
    BEFORE any flag parsing — "insert" appearing after --verbose is just
    another unrecognized token to the pipeline's flag loop."""
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "--verbose", "insert"], env)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: insert"
    assert read_calls(call_log) == []


def test_unknown_arg_short_circuits_before_later_tokens(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = audit_env(fake_plugin_root, call_log)
    proc = run_cli(["audit", "--bogus", "--verbose"], env)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# _scripts_dir() failure mode.
# --------------------------------------------------------------------------


def test_missing_bash_shctx_tooling_exits_1(tmp_path: Path) -> None:
    env = cli_env(tmp_path / "unused.db")
    empty_root = tmp_path / "no-plugin-here"
    empty_root.mkdir()
    env["CLAUDE_PLUGIN_ROOT"] = str(empty_root)

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "audit"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 1
    assert "ERROR: bash shctx tooling not found" in proc.stderr


# ==========================================================================
# `insert` subverb — real fixture DB, no fake scripts involved.
# ==========================================================================


@pytest.fixture
def audit_db(tmp_path: Path) -> tuple[Path, str]:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    return db_path, project_id


def run_insert(args: list[str], env: dict[str, str], *, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """Invoke ``shepherd audit insert ...`` with a stdin body.

    ``conftest.run_cli`` has no ``input=`` passthrough (no other ported
    command reads stdin yet), so this calls ``subprocess.run`` directly
    with the same ``${PY} -m shepherd_cli`` invocation shape.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "audit", "insert", *args],
        input=stdin,
        env=env,
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


def fetch_row(db_path: Path, row_id: int) -> dict[str, object]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM audit_findings WHERE id = ?", (row_id,)).fetchone()
        assert row is not None, f"no audit_findings row with id={row_id}"
        return dict(row)
    finally:
        conn.close()


def test_insert_happy_path_writes_row_and_prints_id(audit_db: tuple[Path, str]) -> None:
    db_path, project_id = audit_db
    env = cli_env(db_path)
    before = int(time.time())

    proc = run_insert(
        [
            "--concern=stale-cache",
            "--severity=high",
            "--hypothesis=the symbol index is behind HEAD",
        ],
        env,
        stdin="Observed 40 stale rows in index_symbols.\n",
    )

    assert proc.returncode == 0, proc.stderr
    row_id = int(proc.stdout.rstrip("\n"))

    row = fetch_row(db_path, row_id)
    assert row["project_id"] == project_id
    assert row["concern"] == "stale-cache"
    assert row["severity"] == "high"
    assert row["hypothesis"] == "the symbol index is behind HEAD"
    assert row["finding"] == "Observed 40 stale rows in index_symbols."
    assert row["sprint_branch"] is None
    assert row["falsification"] is None
    assert row["confidence"] is None
    assert row["evidence_refs"] is None
    assert row["gh_issue"] is None
    assert row["created_at"] % 1000 == 0  # epoch-milliseconds, whole-second-derived
    assert before * 1000 <= row["created_at"] <= (int(time.time()) + 5) * 1000


def test_insert_stdout_is_exactly_the_id_no_extra_output(audit_db: tuple[Path, str]) -> None:
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(
        ["--concern=c", "--severity=low", "--hypothesis=h"],
        env,
        stdin="finding body",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n").isdigit()
    assert proc.stdout.count("\n") == 1


def test_insert_all_optional_fields_populate_when_given(audit_db: tuple[Path, str]) -> None:
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(
        [
            "--concern=c",
            "--severity=medium",
            "--hypothesis=h",
            "--falsification=run the repro script",
            "--confidence=medium",
            "--evidence={\"refs\": [\"a.py:10\"]}",
            "--gh-issue=42",
            "--sprint=feature/foo",
        ],
        env,
        stdin="body",
    )
    assert proc.returncode == 0, proc.stderr
    row_id = int(proc.stdout.rstrip("\n"))
    row = fetch_row(db_path, row_id)
    assert row["falsification"] == "run the repro script"
    assert row["confidence"] == "medium"
    assert json.loads(row["evidence_refs"]) == {"refs": ["a.py:10"]}
    assert row["gh_issue"] == 42
    assert row["sprint_branch"] == "feature/foo"


def test_insert_empty_finding_body_is_allowed(audit_db: tuple[Path, str]) -> None:
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(["--concern=c", "--severity=info", "--hypothesis=h"], env, stdin="")
    assert proc.returncode == 0, proc.stderr
    row_id = int(proc.stdout.rstrip("\n"))
    assert fetch_row(db_path, row_id)["finding"] == ""


def test_insert_strips_all_trailing_newlines_from_stdin_not_interior_ones(
    audit_db: tuple[Path, str],
) -> None:
    """Bash parity: ``finding="$(cat)"`` strips EVERY trailing newline
    (however many) but leaves interior newlines and other trailing
    whitespace (e.g. a trailing space) untouched."""
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(
        ["--concern=c", "--severity=info", "--hypothesis=h"],
        env,
        stdin="line one\nline two \n\n\n",
    )
    assert proc.returncode == 0, proc.stderr
    row_id = int(proc.stdout.rstrip("\n"))
    assert fetch_row(db_path, row_id)["finding"] == "line one\nline two "


def test_insert_missing_required_flags_exits_2(audit_db: tuple[Path, str]) -> None:
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(["--concern=c", "--severity=low"], env, stdin="body")

    assert proc.returncode == 2
    assert proc.stderr.rstrip("\n") == "ERR: --concern, --severity, --hypothesis required"
    assert proc.stdout == ""


def test_insert_empty_string_flag_value_counts_as_missing(audit_db: tuple[Path, str]) -> None:
    """``--hypothesis=`` (empty value) is falsy in bash's ``[[ -n ... ]]``
    check, same as omitting the flag entirely."""
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(
        ["--concern=c", "--severity=low", "--hypothesis="], env, stdin="body"
    )
    assert proc.returncode == 2
    assert proc.stderr.rstrip("\n") == "ERR: --concern, --severity, --hypothesis required"


def test_insert_unknown_flag_exits_2(audit_db: tuple[Path, str]) -> None:
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(
        ["--concern=c", "--severity=low", "--hypothesis=h", "--bogus=x"], env, stdin="body"
    )
    assert proc.returncode == 2
    assert proc.stderr.rstrip("\n") == "unknown flag: --bogus=x"
    assert proc.stdout == ""


def test_insert_unknown_flag_short_circuits_before_required_check(
    audit_db: tuple[Path, str],
) -> None:
    """Bash parity: the flag loop runs to completion (or errors) BEFORE
    the required-fields check — an unknown flag always reports as
    ``unknown flag: ...`` (exit 2), never the "required" message, even
    when required flags are also missing."""
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(["--bogus=x"], env, stdin="body")
    assert proc.returncode == 2
    assert proc.stderr.rstrip("\n") == "unknown flag: --bogus=x"


def test_insert_invalid_evidence_json_is_silently_cleared_not_an_error(
    audit_db: tuple[Path, str],
) -> None:
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(
        [
            "--concern=c",
            "--severity=low",
            "--hypothesis=h",
            "--evidence=not-json{{{",
        ],
        env,
        stdin="body",
    )
    assert proc.returncode == 0, proc.stderr
    row_id = int(proc.stdout.rstrip("\n"))
    assert fetch_row(db_path, row_id)["evidence_refs"] is None


def test_insert_registry_db_not_found_exits_1(tmp_path: Path) -> None:
    missing_db = tmp_path / "does-not-exist.db"
    env = cli_env(missing_db)
    proc = run_insert(["--concern=c", "--severity=low", "--hypothesis=h"], env, stdin="body")

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == f"ERR: registry DB not found at {missing_db}"
    assert proc.stdout == ""


def test_insert_invalid_severity_violates_check_constraint_exits_1(
    audit_db: tuple[Path, str],
) -> None:
    db_path, _ = audit_db
    env = cli_env(db_path)
    proc = run_insert(
        ["--concern=c", "--severity=not-a-real-severity", "--hypothesis=h"], env, stdin="body"
    )
    assert proc.returncode == 1
    assert proc.stderr.startswith("ERROR: ")
    assert "CHECK constraint failed" in proc.stderr
    # No row was left behind by the failed insert.
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM audit_findings").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_insert_with_no_project_registered_fails_on_foreign_key_not_orphaned_row(
    tmp_path: Path,
) -> None:
    """Platform-level divergence from bash, documented in the module
    docstring: bash's raw ``sqlite3`` CLI runs with ``foreign_keys`` OFF
    by default and would silently insert an orphaned ``project_id=''``
    row; Tortoise's sqlite backend sets ``PRAGMA foreign_keys = ON`` for
    every connection (shared by every other ported write path), so this
    port's ``INSERT`` raises ``IntegrityError: FOREIGN KEY constraint
    failed`` — caught by the same handler as a bad ``--severity`` value —
    exit 1, no row written, when the ``projects`` table is empty."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)  # no insert_project() call
    env = cli_env(db_path)

    proc = run_insert(["--concern=c", "--severity=low", "--hypothesis=h"], env, stdin="body")

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: FOREIGN KEY constraint failed"
    assert proc.stdout == ""

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM audit_findings").fetchone()[0]
    finally:
        conn.close()
    assert count == 0
