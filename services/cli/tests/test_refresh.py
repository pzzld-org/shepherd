"""Subprocess parity tests for ``shepherd refresh`` (cache-rebuild pipeline).

Bash parity target: ``skills/context/scripts/cmd_refresh.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli refresh ...``),
exactly like ``test_sync.py``/``test_audit.py``.

Two independent concerns are under test here, exactly mirroring the module
under test's own split:

1. **The four SUBPROCESS-ORCHESTRATION zones** (``symbols``/``shapes``/
   ``github``/``artifacts``) — driven with a throwaway "fake plugin root"
   (see :func:`_make_fake_plugin_root`, copied from ``test_sync.py``'s own
   helper of the same shape) containing tiny, fully-scripted stand-ins for
   ``refresh-symbols.sh``/``refresh-github.sh``/``refresh-artifacts.sh``/
   ``cmd_dups.sh`` — each logs its invocation to ``$CALL_LOG`` and exits
   with a caller-controlled code (via ``FAKE_RC_*`` env vars). This lets
   the tests pin down ``shepherd refresh``'s OWN contract (which argv it
   invokes, in what order, with what output-suppression shape, and how it
   maps a stage's exit code to its own) without ever touching a real
   ``cargo``/``gh`` toolchain.

2. **The NATIVE ``telemetry`` zone** — driven against a REAL full-schema
   fixture DB (``build_full_schema_db`` + ``insert_project``, exactly like
   ``test_query.py``) with a real ``<workdir>/logs/events-*.jsonl`` file on
   disk, asserting on both the printed row count AND the actual
   ``index_cache_usage`` rows written (raw ``sqlite3`` readback, PRAGMA
   table_info tolerant per the port contract).

Like ``test_query.py``, ``shctx refresh``'s ``telemetry`` zone resolves its
project id from a ``<workdir>/project.json`` FILE (``_lib.sh``'s
``shctx_project_id``) — a DIFFERENT location than the fixture DB whenever
``SHCTX_DB`` points at a specific file. Every telemetry test therefore sets
``SHEPHERD_WORKDIR`` to an isolated tmp directory via :func:`_telemetry_env`.
"""

from __future__ import annotations

import json
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest
from conftest import PY, build_full_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Fake sibling scripts — deterministic stand-ins for refresh-symbols.sh,
# refresh-github.sh, refresh-artifacts.sh, cmd_dups.sh.
# --------------------------------------------------------------------------

_STUB_PREAMBLE = '#!/usr/bin/env bash\necho "{name} $*" >> "$CALL_LOG"\n'

_FAKE_SCRIPTS: dict[str, str] = {
    "refresh-symbols.sh": _STUB_PREAMBLE.format(name="refresh-symbols.sh")
    + (
        'echo "stdout:refresh-symbols.sh:$*"\n'
        'echo "stderr:refresh-symbols.sh:$*" >&2\n'
        'exit "${FAKE_RC_SYMBOLS:-0}"\n'
    ),
    "refresh-github.sh": _STUB_PREAMBLE.format(name="refresh-github.sh")
    + (
        'echo "stdout:refresh-github.sh:$*"\n'
        'echo "stderr:refresh-github.sh:$*" >&2\n'
        'exit "${FAKE_RC_GITHUB:-0}"\n'
    ),
    "refresh-artifacts.sh": _STUB_PREAMBLE.format(name="refresh-artifacts.sh")
    + (
        'echo "stdout:refresh-artifacts.sh:$*"\n'
        'echo "stderr:refresh-artifacts.sh:$*" >&2\n'
        'exit "${FAKE_RC_ARTIFACTS:-0}"\n'
    ),
    "cmd_dups.sh": _STUB_PREAMBLE.format(name="cmd_dups.sh")
    + (
        'echo "stdout:cmd_dups.sh:$*"\n'
        'echo "stderr:cmd_dups.sh:$*" >&2\n'
        'exit "${FAKE_RC_SHAPES:-0}"\n'
    ),
}


def _make_fake_plugin_root(tmp_path: Path) -> Path:
    """Build a throwaway ``CLAUDE_PLUGIN_ROOT`` tree with fully-scripted sibling commands.

    Layout mirrors the real plugin just enough for
    :func:`shepherd_cli.resolution.find_bash_shctx` to resolve it:
    ``skills/context/scripts/{shctx, refresh-symbols.sh, refresh-github.sh,
    refresh-artifacts.sh, cmd_dups.sh}``. ``shctx`` itself only needs to
    exist as a file (its dirname is all ``shepherd refresh`` ever uses via
    ``_find_scripts_dir()``); the four stand-ins are real, executable,
    deterministic bash scripts (see ``_FAKE_SCRIPTS``).

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


def _pipeline_env(
    fake_plugin_root: Path,
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
    workdir: Path | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a script-dependent ``shepherd refresh`` test.

    Args:
        fake_plugin_root: The fake plugin root from
            :func:`_make_fake_plugin_root`, wired in as
            ``CLAUDE_PLUGIN_ROOT`` so ``find_bash_shctx()`` resolves to the
            fake sibling scripts instead of the real, toolchain-dependent
            ones.
        call_log: Path the fake sibling scripts append one line to per
            invocation (``$CALL_LOG``).
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_SYMBOLS": "1"}``.
        workdir: When given, sets ``SHEPHERD_WORKDIR`` too (needed for
            ``--scope=all``, whose telemetry stage reads
            ``<workdir>/project.json`` / ``<workdir>/logs``) — a workdir
            with no ``project.json`` written drives telemetry's own
            "project not initialized" failure branch, which is fine for
            these pipeline-shaped tests (they only assert on the four
            script-dependent stages' own behavior).

    Returns:
        A full subprocess environment ready for :func:`conftest.run_cli`.
    """
    env = cli_env(fake_plugin_root / "unused.db")
    env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
    env["CALL_LOG"] = str(call_log)
    if workdir is not None:
        env["SHEPHERD_WORKDIR"] = str(workdir)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


def _read_calls(call_log: Path) -> list[str]:
    """Read back every logged stage invocation, in call order."""
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


@pytest.fixture
def fake_plugin_root(tmp_path: Path) -> Path:
    return _make_fake_plugin_root(tmp_path)


@pytest.fixture
def call_log(tmp_path: Path) -> Path:
    """Path the fake sibling scripts append their invocations to."""
    return tmp_path / "calls.log"


# --------------------------------------------------------------------------
# -h / --help.
# --------------------------------------------------------------------------


def test_help_long_flag_prints_usage_and_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--help"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == (
        "shctx refresh [--scope=symbols|shapes|github|artifacts|telemetry|all] [--all]\n"
        "\n"
        "  --scope=NAME  refresh a single zone\n"
        "                  symbols   — index public symbols from the workspace\n"
        "                  shapes    — index public struct/enum FIELD SHAPES for `dups` (v6.1.8 #157)\n"
        "                  github    — issues / PRs / releases / milestones via gh\n"
        "                  artifacts — markdown specs / plans / handoffs / journal\n"
        "                  telemetry — cache-usage events from <ns>/logs/events-*.jsonl (v5.1.3+)\n"
        "                  all       — every zone above (default)\n"
        "  --all         alias for --scope=all (canonical universal flag, v5.0.4)"
    )
    assert _read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh [--scope=symbols|shapes|github|artifacts|telemetry|all]" in proc.stdout
    assert _read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_other_flags(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope=github", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh [--scope=" in proc.stdout
    assert _read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg / unknown --scope — two DIFFERENT error paths.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"
    assert _read_calls(call_log) == []


def test_verbose_flag_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    """Unlike ``cmd_sync.sh``, ``cmd_refresh.sh`` has no ``--verbose``/``-v`` flag."""
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "-v"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: -v" in proc.stderr
    assert _read_calls(call_log) == []


def test_bare_scope_without_equals_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --scope" in proc.stderr
    assert _read_calls(call_log) == []


def test_positional_token_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "symbols"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: symbols" in proc.stderr
    assert _read_calls(call_log) == []


def test_unknown_scope_value_exits_1_at_dispatch_not_parse(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """``--scope=bogus`` parses fine (any string matches ``--scope=*``); it
    only fails later, at dispatch — a textually DIFFERENT error than an
    unrecognized ARG token."""
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope=bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown --scope: bogus"
    assert _read_calls(call_log) == []


# --------------------------------------------------------------------------
# Single-scope: symbols / github / artifacts — runs ONLY that stage,
# output fully inherited (no suppression), exit code propagated verbatim.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scope", "script"),
    [
        ("symbols", "refresh-symbols.sh"),
        ("github", "refresh-github.sh"),
        ("artifacts", "refresh-artifacts.sh"),
    ],
)
def test_single_scope_runs_only_that_stage(
    fake_plugin_root: Path, call_log: Path, scope: str, script: str
) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", f"--scope={scope}"], env)

    assert proc.returncode == 0, proc.stderr
    assert _read_calls(call_log) == [script]
    assert f"stdout:{script}:" in proc.stdout
    assert f"stderr:{script}:" in proc.stderr


@pytest.mark.parametrize(
    ("scope", "rc_var"),
    [
        ("symbols", "FAKE_RC_SYMBOLS"),
        ("github", "FAKE_RC_GITHUB"),
        ("artifacts", "FAKE_RC_ARTIFACTS"),
    ],
)
def test_single_scope_propagates_nonzero_exit_code(
    fake_plugin_root: Path, call_log: Path, scope: str, rc_var: str
) -> None:
    env = _pipeline_env(fake_plugin_root, call_log, rc={rc_var: "7"})
    proc = run_cli(["refresh", f"--scope={scope}"], env)

    assert proc.returncode == 7


def test_all_flag_is_alias_for_scope_all_before_symbols_dispatch(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """``--all --scope=symbols`` — the LAST token wins (plain reassignment)."""
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--all", "--scope=symbols"], env)

    assert proc.returncode == 0, proc.stderr
    assert _read_calls(call_log) == ["refresh-symbols.sh"]


def test_scope_symbols_then_all_resolves_to_all(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope=symbols", "--all"], env)

    assert proc.returncode == 0, proc.stderr
    calls = _read_calls(call_log)
    assert "refresh-symbols.sh" in calls
    assert "refresh-github.sh" in calls
    assert "refresh-artifacts.sh" in calls


# --------------------------------------------------------------------------
# Single-scope: shapes — bash's refresh_shapes() helper (extra "ok" line
# semantics).
# --------------------------------------------------------------------------


def test_scope_shapes_success_prints_ok_line(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope=shapes"], env)

    assert proc.returncode == 0, proc.stderr
    assert _read_calls(call_log) == ["cmd_dups.sh scan --update --quiet"]
    assert "shctx refresh shapes: ok" in proc.stdout


def test_scope_shapes_failure_suppresses_ok_line_and_propagates_rc(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = _pipeline_env(fake_plugin_root, call_log, rc={"FAKE_RC_SHAPES": "5"})
    proc = run_cli(["refresh", "--scope=shapes"], env)

    assert proc.returncode == 5
    assert "shctx refresh shapes: ok" not in proc.stdout
    assert _read_calls(call_log) == ["cmd_dups.sh scan --update --quiet"]


# --------------------------------------------------------------------------
# _find_scripts_dir() failure mode — single scope hard-fails; --scope=all
# gracefully degrades and still exits 0.
# --------------------------------------------------------------------------


def test_missing_bash_shctx_tooling_single_scope_exits_1(tmp_path: Path) -> None:
    """``find_bash_shctx()`` falls back to walking up from the repo root when
    ``CLAUDE_PLUGIN_ROOT`` doesn't contain it — which would find THIS repo's
    own real ``skills/context/scripts/shctx`` if the subprocess ran with its
    cwd anywhere inside this checkout (``conftest.run_cli`` always uses
    ``cwd=CLI_ROOT``, which IS inside this checkout). So — exactly like
    ``test_sync.py``'s identically-named test — this one bypasses
    ``run_cli()`` and runs the subprocess directly with ``cwd=tmp_path``
    (outside any git repo), so both the ``CLAUDE_PLUGIN_ROOT`` candidate AND
    the walk-up fallback genuinely fail to find any ``shctx``."""
    env = cli_env(tmp_path / "unused.db")
    empty_root = tmp_path / "no-plugin-here"
    empty_root.mkdir()
    env["CLAUDE_PLUGIN_ROOT"] = str(empty_root)

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "refresh", "--scope=symbols"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 1
    assert "ERROR: bash shctx tooling not found" in proc.stderr


def test_missing_bash_shctx_tooling_all_scope_degrades_gracefully_exits_0(
    tmp_path: Path,
) -> None:
    """See :func:`test_missing_bash_shctx_tooling_single_scope_exits_1`'s
    docstring for why this bypasses ``run_cli()`` too."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    empty_root = tmp_path / "no-plugin-here"
    empty_root.mkdir()

    env = cli_env(tmp_path / "unused.db")
    env["CLAUDE_PLUGIN_ROOT"] = str(empty_root)
    env["SHEPHERD_WORKDIR"] = str(workdir)  # no project.json -> telemetry also "fails"

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "refresh"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0, proc.stderr
    for label in ("symbols", "shapes", "github", "artifacts", "telemetry"):
        assert f"shctx: {label} refresh failed (continuing)" in proc.stderr


# --------------------------------------------------------------------------
# --scope=all: fixed order, every stage always runs, exit code ALWAYS 0.
# --------------------------------------------------------------------------


def test_bare_invocation_defaults_to_scope_all(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    # Isolated, empty workdir (no project.json) -> telemetry's own
    # "project not initialized" failure branch -- deterministic and never
    # touches this repo's real .shepherd/ namespace.
    workdir = tmp_path / "wd"
    workdir.mkdir()
    env = _pipeline_env(fake_plugin_root, call_log, workdir=workdir)
    proc = run_cli(["refresh"], env)

    assert proc.returncode == 0, proc.stderr
    assert _read_calls(call_log) == [
        "refresh-symbols.sh",
        "cmd_dups.sh scan --update --quiet",
        "refresh-github.sh",
        "refresh-artifacts.sh",
    ]
    assert "shctx refresh shapes: ok" in proc.stdout
    # telemetry ran too, failed (no project.json), and was caught by the
    # "|| echo ... failed (continuing)" guard -- the overall exit code is
    # still 0.
    assert "shctx: telemetry refresh failed (continuing)" in proc.stderr


def test_scope_all_continues_after_every_stage_fails_and_exits_0(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    workdir.mkdir()  # no project.json -> telemetry "fails" too
    env = _pipeline_env(
        fake_plugin_root,
        call_log,
        rc={
            "FAKE_RC_SYMBOLS": "1",
            "FAKE_RC_SHAPES": "1",
            "FAKE_RC_GITHUB": "1",
            "FAKE_RC_ARTIFACTS": "1",
        },
        workdir=workdir,
    )
    proc = run_cli(["refresh", "--scope=all"], env)

    assert proc.returncode == 0, proc.stderr
    # Every stage still ran despite each one failing.
    assert len(_read_calls(call_log)) == 4
    assert "shctx: symbols refresh failed (continuing)" in proc.stderr
    assert "shctx: shapes refresh failed (continuing)" in proc.stderr
    assert "shctx: github refresh failed (continuing)" in proc.stderr
    assert "shctx: artifacts refresh failed (continuing)" in proc.stderr
    assert "shctx: telemetry refresh failed (continuing)" in proc.stderr
    assert "shctx refresh shapes: ok" not in proc.stdout


def test_scope_all_runs_stages_in_fixed_order_even_with_mixed_results(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    workdir.mkdir()
    env = _pipeline_env(
        fake_plugin_root, call_log, rc={"FAKE_RC_GITHUB": "3"}, workdir=workdir
    )
    proc = run_cli(["refresh", "--scope=all"], env)

    assert proc.returncode == 0, proc.stderr
    assert _read_calls(call_log) == [
        "refresh-symbols.sh",
        "cmd_dups.sh scan --update --quiet",
        "refresh-github.sh",
        "refresh-artifacts.sh",
    ]
    assert "shctx: github refresh failed (continuing)" in proc.stderr
    assert "shctx: symbols refresh failed (continuing)" not in proc.stderr
    assert "shctx: artifacts refresh failed (continuing)" not in proc.stderr


# --------------------------------------------------------------------------
# telemetry — native zone, real DB + real events-*.jsonl fixtures.
# --------------------------------------------------------------------------


def _telemetry_env(
    db_path: Path,
    workdir: Path,
    *,
    project_id: str = "proj-a",
    write_project_json: bool = True,
) -> dict[str, str]:
    """The environment for driving ``shepherd refresh --scope=telemetry``.

    Args:
        db_path: The sqlite file (``SHCTX_DB`` via :func:`cli_env`) —
            independent of ``workdir``, exactly like ``test_query.py``'s
            ``query_env``.
        workdir: An isolated tmp directory (``SHEPHERD_WORKDIR``) —
            ``project.json`` and ``logs/events-*.jsonl`` both live here.
        project_id: The id written into ``project.json``'s ``"id"`` field.
        write_project_json: When False, no ``project.json`` is written
            (drives the "not initialized" error path).

    Returns:
        A full subprocess environment.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if write_project_json:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


@pytest.fixture
def telemetry_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with one registered project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    return db_path


def _read_cache_usage_rows(db_path: Path) -> list[dict[str, object]]:
    """Read back every ``index_cache_usage`` row, PRAGMA table_info tolerant."""
    conn = sqlite3.connect(str(db_path))
    try:
        columns = [info[1] for info in conn.execute("PRAGMA table_info(index_cache_usage)")]
        rows = conn.execute(f"SELECT {', '.join(columns)} FROM index_cache_usage ORDER BY id").fetchall()  # noqa: S608
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def test_telemetry_missing_project_json_exits_1(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir, write_project_json=False)

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 1
    pjson = workdir / "project.json"
    assert proc.stderr.rstrip("\n") == f"ERROR: {pjson} missing — run 'shctx init' first"
    assert proc.stdout == ""


def test_telemetry_no_log_dir_skips_and_exits_0(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"shctx refresh telemetry: no log dir at {workdir}/logs (skipping)"
    assert _read_cache_usage_rows(telemetry_db) == []


def test_telemetry_inserts_cache_usage_events(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "cache_usage",
                        "ts": "2026-07-16T12:00:00Z",
                        "session_id": "sess-1",
                        "role": "engineer",
                        "agent_id": "agent-1",
                        "sprint": "main",
                        "turns": 3,
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 10,
                        "ephemeral_5m_input_tokens": 10,
                        "ephemeral_1h_input_tokens": 0,
                        "hit_rate": 0.9,
                        "parse_error": None,
                    }
                ),
                json.dumps(
                    {
                        "event_type": "cache_usage",
                        "ts": 1752667200,
                        "session_id": "sess-2",
                        "role": "critic",
                        "agent_id": "agent-2",
                    }
                ),
                # Non-cache_usage event -> skipped.
                json.dumps({"event_type": "other", "ts": 1752667300}),
                # Malformed JSON line -> skipped.
                "not json at all",
                # Blank line -> skipped.
                "",
            ]
        )
        + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh telemetry: 2 new row(s)"

    rows = _read_cache_usage_rows(telemetry_db)
    assert len(rows) == 2
    by_session = {row["session_id"]: row for row in rows}

    row1 = by_session["sess-1"]
    assert row1["project_id"] == "proj-a"
    assert row1["ts"] == 1784203200  # 2026-07-16T12:00:00Z -> epoch seconds
    assert row1["role"] == "engineer"
    assert row1["agent_id"] == "agent-1"
    assert row1["sprint"] == "main"
    assert row1["turns"] == 3
    assert row1["input_tokens"] == 100
    assert row1["cache_read_input_tokens"] == 900
    assert row1["hit_rate"] == 0.9

    row2 = by_session["sess-2"]
    assert row2["project_id"] == "proj-a"
    assert row2["ts"] == 1752667200  # already-numeric ts passed straight through
    assert row2["role"] == "critic"  # present, not defaulted
    assert row2["turns"] is None


def test_telemetry_role_defaults_to_unknown_when_absent(
    telemetry_db: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752667200, "session_id": "sess-x"}) + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    rows = _read_cache_usage_rows(telemetry_db)
    assert len(rows) == 1
    assert rows[0]["role"] == "unknown"


def test_telemetry_is_idempotent_via_unique_constraint(
    telemetry_db: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        json.dumps(
            {
                "event_type": "cache_usage",
                "ts": 1752667200,
                "session_id": "sess-dup",
                "agent_id": "agent-dup",
            }
        )
        + "\n"
    )

    first = run_cli(["refresh", "--scope=telemetry"], env)
    assert first.returncode == 0, first.stderr
    assert first.stdout.rstrip("\n") == "shctx refresh telemetry: 1 new row(s)"

    second = run_cli(["refresh", "--scope=telemetry"], env)
    assert second.returncode == 0, second.stderr
    assert second.stdout.rstrip("\n") == "shctx refresh telemetry: 0 new row(s)"

    assert len(_read_cache_usage_rows(telemetry_db)) == 1


def test_telemetry_events_directory_globs_multiple_files_sorted(
    telemetry_db: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-15.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752580800, "session_id": "sess-a"}) + "\n"
    )
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752667200, "session_id": "sess-b"}) + "\n"
    )
    # A non-matching filename must be ignored entirely.
    (logs_dir / "other.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752667200, "session_id": "sess-ignored"}) + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh telemetry: 2 new row(s)"
    session_ids = {row["session_id"] for row in _read_cache_usage_rows(telemetry_db)}
    assert session_ids == {"sess-a", "sess-b"}


def test_telemetry_unparseable_ts_value_is_skipped(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event_type": "cache_usage", "ts": "not-a-timestamp", "session_id": "bad-ts"}),
                json.dumps({"event_type": "cache_usage", "ts": None, "session_id": "null-ts"}),
                json.dumps({"event_type": "cache_usage", "session_id": "missing-ts"}),
            ]
        )
        + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh telemetry: 0 new row(s)"
    assert _read_cache_usage_rows(telemetry_db) == []
