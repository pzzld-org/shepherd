"""Subprocess parity tests for ``shepherd audit`` (lint -> doctor -> status pipeline + ``insert``).

Bash parity target: ``skills/context/scripts/cmd_audit.sh`` (retired).
Every test drives the real CLI as a subprocess (``${PY} -m shepherd_cli
audit ...``), exactly like ``test_sync.py`` — never by importing
``shepherd_cli`` into the pytest process.

Three independent halves, tested separately:

1. **The pipeline** (bare ``shepherd audit`` / ``shepherd audit
   --verbose``) re-invokes three ported sibling subcommands (``lint``,
   ``doctor``, ``status``) as child processes of the same interpreter
   (``[sys.executable, "-m", "shepherd_cli", "<stage>"]``). Driving the
   REAL sibling stages from a gate test would violate the "deterministic,
   local, free, <2s, never flaky" gate-test contract (CLAUDE.md) —
   ``doctor`` in particular resolves its namespace/project.json checks
   against the AMBIENT repo state (not ``SHCTX_DB``-scoped), so it is
   neither hermetic nor fast. Exactly like ``test_sync.py``, this suite
   builds a throwaway FAKE ``shepherd_cli`` package (:func:`fake_cli_root`)
   and runs the CLI with that directory as the subprocess cwd: ``python
   -m`` puts the cwd FIRST on ``sys.path`` (ahead of ``PYTHONPATH``), so
   both the parent invocation and every stage re-invocation resolve the
   fake package. The fake's ``__main__`` handles the three STAGE
   subcommands itself — logging each invocation to ``$CALL_LOG``, printing
   deterministic stdout/stderr markers, and exiting with a
   caller-controlled code (via ``FAKE_RC_*`` env vars) — and DELEGATES
   every other subcommand (``audit``, the command under test) to the real
   package by stripping itself off ``sys.path``.
2. **``insert``** DOES touch a real fixture database (built the same way
   every other DB-backed suite in this package builds one —
   ``conftest.build_full_schema_db`` + ``conftest.insert_project``) and is
   tested against it directly, with stdin fed via a raw ``subprocess.run``
   call (``conftest.run_cli`` has no ``input=`` passthrough, since no
   other ported command reads stdin yet). No fake package is involved:
   ``insert`` never runs a stage.
3. **The pipeline's #250 schema-currency pre-check** — added alongside
   the ``status``/``style`` half of the same fix (see
   ``shepherd_cli/commands/audit.py``'s own module docstring's
   WRITE-SAFETY section and ``tests/test_db_readonly.py`` for the full
   library-level suite) — DOES read one real fixture database directly
   with a raw ``sqlite3.connect()`` (never Tortoise) before any stage
   would otherwise spawn. No fake package involved here either: a behind
   schema must short-circuit BEFORE any stage runs, so there is nothing
   for a fake stage to fake.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import CLI_ROOT, PY, SCHEMA_BASE_SQL, build_full_schema_db, cli_env, insert_project

# --------------------------------------------------------------------------
# Fake shepherd_cli package — deterministic stand-ins for the lint /
# doctor / status stage re-invocations (pipeline path only; `insert` never
# touches these), delegating every other subcommand to the real package.
# --------------------------------------------------------------------------

_FAKE_MAIN = '''\
"""Test stand-in for ``python -m shepherd_cli`` (see test_audit.py docstring).

Stage subcommands (lint/doctor/status) are faked: log argv to $CALL_LOG,
print deterministic markers, exit with $FAKE_RC_<STAGE>. Everything else
(the ``audit`` command under test) delegates to the REAL package.
"""
import os
import sys

_STAGES = {"lint", "doctor", "status"}


def _fake_stage(cmd, args):
    log_path = os.environ.get("CALL_LOG", "")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write((cmd + " " + " ".join(args)).rstrip() + "\\n")
    suffix = ":" + " ".join(args) if args else ""
    print(f"stdout:{cmd}{suffix}")
    print(f"stderr:{cmd}{suffix}", file=sys.stderr)
    raise SystemExit(int(os.environ.get("FAKE_RC_" + cmd.upper(), "0")))


_cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if _cmd in _STAGES:
    _fake_stage(_cmd, sys.argv[2:])

# Delegate to the real shepherd_cli: drop this fake package's directory off
# sys.path, forget the fake modules, and re-import the real entry point
# (resolved via PYTHONPATH, which conftest points at services/cli).
_here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _here]
for _name in [n for n in list(sys.modules) if n == "shepherd_cli" or n.startswith("shepherd_cli.")]:
    del sys.modules[_name]

from shepherd_cli.__main__ import main  # noqa: E402

main()
'''


def _make_fake_cli_root(tmp_path: Path) -> Path:
    """Build a throwaway directory whose ``shepherd_cli`` package fakes the stages.

    The returned directory is used as the subprocess CWD: ``python -m``
    resolves packages from the cwd before ``PYTHONPATH``, so both the
    parent ``audit`` invocation and every ``[sys.executable, "-m",
    "shepherd_cli", "<stage>"]`` stage re-invocation import this fake
    package first. The fake handles stage subcommands deterministically
    (see ``_FAKE_MAIN``) and delegates ``audit`` itself to the real
    package.

    Args:
        tmp_path: The pytest-provided per-test temp directory.

    Returns:
        The directory containing the fake ``shepherd_cli`` package (the
        cwd to run the CLI from).
    """
    fake_root = tmp_path / "fake-cli-root"
    pkg_dir = fake_root / "shepherd_cli"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "__main__.py").write_text(_FAKE_MAIN)
    return fake_root


def audit_env(
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd audit`` pipeline test.

    Args:
        call_log: Path the fake stage stand-ins append one line to per
            invocation (``$CALL_LOG``).
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_DOCTOR": "2"}``.

    Returns:
        A full subprocess environment. Deliberately does NOT need a real
        ``SHCTX_DB`` — the pipeline path never opens a database connection
        (a throwaway path is set anyway purely so ``cli_env`` has
        something to point at; it is never actually opened).
    """
    env = cli_env(call_log.parent / "unused.db")
    env["CALL_LOG"] = str(call_log)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


def run_audit(
    args: list[str],
    env: dict[str, str],
    fake_cli_root: Path,
    *,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli audit ...`` with the fake package as cwd.

    ``conftest.run_cli`` pins ``cwd=CLI_ROOT`` (the real package), so the
    pipeline half uses its own runner: the fake-cli-root cwd is exactly
    what makes the stage re-invocations resolve the fake stand-ins (see
    the module docstring).
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "audit", *args],
        env=env,
        cwd=str(fake_cli_root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def read_calls(call_log: Path) -> list[str]:
    """Read back every logged stage invocation, in call order."""
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


@pytest.fixture
def fake_cli_root(tmp_path: Path) -> Path:
    return _make_fake_cli_root(tmp_path)


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


def test_bare_invocation_runs_full_pipeline_all_green(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log)
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx audit:" in proc.stdout
    assert "  lint:   ok" in proc.stdout
    assert "  doctor: ok" in proc.stdout
    assert "  status: ok" in proc.stdout

    # doctor is invoked TWICE (once silently for rc, once more unredirected
    # at the end); lint and status exactly once each.
    calls = read_calls(call_log)
    assert calls == [
        "lint",
        "doctor",
        "status",
        "doctor",
    ]


def test_bare_invocation_non_verbose_suppresses_lint_and_status_output(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = audit_env(call_log)
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:lint" not in proc.stdout
    assert "stderr:lint" not in proc.stderr
    assert "stdout:status" not in proc.stdout
    assert "stderr:status" not in proc.stderr
    assert "───" not in proc.stdout  # no "─── name ───" headers at all


def test_doctor_output_always_printed_once_regardless_of_verbose(
    fake_cli_root: Path, call_log: Path
) -> None:
    """doctor's FIRST (rc-capturing) call is always silent; its SECOND
    (final) call always inherits stdout/stderr — independent of
    --verbose. Its output appears exactly once, and never behind a
    "─── doctor ───" header (doctor never goes through run_stage)."""
    env = audit_env(call_log)
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("stdout:doctor") == 1
    assert proc.stderr.count("stderr:doctor") == 1
    assert "─── doctor ───" not in proc.stdout

    # doctor's own output appears BEFORE the summary block.
    doctor_pos = proc.stdout.index("stdout:doctor")
    summary_pos = proc.stdout.index("shctx audit:")
    assert doctor_pos < summary_pos


def test_verbose_streams_lint_and_status_output_with_headers_but_not_doctor(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = audit_env(call_log)
    proc = run_audit(["--verbose"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── lint ───" in proc.stdout
    assert "─── status ───" in proc.stdout
    assert "─── doctor ───" not in proc.stdout
    assert "stdout:lint" in proc.stdout
    assert "stderr:lint" in proc.stderr
    assert "stdout:status" in proc.stdout
    # doctor's output still appears exactly once (from its always-inherited
    # final call), not duplicated by --verbose.
    assert proc.stdout.count("stdout:doctor") == 1


def test_verbose_short_flag_is_equivalent(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log)
    proc = run_audit(["-v"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── lint ───" in proc.stdout


def test_multiple_verbose_flags_are_idempotent(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log)
    proc = run_audit(["-v", "--verbose"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── lint ───" in proc.stdout


# --------------------------------------------------------------------------
# doctor's three-state summary (ok / warn / fail) vs. lint/status's
# two-state summary (ok / fail).
# --------------------------------------------------------------------------


def test_doctor_warn_only_exits_2_and_summarizes_warn(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log, rc={"FAKE_RC_DOCTOR": "2"})
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 2
    assert "  lint:   ok" in proc.stdout
    assert "  doctor: warn" in proc.stdout
    assert "  status: ok" in proc.stdout


def test_doctor_hard_fail_exits_1_and_summarizes_fail_with_rc(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = audit_env(call_log, rc={"FAKE_RC_DOCTOR": "1"})
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  doctor: fail (rc=1)" in proc.stdout


def test_doctor_arbitrary_nonzero_rc_summarizes_fail_with_that_rc(
    fake_cli_root: Path, call_log: Path
) -> None:
    """An rc other than 0/1/2 renders "fail (rc=N)" in the summary — but the
    aggregate exit is 0, matching cmd_audit.sh line 98 exactly: it forces exit 1
    only on `rc_doctor == 1` (not any non-zero), exit 2 only on `rc_doctor == 2`;
    every other doctor rc (7 here) falls through to `exit 0` despite the "fail"
    label. A bash quirk, reproduced faithfully."""
    env = audit_env(call_log, rc={"FAKE_RC_DOCTOR": "7"})
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 0
    assert "  doctor: fail (rc=7)" in proc.stdout


def test_lint_failure_exits_1(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log, rc={"FAKE_RC_LINT": "5"})
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  lint:   fail (rc=5)" in proc.stdout
    assert "  doctor: ok" in proc.stdout
    assert "  status: ok" in proc.stdout


def test_status_failure_exits_1(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log, rc={"FAKE_RC_STATUS": "3"})
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  status: fail (rc=3)" in proc.stdout


def test_every_stage_runs_even_when_an_earlier_one_fails(
    fake_cli_root: Path, call_log: Path
) -> None:
    """Bash parity: each rc_* is captured independently — a failed early
    stage does NOT short-circuit later stages."""
    env = audit_env(call_log, rc={"FAKE_RC_LINT": "1", "FAKE_RC_STATUS": "1"})
    proc = run_audit([], env, fake_cli_root)

    assert proc.returncode == 1
    calls = read_calls(call_log)
    assert calls == ["lint", "doctor", "status", "doctor"]


def test_lint_fail_and_doctor_warn_together_exit_1_not_2(
    fake_cli_root: Path, call_log: Path
) -> None:
    """The hard-fail branch (lint/status nonzero, or doctor==1) is checked
    BEFORE the doctor==2 warn branch — a lint failure wins even when
    doctor only warned."""
    env = audit_env(call_log, rc={"FAKE_RC_LINT": "1", "FAKE_RC_DOCTOR": "2"})
    proc = run_audit([], env, fake_cli_root)

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
    fake_cli_root: Path, call_log: Path
) -> None:
    env = audit_env(call_log)
    proc = run_audit(["--help"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _HELP_TEXT
    assert read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log)
    proc = run_audit(["-h"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _HELP_TEXT
    assert read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_verbose(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = audit_env(call_log)
    proc = run_audit(["--verbose", "-h"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _HELP_TEXT
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log)
    proc = run_audit(["--bogus"], env, fake_cli_root)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"
    assert read_calls(call_log) == []


def test_positional_token_is_unknown_arg(fake_cli_root: Path, call_log: Path) -> None:
    env = audit_env(call_log)
    proc = run_audit(["bogus-subcommand"], env, fake_cli_root)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: bogus-subcommand"
    assert read_calls(call_log) == []


def test_insert_not_in_first_position_is_unknown_arg(
    fake_cli_root: Path, call_log: Path
) -> None:
    """Bash checks the LITERAL first token (``${1:-}" == "insert"``)
    BEFORE any flag parsing — "insert" appearing after --verbose is just
    another unrecognized token to the pipeline's flag loop."""
    env = audit_env(call_log)
    proc = run_audit(["--verbose", "insert"], env, fake_cli_root)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: insert"
    assert read_calls(call_log) == []


def test_unknown_arg_short_circuits_before_later_tokens(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = audit_env(call_log)
    proc = run_audit(["--bogus", "--verbose"], env, fake_cli_root)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# _run_stage() launch-failure mode.
# --------------------------------------------------------------------------

_RUN_STAGE_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.audit import _run_stage\n"
    "print(_run_stage('probe', [sys.argv[1]], False))\n"
)


def test_unlaunchable_stage_counts_as_rc_127(tmp_path: Path) -> None:
    """A stage that cannot be launched at all (OSError from process
    creation — the moral equivalent of bash's missing/unexecutable
    ``cmd_*.sh``) maps to rc 127, the shell's own command-not-found code,
    instead of crashing the pipeline. Driven via a ``-c`` snippet in a
    fresh subprocess (the test_panes.py private-helper pattern)."""
    env = cli_env(tmp_path / "unused.db")
    proc = subprocess.run(
        [PY, "-c", _RUN_STAGE_SNIPPET, str(tmp_path / "no-such-interpreter")],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "127"


# ==========================================================================
# `insert` subverb — real fixture DB, no fake package involved.
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


# ==========================================================================
# #250 schema-currency pre-check — a REAL fixture DB (no fake package: the
# check must fire BEFORE any stage would otherwise spawn, so there is
# nothing for a fake stage to intercept). See tests/test_db_readonly.py
# for the full library-level lifespan(migrate=False)/schema_is_current()
# suite this pre-check is built on.
# ==========================================================================


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bare_audit_refuses_on_behind_schema_before_any_stage(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_BASE_SQL.read_text())  # ONLY 0001_init.sql — no migrations applied
        conn.commit()
    finally:
        conn.close()
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _sha256(db_path)

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "audit"],
        env=env,
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == "schema is behind the shipped migrations; run: shepherd migrate"
    assert _sha256(db_path) == before_hash


def test_audit_on_current_schema_db_is_unaffected_by_the_precheck(tmp_path: Path) -> None:
    """Pins that a healthy, fully-migrated DB never trips the new #250
    pre-check — the pipeline still runs (and, against a real ``lint``/
    ``doctor``/``status``, may fail for unrelated reasons in this ambient
    dev checkout, so this only asserts the schema-behind refusal text is
    absent, not a specific exit code)."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "audit"],
        env=env,
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert "schema is behind the shipped migrations" not in proc.stderr
