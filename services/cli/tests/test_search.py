"""Subprocess parity tests for ``shepherd search`` (FTS5 full-text search).

Bash parity target: ``skills/context/scripts/cmd_search.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli search ...``)
against a full-schema fixture DB, seeding ``index_symbols``/``artifacts``
rows via raw ``sqlite3`` (schema-tolerant via ``PRAGMA table_info``,
mirroring ``conftest.insert_teammate``'s / ``test_query.py``'s
``_insert_row`` approach) so these tests exercise the same on-disk shape
the bash tooling itself reads and the same FTS5 virtual tables migration
``0004_fts_search.sql`` creates and keeps synced via triggers.

Like ``shctx query`` (see ``test_query.py``'s module docstring),
``shctx search``'s project-id resolution does NOT read the ``projects``
table — it reads a ``project.json`` FILE in the resolved shepherd work
directory (``_lib.sh``'s ``shctx_project_id``/``shctx_project_id_path``),
independently of ``SHCTX_DB``. So every test here sets ``SHEPHERD_WORKDIR``
to an isolated tmp directory (via :func:`search_env`) containing a
``project.json`` whose ``id`` matches the fixture DB's seeded
``projects.id`` row — using ``cli_env()`` alone would silently resolve
``resolve_workdir()`` against THIS repo's own real ``.artifacts/`` (no
``project.json`` there), turning every search test into a
project-not-registered failure that has nothing to do with the code under
test.

One coexistence-architecture wrinkle worth flagging up front: bash's
``cmd_search.sh`` does NOT call ``shctx_ensure_migrated`` before its own
explicit ``index_fts_symbols``-presence check, so a genuinely un-migrated
project (only ``0001_init.sql`` ever applied) legitimately hits that
check's ``exit 2`` branch in bash. This CLI's shared ``db.lifespan()``
(:mod:`shepherd_cli.db`, not owned by this port) self-heals ANY reachable
DB to the shipped HEAD schema — including migration 0004 — before every
single command runs, which makes a merely-behind-on-migrations fixture
DB an unreliable way to exercise the "FTS tables missing" branch here: it
gets silently healed out from under the test before the port's own check
ever runs. :func:`_drop_fts_symbols_table` instead builds a FULLY
migrated fixture DB (``schema_versions`` already claims every migration,
including 0004, is applied) and then drops the ``index_fts_symbols``
virtual table directly — reproducing a DB that LOOKS current to the fast
self-heal check (``MAX(version)``/``COUNT(*)`` already at shipped HEAD)
but has actually lost the table, which is exactly the shape this port's
own defensive re-check (mirroring bash's) exists to catch. See
:func:`test_fts_tables_missing_exits_2_even_though_schema_versions_is_current`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import build_full_schema_db, cli_env, insert_project, run_cli

#: Matches the ``printf('%.4f', bm25(...))`` rank text cmd_search.sh's own
#: queries produce -- used to normalize/locate rank tokens in assertions
#: without pinning tests to a specific numeric bm25 value (which is a
#: SQLite-FTS5-internal computation this port does not control and should
#: not need to reproduce bit-for-bit to prove parity; only the *shape*
#: -- a signed, fixed-4-decimal string -- is this port's own contract).
_RANK_RE = re.compile(r"-?\d+\.\d{4}")


# --------------------------------------------------------------------------
# Raw-sqlite3 seed helpers (schema-tolerant, mirroring test_query.py's
# _insert_row).
# --------------------------------------------------------------------------
def _insert_row(db_path: Path, table: str, values: dict[str, object]) -> None:
    """Insert one row into ``table``, keeping only columns that actually exist.

    Args:
        db_path: The fixture DB to write into.
        table: Table name (test-controlled constant, never user input).
        values: ``{column: value}`` to insert; extra keys not present on
            the table are silently dropped.
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


def _insert_symbol(
    db_path: Path,
    project_id: str,
    *,
    id: str,  # noqa: A002 - matches the column name, mirrors conftest's own `id` param naming
    name: str,
    kind: str = "fn",
    package: str = "pkg",
    file_path: str = "src/lib.rs",
    line: int | None = 1,
    signature: str | None = None,
    doc_summary: str | None = None,
) -> None:
    """Insert one ``index_symbols`` row (FTS-synced via the 0004 triggers)."""
    now = int(time.time())
    _insert_row(
        db_path,
        "index_symbols",
        {
            "id": id,
            "project_id": project_id,
            "name": name,
            "kind": kind,
            "package": package,
            "file_path": file_path,
            "line": line,
            "signature": signature,
            "doc_summary": doc_summary,
            "language": "rust",
            "hash": f"hash-{id}",
            "refreshed_at": now,
        },
    )


def _insert_artifact(
    db_path: Path,
    project_id: str,
    *,
    id: str,  # noqa: A002
    path: str,
    kind: str = "doc",
    sprint_branch: str | None = None,
    title: str | None = None,
    content: str | None = None,
) -> None:
    """Insert one ``artifacts`` row (FTS-synced via the 0004 triggers)."""
    now = int(time.time())
    _insert_row(
        db_path,
        "artifacts",
        {
            "id": id,
            "project_id": project_id,
            "kind": kind,
            "path": path,
            "sprint_branch": sprint_branch,
            "title": title,
            "content": content,
            "hash": f"hash-{id}",
            "created_at": now,
            "updated_at": now,
        },
    )


def _drop_fts_symbols_table(db_path: Path) -> None:
    """Drop ``index_fts_symbols`` WITHOUT touching ``schema_versions``.

    Used by the "FTS tables missing" test only -- see the module
    docstring's coexistence-architecture note for why a merely-behind-on-
    migrations fixture DB cannot exercise this branch (the shared
    ``db.lifespan()`` self-heal would silently fix it first). Leaving
    ``schema_versions`` claiming migration 4 is applied means the fast
    self-heal check (``MAX(version)``/``COUNT(*)`` already at shipped
    HEAD) reports "already current" and does NOT attempt to re-apply
    0004 -- reproducing a DB that looks current but has lost the table.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE index_fts_symbols;")
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Fixture DB + workdir/project.json + CLI-invocation helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def search_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB (migration 0004's FTS5 tables included) with two projects."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    insert_project(db_path, project_id="proj-b")
    return db_path


def search_env(
    db_path: Path, workdir: Path, project_id: str = "proj-a", write_project_json: bool = True
) -> dict[str, str]:
    """The environment for driving ``shepherd search`` against one fixture DB.

    Args:
        db_path: The sqlite file (drives ``SHCTX_DB`` via :func:`cli_env`).
        workdir: An isolated tmp directory to use as the shepherd work
            directory (``SHEPHERD_WORKDIR``) -- where ``project.json`` is
            read from, independently of ``SHCTX_DB`` (see the module
            docstring).
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


def _run_search(db_path: Path, workdir: Path, args: Sequence[str], *, project_id: str = "proj-a") -> object:
    """Run ``shepherd search <args>`` and return the completed subprocess."""
    return run_cli(["search", *args], search_env(db_path, workdir, project_id=project_id))


def _normalize_ranks(text: str) -> str:
    """Replace every rank token with a fixed placeholder, for rank-blind string comparisons."""
    return _RANK_RE.sub("<RANK>", text)


# --------------------------------------------------------------------------
# Usage / validation / not-found -- every non-happy exit-code branch.
# --------------------------------------------------------------------------
def test_no_args_prints_search_text_required_and_usage_to_stderr_exits_1(search_db: Path, tmp_path: Path) -> None:
    # Bash parity: `[[ -n "$text" ]] || { echo "ERROR: search text required" >&2; usage >&2; exit 1; }`.
    proc = _run_search(search_db, tmp_path / "wd", [])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: search text required" in proc.stderr
    assert "shctx search <text> [--scope=symbols|artifacts|all]" in proc.stderr


def test_flags_only_no_text_is_also_the_text_required_error(search_db: Path, tmp_path: Path) -> None:
    # A line of pure flags (no free-text word) parses to an empty `text` just like
    # bare `[]` does -- bash's loop never distinguishes "no tokens at all" from
    # "tokens, but none of them were text".
    proc = _run_search(search_db, tmp_path / "wd", ["--scope=symbols", "--json"])
    assert proc.returncode == 1
    assert "ERROR: search text required" in proc.stderr


@pytest.mark.parametrize("help_flag", ["-h", "--help"])
def test_help_flag_prints_usage_to_stdout_and_exits_0(search_db: Path, tmp_path: Path, help_flag: str) -> None:
    proc = _run_search(search_db, tmp_path / "wd", [help_flag])
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout.rstrip("\n") == (
        "shctx search <text> [--scope=symbols|artifacts|all] [--limit=N] [--md|--json]\n"
        "\n"
        "FTS5 search over the project's symbol index and artifact content. Requires\n"
        'schema migration 0004 (run `shctx migrate` if it errors with "no such table").\n'
        "\n"
        "  text          search text — passes to FTS5 (`name AND signature` etc OK)\n"
        "  --scope       symbols | artifacts | all (default: all)\n"
        "  --all         alias for --scope=all (canonical universal flag, v5.0.4)\n"
        "  --limit       max results per scope (default: 20)\n"
        "  --md | --json output format (default: md)\n"
        "\n"
        "Examples:\n"
        '  shctx search "BookSnapshot"\n'
        '  shctx search "QuestDB ILP" --scope=artifacts\n'
        '  shctx search "candle OR ohlc" --scope=symbols --limit=10 --json'
    )


def test_help_flag_short_circuits_before_later_tokens_are_examined(search_db: Path, tmp_path: Path) -> None:
    # Bash: `usage; exit 0` fires the moment -h/--help is seen, regardless of
    # position -- an unknown flag AFTER -h must never be reached.
    proc = _run_search(search_db, tmp_path / "wd", ["-h", "--totally-bogus-flag"])
    assert proc.returncode == 0
    assert "ERROR" not in proc.stdout
    assert proc.stderr == ""


def test_unknown_flag_exits_1_with_error_and_usage(search_db: Path, tmp_path: Path) -> None:
    # Bash: `--*) echo "ERROR: unknown flag: $1" >&2; usage >&2; exit 1 ;;` --
    # unlike --scope/--limit validation below, this branch DOES print usage.
    proc = _run_search(search_db, tmp_path / "wd", ["widget", "--bogus-flag"])
    assert proc.returncode == 1
    assert "ERROR: unknown flag: --bogus-flag" in proc.stderr
    assert "shctx search <text> [--scope=symbols|artifacts|all]" in proc.stderr


def test_invalid_scope_exits_1_with_message_only_no_usage(search_db: Path, tmp_path: Path) -> None:
    # Bash: `case "$scope" in symbols|artifacts|all) ;; *) echo "ERROR: --scope
    # must be symbols|artifacts|all" >&2; exit 1 ;; esac` -- no usage() call here,
    # unlike the unknown-flag branch above.
    proc = _run_search(search_db, tmp_path / "wd", ["widget", "--scope=bogus"])
    assert proc.returncode == 1
    assert proc.stderr.strip() == "ERROR: --scope must be symbols|artifacts|all"


def test_invalid_limit_exits_1(search_db: Path, tmp_path: Path) -> None:
    proc = _run_search(search_db, tmp_path / "wd", ["widget", "--limit=notanumber"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR" in proc.stderr
    assert "--limit" in proc.stderr


def test_missing_project_json_exits_1(search_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = search_env(search_db, workdir, write_project_json=False)
    proc = run_cli(["search", "widget"], env)
    assert proc.returncode == 1
    assert "missing" in proc.stderr
    assert "shctx init" in proc.stderr


def test_fts_tables_missing_exits_2_even_though_schema_versions_is_current(search_db: Path, tmp_path: Path) -> None:
    # See the module docstring's coexistence-architecture note: this reproduces
    # a DB the shared self-heal considers "already current" but that has
    # actually lost index_fts_symbols -- the one shape that still legitimately
    # reaches this command's own defensive re-check.
    _drop_fts_symbols_table(search_db)
    proc = _run_search(search_db, tmp_path / "wd", ["widget"])
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.strip() == (
        "ERROR: FTS tables missing. Run `shctx migrate` to apply 0004_fts_search.sql."
    )


def test_malformed_fts5_query_text_exits_1_with_controlled_message(search_db: Path, tmp_path: Path) -> None:
    """A search string FTS5's own query grammar rejects is a controlled failure, not a crash.

    An un-quoted mid-word hyphen (e.g. ``nothing-will-match``) is not
    literal text to FTS5 -- its query grammar parses the ``-`` as a
    NOT-operator, and this particular shape fails outright with a SQLite
    ``OperationalError`` (``no such column: will``). This is a
    DELIBERATE, DOCUMENTED deviation from bash's own behavior on the
    same input (see ``_search_impl``'s docstring in ``search.py``): bash
    splices that raw SQL runtime error into the middle of otherwise-valid
    markdown output and still exits 0 (a `sqlite3` CLI quirk combined
    with the error occurring inside an unchecked process substitution),
    which is not a behavior worth reproducing. This port instead reports
    one controlled error line on stderr and exits 1.
    """
    proc = _run_search(search_db, tmp_path / "wd", ["nothing-will-match-this"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: invalid search text" in proc.stderr
    assert "no such column" in proc.stderr


# --------------------------------------------------------------------------
# Happy path -- markdown (default) and JSON, all three scopes.
# --------------------------------------------------------------------------
def test_happy_path_md_default_scope_all(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot", package="orderbook", file_path="src/lib.rs", line=42)
    _insert_artifact(
        search_db, "proj-a", id="a1", path="docs/book.md", sprint_branch="main",
        title="Book notes", content="This describes the BookSnapshot type in detail.",
    )
    proc = _run_search(search_db, tmp_path / "wd", ["BookSnapshot"])
    assert proc.returncode == 0
    assert proc.stderr == ""
    normalized = _normalize_ranks(proc.stdout)
    assert normalized == (
        "# shctx search — `BookSnapshot`\n"
        "\n"
        "## Symbols\n"
        "\n"
        "| package | kind | name | file:line | rank |\n"
        "|---|---|---|---|---|\n"
        "| `orderbook` | fn | `BookSnapshot` | `src/lib.rs:42` | <RANK> |\n"
        "\n"
        "## Artifacts\n"
        "\n"
        "- **doc** · `docs/book.md` · branch `main` · rank <RANK>\n"
        "  - Book notes\n"
        "  - This describes the «BookSnapshot» type in detail.\n"
    )


def test_happy_path_json_default_scope_all_is_valid_json_with_expected_shape(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot", package="orderbook", file_path="src/lib.rs", line=42)
    _insert_artifact(
        search_db, "proj-a", id="a1", path="docs/book.md", sprint_branch="main",
        title="Book notes", content="This describes the BookSnapshot type in detail.",
    )
    proc = _run_search(search_db, tmp_path / "wd", ["BookSnapshot", "--json"])
    assert proc.returncode == 0
    assert proc.stderr == ""

    # The raw text (not just the parsed structure) must match bash's own hand-
    # rolled comma placement byte-for-byte, modulo the rank values themselves.
    normalized = _normalize_ranks(proc.stdout)
    assert normalized == (
        "{\n"
        '  "symbols": [\n'
        '    {"package":"orderbook","kind":"fn","name":"BookSnapshot","file":"src/lib.rs","line":42,"rank":<RANK>}\n'
        "  ]\n"
        "  ,\n"
        '  "artifacts": [\n'
        '    {"kind":"doc","path":"docs/book.md","title":"Book notes","branch":"main",'
        '"context":"This describes the «BookSnapshot» type in detail.","rank":<RANK>}\n'
        "  ]\n"
        "}\n"
    )

    parsed = json.loads(proc.stdout)
    assert set(parsed.keys()) == {"symbols", "artifacts"}
    assert len(parsed["symbols"]) == 1
    assert len(parsed["artifacts"]) == 1
    sym = parsed["symbols"][0]
    assert sym["package"] == "orderbook"
    assert sym["kind"] == "fn"
    assert sym["name"] == "BookSnapshot"
    assert sym["file"] == "src/lib.rs"
    assert sym["line"] == 42
    assert isinstance(sym["rank"], float)
    art = parsed["artifacts"][0]
    assert art["kind"] == "doc"
    assert art["path"] == "docs/book.md"
    assert art["title"] == "Book notes"
    assert art["branch"] == "main"
    assert "BookSnapshot" in art["context"]
    assert isinstance(art["rank"], float)


def test_scope_symbols_only_omits_artifacts_section(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot")
    _insert_artifact(search_db, "proj-a", id="a1", path="docs/book.md", content="BookSnapshot details")
    proc = _run_search(search_db, tmp_path / "wd", ["BookSnapshot", "--scope=symbols"])
    assert proc.returncode == 0
    assert "## Symbols" in proc.stdout
    assert "## Artifacts" not in proc.stdout
    assert "docs/book.md" not in proc.stdout


def test_scope_artifacts_only_omits_symbols_section(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot")
    _insert_artifact(search_db, "proj-a", id="a1", path="docs/book.md", content="BookSnapshot details")
    proc = _run_search(search_db, tmp_path / "wd", ["BookSnapshot", "--scope=artifacts"])
    assert proc.returncode == 0
    assert "## Symbols" not in proc.stdout
    assert "## Artifacts" in proc.stdout
    assert "docs/book.md" in proc.stdout


def test_scope_artifacts_only_json_has_no_symbols_key(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot")
    _insert_artifact(search_db, "proj-a", id="a1", path="docs/book.md", content="BookSnapshot details")
    proc = _run_search(search_db, tmp_path / "wd", ["BookSnapshot", "--scope=artifacts", "--json"])
    assert proc.returncode == 0
    parsed = json.loads(proc.stdout)
    assert set(parsed.keys()) == {"artifacts"}


def test_all_flag_is_an_alias_for_scope_all(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot")
    _insert_artifact(search_db, "proj-a", id="a1", path="docs/book.md", content="BookSnapshot details")
    via_all_flag = _run_search(search_db, tmp_path / "wd1", ["BookSnapshot", "--all"])
    via_scope_all = _run_search(search_db, tmp_path / "wd2", ["BookSnapshot", "--scope=all"])
    assert via_all_flag.returncode == via_scope_all.returncode == 0
    assert _normalize_ranks(via_all_flag.stdout) == _normalize_ranks(via_scope_all.stdout)
    assert "## Symbols" in via_all_flag.stdout
    assert "## Artifacts" in via_all_flag.stdout


def test_all_flag_after_explicit_scope_overrides_it(search_db: Path, tmp_path: Path) -> None:
    # Bash: plain variable reassignment inside the loop -- whichever of
    # --scope=.../--all appears LAST wins, in either direction.
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot")
    proc = _run_search(search_db, tmp_path / "wd", ["BookSnapshot", "--scope=symbols", "--all"])
    assert proc.returncode == 0
    assert "## Symbols" in proc.stdout
    assert "## Artifacts" in proc.stdout


# --------------------------------------------------------------------------
# Free-text word joining / flag interleaving.
# --------------------------------------------------------------------------
def test_multiple_positional_words_are_space_joined_into_one_query(search_db: Path, tmp_path: Path) -> None:
    proc = _run_search(search_db, tmp_path / "wd", ["Book", "Snapshot", "--scope=symbols"])
    assert proc.returncode == 0
    assert proc.stdout.startswith("# shctx search — `Book Snapshot`\n")


def test_flags_interleaved_with_text_words_in_any_order(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s1", name="BookSnapshot")
    proc = _run_search(search_db, tmp_path / "wd", ["Book", "--scope=symbols", "Snapshot", "--limit=5"])
    assert proc.returncode == 0
    assert proc.stdout.startswith("# shctx search — `Book Snapshot`\n")
    assert "## Symbols" in proc.stdout
    assert "## Artifacts" not in proc.stdout


# --------------------------------------------------------------------------
# Ordering / limit.
# --------------------------------------------------------------------------
def test_limit_truncates_result_count(search_db: Path, tmp_path: Path) -> None:
    for i in range(3):
        _insert_symbol(search_db, "proj-a", id=f"s{i}", name=f"Widget{i}", doc_summary="widget " * (i + 1))
    proc = _run_search(search_db, tmp_path / "wd", ["widget", "--scope=symbols", "--limit=2"])
    assert proc.returncode == 0
    names = re.findall(r"`(Widget\d)`", proc.stdout)
    assert len(names) == 2


def test_negative_limit_means_unlimited(search_db: Path, tmp_path: Path) -> None:
    # SQLite semantics: LIMIT -1 (or any negative value) means "no limit" --
    # bash's `$((limit + 0))` arithmetic passes a negative --limit straight
    # through with no special-casing, and so does this port.
    for i in range(3):
        _insert_symbol(search_db, "proj-a", id=f"s{i}", name=f"Widget{i}", doc_summary="widget " * (i + 1))
    proc = _run_search(search_db, tmp_path / "wd", ["widget", "--scope=symbols", "--limit=-1"])
    assert proc.returncode == 0
    names = re.findall(r"`(Widget\d)`", proc.stdout)
    assert len(names) == 3


def test_default_limit_is_20(search_db: Path, tmp_path: Path) -> None:
    for i in range(25):
        _insert_symbol(search_db, "proj-a", id=f"s{i}", name=f"Widget{i:02d}", doc_summary="widget")
    proc = _run_search(search_db, tmp_path / "wd", ["widget", "--scope=symbols"])
    assert proc.returncode == 0
    names = re.findall(r"`(Widget\d\d)`", proc.stdout)
    assert len(names) == 20


def test_result_order_matches_the_underlying_order_by_rank_query(search_db: Path, tmp_path: Path) -> None:
    """The CLI's row order must match the SAME SQL run directly against the DB.

    Deliberately does not assert a hand-picked expected order (bm25's exact
    numeric output is a SQLite-FTS5-internal computation this port must
    reproduce, not predict) -- instead it runs the identical query bash's
    ``run_symbols()`` / this port's ``_SYMBOLS_SQL`` describes directly
    against the fixture DB and asserts the CLI prints names in that exact
    same sequence, proving the ``ORDER BY rank`` clause made it through the
    port unchanged.
    """
    _insert_symbol(search_db, "proj-a", id="s1", name="WidgetOne", doc_summary="widget widget widget widget")
    _insert_symbol(search_db, "proj-a", id="s2", name="WidgetTwo", doc_summary="widget appears once")
    _insert_symbol(search_db, "proj-a", id="s3", name="WidgetThree", doc_summary="widget shows up too")

    conn = sqlite3.connect(str(search_db))
    try:
        expected_rows = conn.execute(
            """
            SELECT s.name AS name, printf('%.4f', bm25(index_fts_symbols)) AS rank
            FROM index_fts_symbols
            JOIN index_symbols s ON s.rowid = index_fts_symbols.rowid
            WHERE index_fts_symbols MATCH ?
              AND s.project_id = ?
            ORDER BY rank
            LIMIT ?
            """,
            ("widget", "proj-a", 20),
        ).fetchall()
    finally:
        conn.close()
    expected_names = [row[0] for row in expected_rows]
    assert expected_names, "fixture must produce at least one match for this test to be meaningful"

    proc = _run_search(search_db, tmp_path / "wd", ["widget", "--scope=symbols"])
    assert proc.returncode == 0
    actual_names = re.findall(r"`(Widget\w+)`", proc.stdout)
    assert actual_names == expected_names


# --------------------------------------------------------------------------
# Empty / not-found.
# --------------------------------------------------------------------------
def test_no_matches_prints_section_headers_with_no_rows_and_exits_0(search_db: Path, tmp_path: Path) -> None:
    proc = _run_search(search_db, tmp_path / "wd", ["zzznomatchzzz"])
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout == (
        "# shctx search — `zzznomatchzzz`\n"
        "\n"
        "## Symbols\n"
        "\n"
        "| package | kind | name | file:line | rank |\n"
        "|---|---|---|---|---|\n"
        "\n"
        "## Artifacts\n"
        "\n"
    )


def test_no_matches_json_is_valid_with_empty_arrays(search_db: Path, tmp_path: Path) -> None:
    proc = _run_search(search_db, tmp_path / "wd", ["zzznomatchzzz", "--json"])
    assert proc.returncode == 0
    parsed = json.loads(proc.stdout)
    assert parsed == {"symbols": [], "artifacts": []}


# --------------------------------------------------------------------------
# Project scoping.
# --------------------------------------------------------------------------
def test_scoped_to_active_project_only(search_db: Path, tmp_path: Path) -> None:
    _insert_symbol(search_db, "proj-a", id="s-a", name="SharedTermHere", package="pkg-a")
    _insert_symbol(search_db, "proj-b", id="s-b", name="SharedTermHere", package="pkg-b")
    proc = _run_search(search_db, tmp_path / "wd", ["SharedTermHere", "--scope=symbols"], project_id="proj-a")
    assert proc.returncode == 0
    assert "pkg-a" in proc.stdout
    assert "pkg-b" not in proc.stdout


# --------------------------------------------------------------------------
# Artifact rendering edge cases (branch/context omission).
# --------------------------------------------------------------------------
def test_artifact_without_sprint_branch_omits_branch_segment(search_db: Path, tmp_path: Path) -> None:
    _insert_artifact(search_db, "proj-a", id="a1", path="docs/nobranch.md", title="Widget notes", sprint_branch=None)
    proc = _run_search(search_db, tmp_path / "wd", ["Widget", "--scope=artifacts"])
    assert proc.returncode == 0
    normalized = _normalize_ranks(proc.stdout)
    assert normalized == (
        "# shctx search — `Widget`\n"
        "\n"
        "## Artifacts\n"
        "\n"
        "- **doc** · `docs/nobranch.md` · rank <RANK>\n"
        "  - Widget notes\n"
    )


def test_artifact_with_no_content_match_omits_context_line(search_db: Path, tmp_path: Path) -> None:
    # A hit that matched entirely via `title` (content NULL/no highlight target)
    # must render with no third "- <ctx>" line -- and must not crash: this is
    # the regression case for FTS5's snippet() returning SQL NULL (not an
    # empty string) here, which the port must coerce to "" the same way
    # sqlite3's own list-mode CLI output renders a NULL cell.
    _insert_artifact(search_db, "proj-a", id="a1", path="docs/nocontent.md", title="Widget notes", content=None)
    proc = _run_search(search_db, tmp_path / "wd", ["Widget", "--scope=artifacts"])
    assert proc.returncode == 0
    normalized = _normalize_ranks(proc.stdout)
    assert normalized == (
        "# shctx search — `Widget`\n"
        "\n"
        "## Artifacts\n"
        "\n"
        "- **doc** · `docs/nocontent.md` · rank <RANK>\n"
        "  - Widget notes\n"
    )


def test_artifact_with_no_title_renders_empty_title_line(search_db: Path, tmp_path: Path) -> None:
    _insert_artifact(search_db, "proj-a", id="a1", path="docs/notitle.md", title=None, content="Widget appears here")
    proc = _run_search(search_db, tmp_path / "wd", ["Widget", "--scope=artifacts"])
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    # "- **doc** ... rank ..." then a bare "  - " (empty title) then the ctx line.
    assert lines[-2] == "  - "
    assert "Widget" in lines[-1]
