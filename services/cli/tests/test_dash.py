"""Subprocess regression tests for ``shepherd dash`` — native port of ``cmd_dash.sh``.

Bash parity target: the retired ``skills/context/scripts/cmd_dash.sh``
(v6.1.5 #13). Every test drives the real CLI as a subprocess (``${PY} -m
shepherd_cli dash``), exactly like ``test_status.py`` and
``test_report.py`` — never by importing ``shepherd_cli`` into the pytest
process — and seeds every table via raw ``sqlite3`` (schema-tolerant via
``PRAGMA table_info``, mirroring ``conftest.insert_teammate``/
``test_report.py``'s local helpers).

This suite originally double-ran every scenario through the legacy
``cmd_dash.sh`` and asserted byte-for-byte stdout parity. That bash layer
is retired (and its ``GRAPH`` delegation target, ``cmd_graph.sh``, with
it — ``dash`` now renders that section by calling the native
:mod:`shepherd_cli.commands.graph` ``status`` implementation in-process),
so the regression gates here are DIRECT expected-output assertions: the
exact section lines, orderings, truncations, and degrade branches the
bash-parity runs pinned down while both implementations coexisted. The
one nondeterministic token — the header's live ``HH:MM:SS`` wall clock —
is simply never asserted on.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import (
    REPO_ROOT,
    build_full_schema_db,
    clean_env_dict,
    insert_project,
    run_cli,
)


def _current_branch() -> str:
    """The git branch this test process's checkout is currently on.

    ``shepherd dash``'s ``_current_branch()`` resolves this via ``git
    rev-parse --abbrev-ref HEAD`` from the invoking process's cwd — since
    ``run_cli`` runs with ``cwd=CLI_ROOT`` (inside this same repo
    checkout), it resolves to the SAME real branch name this helper reads
    directly, letting FOCUS/GRAPH tests seed rows and state files that
    will actually match.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _dash_env(db_path: Path, workdir: Path) -> dict[str, str]:
    """Environment for ``shepherd dash``, isolated to ``workdir``.

    Mirrors ``test_status.py``'s ``_status_env``: sets ``SHCTX_DB`` (the
    CLI reads/writes the exact fixture DB) AND ``SHEPHERD_WORKDIR`` (so
    the lock file, ``project.json``, and ``graph/state.json`` lookups —
    all independent of ``SHCTX_DB`` — resolve inside ``workdir``, never
    this real repo's own ``.shepherd``/``.artifacts``).
    ``CLAUDE_PLUGIN_ROOT`` still points at the repo root so
    ``find_migrations_dir()`` (the ``db.lifespan``/self-heal path)
    resolves against the real ``skills/context/schema`` tree.

    Args:
        db_path: The fixture sqlite file.
        workdir: The throwaway directory ``shepherd.lock``/
            ``project.json``/``graph/`` are read from; need not exist yet.

    Returns:
        A stripped-then-rebuilt environment safe for ``run_cli``.
    """
    env = clean_env_dict()
    env["SHCTX_DB"] = str(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env


def _insert_row(db_path: Path, table: str, **columns: object) -> None:
    """Insert one row into ``table``, schema-tolerant via ``PRAGMA table_info``.

    Silently drops any keyword whose column is absent from the live
    schema (mirrors ``conftest.insert_teammate``'s tolerance pattern) so
    this single helper works across every table this suite seeds without
    needing a bespoke per-table variant.

    Args:
        db_path: The fixture DB to write into.
        table: The table name (from a fixed set of call sites below —
            never user input).
        **columns: Column name -> value pairs for one row.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        available = {info[1] for info in conn.execute(f"PRAGMA table_info({table})")}
        cols = [c for c in columns if c in available]
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",  # noqa: S608 - fixed table/column names from hardcoded call sites, no user input
            [columns[c] for c in cols],
        )
        conn.commit()
    finally:
        conn.close()


def _write_lock_file(workdir: Path) -> None:
    """Write a minimal ``shepherd.lock`` file (only ``held`` state matters here)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "shepherd.lock").write_text(
        json.dumps({"holder_session_id": "sess-dash", "mode": "autorun", "acquired_at": 1, "pid": 1, "children": []})
    )


def _write_project_json(workdir: Path, project_id: str | None) -> None:
    """Write ``<workdir>/project.json`` with the given ``id`` (or a JSON ``null``)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "project.json").write_text(json.dumps({"id": project_id}))


def _write_graph_state(workdir: Path, sprint: str, nodes: dict[str, str], *, run: str | None = None) -> None:
    """Write a ``graph/state.json`` in the shape ``graph status`` reads.

    Args:
        workdir: The dashboard's resolved work directory.
        sprint: The ``state["sprint"]`` value ``graph status`` echoes.
        nodes: ``{node_id: state}`` — ``state`` one of ``ready``,
            ``in_flight``, ``pending``, ``done``, ``skipped``.
        run: When given, write the run-scoped shim location
            (``<workdir>/runs/<run>/graph/state.json``) instead of the
            legacy ``<workdir>/graph/state.json``.
    """
    graph_dir = (workdir / "runs" / run / "graph") if run else (workdir / "graph")
    graph_dir.mkdir(parents=True, exist_ok=True)
    state = {"sprint": sprint, "nodes": {nid: {"state": s} for nid, s in nodes.items()}}
    (graph_dir / "state.json").write_text(json.dumps(state))


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row; every dash-section table's FK points into this."""
    return insert_project(db_path)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """A fresh, empty work directory (lock/project.json/graph/ all absent to start)."""
    return tmp_path / "work"


def _now_s() -> int:
    return int(time.time())


# --------------------------------------------------------------------------
# Missing-DB branch: bash-parity exit 0 (NOT 1 — unlike every other ported
# command's missing-DB branch), header + one degraded-state line only.
# --------------------------------------------------------------------------
def test_missing_db_exits_0_with_degraded_message(tmp_path: Path) -> None:
    db_path_ = tmp_path / "shepherd.db"  # never created
    workdir_ = tmp_path / "work"
    env = _dash_env(db_path_, workdir_)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("═══ SHEPHERD DASH ═══  ")
    assert lines[1] == "  (no registry DB — run 'shctx init'; dashboard limited to git state)"


# --------------------------------------------------------------------------
# Empty DB (no seeded rows, no project.json, no lock, no graph state) —
# every section's "none"/"free"/"never" branch at once.
# --------------------------------------------------------------------------
def test_empty_schema_db_renders_every_degraded_branch(db_path: Path, workdir: Path) -> None:
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    assert "SPRINT      schema=v" in stdout
    assert "lock=free" in stdout
    assert "FOCUS" not in stdout
    assert "GRAPH       (no stage-graph state — solo / pre-extract)" in stdout
    assert "TEAMMATES   none live" in stdout
    assert "SIGNALS     none pending" in stdout
    assert "ESCALATION  none open" in stdout
    assert "LOOPS       none active" in stdout
    # No project.json -> apid is empty -> ADAPT/EVAL are omitted ENTIRELY,
    # not just their "no history" sub-branch.
    assert "ADAPT" not in stdout
    assert "EVAL" not in stdout
    assert "STALE       issues=-  prs=-" in stdout


# --------------------------------------------------------------------------
# SPRINT / lock state.
# --------------------------------------------------------------------------
def test_lock_held_renders_held(db_path: Path, workdir: Path) -> None:
    _write_lock_file(workdir)
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "lock=HELD" in proc.stdout


# --------------------------------------------------------------------------
# FOCUS.
# --------------------------------------------------------------------------
def test_focus_line_present_truncated_and_ellipsized(db_path: Path, workdir: Path) -> None:
    branch = _current_branch()
    now_s = _now_s()
    long_obj = "line one\nline two\r\nline three " + ("x" * 80)
    _insert_row(db_path, "focus", sprint=branch, lane="", objective=long_obj, updated_at=now_s)
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    focus_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("FOCUS")]
    assert len(focus_lines) == 1
    rendered = focus_lines[0][len("FOCUS       ") :]
    assert rendered.endswith("…")
    body = rendered[:-1]
    assert len(body) == 76
    assert "\n" not in body and "\r" not in body


def test_focus_line_absent_when_no_matching_sprint(db_path: Path, workdir: Path) -> None:
    _insert_row(db_path, "focus", sprint="some-other-branch", lane="", objective="unrelated", updated_at=_now_s())
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "FOCUS" not in proc.stdout


def test_focus_line_absent_when_objective_null(db_path: Path, workdir: Path) -> None:
    branch = _current_branch()
    _insert_row(db_path, "focus", sprint=branch, lane="", objective=None, updated_at=_now_s())
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "FOCUS" not in proc.stdout


# --------------------------------------------------------------------------
# GRAPH (rendered in-process by the native graph-status implementation).
# --------------------------------------------------------------------------
def test_graph_section_no_state_file(db_path: Path, workdir: Path) -> None:
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "GRAPH       (no stage-graph state — solo / pre-extract)" in proc.stdout


def test_graph_section_renders_native_graph_status(db_path: Path, workdir: Path) -> None:
    branch = _current_branch()
    _write_graph_state(workdir, branch, {"n1": "done", "n2": "ready", "n3": "in_flight"})
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    assert "GRAPH\n" in stdout
    assert f"  Graph status — sprint: {branch}" in stdout
    assert "    completion: 1/3 (33%)" in stdout
    assert "    Ready now:  n2" in stdout
    assert "    In flight:  n3" in stdout


def test_graph_section_honors_run_scoped_state(db_path: Path, workdir: Path) -> None:
    """The run-shim deviation shared with ``shepherd graph``: with a run
    identifiable (SHEPHERD_RUN) and a run-scoped state.json present, the
    GRAPH gate and the renderer BOTH resolve to
    ``<workdir>/runs/<run>/graph/`` — no legacy ``<workdir>/graph/``
    state file needed, and no gate/renderer disagreement possible."""
    branch = _current_branch()
    _write_graph_state(workdir, branch, {"n1": "ready"}, run="r1")
    assert not (workdir / "graph" / "state.json").exists()
    env = _dash_env(db_path, workdir)
    env["SHEPHERD_RUN"] = "r1"

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "GRAPH\n" in proc.stdout
    assert f"  Graph status — sprint: {branch}" in proc.stdout
    assert "(no stage-graph state" not in proc.stdout


def test_graph_section_error_degradation_on_corrupt_state(db_path: Path, workdir: Path) -> None:
    """An unparseable state.json — the in-process analogue of a crashed
    ``graph status`` child — degrades to the bash pipeline's
    ``"  (graph status error)"`` line, and the dashboard keeps rendering
    every later section instead of aborting (exit stays 0)."""
    graph_dir = workdir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "state.json").write_text("{not json")
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    assert "GRAPH\n" in stdout
    assert "  (graph status error)" in stdout
    # Later sections still render — the failure stayed contained.
    assert "TEAMMATES" in stdout
    assert "STALE" in stdout


# --------------------------------------------------------------------------
# TEAMMATES.
# --------------------------------------------------------------------------
def test_teammates_roster_excludes_crashed_and_retired_orders_by_name(
    db_path: Path, project_id: str, workdir: Path
) -> None:
    now_ms = int(time.time() * 1000)
    rows = [
        ("tm-z", "zed", "engineer", "active", now_ms - 5_000),
        ("tm-a", "alice", "critic", "idle", now_ms - 65_000),
        ("tm-crashed", "ghost", "engineer", "crashed", now_ms),
        ("tm-retired", "relic", "engineer", "retired", now_ms),
    ]
    for tid, name, agent_type, status, last_seen in rows:
        _insert_row(
            db_path,
            "teammates",
            id=tid,
            project_id=project_id,
            team_name="team-a",
            teammate_name=name,
            agent_type=agent_type,
            session_id="sess-1",
            spawned_at=now_ms,
            last_seen_at=last_seen,
            status=status,
        )
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    assert "TEAMMATES   2 live" in stdout
    assert "ghost" not in stdout
    assert "relic" not in stdout
    alice_idx = stdout.index("alice:critic:idle:")
    zed_idx = stdout.index("zed:engineer:active:")
    assert alice_idx < zed_idx  # ORDER BY teammate_name -> alice before zed


def test_teammates_none_live(db_path: Path, workdir: Path) -> None:
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "TEAMMATES   none live" in proc.stdout


# --------------------------------------------------------------------------
# SIGNALS.
# --------------------------------------------------------------------------
def test_signals_pending_grouped_by_recipient(db_path: Path, project_id: str, workdir: Path) -> None:
    now_s = _now_s()
    for recipient in ("spawn-a", "spawn-a", "spawn-a", "spawn-b"):
        _insert_row(
            db_path,
            "session_signals",
            project_id=project_id,
            sender="root",
            recipient=recipient,
            kind="seed-ready",
            payload="{}",
            sent_at=now_s,
        )
    # An already-consumed signal must not be counted.
    _insert_row(
        db_path,
        "session_signals",
        project_id=project_id,
        sender="root",
        recipient="spawn-c",
        kind="seed-ready",
        payload="{}",
        sent_at=now_s,
        consumed_at=now_s,
    )
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    assert "SIGNALS     pending" in stdout
    assert "spawn-a: 3" in stdout
    assert "spawn-b: 1" in stdout
    assert "spawn-c" not in stdout
    # ORDER BY COUNT(*) DESC with distinct counts (3 > 1) is fully
    # deterministic — no tie for SQLite's planner to break arbitrarily —
    # so the higher-count recipient must render first.
    assert stdout.index("spawn-a: 3") < stdout.index("spawn-b: 1")


def test_signals_none_pending(db_path: Path, workdir: Path) -> None:
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "SIGNALS     none pending" in proc.stdout


# --------------------------------------------------------------------------
# ESCALATION.
# --------------------------------------------------------------------------
def test_escalation_open_count_and_oldest_age(db_path: Path, project_id: str, workdir: Path) -> None:
    now_s = _now_s()
    _insert_row(db_path, "escalations", project_id=project_id, role="engineer", question="q-old", raised_at=now_s - 400)
    _insert_row(db_path, "escalations", project_id=project_id, role="engineer", question="q-new", raised_at=now_s - 30)
    # Resolved escalations are excluded from v_escalations_open entirely.
    _insert_row(
        db_path,
        "escalations",
        project_id=project_id,
        role="engineer",
        question="q-resolved",
        raised_at=now_s - 9_000,
        resolved_at=now_s - 1,
    )
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "ESCALATION  2 open (oldest 6m)" in proc.stdout


def test_escalation_none_open(db_path: Path, workdir: Path) -> None:
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "ESCALATION  none open" in proc.stdout


# --------------------------------------------------------------------------
# LOOPS.
# --------------------------------------------------------------------------
def test_loops_active_ordered_by_created_at(db_path: Path, project_id: str, workdir: Path) -> None:
    now_s = _now_s()
    _insert_row(
        db_path, "loops", id="loop-2", project_id=project_id, kind="convergence",
        max_iterations=3, status="active", created_at=now_s - 10,
    )
    _insert_row(
        db_path, "loops", id="loop-1", project_id=project_id, kind="focus",
        max_iterations=5, status="active", created_at=now_s - 100,
    )
    # A converged (non-active) loop must not appear.
    _insert_row(
        db_path, "loops", id="loop-3", project_id=project_id, kind="watch",
        max_iterations=2, status="converged", created_at=now_s - 5,
    )
    _insert_row(db_path, "loop_iterations", loop_id="loop-1", iteration=1, new_findings=1, recorded_at=now_s - 90)
    _insert_row(db_path, "loop_iterations", loop_id="loop-1", iteration=2, new_findings=0, recorded_at=now_s - 50)
    _insert_row(db_path, "loop_iterations", loop_id="loop-2", iteration=1, new_findings=1, recorded_at=now_s - 8)
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    assert "LOOPS       active" in stdout
    assert "focus 2/5 (find=1)" in stdout
    assert "convergence 1/3 (find=1)" in stdout
    assert "watch" not in stdout
    loop1_idx = stdout.index("focus 2/5")
    loop2_idx = stdout.index("convergence 1/3")
    assert loop1_idx < loop2_idx  # ORDER BY created_at ASC -> loop-1 (older) first


def test_loops_none_active(db_path: Path, workdir: Path) -> None:
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "LOOPS       none active" in proc.stdout


# --------------------------------------------------------------------------
# ADAPT (and its project.json-presence gate).
# --------------------------------------------------------------------------
def test_adapt_omitted_without_project_json(db_path: Path, project_id: str, workdir: Path) -> None:
    _insert_row(
        db_path, "mem_entries", id="mem-1", project_id=project_id, kind="prior",
        title="prior: irrelevant", body="b", created_at=_now_s(), updated_at=_now_s(),
    )
    env = _dash_env(db_path, workdir)  # no project.json written

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "ADAPT" not in proc.stdout
    assert "EVAL" not in proc.stdout


def test_adapt_with_metrics_priors_and_latest_lesson(db_path: Path, project_id: str, workdir: Path) -> None:
    now_s = _now_s()
    _write_project_json(workdir, project_id)
    _insert_row(
        db_path, "sprint_metrics", project_id=project_id, sprint_branch="s1",
        lane_count=4, wall_minutes=30.0, created_at=now_s,
    )
    _insert_row(
        db_path, "sprint_metrics", project_id=project_id, sprint_branch="s2",
        lane_count=2, wall_minutes=60.0, created_at=now_s,
    )
    _insert_row(
        db_path, "mem_entries", id="mem-old", project_id=project_id, kind="prior",
        title="prior: old lesson", body="b", created_at=now_s - 100, updated_at=now_s - 100,
    )
    _insert_row(
        db_path, "mem_entries", id="mem-new", project_id=project_id, kind="prior",
        title="prior: newest lesson learned", body="b", created_at=now_s, updated_at=now_s,
    )
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    # avg(lane_count) = 3, avg(wall_minutes) = 45 — exact, no rounding ambiguity.
    assert "ADAPT       2 sprint(s)  lanes~3  wall~45m  priors=2" in stdout
    assert "              latest: newest lesson learned" in stdout


def test_adapt_priors_only_no_sprint_metrics_yet(db_path: Path, project_id: str, workdir: Path) -> None:
    _write_project_json(workdir, project_id)
    _insert_row(
        db_path, "mem_entries", id="mem-1", project_id=project_id, kind="prior",
        title="prior: a lesson", body="b", created_at=_now_s(), updated_at=_now_s(),
    )
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "ADAPT       priors=1 (no sprint metrics yet)" in proc.stdout


def test_adapt_no_history_yet_with_project_json_present(db_path: Path, project_id: str, workdir: Path) -> None:
    _write_project_json(workdir, project_id)
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "ADAPT       no history yet (first cycle lands at close)" in proc.stdout


def test_adapt_project_json_present_but_id_null(db_path: Path, workdir: Path) -> None:
    """``project.json`` exists and is valid JSON, but its ``id`` key is JSON
    ``null`` — jq -r's raw-output rendering is the literal string
    ``"null"`` (non-empty), so ADAPT still runs (scoped to a project_id
    that matches nothing), landing on the "no history yet" branch rather
    than being omitted like the missing-file case."""
    _write_project_json(workdir, None)
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "ADAPT       no history yet (first cycle lands at close)" in proc.stdout


# --------------------------------------------------------------------------
# EVAL (omit-if-empty; only reachable once ADAPT's project-id gate passes).
# --------------------------------------------------------------------------
def test_eval_omitted_when_no_runs_recorded_for_project(db_path: Path, project_id: str, workdir: Path) -> None:
    _write_project_json(workdir, project_id)
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "EVAL" not in proc.stdout


def test_eval_latest_run_renders_pass_and_middle_dot_subject(db_path: Path, project_id: str, workdir: Path) -> None:
    _write_project_json(workdir, project_id)
    now_s = _now_s()
    _insert_row(
        db_path, "eval_runs", id="ev-1", project_id=project_id, kind="reflection",
        subject_ref=None, score=91, threshold=80, passed=1, created_at=now_s,
    )
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "EVAL        latest: reflection · 91/80 PASS  (1 scored)" in proc.stdout


def test_eval_failed_run_renders_fail_and_subject_ref(db_path: Path, project_id: str, workdir: Path) -> None:
    _write_project_json(workdir, project_id)
    now_s = _now_s()
    _insert_row(
        db_path, "eval_runs", id="ev-1", project_id=project_id, kind="discovery",
        subject_ref="mem-42", score=55, threshold=80, passed=0, created_at=now_s,
    )
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "EVAL        latest: discovery mem-42 55/80 FAIL  (1 scored)" in proc.stdout


# --------------------------------------------------------------------------
# STALE.
# --------------------------------------------------------------------------
def test_stale_freshness_and_never(db_path: Path, project_id: str, workdir: Path) -> None:
    now_s = _now_s()
    _insert_row(
        db_path, "index_issues", id="iss-1", project_id=project_id, source="github",
        number=1, title="t", state="open", url="u", created_at=now_s, updated_at=now_s,
        refreshed_at=now_s - 200,
    )
    # index_prs deliberately left empty -> "never" ("-").
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "STALE       issues=3m  prs=-" in proc.stdout


# --------------------------------------------------------------------------
# No-subcommand / args-ignored behavior (cmd_dash.sh never read its own $@).
# --------------------------------------------------------------------------
@pytest.mark.parametrize("extra_args", [[], ["-h"], ["--help"], ["--json"], ["garbage", "--unknown-flag"]])
def test_every_argument_shape_is_ignored_and_still_renders(
    db_path: Path, workdir: Path, extra_args: list[str]
) -> None:
    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash", *extra_args], env)

    assert proc.returncode == 0, proc.stderr
    assert "SPRINT" in proc.stdout
    assert "STALE" in proc.stdout
    # No Click help text leaked through (--help/-h are swallowed, not handled).
    assert "Usage:" not in proc.stdout


# --------------------------------------------------------------------------
# Full end-to-end: every section populated at once, in cmd_dash.sh's exact
# top-to-bottom section order (mirrors test_status.py's comprehensive
# seeded-tables gate, minus the retired bash twin).
# --------------------------------------------------------------------------
def test_full_dashboard_every_section_populated_in_order(db_path: Path, project_id: str, workdir: Path) -> None:
    branch = _current_branch()
    now_s = _now_s()
    now_ms = now_s * 1000

    _write_project_json(workdir, project_id)
    _write_lock_file(workdir)
    _write_graph_state(workdir, branch, {"n1": "done", "n2": "ready"})

    _insert_row(db_path, "focus", sprint=branch, lane="", objective="Ship it.", updated_at=now_s)

    _insert_row(
        db_path, "teammates", id="tm-1", project_id=project_id, team_name="team-a",
        teammate_name="nova", agent_type="engineer", session_id="sess-1",
        spawned_at=now_ms, last_seen_at=now_ms - 5_000, status="active",
    )

    _insert_row(
        db_path, "session_signals", project_id=project_id, sender="root",
        recipient="spawn-x", kind="seed-ready", payload="{}", sent_at=now_s,
    )

    # 400s (not 60s) deliberately: keeps the rendered age comfortably inside
    # the "minutes" bucket (400//60 == 6) even with a few seconds of real
    # subprocess-spawn jitter between `now_s` and the moment the dashboard
    # actually renders — a 60s offset risks crossing _age()'s `< 90` ->
    # seconds/minutes boundary and flaking.
    _insert_row(db_path, "escalations", project_id=project_id, role="engineer", question="q1", raised_at=now_s - 400)

    _insert_row(
        db_path, "loops", id="loop-1", project_id=project_id, kind="focus",
        max_iterations=5, status="active", created_at=now_s - 20,
    )
    _insert_row(db_path, "loop_iterations", loop_id="loop-1", iteration=1, new_findings=1, recorded_at=now_s - 10)

    _insert_row(
        db_path, "sprint_metrics", project_id=project_id, sprint_branch="s1",
        lane_count=3, wall_minutes=45.0, created_at=now_s,
    )
    _insert_row(
        db_path, "mem_entries", id="mem-1", project_id=project_id, kind="prior",
        title="prior: batch the writes", body="b", created_at=now_s, updated_at=now_s,
    )

    _insert_row(
        db_path, "eval_runs", id="ev-1", project_id=project_id, kind="reflection",
        subject_ref=None, score=95, threshold=80, passed=1, created_at=now_s,
    )

    _insert_row(
        db_path, "index_issues", id="iss-1", project_id=project_id, source="github",
        number=1, title="t", state="open", url="u", created_at=now_s, updated_at=now_s,
        refreshed_at=now_s - 400,
    )
    # 6000s clears _age()'s `< 5400` minutes-vs-hours boundary (5400s = 90
    # minutes) with margin, so this renders as hours, not a 66-minute count.
    _insert_row(
        db_path, "index_prs", id="pr-1", project_id=project_id, source="github",
        number=1, title="t", state="open", base_branch="main", head_branch="feature",
        url="u", created_at=now_s, updated_at=now_s, refreshed_at=now_s - 6_000,
    )

    env = _dash_env(db_path, workdir)

    proc = run_cli(["dash"], env)

    assert proc.returncode == 0, proc.stderr
    stdout = proc.stdout
    expected_in_order = (
        "═══ SHEPHERD DASH ═══",
        "lock=HELD",
        "FOCUS       Ship it.…",
        "GRAPH",
        "TEAMMATES   1 live",
        "nova:engineer:active:",
        "SIGNALS     pending",
        "spawn-x: 1",
        "ESCALATION  1 open (oldest 6m)",
        "LOOPS       active",
        "focus 1/5 (find=1)",
        "ADAPT       1 sprint(s)  lanes~3  wall~45m  priors=1",
        "latest: batch the writes",
        "EVAL        latest: reflection · 95/80 PASS  (1 scored)",
        "STALE       issues=6m  prs=1h",
    )
    last_idx = -1
    for expected in expected_in_order:
        idx = stdout.find(expected)
        assert idx != -1, f"missing {expected!r} in:\n{stdout}"
        assert idx > last_idx, f"{expected!r} out of order in:\n{stdout}"
        last_idx = idx
