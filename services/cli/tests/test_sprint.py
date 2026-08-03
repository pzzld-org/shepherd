"""Subprocess parity tests for ``shepherd sprint`` (open/wave/close pipelines).

Bash parity target: the retired ``cmd_sprint.sh``. Every test drives the
real CLI as a subprocess (``${PY} -m shepherd_cli sprint ...``), exactly
like ``test_deliverable.py`` — never by importing ``shepherd_cli`` into
the pytest process.

``sprint`` is an ORCHESTRATION command: every stage of every pipeline
runs a sibling native subcommand of this same CLI (``lock``, ``refresh``,
``lint``, ``status``, ``handoff``, ``worktree``, ``close-lane``) as a
child process of the invoking interpreter — the bash ``cmd_*.sh`` layer
is gone from the call path entirely. None of those real stages are
network-free or fast (``refresh --scope=github`` hits ``gh``/GitHub;
``worktree gc`` runs real ``git`` plumbing), so driving them for real
from a gate test would violate the "deterministic, local, free, <2s,
never flaky" gate-test contract (CLAUDE.md). Per that same contract's
latent-vs-deterministic split, this suite instead substitutes ONE tiny,
fully-deterministic stand-in stage CLI (see ``_FAKE_STAGE_CLI`` /
:func:`stage_cli`) via ``sprint``'s documented dependency-injection seam,
the ``SHEPHERD_SPRINT_STAGE_CMD`` environment variable (the successor to
the old trick of pointing ``CLAUDE_PLUGIN_ROOT`` at fake ``cmd_*.sh``
scripts). The stand-in logs every invocation to ``$CALL_LOG`` and exits
with a caller-controlled code (``FAKE_RC_*`` env vars), giving full, fast,
deterministic control over every stage's exit code and stdout/stderr.
That lets the tests below pin down ``shepherd sprint``'s OWN contract
exactly: which argv it invokes each stage with, in what order, in what
shape (``run_stage``'s verbose-vs-suppressed output handling), and how it
aggregates per-stage exit codes into its own final exit code and summary
text — orchestration concerns that belong to ``sprint`` itself, not to
any of the seven subcommands it dispatches.

The one piece of ``close`` that touches the database directly (finding
``lane_closures`` rows tied to the closing sprint branch) is exercised
against the REAL full schema (``build_full_schema_db``), seeded via raw
``sqlite3`` — schema-tolerant via ``PRAGMA table_info`` per the house
style (``conftest.insert_teammate``, ``test_deliverable.insert_deliverable``).
"""

from __future__ import annotations

import json
import shlex
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import PY, build_full_schema_db, clean_env_dict, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Fixture DB.
# --------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row (not read by ``sprint`` itself, but keeps
    the fixture DB shape consistent with the rest of the suite)."""
    return insert_project(db_path)


def insert_lane_closure(
    db_path: Path,
    *,
    id_: str,
    project_id: str,
    sprint_branch: str,
    lane_id: str,
    closed_at: int,
    status: str = "clean",
) -> None:
    """Insert one ``lane_closures`` row directly via sqlite3.

    Column-tolerant via ``PRAGMA table_info`` (house style — see
    ``conftest.insert_teammate``), even though ``lane_closures`` has never
    gained a column across migrations since ``0003_canonical_types_filter.sql``
    created it wholesale.

    Args:
        db_path: The fixture DB to write into.
        id_: The row's TEXT primary key (a UUIDv7 string in real usage;
            any unique string is fine for a fixture).
        project_id: FK target in ``projects.id``.
        sprint_branch: The ``sprint_branch`` column value.
        lane_id: The ``lane_id`` column value.
        closed_at: Epoch-seconds for ``closed_at`` — the schema declares
            this ``NOT NULL``, so unlike every other timestamp column in
            this test suite's helpers, there is no "leave it NULL" option
            here at all.
        status: One of ``clean``/``partial``/``failed`` (the column's
            CHECK constraint).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(lane_closures)")}
        fields: list[str] = ["id", "project_id", "sprint_branch", "lane_id", "closed_at", "resolved_issues", "status"]
        values: list[object] = [id_, project_id, sprint_branch, lane_id, closed_at, "[]", status]
        assert columns.issuperset(fields), f"lane_closures missing expected columns: {fields}"
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO lane_closures ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608 - fixed column allow-list above, no user input
            values,
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Fake stage CLI — one deterministic Python stand-in for every sibling
# subcommand a sprint pipeline dispatches (lock, refresh, lint, status,
# handoff, worktree, close-lane), wired in via the documented
# SHEPHERD_SPRINT_STAGE_CMD dependency-injection seam.
# --------------------------------------------------------------------------

_FAKE_STAGE_CLI = '''\
"""Deterministic stand-in stage CLI for shepherd sprint gate tests.

Invoked exactly like the real runner ([sys.executable, "-m",
"shepherd_cli"] replaced by [PY, this_file]): argv after the runner prefix
is the stage's own subcommand tokens, e.g. ["lock", "acquire",
"--mode=sprint"]. Appends that argv (space-joined) as one line to
$CALL_LOG, prints one marker line to stdout and one to stderr (so
run_stage's verbose-vs-suppressed handling is observable), and exits with
a caller-controlled FAKE_RC_* code — the same control surface the old
fake cmd_*.sh scripts offered, minus the bash.
"""
import os
import sys

args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\\n")

sub = args[0] if args else ""


def env_rc(*names):
    for name in names:
        if name is None:
            continue
        value = os.environ.get(name)
        if value:
            return int(value)
    return 0


if sub == "lock":
    action = args[1] if len(args) > 1 else ""
    marker = "lock:" + action
    if action == "acquire":
        rc = env_rc("FAKE_RC_LOCK_ACQUIRE", "FAKE_RC_LOCK")
    elif action == "release":
        rc = env_rc("FAKE_RC_LOCK_RELEASE", "FAKE_RC_LOCK")
    else:
        rc = env_rc("FAKE_RC_LOCK")
elif sub == "refresh":
    scope = ""
    for arg in args[1:]:
        if arg.startswith("--scope="):
            scope = arg[len("--scope="):]
    marker = "refresh:" + scope
    scoped = {
        "all": "FAKE_RC_REFRESH_ALL",
        "github": "FAKE_RC_REFRESH_GITHUB",
        "artifacts": "FAKE_RC_REFRESH_ARTIFACTS",
    }.get(scope)
    rc = env_rc(scoped, "FAKE_RC_REFRESH")
elif sub == "lint":
    marker = "lint"
    rc = env_rc("FAKE_RC_LINT")
elif sub == "status":
    marker = "status"
    rc = env_rc("FAKE_RC_STATUS")
elif sub == "handoff":
    marker = "handoff:" + (args[1] if len(args) > 1 else "")
    rc = env_rc("FAKE_RC_HANDOFF")
elif sub == "worktree":
    marker = "worktree:" + (args[1] if len(args) > 1 else "")
    rc = env_rc("FAKE_RC_WORKTREE")
elif sub == "close-lane":
    marker = "close-lane"
    rc = env_rc("FAKE_RC_CLOSE_LANE")
else:
    marker = sub or "?"
    rc = 0

print("stdout:" + marker)
print("stderr:" + marker, file=sys.stderr)
sys.exit(rc)
'''


@pytest.fixture
def stage_cli(tmp_path: Path) -> Path:
    """A throwaway deterministic stand-in stage CLI (see ``_FAKE_STAGE_CLI``).

    Plain Python, no executable bit needed — ``sprint_env`` wires it in as
    ``SHEPHERD_SPRINT_STAGE_CMD="${PY} <this file>"``, so every stage a
    pipeline dispatches runs this file instead of the real
    ``[sys.executable, "-m", "shepherd_cli"]`` subcommands.
    """
    path = tmp_path / "fake_stage_cli.py"
    path.write_text(_FAKE_STAGE_CLI)
    return path


def sprint_env(
    db_path: Path,
    stage_cli: Path,
    workdir: Path,
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd sprint`` test.

    Args:
        db_path: The fixture DB (SHCTX_DB).
        stage_cli: The stand-in stage CLI from :func:`stage_cli`, wired in
            via ``SHEPHERD_SPRINT_STAGE_CMD`` (``_stage_base_argv()``'s
            documented dependency-injection seam) so every pipeline stage
            runs the deterministic stand-in instead of the real,
            network/git-dependent native subcommands.
        workdir: An absolute directory ``SHEPHERD_WORKDIR`` points at —
            gives each test a private, empty-by-default ``project.json``
            location (``_read_project_id()``'s target).
        call_log: Path the stand-in appends one line to per invocation
            (``$CALL_LOG``) — read back to assert which stages actually
            ran, in what order, with what argv.
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_LOCK_ACQUIRE": "1"}``.

    Returns:
        A full subprocess environment ready for :func:`conftest.run_cli`.
    """
    env = cli_env(db_path)
    env["SHEPHERD_SPRINT_STAGE_CMD"] = " ".join(shlex.quote(part) for part in (PY, str(stage_cli)))
    env["SHEPHERD_WORKDIR"] = str(workdir)
    env["CALL_LOG"] = str(call_log)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """A private, empty SHEPHERD_WORKDIR for one test (no project.json yet)."""
    path = tmp_path / "workdir"
    path.mkdir()
    return path


@pytest.fixture
def call_log(tmp_path: Path) -> Path:
    """Path the fake sibling scripts append their invocations to."""
    return tmp_path / "calls.log"


def read_calls(call_log: Path) -> list[str]:
    """Read back every logged stage invocation, in call order.

    Each line is the stage's full subcommand argv, space-joined by the
    stand-in — e.g. ``"lock acquire --mode=sprint"`` or ``"lint"``
    (right-stripped defensively; the stand-in's ``" ".join(args)`` format
    emits no trailing whitespace of its own).
    """
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------
# Sub-app usage/exit-code parity (no-subcommand, help, unknown subcommand).
# --------------------------------------------------------------------------


def test_no_subcommand_shows_usage_and_exits_0(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["sprint"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sprint <open|wave|close>" in proc.stdout
    assert "open <branch>" in proc.stdout
    assert "wave <wave-id>" in proc.stdout
    assert "close <branch>" in proc.stdout


def test_help_subcommand_shows_usage_and_exits_0(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["sprint", "help"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sprint <open|wave|close>" in proc.stdout


def test_unknown_subcommand_exits_nonzero(db_path: Path, project_id: str) -> None:
    """Known parity gap (see sprint.py's module docstring): bash exits 1
    with "ERROR: unknown subcommand: $sub" on stderr; Typer/Click's own
    "No such command" error fires instead, with exit code 2 — matching
    the same accepted divergence as ``deliverable``/``signal``'s own
    ``test_unknown_subcommand_exits_2``."""
    env = cli_env(db_path)
    proc = run_cli(["sprint", "bogus"], env)

    assert proc.returncode == 2


# --------------------------------------------------------------------------
# open
# --------------------------------------------------------------------------


@pytest.mark.parametrize("args", [["sprint", "open"], ["sprint", "open", ""]])
def test_open_missing_or_empty_branch_exits_1_with_usage(
    db_path: Path, project_id: str, args: list[str]
) -> None:
    env = cli_env(db_path)
    proc = run_cli(args, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: usage: shctx sprint open <branch>" in proc.stderr


def test_open_all_stages_succeed_prints_summary_and_exits_0(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "open", "feature-x"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sprint open feature-x: elapsed=" in proc.stdout
    assert "  lock:    acquired" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  status:  ok" in proc.stdout

    calls = read_calls(call_log)
    assert len(calls) == 4
    assert calls[0] == "lock acquire --mode=sprint"
    assert calls[1] == "refresh --scope=all"
    assert calls[2] == "lint"
    assert calls[3] == "status"


def test_open_stage_failure_still_runs_every_later_stage_and_exits_1(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    """Bash parity: each rc_* is captured independently — a failed early
    stage does NOT short-circuit later stages (no ``set -e``-style abort
    inside the ``open`` branch)."""
    env = sprint_env(
        db_path, stage_cli, workdir, call_log,
        rc={"FAKE_RC_LOCK_ACQUIRE": "1", "FAKE_RC_STATUS": "3"},
    )
    proc = run_cli(["sprint", "open", "feature-x"], env)

    assert proc.returncode == 1
    assert "  lock:    fail (rc=1)" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  status:  fail (rc=3)" in proc.stdout

    # Every stage still ran despite the first one failing.
    assert len(read_calls(call_log)) == 4


def test_open_non_verbose_suppresses_stage_stdout_and_stderr(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "open", "feature-x"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:lock" not in proc.stdout
    assert "stderr:lock" not in proc.stderr
    assert "───" not in proc.stdout  # no "─── name ───" headers


def test_open_verbose_streams_stage_output_with_headers(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "open", "feature-x", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── lock acquire ───" in proc.stdout
    assert "─── refresh --all ───" in proc.stdout
    assert "stdout:lock:acquire" in proc.stdout
    assert "stderr:lock:acquire" in proc.stderr
    # The final bash-parity summary still prints after the streamed stages.
    assert "shctx sprint open feature-x: elapsed=" in proc.stdout


def test_open_verbose_short_flag_is_equivalent(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "open", "feature-x", "-v"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:lock:acquire" in proc.stdout


def test_open_flag_before_positional_still_resolves_branch(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    """Intentional divergence from bash (documented in sprint.py): bash's
    naive ``branch="${1:-}"`` would treat a leading ``--verbose`` AS the
    branch name if it preceded the positional. Typer parses options
    independent of position, so this resolves ``branch`` correctly either
    way — a strict improvement, not a parity break."""
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "open", "--verbose", "feature-x"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sprint open feature-x: elapsed=" in proc.stdout


# --------------------------------------------------------------------------
# wave
# --------------------------------------------------------------------------


@pytest.mark.parametrize("args", [["sprint", "wave"], ["sprint", "wave", ""]])
def test_wave_missing_or_empty_wave_id_exits_1_with_usage(
    db_path: Path, project_id: str, args: list[str]
) -> None:
    env = cli_env(db_path)
    proc = run_cli(args, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: usage: shctx sprint wave <wave-id>" in proc.stderr


def test_wave_default_scope_runs_github_then_artifacts(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "wave", "w1"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sprint wave w1: scope=github,artifacts elapsed=" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "refresh --scope=github",
        "refresh --scope=artifacts",
        "lint",
    ]


def test_wave_all_flag_forwards_scope_all_as_single_stage(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "wave", "w1", "--all"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sprint wave w1: scope=all elapsed=" in proc.stdout

    calls = read_calls(call_log)
    assert calls == ["refresh --scope=all", "lint"]


def test_wave_partial_refresh_failure_formats_g_and_a_rcs(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(
        db_path, stage_cli, workdir, call_log,
        rc={"FAKE_RC_REFRESH_GITHUB": "1", "FAKE_RC_REFRESH_ARTIFACTS": "0"},
    )
    proc = run_cli(["sprint", "wave", "w1"], env)

    assert proc.returncode == 1
    assert "  refresh: fail (g=1 a=0)" in proc.stdout
    # lint still runs even though refresh partially failed.
    assert "  lint:    ok" in proc.stdout
    assert len(read_calls(call_log)) == 3


def test_wave_lint_failure_exits_1(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, fake_plugin_root, workdir, call_log, rc={"FAKE_RC_LINT": "5"})
    proc = run_cli(["sprint", "wave", "w1"], env)

    assert proc.returncode == 1
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    fail (rc=5)" in proc.stdout


# --------------------------------------------------------------------------
# close
# --------------------------------------------------------------------------


@pytest.mark.parametrize("args", [["sprint", "close"], ["sprint", "close", ""]])
def test_close_missing_or_empty_branch_exits_1_with_usage(
    db_path: Path, project_id: str, args: list[str]
) -> None:
    env = cli_env(db_path)
    proc = run_cli(args, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: usage: shctx sprint close <branch>" in proc.stderr


def test_close_all_stages_succeed_prints_summary_and_exits_0(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "close", "feature-x"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sprint close feature-x: elapsed=" in proc.stdout
    assert "  lanes:   closed=0 failed=0" in proc.stdout
    assert "  handoff: ok" in proc.stdout
    assert "  gc:      ok" in proc.stdout
    assert "  lock:    released" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "handoff create --branch=feature-x",
        "worktree gc",
        "lock release",
    ]


def test_close_stage_failure_still_runs_every_later_stage_and_exits_1(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(
        db_path, stage_cli, workdir, call_log,
        rc={"FAKE_RC_HANDOFF": "1", "FAKE_RC_LOCK_RELEASE": "2"},
    )
    proc = run_cli(["sprint", "close", "feature-x"], env)

    assert proc.returncode == 1
    assert "  handoff: fail (rc=1)" in proc.stdout
    assert "  gc:      ok" in proc.stdout
    assert "  lock:    fail (rc=2)" in proc.stdout
    assert len(read_calls(call_log)) == 3


def test_close_no_project_json_skips_lane_step_without_error(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    """Bash parity: ``shctx_project_id`` errors when project.json is
    missing; the ``2>/dev/null || echo ""`` wrapper in cmd_sprint.sh's
    close branch swallows that, leaving project_id empty and the whole
    lane-closing step skipped (``[[ -n "$project_id" ]]`` guard)."""
    assert not (workdir / "project.json").exists()
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "close", "feature-x"], env)

    assert proc.returncode == 0, proc.stderr
    assert "  lanes:   closed=0 failed=0" in proc.stdout


def test_close_lane_closures_table_missing_skips_lane_step_without_error(
    tmp_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    """Bash parity: cmd_sprint.sh's sqlite_master introspection guards the
    lane-closing step against a DB that predates migration 0003 — here
    simulated with a DB file that does not exist yet at all (zero tables,
    since ensure_migrated's self-heal only runs against an EXISTING file
    per shepherd_cli.db's own contract)."""
    (workdir / "project.json").write_text('{"id": "proj-fresh"}')
    fresh_db = tmp_path / "not-yet-created.db"
    assert not fresh_db.exists()

    env = sprint_env(fresh_db, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "close", "feature-x"], env)

    assert proc.returncode == 0, proc.stderr
    assert "  lanes:   closed=0 failed=0" in proc.stdout


def test_close_seeded_lane_row_never_counted_due_to_not_null_constraint(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    """The schema declares lane_closures.closed_at NOT NULL, and
    cmd_close-lane.sh (the table's sole writer) always sets it to
    shctx_now() on insert/upsert — so cmd_sprint.sh's own
    ``WHERE closed_at IS NULL`` query can never match a real row. This
    port issues that exact query anyway (bash parity means mirroring the
    query, not fixing the dead branch it guards) and must therefore report
    zero closed/failed lanes even with a matching-branch row present."""
    (workdir / "project.json").write_text(f'{{"id": "{project_id}"}}')
    insert_lane_closure(
        db_path, id_="lc-1", project_id=project_id, sprint_branch="feature-x",
        lane_id="lane-1", closed_at=int(time.time()),
    )

    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "close", "feature-x"], env)

    assert proc.returncode == 0, proc.stderr
    assert "  lanes:   closed=0 failed=0" in proc.stdout
    # The close-lane subcommand was never invoked (no CALL_LOG line for it).
    assert all("close-lane" not in call for call in read_calls(call_log))


def test_close_verbose_streams_handoff_gc_lock_output(
    db_path: Path, project_id: str, stage_cli: Path, workdir: Path, call_log: Path
) -> None:
    env = sprint_env(db_path, stage_cli, workdir, call_log)
    proc = run_cli(["sprint", "close", "feature-x", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── handoff ───" in proc.stdout
    assert "─── worktree gc ───" in proc.stdout
    assert "─── lock release ───" in proc.stdout
    assert "stdout:handoff:create" in proc.stdout
    assert "stderr:handoff:create" in proc.stderr


# --------------------------------------------------------------------------
# _scripts_dir() failure mode.
# --------------------------------------------------------------------------


def test_missing_bash_shctx_tooling_exits_1(db_path: Path, project_id: str, tmp_path: Path) -> None:
    """When the bash shctx tooling cannot be located at all (no
    CLAUDE_PLUGIN_ROOT match and no skills/context/scripts/shctx found by
    walking up from the repo root), every pipeline is unusable — exit 1
    with a clear stderr message rather than a stack trace."""
    env = cli_env(db_path)
    # Point CLAUDE_PLUGIN_ROOT somewhere with no skills/context/scripts/shctx,
    # and run from an empty cwd outside any git repo so the walk-up fallback
    # in find_bash_shctx() also fails to find the real tree.
    empty_root = tmp_path / "no-plugin-here"
    empty_root.mkdir()
    env["CLAUDE_PLUGIN_ROOT"] = str(empty_root)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "workdir")

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "sprint", "open", "feature-x"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 1
    assert "ERROR: bash shctx tooling not found" in proc.stderr
