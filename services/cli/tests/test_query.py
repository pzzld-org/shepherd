"""Subprocess parity tests for ``shepherd query`` (canned-SQL runner).

Bash parity target: ``skills/context/scripts/cmd_query.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli query ...``)
against a full-schema fixture DB, seeding rows via raw ``sqlite3``
(schema-tolerant via ``PRAGMA table_info``, mirroring
``conftest.insert_teammate``'s approach) so these tests exercise the same
on-disk shape the bash tooling itself reads.

Unlike every other ported command, ``shctx query``'s project-id resolution
does NOT read the ``projects`` table — it reads a ``project.json`` FILE in
the resolved shepherd work directory (``_lib.sh``'s
``shctx_project_id``/``shctx_project_id_path``). That file lives in a
DIFFERENT place than the fixture DB whenever ``SHCTX_DB`` is used to point
at a specific file (exactly like bash: ``shctx_db_path``'s ``SHCTX_DB``
override does not also redirect ``shctx_project_id_path``, which always
resolves off ``resolve_workdir()``). So every test here sets
``SHEPHERD_WORKDIR`` to an isolated tmp directory (via :func:`query_env`)
containing a ``project.json`` whose ``id`` matches the fixture DB's seeded
``projects.id`` row — using ``cli_env()`` alone would silently resolve
``resolve_workdir()`` against THIS repo's own real ``.artifacts/`` (no
``project.json`` there), turning every query test into a
project-not-registered failure that has nothing to do with the code under
test.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import build_full_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Fixture DB + workdir/project.json + raw-sqlite3 seed helpers.
# --------------------------------------------------------------------------


def _insert_row(db_path: Path, table: str, values: dict[str, object]) -> None:
    """Insert one row into ``table``, keeping only columns that actually exist.

    Schema-tolerant like ``conftest.insert_teammate``: reads
    ``PRAGMA table_info(table)`` and silently drops any key in ``values``
    that isn't a real column, so a test fixture doesn't need to track
    every column a migration might have added or removed.

    Args:
        db_path: The fixture DB to write into.
        table: Table name (test-controlled constant, never user input —
            interpolated directly into the SQL text).
        values: ``{column: value}`` to insert; extra keys not present on
            the table are ignored.
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


@pytest.fixture
def query_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with one registered project (FK target + ``:project_id`` scope)."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    insert_project(db_path, project_id="proj-b")
    return db_path


def query_env(db_path: Path, workdir: Path, project_id: str = "proj-a", write_project_json: bool = True) -> dict[str, str]:
    """The environment for driving ``shepherd query`` against one fixture DB.

    Args:
        db_path: The sqlite file (drives ``SHCTX_DB`` via :func:`cli_env`).
        workdir: An isolated tmp directory to use as the shepherd work
            directory (``SHEPHERD_WORKDIR``) — this is where
            ``project.json`` is read from, independently of ``SHCTX_DB``
            (see the module docstring).
        project_id: The id to write into ``project.json``'s ``"id"``
            field, when ``write_project_json`` is True.
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


def _run_query(db_path: Path, workdir: Path, args: Sequence[str], *, project_id: str = "proj-a") -> object:
    """Run ``shepherd query <args>`` and return the completed subprocess."""
    return run_cli(["query", *args], query_env(db_path, workdir, project_id=project_id))


# --------------------------------------------------------------------------
# Usage / validation / not-found — every non-happy exit-code branch.
# --------------------------------------------------------------------------


def test_no_name_prints_usage_to_stderr_and_exits_1(query_db: Path, tmp_path: Path) -> None:
    # Bash parity: `[[ -n "$name" ]] || { echo "ERROR: usage: ..." >&2; exit 1; }`.
    proc = _run_query(query_db, tmp_path / "wd", [])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: usage: shctx query <name>" in proc.stderr


def test_bad_flag_exits_1_with_message(query_db: Path, tmp_path: Path) -> None:
    # Bash parity: `*) echo "ERROR: bad arg: $a" >&2; exit 1 ;;` — a flag that is
    # neither --json/--md nor --key=val (e.g. a bare word, or --flag with no '=').
    proc = _run_query(query_db, tmp_path / "wd", ["mem-search", "notaflag"])
    assert proc.returncode == 1
    assert "ERROR: bad arg: notaflag" in proc.stderr

    proc2 = _run_query(query_db, tmp_path / "wd2", ["mem-search", "--bareflag"])
    assert proc2.returncode == 1
    assert "ERROR: bad arg: --bareflag" in proc2.stderr


def test_unknown_query_name_exits_1_with_message(query_db: Path, tmp_path: Path) -> None:
    proc = _run_query(query_db, tmp_path / "wd", ["totally-not-a-real-query"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: query not found: totally-not-a-real-query" in proc.stderr


def test_missing_project_json_exits_1(query_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = query_env(query_db, workdir, write_project_json=False)
    proc = run_cli(["query", "mem-search", "--q=%x%"], env)
    assert proc.returncode == 1
    assert "missing" in proc.stderr
    assert "shctx init" in proc.stderr


def test_no_subcommand_and_query_alone_are_the_same_usage_error(query_db: Path, tmp_path: Path) -> None:
    # `shepherd query` (bare) is bash's own name-missing branch, not a distinct
    # "no subcommand" usage dump like deliverable/signal (query has no verbs to
    # dispatch among — it's a single positional-argument command).
    bare = _run_query(query_db, tmp_path / "wd", [])
    named = _run_query(query_db, tmp_path / "wd", [])
    assert bare.returncode == named.returncode == 1


# --------------------------------------------------------------------------
# mem-search — happy path, --json, project scoping, empty result.
# --------------------------------------------------------------------------


def _seed_mem_entry(db_path: Path, *, entry_id: str, project_id: str, title: str, body: str = "body", tags: str = "[]", pinned: int = 0) -> None:
    now = int(time.time())
    _insert_row(
        db_path,
        "mem_entries",
        {
            "id": entry_id, "project_id": project_id, "kind": "note",
            "title": title, "body": body, "tags": tags, "pinned": pinned,
            "created_at": now, "updated_at": now,
        },
    )


def test_mem_search_md_happy_path(query_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(query_db, entry_id="m1", project_id="proj-a", title="hello world", tags='["a","b"]')
    _seed_mem_entry(query_db, entry_id="m2", project_id="proj-a", title="unrelated entry")
    proc = _run_query(query_db, tmp_path / "wd", ["mem-search", "--q=%hello%"])
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert lines[0].startswith("| id ")
    assert lines[1].startswith("|----") or lines[1].startswith("|---")
    assert any("hello world" in line for line in lines[2:])
    assert not any("unrelated entry" in line for line in lines[2:])


def test_mem_search_json_shape_and_types(query_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(query_db, entry_id="m1", project_id="proj-a", title="hello world", tags='["a","b"]', pinned=1)
    proc = _run_query(query_db, tmp_path / "wd", ["mem-search", "--q=%hello%", "--json"])
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert rows == [
        {
            "id": "m1", "kind": "note", "title": "hello world", "body": "body",
            "tags": '["a","b"]', "pinned": 1,
            "created_at": rows[0]["created_at"],
        }
    ]
    assert isinstance(rows[0]["pinned"], int)
    assert isinstance(rows[0]["created_at"], int)


def test_mem_search_scoped_to_active_project(query_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(query_db, entry_id="ma", project_id="proj-a", title="alpha needle")
    _seed_mem_entry(query_db, entry_id="mb", project_id="proj-b", title="beta needle")
    proc = _run_query(query_db, tmp_path / "wd", ["mem-search", "--q=%needle%", "--json"], project_id="proj-a")
    rows = json.loads(proc.stdout)
    assert [row["id"] for row in rows] == ["ma"]


def test_mem_search_no_match_prints_nothing(query_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(query_db, entry_id="m1", project_id="proj-a", title="hello world")
    md = _run_query(query_db, tmp_path / "wd1", ["mem-search", "--q=%zzz-no-match%"])
    assert md.returncode == 0
    assert md.stdout == ""
    js = _run_query(query_db, tmp_path / "wd2", ["mem-search", "--q=%zzz-no-match%", "--json"])
    assert js.returncode == 0
    assert js.stdout == ""  # bash parity: sqlite3 -json prints ZERO bytes for zero rows.


def test_last_format_flag_wins(query_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(query_db, entry_id="m1", project_id="proj-a", title="hello world")
    both = _run_query(query_db, tmp_path / "wd", ["mem-search", "--q=%hello%", "--json", "--md"])
    assert both.returncode == 0
    assert both.stdout.lstrip().startswith("|")  # last flag (--md) wins, bash parity.

    both2 = _run_query(query_db, tmp_path / "wd2", ["mem-search", "--q=%hello%", "--md", "--json"])
    assert both2.returncode == 0
    json.loads(both2.stdout)  # last flag (--json) wins -> valid JSON, not a table.


# --------------------------------------------------------------------------
# dedup-check — single bind param, missing-flag -> NULL fill, quote escaping.
# --------------------------------------------------------------------------


def _seed_symbol(
    db_path: Path, *, symbol_id: str, project_id: str, name: str, kind: str = "fn",
    package: str = "core", visibility: str | None = "pub", file_path: str = "src/lib.rs",
    line: int = 1, signature: str | None = None,
) -> None:
    now = int(time.time())
    _insert_row(
        db_path,
        "index_symbols",
        {
            "id": symbol_id, "project_id": project_id, "name": name, "kind": kind,
            "package": package, "file_path": file_path, "line": line,
            "visibility": visibility, "signature": signature, "doc_summary": None,
            "language": "rust", "hash": f"hash-{symbol_id}", "refreshed_at": now,
        },
    )


def test_dedup_check_missing_name_binds_null_matches_nothing(query_db: Path, tmp_path: Path) -> None:
    _seed_symbol(query_db, symbol_id="s1", project_id="proj-a", name="DriftCircuit")
    # No --name given -> :name -> NULL -> `name = NULL` never matches (SQL NULL semantics).
    proc = _run_query(query_db, tmp_path / "wd", ["dedup-check"])
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_dedup_check_with_name_and_single_quote_escaping(query_db: Path, tmp_path: Path) -> None:
    _seed_symbol(query_db, symbol_id="s1", project_id="proj-a", name="O'Brien", package="widgets", kind="struct")
    proc = _run_query(query_db, tmp_path / "wd", ["dedup-check", "--name=O'Brien", "--json"])
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    assert rows[0]["name"] == "O'Brien"
    assert rows[0]["package"] == "widgets"


def test_dedup_check_scoped_to_active_project(query_db: Path, tmp_path: Path) -> None:
    # dedup-check.sql does not select `id` (only name/kind/package/file_path/line/
    # signature) -- scope on `package`, which we seed differently per project, instead.
    _seed_symbol(query_db, symbol_id="s1", project_id="proj-a", name="Shared", package="pkg-a")
    _seed_symbol(query_db, symbol_id="s2", project_id="proj-b", name="Shared", package="pkg-b")
    proc = _run_query(query_db, tmp_path / "wd", ["dedup-check", "--name=Shared", "--json"], project_id="proj-a")
    rows = json.loads(proc.stdout)
    assert [row["package"] for row in rows] == ["pkg-a"]


# --------------------------------------------------------------------------
# open-issues — view filter (state='open') + ORDER BY number, project scoped.
# --------------------------------------------------------------------------


def _seed_issue(
    db_path: Path, *, issue_id: str, project_id: str, number: int, state: str,
    title: str = "issue", labels: str = "[]", milestone: str | None = None,
) -> None:
    now = int(time.time())
    _insert_row(
        db_path,
        "index_issues",
        {
            "id": issue_id, "project_id": project_id, "source": "github", "number": number,
            "title": title, "state": state, "labels": labels, "milestone": milestone,
            "assignees": "[]", "body": None, "url": f"https://example/{number}",
            "created_at": now, "updated_at": now, "refreshed_at": now,
        },
    )


def test_open_issues_filters_state_and_orders_by_number(query_db: Path, tmp_path: Path) -> None:
    _seed_issue(query_db, issue_id="i3", project_id="proj-a", number=30, state="open")
    _seed_issue(query_db, issue_id="i1", project_id="proj-a", number=10, state="open")
    _seed_issue(query_db, issue_id="i2", project_id="proj-a", number=20, state="open")
    _seed_issue(query_db, issue_id="ic", project_id="proj-a", number=15, state="closed")
    _seed_issue(query_db, issue_id="ib", project_id="proj-b", number=5, state="open")

    proc = _run_query(query_db, tmp_path / "wd", ["open-issues", "--json"], project_id="proj-a")
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert [row["number"] for row in rows] == [10, 20, 30]
    assert all(row["state"] == "open" for row in rows)


# --------------------------------------------------------------------------
# open-prs — state filter + ORDER BY updated_at DESC.
# --------------------------------------------------------------------------


def _seed_pr(
    db_path: Path, *, pr_id: str, project_id: str, number: int, state: str, updated_at: int,
) -> None:
    now = int(time.time())
    _insert_row(
        db_path,
        "index_prs",
        {
            "id": pr_id, "project_id": project_id, "source": "github", "number": number,
            "title": f"pr {number}", "state": state, "base_branch": "main",
            "head_branch": f"feat/{number}", "labels": "[]", "url": f"https://example/pr/{number}",
            "created_at": now, "updated_at": updated_at, "merged_at": None, "refreshed_at": now,
        },
    )


def test_open_prs_filters_state_and_orders_updated_at_desc(query_db: Path, tmp_path: Path) -> None:
    _seed_pr(query_db, pr_id="p1", project_id="proj-a", number=1, state="open", updated_at=100)
    _seed_pr(query_db, pr_id="p2", project_id="proj-a", number=2, state="open", updated_at=300)
    _seed_pr(query_db, pr_id="p3", project_id="proj-a", number=3, state="open", updated_at=200)
    _seed_pr(query_db, pr_id="p4", project_id="proj-a", number=4, state="closed", updated_at=999)

    proc = _run_query(query_db, tmp_path / "wd", ["open-prs", "--json"])
    rows = json.loads(proc.stdout)
    assert [row["number"] for row in rows] == [2, 3, 1]
    assert all(row["state"] == "open" for row in rows)


# --------------------------------------------------------------------------
# recent-releases — ORDER BY published_at DESC LIMIT 25.
# --------------------------------------------------------------------------


def test_recent_releases_orders_published_at_desc(query_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    for tag, published_at in (("v1", now - 300), ("v2", now - 100), ("v3", now - 200)):
        _insert_row(
            query_db, "index_releases",
            {
                "id": f"rel-{tag}", "project_id": "proj-a", "source": "github", "tag": tag,
                "name": tag, "prerelease": 0, "draft": 0, "body": None,
                "url": f"https://example/{tag}", "published_at": published_at, "refreshed_at": now,
            },
        )
    proc = _run_query(query_db, tmp_path / "wd", ["recent-releases", "--json"])
    rows = json.loads(proc.stdout)
    assert [row["tag"] for row in rows] == ["v2", "v3", "v1"]


# --------------------------------------------------------------------------
# canonical-types — kind + visibility filtered view (migration 0003).
# --------------------------------------------------------------------------


def test_canonical_types_filters_kind_and_visibility(query_db: Path, tmp_path: Path) -> None:
    _seed_symbol(query_db, symbol_id="s1", project_id="proj-a", name="Widget", kind="struct", visibility="pub")
    _seed_symbol(query_db, symbol_id="s2", project_id="proj-a", name="helper_fn", kind="fn", visibility="pub")
    _seed_symbol(query_db, symbol_id="s3", project_id="proj-a", name="Hidden", kind="struct", visibility="private")

    proc = _run_query(query_db, tmp_path / "wd", ["canonical-types", "--json"])
    rows = json.loads(proc.stdout)
    assert [row["name"] for row in rows] == ["Widget"]
    assert rows[0]["kind"] == "struct"


# --------------------------------------------------------------------------
# drift-risk — open issues with a critical/high label.
# --------------------------------------------------------------------------


def test_drift_risk_filters_open_and_critical_or_high_labels(query_db: Path, tmp_path: Path) -> None:
    _seed_issue(query_db, issue_id="i1", project_id="proj-a", number=1, state="open", labels='["critical"]')
    _seed_issue(query_db, issue_id="i2", project_id="proj-a", number=2, state="open", labels='["high"]')
    _seed_issue(query_db, issue_id="i3", project_id="proj-a", number=3, state="open", labels='["low"]')
    _seed_issue(query_db, issue_id="i4", project_id="proj-a", number=4, state="closed", labels='["critical"]')

    proc = _run_query(query_db, tmp_path / "wd", ["drift-risk", "--json"])
    rows = json.loads(proc.stdout)
    assert sorted(row["number"] for row in rows) == [1, 2]


# --------------------------------------------------------------------------
# search-symbols / search-artifacts — FTS5 MATCH + optional --limit.
# --------------------------------------------------------------------------


def test_search_symbols_fts_match(query_db: Path, tmp_path: Path) -> None:
    _seed_symbol(query_db, symbol_id="s1", project_id="proj-a", name="DriftCircuit", signature="fn drift() -> bool")
    _seed_symbol(query_db, symbol_id="s2", project_id="proj-a", name="Unrelated", signature="fn other()")

    proc = _run_query(query_db, tmp_path / "wd", ["search-symbols", "--q=DriftCircuit", "--json"])
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert [row["name"] for row in rows] == ["DriftCircuit"]


def test_search_artifacts_fts_match_respects_limit(query_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    for i in range(3):
        _insert_row(
            query_db, "artifacts",
            {
                "id": f"art-{i}", "project_id": "proj-a", "kind": "doc", "path": f"docs/needle-{i}.md",
                "sprint_branch": None, "title": f"needle doc {i}", "hash": f"h{i}",
                "created_at": now, "updated_at": now, "content": "the needle is here",
            },
        )
    proc = _run_query(query_db, tmp_path / "wd", ["search-artifacts", "--q=needle", "--limit=1", "--json"])
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1


# --------------------------------------------------------------------------
# cache-usage — optional --sprint binding (NULL -> match-all) + rollup math.
# --------------------------------------------------------------------------


def _seed_cache_usage(
    db_path: Path, *, row_id: int, project_id: str, sprint: str, role: str, ts: int,
    input_tokens: int, cache_read: int, cache_creation: int, hit_rate: float,
) -> None:
    _insert_row(
        db_path, "index_cache_usage",
        {
            "id": row_id, "project_id": project_id, "ts": ts, "session_id": f"sess-{row_id}",
            "role": role, "agent_id": f"agent-{row_id}", "sprint": sprint, "turns": 1,
            "input_tokens": input_tokens, "output_tokens": 10,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_creation,
            "ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0,
            "hit_rate": hit_rate, "parse_error": None,
        },
    )


def test_cache_usage_rolls_up_all_sprints_when_sprint_omitted(query_db: Path, tmp_path: Path) -> None:
    _seed_cache_usage(query_db, row_id=1, project_id="proj-a", sprint="feat-a", role="engineer", ts=1,
                       input_tokens=100, cache_read=50, cache_creation=10, hit_rate=0.5)
    _seed_cache_usage(query_db, row_id=2, project_id="proj-a", sprint="feat-b", role="engineer", ts=2,
                       input_tokens=200, cache_read=150, cache_creation=20, hit_rate=0.75)

    proc = _run_query(query_db, tmp_path / "wd", ["cache-usage", "--json"])
    rows = json.loads(proc.stdout)
    sprints = {row["sprint"] for row in rows}
    assert sprints == {"feat-a", "feat-b"}


def test_cache_usage_filters_by_sprint_when_given(query_db: Path, tmp_path: Path) -> None:
    _seed_cache_usage(query_db, row_id=1, project_id="proj-a", sprint="feat-a", role="engineer", ts=1,
                       input_tokens=100, cache_read=50, cache_creation=10, hit_rate=0.5)
    _seed_cache_usage(query_db, row_id=2, project_id="proj-a", sprint="feat-b", role="engineer", ts=2,
                       input_tokens=200, cache_read=150, cache_creation=20, hit_rate=0.75)

    proc = _run_query(query_db, tmp_path / "wd", ["cache-usage", "--sprint=feat-a", "--json"])
    rows = json.loads(proc.stdout)
    assert [row["sprint"] for row in rows] == ["feat-a"]
    assert rows[0]["dispatches"] == 1


def test_cache_usage_excludes_parse_error_rows(query_db: Path, tmp_path: Path) -> None:
    _seed_cache_usage(query_db, row_id=1, project_id="proj-a", sprint="feat-a", role="engineer", ts=1,
                       input_tokens=100, cache_read=50, cache_creation=10, hit_rate=0.5)
    _insert_row(
        query_db, "index_cache_usage",
        {
            "id": 2, "project_id": "proj-a", "ts": 2, "session_id": "sess-2", "role": "engineer",
            "agent_id": "agent-2", "sprint": "feat-a", "turns": 1, "input_tokens": None,
            "output_tokens": None, "cache_read_input_tokens": None, "cache_creation_input_tokens": None,
            "ephemeral_5m_input_tokens": None, "ephemeral_1h_input_tokens": None, "hit_rate": None,
            "parse_error": "boom",
        },
    )
    proc = _run_query(query_db, tmp_path / "wd", ["cache-usage", "--sprint=feat-a", "--json"])
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    assert rows[0]["dispatches"] == 1  # the parse_error row never enters the rollup.
