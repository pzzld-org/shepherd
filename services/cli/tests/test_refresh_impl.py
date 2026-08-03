"""Fixture-tree tests for :mod:`shepherd_cli.refresh_impl` (native refresh stages).

Bash parity targets: ``skills/context/scripts/refresh-symbols.sh`` (v5.0.3),
``refresh-github.sh``, ``refresh-artifacts.sh`` — the three stage scripts
ported natively into ``shepherd_cli/refresh_impl.py``. Every test drives
the real CLI as a subprocess (``${PY} -m shepherd_cli refresh
--scope=<zone>``, the only way the stage functions are reachable) against
REAL fixture state:

* **symbols** — a fixture crate tree scanned via a stub ``cargo`` on
  ``PATH`` whose ``metadata`` output points at it (deterministic, no rust
  toolchain needed), asserting the exact ``index_symbols`` rows: every
  kind (fn/struct/trait/enum/const/static/type/mod), visibility peeling
  (``pub``/``pub(crate)``/private), modifier sequences (``async``,
  ``const fn``, ``unsafe extern "C"``), single + aliased + group
  re-exports, private-``use`` exclusion, and the stale-row sweep.
* **artifacts** — a markdown tree covering every classify() arm (dot and
  hyphen suffix forms, docs/diagrams/, docs/journal/, unclassified),
  the title pipeline's quote-stripping QUIRK, the 200-byte title cap, the
  262144-byte content cap, the content-column schema probe (with and
  without migration 0004), and upsert-on-rescan.
* **github** — a stub ``gh`` on ``PATH`` serving canned JSON, asserting
  the exact rows across all four index tables (including the
  literal-``'NULL'`` milestone quirk, ``jq -r`` null rendering, epoch
  conversions, and constructed release URLs), plus the ``shctx_gh_retry``
  loop: transient retry-then-succeed, retry exhaustion, non-transient
  fail-fast, and graceful gh absence.

The expected epoch values and row shapes below were captured from the REAL
bash scripts running on identical fixtures (byte-for-byte identical output
verified during the port) — they are independent anchors, not re-derived
from the code under test.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest
from conftest import build_full_schema_db, build_partial_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Shared environment plumbing.
# --------------------------------------------------------------------------


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _stage_env(
    tmp_path: Path,
    db_path: Path,
    *,
    bin_dir: Path | None = None,
    bare_path: bool = False,
    project_id: str = "proj-a",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """cli_env + an isolated ``SHEPHERD_WORKDIR`` (with ``project.json``) + PATH stubs.

    Args:
        tmp_path: The per-test temp directory; the workdir is
            ``tmp_path/wd``.
        db_path: The ``SHCTX_DB`` fixture DB.
        bin_dir: When given, prepended to ``PATH``.
        bare_path: When True, ``PATH`` is REPLACED by ``bin_dir`` — drives
            the which()-based graceful-absence branches.
        project_id: Written into ``<workdir>/project.json``.
        extra: Additional env vars.

    Returns:
        A full subprocess environment.
    """
    workdir = tmp_path / "wd"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    if bin_dir is not None:
        env["PATH"] = str(bin_dir) if bare_path else f"{bin_dir}{os.pathsep}{env['PATH']}"
    for key, value in (extra or {}).items():
        env[key] = value
    return env


@pytest.fixture
def full_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with the ``proj-a`` project registered."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    return db_path


# --------------------------------------------------------------------------
# symbols — fixture crate + stub cargo.
# --------------------------------------------------------------------------

_LIB_RS = """pub fn alpha() {}
    pub(crate) struct Beta { x: u8 }
async fn hidden_async() {}
pub async fn gamma() {}
pub const fn delta() {}
pub unsafe extern "C" fn epsilon() {}
const SECRET: u8 = 1;
pub const LIMIT: u8 = 2;
pub static COUNT: u8 = 3;
pub type Alias = u8;
pub mod submod {}
pub trait Doer {}
pub enum Kind { A }
use private::Thing;
pub use crate::alpha_mod::Renamed as Pub;
pub use crate::grp::{One, Two as Deux};
fn plain() {}
"""


def _make_crate(tmp_path: Path) -> Path:
    """A fixture crate directory with ``Cargo.toml`` + ``src/lib.rs``."""
    crate = tmp_path / "crate"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text('[package]\nname = "fixturecrate"\nversion = "0.1.0"\n')
    (crate / "src" / "lib.rs").write_text(_LIB_RS)
    return crate


def _make_cargo_stub(tmp_path: Path, crate: Path) -> Path:
    """A PATH dir with a ``cargo`` stub whose metadata points at ``crate``."""
    bin_dir = tmp_path / "cargo-bin"
    bin_dir.mkdir(exist_ok=True)
    metadata = tmp_path / "cargo-metadata.json"
    metadata.write_text(
        json.dumps({"packages": [{"name": "fixturecrate", "manifest_path": str(crate / "Cargo.toml")}]})
    )
    _write_executable(bin_dir / "cargo", f'#!/usr/bin/env bash\ncat "{metadata}"\n')
    return bin_dir


def _symbol_rows(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT name, kind, package, file_path, line, visibility, signature, language "
            "FROM index_symbols ORDER BY name, kind"
        ).fetchall()
    finally:
        conn.close()


def test_symbols_indexes_every_kind_visibility_and_reexport(full_db: Path, tmp_path: Path) -> None:
    crate = _make_crate(tmp_path)
    env = _stage_env(tmp_path, full_db, bin_dir=_make_cargo_stub(tmp_path, crate))

    proc = run_cli(["refresh", "--scope=symbols"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh symbols: ok"

    pkg = str(crate)
    lib = str(crate / "src" / "lib.rs")
    expected = sorted(
        [
            ("alpha", "fn", pkg, lib, 1, "pub", "pub fn alpha() {}", "rust"),
            ("Beta", "struct", pkg, lib, 2, "pub(crate)", "pub(crate) struct Beta { x: u8 }", "rust"),
            ("hidden_async", "fn", pkg, lib, 3, "private", "async fn hidden_async() {}", "rust"),
            ("gamma", "fn", pkg, lib, 4, "pub", "pub async fn gamma() {}", "rust"),
            ("delta", "fn", pkg, lib, 5, "pub", "pub const fn delta() {}", "rust"),
            ("epsilon", "fn", pkg, lib, 6, "pub", 'pub unsafe extern "C" fn epsilon() {}', "rust"),
            ("SECRET", "const", pkg, lib, 7, "private", "const SECRET: u8 = 1;", "rust"),
            ("LIMIT", "const", pkg, lib, 8, "pub", "pub const LIMIT: u8 = 2;", "rust"),
            ("COUNT", "static", pkg, lib, 9, "pub", "pub static COUNT: u8 = 3;", "rust"),
            ("Alias", "type", pkg, lib, 10, "pub", "pub type Alias = u8;", "rust"),
            ("submod", "mod", pkg, lib, 11, "pub", "pub mod submod {}", "rust"),
            ("Doer", "trait", pkg, lib, 12, "pub", "pub trait Doer {}", "rust"),
            ("Kind", "enum", pkg, lib, 13, "pub", "pub enum Kind { A }", "rust"),
            # Line 14's private `use private::Thing;` is deliberately NOT indexed.
            ("Pub", "re-export", pkg, lib, 15, "pub", "pub use crate::alpha_mod::Renamed as Pub;", "rust"),
            ("One", "re-export", pkg, lib, 16, "pub", "pub use crate::grp::{One, Two as Deux};", "rust"),
            ("Deux", "re-export", pkg, lib, 16, "pub", "pub use crate::grp::{One, Two as Deux};", "rust"),
            ("plain", "fn", pkg, lib, 17, "private", "fn plain() {}", "rust"),
        ],
        key=lambda row: (row[0], row[1]),
    )
    assert _symbol_rows(full_db) == expected


def test_symbols_sweeps_stale_rust_rows_but_keeps_other_languages(
    full_db: Path, tmp_path: Path
) -> None:
    crate = _make_crate(tmp_path)
    conn = sqlite3.connect(str(full_db))
    try:
        conn.execute(
            "INSERT INTO index_symbols (id, project_id, name, kind, package, file_path, line, "
            "visibility, signature, doc_summary, language, hash, refreshed_at) "
            "VALUES ('stale-rust', 'proj-a', 'OldSym', 'fn', 'oldpkg', 'old.rs', 1, 'pub', 'x', NULL, 'rust', 'h1', 1)"
        )
        conn.execute(
            "INSERT INTO index_symbols (id, project_id, name, kind, package, file_path, line, "
            "visibility, signature, doc_summary, language, hash, refreshed_at) "
            "VALUES ('old-python', 'proj-a', 'PySym', 'fn', 'pypkg', 'old.py', 1, 'pub', 'y', NULL, 'python', 'h2', 1)"
        )
        conn.commit()
    finally:
        conn.close()
    env = _stage_env(tmp_path, full_db, bin_dir=_make_cargo_stub(tmp_path, crate))

    proc = run_cli(["refresh", "--scope=symbols"], env)

    assert proc.returncode == 0, proc.stderr
    names = {row[0]: row[7] for row in _symbol_rows(full_db)}
    assert "OldSym" not in names  # stale rust row swept (refreshed_at < now)
    assert names.get("PySym") == "python"  # non-rust rows untouched by the sweep


def test_symbols_rescan_is_idempotent(full_db: Path, tmp_path: Path) -> None:
    crate = _make_crate(tmp_path)
    env = _stage_env(tmp_path, full_db, bin_dir=_make_cargo_stub(tmp_path, crate))

    first = run_cli(["refresh", "--scope=symbols"], env)
    assert first.returncode == 0, first.stderr
    count_after_first = len(_symbol_rows(full_db))

    second = run_cli(["refresh", "--scope=symbols"], env)
    assert second.returncode == 0, second.stderr
    assert len(_symbol_rows(full_db)) == count_after_first  # upsert on (project,name,package,kind)


# --------------------------------------------------------------------------
# artifacts — markdown classification, title/content pipelines, schema probe.
# --------------------------------------------------------------------------


def _artifact_rows(db_path: Path, *, with_content: bool = True) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        cols = "kind, path, title, hash" + (", content" if with_content else "")
        return conn.execute(f"SELECT {cols} FROM artifacts ORDER BY path").fetchall()  # noqa: S608
    finally:
        conn.close()


def test_artifacts_classifies_every_kind_and_skips_unclassified(
    full_db: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    (workdir / "docs" / "plans").mkdir(parents=True)
    (workdir / "docs" / "diagrams").mkdir(parents=True)
    (workdir / "docs" / "journal").mkdir(parents=True)
    (workdir / "docs" / "specs").mkdir(parents=True)
    (workdir / "docs" / "plans" / "foo.plan.md").write_text("# Hello Plan\nbody\n")
    (workdir / "docs" / "plans" / "2026-01-01-bar-seed.md").write_text("# Bar Seed\n")  # hyphen form
    (workdir / "docs" / "diagrams" / "arch.md").write_text("diagram no heading\n")
    (workdir / "docs" / "journal" / "day1.md").write_text("# Journal Day 1\n")
    (workdir / "docs" / "specs" / "thing.spec.md").write_text("# Spec Here\n")
    (workdir / "notes.md").write_text("# Not classified\n")  # no suffix, no kind dir -> skipped

    env = _stage_env(tmp_path, full_db)
    proc = run_cli(["refresh", "--scope=artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh artifacts: ok"
    rows = _artifact_rows(full_db, with_content=False)
    by_path = {Path(path).name: kind for kind, path, _title, _hash in rows}
    assert by_path == {
        "arch.md": "diagram",
        "day1.md": "journal",
        "2026-01-01-bar-seed.md": "seed",
        "foo.plan.md": "plan",
        "thing.spec.md": "spec",
    }
    # Titles: heading marker stripped; a heading-less first line kept verbatim.
    titles = {Path(path).name: title for _kind, path, title, _hash in rows}
    assert titles["foo.plan.md"] == "Hello Plan"
    assert titles["arch.md"] == "diagram no heading"


def test_artifacts_title_strips_single_quotes_and_content_is_verbatim(
    full_db: Path, tmp_path: Path
) -> None:
    """The bash title pipeline's ``s/'//g`` QUIRK removes quotes from the
    stored TITLE, while the content pipeline stores the original text
    (minus command-substitution-stripped trailing newlines)."""
    workdir = tmp_path / "wd"
    (workdir / "docs" / "plans").mkdir(parents=True)
    (workdir / "docs" / "plans" / "q.plan.md").write_text("# It's a 'plan'\nbody with a 'quote'\n")

    env = _stage_env(tmp_path, full_db)
    proc = run_cli(["refresh", "--scope=artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    ((kind, _path, title, _hash, content),) = _artifact_rows(full_db)
    assert kind == "plan"
    assert title == "Its a plan"  # quotes REMOVED (bash sed quirk), heading marker stripped
    assert content == "# It's a 'plan'\nbody with a 'quote'"  # verbatim, trailing newline stripped


def test_artifacts_title_and_content_byte_caps(full_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    (workdir / "docs" / "plans").mkdir(parents=True)
    (workdir / "docs" / "plans" / "big.plan.md").write_bytes(b"x" * 300000)

    env = _stage_env(tmp_path, full_db)
    proc = run_cli(["refresh", "--scope=artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    ((_kind, _path, title, _hash, content),) = _artifact_rows(full_db)
    assert title == "x" * 200  # head -c 200
    assert content == "x" * 262144  # head -c 262144


def test_artifacts_hash_is_sha256_of_full_file_content(full_db: Path, tmp_path: Path) -> None:
    import hashlib

    workdir = tmp_path / "wd"
    (workdir / "docs" / "plans").mkdir(parents=True)
    body = b"# Hashed\nsome body\n"
    (workdir / "docs" / "plans" / "h.plan.md").write_bytes(body)

    env = _stage_env(tmp_path, full_db)
    proc = run_cli(["refresh", "--scope=artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    ((_kind, _path, _title, digest, _content),) = _artifact_rows(full_db)
    assert digest == hashlib.sha256(body).hexdigest()  # shasum -a 256 "$f"


def test_artifacts_rescan_upserts_on_project_and_path(full_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    plans = workdir / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "foo.plan.md").write_text("# Old Title\n")
    env = _stage_env(tmp_path, full_db)

    first = run_cli(["refresh", "--scope=artifacts"], env)
    assert first.returncode == 0, first.stderr

    (plans / "foo.plan.md").write_text("# New Title\nchanged\n")
    second = run_cli(["refresh", "--scope=artifacts"], env)
    assert second.returncode == 0, second.stderr

    rows = _artifact_rows(full_db, with_content=False)
    assert len(rows) == 1  # ON CONFLICT(project_id, path) — no duplicate row
    assert rows[0][2] == "New Title"


def test_artifacts_pre_0004_schema_without_content_column_still_indexes(
    tmp_path: Path,
) -> None:
    """The ``has_content_col`` probe: a DB predating migration 0004 (no
    ``artifacts.content`` column) gets the content-less UPSERT."""
    db_path = tmp_path / "shepherd.db"
    build_partial_schema_db(db_path)  # 0001 + 0007 only — artifacts has no content column
    insert_project(db_path, project_id="proj-a")
    workdir = tmp_path / "wd"
    (workdir / "docs" / "plans").mkdir(parents=True)
    (workdir / "docs" / "plans" / "foo.plan.md").write_text("# Hello Plan\n")

    env = _stage_env(tmp_path, db_path)
    proc = run_cli(["refresh", "--scope=artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(artifacts)")}
        rows = conn.execute("SELECT kind, title FROM artifacts").fetchall()
    finally:
        conn.close()
    assert "content" not in columns  # the fixture really is pre-0004
    assert rows == [("plan", "Hello Plan")]


# --------------------------------------------------------------------------
# github — stub gh with canned JSON; the four index tables + retry loop.
# --------------------------------------------------------------------------

_GH_STUB = """#!/usr/bin/env bash
if [ "${FAKE_GH_RC:-0}" != "0" ]; then echo "stub gh: boom" >&2; exit "$FAKE_GH_RC"; fi
case "$1" in
  repo) printf 'acme/widget\\n' ;;
  issue)
    n=0
    if [ -n "${RETRY_COUNT_FILE:-}" ] && [ -f "$RETRY_COUNT_FILE" ]; then n=$(cat "$RETRY_COUNT_FILE"); fi
    if [ -n "${RETRY_COUNT_FILE:-}" ]; then echo $((n+1)) > "$RETRY_COUNT_FILE"; fi
    if [ "$n" -lt "${FAIL_ISSUE_TIMES:-0}" ]; then echo "HTTP 504" >&2; exit 1; fi
    cat "$FAKE_GH_DIR/issues.json" ;;
  pr) cat "$FAKE_GH_DIR/prs.json" ;;
  release) cat "$FAKE_GH_DIR/releases.json" ;;
  api) cat "$FAKE_GH_DIR/milestones.json" ;;
  *) exit 1 ;;
esac
"""

_ISSUES_JSON = [
    {
        "number": 1,
        "title": "First bug's title",
        "state": "OPEN",
        "labels": [{"name": "bug"}, {"name": "p1"}],
        "milestone": {"title": "v1.0"},
        "assignees": [{"login": "joe"}],
        "body": "It breaks.",
        "url": "https://github.com/acme/widget/issues/1",
        "createdAt": "2026-01-02T03:04:05Z",
        "updatedAt": "2026-01-03T00:00:00Z",
    },
    {
        "number": 2,
        "title": "Second",
        "state": "CLOSED",
        "labels": [],
        "milestone": None,
        "assignees": [],
        "body": None,
        "url": "https://github.com/acme/widget/issues/2",
        "createdAt": "2026-02-01T00:00:00Z",
        "updatedAt": "2026-02-02T00:00:00Z",
    },
]

_PRS_JSON = [
    {
        "number": 7,
        "title": "Add widget",
        "state": "MERGED",
        "baseRefName": "main",
        "headRefName": "feat/widget",
        "labels": [{"name": "enhancement"}],
        "url": "https://github.com/acme/widget/pull/7",
        "createdAt": "2026-03-01T00:00:00Z",
        "updatedAt": "2026-03-02T00:00:00Z",
        "mergedAt": "2026-03-02T12:00:00Z",
    },
    {
        "number": 8,
        "title": "WIP",
        "state": "OPEN",
        "baseRefName": "main",
        "headRefName": "feat/wip",
        "labels": [],
        "url": "https://github.com/acme/widget/pull/8",
        "createdAt": "2026-03-05T00:00:00Z",
        "updatedAt": "2026-03-05T01:00:00Z",
        "mergedAt": None,
    },
]

_RELEASES_JSON = [
    {
        "tagName": "v1.0.0",
        "name": "One point oh",
        "isDraft": False,
        "isPrerelease": False,
        "publishedAt": "2026-04-01T00:00:00Z",
    },
    {"tagName": "v1.1.0-rc1", "name": None, "isDraft": True, "isPrerelease": True, "publishedAt": None},
]

_MILESTONES_JSON = [
    {
        "number": 3,
        "title": "v1.0",
        "state": "open",
        "due_on": "2026-05-01T00:00:00Z",
        "description": "Big one",
        "html_url": "https://github.com/acme/widget/milestone/3",
    },
    {
        "number": 4,
        "title": "backlog",
        "state": "closed",
        "due_on": None,
        "description": None,
        "html_url": "https://github.com/acme/widget/milestone/4",
    },
]


def _make_gh_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Write the gh stub + canned JSON; returns ``(bin_dir, data_dir)``."""
    bin_dir = tmp_path / "gh-bin"
    bin_dir.mkdir(exist_ok=True)
    _write_executable(bin_dir / "gh", _GH_STUB)
    data_dir = tmp_path / "gh-data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "issues.json").write_text(json.dumps(_ISSUES_JSON))
    (data_dir / "prs.json").write_text(json.dumps(_PRS_JSON))
    (data_dir / "releases.json").write_text(json.dumps(_RELEASES_JSON))
    (data_dir / "milestones.json").write_text(json.dumps(_MILESTONES_JSON))
    return bin_dir, data_dir


def _github_env(tmp_path: Path, db_path: Path, **extra: str) -> dict[str, str]:
    bin_dir, data_dir = _make_gh_fixture(tmp_path)
    return _stage_env(tmp_path, db_path, bin_dir=bin_dir, extra={"FAKE_GH_DIR": str(data_dir), **extra})


def test_github_indexes_all_four_tables_with_bash_verified_rows(
    full_db: Path, tmp_path: Path
) -> None:
    env = _github_env(tmp_path, full_db)
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh github: ok"

    conn = sqlite3.connect(str(full_db))
    try:
        issues = conn.execute(
            "SELECT id, project_id, source, number, title, state, labels, milestone, assignees, "
            "body, url, created_at, updated_at FROM index_issues ORDER BY number"
        ).fetchall()
        prs = conn.execute(
            "SELECT id, number, title, state, base_branch, head_branch, labels, url, "
            "created_at, updated_at, merged_at FROM index_prs ORDER BY number"
        ).fetchall()
        releases = conn.execute(
            "SELECT id, tag, name, prerelease, draft, body, url, published_at "
            "FROM index_releases ORDER BY tag"
        ).fetchall()
        milestones = conn.execute(
            "SELECT id, number, title, state, due_on, description, url "
            "FROM index_milestones ORDER BY number"
        ).fetchall()
    finally:
        conn.close()

    # Epoch values below were produced by the REAL refresh-github.sh on this
    # exact canned data (bash/python rows verified byte-identical).
    assert issues == [
        (
            "github:acme/widget#1",
            "proj-a",
            "github",
            1,
            "First bug's title",
            "open",
            '["bug","p1"]',
            "v1.0",
            '["joe"]',
            "It breaks.",
            "https://github.com/acme/widget/issues/1",
            1767323045,
            1767398400,
        ),
        (
            "github:acme/widget#2",
            "proj-a",
            "github",
            2,
            "Second",
            "closed",
            "[]",
            "NULL",  # bash quirk: '${milestone:-NULL}' stores the literal string
            "[]",
            "null",  # jq -r renders JSON null as the literal string
            "https://github.com/acme/widget/issues/2",
            1769904000,
            1769990400,
        ),
    ]
    assert prs == [
        (
            "github:acme/widget#pr7",
            7,
            "Add widget",
            "merged",
            "main",
            "feat/widget",
            '["enhancement"]',
            "https://github.com/acme/widget/pull/7",
            1772323200,
            1772409600,
            1772452800,
        ),
        (
            "github:acme/widget#pr8",
            8,
            "WIP",
            "open",
            "main",
            "feat/wip",
            "[]",
            "https://github.com/acme/widget/pull/8",
            1772668800,
            1772672400,
            None,  # unmerged -> real SQL NULL (unquoted NULL in bash)
        ),
    ]
    assert releases == [
        (
            "github:acme/widget:tag:v1.0.0",
            "v1.0.0",
            "One point oh",
            0,
            0,
            None,
            "https://github.com/acme/widget/releases/tag/v1.0.0",  # constructed URL
            1775001600,
        ),
        (
            "github:acme/widget:tag:v1.1.0-rc1",
            "v1.1.0-rc1",
            "",  # .name // empty
            1,
            1,
            None,
            "https://github.com/acme/widget/releases/tag/v1.1.0-rc1",
            None,  # unpublished draft
        ),
    ]
    assert milestones == [
        (
            "github:acme/widget:ms:3",
            3,
            "v1.0",
            "open",
            1777593600,
            "Big one",
            "https://github.com/acme/widget/milestone/3",
        ),
        (
            "github:acme/widget:ms:4",
            4,
            "backlog",
            "closed",
            None,  # no due date -> real SQL NULL
            "",  # .description // empty
            "https://github.com/acme/widget/milestone/4",
        ),
    ]


def test_github_rescan_upserts_without_duplicates(full_db: Path, tmp_path: Path) -> None:
    env = _github_env(tmp_path, full_db)
    first = run_cli(["refresh", "--scope=github"], env)
    assert first.returncode == 0, first.stderr
    second = run_cli(["refresh", "--scope=github"], env)
    assert second.returncode == 0, second.stderr

    conn = sqlite3.connect(str(full_db))
    try:
        counts = [
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in ("index_issues", "index_prs", "index_releases", "index_milestones")
        ]
    finally:
        conn.close()
    assert counts == [2, 2, 2, 2]


def test_github_transient_failure_retries_then_succeeds(full_db: Path, tmp_path: Path) -> None:
    env = _github_env(
        tmp_path,
        full_db,
        RETRY_COUNT_FILE=str(tmp_path / "retry-count"),
        FAIL_ISSUE_TIMES="1",  # first `gh issue list` call emits "HTTP 504" and fails
        SHCTX_GH_RETRY_BACKOFF="0",  # 0**attempt -> zero sleep, deterministic and fast
    )
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx_gh_retry: transient failure (attempt 1/3); retrying in 0s..." in proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh github: ok"
    conn = sqlite3.connect(str(full_db))
    try:
        count = conn.execute("SELECT COUNT(*) FROM index_issues").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_github_transient_failures_exhaust_retries_and_fail(full_db: Path, tmp_path: Path) -> None:
    env = _github_env(
        tmp_path,
        full_db,
        RETRY_COUNT_FILE=str(tmp_path / "retry-count"),
        FAIL_ISSUE_TIMES="99",
        SHCTX_GH_RETRY_MAX="2",
        SHCTX_GH_RETRY_BACKOFF="0",
    )
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 1
    assert "shctx_gh_retry: exhausted 2 attempts; last output:" in proc.stderr
    assert (tmp_path / "retry-count").read_text().strip() == "2"  # exactly max_attempts calls


def test_github_non_transient_failure_fails_fast_without_retry(
    full_db: Path, tmp_path: Path
) -> None:
    env = _github_env(tmp_path, full_db, FAKE_GH_RC="4")
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 4
    assert "stub gh: boom" in proc.stderr
    assert "shctx_gh_retry: transient failure" not in proc.stderr
    assert "shctx refresh github: ok" not in proc.stdout


def test_github_missing_gh_binary_skips_gracefully(full_db: Path, tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = _stage_env(tmp_path, full_db, bin_dir=empty_bin, bare_path=True)
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx: gh CLI not installed; skipping github refresh"
