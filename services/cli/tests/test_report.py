"""Subprocess parity tests for ``shepherd report`` (discovery/audit/escalation/close/teammates).

Bash parity target: ``skills/context/scripts/cmd_report.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli report ...``),
exactly like ``test_deliverable.py`` — never by importing ``shepherd_cli``
into the pytest process — and seeds the ``discovery_findings``,
``audit_findings``, and ``escalations`` tables via raw ``sqlite3`` (schema-
tolerant via ``PRAGMA table_info``, mirroring ``conftest.insert_teammate``)
so these tests exercise the same on-disk shape the bash tooling itself
reads and writes. ``teammates`` rows are seeded via ``conftest.insert_teammate``
directly, reusing the existing fixture helper rather than reinventing it.

NOTE: this module is written against the ``report`` Typer sub-app before
the orchestrator wires it into ``shepherd_cli/app.py``'s ``PORTED`` set —
per the port contract, this file is syntax-checked (``python -m
py_compile``) but not run via pytest in this session; the orchestrator's
integration pass is what turns these into a green (or red, informatively)
suite.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from conftest import (
    TeammateRow,
    build_full_schema_db,
    cli_env,
    insert_project,
    insert_teammate,
    run_cli,
)

# --------------------------------------------------------------------------
# Fixture DB + raw-sqlite3 seed helpers (schema-tolerant, mirroring
# test_deliverable.py's insert_deliverable approach).
# --------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row; the report tables' FKs point into this."""
    return insert_project(db_path)


def insert_discovery_finding(
    db_path: Path,
    project_id: str,
    *,
    discovery_run: str,
    sprint_branch: str | None = None,
    section: str | None = None,
    title: str = "A finding",
    body: str = "Body text.",
    sources: str | None = None,
    created_at: int,
) -> int:
    """Insert one ``discovery_findings`` row directly via sqlite3.

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in ``projects.id``.
        discovery_run: The ``discovery_run`` column value.
        sprint_branch: The ``sprint_branch`` column value, or None.
        section: The ``section`` column value, or None.
        title: The ``title`` column value.
        body: The ``body`` column value.
        sources: The ``sources`` column value (JSON text), or None.
        created_at: Epoch-milliseconds for the ``created_at`` column
            (bash's ``cmd_discovery.sh`` writes ``$(($(date +%s) * 1000))``).

    Returns:
        The inserted row's autoincrement ``id``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(discovery_findings)")}
        fields = ["project_id", "sprint_branch", "discovery_run", "section", "title", "body", "sources", "created_at"]
        values: list[object] = [
            project_id, sprint_branch, discovery_run, section, title, body, sources, created_at,
        ]
        assert columns.issuperset(fields), f"discovery_findings missing expected columns: {fields}"
        placeholders = ", ".join("?" for _ in fields)
        cursor = conn.execute(
            f"INSERT INTO discovery_findings ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
        conn.commit()
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)
    finally:
        conn.close()


def insert_audit_finding(
    db_path: Path,
    project_id: str,
    *,
    sprint_branch: str,
    concern: str = "correctness",
    severity: str = "medium",
    hypothesis: str = "A hypothesis.",
    falsification: str | None = None,
    confidence: str | None = None,
    finding: str = "A finding.",
    gh_issue: int | None = None,
    created_at: int,
) -> int:
    """Insert one ``audit_findings`` row directly via sqlite3.

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in ``projects.id``.
        sprint_branch: The ``sprint_branch`` column value.
        concern: The ``concern`` column value.
        severity: The ``severity`` column value (one of the CHECK
            constraint's allowed values).
        hypothesis: The ``hypothesis`` column value.
        falsification: The ``falsification`` column value, or None.
        confidence: The ``confidence`` column value, or None.
        finding: The ``finding`` column value.
        gh_issue: The ``gh_issue`` column value, or None.
        created_at: Epoch-milliseconds for the ``created_at`` column.

    Returns:
        The inserted row's autoincrement ``id``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(audit_findings)")}
        fields = [
            "project_id", "sprint_branch", "concern", "severity", "hypothesis",
            "falsification", "confidence", "finding", "gh_issue", "created_at",
        ]
        values: list[object] = [
            project_id, sprint_branch, concern, severity, hypothesis,
            falsification, confidence, finding, gh_issue, created_at,
        ]
        assert columns.issuperset(fields), f"audit_findings missing expected columns: {fields}"
        placeholders = ", ".join("?" for _ in fields)
        cursor = conn.execute(
            f"INSERT INTO audit_findings ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
        conn.commit()
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)
    finally:
        conn.close()


def insert_escalation(
    db_path: Path,
    project_id: str,
    *,
    role: str = "engineer",
    phase: str | None = None,
    question: str = "What now?",
    raised_at: int,
    resolved_at: int | None = None,
) -> int:
    """Insert one ``escalations`` row directly via sqlite3.

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in ``projects.id``.
        role: The ``role`` column value.
        phase: The ``phase`` column value, or None.
        question: The ``question`` column value.
        raised_at: Epoch timestamp for the ``raised_at`` column.
        resolved_at: Epoch timestamp for the ``resolved_at`` column, or
            None to leave the escalation open (matched by
            ``v_escalations_open``).

    Returns:
        The inserted row's autoincrement ``id``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(escalations)")}
        fields = ["project_id", "role", "phase", "question", "blocking", "raised_at", "resolved_at"]
        values: list[object] = [project_id, role, phase, question, 1, raised_at, resolved_at]
        assert columns.issuperset(fields), f"escalations missing expected columns: {fields}"
        placeholders = ", ".join("?" for _ in fields)
        cursor = conn.execute(
            f"INSERT INTO escalations ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
        conn.commit()
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _now_ms() -> int:
    """Test-side timestamp helper (epoch-milliseconds), matching the *_findings tables' unit."""
    return int(time.time() * 1000)


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def test_discovery_happy_path_renders_markdown(db_path: Path, project_id: str) -> None:
    base = _now_ms()
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", section="Findings", title="Thing One",
        body="Body one.", sources='["https://example.invalid"]', created_at=base,
    )
    proc = run_cli(["report", "discovery", "--run", "run-1"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "# Discovery report — run `run-1`" in proc.stdout
    assert "## Findings — Thing One" in proc.stdout
    assert "Body one." in proc.stdout
    assert "_sources_: `[\"https://example.invalid\"]`" in proc.stdout


def test_discovery_missing_section_falls_back_to_general(db_path: Path, project_id: str) -> None:
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", section=None, title="No section",
        body="Body.", created_at=_now_ms(),
    )
    proc = run_cli(["report", "discovery", "--run", "run-1"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "## General — No section" in proc.stdout


def test_discovery_sprint_filter(db_path: Path, project_id: str) -> None:
    base = _now_ms()
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", sprint_branch="feature/x",
        title="In sprint", body="B", created_at=base,
    )
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", sprint_branch="feature/y",
        title="Other sprint", body="B", created_at=base + 1,
    )
    proc = run_cli(["report", "discovery", "--run", "run-1", "--sprint", "feature/x", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    assert rows[0]["title"] == "In sprint"


def test_discovery_orders_by_section_then_created_at(db_path: Path, project_id: str) -> None:
    base = _now_ms()
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", section="B", title="B-second",
        body="b", created_at=base + 10,
    )
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", section="B", title="B-first",
        body="b", created_at=base,
    )
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", section="A", title="A-only",
        body="a", created_at=base + 5,
    )
    proc = run_cli(["report", "discovery", "--run", "run-1", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    titles = [row["title"] for row in json.loads(proc.stdout)]
    assert titles == ["A-only", "B-first", "B-second"]


def test_discovery_json_shape(db_path: Path, project_id: str) -> None:
    insert_discovery_finding(
        db_path, project_id, discovery_run="run-1", section="S", title="T",
        body="B", sources=None, created_at=_now_ms(),
    )
    proc = run_cli(["report", "discovery", "--run", "run-1", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    assert set(rows[0].keys()) == {"section", "title", "body", "sources"}
    assert rows[0]["sources"] is None


def test_discovery_no_matches_is_header_only(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "discovery", "--run", "nope", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []

    text_proc = run_cli(["report", "discovery", "--run", "nope"], cli_env(db_path))
    assert text_proc.returncode == 0, text_proc.stderr
    assert text_proc.stdout.rstrip("\n") == "# Discovery report — run `nope`"


def test_discovery_missing_run_exits_2_with_usage(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "discovery"], cli_env(db_path))

    assert proc.returncode == 2
    assert "shctx report discovery" in proc.stdout


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------


def test_audit_happy_path_renders_markdown(db_path: Path, project_id: str) -> None:
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", concern="perf", severity="high",
        hypothesis="It is slow.", falsification="Tried X, still slow.", confidence="medium",
        finding="Confirmed slow.", gh_issue=42, created_at=_now_ms(),
    )
    proc = run_cli(["report", "audit", "--sprint", "feature/x"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "# Audit report — sprint `feature/x`" in proc.stdout
    assert "### [high / perf] It is slow." in proc.stdout
    assert "(filed as #42)" in proc.stdout
    assert "**Finding:** Confirmed slow." in proc.stdout
    assert "**Falsification attempt:** Tried X, still slow." in proc.stdout
    assert "**Confidence:** medium" in proc.stdout


def test_audit_no_gh_issue_omits_filed_line(db_path: Path, project_id: str) -> None:
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", severity="low",
        finding="F.", gh_issue=None, created_at=_now_ms(),
    )
    proc = run_cli(["report", "audit", "--sprint", "feature/x"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "filed as" not in proc.stdout


def test_audit_severity_ordering(db_path: Path, project_id: str) -> None:
    base = _now_ms()
    for i, sev in enumerate(["low", "critical", "info", "high", "medium"]):
        insert_audit_finding(
            db_path, project_id, sprint_branch="feature/x", severity=sev,
            hypothesis=f"hyp-{sev}", finding="f", created_at=base + i,
        )
    proc = run_cli(["report", "audit", "--sprint", "feature/x", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    severities = [row["severity"] for row in json.loads(proc.stdout)]
    # Bash CASE order: critical, high, medium, low, ELSE (info falls last).
    assert severities == ["critical", "high", "medium", "low", "info"]


def test_audit_concern_and_severity_filters(db_path: Path, project_id: str) -> None:
    base = _now_ms()
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", concern="perf", severity="high",
        hypothesis="h1", finding="f1", created_at=base,
    )
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", concern="security", severity="high",
        hypothesis="h2", finding="f2", created_at=base + 1,
    )
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", concern="perf", severity="low",
        hypothesis="h3", finding="f3", created_at=base + 2,
    )
    proc = run_cli(
        ["report", "audit", "--sprint", "feature/x", "--concern", "perf", "--severity", "high", "--json"],
        cli_env(db_path),
    )

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    assert rows[0]["hypothesis"] == "h1"


def test_audit_json_shape(db_path: Path, project_id: str) -> None:
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", created_at=_now_ms(),
    )
    proc = run_cli(["report", "audit", "--sprint", "feature/x", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert set(rows[0].keys()) == {
        "concern", "severity", "hypothesis", "falsification", "confidence", "finding", "gh_issue",
    }


def test_audit_missing_sprint_exits_2_with_usage(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "audit"], cli_env(db_path))

    assert proc.returncode == 2
    assert "shctx report audit" in proc.stdout


# --------------------------------------------------------------------------
# escalation
# --------------------------------------------------------------------------


def test_escalation_open_only_renders_open_rows(db_path: Path, project_id: str) -> None:
    now = int(time.time())
    insert_escalation(db_path, project_id, role="engineer", phase="build", question="Q1?", raised_at=now)
    insert_escalation(
        db_path, project_id, role="reviewer", question="Q2?", raised_at=now + 1, resolved_at=now + 10,
    )
    proc = run_cli(["report", "escalation", "--open-only"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "# Escalations" in proc.stdout
    assert "[engineer/build]" in proc.stdout
    assert "Q1?" in proc.stdout
    assert "Q2?" not in proc.stdout  # resolved, excluded from open-only


def test_escalation_open_only_missing_phase_renders_question_mark(db_path: Path, project_id: str) -> None:
    insert_escalation(db_path, project_id, role="engineer", phase=None, question="Q?", raised_at=int(time.time()))
    proc = run_cli(["report", "escalation", "--open-only"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "[engineer/?]" in proc.stdout


def test_escalation_full_annotates_open_and_resolved(db_path: Path, project_id: str) -> None:
    now = int(time.time())
    insert_escalation(db_path, project_id, role="engineer", question="Still open", raised_at=now)
    insert_escalation(
        db_path, project_id, role="reviewer", question="Done", raised_at=now + 1, resolved_at=now + 5,
    )
    proc = run_cli(["report", "escalation"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "[engineer/OPEN]" in proc.stdout
    assert "[reviewer/RESOLVED]" in proc.stdout


def test_escalation_full_orders_raised_at_descending(db_path: Path, project_id: str) -> None:
    now = int(time.time())
    insert_escalation(db_path, project_id, role="r1", question="oldest", raised_at=now)
    insert_escalation(db_path, project_id, role="r2", question="newest", raised_at=now + 100)
    proc = run_cli(["report", "escalation", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    questions = [row["question"] for row in json.loads(proc.stdout)]
    assert questions == ["newest", "oldest"]


def test_escalation_open_only_json_shape(db_path: Path, project_id: str) -> None:
    insert_escalation(db_path, project_id, role="engineer", phase="p", question="Q", raised_at=int(time.time()))
    proc = run_cli(["report", "escalation", "--open-only", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert set(rows[0].keys()) == {"id", "role", "phase", "question", "raised_at"}


def test_escalation_no_rows_is_header_only(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "escalation"], cli_env(db_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "# Escalations"

    json_proc = run_cli(["report", "escalation", "--json"], cli_env(db_path))
    assert json.loads(json_proc.stdout) == []


# --------------------------------------------------------------------------
# teammates
# --------------------------------------------------------------------------


def test_teammates_happy_path_and_ordering(db_path: Path, project_id: str) -> None:
    now_ms = int(time.time() * 1000)
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-1", team_name="alpha", teammate_name="older", agent_type="shepherd:engineer",
        session_id=None, status="active", declared_state=None,
        spawned_at=now_ms - 1000, last_seen_at=now_ms,
    ))
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-2", team_name="alpha", teammate_name="newer", agent_type="shepherd:reviewer",
        session_id=None, status="idle", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))
    proc = run_cli(["report", "teammates", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    names = [row["teammate_name"] for row in json.loads(proc.stdout)]
    assert names == ["newer", "older"]  # spawned_at DESC


def test_teammates_team_filter(db_path: Path, project_id: str) -> None:
    now_ms = int(time.time() * 1000)
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-1", team_name="alpha", teammate_name="a-member", agent_type="shepherd:engineer",
        session_id=None, status="active", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-2", team_name="beta", teammate_name="b-member", agent_type="shepherd:engineer",
        session_id=None, status="active", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))
    proc = run_cli(["report", "teammates", "--team", "beta", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    assert rows[0]["teammate_name"] == "b-member"


def test_teammates_stale_mins_flag_accepted_but_has_no_effect(db_path: Path, project_id: str) -> None:
    now_ms = int(time.time() * 1000)
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-1", team_name="alpha", teammate_name="solo", agent_type="shepherd:engineer",
        session_id=None, status="active", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))
    without = run_cli(["report", "teammates", "--json"], cli_env(db_path))
    with_flag = run_cli(["report", "teammates", "--stale-mins", "999", "--json"], cli_env(db_path))

    assert without.returncode == 0, without.stderr
    assert with_flag.returncode == 0, with_flag.stderr
    assert json.loads(without.stdout) == json.loads(with_flag.stdout)


def test_teammates_json_shape(db_path: Path, project_id: str) -> None:
    now_ms = int(time.time() * 1000)
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-1", team_name="alpha", teammate_name="solo", agent_type="shepherd:engineer",
        session_id=None, status="active", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))
    proc = run_cli(["report", "teammates", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert set(rows[0].keys()) == {"teammate_name", "agent_type", "status", "last_seen_at"}


def test_teammates_no_rows_is_header_only(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "teammates"], cli_env(db_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "# Teammates"


# --------------------------------------------------------------------------
# close
# --------------------------------------------------------------------------


def test_close_composes_all_three_sections(db_path: Path, project_id: str) -> None:
    now = int(time.time())
    now_ms = int(time.time() * 1000)
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", severity="critical",
        hypothesis="Crash risk.", finding="Confirmed.", created_at=now_ms,
    )
    insert_escalation(db_path, project_id, role="engineer", question="Blocked?", raised_at=now)
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-1", team_name="alpha", teammate_name="member", agent_type="shepherd:engineer",
        session_id=None, status="active", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))
    proc = run_cli(["report", "close", "--sprint", "feature/x"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "# Close report — `feature/x`" in out
    assert "## Audit findings" in out
    assert "# Audit report — sprint `feature/x`" in out
    assert "Crash risk." in out
    assert "## Open escalations" in out
    assert "# Escalations" in out
    assert "Blocked?" in out
    assert "## Teammate roster" in out
    assert "# Teammates" in out
    assert "member" in out

    # Section order matters: Audit findings before Open escalations before Teammate roster.
    assert out.index("## Audit findings") < out.index("## Open escalations") < out.index("## Teammate roster")


def test_close_json_shape(db_path: Path, project_id: str) -> None:
    now = int(time.time())
    now_ms = int(time.time() * 1000)
    insert_audit_finding(
        db_path, project_id, sprint_branch="feature/x", created_at=now_ms,
    )
    insert_escalation(db_path, project_id, role="engineer", question="Q?", raised_at=now)
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-1", team_name="alpha", teammate_name="member", agent_type="shepherd:engineer",
        session_id=None, status="active", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))
    proc = run_cli(["report", "close", "--sprint", "feature/x", "--json"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["sprint"] == "feature/x"
    assert len(payload["audit_findings"]) == 1
    assert len(payload["open_escalations"]) == 1
    assert len(payload["teammates"]) == 1


def test_close_missing_sprint_exits_2_with_usage(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "close"], cli_env(db_path))

    assert proc.returncode == 2
    assert "shctx report close" in proc.stdout


# --------------------------------------------------------------------------
# Sub-app usage/exit-code parity + DB-existence check.
# --------------------------------------------------------------------------


def test_no_db_exits_1(tmp_path: Path) -> None:
    missing_db = tmp_path / "nonexistent.db"
    proc = run_cli(["report", "discovery", "--run", "x"], cli_env(missing_db))

    assert proc.returncode == 1
    assert "registry DB not found" in proc.stderr


def test_no_db_exits_1_even_with_no_subcommand(tmp_path: Path) -> None:
    """Bash parity quirk: the DB check runs BEFORE the kind is even parsed,
    so a bare `shctx report` on an uninitialized project still exits 1,
    not the usual no-subcommand exit-0 usage."""
    missing_db = tmp_path / "nonexistent.db"
    proc = run_cli(["report"], cli_env(missing_db))

    assert proc.returncode == 1
    assert "registry DB not found" in proc.stderr


def test_no_subcommand_prints_usage_and_exits_0(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "shctx report discovery" in proc.stdout
    assert "shctx report audit" in proc.stdout
    assert "shctx report escalation" in proc.stdout
    assert "shctx report close" in proc.stdout
    assert "shctx report teammates" in proc.stdout


def test_help_subcommand_prints_usage_and_exits_0(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "help"], cli_env(db_path))

    assert proc.returncode == 0, proc.stderr
    assert "shctx report discovery" in proc.stdout


def test_unknown_subcommand_exits_2(db_path: Path, project_id: str) -> None:
    proc = run_cli(["report", "bogus"], cli_env(db_path))

    assert proc.returncode == 2
