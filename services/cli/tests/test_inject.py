"""Subprocess parity tests for ``shepherd inject`` (role-tailored [DB-CONTEXT] block).

Bash parity target: ``skills/context/scripts/cmd_inject.sh``; every
load-bearing assertion from ``skills/context/tests/test_inject.sh`` is
migrated here (each role emits ``[DB-CONTEXT]``/``[/DB-CONTEXT]``), plus
coverage for the per-role bodies, caps, scope filtering, failure
fallbacks, and the deliberate issue-#243 section reordering the module
docstring documents (stable content first, volatile last, priors LAST).

INVOCATION NOTE: ``inject`` is not yet registered in
``shepherd_cli.app``/``__main__.PORTED``, so ``run_cli(["inject", ...])``
would fall through to the bash shim. Every test drives the module's own
Typer app directly in a fresh subprocess — an invocation that works both
before AND after registration.

ENVIRONMENT NOTE (same shape as ``tests/test_query.py``): inject's
engineer/coder/auditor/planter bodies are assembled from in-process
``shepherd query`` invocations, and ``shctx query``'s project-id
resolution reads a ``project.json`` FILE in the resolved work directory
— NOT the ``projects`` table. So every test sets ``SHEPHERD_WORKDIR`` to
an isolated tmp dir holding a ``project.json`` whose id matches the
fixture DB's seeded ``projects.id`` row, while ``SHCTX_DB`` points at
the fixture DB itself. The adapt-backed tail sections (priors,
recommendation) resolve their project via the ``projects`` table like
every other ported command.
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
# Module-app invocation + fixture helpers.
# --------------------------------------------------------------------------
_INJECT_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.inject import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd inject')\n"
)


def run_inject(
    args: Sequence[str],
    env: dict[str, str],
    *,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    """Run the inject module app as a real subprocess (see module docstring)."""
    return subprocess.run(
        [PY, "-c", _INJECT_SNIPPET, *args],
        env=env,
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def inject_env(
    db_path: Path,
    workdir: Path,
    *,
    project_id: str = "proj-test",
    write_project_json: bool = True,
) -> dict[str, str]:
    """Environment for driving inject: SHCTX_DB + a workdir with project.json.

    Args:
        db_path: The fixture DB (drives ``SHCTX_DB`` via ``cli_env``).
        workdir: Isolated tmp shepherd work directory
            (``SHEPHERD_WORKDIR``) — where the query sub-invocations read
            ``project.json`` from.
        project_id: The id written into ``project.json`` (must match the
            DB's seeded ``projects.id`` row for the queries to scope).
        write_project_json: False drives the query-failure paths (the
            bash "gh unavailable"/fatal branches).

    Returns:
        A full subprocess environment.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if write_project_json:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def _seed(db_path: Path, sql: str, params: Sequence[object]) -> None:
    """Execute one seed statement against the fixture DB."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def seed_symbol(db_path: Path, symbol_id: str, name: str, package: str, file_path: str) -> None:
    """Insert one pub struct symbol (a v_canonical_types row)."""
    _seed(
        db_path,
        "INSERT INTO index_symbols (id, project_id, name, kind, package, file_path, line, visibility, signature, language, hash, refreshed_at)"
        " VALUES (?, 'proj-test', ?, 'struct', ?, ?, 10, 'pub', ?, 'rust', ?, ?)",
        (symbol_id, name, package, file_path, f"struct {name}", f"hash-{symbol_id}", int(time.time())),
    )


def seed_open_issue(db_path: Path, issue_id: str, number: int, title: str, labels: str = '["high"]') -> None:
    """Insert one open issue (rows for v_open_issues AND v_drift_risk when labeled high)."""
    now = int(time.time())
    _seed(
        db_path,
        "INSERT INTO index_issues (id, project_id, source, number, title, state, labels, url, created_at, updated_at, refreshed_at)"
        " VALUES (?, 'proj-test', 'gh', ?, ?, 'open', ?, 'http://issue', ?, ?, ?)",
        (issue_id, number, title, labels, now, now, now),
    )


def seed_open_pr(db_path: Path, pr_id: str, number: int, title: str) -> None:
    """Insert one open PR (an index_prs row the open-prs query returns)."""
    now = int(time.time())
    _seed(
        db_path,
        "INSERT INTO index_prs (id, project_id, source, number, title, state, base_branch, head_branch, url, created_at, updated_at, refreshed_at)"
        " VALUES (?, 'proj-test', 'gh', ?, ?, 'open', 'main', 'dev', 'http://pr', ?, ?, ?)",
        (pr_id, number, title, now, now, now),
    )


def seed_prior(db_path: Path, entry_id: str, title: str, body: str, tag: str) -> None:
    """Insert one mem_entries(kind='prior') lesson (the priors tail's input)."""
    now = int(time.time())
    _seed(
        db_path,
        "INSERT INTO mem_entries (id, project_id, kind, title, body, tags, pinned, created_at, updated_at)"
        " VALUES (?, 'proj-test', 'prior', ?, ?, ?, 0, ?, ?)",
        (entry_id, title, body, json.dumps([tag]), now, now),
    )


def seed_sprint_metrics(db_path: Path, sprint: str, lanes: int = 4, wall: float = 70.0, api: int = 150) -> None:
    """Insert one sprint_metrics close (makes the recommendation tail fire)."""
    _seed(
        db_path,
        "INSERT INTO sprint_metrics (project_id, sprint_branch, grade, lane_count, wall_minutes, api_calls, created_at)"
        " VALUES ('proj-test', ?, 'B', ?, ?, ?, ?)",
        (sprint, lanes, wall, api, int(time.time())),
    )


@pytest.fixture
def inject_db(tmp_path: Path) -> Path:
    """A full-schema DB with a project + symbols/issue/PR the queries return."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path)  # project_id="proj-test"
    seed_symbol(db_path, "sym-1", "FooType", "crates/store", "crates/store/src/lib.rs")
    seed_symbol(db_path, "sym-2", "BarType", "crates/web", "crates/web/src/lib.rs")
    seed_open_issue(db_path, "iss-1", 7, "fix the thing")
    seed_open_pr(db_path, "pr-1", 9, "a pr")
    return db_path


# --------------------------------------------------------------------------
# test_inject.sh parity: every role emits the block.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["engineer", "coder", "auditor", "planter"])
def test_role_emits_db_context_block(role: str, inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject([role], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "[DB-CONTEXT]" in proc.stdout
    assert "[/DB-CONTEXT]" in proc.stdout
    # The block is the whole output: opener first line, closer last line.
    lines = proc.stdout.splitlines()
    assert lines[0] == "[DB-CONTEXT]"
    assert lines[-1] == "[/DB-CONTEXT]"


def test_missing_role_prints_usage_exit_1(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject([], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: usage: shctx inject <engineer|coder|auditor|planter>" in proc.stderr


def test_unknown_role_exit_1(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject(["bogus"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 1
    assert "ERROR: unknown role: bogus" in proc.stderr


def test_unknown_flags_silently_ignored(inject_db: Path, tmp_path: Path) -> None:
    # Bash parity: the flag loop has no `*)` error arm — junk tokens after the
    # role are ignored and the block still renders.
    proc = run_inject(["auditor", "--not-a-flag", "stray"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "[DB-CONTEXT]" in proc.stdout


def test_limit_non_numeric_errors(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject(["coder", "--limit=lots"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 1
    assert "ERROR: --limit must be numeric (got 'lots')" in proc.stderr


# --------------------------------------------------------------------------
# Engineer: full surface, #243 ordering, cache-tail discipline.
# --------------------------------------------------------------------------
def test_engineer_sections_present_and_stable_head_first(inject_db: Path, tmp_path: Path) -> None:
    # Issue #243 reorder (documented module deviation #1): canonical types
    # (stable) FIRST, drift risk next, open issues (volatile) LAST in the head.
    proc = run_inject(["engineer"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "## Canonical types (top 80)" in out  # engineer default limit
    assert "FooType" in out
    assert "fix the thing" in out
    types_at = out.index("## Canonical types")
    drift_at = out.index("## Drift risk")
    issues_at = out.index("## Open issues")
    assert types_at < drift_at < issues_at


def test_engineer_tail_recommendation_then_priors_last(inject_db: Path, tmp_path: Path) -> None:
    seed_prior(inject_db, "p-1", "prior: duplication", "[high] sprint t: dup", "duplication")
    seed_sprint_metrics(inject_db, "t")
    proc = run_inject(["engineer"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    issues_at = out.index("## Open issues")
    rec_at = out.index("### Dispatch recommendation")
    priors_at = out.index("### Priors / lessons carried forward")
    closer_at = out.index("[/DB-CONTEXT]")
    # Volatile head last section < semi-stable recommendation < priors LAST.
    assert issues_at < rec_at < priors_at < closer_at


def test_engineer_omits_empty_tail_sections(inject_db: Path, tmp_path: Path) -> None:
    # Cold store: priors empty AND recommend prints its "no history yet" note —
    # both sections must be omitted (bash's omit-if-empty / case guard).
    proc = run_inject(["engineer"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "### Priors / lessons carried forward" not in proc.stdout
    assert "### Dispatch recommendation" not in proc.stdout
    assert "no history yet" not in proc.stdout


def test_engineer_full_removes_cap(inject_db: Path, tmp_path: Path) -> None:
    # --full sets limit=0 (no cap) — and the header prints "top 0", a bash
    # quirk kept verbatim.
    proc = run_inject(["engineer", "--full"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "## Canonical types (top 0)" in proc.stdout
    assert "FooType" in proc.stdout
    assert "BarType" in proc.stdout


def test_engineer_fails_when_canonical_types_query_fails(inject_db: Path, tmp_path: Path) -> None:
    # Bash parity: issues/drift have `|| echo` cushions, but the types capture
    # does NOT — a failing canonical-types query aborts inject (set -e).
    # No project.json in the workdir makes every query sub-invocation fail.
    env = inject_env(inject_db, tmp_path / "wd", write_project_json=False)
    proc = run_inject(["engineer"], env)
    assert proc.returncode == 1
    assert "[DB-CONTEXT]" not in proc.stdout


# --------------------------------------------------------------------------
# Coder: file-scope-filtered canonical types.
# --------------------------------------------------------------------------
def test_coder_scope_filters_lines(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject(["coder", "--scope=crates/store"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "## Existing canonical types in scope `crates/store` — REUSE; do not duplicate" in proc.stdout
    assert "FooType" in proc.stdout
    assert "BarType" not in proc.stdout


def test_coder_no_scope_uses_default_header_and_limit(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject(["coder"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "## Existing canonical types (top 30) — REUSE; do not duplicate" in proc.stdout
    assert "FooType" in proc.stdout
    assert "BarType" in proc.stdout


def test_coder_scope_without_matches_prints_fallback(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject(["coder", "--scope=no/such/path"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "_(no matches; coder should read canonical-types.md catalog directly)_" in proc.stdout


def test_coder_limit_caps_lines(inject_db: Path, tmp_path: Path) -> None:
    # --limit=1 keeps only the first line of the canonical-types markdown
    # (its header row) — head -n semantics, applied before the fallback check.
    proc = run_inject(["coder", "--limit=1"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "## Existing canonical types (top 1) — REUSE; do not duplicate" in proc.stdout
    assert "FooType" not in proc.stdout
    assert "BarType" not in proc.stdout


# --------------------------------------------------------------------------
# Auditor: cross-cutting state only, cushioned fallbacks.
# --------------------------------------------------------------------------
def test_auditor_sections(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject(["auditor"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "## Open issues (cross-cutting)" in out
    assert "## Open PRs" in out
    assert "fix the thing" in out
    assert "a pr" in out
    assert out.index("## Open issues (cross-cutting)") < out.index("## Open PRs")


def test_auditor_query_failure_falls_back_to_none_markers(inject_db: Path, tmp_path: Path) -> None:
    # Bash parity: both auditor sections carry `|| echo "_(none)_"` cushions,
    # so a failing query still emits the block with exit 0 — unlike engineer.
    env = inject_env(inject_db, tmp_path / "wd", write_project_json=False)
    proc = run_inject(["auditor"], env)
    assert proc.returncode == 0, proc.stderr
    assert "[DB-CONTEXT]" in proc.stdout
    assert proc.stdout.count("_(none)_") == 2


# --------------------------------------------------------------------------
# Planter: seed-author surface, priors tail.
# --------------------------------------------------------------------------
def test_planter_drift_before_issues_priors_last(inject_db: Path, tmp_path: Path) -> None:
    # #243 reorder (module deviation #1): drift risk before open issues;
    # the priors tail stays LAST.
    seed_prior(inject_db, "p-1", "prior: duplication", "[high] sprint t: dup", "duplication")
    proc = run_inject(["planter"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    drift_at = out.index("## Drift risk")
    issues_at = out.index("## Open issues")
    priors_at = out.index("### Priors / lessons carried forward")
    assert drift_at < issues_at < priors_at < out.index("[/DB-CONTEXT]")


def test_planter_omits_priors_when_store_empty(inject_db: Path, tmp_path: Path) -> None:
    proc = run_inject(["planter"], inject_env(inject_db, tmp_path / "wd"))
    assert proc.returncode == 0, proc.stderr
    assert "### Priors / lessons carried forward" not in proc.stdout
