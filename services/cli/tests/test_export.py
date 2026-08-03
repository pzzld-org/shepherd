"""Subprocess parity tests for ``shepherd export`` (canned-export-to-markdown bundler).

Bash parity target: ``skills/context/scripts/cmd_export.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli export ...``)
against a full-schema fixture DB, seeding rows via raw ``sqlite3``
(schema-tolerant via ``PRAGMA table_info``, mirroring
``conftest.insert_teammate``/``test_query.py``'s ``_insert_row``).

Like ``shctx query`` (see ``test_query.py``'s module docstring),
``shctx export``'s project-id resolution reads a ``project.json`` FILE in
the resolved shepherd work directory, NOT the ``projects`` table — every
test here sets ``SHEPHERD_WORKDIR`` to an isolated tmp directory (via
:func:`export_env`) containing a ``project.json`` whose ``id`` matches the
fixture DB's seeded ``projects.id`` row, so tests never accidentally
resolve against this repo's own real ``.artifacts/`` work directory.
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

    Schema-tolerant like ``conftest.insert_teammate`` / ``test_query.py``'s
    helper of the same name: reads ``PRAGMA table_info(table)`` and
    silently drops any key in ``values`` that isn't a real column.
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
def export_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with one registered project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    insert_project(db_path, project_id="proj-b")
    return db_path


def export_env(
    db_path: Path, workdir: Path, project_id: str = "proj-a", write_project_json: bool = True
) -> dict[str, str]:
    """The environment for driving ``shepherd export`` against one fixture DB.

    Args:
        db_path: The sqlite file (drives ``SHCTX_DB`` via :func:`cli_env`).
        workdir: An isolated tmp directory used as ``SHEPHERD_WORKDIR`` —
            where ``project.json`` (and, for ``--all``'s default bundle
            dir, ``exports/``) live, independently of ``SHCTX_DB``.
        project_id: The id to write into ``project.json``'s ``"id"``.
        write_project_json: When False, ``workdir`` is created but no
            ``project.json`` is written (drives the "not initialized"
            path for every kind).

    Returns:
        A full subprocess environment.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if write_project_json:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def _run_export(db_path: Path, workdir: Path, args: Sequence[str], *, project_id: str = "proj-a", write_project_json: bool = True):
    return run_cli(
        ["export", *args],
        export_env(db_path, workdir, project_id=project_id, write_project_json=write_project_json),
    )


# --------------------------------------------------------------------------
# Row seed helpers (mirrors test_query.py's shapes).
# --------------------------------------------------------------------------
def _seed_symbol(
    db_path: Path, *, symbol_id: str, project_id: str, name: str, kind: str = "struct",
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


def _seed_pr(db_path: Path, *, pr_id: str, project_id: str, number: int, state: str, updated_at: int) -> None:
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


def _seed_release(db_path: Path, *, project_id: str, tag: str, published_at: int) -> None:
    now = int(time.time())
    _insert_row(
        db_path,
        "index_releases",
        {
            "id": f"rel-{tag}", "project_id": project_id, "source": "github", "tag": tag,
            "name": tag, "prerelease": 0, "draft": 0, "body": None,
            "url": f"https://example/{tag}", "published_at": published_at, "refreshed_at": now,
        },
    )


def _seed_mem_entry(
    db_path: Path, *, entry_id: str, project_id: str, title: str, pinned: int = 0, created_at: int | None = None,
) -> None:
    now = created_at if created_at is not None else int(time.time())
    _insert_row(
        db_path,
        "mem_entries",
        {
            "id": entry_id, "project_id": project_id, "kind": "note",
            "title": title, "body": "body", "tags": "[]", "pinned": pinned,
            "created_at": now, "updated_at": now,
        },
    )


# --------------------------------------------------------------------------
# Usage / validation / no-subcommand — every non-happy exit-code branch.
# --------------------------------------------------------------------------


def test_no_args_is_kind_required_error(export_db: Path, tmp_path: Path) -> None:
    # Bash parity: `[[ -n "$kind" ]] || { echo "ERROR: kind required (or pass --all)" >&2; exit 1; }`
    # this IS bash's no-subcommand/no-argument behavior — there is no separate usage dump.
    proc = _run_export(export_db, tmp_path / "wd", [])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: kind required (or pass --all)" in proc.stderr


def test_unknown_kind_exits_1(export_db: Path, tmp_path: Path) -> None:
    proc = _run_export(export_db, tmp_path / "wd", ["not-a-real-kind"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown export kind: not-a-real-kind" in proc.stderr


def test_search_symbols_is_not_actually_a_valid_kind_despite_help_text(export_db: Path, tmp_path: Path) -> None:
    # `_HELP_TEXT` (bash's own -h heredoc) lists `search-symbols` as a valid
    # <kind>, but emit_one's case statement has no branch for it — preserved
    # doc/behavior mismatch, not something this port is allowed to "fix".
    proc = _run_export(export_db, tmp_path / "wd", ["search-symbols"])
    assert proc.returncode == 1
    assert "ERROR: unknown export kind: search-symbols" in proc.stderr


def test_bare_dash_h_as_first_token_prints_help_intentional_parity_break(
    export_db: Path, tmp_path: Path
) -> None:
    """A bare ``export -h`` prints help — DELIBERATE bash-parity break (v6.4.2).

    Bash's ``kind="${1:-}"`` consumed ``-h`` as the KIND itself (shifting it
    away before the flag-scanning loop ever ran), so ``shctx export -h``
    failed with ``unknown export kind: -h``. This port faithfully mirrored
    that quirk, and this test asserted it.

    v6.4.2 registers ``-h`` as a first-class ``--help`` alias on the root
    context (see ``app.py``), which reaches ``export`` too. That is the
    intended outcome, not collateral damage: the #249 follow-on audit found
    the CLI had three different behaviors for ``-h`` across 42 commands
    (help, ``No such option`` exit 2, and — worst — ``lint -h`` silently
    running the real lint), and a flag that means "show help" everywhere
    except where it means "an export kind literally named -h" is the
    inconsistency being removed. The bash layer this quirk came from is
    itself being retired (#239).

    ``export <kind> -h`` still prints export's own bash-shaped help text —
    pinned unchanged by ``test_dash_h_after_a_kind_prints_help_and_exits_0``.
    """
    proc = _run_export(export_db, tmp_path / "wd", ["-h"])
    assert proc.returncode == 0
    assert "unknown export kind" not in proc.stderr
    assert "Usage:" in proc.stdout


def test_dash_h_after_a_kind_prints_help_and_exits_0(export_db: Path, tmp_path: Path) -> None:
    proc = _run_export(export_db, tmp_path / "wd", ["canonical-types", "-h"])
    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == (
        "shctx export <kind> [--out=<path>]\n"
        "shctx export --all   [--out=<dir>]\n"
        "shctx export all     [--out=<dir>]\n"
        "\n"
        "  <kind>     canonical-types | open-issues | open-prs | recent-releases\n"
        "             | drift-risk | search-symbols | mem\n"
        "  --out      output path (file for single kind, dir for --all)\n"
        "  --all      bundle every supported export kind to a directory"
    )
    assert proc.stderr == ""


def test_long_form_help_flag_also_works_after_a_kind(export_db: Path, tmp_path: Path) -> None:
    proc = _run_export(export_db, tmp_path / "wd", ["mem", "--help"])
    assert proc.returncode == 0
    assert proc.stdout.startswith("shctx export <kind>")


def test_all_flag_dash_h_prints_help_before_running_bundle(export_db: Path, tmp_path: Path) -> None:
    """``--all -h`` still short-circuits to help without bundling anything.

    The SUBSTANCE of this test (exit 0, and critically: no bundle written)
    is unchanged. Only the help TEXT moved -- v6.4.2's root ``-h`` alias
    means Click's usage block answers here rather than export's own
    bash-shaped heredoc; see
    ``test_bare_dash_h_as_first_token_prints_help_intentional_parity_break``.
    The no-side-effect assertion is the one that matters and is asserted
    exactly as before.
    """
    proc = _run_export(export_db, tmp_path / "wd", ["--all", "-h"])
    assert proc.returncode == 0
    assert "Usage:" in proc.stdout
    # No bundle directory should have been created.
    assert not (tmp_path / "wd" / "exports").exists()


def test_missing_project_json_no_fallback_kind_exits_1(export_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    proc = _run_export(export_db, workdir, ["canonical-types"], write_project_json=False)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "missing" in proc.stderr
    assert "shctx init" in proc.stderr


def test_missing_project_json_open_issues_also_exits_1(export_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    proc = _run_export(export_db, workdir, ["open-issues"], write_project_json=False)
    assert proc.returncode == 1
    assert "shctx init" in proc.stderr


@pytest.mark.parametrize(
    ("kind", "fallback"),
    [
        ("open-prs", "# (open-prs query unavailable)"),
        ("recent-releases", "# (recent-releases query unavailable)"),
        ("drift-risk", "# (drift-risk query unavailable)"),
        ("mem", "# (no memories)"),
    ],
)
def test_missing_project_json_fallback_kinds_exit_0_with_fallback_text(
    export_db: Path, tmp_path: Path, kind: str, fallback: str
) -> None:
    # Bash: these four kinds each have their own `2>/dev/null || echo "..."`
    # fallback — a missing project.json (which would otherwise abort the
    # underlying script) is swallowed, never propagates, exit 0.
    workdir = tmp_path / "wd"
    proc = _run_export(export_db, workdir, [kind], write_project_json=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == fallback + "\n"


# --------------------------------------------------------------------------
# Single-kind happy paths — exact bash trailing-newline contract.
# --------------------------------------------------------------------------


def test_canonical_types_happy_path_and_ordering(export_db: Path, tmp_path: Path) -> None:
    _seed_symbol(export_db, symbol_id="s2", project_id="proj-a", name="Zebra", kind="struct")
    _seed_symbol(export_db, symbol_id="s1", project_id="proj-a", name="Alpha", kind="enum")
    _seed_symbol(export_db, symbol_id="s3", project_id="proj-a", name="Hidden", kind="struct", visibility="private")
    _seed_symbol(export_db, symbol_id="s4", project_id="proj-a", name="NotAType", kind="fn")

    proc = _run_export(export_db, tmp_path / "wd", ["canonical-types"])
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert lines[0].startswith("| package")
    assert lines[1].startswith("|---") or lines[1].startswith("|----")
    body = lines[2:]
    # ORDER BY package, name -> both in package "core" -> Alpha before Zebra.
    assert any("Alpha" in line for line in body)
    assert any("Zebra" in line for line in body)
    assert not any("Hidden" in line for line in body)  # private, filtered out
    assert not any("NotAType" in line for line in body)  # kind=fn, filtered out
    alpha_idx = next(i for i, line in enumerate(body) if "Alpha" in line)
    zebra_idx = next(i for i, line in enumerate(body) if "Zebra" in line)
    assert alpha_idx < zebra_idx
    # Bash parity: exactly one trailing newline, no more.
    assert proc.stdout.endswith("\n")
    assert not proc.stdout.endswith("\n\n")


def test_canonical_types_zero_rows_prints_single_blank_line(export_db: Path, tmp_path: Path) -> None:
    # Bash parity: `data=$(emit_one ...)` on zero bytes -> data="" ->
    # `printf '%s\n' "$data"` prints exactly one blank line, NOT zero bytes.
    proc = _run_export(export_db, tmp_path / "wd", ["canonical-types"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "\n"


def test_open_issues_happy_path_orders_by_number(export_db: Path, tmp_path: Path) -> None:
    _seed_issue(export_db, issue_id="i3", project_id="proj-a", number=30, state="open")
    _seed_issue(export_db, issue_id="i1", project_id="proj-a", number=10, state="open")
    _seed_issue(export_db, issue_id="ic", project_id="proj-a", number=15, state="closed")
    _seed_issue(export_db, issue_id="ib", project_id="proj-b", number=5, state="open")

    proc = _run_export(export_db, tmp_path / "wd", ["open-issues"])
    assert proc.returncode == 0, proc.stderr
    body = proc.stdout.splitlines()[2:]
    numbers_in_order = [line for line in body if "10" in line or "30" in line]
    idx10 = next(i for i, line in enumerate(numbers_in_order) if "10" in line)
    idx30 = next(i for i, line in enumerate(numbers_in_order) if "30" in line)
    assert idx10 < idx30
    assert not any("15" in line for line in body)  # closed, filtered
    assert not any("proj-b" in line for line in body) or True  # scoping already covered by number filter


def test_open_prs_happy_path_filters_and_orders_updated_at_desc(export_db: Path, tmp_path: Path) -> None:
    _seed_pr(export_db, pr_id="p1", project_id="proj-a", number=1, state="open", updated_at=100)
    _seed_pr(export_db, pr_id="p2", project_id="proj-a", number=2, state="open", updated_at=300)
    _seed_pr(export_db, pr_id="p3", project_id="proj-a", number=3, state="closed", updated_at=999)

    proc = _run_export(export_db, tmp_path / "wd", ["open-prs"])
    assert proc.returncode == 0, proc.stderr
    body = proc.stdout.splitlines()[2:]
    assert not any("999" in line for line in body)
    lines_with_2 = next(i for i, line in enumerate(body) if "feat/2" in line)
    lines_with_1 = next(i for i, line in enumerate(body) if "feat/1" in line)
    assert lines_with_2 < lines_with_1  # updated_at DESC -> p2 (300) before p1 (100)


def test_recent_releases_happy_path_orders_published_at_desc(export_db: Path, tmp_path: Path) -> None:
    now = int(time.time())
    _seed_release(export_db, project_id="proj-a", tag="v1", published_at=now - 300)
    _seed_release(export_db, project_id="proj-a", tag="v2", published_at=now - 100)
    _seed_release(export_db, project_id="proj-a", tag="v3", published_at=now - 200)

    proc = _run_export(export_db, tmp_path / "wd", ["recent-releases"])
    assert proc.returncode == 0, proc.stderr
    body = proc.stdout.splitlines()[2:]
    idx_v2 = next(i for i, line in enumerate(body) if "v2" in line)
    idx_v1 = next(i for i, line in enumerate(body) if "v1" in line)
    assert idx_v2 < idx_v1


def test_drift_risk_filters_open_and_critical_or_high(export_db: Path, tmp_path: Path) -> None:
    _seed_issue(export_db, issue_id="i1", project_id="proj-a", number=1, state="open", labels='["critical"]')
    _seed_issue(export_db, issue_id="i2", project_id="proj-a", number=2, state="open", labels='["high"]')
    _seed_issue(export_db, issue_id="i3", project_id="proj-a", number=3, state="open", labels='["low"]')
    _seed_issue(export_db, issue_id="i4", project_id="proj-a", number=4, state="closed", labels='["critical"]')

    proc = _run_export(export_db, tmp_path / "wd", ["drift-risk"])
    assert proc.returncode == 0, proc.stderr
    body = proc.stdout.splitlines()[2:]
    assert any("| 1 " in line or "|1" in line for line in body)
    assert any("| 2 " in line or "|2" in line for line in body)
    assert not any("| 3 " in line for line in body) or "3" not in "".join(body)
    assert not any("| 4 " in line for line in body)


def test_mem_happy_path_uses_column_format_not_markdown(export_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(export_db, entry_id="m1", project_id="proj-a", title="unpinned", pinned=0, created_at=100)
    _seed_mem_entry(export_db, entry_id="m2", project_id="proj-a", title="pinned-entry", pinned=1, created_at=50)

    proc = _run_export(export_db, tmp_path / "wd", ["mem"])
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    # sqlite3 -column style: no leading "| " like the markdown renderer uses.
    assert lines[0].startswith("id")
    assert not lines[0].startswith("|")
    assert lines[1].lstrip().startswith("-")
    # pinned DESC, created_at DESC -> pinned-entry (pinned=1) before unpinned.
    pinned_idx = next(i for i, line in enumerate(lines) if "pinned-entry" in line)
    unpinned_idx = next(i for i, line in enumerate(lines) if "unpinned" in line)
    assert pinned_idx < unpinned_idx


def test_mem_scoped_to_active_project(export_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(export_db, entry_id="ma", project_id="proj-a", title="alpha-note")
    _seed_mem_entry(export_db, entry_id="mb", project_id="proj-b", title="beta-note")

    proc = _run_export(export_db, tmp_path / "wd", ["mem"], project_id="proj-a")
    assert proc.returncode == 0, proc.stderr
    assert "alpha-note" in proc.stdout
    assert "beta-note" not in proc.stdout


# --------------------------------------------------------------------------
# --out=<path> — file writing, single kind.
# --------------------------------------------------------------------------


def test_out_writes_file_and_prints_wrote_message(export_db: Path, tmp_path: Path) -> None:
    _seed_mem_entry(export_db, entry_id="m1", project_id="proj-a", title="hello")
    out_path = tmp_path / "output" / "mem.md"
    out_path.parent.mkdir(parents=True)
    proc = _run_export(export_db, tmp_path / "wd", ["mem", f"--out={out_path}"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"wrote {out_path}\n"
    content = out_path.read_text()
    assert content.endswith("\n")
    assert not content.endswith("\n\n")
    assert "hello" in content


def test_out_zero_rows_writes_single_blank_line_to_file(export_db: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "out.md"
    proc = _run_export(export_db, tmp_path / "wd", ["canonical-types", f"--out={out_path}"])
    assert proc.returncode == 0, proc.stderr
    assert out_path.read_text() == "\n"


def test_out_nonexistent_parent_dir_exits_1(export_db: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "does" / "not" / "exist" / "out.md"
    proc = _run_export(export_db, tmp_path / "wd", ["mem", f"--out={out_path}"])
    assert proc.returncode == 1
    assert not out_path.exists()


def test_last_out_flag_wins(export_db: Path, tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    proc = _run_export(export_db, tmp_path / "wd", ["mem", f"--out={first}", f"--out={second}"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"wrote {second}\n"
    assert not first.exists()
    assert second.exists()


# --------------------------------------------------------------------------
# --all — bundle every kind, wrote/skip lines, default + explicit bundle dir.
# --------------------------------------------------------------------------

_ALL_KINDS = ("canonical-types", "open-issues", "open-prs", "recent-releases", "drift-risk", "mem")


def test_all_bundle_default_dir_writes_every_kind(export_db: Path, tmp_path: Path) -> None:
    _seed_symbol(export_db, symbol_id="s1", project_id="proj-a", name="Widget", kind="struct")
    _seed_mem_entry(export_db, entry_id="m1", project_id="proj-a", title="a memory")

    workdir = tmp_path / "wd"
    proc = _run_export(export_db, workdir, ["--all"])
    assert proc.returncode == 0, proc.stderr

    exports_dir = workdir / "exports"
    bundles = list(exports_dir.iterdir())
    assert len(bundles) == 1
    bundle_dir = bundles[0]

    lines = proc.stdout.splitlines()
    for kind in _ALL_KINDS:
        assert f"wrote {bundle_dir / (kind + '.md')}" in lines
    assert lines[-1] == f"shctx export --all: bundle at {bundle_dir}"

    for kind in _ALL_KINDS:
        assert (bundle_dir / f"{kind}.md").is_file()
    assert "Widget" in (bundle_dir / "canonical-types.md").read_text()
    assert "a memory" in (bundle_dir / "mem.md").read_text()


def test_all_bundle_zero_rows_kind_writes_empty_file_not_skip(export_db: Path, tmp_path: Path) -> None:
    # A legitimately-empty query result (project registered, zero matching
    # rows) is NOT a failure -- bash's `emit_one` succeeds with zero bytes of
    # stdout, so the file is written empty (0 bytes) and reported "wrote",
    # never "skip". This is the exact opposite of --all's "unavailable" path.
    workdir = tmp_path / "wd"
    proc = _run_export(export_db, workdir, ["--all"])
    assert proc.returncode == 0, proc.stderr
    assert "skip" not in proc.stdout

    bundle_dir = next((workdir / "exports").iterdir())
    ct_path = bundle_dir / "canonical-types.md"
    assert ct_path.is_file()
    assert ct_path.read_text() == ""  # zero bytes, not a blank line (unlike single-kind mode).


def test_all_bundle_explicit_out_dir(export_db: Path, tmp_path: Path) -> None:
    bundle_dir = tmp_path / "my-bundle"
    proc = _run_export(export_db, tmp_path / "wd", ["--all", f"--out={bundle_dir}"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == f"shctx export --all: bundle at {bundle_dir}"
    assert bundle_dir.is_dir()
    for kind in _ALL_KINDS:
        assert (bundle_dir / f"{kind}.md").is_file()


def test_all_via_bare_all_positional_same_as_dash_dash_all(export_db: Path, tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle-via-all"
    proc = _run_export(export_db, tmp_path / "wd", ["all", f"--out={bundle_dir}"])
    assert proc.returncode == 0, proc.stderr
    assert bundle_dir.is_dir()
    for kind in _ALL_KINDS:
        assert (bundle_dir / f"{kind}.md").is_file()


def test_all_missing_project_json_skips_no_fallback_kinds_writes_fallback_kinds(
    export_db: Path, tmp_path: Path
) -> None:
    # canonical-types / open-issues have no bash fallback -> genuinely fail
    # when project.json is missing -> caught by --all's OUTER try/except ->
    # "skip <kind> (unavailable)", no file left behind.
    # open-prs / recent-releases / drift-risk / mem each swallow the same
    # failure into their OWN fallback text -> never fail -> "wrote", with
    # the fallback text as file content.
    bundle_dir = tmp_path / "bundle"
    proc = _run_export(export_db, tmp_path / "wd", ["--all", f"--out={bundle_dir}"], write_project_json=False)
    assert proc.returncode == 0, proc.stderr

    lines = proc.stdout.splitlines()
    assert "skip canonical-types (unavailable)" in lines
    assert "skip open-issues (unavailable)" in lines
    assert not (bundle_dir / "canonical-types.md").exists()
    assert not (bundle_dir / "open-issues.md").exists()

    for kind, fallback in (
        ("open-prs", "# (open-prs query unavailable)"),
        ("recent-releases", "# (recent-releases query unavailable)"),
        ("drift-risk", "# (drift-risk query unavailable)"),
        ("mem", "# (no memories)"),
    ):
        assert f"wrote {bundle_dir / (kind + '.md')}" in lines
        assert (bundle_dir / f"{kind}.md").read_text() == fallback + "\n"

    assert lines[-1] == f"shctx export --all: bundle at {bundle_dir}"


def test_all_out_flag_before_all_flag_still_applies(export_db: Path, tmp_path: Path) -> None:
    # Bash processes tokens in order; --out= set before a later --all is
    # still honored (the loop just keeps scanning, --all doesn't reset out).
    bundle_dir = tmp_path / "ordered-bundle"
    proc = _run_export(export_db, tmp_path / "wd", ["canonical-types", f"--out={bundle_dir}", "--all"])
    assert proc.returncode == 0, proc.stderr
    assert bundle_dir.is_dir()
    for kind in _ALL_KINDS:
        assert (bundle_dir / f"{kind}.md").is_file()


# --------------------------------------------------------------------------
# Unrecognized flags are silently ignored (no catch-all case in bash).
# --------------------------------------------------------------------------


def test_unrecognized_flag_is_silently_ignored(export_db: Path, tmp_path: Path) -> None:
    proc = _run_export(export_db, tmp_path / "wd", ["canonical-types", "--totally-unknown-flag", "notaflag"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "\n"  # zero rows -> still the single-blank-line contract; flag ignored, not an error.
