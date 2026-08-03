"""Subprocess tests for ``shepherd loop`` — native port of ``cmd_loop.sh``.

Bash parity target: ``skills/context/scripts/cmd_loop.sh``; every
load-bearing assertion from ``skills/context/tests/test_loop_lifecycle.sh``
is migrated here (init id shape + row state, status text/json/md, record
x2 + idempotent re-record, close, list active/all/json, focus upsert/show/
refresh, per-lane focus independence, day-sequence uniqueness, native-cmd
emission for fixed/self-paced/override/in-session pacing, and the
``--self-paced``/``--interval`` conflict), plus this port's own documented
deviations and the issue-#234 apostrophe regression.

INVOCATION NOTE (the ``test_adapt.py`` pattern): ``loop`` is not yet
registered in ``shepherd_cli.app``/``__main__``, so ``run_cli(["loop",
...])`` would fall through to the bash shim. Every test therefore drives
the module's own Typer app directly in a fresh subprocess (``${PY} -c
"...loop import app; app(...)"``) — an invocation that works both before
AND after registration, so these tests need no edits when the integrator
flips the sub-app on.

REGRESSION #234: bash's ``loop focus upsert`` built its SQL by string
interpolation and broke on an ``--objective`` containing an apostrophe
even with the ``_txt()`` quote-doubling helper. The port binds every value
as a ``?`` parameter; ``test_focus_upsert_special_characters_roundtrip``
upserts an objective containing an apostrophe, a double quote, AND a
semicolon (an injection-shaped payload), then reads it back byte-identical
from the DB directly and through ``focus show --json``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import CLI_ROOT, PY, build_full_schema_db, cli_env, insert_project

# --------------------------------------------------------------------------
# Module-app invocation + raw-sqlite3 helpers.
# --------------------------------------------------------------------------
_LOOP_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.loop import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd loop')\n"
)

#: The objective the #234 regression round-trips: apostrophe, double
#: quote, semicolon (and an SQL-injection shape for good measure).
TRICKY_OBJECTIVE = """Ship Joe's "focus-loop"; DROP TABLE focus; --v6.0.9"""


def run_loop(
    args: Sequence[str],
    env: dict[str, str],
    *,
    cwd: Path | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Run the loop module app as a real subprocess (see module docstring)."""
    return subprocess.run(
        [PY, "-c", _LOOP_SNIPPET, *args],
        env=env,
        cwd=str(cwd or CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _db_rows(db_path: Path, sql: str, params: Sequence[object] = ()) -> list[tuple]:
    """Fetch rows from the fixture DB (test-controlled SQL only)."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _db_scalar(db_path: Path, sql: str, params: Sequence[object] = ()) -> object:
    """Fetch one scalar from the fixture DB."""
    rows = _db_rows(db_path, sql, params)
    return rows[0][0] if rows else None


@pytest.fixture
def loop_db(tmp_path: Path) -> tuple[Path, str]:
    """A full-schema fixture DB with one registered project (FK target)."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    return db_path, project_id


def _init(env: dict[str, str], *extra: str) -> str:
    """``loop init`` with defaults suitable for most tests; returns the loop-id."""
    args = ["init", "--task=find all TODO comments", "--max=5", "--kind=convergence", "--agent=discovery"]
    proc = run_loop([*args, *extra], env)
    assert proc.returncode == 0, f"init failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return proc.stdout.strip()


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------
def test_init_emits_day_scoped_id_and_row(loop_db: tuple[Path, str]) -> None:
    """Bash: init-id-prefix / init-status / init-max / init-kind."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)

    assert loop_id.startswith("loop-")
    assert re.fullmatch(r"loop-[0-9]{8}-[0-9]{3}", loop_id), f"unexpected id format: {loop_id}"
    # The date component is today's local date, like bash's `date +%Y%m%d`.
    assert loop_id[5:13] == time.strftime("%Y%m%d")

    row = _db_rows(
        db_path,
        "SELECT status, max_iterations, kind, agent, task, until_field, interval FROM loops WHERE id=?",
        [loop_id],
    )[0]
    assert row == ("active", 5, "convergence", "discovery", "find all TODO comments", "new_findings", None)


def test_init_task_with_special_characters_roundtrips(loop_db: tuple[Path, str]) -> None:
    """#234 class on loops.task: apostrophe/quote/semicolon bind cleanly."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    task = """find Joe's "TODO"; markers"""
    proc = run_loop(["init", f"--task={task}", "--max=3"], env)
    assert proc.returncode == 0, proc.stderr
    loop_id = proc.stdout.strip()
    assert _db_scalar(db_path, "SELECT task FROM loops WHERE id=?", [loop_id]) == task


def test_init_second_same_day_increments_sequence(loop_db: tuple[Path, str]) -> None:
    """Bash: day-sequence — two inits on the same day produce distinct, increasing ids."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    first = _init(env)
    proc = run_loop(["init", "--task=second loop same day", "--max=3", "--kind=watch"], env)
    assert proc.returncode == 0, proc.stderr
    second = proc.stdout.strip()
    assert second != first
    assert second.startswith("loop-")
    assert int(second.rsplit("-", 1)[1]) == int(first.rsplit("-", 1)[1]) + 1


def test_init_requires_max(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    proc = run_loop(["init", "--task=x"], cli_env(db_path))
    assert proc.returncode == 1
    assert "ERROR: loop init requires --max=<N>" in proc.stderr


@pytest.mark.parametrize("bad_max", ["0", "abc", "-3"])
def test_init_rejects_nonpositive_max(loop_db: tuple[Path, str], bad_max: str) -> None:
    db_path, _ = loop_db
    proc = run_loop(["init", "--task=x", f"--max={bad_max}"], cli_env(db_path))
    assert proc.returncode == 1
    assert f"ERROR: --max must be a positive integer (got '{bad_max}')" in proc.stderr


def test_init_rejects_unknown_kind(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    proc = run_loop(["init", "--task=x", "--max=4", "--kind=bogus"], cli_env(db_path))
    assert proc.returncode == 1
    assert "ERROR: --kind must be focus|convergence|watch|generic (got 'bogus')" in proc.stderr


def test_init_self_paced_stores_sentinel(loop_db: tuple[Path, str]) -> None:
    """Bash: self-paced-sentinel — interval column holds the literal 'self-paced'."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = run_loop(["init", "--task=exhaustive discovery", "--max=8", "--self-paced"], env)
    assert proc.returncode == 0, proc.stderr
    loop_id = proc.stdout.strip()
    assert _db_scalar(db_path, "SELECT interval FROM loops WHERE id=?", [loop_id]) == "self-paced"


def test_init_self_paced_conflicts_with_interval(loop_db: tuple[Path, str]) -> None:
    """Bash: self-paced-interval-conflict — rc must be 1."""
    db_path, _ = loop_db
    proc = run_loop(["init", "--task=bad", "--max=4", "--self-paced", "--interval=5m"], cli_env(db_path))
    assert proc.returncode == 1
    assert "ERROR: --self-paced and --interval=<dur> are mutually exclusive" in proc.stderr


def test_unknown_option_exits_2(loop_db: tuple[Path, str]) -> None:
    """Documented deviation 1: unknown option -> Click's exit 2, not bash's exit 1."""
    db_path, _ = loop_db
    proc = run_loop(["init", "--task=x", "--max=4", "--bogus=1"], cli_env(db_path))
    assert proc.returncode == 2


def test_bare_invocation_prints_usage_exit_0(loop_db: tuple[Path, str]) -> None:
    """Bash: bare `shctx loop` prints usage and exits 0."""
    db_path, _ = loop_db
    proc = run_loop([], cli_env(db_path))
    assert proc.returncode == 0
    assert "Usage" in proc.stdout


def test_no_project_registered_gate(tmp_path: Path) -> None:
    """Bash-parity prerequisite gate: every subcommand exits 1 without a project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)  # full schema, but NO projects row
    env = cli_env(db_path)
    for args in (["init", "--task=x", "--max=3"], ["status", "--id=loop-x"], ["list"], ["focus", "show", "--sprint=s"]):
        proc = run_loop(args, env)
        assert proc.returncode == 1, f"{args}: {proc.stdout!r} {proc.stderr!r}"
        assert "ERROR: no project registered" in proc.stderr


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
def test_status_requires_id(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    proc = run_loop(["status"], cli_env(db_path))
    assert proc.returncode == 1
    assert "ERROR: loop status requires --id=<loop-id>" in proc.stderr


def test_status_not_found(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    proc = run_loop(["status", "--id=loop-19700101-001"], cli_env(db_path))
    assert proc.returncode == 1
    assert "ERROR: loop not found: loop-19700101-001" in proc.stderr


def test_status_text_before_iterations(loop_db: tuple[Path, str]) -> None:
    """Bash: status-id / status-active — exact text shape, no iterations yet."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)
    created_at = _db_scalar(db_path, "SELECT created_at FROM loops WHERE id=?", [loop_id])

    proc = run_loop(["status", f"--id={loop_id}"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        f"id={loop_id} kind=convergence status=active max=5 until=new_findings",
        f"task=find all TODO comments agent=discovery interval=none created_at={created_at}",
        "iterations: (none yet)",
    ]


def test_status_json(loop_db: tuple[Path, str]) -> None:
    """Bash: status-json-id / status-json-status / status-json-iters."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)

    proc = run_loop(["status", f"--id={loop_id}", "--json"], env)
    assert proc.returncode == 0, proc.stderr
    assert f'"{loop_id}"' in proc.stdout  # bash asserts the quoted id substring
    payload = json.loads(proc.stdout)
    assert payload["id"] == loop_id
    assert payload["status"] == "active"
    assert payload["iterations"] == []
    # Key order mirrors bash's json_object argument order exactly.
    assert list(payload.keys()) == [
        "id", "kind", "task", "agent", "max_iterations", "until_field",
        "interval", "status", "created_at", "iterations",
    ]


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------
def _record_two(env: dict[str, str], loop_id: str) -> None:
    """The bash lifecycle's two record calls."""
    for iteration, nf, summary in (("1", "true", "found 3 TODO comments"), ("2", "false", "no new findings")):
        proc = run_loop(
            ["record", f"--id={loop_id}", f"--iteration={iteration}", f"--new_findings={nf}", f"--summary={summary}"],
            env,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == f"loop record: {loop_id} iteration {iteration} new_findings={nf}\n"


def test_record_two_iterations(loop_db: tuple[Path, str]) -> None:
    """Bash: record-count / record-nf1 / record-nf2 + the exact record line."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)
    _record_two(env, loop_id)

    assert _db_scalar(db_path, "SELECT COUNT(*) FROM loop_iterations WHERE loop_id=?", [loop_id]) == 2
    assert _db_scalar(db_path, "SELECT new_findings FROM loop_iterations WHERE loop_id=? AND iteration=1", [loop_id]) == 1
    assert _db_scalar(db_path, "SELECT new_findings FROM loop_iterations WHERE loop_id=? AND iteration=2", [loop_id]) == 0


def test_status_md_shows_iterations(loop_db: tuple[Path, str]) -> None:
    """Bash: status-md-iter1 / status-md-iter2 / status-md-summ."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)
    _record_two(env, loop_id)

    proc = run_loop(["status", f"--id={loop_id}", "--md"], env)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert f"## Loop: {loop_id}" in out
    assert "- status: **active**" in out
    assert "| # | new_findings | summary | recorded_at |" in out
    assert "| 1 | true | found 3 TODO comments |" in out
    assert "| 2 | false | no new findings |" in out


def test_record_idempotent_replace(loop_db: tuple[Path, str]) -> None:
    """Bash: record-idempotent-count / record-idempotent-replaced."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)
    _record_two(env, loop_id)

    proc = run_loop(
        ["record", f"--id={loop_id}", "--iteration=1", "--new_findings=false", "--summary=re-recorded"],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    assert _db_scalar(db_path, "SELECT COUNT(*) FROM loop_iterations WHERE loop_id=?", [loop_id]) == 2  # still 2, not 3
    assert _db_scalar(db_path, "SELECT new_findings FROM loop_iterations WHERE loop_id=? AND iteration=1", [loop_id]) == 0
    assert _db_scalar(db_path, "SELECT summary FROM loop_iterations WHERE loop_id=? AND iteration=1", [loop_id]) == "re-recorded"


def test_record_validation(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)

    cases = [
        (["record"], "ERROR: loop record requires --id=<loop-id>"),
        (["record", f"--id={loop_id}"], "ERROR: loop record requires --iteration=<N>"),
        (["record", f"--id={loop_id}", "--iteration=1"], "ERROR: loop record requires --new_findings=<true|false|0|1>"),
        (
            ["record", "--id=loop-19700101-001", "--iteration=1", "--new_findings=true"],
            "ERROR: loop not found: loop-19700101-001",
        ),
        (
            ["record", f"--id={loop_id}", "--iteration=1", "--new_findings=maybe"],
            "ERROR: --new_findings must be true|false|1|0 (got 'maybe')",
        ),
        (
            ["record", f"--id={loop_id}", "--iteration=abc", "--new_findings=true"],
            "ERROR: --iteration must be a positive integer (got 'abc')",
        ),
    ]
    for args, message in cases:
        proc = run_loop(args, env)
        assert proc.returncode == 1, f"{args}: {proc.stdout!r} {proc.stderr!r}"
        assert message in proc.stderr, f"{args}: {proc.stderr!r}"

    # --iteration=0 passes bash's _num regex and dies on CHECK(iteration > 0)
    # (documented deviation 4: same exit 1, driver's message text).
    proc = run_loop(["record", f"--id={loop_id}", "--iteration=0", "--new_findings=true"], env)
    assert proc.returncode == 1
    assert proc.stderr.startswith("ERROR:")
    assert _db_scalar(db_path, "SELECT COUNT(*) FROM loop_iterations WHERE loop_id=?", [loop_id]) == 0


# --------------------------------------------------------------------------
# close + list
# --------------------------------------------------------------------------
def test_close_converged(loop_db: tuple[Path, str]) -> None:
    """Bash: close-output / close-output2 / close-status."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)
    _record_two(env, loop_id)

    proc = run_loop(["close", f"--id={loop_id}", "--status=converged"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"loop close: {loop_id} status=converged iterations=2\n"
    assert _db_scalar(db_path, "SELECT status FROM loops WHERE id=?", [loop_id]) == "converged"


def test_close_validation(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)

    cases = [
        (["close"], "ERROR: loop close requires --id=<loop-id>"),
        ([f"close", f"--id={loop_id}"], "ERROR: loop close requires --status=<converged|cap-reached|aborted>"),
        (
            ["close", f"--id={loop_id}", "--status=done"],
            "ERROR: --status must be converged|cap-reached|aborted (got 'done')",
        ),
        (
            ["close", "--id=loop-19700101-001", "--status=converged"],
            "ERROR: loop not found: loop-19700101-001",
        ),
    ]
    for args, message in cases:
        proc = run_loop(args, env)
        assert proc.returncode == 1, f"{args}: {proc.stderr!r}"
        assert message in proc.stderr


def test_list_active_excludes_closed_all_includes(loop_db: tuple[Path, str]) -> None:
    """Bash: list-active / list-all / list-json-all."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)
    run_loop(["close", f"--id={loop_id}", "--status=converged"], env)

    active = run_loop(["list"], env)
    assert active.returncode == 0
    assert loop_id not in active.stdout
    assert active.stdout == "_(no loops found)_\n"

    everything = run_loop(["list", "--all"], env)
    assert everything.returncode == 0
    assert loop_id in everything.stdout
    assert "converged" in everything.stdout

    as_json = run_loop(["list", "--all", "--json"], env)
    assert as_json.returncode == 0
    assert f'"{loop_id}"' in as_json.stdout
    payload = json.loads(as_json.stdout)
    assert [item["id"] for item in payload] == [loop_id]
    assert payload[0]["status"] == "converged"


def test_list_empty_json_is_empty_array(loop_db: tuple[Path, str]) -> None:
    """Bash json_group_array over the empty set prints []."""
    db_path, _ = loop_db
    proc = run_loop(["list", "--json"], cli_env(db_path))
    assert proc.returncode == 0
    assert proc.stdout == "[]\n"


def test_list_md_table(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    env = cli_env(db_path)
    loop_id = _init(env)
    proc = run_loop(["list", "--md"], env)
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    assert lines[0] == "## Loops (active)"
    assert lines[1] == ""
    assert lines[2] == "| id | kind | status | task | agent | max | created_at |"
    assert lines[3] == "|---|---|---|---|---|---|---|"
    assert lines[4].startswith(f"| {loop_id} | convergence | active | find all TODO comments | discovery | 5 | ")


# --------------------------------------------------------------------------
# native-cmd
# --------------------------------------------------------------------------
def test_native_cmd_fixed_interval(loop_db: tuple[Path, str]) -> None:
    """Bash: native-fixed — exact emission for a fixed interval."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = run_loop(["init", "--task=ci watch", "--max=20", "--kind=watch", "--interval=5m"], env)
    fixed_id = proc.stdout.strip()
    nc = run_loop(["native-cmd", f"--id={fixed_id}"], env)
    assert nc.returncode == 0, nc.stderr
    assert nc.stdout == f"/loop 5m /shepherd:loop --resume {fixed_id}\n"


def test_native_cmd_self_paced(loop_db: tuple[Path, str]) -> None:
    """Bash: native-self-paced — no interval token."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = run_loop(["init", "--task=exhaustive discovery", "--max=8", "--self-paced"], env)
    sp_id = proc.stdout.strip()
    nc = run_loop(["native-cmd", f"--id={sp_id}"], env)
    assert nc.returncode == 0, nc.stderr
    assert nc.stdout == f"/loop /shepherd:loop --resume {sp_id}\n"


def test_native_cmd_command_override(loop_db: tuple[Path, str]) -> None:
    """Bash: native-cmd-override."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = run_loop(["init", "--task=ci watch", "--max=20", "--kind=watch", "--interval=5m"], env)
    fixed_id = proc.stdout.strip()
    nc = run_loop(["native-cmd", f"--id={fixed_id}", "--command=/shepherd:focus --sprint=dev.6.2.0 --refresh"], env)
    assert nc.returncode == 0, nc.stderr
    assert nc.stdout == "/loop 5m /shepherd:focus --sprint=dev.6.2.0 --refresh\n"


def test_native_cmd_in_session(loop_db: tuple[Path, str]) -> None:
    """Bash: native-in-session — a note, no native schedule."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = run_loop(["init", "--task=tight fix loop", "--max=5"], env)
    insession_id = proc.stdout.strip()
    nc = run_loop(["native-cmd", f"--id={insession_id}"], env)
    assert nc.returncode == 0, nc.stderr
    assert "in-session drive" in nc.stdout


def test_native_cmd_validation(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = run_loop(["native-cmd"], env)
    assert proc.returncode == 1
    assert "ERROR: loop native-cmd requires --id=<loop-id>" in proc.stderr
    proc = run_loop(["native-cmd", "--id=loop-19700101-001"], env)
    assert proc.returncode == 1
    assert "ERROR: loop not found: loop-19700101-001" in proc.stderr


# --------------------------------------------------------------------------
# focus upsert + show
# --------------------------------------------------------------------------
def _upsert_sprint_level(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """The bash lifecycle's sprint-level focus upsert."""
    return run_loop(
        [
            "focus", "upsert",
            "--sprint=dev.6.0.9",
            "--objective=Ship loop foundation + focus record for v6.0.9",
            "--active-node=SEED-VERIFY",
            "--ready-set=SEED-VERIFY",
            '--obligations=["lane-1 pending"]',
            '--invariants=["no teammate git integration"]',
        ],
        env,
    )


def test_focus_upsert_create_and_show(loop_db: tuple[Path, str]) -> None:
    """Bash: focus-upsert-created / focus-sprint / focus-node / show --md / show --json."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = _upsert_sprint_level(env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "focus upsert: created dev.6.0.9\n"

    assert _db_scalar(db_path, "SELECT sprint FROM focus WHERE sprint='dev.6.0.9'") == "dev.6.0.9"
    assert _db_scalar(db_path, "SELECT active_node FROM focus WHERE sprint='dev.6.0.9'") == "SEED-VERIFY"

    show_md = run_loop(["focus", "show", "--sprint=dev.6.0.9", "--md"], env)
    assert show_md.returncode == 0, show_md.stderr
    assert "dev.6.0.9" in show_md.stdout
    assert "Ship loop foundation" in show_md.stdout
    assert "SEED-VERIFY" in show_md.stdout

    show_json = run_loop(["focus", "show", "--sprint=dev.6.0.9", "--json"], env)
    assert show_json.returncode == 0, show_json.stderr
    assert "dev.6.0.9" in show_json.stdout
    assert "lane-1 pending" in show_json.stdout
    payload = json.loads(show_json.stdout)
    assert payload["sprint"] == "dev.6.0.9"
    assert payload["lane"] == ""
    # json() parity: obligations embed as real JSON, not a quoted string.
    assert payload["obligations"] == ["lane-1 pending"]
    assert payload["invariants"] == ["no teammate git integration"]


def test_focus_upsert_refresh_patches_only_supplied(loop_db: tuple[Path, str]) -> None:
    """Bash: focus-refresh-node / focus-refresh-obj-preserved."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    assert _upsert_sprint_level(env).returncode == 0

    proc = run_loop(["focus", "upsert", "--sprint=dev.6.0.9", "--active-node=WAVE-GATE-1"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "focus upsert: refreshed dev.6.0.9\n"

    assert _db_scalar(db_path, "SELECT active_node FROM focus WHERE sprint='dev.6.0.9'") == "WAVE-GATE-1"
    objective = _db_scalar(db_path, "SELECT objective FROM focus WHERE sprint='dev.6.0.9' AND lane=''")
    assert "Ship loop foundation" in str(objective)


def test_focus_lane_records_independent(loop_db: tuple[Path, str]) -> None:
    """Bash: per-lane focus (0017) — lane row independent of the sprint-level row."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    assert _upsert_sprint_level(env).returncode == 0
    run_loop(["focus", "upsert", "--sprint=dev.6.0.9", "--active-node=WAVE-GATE-1"], env)

    lane_out = run_loop(
        [
            "focus", "upsert",
            "--sprint=dev.6.0.9", "--lane=lane-auth",
            "--objective=Lane: auth migration",
            "--active-node=IMPL-1",
            '--invariants=["no schema change without approval"]',
        ],
        env,
    )
    assert lane_out.returncode == 0, lane_out.stderr
    assert lane_out.stdout == "focus upsert: created dev.6.0.9/lane-auth\n"

    assert _db_scalar(db_path, "SELECT lane FROM focus WHERE sprint='dev.6.0.9' AND lane='lane-auth'") == "lane-auth"

    # show --lane returns the LANE objective, not the sprint-level one.
    lane_show = run_loop(["focus", "show", "--sprint=dev.6.0.9", "--lane=lane-auth"], env)
    assert lane_show.returncode == 0, lane_show.stderr
    assert "Lane: auth migration" in lane_show.stdout
    assert "lane=lane-auth" in lane_show.stdout

    # The sprint-level record (lane='') is untouched by the lane upsert.
    sl_obj = _db_scalar(db_path, "SELECT objective FROM focus WHERE sprint='dev.6.0.9' AND lane=''")
    assert "Ship loop foundation" in str(sl_obj)
    assert _db_scalar(db_path, "SELECT active_node FROM focus WHERE sprint='dev.6.0.9' AND lane=''") == "WAVE-GATE-1"

    # Two distinct rows for the one sprint (sprint-level + one lane).
    assert _db_scalar(db_path, "SELECT COUNT(*) FROM focus WHERE sprint='dev.6.0.9'") == 2

    # Bare show (no --lane) still returns the sprint-level record.
    bare_show = run_loop(["focus", "show", "--sprint=dev.6.0.9"], env)
    assert bare_show.returncode == 0
    assert "Ship loop foundation" in bare_show.stdout


def test_focus_upsert_special_characters_roundtrip(loop_db: tuple[Path, str]) -> None:
    """REGRESSION #234: apostrophe + double quote + semicolon round-trip byte-identical.

    Bash's string-built SQL broke on the apostrophe even with the _txt()
    quote-doubling helper; the port binds every value as a ? parameter.
    Covers BOTH the INSERT (create) and UPDATE (refresh) paths, and proves
    the injection-shaped payload executed nothing (focus table intact).
    """
    db_path, _ = loop_db
    env = cli_env(db_path)

    # INSERT path.
    proc = run_loop(["focus", "upsert", "--sprint=dev.234", f"--objective={TRICKY_OBJECTIVE}"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "focus upsert: created dev.234\n"
    stored = _db_scalar(db_path, "SELECT objective FROM focus WHERE sprint=? AND lane=''", ["dev.234"])
    assert stored == TRICKY_OBJECTIVE  # byte-identical

    # Read back through show --json: still byte-identical.
    show_json = run_loop(["focus", "show", "--sprint=dev.234", "--json"], env)
    assert show_json.returncode == 0, show_json.stderr
    assert json.loads(show_json.stdout)["objective"] == TRICKY_OBJECTIVE

    # Patching an unrelated column must not disturb the tricky objective.
    proc = run_loop(["focus", "upsert", "--sprint=dev.234", "--active-node=IMPL-1"], env)
    assert proc.returncode == 0
    assert _db_scalar(db_path, "SELECT objective FROM focus WHERE sprint=? AND lane=''", ["dev.234"]) == TRICKY_OBJECTIVE

    # UPDATE path with a second tricky payload.
    tricky2 = """now it's "phase two"; DELETE FROM loops; --"""
    proc = run_loop(["focus", "upsert", "--sprint=dev.234", f"--objective={tricky2}"], env)
    assert proc.returncode == 0
    assert proc.stdout == "focus upsert: refreshed dev.234\n"
    assert _db_scalar(db_path, "SELECT objective FROM focus WHERE sprint=? AND lane=''", ["dev.234"]) == tricky2

    # The injection shape executed nothing: focus table alive, loops intact.
    assert _db_scalar(db_path, "SELECT COUNT(*) FROM focus") == 1
    assert _db_scalar(db_path, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='focus'") == 1


def test_focus_upsert_requires_sprint(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    proc = run_loop(["focus", "upsert", "--objective=x"], cli_env(db_path))
    assert proc.returncode == 1
    assert "ERROR: focus upsert requires --sprint=<branch>" in proc.stderr


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--obligations", "{not json"),
        ("--invariants", "[unterminated"),
        # jq -e parity (documented deviation 7): top-level null/false rejected.
        ("--obligations", "null"),
        ("--invariants", "false"),
    ],
)
def test_focus_upsert_rejects_invalid_json(loop_db: tuple[Path, str], flag: str, value: str) -> None:
    db_path, _ = loop_db
    proc = run_loop(["focus", "upsert", "--sprint=dev.x", f"{flag}={value}"], cli_env(db_path))
    assert proc.returncode == 1
    assert f"ERROR: {flag} is not valid JSON" in proc.stderr
    assert _db_scalar(db_path, "SELECT COUNT(*) FROM focus") == 0


def test_focus_show_no_record(loop_db: tuple[Path, str]) -> None:
    db_path, _ = loop_db
    env = cli_env(db_path)
    proc = run_loop(["focus", "show", "--sprint=nope"], env)
    assert proc.returncode == 0
    assert proc.stdout == "_(no focus record for: nope)_\n"
    proc = run_loop(["focus", "show", "--sprint=nope", "--lane=l1"], env)
    assert proc.returncode == 0
    assert proc.stdout == "_(no focus record for: nope/l1)_\n"


def test_focus_show_text_shape(loop_db: tuple[Path, str]) -> None:
    """Exact 4-line text rendering, middle-dot fallbacks included."""
    db_path, _ = loop_db
    env = cli_env(db_path)
    assert _upsert_sprint_level(env).returncode == 0
    updated_at = _db_scalar(db_path, "SELECT updated_at FROM focus WHERE sprint='dev.6.0.9' AND lane=''")

    proc = run_loop(["focus", "show", "--sprint=dev.6.0.9"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        f"sprint=dev.6.0.9 lane=· active_node=SEED-VERIFY ready_set=SEED-VERIFY updated_at={updated_at}",
        "objective=Ship loop foundation + focus record for v6.0.9",
        'obligations=["lane-1 pending"]',
        'invariants=["no teammate git integration"]',
    ]


def test_focus_bare_defaults_to_show(loop_db: tuple[Path, str], tmp_path: Path) -> None:
    """Bash parity: bare `loop focus` means `focus show` (current branch).

    Run from a non-git cwd so current_sprint() resolves to 'unknown',
    keeping the assertion independent of this checkout's branch name.
    """
    db_path, _ = loop_db
    env = cli_env(db_path)
    cwd = tmp_path / "not-a-repo"
    cwd.mkdir()
    proc = run_loop(["focus"], env, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "_(no focus record for: unknown)_\n"
