"""Subprocess parity tests for ``shepherd issues`` (``classify``/``list``).

Bash parity target: ``skills/context/scripts/cmd_issues.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli issues ...``)
against a full-schema fixture DB, seeding ``index_issues`` rows via raw
``sqlite3`` (schema-tolerant via ``PRAGMA table_info``, mirroring
``test_query.py``'s/``test_search.py``'s own ``_insert_row`` helper).

Like ``shctx query``/``shctx search`` (see those modules' own test-file
docstrings), ``shctx issues``'s project-id resolution does NOT read the
``projects`` table — it reads a ``project.json`` FILE in the resolved
shepherd work directory. So every test here sets ``SHEPHERD_WORKDIR`` to an
isolated tmp directory (via :func:`issues_env`) containing a
``project.json`` whose ``id`` matches the fixture DB's seeded
``projects.id`` row.

Several tests assert byte-for-byte STDOUT parity against the legacy
``cmd_issues.sh`` run on the IDENTICAL sqlite file and workdir state
(mirroring ``test_status.py``'s bash-parity pattern) — EXCEPT
``classify --md``'s per-issue detail rows, where bash's own shipped source
crashes (a real, pre-existing bug: ``printf '- #%-5s  %s%s\\n' ...`` has a
format string beginning with ``-``, which bash's ``printf`` builtin
misparses as an unrecognized option, verified against a real ``bash 5.2``
binary — ``printf: - : invalid option``, exit 2, after printing only the
bucket-count summary table and the first bucket's bare heading). Per
``shepherd_cli.commands.issues``'s module docstring, this port renders the
CORRECT, complete output there instead of reproducing bash's crash — see
:func:`test_classify_md_renders_full_detail_sections_bash_crashes_here`,
which documents and pins that specific, deliberate deviation instead of
diffing against bash for that one format.

NOTE: this module is written against the ``issues`` Typer sub-app before
the orchestrator wires it into ``shepherd_cli/app.py``/``shepherd_cli/
__main__.py``'s ``PORTED`` set. Until that lands, ``${PY} -m shepherd_cli
issues`` transparently shims to the bash ``cmd_issues.sh`` via
``__main__.py``'s passthrough (so these tests are currently just comparing
bash against itself). Per the port contract, this file is syntax-checked
(``python -m py_compile``) but not run via pytest in this session; the
orchestrator's integration pass (adding ``"issues"`` to ``PORTED`` and
``app.add_typer(issues.app, name="issues")``) is what turns these into a
green (or red, informatively) suite. Every scenario in this file was
independently verified, byte-for-byte, against a real ``cmd_issues.sh``
run under bash 5.2 during development of ``shepherd_cli/commands/issues.py``
(see that module's own docstring for the deviations found and documented
along the way).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import REPO_ROOT, build_full_schema_db, cli_env, insert_project, run_cli

CMD_ISSUES_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_issues.sh"


# --------------------------------------------------------------------------
# Fixture DB + workdir/project.json + raw-sqlite3 seed helpers.
# --------------------------------------------------------------------------
def _insert_row(db_path: Path, table: str, values: dict[str, object]) -> None:
    """Insert one row into ``table``, keeping only columns that actually exist.

    Schema-tolerant like ``conftest.insert_teammate``/``test_query.py``'s
    own ``_insert_row``: reads ``PRAGMA table_info(table)`` and silently
    drops any key in ``values`` that isn't a real column.

    Args:
        db_path: The fixture DB to write into.
        table: Table name (test-controlled constant, never user input).
        values: ``{column: value}`` to insert; extra keys are ignored.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608 - fixed test table names only
        fields = [key for key in values if key in columns]
        placeholders = ", ".join("?" for _ in fields)
        col_list = ", ".join(fields)
        conn.execute(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",  # noqa: S608 - fixed table/column allow-list above
            [values[key] for key in fields],
        )
        conn.commit()
    finally:
        conn.close()


def _insert_issue(
    db_path: Path,
    project_id: str,
    *,
    id: str,  # noqa: A002 - matches the column name, mirrors test_search.py's own `id` param naming
    number: int,
    title: str,
    state: str = "open",
    labels: str = "[]",
    milestone: str | None = None,
    url: str | None = None,
    updated_at: int | None = None,
    now: int | None = None,
) -> None:
    """Insert one ``index_issues`` row.

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in ``projects.id``.
        id: The row's primary key.
        number: The issue number (rendered as ``#<number>``).
        title: The issue title.
        state: ``"open"`` or ``"closed"``.
        labels: The raw JSON-array TEXT column (default: empty array).
        milestone: The milestone name, or None for "no milestone".
        url: The issue URL; defaults to a value derived from ``number``.
        updated_at: Epoch-seconds ``updated_at``; defaults to ``now``.
        now: Epoch-seconds "current time" used for ``created_at``/
            ``refreshed_at`` and the ``updated_at`` default; defaults to
            the real wall-clock time.
    """
    if now is None:
        now = int(time.time())
    _insert_row(
        db_path,
        "index_issues",
        {
            "id": id,
            "project_id": project_id,
            "source": "github",
            "number": number,
            "title": title,
            "state": state,
            "labels": labels,
            "milestone": milestone,
            "assignees": "[]",
            "url": url or f"https://example.test/issues/{number}",
            "created_at": now,
            "updated_at": now if updated_at is None else updated_at,
            "refreshed_at": now,
        },
    )


@pytest.fixture
def issues_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with one registered project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    return db_path


def issues_env(db_path: Path, workdir: Path, project_id: str = "proj-a", write_project_json: bool = True) -> dict[str, str]:
    """The environment for driving ``shepherd issues`` against one fixture DB.

    Args:
        db_path: The sqlite file (drives ``SHCTX_DB`` via :func:`cli_env`).
        workdir: An isolated tmp directory to use as the shepherd work
            directory (``SHEPHERD_WORKDIR``) — where ``project.json`` is
            read from, independently of ``SHCTX_DB``.
        project_id: The id to write into ``project.json``'s ``"id"`` field.
        write_project_json: When False, ``workdir`` is created but no
            ``project.json`` is written (drives the "not initialized"
            error path).

    Returns:
        A full subprocess environment.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if write_project_json:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def _run_issues(db_path: Path, workdir: Path, args: Sequence[str], *, project_id: str = "proj-a") -> subprocess.CompletedProcess[str]:
    """Run ``shepherd issues <args>`` and return the completed subprocess."""
    return run_cli(["issues", *args], issues_env(db_path, workdir, project_id=project_id))


def _run_bash_issues(db_path: Path, workdir: Path, args: Sequence[str], *, project_id: str = "proj-a") -> subprocess.CompletedProcess[str]:
    """Run the legacy ``cmd_issues.sh`` directly (bash-parity twin of :func:`_run_issues`)."""
    return subprocess.run(
        ["bash", str(CMD_ISSUES_SH), *args],
        env=issues_env(db_path, workdir, project_id=project_id),
        capture_output=True,
        text=True,
        timeout=15,
    )


def _seed_all_buckets(db_path: Path, project_id: str, now: int) -> None:
    """Seed six open issues (one per bucket, plus a closed one) + one milestone-blocking issue.

    Bucket coverage, by issue:
      - ``#1`` "Fix login bug" — labels ``["bug","p0"]`` -> blocking-this-sprint
        (via the ``p0`` label, milestone unset).
      - ``#2`` "Add feature X" — labels ``["enhancement","tracking"]``, no
        milestone -> tracking-future.
      - ``#3`` "Old regression" — labels ``["bug","regression"]``, no
        milestone, updated recently -> drift-risk.
      - ``#4`` "Deferred thing" — labels ``["deferred"]`` -> labeled-non-issue.
      - ``#5`` "Mystery" — no labels, no milestone -> unclassified.
      - ``#6`` "Closed one" — ``state="closed"`` (excluded from both
        ``classify``, which only ever looks at ``state='open'``, and any
        ``list --state=open`` filter).
      - ``#7`` "Milestone match" — no special labels, ``milestone="v1.0.0"``
        (matches the sprint's own resolved milestone) -> blocking-this-sprint
        via the milestone-equality branch, not a label.

    Args:
        db_path: The fixture DB to seed.
        project_id: FK target in ``projects.id``.
        now: The "current time" epoch-seconds baseline every row's
            timestamps derive from.
    """
    _insert_issue(db_path, project_id, id="iss-1", number=1, title="Fix login bug", labels='["bug","p0"]', now=now, updated_at=now - 100)
    _insert_issue(
        db_path, project_id, id="iss-2", number=2, title="Add feature X", labels='["enhancement","tracking"]', now=now, updated_at=now - 200
    )
    _insert_issue(
        db_path, project_id, id="iss-3", number=3, title="Old regression", labels='["bug","regression"]', now=now, updated_at=now - 5000
    )
    _insert_issue(db_path, project_id, id="iss-4", number=4, title="Deferred thing", labels='["deferred"]', now=now, updated_at=now - 300)
    _insert_issue(db_path, project_id, id="iss-5", number=5, title="Mystery", now=now, updated_at=now - 400)
    _insert_issue(db_path, project_id, id="iss-6", number=6, title="Closed one", state="closed", labels='["bug"]', now=now, updated_at=now - 900)
    _insert_issue(
        db_path,
        project_id,
        id="iss-7",
        number=7,
        title="Milestone match",
        milestone="v1.0.0",
        now=now,
        updated_at=now - 50,
    )


# --------------------------------------------------------------------------
# Top-level dispatch: no-subcommand / -h / --help / unknown subcommand.
# --------------------------------------------------------------------------
def test_no_subcommand_prints_usage_to_stdout_and_exits_0(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", [])
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout.rstrip("\n").startswith("shctx issues <classify|list> [args]")
    assert "Buckets (classify):" in proc.stdout


@pytest.mark.parametrize("help_flag", ["-h", "--help"])
def test_top_level_help_flag_prints_usage_to_stdout_and_exits_0(issues_db: Path, tmp_path: Path, help_flag: str) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", [help_flag])
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert "shctx issues <classify|list> [args]" in proc.stdout


def test_unknown_subcommand_exits_2_with_error_and_usage_on_stderr(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["bogus"])
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "ERROR: unknown subcommand: bogus" in proc.stderr
    assert "shctx issues <classify|list> [args]" in proc.stderr


def test_bash_parity_no_subcommand(issues_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, [])
    bash_proc = _run_bash_issues(issues_db, workdir, [])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert python_proc.stderr == bash_proc.stderr == ""


def test_bash_parity_unknown_subcommand(issues_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["bogus"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["bogus"])
    assert python_proc.returncode == bash_proc.returncode == 2
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# classify — per-subcommand -h/--help, unknown arg, invalid --drift-days.
# --------------------------------------------------------------------------
def test_classify_help_flag_prints_usage_and_exits_0(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["classify", "-h"])
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert "classify [--sprint=BRANCH]" in proc.stdout


def test_classify_unknown_arg_exits_2(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["classify", "--bogus"])
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: unknown arg: --bogus"


def test_classify_help_short_circuits_before_later_unknown_arg(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["classify", "-h", "--totally-bogus"])
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_classify_invalid_drift_days_exits_1(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["classify", "--drift-days=notanumber"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "--drift-days" in proc.stderr


def test_bash_parity_classify_help(issues_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["classify", "-h"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "-h"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_bash_parity_classify_unknown_arg(issues_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["classify", "--bogus"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "--bogus"])
    assert python_proc.returncode == bash_proc.returncode == 2
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# classify — missing DB / missing project.json / no open issues.
# --------------------------------------------------------------------------
def test_classify_missing_db_exits_1_with_bash_parity_message(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"  # never created
    workdir = tmp_path / "wd"
    proc = _run_issues(db_path, workdir, ["classify"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: no root.db — run 'shctx init && shctx refresh'"


def test_bash_parity_classify_missing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    workdir = tmp_path / "wd"
    python_proc = _run_issues(db_path, workdir, ["classify"])
    bash_proc = _run_bash_issues(db_path, workdir, ["classify"])
    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stderr == bash_proc.stderr


def test_classify_missing_project_json_exits_1(issues_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = issues_env(issues_db, workdir, write_project_json=False)
    proc = run_cli(["issues", "classify"], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "project.json missing" in proc.stderr


def test_classify_no_open_issues_exits_0_with_stderr_message_no_stdout(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _insert_issue(issues_db, "proj-a", id="iss-closed", number=1, title="Closed only", state="closed", now=now)
    workdir = tmp_path / "wd"
    proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0"])
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr.strip() == "No open issues in cache. Run 'shctx refresh --scope=github' to populate."


def test_bash_parity_classify_no_open_issues(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _insert_issue(issues_db, "proj-a", id="iss-closed", number=1, title="Closed only", state="closed", now=now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# classify — happy path: every bucket, text/json/md, bash-parity.
# --------------------------------------------------------------------------
def test_classify_text_buckets_all_five(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0"])
    assert proc.returncode == 0, proc.stderr

    assert "blocking-this-sprint            2" in proc.stdout  # #1 (label) + #7 (milestone)
    assert "labeled-non-issue               1" in proc.stdout
    assert "tracking-future                 1" in proc.stdout
    assert "drift-risk                      1" in proc.stdout
    assert "unclassified                    1" in proc.stdout
    assert "#6" not in proc.stdout  # the closed issue never appears
    assert "#7" in proc.stdout
    assert "Milestone match" in proc.stdout


def test_bash_parity_classify_text_all_buckets(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0"])
    assert python_proc.returncode == bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout


def test_bash_parity_classify_json_all_buckets(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--json"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--json"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout

    payload = json.loads(python_proc.stdout)
    assert len(payload) == 6  # every OPEN issue (#6 is closed, excluded)
    by_number = {entry["number"]: entry for entry in payload}
    assert by_number[1]["bucket"] == "blocking-this-sprint"
    assert by_number[1]["labels"] == ["bug", "p0"]
    assert by_number[2]["bucket"] == "tracking-future"
    assert by_number[3]["bucket"] == "drift-risk"
    assert by_number[4]["bucket"] == "labeled-non-issue"
    assert by_number[5]["bucket"] == "unclassified"
    assert by_number[5]["milestone"] is None
    assert by_number[7]["bucket"] == "blocking-this-sprint"
    assert by_number[7]["milestone"] == "v1.0.0"
    assert 6 not in by_number


def test_bash_parity_classify_unclassified_only_text(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--unclassified-only"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--unclassified-only"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert "Mystery" in python_proc.stdout
    assert "Fix login bug" not in python_proc.stdout


def test_bash_parity_classify_drift_days_excludes_old_row(issues_db: Path, tmp_path: Path) -> None:
    """A drift-risk candidate older than --drift-days falls through to unclassified."""
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--drift-days=0"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--drift-days=0"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert "drift-risk                      0" in python_proc.stdout


def test_classify_md_renders_full_detail_sections_bash_crashes_here(issues_db: Path, tmp_path: Path) -> None:
    """Deliberate, documented deviation: bash's own ``cmd_issues.sh`` crashes rendering
    ``classify --md``'s per-issue detail rows (a real bug — a ``printf`` format string
    beginning with ``-`` is misparsed as an option by bash's ``printf`` builtin, exit 2,
    verified against a real ``bash 5.2`` — see ``shepherd_cli/commands/issues.py``'s
    module docstring). This port renders the CORRECT, complete output instead."""
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"

    python_proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--md"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["classify", "--sprint=v1.0.0", "--md"])

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 2  # bash's own crash, pinned so a future bash fix is noticed
    assert "printf: - : invalid option" in bash_proc.stderr

    assert "## Issue triage — v1.0.0 (milestone: v1.0.0)" in python_proc.stdout
    assert "### Blocking this sprint (2)" in python_proc.stdout
    assert "### Drift risk (high-severity, no sprint milestone) (1)" in python_proc.stdout
    assert "### Unclassified (review manually) (1)" in python_proc.stdout
    assert "### Tracking / future work (1)" in python_proc.stdout
    assert "### Labeled non-issue (deferred / wontfix / etc.) (1)" in python_proc.stdout
    assert "- #1      Fix login bug" in python_proc.stdout
    assert "labels: bug p0" in python_proc.stdout
    assert "- #7      Milestone match · milestone: v1.0.0" in python_proc.stdout
    assert "Tip: use --unclassified-only" in python_proc.stdout
    # bash's truncated (crashed) output must NOT be mistaken for a passing comparison.
    assert python_proc.stdout != bash_proc.stdout


# --------------------------------------------------------------------------
# list — per-subcommand -h/--help, unknown arg, invalid --limit.
# --------------------------------------------------------------------------
def test_list_help_flag_prints_usage_and_exits_0(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["list", "-h"])
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert "list [--state=open|closed|all]" in proc.stdout


def test_list_unknown_arg_exits_2(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["list", "--bogus"])
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: unknown arg: --bogus"


def test_list_invalid_limit_exits_1(issues_db: Path, tmp_path: Path) -> None:
    proc = _run_issues(issues_db, tmp_path / "wd", ["list", "--limit=notanumber"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "--limit" in proc.stderr


def test_bash_parity_list_help(issues_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "-h"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "-h"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# list — missing DB / missing project.json.
# --------------------------------------------------------------------------
def test_list_missing_db_exits_1_with_bash_parity_message(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    workdir = tmp_path / "wd"
    proc = _run_issues(db_path, workdir, ["list"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: no root.db"


def test_bash_parity_list_missing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    workdir = tmp_path / "wd"
    python_proc = _run_issues(db_path, workdir, ["list"])
    bash_proc = _run_bash_issues(db_path, workdir, ["list"])
    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stderr == bash_proc.stderr


def test_list_missing_project_json_exits_1(issues_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = issues_env(issues_db, workdir, write_project_json=False)
    proc = run_cli(["issues", "list"], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "project.json missing" in proc.stderr


# --------------------------------------------------------------------------
# list — happy path: text/md/json, --state, --limit, ordering, empty result.
# --------------------------------------------------------------------------
def test_bash_parity_list_default_text(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert "#6" not in python_proc.stdout  # default --state=open excludes the closed issue


def test_bash_parity_list_state_all_includes_closed(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "--state=all"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "--state=all"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert "#6" in python_proc.stdout
    assert "Closed one" in python_proc.stdout


def test_bash_parity_list_state_closed(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "--state=closed"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "--state=closed"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert "Closed one" in python_proc.stdout
    assert "Fix login bug" not in python_proc.stdout


def test_bash_parity_list_md(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "--md"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "--md"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert "| # | Title | State | Milestone | Labels |" in python_proc.stdout


def test_bash_parity_list_json(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "--json"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "--json"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout

    payload = json.loads(python_proc.stdout)
    assert len(payload) == 6
    assert all("milestone" in entry for entry in payload)
    # #5 has no milestone -> COALESCE(milestone,'') -> empty string (NOT null, unlike classify --json).
    by_number = {entry["number"]: entry for entry in payload}
    assert by_number[5]["milestone"] == ""
    assert by_number[7]["milestone"] == "v1.0.0"
    assert isinstance(by_number[1]["labels"], str)  # list --json keeps labels as its raw TEXT string, unlike classify --json


def test_bash_parity_list_json_empty_result_prints_nothing(issues_db: Path, tmp_path: Path) -> None:
    """bash-parity: a zero-row --json result prints ZERO bytes, not "[]" (see the module docstring)."""
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "--state=closed", "--json"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "--state=closed", "--json"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout == ""


def test_bash_parity_list_empty_result_text_still_prints_header(issues_db: Path, tmp_path: Path) -> None:
    """bash-parity: text/md formats always print the header + separator, even with zero rows."""
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "--state=closed"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "--state=closed"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    assert "Issue" in python_proc.stdout
    assert "Title" in python_proc.stdout


def test_bash_parity_list_limit(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list", "--limit=2"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list", "--limit=2"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    # ORDER BY updated_at DESC LIMIT 2 -> the two MOST RECENTLY updated open
    # issues: #7 (now-50) and #1 (now-100).
    assert "#7" in python_proc.stdout
    assert "#1" in python_proc.stdout
    assert "#2" not in python_proc.stdout


def test_list_ordering_is_updated_at_desc(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    proc = _run_issues(issues_db, workdir, ["list", "--json"])
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    numbers_in_order = [entry["number"] for entry in payload]
    # updated_at (relative to `now`): #7=-50, #1=-100, #2=-200, #4=-300, #5=-400, #3=-5000.
    assert numbers_in_order == [7, 1, 2, 4, 5, 3]


def test_bash_parity_list_milestone_placeholder_padding(issues_db: Path, tmp_path: Path) -> None:
    """Regression pin for the byte-vs-codepoint padding fix: the COALESCE(milestone,'—')
    em-dash placeholder must pad to the SAME column width bash's printf produces under
    the C/POSIX locale (see shepherd_cli/commands/issues.py's module docstring)."""
    now = int(time.time())
    _insert_issue(issues_db, "proj-a", id="iss-nom", number=42, title="No milestone here", now=now)
    workdir = tmp_path / "wd"
    python_proc = _run_issues(issues_db, workdir, ["list"])
    bash_proc = _run_bash_issues(issues_db, workdir, ["list"])
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# classify — sprint resolution: explicit --sprint vs git-branch fallback.
# --------------------------------------------------------------------------
def test_classify_sprint_strips_dev_suffix(issues_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _insert_issue(issues_db, "proj-a", id="iss-1", number=1, title="On sprint", milestone="v6.4.0", now=now)
    workdir = tmp_path / "wd"
    proc = _run_issues(issues_db, workdir, ["classify", "--sprint=v6.4.0-dev.3", "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload[0]["bucket"] == "blocking-this-sprint"


def test_classify_defaults_sprint_to_current_git_branch(issues_db: Path, tmp_path: Path) -> None:
    """No --sprint given -> bash/this port both resolve `git rev-parse --abbrev-ref
    HEAD` from the invoking process's own cwd (run_cli's cwd is CLI_ROOT, inside this
    repo checkout) -- mirroring test_dash.py's own `_current_branch()` helper."""
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    now = int(time.time())
    _seed_all_buckets(issues_db, "proj-a", now)
    workdir = tmp_path / "wd"
    proc = _run_issues(issues_db, workdir, ["classify"])
    assert proc.returncode == 0, proc.stderr
    assert f"sprint: {branch}" in proc.stdout
