"""Tests for `shepherd panes` — native port of `cmd_panes.sh` (tmux pane observability).

FIRST test suite for this command: no bash test ever existed for
`cmd_panes.sh`, so every load-bearing behavior is asserted here from the
bash source directly (status dashboard SQL + rendering + footer, capture
loop semantics, tail byte-parity, prune orphan rules, the script-top DB
gate, usage/help dispatch, and the #200 declared_state degrade).

Drives the module's Typer app DIRECTLY via a `${PY} -c` subprocess
snippet (`shepherd_cli.commands.panes.app`) — the sub-app is not yet
registered in `shepherd_cli.app`, so module-level invocation is what
works both BEFORE and AFTER the integrator flips registration (see
test_graph.py's identical note).

NO LIVE TMUX REQUIRED, per the "deterministic, local, free, <2s, never
flaky" gate-test contract: every tmux interaction goes through a tiny,
fully-scripted `tmux` stand-in written into a throwaway `bin/` directory
and PREPENDED to `PATH` (the test_close_lane.py fake-`gh` technique).
The stub's behavior is driven by marker files in `$TMUX_STUB_DIR`
(alive_<pane>, cwd_<pane>, cap_<pane>, capfail_<pane>, killfail_<pane>)
and it appends every invocation's argv to `$TMUX_STUB_DIR/log`, so both
DIRECTIONS are assertable: what the CLI told tmux, and what tmux told
the CLI. The no-tmux degradation paths are driven by REPLACING `PATH`
with an empty directory (the test_dups.py technique) — safe here because
every env pins `SHCTX_DB` + an absolute `SHEPHERD_WORKDIR` +
`CLAUDE_PLUGIN_ROOT`, so no code path needs `git` off `PATH` either.

The status table renderer's byte-parity with modern sqlite3
`-header -column` mode is asserted against the REAL `sqlite3` binary on
a fully literal (timing-free) SELECT — skipped only if no sqlite3 CLI
exists on the machine.
"""

from __future__ import annotations

import re
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import (
    CLI_ROOT,
    PY,
    TeammateRow,
    build_full_schema_db,
    build_partial_schema_db,
    cli_env,
    clean_env_dict,
    insert_project,
    insert_teammate,
)

#: Verbatim bash-parity usage text — must stay byte-for-byte identical to
#: shepherd_cli/commands/panes.py's own `_USAGE` constant (and to
#: cmd_panes.sh's `usage()` heredoc).
_USAGE = (
    "shctx panes status [--stale-mins=N]   per-lane dashboard (liveness + heartbeat + pane id)\n"
    "shctx panes capture [--lines=N]       snapshot each live teammate pane to <ns>/logs/panes/<lane>.log\n"
    "shctx panes tail <lane> [--lines=N]   print the tail of a captured lane log\n"
    "shctx panes prune [--closed-only]     kill orphan panes (closed teammates; else also worktree-gone)"
)

_PANES_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.panes import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd panes')\n"
)

_STATUS_HEADER = ["lane", "role", "status", "declared", "idle_s", "pane", "phase", "verdict"]

#: Fully-scripted tmux stand-in. Behavior is driven by files in
#: $TMUX_STUB_DIR (see the module docstring); every argv is logged.
_TMUX_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TMUX_STUB_DIR/log"
case "$1" in
  display)
    pane="$4"; fmt="$5"
    [ -e "$TMUX_STUB_DIR/alive_$pane" ] || exit 1
    if [ "$fmt" = "#{pane_id}" ]; then
      printf '%s\\n' "$pane"
    else
      cat "$TMUX_STUB_DIR/cwd_$pane" 2>/dev/null
    fi
    ;;
  capture-pane)
    pane="$4"
    [ -e "$TMUX_STUB_DIR/alive_$pane" ] || exit 1
    [ -e "$TMUX_STUB_DIR/capfail_$pane" ] && exit 1
    if [ -e "$TMUX_STUB_DIR/cap_$pane" ]; then
      cat "$TMUX_STUB_DIR/cap_$pane"
    else
      printf 'pane %s line\\n' "$pane"
    fi
    ;;
  kill-pane)
    pane="$3"
    [ -e "$TMUX_STUB_DIR/alive_$pane" ] || exit 1
    [ -e "$TMUX_STUB_DIR/killfail_$pane" ] && exit 1
    rm -f "$TMUX_STUB_DIR/alive_$pane"
    ;;
esac
exit 0
"""


# --------------------------------------------------------------------------
# Helpers: invocation, environment, DB seeding, tmux stub.
# --------------------------------------------------------------------------
def run_panes(
    args: list[str],
    env: dict[str, str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the panes module app directly: `${PY} -c "<snippet>" <args>`."""
    return subprocess.run(
        [PY, "-c", _PANES_SNIPPET, *args],
        cwd=str(cwd if cwd is not None else CLI_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def panes_env(
    db_path: Path,
    workdir: Path,
    *,
    bin_dir: Path | None = None,
    stub_dir: Path | None = None,
    path_override: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a `shepherd panes` test.

    Args:
        db_path: The fixture sqlite file (`SHCTX_DB`, via `cli_env`).
        workdir: An isolated tmp directory used as `SHEPHERD_WORKDIR` —
            where `logs/panes/` (and `runs/`) live, never the real
            repo's `.shepherd/`.
        bin_dir: When given, PREPENDED to `PATH` (holds the fake tmux).
        stub_dir: When given, sets `TMUX_STUB_DIR` for the stub.
        path_override: When given, REPLACES `PATH` entirely (simulates
            "no tmux binary anywhere on PATH").
        extra: Any additional env vars to set last (e.g. SHEPHERD_RUN).
    """
    workdir.mkdir(parents=True, exist_ok=True)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    if path_override is not None:
        env["PATH"] = path_override
    elif bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if stub_dir is not None:
        env["TMUX_STUB_DIR"] = str(stub_dir)
    if extra:
        env.update(extra)
    return env


def _write_tmux_stub(bin_dir: Path, stub_dir: Path) -> None:
    """Write the scripted tmux stand-in and initialize its state dir."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "log").write_text("")
    tmux_path = bin_dir / "tmux"
    tmux_path.write_text(_TMUX_STUB)
    tmux_path.chmod(0o755)


def _stub_log(stub_dir: Path) -> str:
    return (stub_dir / "log").read_text()


def _mark_alive(stub_dir: Path, pane: str) -> None:
    (stub_dir / f"alive_{pane}").write_text("")


@pytest.fixture
def panes_db(tmp_path: Path) -> tuple[Path, str]:
    """A full-schema fixture DB with one registered project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    return db_path, project_id


def _seed_teammate(
    db_path: Path,
    project_id: str,
    *,
    name: str,
    status: str = "active",
    declared: str | None = None,
    pane: str | None = None,
    last_seen_ago_s: int = 0,
    team: str = "panes-team",
    role: str = "shepherd:engineer",
) -> str:
    """Insert one teammate (optionally with a tmux pane id); returns its id.

    conftest's TeammateRow has no tmux_pane_id field (the #198 fixtures
    predate this command), so the pane id is stamped with a follow-up
    parameterized UPDATE.
    """
    now_ms = int(time.time() * 1000)
    teammate_id = f"tm-{name}"
    insert_teammate(
        db_path,
        project_id,
        TeammateRow(
            id=teammate_id,
            team_name=team,
            teammate_name=name,
            agent_type=role,
            session_id=None,
            status=status,
            declared_state=declared,
            spawned_at=now_ms,
            last_seen_at=now_ms - last_seen_ago_s * 1000,
        ),
    )
    if pane is not None:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("UPDATE teammates SET tmux_pane_id=? WHERE id=?", (pane, teammate_id))
            conn.commit()
        finally:
            conn.close()
    return teammate_id


def _add_heartbeat(db_path: Path, teammate_id: str, ts: int, phase: str | None) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO heartbeats (teammate_id, ts, phase) VALUES (?, ?, ?)",
            (teammate_id, ts, phase),
        )
        conn.commit()
    finally:
        conn.close()


def _status_rows_by_lane(stdout: str) -> tuple[list[str], dict[str, dict[str, str]], list[str]]:
    """Parse `status` stdout: (header tokens, {lane: row dict}, lane order)."""
    lines = stdout.splitlines()
    header = lines[0].split()
    assert set(lines[1]) <= {"-", " "}, f"expected dashed separator, got {lines[1]!r}"
    rows: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for line in lines[2:]:
        if not line.strip():
            break  # blank line before the footer
        tokens = line.split()
        assert len(tokens) == len(header), f"malformed row: {line!r}"
        row = dict(zip(header, tokens, strict=True))
        rows[row["lane"]] = row
        order.append(row["lane"])
    return header, rows, order


def _footer(workdir: Path, log_dir: str | None = None) -> str:
    d = log_dir if log_dir is not None else f"{workdir}/logs/panes"
    return f"pane logs: {d}/<lane>.log   (refresh: shctx panes capture; watch: /loop 30s shctx panes status)"


# --------------------------------------------------------------------------
# Dispatch: usage, help, DB gate, unknown subcommand.
# --------------------------------------------------------------------------
def test_bare_invocation_prints_usage_exit_0(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, _ = panes_db
    result = run_panes([], panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == _USAGE + "\n"


@pytest.mark.parametrize("args", [["-h"], ["--help"], ["help"]])
def test_help_forms_print_usage_exit_0(panes_db: tuple[Path, str], tmp_path: Path, args: list[str]) -> None:
    db_path, _ = panes_db
    result = run_panes(args, panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == _USAGE + "\n"


@pytest.mark.parametrize("args", [[], ["status"], ["capture"], ["tail", "x"], ["prune"], ["--help"]])
def test_missing_db_gates_every_invocation_exit_1(tmp_path: Path, args: list[str]) -> None:
    """Bash parity: the script-top `[[ -f $DB ]]` gate beats EVERY arm, help included."""
    missing_db = tmp_path / "nowhere" / "shepherd.db"
    env = panes_env(missing_db, tmp_path / "wd")
    result = run_panes(args, env)
    assert result.returncode == 1
    assert result.stderr.strip() == f"ERR: registry DB not found at {missing_db} (run 'shctx init')"
    assert result.stdout == ""


def test_unknown_subcommand_exit_2(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    """Documented deviation: Click's own unknown-command error, same exit 2 as bash."""
    db_path, _ = panes_db
    result = run_panes(["bogus"], panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 2


def test_unknown_flag_exit_2(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    """Bash: `unknown flag: --wat` exit 2; Click: its own UsageError, same exit 2."""
    db_path, _ = panes_db
    result = run_panes(["status", "--wat"], panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 2


# --------------------------------------------------------------------------
# status: dashboard rows, verdicts, ordering, footer, degrade, --json.
# --------------------------------------------------------------------------
def test_status_dashboard_rows_verdicts_order_footer(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    workdir = tmp_path / "wd"
    # active rows (sorted by name): a-inprog, e-error, z-crashy; then booting; then idle.
    tid = _seed_teammate(db_path, project_id, name="a-inprog", status="active",
                         declared="in-progress", pane="%1", last_seen_ago_s=20 * 60)
    _add_heartbeat(db_path, tid, ts=1000, phase="plan")
    _add_heartbeat(db_path, tid, ts=2000, phase="implement")
    _seed_teammate(db_path, project_id, name="e-error", status="active", declared="error", pane="%9")
    _seed_teammate(db_path, project_id, name="z-crashy", status="active", last_seen_ago_s=20 * 60)
    _seed_teammate(db_path, project_id, name="m-boot", status="booting", last_seen_ago_s=10)
    _seed_teammate(db_path, project_id, name="b-idle", status="idle", declared="idle")
    _seed_teammate(db_path, project_id, name="c-done", status="idle", declared="complete")

    result = run_panes(["status"], panes_env(db_path, workdir))
    assert result.returncode == 0, result.stderr

    header, rows, order = _status_rows_by_lane(result.stdout)
    assert header == _STATUS_HEADER
    # ORDER BY v.status, v.teammate_name: 'active' < 'booting' < 'idle'.
    assert order == ["a-inprog", "e-error", "z-crashy", "m-boot", "b-idle", "c-done"]

    # Declaration beats the timing heuristic (#193): stale but in-progress -> ok.
    assert rows["a-inprog"]["verdict"] == "ok"
    assert rows["a-inprog"]["declared"] == "in-progress"
    assert rows["a-inprog"]["pane"] == "%1"
    assert rows["a-inprog"]["phase"] == "implement"  # latest heartbeat wins
    assert int(rows["a-inprog"]["idle_s"]) >= 19 * 60

    assert rows["e-error"]["verdict"] == "error"
    assert rows["z-crashy"]["verdict"] == "presumed-crashed"  # undeclared + stale + active
    assert rows["z-crashy"]["declared"] == "-"
    assert rows["z-crashy"]["pane"] == "-"
    assert rows["z-crashy"]["phase"] == "-"
    assert rows["m-boot"]["verdict"] == "ok"  # undeclared + fresh + booting
    assert rows["b-idle"]["verdict"] == "idle"
    assert rows["c-done"]["verdict"] == "complete"
    assert rows["m-boot"]["role"] == "shepherd:engineer"

    # Blank line, then the verbatim footer.
    lines = result.stdout.splitlines()
    assert lines[-2] == ""
    assert lines[-1] == _footer(workdir)


def test_status_excludes_crashed_and_retired(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="live-one", status="active")
    _seed_teammate(db_path, project_id, name="dead-one", status="crashed")
    _seed_teammate(db_path, project_id, name="gone-one", status="retired")
    result = run_panes(["status"], panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 0, result.stderr
    _, rows, _ = _status_rows_by_lane(result.stdout)
    assert set(rows) == {"live-one"}


def test_status_stale_mins_flag_moves_the_threshold(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="two-min-quiet", status="active", last_seen_ago_s=120)
    env = panes_env(db_path, tmp_path / "wd")

    _, rows, _ = _status_rows_by_lane(run_panes(["status"], env).stdout)
    assert rows["two-min-quiet"]["verdict"] == "ok"  # default 5-min window

    _, rows, _ = _status_rows_by_lane(run_panes(["status", "--stale-mins=1"], env).stdout)
    assert rows["two-min-quiet"]["verdict"] == "presumed-crashed"


def test_status_empty_prints_only_blank_line_and_footer(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    """sqlite3 -header -column prints NOTHING for zero rows — so does the port."""
    db_path, _ = panes_db
    workdir = tmp_path / "wd"
    result = run_panes(["status"], panes_env(db_path, workdir))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n" + _footer(workdir) + "\n"


def test_status_dash_alias(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    """``dash`` renders identically to ``status`` — a RENDERER contract.

    The rendered row carries a live "seconds since last seen" column, so the
    two invocations straddle a second boundary often enough to fail on the
    clock rather than on the aliasing (observed: 119 vs 120). Normalize that
    one column before the byte comparison — same treatment
    ``test_eval.py``'s ``--md`` flag-parity test needs for its relative age.
    """
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="lane-a", status="active", last_seen_ago_s=120)
    env = panes_env(db_path, tmp_path / "wd")
    via_status = run_panes(["status", "--stale-mins=1"], env)
    via_dash = run_panes(["dash", "--stale-mins=1"], env)
    assert via_dash.returncode == 0, via_dash.stderr

    def _freeze_age(text: str) -> str:
        """Replace the sec-since-seen column's value with a fixed token."""
        return re.sub(r"\b\d+\b(?=\s+-)", "AGE", text)

    assert _freeze_age(via_dash.stdout) == _freeze_age(via_status.stdout)


def test_status_json_additive(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    tid = _seed_teammate(db_path, project_id, name="lane-j", status="active",
                         declared="in-progress", pane="%4")
    _add_heartbeat(db_path, tid, ts=5, phase="review")
    result = run_panes(["status", "--json"], panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, list) and len(payload) == 1
    row = payload[0]
    assert list(row) == _STATUS_HEADER
    assert row["lane"] == "lane-j"
    assert row["declared"] == "in-progress"
    assert row["pane"] == "%4"
    assert row["phase"] == "review"
    assert row["verdict"] == "ok"
    assert isinstance(row["idle_s"], int)


def test_status_degrades_without_declared_state_column(tmp_path: Path) -> None:
    """#200 backstop: pre-0019 DB + unhealable schema -> timing-only verdict, declared '-'."""
    db_path = tmp_path / "old.db"
    build_partial_schema_db(db_path)  # 0001 + 0007 only: no declared_state column
    project_id = insert_project(db_path)
    _seed_teammate(db_path, project_id, name="old-lane", status="active", last_seen_ago_s=20 * 60)

    empty_plugin_root = tmp_path / "no-plugin-here"
    empty_plugin_root.mkdir()
    env = panes_env(db_path, tmp_path / "wd")
    env["CLAUDE_PLUGIN_ROOT"] = str(empty_plugin_root)  # self-heal cannot find migrations
    # cwd outside the repo so the walk-up lookup fails too.
    result = run_panes(["status"], env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    _, rows, _ = _status_rows_by_lane(result.stdout)
    assert rows["old-lane"]["declared"] == "-"
    assert rows["old-lane"]["verdict"] == "presumed-crashed"


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="no sqlite3 CLI on this machine")
def test_render_matches_sqlite3_column_mode_byte_for_byte(tmp_path: Path) -> None:
    """The table renderer reproduces modern sqlite3 -header -column exactly."""
    rows = [
        {"lane": "engineer-a", "role": "shepherd:engineer", "status": "active",
         "declared": "in-progress", "idle_s": 1234, "pane": "%1",
         "phase": "implement", "verdict": "ok"},
        {"lane": "x", "role": "r", "status": "idle", "declared": "-",
         "idle_s": 5, "pane": "-", "phase": "-", "verdict": "presumed-crashed"},
    ]
    snippet = (
        "import json, sys\n"
        "from shepherd_cli.commands.panes import _render_column_table\n"
        "table = _render_column_table(json.loads(sys.argv[1]))\n"
        "sys.stdout.write('' if table is None else table + '\\n')\n"
    )
    ours = subprocess.run(
        [PY, "-c", snippet, json.dumps(rows)],
        cwd=str(CLI_ROOT), env=clean_env_dict(), capture_output=True, text=True, timeout=30,
    )
    assert ours.returncode == 0, ours.stderr

    sql = (
        "SELECT 'engineer-a' AS lane, 'shepherd:engineer' AS role, 'active' AS status,"
        " 'in-progress' AS declared, 1234 AS idle_s, '%1' AS pane, 'implement' AS phase, 'ok' AS verdict "
        "UNION ALL SELECT 'x','r','idle','-',5,'-','-','presumed-crashed';"
    )
    theirs = subprocess.run(
        ["sqlite3", "-header", "-column", ":memory:", sql],
        capture_output=True, text=True, timeout=30,
    )
    assert theirs.returncode == 0, theirs.stderr
    assert ours.stdout == theirs.stdout


# --------------------------------------------------------------------------
# capture.
# --------------------------------------------------------------------------
def test_capture_without_tmux_degrades_exit_0(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="alpha", status="active", pane="%1")
    workdir = tmp_path / "wd"
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    result = run_panes(["capture"], panes_env(db_path, workdir, path_override=str(empty_bin)))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "tmux not available — nothing to capture (teammateMode is in-process?)\n"
    assert not (workdir / "logs").exists()


def test_capture_writes_live_panes_only(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="alpha", status="active", pane="%1")
    _seed_teammate(db_path, project_id, name="beta", status="active", pane="%2")  # dead pane
    _seed_teammate(db_path, project_id, name="gamma", status="active")  # no pane
    _seed_teammate(db_path, project_id, name="delta", status="crashed", pane="%3")  # excluded status

    workdir, bin_dir, stub_dir = tmp_path / "wd", tmp_path / "bin", tmp_path / "stub"
    _write_tmux_stub(bin_dir, stub_dir)
    _mark_alive(stub_dir, "%1")
    (stub_dir / "cap_%1").write_text("line1\nline2\n")

    result = run_panes(["capture"], panes_env(db_path, workdir, bin_dir=bin_dir, stub_dir=stub_dir))
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"captured 1 live pane(s) → {workdir}/logs/panes/\n"
    assert (workdir / "logs" / "panes" / "alpha.log").read_text() == "line1\nline2\n"
    assert not (workdir / "logs" / "panes" / "beta.log").exists()

    log = _stub_log(stub_dir)
    assert "capture-pane -p -t %1 -S -200" in log  # default --lines=200
    assert "display -p -t %2 #{pane_id}" in log  # dead pane was probed...
    assert "capture-pane -p -t %2" not in log  # ...but never captured
    assert "%3" not in log  # crashed teammate never reaches tmux at all


def test_capture_lines_flag_and_safe_name(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="lane/w spaces", status="idle", pane="%5")
    workdir, bin_dir, stub_dir = tmp_path / "wd", tmp_path / "bin", tmp_path / "stub"
    _write_tmux_stub(bin_dir, stub_dir)
    _mark_alive(stub_dir, "%5")

    result = run_panes(["capture", "--lines=5"], panes_env(db_path, workdir, bin_dir=bin_dir, stub_dir=stub_dir))
    assert result.returncode == 0, result.stderr
    assert "capture-pane -p -t %5 -S -5" in _stub_log(stub_dir)
    # safe_name: every char outside A-Za-z0-9._- becomes '_'.
    assert (workdir / "logs" / "panes" / "lane_w_spaces.log").is_file()


def test_capture_failure_truncates_log_but_does_not_count(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    """Bash parity: `tmux ... > file || continue` creates/truncates the file even on failure."""
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="flaky", status="active", pane="%6")
    workdir, bin_dir, stub_dir = tmp_path / "wd", tmp_path / "bin", tmp_path / "stub"
    _write_tmux_stub(bin_dir, stub_dir)
    _mark_alive(stub_dir, "%6")
    (stub_dir / "capfail_%6").write_text("")
    log_file = workdir / "logs" / "panes" / "flaky.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text("stale content from an earlier capture\n")

    result = run_panes(["capture"], panes_env(db_path, workdir, bin_dir=bin_dir, stub_dir=stub_dir))
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"captured 0 live pane(s) → {workdir}/logs/panes/\n"
    assert log_file.read_text() == ""  # truncated by the redirection, like bash


def test_capture_run_scoped_flag_and_marker(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    """Run shim: --run flag and the runs/current marker route NEW logs to runs/<run>/."""
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="alpha", status="active", pane="%1")
    workdir, bin_dir, stub_dir = tmp_path / "wd", tmp_path / "bin", tmp_path / "stub"
    _write_tmux_stub(bin_dir, stub_dir)
    _mark_alive(stub_dir, "%1")
    env = panes_env(db_path, workdir, bin_dir=bin_dir, stub_dir=stub_dir)

    result = run_panes(["capture", "--run=r7"], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"captured 1 live pane(s) → {workdir}/runs/r7/logs/panes/\n"
    assert (workdir / "runs" / "r7" / "logs" / "panes" / "alpha.log").is_file()

    (workdir / "runs").mkdir(exist_ok=True)
    (workdir / "runs" / "current").write_text("r9\n")
    result = run_panes(["capture"], env)
    assert result.returncode == 0, result.stderr
    assert (workdir / "runs" / "r9" / "logs" / "panes" / "alpha.log").is_file()


# --------------------------------------------------------------------------
# tail.
# --------------------------------------------------------------------------
def test_tail_requires_lane_exit_2(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, _ = panes_db
    result = run_panes(["tail"], panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 2
    assert result.stderr.strip() == "usage: shctx panes tail <lane> [--lines=N]"


def test_tail_without_capture_exit_1(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, _ = panes_db
    result = run_panes(["tail", "ghost-lane"], panes_env(db_path, tmp_path / "wd"))
    assert result.returncode == 1
    assert result.stderr.strip() == "no capture for 'ghost-lane' yet — run: shctx panes capture"


def test_tail_prints_last_lines_byte_for_byte(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, _ = panes_db
    workdir = tmp_path / "wd"
    log_dir = workdir / "logs" / "panes"
    log_dir.mkdir(parents=True)
    content = "".join(f"l{i:02d}\n" for i in range(1, 51))
    (log_dir / "mylane.log").write_text(content)
    env = panes_env(db_path, workdir)

    result = run_panes(["tail", "mylane"], env)  # default --lines=40
    assert result.returncode == 0, result.stderr
    assert result.stdout == "".join(f"l{i:02d}\n" for i in range(11, 51))

    result = run_panes(["tail", "mylane", "--lines=3"], env)
    assert result.stdout == "l48\nl49\nl50\n"

    # tail -n parity on a log whose final line has no trailing newline.
    (log_dir / "rawlane.log").write_text("a\nb")
    result = run_panes(["tail", "rawlane", "--lines=1"], env)
    assert result.stdout == "b"

    # safe_name applies to the lookup exactly like capture's write side.
    (log_dir / "lane_w_spaces.log").write_text("z\n")
    result = run_panes(["tail", "lane/w spaces", "--lines=1"], env)
    assert result.stdout == "z\n"


def test_tail_json_additive(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, _ = panes_db
    workdir = tmp_path / "wd"
    log_dir = workdir / "logs" / "panes"
    log_dir.mkdir(parents=True)
    (log_dir / "mylane.log").write_text("one\ntwo\nthree\n")
    result = run_panes(["tail", "mylane", "--lines=2", "--json"], panes_env(db_path, workdir))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"lane": "mylane", "path": str(log_dir / "mylane.log"), "lines": ["two", "three"]}


def test_tail_run_scoped_prefers_run_log_falls_back_to_legacy(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, _ = panes_db
    workdir = tmp_path / "wd"
    legacy_dir = workdir / "logs" / "panes"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "mylane.log").write_text("legacy\n")
    env = panes_env(db_path, workdir, extra={"SHEPHERD_RUN": "r7"})

    # Run identified but no run-scoped log yet -> ALWAYS fall back to legacy.
    result = run_panes(["tail", "mylane", "--lines=1"], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "legacy\n"

    run_dir = workdir / "runs" / "r7" / "logs" / "panes"
    run_dir.mkdir(parents=True)
    (run_dir / "mylane.log").write_text("run-scoped\n")
    result = run_panes(["tail", "mylane", "--lines=1"], env)
    assert result.stdout == "run-scoped\n"


# --------------------------------------------------------------------------
# prune.
# --------------------------------------------------------------------------
def test_prune_without_tmux_degrades_exit_0(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="ghost", status="crashed", pane="%2")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    result = run_panes(["prune"], panes_env(db_path, tmp_path / "wd", path_override=str(empty_bin)))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "tmux not available — no panes to prune\n"


def test_prune_kills_closed_teammates_live_panes_only(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    workdir = tmp_path / "wd"
    workdir.mkdir()
    _seed_teammate(db_path, project_id, name="ghost", status="crashed", pane="%2")
    _seed_teammate(db_path, project_id, name="worker", status="active", pane="%1")
    _seed_teammate(db_path, project_id, name="long-gone", status="retired", pane="%8")  # pane dead

    bin_dir, stub_dir = tmp_path / "bin", tmp_path / "stub"
    _write_tmux_stub(bin_dir, stub_dir)
    _mark_alive(stub_dir, "%2")
    _mark_alive(stub_dir, "%1")
    (stub_dir / "cwd_%1").write_text(f"{workdir}\n")  # live teammate, ordinary cwd

    result = run_panes(["prune"], panes_env(db_path, workdir, bin_dir=bin_dir, stub_dir=stub_dir))
    assert result.returncode == 0, result.stderr
    assert "killed orphan pane %2 (ghost, status=crashed)" in result.stdout
    assert result.stdout.endswith("pruned 1 orphan pane(s)\n")

    log = _stub_log(stub_dir)
    assert "kill-pane -t %2" in log
    assert "kill-pane -t %1" not in log
    assert "kill-pane -t %8" not in log  # already-dead pane: nothing to do


def test_prune_worktree_gone_heuristic_and_closed_only(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    workdir = tmp_path / "wd"
    _seed_teammate(db_path, project_id, name="wt-lane", status="active", pane="%5")
    _seed_teammate(db_path, project_id, name="ok-lane", status="active", pane="%6")

    bin_dir, stub_dir = tmp_path / "bin", tmp_path / "stub"
    _write_tmux_stub(bin_dir, stub_dir)
    _mark_alive(stub_dir, "%5")
    _mark_alive(stub_dir, "%6")
    gone_worktree = tmp_path / "repo" / ".worktrees" / "lane-1"  # never created
    live_worktree = tmp_path / "repo" / ".worktrees" / "lane-2"
    live_worktree.mkdir(parents=True)
    (stub_dir / "cwd_%5").write_text(f"{gone_worktree}\n")
    (stub_dir / "cwd_%6").write_text(f"{live_worktree}\n")
    env = panes_env(db_path, workdir, bin_dir=bin_dir, stub_dir=stub_dir)

    # --closed-only skips the worktree heuristic entirely: nothing dies.
    result = run_panes(["prune", "--closed-only"], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "pruned 0 orphan pane(s)\n"

    # Default mode: only the worktree-GONE pane is an orphan.
    result = run_panes(["prune"], env)
    assert result.returncode == 0, result.stderr
    assert "killed orphan pane %5 (wt-lane, status=active)" in result.stdout
    assert result.stdout.endswith("pruned 1 orphan pane(s)\n")
    assert "kill-pane -t %6" not in _stub_log(stub_dir)


def test_prune_failed_kill_is_silent_and_uncounted(panes_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = panes_db
    _seed_teammate(db_path, project_id, name="stubborn", status="crashed", pane="%7")
    bin_dir, stub_dir = tmp_path / "bin", tmp_path / "stub"
    _write_tmux_stub(bin_dir, stub_dir)
    _mark_alive(stub_dir, "%7")
    (stub_dir / "killfail_%7").write_text("")

    result = run_panes(["prune"], panes_env(db_path, tmp_path / "wd", bin_dir=bin_dir, stub_dir=stub_dir))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "pruned 0 orphan pane(s)\n"
    assert "kill-pane -t %7" in _stub_log(stub_dir)  # it did try
