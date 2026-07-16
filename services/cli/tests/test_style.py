"""Subprocess parity tests for ``shepherd style`` (init/show/list/edit).

Bash parity target: ``skills/context/scripts/cmd_style.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli style ...``),
exactly like ``test_mem.py``/``test_deliverable.py`` — never by importing
``shepherd_cli`` into the pytest process — and seeds/reads the ``styles``
table via raw ``sqlite3`` (PRAGMA table_info-tolerant) so these tests
exercise the same on-disk shape the bash tooling itself reads and writes.

CRITICAL ISOLATION NOTE: unlike every other #198-wave group so far
(mem/deliverable/signal/status), ``style`` ALSO touches the real
filesystem (``<workdir>/styles/<lang>.md``), not just the sqlite DB.
``resolve_workdir()`` auto-detects an EXISTING ``.shepherd/``/
``.artifacts/`` directory relative to the git repo root when
``SHEPHERD_WORKDIR`` is unset — and this actual checkout has a real,
committed ``.artifacts/`` directory with real style files in it. Every
test in this module MUST set ``SHEPHERD_WORKDIR`` to an isolated
``tmp_path`` (see :func:`style_env`) or it would read/write the live
repo's own ``.artifacts/styles/`` as a side effect of running the test
suite. Do not remove that override.

Timestamps in this table are epoch-SECONDS (``shctx_now`` = ``date
+%s``), matching ``mem_entries``/``sessions``/etc — NOT epoch-milliseconds
like ``teammates``/``deliverables``/``session_signals``.

Two deliberate, documented parity deviations (see
``shepherd_cli/commands/style.py``'s module docstring for the full
rationale, mirrored from ``commands/mem.py``'s precedent):

1. Project-id resolution queries the ``projects`` table (``SELECT id FROM
   projects LIMIT 1``) rather than reading ``<workdir>/project.json``
   through ``jq`` the way ``cmd_style.sh``'s own ``shctx_project_id()``
   does — so these tests seed a project via ``conftest.insert_project``,
   not a ``project.json`` file.
2. Row ids are an independently-generated UUIDv7 (stdlib time/urandom),
   not byte-identical to bash's ``shctx_uuid7`` construction, but
   spec-compliant and unique — ``_UUID7_RE`` below checks the shape, not
   an exact value.
"""

from __future__ import annotations

import json
import re
import sqlite3
import stat
import time
from pathlib import Path

import pytest
from conftest import REPO_ROOT, build_full_schema_db, cli_env, insert_project, run_cli

# UUIDv7 shape: 8-4-4-4-12 hex, version nibble '7', variant nibble in [8-b].
_UUID7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

#: Every language the real, checked-in skill bundles (``skills/context/styles/*.md``).
#: Tests read these files for real (via ``CLAUDE_PLUGIN_ROOT`` -> the real repo root,
#: same as every other subprocess test in this suite) but only ever WRITE into an
#: isolated ``tmp_path`` workdir — never the real ``skills/context/styles/`` source.
_BUNDLED_LANGUAGES = ("go", "python", "rust", "shell", "sql", "typescript")


# --------------------------------------------------------------------------
# Fixture DB/workdir + raw-sqlite3 seed/read helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row; ``styles.project_id`` FKs into this."""
    return insert_project(db_path)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """An isolated work directory — see the module docstring's isolation note."""
    path = tmp_path / "workdir"
    path.mkdir()
    return path


def style_env(db_path: Path, workdir: Path) -> dict[str, str]:
    """The environment for driving ``shepherd style``, isolated from the real repo.

    Args:
        db_path: The fixture DB (sets ``SHCTX_DB``, via ``cli_env``).
        workdir: The isolated work directory (sets ``SHEPHERD_WORKDIR``,
            overriding ``resolve_workdir()``'s real-``.artifacts/``
            auto-detection — see the module docstring's isolation note).

    Returns:
        The full environment dict for :func:`conftest.run_cli`.
    """
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def fetch_style_row(db_path: Path, project_id: str, language: str) -> dict[str, object] | None:
    """Read one ``styles`` row by ``(project_id, language)``, or None if absent."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM styles WHERE project_id = ? AND language = ?",
            (project_id, language),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def count_styles(db_path: Path) -> int:
    """Total row count in ``styles``, across all projects."""
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM styles").fetchone()[0])
    finally:
        conn.close()


def insert_style_row(
    db_path: Path,
    project_id: str,
    *,
    style_id: str,
    language: str,
    source_path: str,
    active: int = 1,
    created_at: int,
    updated_at: int | None = None,
) -> None:
    """Insert one ``styles`` row directly via sqlite3 (column-tolerant)."""
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(styles)")}
        fields = ["id", "project_id", "language", "source_path", "active", "created_at", "updated_at"]
        assert columns.issuperset(fields), f"styles missing expected columns: {fields} not subset of {columns}"
        values: list[object] = [
            style_id, project_id, language, source_path, active,
            created_at, updated_at if updated_at is not None else created_at,
        ]
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO styles ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608 - fixed column allow-list above, no user input
            values,
        )
        conn.commit()
    finally:
        conn.close()


def make_fake_editor(tmp_path: Path, *, exit_code: int, marker_path: Path | None = None) -> Path:
    """Write a tiny shell script usable as ``$EDITOR``, exiting with ``exit_code``.

    Args:
        tmp_path: Where to write the script.
        exit_code: The exit code the script returns.
        marker_path: If given, the script touches this path first (so a
            test can assert the "editor" actually ran, e.g. was invoked
            with the expected file argument recorded to a marker file).

    Returns:
        The absolute path to the executable script — bash-parity note:
        ``cmd_style.sh`` invokes ``"${EDITOR:-vi}"`` as a single literal
        token (no shell-splitting), and this module's ``_run_edit``
        mirrors that with ``subprocess.run([editor, dst])`` — so
        ``EDITOR`` must be one executable path, never a "command with
        args" string.
    """
    script = tmp_path / f"fake_editor_{exit_code}.sh"
    marker_line = f'echo "$1" > {marker_path}\n' if marker_path is not None else ""
    script.write_text(f"#!/bin/sh\n{marker_line}exit {exit_code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _now() -> int:
    """Test-side mirror of ``_lib.sh``'s ``shctx_now`` (epoch seconds)."""
    return int(time.time())


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


def test_init_happy_path_copies_file_and_upserts_row(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    before = _now()
    proc = run_cli(["style", "init", "python"], env)
    after = _now()

    assert proc.returncode == 0, proc.stderr
    dst = workdir / "styles" / "python.md"
    assert f"shctx style: wrote {dst}" in proc.stdout
    assert dst.is_file()
    bundled = REPO_ROOT / "skills" / "context" / "styles" / "python.md"
    assert dst.read_text() == bundled.read_text()

    row = fetch_style_row(db_path, project_id, "python")
    assert row is not None
    assert _UUID7_RE.match(row["id"]), f"not a UUIDv7: {row['id']!r}"
    assert row["project_id"] == project_id
    assert row["source_path"] == str(dst)
    assert row["active"] == 1
    assert before <= row["created_at"] <= after
    assert row["created_at"] == row["updated_at"]


def test_init_all_writes_every_bundled_language(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "init", "--all"], env)

    assert proc.returncode == 0, proc.stderr
    for lang in _BUNDLED_LANGUAGES:
        assert (workdir / "styles" / f"{lang}.md").is_file(), f"{lang}.md not written"
        assert fetch_style_row(db_path, project_id, lang) is not None, f"{lang} row missing"
    assert count_styles(db_path) == len(_BUNDLED_LANGUAGES)


def test_init_preserves_existing_file_but_still_upserts_row(db_path: Path, project_id: str, workdir: Path) -> None:
    styles_dir = workdir / "styles"
    styles_dir.mkdir(parents=True)
    dst = styles_dir / "python.md"
    dst.write_text("MY CUSTOM PROJECT-LOCAL EDITS")
    env = style_env(db_path, workdir)

    proc = run_cli(["style", "init", "python"], env)

    assert proc.returncode == 0, proc.stderr
    assert f"{dst} already exists (preserving)" in proc.stdout
    assert dst.read_text() == "MY CUSTOM PROJECT-LOCAL EDITS"  # untouched
    assert fetch_style_row(db_path, project_id, "python") is not None  # row still written


def test_init_second_run_upserts_not_duplicates(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    first = run_cli(["style", "init", "python"], env)
    assert first.returncode == 0, first.stderr
    first_row = fetch_style_row(db_path, project_id, "python")
    assert first_row is not None

    second = run_cli(["style", "init", "python"], env)
    assert second.returncode == 0, second.stderr
    second_row = fetch_style_row(db_path, project_id, "python")
    assert second_row is not None

    assert count_styles(db_path) == 1  # no duplicate row
    assert second_row["id"] == first_row["id"]  # id preserved across the upsert
    assert second_row["created_at"] == first_row["created_at"]  # created_at preserved
    assert second_row["updated_at"] >= first_row["updated_at"]


def test_init_missing_lang_arg_exits_1(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "init"], env)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx style init <lang|--all>" in proc.stderr


def test_init_unknown_language_exits_1_and_writes_nothing(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "init", "not-a-real-language"], env)

    assert proc.returncode == 1
    assert "ERROR: no bundled style for not-a-real-language" in proc.stderr
    assert not (workdir / "styles" / "not-a-real-language.md").exists()
    assert count_styles(db_path) == 0


def test_init_no_project_registered_exits_1(db_path: Path, workdir: Path) -> None:
    """No ``projects`` row at all: the project-resolution gate fires FIRST,
    even before ``init``'s own missing-arg check would (bash-parity
    ordering — project_id resolves unconditionally, before dispatch)."""
    env = style_env(db_path, workdir)  # no project_id fixture used -> no projects row
    proc = run_cli(["style", "init"], env)

    assert proc.returncode == 1
    assert "no project registered" in proc.stderr
    assert count_styles(db_path) == 0


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


def test_list_before_any_init_prints_nothing(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "list"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_bare_style_with_no_subcommand_defaults_to_list(db_path: Path, project_id: str, workdir: Path) -> None:
    """Bash parity: ``sub="${1:-list}"`` — a bare ``shctx style`` runs
    ``list``, NOT a usage message (unlike deliverable/signal/mem's own
    no-subcommand contracts)."""
    env = style_env(db_path, workdir)
    run_cli(["style", "init", "python"], env)

    proc = run_cli(["style"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "python.md"


def test_list_text_mode_lists_filenames_alphabetically(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    run_cli(["style", "init", "rust"], env)
    run_cli(["style", "init", "go"], env)

    proc = run_cli(["style", "list"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().split("\n") == ["go.md", "rust.md"]


def test_list_json_shape_and_language_ordering(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    run_cli(["style", "init", "typescript"], env)
    run_cli(["style", "init", "python"], env)

    proc = run_cli(["style", "list", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert [row["language"] for row in rows] == ["python", "typescript"]  # ORDER BY language
    assert set(rows[0].keys()) == {"id", "project_id", "language", "source_path", "active", "created_at", "updated_at"}


def test_list_json_empty_project_is_empty_array(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "list", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


def test_list_json_scoped_to_active_project_only(db_path: Path, project_id: str, workdir: Path) -> None:
    other_project = insert_project(db_path, project_id="proj-other")
    now = _now()
    insert_style_row(
        db_path, other_project, style_id="019f0000-0000-7000-8000-000000000001",
        language="rust", source_path=str(workdir / "styles" / "rust.md"), created_at=now,
    )
    env = style_env(db_path, workdir)
    run_cli(["style", "init", "python"], env)

    proc = run_cli(["style", "list", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    languages = {row["language"] for row in json.loads(proc.stdout)}
    assert languages == {"python"}  # the "rust" row (other project) never appears


def test_list_no_project_registered_exits_1(db_path: Path, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "list"], env)

    assert proc.returncode == 1
    assert "no project registered" in proc.stderr


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------


def test_show_happy_path_prints_raw_file_content(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    run_cli(["style", "init", "python"], env)
    bundled = REPO_ROOT / "skills" / "context" / "styles" / "python.md"

    proc = run_cli(["style", "show", "python"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == bundled.read_text()  # byte-for-byte, no extra newline (bash-parity `cat`)


def test_show_json_wraps_content_with_metadata(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    run_cli(["style", "init", "python"], env)
    bundled = REPO_ROOT / "skills" / "context" / "styles" / "python.md"

    proc = run_cli(["style", "show", "python", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["language"] == "python"
    assert payload["source_path"] == str(workdir / "styles" / "python.md")
    assert payload["content"] == bundled.read_text()


def test_show_missing_lang_arg_exits_1(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "show"], env)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx style show <lang>" in proc.stderr


def test_show_never_initialized_language_exits_1_cat_style_message(
    db_path: Path, project_id: str, workdir: Path
) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "show", "python"], env)  # never init'd -> no dst file

    assert proc.returncode == 1
    expected_path = workdir / "styles" / "python.md"
    assert f"cat: {expected_path}: No such file or directory" in proc.stderr


def test_show_no_project_registered_exits_1(db_path: Path, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "show", "python"], env)

    assert proc.returncode == 1
    assert "no project registered" in proc.stderr


# --------------------------------------------------------------------------
# edit
# --------------------------------------------------------------------------


def test_edit_seeds_from_bundle_when_missing_then_invokes_editor(
    db_path: Path, project_id: str, workdir: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "editor_invoked_on.txt"
    editor = make_fake_editor(tmp_path, exit_code=0, marker_path=marker)
    env = style_env(db_path, workdir)
    env["EDITOR"] = str(editor)

    proc = run_cli(["style", "edit", "go"], env)

    assert proc.returncode == 0, proc.stderr
    dst = workdir / "styles" / "go.md"
    assert dst.is_file()  # seeded from the bundled source, since it didn't exist
    assert fetch_style_row(db_path, project_id, "go") is not None  # init_one's upsert ran
    assert marker.read_text().strip() == str(dst)  # editor was invoked with the dst path


def test_edit_existing_file_does_not_reinit_or_touch_row(
    db_path: Path, project_id: str, workdir: Path, tmp_path: Path
) -> None:
    styles_dir = workdir / "styles"
    styles_dir.mkdir(parents=True)
    dst = styles_dir / "python.md"
    dst.write_text("already here")
    old_ts = _now() - 10_000
    insert_style_row(
        db_path, project_id, style_id="019f0000-0000-7000-8000-000000000002",
        language="python", source_path=str(dst), created_at=old_ts, updated_at=old_ts,
    )
    editor = make_fake_editor(tmp_path, exit_code=0)
    env = style_env(db_path, workdir)
    env["EDITOR"] = str(editor)

    proc = run_cli(["style", "edit", "python"], env)

    assert proc.returncode == 0, proc.stderr
    assert dst.read_text() == "already here"  # never overwritten
    row = fetch_style_row(db_path, project_id, "python")
    assert row is not None
    assert row["updated_at"] == old_ts  # untouched — init_one never ran


def test_edit_propagates_nonzero_editor_exit_code(
    db_path: Path, project_id: str, workdir: Path, tmp_path: Path
) -> None:
    editor = make_fake_editor(tmp_path, exit_code=3)
    env = style_env(db_path, workdir)
    env["EDITOR"] = str(editor)

    proc = run_cli(["style", "edit", "rust"], env)

    assert proc.returncode == 3, proc.stderr  # bash: the editor's own exit status is the script's


def test_edit_missing_lang_arg_exits_1(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "edit"], env)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx style edit <lang>" in proc.stderr


def test_edit_unknown_language_never_initialized_exits_1(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "edit", "not-a-real-language"], env)

    assert proc.returncode == 1
    assert "ERROR: no bundled style for not-a-real-language" in proc.stderr


def test_edit_no_project_registered_exits_1(db_path: Path, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "edit", "python"], env)

    assert proc.returncode == 1
    assert "no project registered" in proc.stderr


# --------------------------------------------------------------------------
# Sub-app usage/exit-code parity.
# --------------------------------------------------------------------------


def test_unknown_subcommand_exits_1_with_usage_message(db_path: Path, project_id: str, workdir: Path) -> None:
    # Bash parity: cmd_style.sh's `*)` branch — exit 1 (NOT Click's default 2,
    # and NOT the exit-2 gap left by commands/mem.py's own unknown-subcommand
    # handling — see commands/style.py's module docstring for why this port
    # bypasses Typer's normal subcommand routing specifically to get this right).
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "bogus"], env)

    assert proc.returncode == 1
    assert proc.stderr.strip() == "ERROR: usage: shctx style <init|show|list|edit>"


def test_unknown_subcommand_still_gated_by_project_resolution(db_path: Path, workdir: Path) -> None:
    """Bash parity ordering: project_id resolves BEFORE the case dispatch,
    so even an unrecognized subcommand fails on the project gate first when
    no project is registered (not on the "unknown subcommand" message)."""
    env = style_env(db_path, workdir)  # no project seeded
    proc = run_cli(["style", "bogus"], env)

    assert proc.returncode == 1
    assert "no project registered" in proc.stderr
    assert "usage: shctx style <init" not in proc.stderr


def test_mkdir_dst_dir_happens_even_for_unknown_subcommand(db_path: Path, project_id: str, workdir: Path) -> None:
    """Bash parity: ``mkdir -p "$dst_dir"`` runs unconditionally, before the
    case dispatch — so even a bogus subcommand still creates the styles/
    destination directory as a side effect."""
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "bogus"], env)

    assert proc.returncode == 1
    assert (workdir / "styles").is_dir()


def test_json_flag_recognized_regardless_of_position(db_path: Path, project_id: str, workdir: Path) -> None:
    env = style_env(db_path, workdir)
    run_cli(["style", "init", "python"], env)

    after = run_cli(["style", "list", "--json"], env)
    before = run_cli(["style", "--json", "list"], env)

    assert after.returncode == 0, after.stderr
    assert before.returncode == 0, before.stderr
    assert json.loads(after.stdout) == json.loads(before.stdout)


def test_module_invocable_directly(db_path: Path, project_id: str, workdir: Path) -> None:
    """Smoke check: the shim/module path resolves without import errors."""
    env = style_env(db_path, workdir)
    proc = run_cli(["style", "--help"], env)

    assert proc.returncode == 0, proc.stderr
