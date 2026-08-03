"""Subprocess parity tests for ``shepherd adapt`` (adaptation loop).

Bash parity target: ``skills/context/scripts/cmd_adapt.sh``; every
load-bearing assertion from ``skills/context/tests/test_cmd_adapt.sh``
and ``skills/context/tests/test_compile_telemetry.sh`` is migrated here.

INVOCATION NOTE: ``adapt`` is not yet registered in
``shepherd_cli.app``/``__main__.PORTED``, so ``run_cli(["adapt", ...])``
would fall through to the bash shim. Every test therefore drives the
module's own Typer app directly in a fresh subprocess (``${PY} -c
"...adapt import app; app(...)"``) — an invocation that works both
before AND after registration, so these tests need no edits when the
integrator flips the sub-app on.

Fixture DBs are the shared full-schema builders from
:mod:`tests.conftest`; rows are seeded via raw stdlib ``sqlite3``
(``audit_findings``/``mem_entries``/``sprint_metrics``/``compile_runs``
— the same on-disk shape bash's own tooling writes), rather than by
driving the ``audit``/``mem`` command groups, so a regression in a
sibling port cannot masquerade as an ``adapt`` failure.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import CLI_ROOT, PY, build_full_schema_db, cli_env, insert_project

# --------------------------------------------------------------------------
# Module-app invocation + raw-sqlite3 seed helpers.
# --------------------------------------------------------------------------
_ADAPT_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.adapt import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd adapt')\n"
)


def run_adapt(
    args: Sequence[str],
    env: dict[str, str],
    *,
    cwd: Path | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Run the adapt module app as a real subprocess (see module docstring)."""
    return subprocess.run(
        [PY, "-c", _ADAPT_SNIPPET, *args],
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


def seed_finding(
    db_path: Path,
    sprint: str,
    concern: str,
    severity: str,
    finding: str,
    *,
    project_id: str = "proj-test",
) -> None:
    """Insert one audit_findings row (the roll harvest's input)."""
    now = int(time.time())
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO audit_findings (project_id, sprint_branch, concern, severity, hypothesis, finding, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, sprint, concern, severity, "test hypothesis", finding, now),
        )
        conn.commit()
    finally:
        conn.close()


def seed_prior(
    db_path: Path,
    entry_id: str,
    title: str,
    tag: str,
    *,
    pinned: int = 0,
    created_at: int = 1,
    updated_at: int = 1,
    body: str = "old",
    project_id: str = "proj-test",
) -> None:
    """Insert one mem_entries(kind='prior') row directly (decay/dedup fixtures)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO mem_entries (id, project_id, kind, title, body, tags, pinned, created_at, updated_at)"
            " VALUES (?, ?, 'prior', ?, ?, ?, ?, ?, ?)",
            (entry_id, project_id, title, body, json.dumps([tag]), pinned, created_at, updated_at),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def adapt_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with one registered project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path)  # project_id="proj-test"
    return db_path


def _roll(env: dict[str, str], sprint: str, *flags: str) -> subprocess.CompletedProcess[str]:
    """Run ``adapt roll --sprint=<sprint> <flags>`` and assert it succeeded."""
    proc = run_adapt(["roll", f"--sprint={sprint}", *flags], env)
    assert proc.returncode == 0, proc.stderr
    return proc


def _seed_three_sprint_history(
    db_path: Path,
    env: dict[str, str],
    *,
    grades: tuple[str, str, str] = ("A", "B", "C"),
    walls: tuple[str, str, str] = ("60", "90", "140"),
    apis: tuple[str, str, str] = ("100", "150", "260"),
    concern: str = "duplication",
) -> None:
    """Three closes with a recurring HIGH concern (the §VI trends fixture)."""
    for sprint, grade, wall, api in zip(("s1", "s2", "s3"), grades, walls, apis, strict=True):
        seed_finding(db_path, sprint, concern, "high", "recurs")
        _roll(env, sprint, f"--grade={grade}", "--lanes=4", f"--wall-min={wall}", f"--api={api}")


# --------------------------------------------------------------------------
# Bare invocation + prerequisite gate.
# --------------------------------------------------------------------------
def test_bare_invocation_prints_usage_exit_0(adapt_db: Path) -> None:
    # Bash parity: `case "$sub" in ""|-h|--help) usage; exit 0` — stdout, exit 0.
    proc = run_adapt([], cli_env(adapt_db))
    assert proc.returncode == 0
    assert "shctx adapt <roll|priors|report|recommend>" in proc.stdout
    assert proc.stderr == ""


def test_no_project_registered_exits_1(tmp_path: Path) -> None:
    # Bash parity: pid=$(shctx_project_id) runs before EVERY subcommand under
    # set -e, so a missing project aborts even a read-only `priors` with exit 1.
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)  # schema, but NO projects row
    proc = run_adapt(["priors", "--metrics"], cli_env(db_path))
    assert proc.returncode == 1
    assert "ERROR: no project registered" in proc.stderr


# --------------------------------------------------------------------------
# roll — metrics row + harvest + decay.
# --------------------------------------------------------------------------
def test_roll_requires_sprint(adapt_db: Path) -> None:
    proc = run_adapt(["roll"], cli_env(adapt_db))
    assert proc.returncode == 1
    assert "ERROR: adapt roll requires --sprint=<branch>" in proc.stderr


def test_roll_writes_metrics_row_and_harvests_high_critical(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    seed_finding(adapt_db, "test", "duplication", "high", "duplicated helper across two lanes")
    seed_finding(adapt_db, "test", "injection", "critical", "user string reached the sql string")
    seed_finding(adapt_db, "test", "style", "low", "trailing whitespace")

    proc = _roll(env, "test", "--grade=B", "--lanes=4", "--waves=2", "--wall-min=70", "--api=150")
    assert "adapt roll" in proc.stdout
    assert "2 prior(s) harvested" in proc.stdout

    assert _db_scalar(adapt_db, "SELECT count(*) FROM sprint_metrics WHERE sprint_branch='test'") == 1
    assert _db_scalar(adapt_db, "SELECT lane_count FROM sprint_metrics WHERE sprint_branch='test'") == 4
    assert _db_scalar(adapt_db, "SELECT CAST(wall_minutes AS INTEGER) FROM sprint_metrics WHERE sprint_branch='test'") == 70
    assert _db_scalar(adapt_db, "SELECT findings_json FROM sprint_metrics WHERE sprint_branch='test'") == '{"high":1,"critical":1}'
    assert _db_scalar(adapt_db, "SELECT n FROM v_sprint_metrics_avg") == 1

    # Exactly the two high/critical findings became priors; low is skipped.
    titles = {row[0] for row in _db_rows(adapt_db, "SELECT title FROM mem_entries WHERE kind='prior'")}
    assert titles == {"prior: duplication", "prior: injection"}


def test_roll_is_idempotent_and_dedupes_priors(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    seed_finding(adapt_db, "test", "duplication", "high", "dup")
    seed_finding(adapt_db, "test", "injection", "critical", "inj")
    _roll(env, "test", "--grade=B", "--lanes=4", "--wall-min=70", "--api=150")
    _roll(env, "test", "--grade=A", "--lanes=5", "--wall-min=80", "--api=160")

    assert _db_scalar(adapt_db, "SELECT count(*) FROM sprint_metrics WHERE sprint_branch='test'") == 1
    assert _db_scalar(adapt_db, "SELECT grade FROM sprint_metrics WHERE sprint_branch='test'") == "A"
    assert _db_scalar(adapt_db, "SELECT count(*) FROM mem_entries WHERE kind='prior'") == 2


def test_roll_recurrence_refreshes_prior_last_seen(adapt_db: Path) -> None:
    # v6.0.8: a recurring concern touches the existing prior's updated_at
    # (last-seen) instead of inserting a duplicate — decay's collision-proofing.
    env = cli_env(adapt_db)
    seed_prior(adapt_db, "old-prior-1", "prior: duplication", "duplication", updated_at=1)
    seed_finding(adapt_db, "test", "duplication", "high", "recurs")
    _roll(env, "test", "--grade=B")

    assert _db_scalar(adapt_db, "SELECT count(*) FROM mem_entries WHERE title='prior: duplication'") == 1
    updated_at = _db_scalar(adapt_db, "SELECT updated_at FROM mem_entries WHERE id='old-prior-1'")
    assert isinstance(updated_at, int) and updated_at > 1


def test_roll_rejects_non_numeric_flag(adapt_db: Path) -> None:
    proc = run_adapt(["roll", "--sprint=test", "--lanes=abc"], cli_env(adapt_db))
    assert proc.returncode == 1
    assert "ERROR: --lanes must be numeric (got 'abc')" in proc.stderr
    proc2 = run_adapt(["roll", "--sprint=test", "--wall-min=1.2.3"], cli_env(adapt_db))
    assert proc2.returncode == 1
    assert "ERROR: --wall-min must be numeric (got '1.2.3')" in proc2.stderr


def test_roll_without_wall_min_writes_null(adapt_db: Path) -> None:
    # wall-min is explicit-only: absent -> NULL so the cost trend stays dormant.
    env = cli_env(adapt_db)
    proc = _roll(env, "nowall", "--grade=B", "--lanes=2")
    assert "adapt roll" in proc.stdout
    assert _db_scalar(adapt_db, "SELECT count(*) FROM sprint_metrics WHERE sprint_branch='nowall'") == 1
    assert _db_scalar(adapt_db, "SELECT wall_minutes IS NULL FROM sprint_metrics WHERE sprint_branch='nowall'") == 1


def test_roll_decay_prunes_stale_unpinned_keeps_pinned(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    _roll(env, "s1", "--grade=A")
    _roll(env, "s2", "--grade=B")
    seed_prior(adapt_db, "stale-0001", "prior: stale-concern", "stale-concern", pinned=0, updated_at=1)
    seed_prior(adapt_db, "pinned-0001", "prior: pinned-concern", "pinned-concern", pinned=1, updated_at=1)

    env_decay = dict(env)
    env_decay["SHCTX_ADAPT_DECAY_SPRINTS"] = "1"
    proc = run_adapt(["roll", "--sprint=s3", "--grade=C", "--wall-min=140", "--api=260"], env_decay)
    assert proc.returncode == 0, proc.stderr
    assert "1 stale prior(s) pruned" in proc.stdout

    assert _db_scalar(adapt_db, "SELECT count(*) FROM mem_entries WHERE id='stale-0001'") == 0
    assert _db_scalar(adapt_db, "SELECT count(*) FROM mem_entries WHERE id='pinned-0001'") == 1


def test_roll_decay_graceful_below_two_closes(adapt_db: Path) -> None:
    # <2 recorded closes: no cadence to measure -> nothing pruned even with
    # an aggressive window (bash's `nsprints >= 2` guard).
    env = dict(cli_env(adapt_db))
    env["SHCTX_ADAPT_DECAY_SPRINTS"] = "0"
    seed_prior(adapt_db, "stale-0001", "prior: stale-concern", "stale-concern", updated_at=1)
    proc = run_adapt(["roll", "--sprint=first"], env)
    assert proc.returncode == 0, proc.stderr
    assert "0 stale prior(s) pruned" in proc.stdout
    assert _db_scalar(adapt_db, "SELECT count(*) FROM mem_entries WHERE id='stale-0001'") == 1


# --------------------------------------------------------------------------
# priors — metrics averages + lessons feed.
# --------------------------------------------------------------------------
def test_priors_metrics_empty_emits_nothing(adapt_db: Path) -> None:
    proc = run_adapt(["priors", "--metrics"], cli_env(adapt_db))
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_priors_metrics_json_and_text_after_roll(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    _roll(env, "test", "--grade=B", "--lanes=4", "--wall-min=70", "--api=150")

    proc = run_adapt(["priors", "--metrics", "--json"], env)
    assert proc.returncode == 0
    assert "avg_sprint_minutes" in proc.stdout
    assert "avg_api_per_sprint" in proc.stdout
    # jq-parity number rendering: an integral average prints bare (70, not 70.0).
    assert proc.stdout.strip() == '{"n":1,"avg_sprint_minutes":70,"avg_api_per_sprint":150,"avg_lane_count":4,"avg_loc_delta":0}'

    proc_text = run_adapt(["priors", "--metrics"], env)
    assert proc_text.returncode == 0
    assert "avg_sprint_minutes=" in proc_text.stdout
    # sqlite-CLI-parity number rendering in the text format (70.0, like bash).
    assert "avg_sprint_minutes=70.0" in proc_text.stdout


def test_priors_lessons_md_surfaces_harvested_priors(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    seed_finding(adapt_db, "test", "duplication", "high", "dup")
    _roll(env, "test")
    proc = run_adapt(["priors", "--lessons", "--md"], env)
    assert proc.returncode == 0
    assert "### Priors / lessons carried forward" in proc.stdout
    assert "prior:" in proc.stdout


def test_priors_lessons_empty_emits_nothing(adapt_db: Path) -> None:
    proc = run_adapt(["priors", "--lessons", "--md"], cli_env(adapt_db))
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_priors_all_json_shape(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    # Empty store: bash still prints the jq-assembled envelope.
    proc_empty = run_adapt(["priors", "--all", "--json"], env)
    assert proc_empty.returncode == 0
    assert proc_empty.stdout.strip() == '{"metrics":null,"lessons":[]}'

    seed_finding(adapt_db, "test", "duplication", "high", "dup")
    _roll(env, "test", "--lanes=4", "--wall-min=70", "--api=150")
    proc = run_adapt(["priors", "--all", "--json"], env)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["metrics"]["n"] == 1
    assert payload["lessons"][0]["title"] == "prior: duplication"
    assert payload["lessons"][0]["tags"] == ["duplication"]


# --------------------------------------------------------------------------
# reflect — one-line close reflection (Reflexion pattern).
# --------------------------------------------------------------------------
def test_reflect_stores_reflection_tagged_and_bodied(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    proc = run_adapt(["reflect", "--sprint=test", "--note=lanes were oversized for a docs sprint"], env)
    assert proc.returncode == 0, proc.stderr
    assert "stored reflection" in proc.stdout
    assert _db_scalar(adapt_db, "SELECT count(*) FROM mem_entries WHERE kind='prior' AND title LIKE 'prior: reflection%'") == 1
    assert _db_scalar(adapt_db, "SELECT json_extract(tags,'$[0]') FROM mem_entries WHERE title LIKE 'prior: reflection%'") == "reflection"
    body = _db_scalar(adapt_db, "SELECT body FROM mem_entries WHERE title LIKE 'prior: reflection%'")
    assert body == "[reflection] sprint test: lanes were oversized for a docs sprint"


def test_reflect_is_idempotent_per_sprint(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    run_adapt(["reflect", "--sprint=test", "--note=first lesson"], env)
    proc = run_adapt(["reflect", "--sprint=test", "--note=updated lesson"], env)
    assert proc.returncode == 0
    assert "updated reflection" in proc.stdout
    assert _db_scalar(adapt_db, "SELECT count(*) FROM mem_entries WHERE title LIKE 'prior: reflection%'") == 1
    body = _db_scalar(adapt_db, "SELECT body FROM mem_entries WHERE title LIKE 'prior: reflection%'")
    assert "updated lesson" in str(body)


def test_reflect_surfaces_in_lessons_feed(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    run_adapt(["reflect", "--sprint=test", "--note=a lesson"], env)
    proc = run_adapt(["priors", "--lessons", "--md"], env)
    assert proc.returncode == 0
    assert "reflection" in proc.stdout


def test_reflect_requires_note(adapt_db: Path) -> None:
    proc = run_adapt(["reflect", "--sprint=test"], cli_env(adapt_db))
    assert proc.returncode == 1
    assert "ERROR: adapt reflect requires --note=<lesson>" in proc.stderr


def test_reflect_requires_sprint(adapt_db: Path) -> None:
    proc = run_adapt(["reflect", "--note=x"], cli_env(adapt_db))
    assert proc.returncode == 1
    assert "ERROR: adapt reflect requires --sprint=<branch>" in proc.stderr


def test_reflect_pin_sets_and_is_preserved_on_replay(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    run_adapt(["reflect", "--sprint=pinsprint", "--note=keep me", "--pin"], env)
    assert _db_scalar(adapt_db, "SELECT pinned FROM mem_entries WHERE title='prior: reflection (pinsprint)'") == 1
    # Re-reflect WITHOUT --pin must PRESERVE the pin (no silent unpin footgun).
    run_adapt(["reflect", "--sprint=pinsprint", "--note=updated, still pinned"], env)
    assert _db_scalar(adapt_db, "SELECT pinned FROM mem_entries WHERE title='prior: reflection (pinsprint)'") == 1


# --------------------------------------------------------------------------
# report — sprint patterns + trends.
# --------------------------------------------------------------------------
def test_report_md_empty_store_message(adapt_db: Path) -> None:
    proc = run_adapt(["report", "--md"], cli_env(adapt_db))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "_(no sprint metrics recorded yet — first adaptation cycle lands at this sprint's close)_"


def test_report_md_renders_sprint_table(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    _roll(env, "test", "--grade=B", "--lanes=4", "--waves=2", "--wall-min=70", "--api=150")
    proc = run_adapt(["report", "--md"], env)
    assert proc.returncode == 0
    assert "## Sprint patterns" in proc.stdout
    assert "test" in proc.stdout
    assert "| test | B | · | 4 | 2 | 70 | 150 |" in proc.stdout
    assert "### Dispatch priors — measured (1 prior sprint(s))" in proc.stdout


def test_report_json(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    _roll(env, "test", "--grade=B", "--lanes=4", "--wall-min=70", "--api=150")
    proc = run_adapt(["report", "--json"], env)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload[0]["sprint"] == "test"
    assert payload[0]["grade"] == "B"
    assert payload[0]["lanes"] == 4
    assert payload[0]["findings"] == {"high": 0, "critical": 0}


def test_report_trends_insufficient_history_emits_nothing(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    _roll(env, "only-one", "--grade=A")
    proc = run_adapt(["report", "--trends"], env)
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_report_trends_fires_all_three_signals(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    _seed_three_sprint_history(adapt_db, env)

    proc = run_adapt(["report", "--trends"], env)
    assert proc.returncode == 0
    assert "TREND ALERT" in proc.stdout
    assert "duplication" in proc.stdout
    assert "trending DOWN" in proc.stdout
    assert "Cost rising sharply" in proc.stdout

    proc_json = run_adapt(["report", "--trends", "--json"], env)
    assert proc_json.returncode == 0
    assert '"grade_trending_down":true' in proc_json.stdout
    payload = json.loads(proc_json.stdout)
    assert payload == {
        "trend_alert": True,
        "recurring_concern": True,
        "concern": "duplication",
        "grade_trending_down": True,
        "cost_rising": True,
    }


def test_report_trends_exit0_when_only_concern_fires(adapt_db: Path) -> None:
    # v6.0.8 regression: a fired alert whose LAST signal is false must still
    # exit 0 (bash's trailing-`&&`-under-`set -e` hazard).
    env = cli_env(adapt_db)
    _seed_three_sprint_history(
        adapt_db, env,
        grades=("B", "B", "B"), walls=("60", "60", "60"), apis=("100", "100", "100"),
        concern="flaky",
    )
    proc = run_adapt(["report", "--trends"], env)
    assert proc.returncode == 0
    assert "TREND ALERT" in proc.stdout
    assert "flaky" in proc.stdout
    assert "trending DOWN" not in proc.stdout
    assert "Cost rising" not in proc.stdout


# --------------------------------------------------------------------------
# recommend — measured dispatch guidance.
# --------------------------------------------------------------------------
def test_recommend_empty_store_notes_no_history(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    proc = run_adapt(["recommend", "--md"], env)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "_(no history yet, use defaults)_"
    proc_json = run_adapt(["recommend", "--json"], env)
    assert proc_json.returncode == 0
    assert proc_json.stdout.strip() == '{"history":false,"note":"no history yet, use defaults"}'


def test_recommend_md_and_json_with_history(adapt_db: Path) -> None:
    env = cli_env(adapt_db)
    seed_finding(adapt_db, "test", "duplication", "high", "dup")
    _roll(env, "test", "--grade=B", "--lanes=4", "--wall-min=70", "--api=150")

    proc = run_adapt(["recommend", "--md"], env)
    assert proc.returncode == 0
    assert "suggested lanes" in proc.stdout
    assert "t-shirt band" in proc.stdout
    assert "- suggested lanes: 4 _(measured avg_lane_count 4.0)_" in proc.stdout
    assert "- t-shirt band: M _(measured avg 70 min/sprint)_" in proc.stdout
    assert "watch-concerns: duplication" in proc.stdout

    proc_json = run_adapt(["recommend", "--json"], env)
    assert proc_json.returncode == 0
    assert "suggested_lanes" in proc_json.stdout
    assert "size_band" in proc_json.stdout
    assert proc_json.stdout.strip() == '{"history":true,"n":1,"suggested_lanes":4,"size_band":"M","watch_concerns":"duplication"}'


def test_recommend_exit0_without_watch_concerns(adapt_db: Path) -> None:
    # v6.0.8 regression twin: history present, priors store empty — the final
    # optional line is skipped and the command must still exit 0.
    env = cli_env(adapt_db)
    _roll(env, "test", "--grade=B", "--lanes=4", "--wall-min=70", "--api=150")
    proc = run_adapt(["recommend", "--md"], env)
    assert proc.returncode == 0
    assert "suggested lanes" in proc.stdout
    assert "watch-concerns" not in proc.stdout


# --------------------------------------------------------------------------
# report --compile-telemetry (migration 0014; test_compile_telemetry.sh parity).
# --------------------------------------------------------------------------
def _git_repo_on_branch(path: Path, branch: str) -> Path:
    """Create a tmp git repo whose HEAD branch names the sprint under test.

    The compile-telemetry aggregator scopes rows by current_sprint()
    (``git rev-parse --abbrev-ref HEAD`` in the process cwd), so tests
    run the CLI from inside this repo instead of CLI_ROOT.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=path, check=True)
    return path


def _seed_compile_run(
    db_path: Path,
    run_id: str,
    sprint: str,
    segment: str,
    *,
    degraded: int = 0,
    degradation_cause: str | None = None,
    recovered: int | None = None,
    peak_concurrency: int = 5,
) -> None:
    """Insert one compile_runs row (mirrors test_compile_telemetry.sh's seeds)."""
    now = int(time.time())
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO compile_runs"
            " (project_id, run_id, sprint, segment, segment_node_count, total_agents,"
            "  peak_concurrency, concurrency_ceiling,"
            "  faithfulness_soundness, faithfulness_completeness, faithfulness_determinism,"
            "  faithfulness_ok, seam_export_present, seam_export_consumed,"
            "  degraded, degradation_cause, recovered,"
            "  script_sha256, compiled_at, run_started_at, run_finished_at)"
            " VALUES (?, ?, ?, ?, 3, 5, ?, 16, 'PASS', 'PASS', 'PASS', 1, 1, 1, ?, ?, ?, 'abc123', ?, ?, ?)",
            ("proj-test", run_id, sprint, segment, peak_concurrency, degraded, degradation_cause, recovered, now, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def test_compile_telemetry_md_and_json(adapt_db: Path, tmp_path: Path) -> None:
    sprint = "dev-tel-test"
    repo = _git_repo_on_branch(tmp_path / "repo", sprint)
    _seed_compile_run(adapt_db, "run-teltest-001", sprint, "CLOSE-SWARM")
    _seed_compile_run(
        adapt_db, "run-teltest-002", sprint, "WAVE-1-IMPL",
        degraded=1, degradation_cause="runtime_unavailable", recovered=1, peak_concurrency=0,
    )
    env = cli_env(adapt_db)

    proc = run_adapt(["report", "--compile-telemetry", "--md"], env, cwd=repo)
    assert proc.returncode == 0, proc.stderr
    assert "CLOSE-SWARM" in proc.stdout
    assert "WAVE-1-IMPL" in proc.stdout
    assert "Degradation events" in proc.stdout
    assert "runtime_unavailable" in proc.stdout
    assert "1/1 recovered" in proc.stdout
    assert "| 0 |" in proc.stdout  # the clean segment's zero degrade column

    proc_json = run_adapt(["report", "--compile-telemetry", "--json"], env, cwd=repo)
    assert proc_json.returncode == 0
    assert '"segment"' in proc_json.stdout
    assert '"degradation_events":1' in proc_json.stdout
    assert '"recovered_events":1' in proc_json.stdout
    assert '"runtime_unavailable"' in proc_json.stdout
    assert '"faithfulness_pass_rate"' in proc_json.stdout


def test_compile_telemetry_graceful_empty_sprint(adapt_db: Path, tmp_path: Path) -> None:
    # Rows exist for a DIFFERENT sprint; the current branch has none -> nothing.
    _seed_compile_run(adapt_db, "run-x", "some-other-sprint", "CLOSE-SWARM")
    repo = _git_repo_on_branch(tmp_path / "repo", "dev-empty-sprint")
    proc = run_adapt(["report", "--compile-telemetry", "--md"], cli_env(adapt_db), cwd=repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
