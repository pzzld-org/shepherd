"""Subprocess parity tests for ``shepherd init`` (bash: ``cmd_init.sh`` + ``scaffold.sh``).

Every test drives the real CLI as a subprocess (``${PY} -m shepherd_cli
init ...``) under an ISOLATED, NON-git ``cwd`` and, for most scenarios, the
REAL ``CLAUDE_PLUGIN_ROOT`` (this checkout's own ``skills/context/`` tree)
so the base schema, migrations, and ``references/naming-conventions.md``
all resolve exactly like a real install — mirroring ``test_doctor.py``'s
isolation pattern, NOT ``conftest.run_cli``'s fixed ``cwd=CLI_ROOT``
(which sits inside THIS repo's own git working tree and would make
``resolve_repo_root()`` climb to this repo's real root instead of the
throwaway ``work_dir``).

``shepherd init`` is the ONE command in this package that CREATES the
sqlite file from scratch and narrates its own migration gap-fill to
stderr (see ``shepherd_cli/commands/init.py``'s module docstring) — this
suite therefore verifies the resulting on-disk state (directory tree,
``.gitignore``, ``CONVENTIONS.md``, ``project.json``, the ``projects``
row, ``schema_versions`` reaching HEAD) AND the exact stdout/stderr text
the legacy ``cmd_init.sh`` produced (the fixed-string assertions below
were captured byte-for-byte from the bash implementation before the bash
layer's retirement — they are the parity contract, kept with no runtime
dependency on the deleted scripts).

The trailing auto-refresh trigger is an IN-PROCESS call to
:func:`shepherd_cli.refresh_impl.refresh_artifacts` (the native port of
``refresh-artifacts.sh``) — covered three ways below: a CANARY
``refresh-artifacts.sh`` in a fake plugin root proves the bash script is
never executed anymore; a dropped-``artifacts``-table DB pins down
nonzero-exit propagation; an end-to-end test asserts the actual
``artifacts`` rows the native indexer writes (the same rows the bash
script wrote, verified identical during the port).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import stat
import subprocess
import time
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, build_full_schema_db, clean_env_dict

SCHEMA_DIR = REPO_ROOT / "skills" / "context" / "schema"
SCHEMA_BASE_SQL = SCHEMA_DIR / "0001_init.sql"
MIGRATIONS_DIR = SCHEMA_DIR / "migrations"
NAMING_CONVENTIONS_MD = REPO_ROOT / "skills" / "context" / "references" / "naming-conventions.md"

_USAGE_MARKER = "shctx init [--artifacts|--shepherd] [--no-config] [--no-doctor] [--user]"

#: The exact ``mkdir -p`` dir set from ``scaffold.sh``, relative to the
#: namespace root — see ``shepherd_cli/commands/init.py``'s
#: ``_SCAFFOLD_DIRS``.
_SCAFFOLD_DIR_NAMES = (
    "archive",
    "cache",
    "ctx",
    "docs/plans",
    "docs/reports",
    "docs/handoffs",
    "docs/specs",
    "docs/diagrams",
    "docs/journal",
    "logs",
    "scripts",
    "templates",
    "tmp",
    "types",
    "profiles",
    "styles",
)

_GITKEEP_DIR_NAMES = (
    "archive",
    "scripts",
    "templates",
    "types",
    "docs/plans",
    "docs/reports",
    "docs/journal",
    "docs/handoffs",
    "docs/diagrams",
)


def _shipped_migration_count() -> int:
    """Number of ``migrations/NNNN_*.sql`` files (excludes ``0001_init.sql`` itself)."""
    files = list(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert files, "no migration files found — fixture setup is broken"
    return len(files)


def _max_migration_version() -> int:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    return max(int(f.name[:4]) for f in files)


def _schema_versions(db_path: Path) -> tuple[int, int]:
    """``(MAX(version), COUNT(*))`` from ``schema_versions``."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COALESCE(MAX(version), 0), COUNT(*) FROM schema_versions;").fetchone()
    finally:
        conn.close()
    return int(row[0]), int(row[1])


def _projects_rows(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT id, name, scope, tags, created_at, updated_at FROM projects;").fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Isolation fixtures + subprocess helpers (mirrors test_doctor.py).
# --------------------------------------------------------------------------
@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh, non-git directory to use as the CLI's ``cwd`` / repo root fallback."""
    d = tmp_path / "work"
    d.mkdir()
    return d


def _init_env(
    *, workdir: Path | None = None, plugin_root: Path | None = None, home: Path | None = None
) -> dict[str, str]:
    """A stripped-then-rebuilt environment for a ``shepherd init`` test.

    Args:
        workdir: When given, sets ``SHEPHERD_WORKDIR`` (an absolute path,
            used as-is) so the namespace resolves inside it regardless of
            ``resolve_repo_root()``'s own git-toplevel/getcwd() fallback —
            most tests below instead rely on the plain non-git ``cwd``
            fallback (``work_dir`` IS the repo root, and the namespace is
            ``work_dir/.shepherd``), so this is only used for the
            few scenarios that need to decouple the two.
        plugin_root: ``CLAUDE_PLUGIN_ROOT`` override; defaults to this
            checkout's own real ``REPO_ROOT`` so the real base schema,
            migrations, and ``references/naming-conventions.md`` resolve.
        home: When given, sets ``SHEPHERD_HOME`` (an absolute path) so
            ``--user``/doctor's user-tier section resolve against an
            isolated, throwaway directory instead of the real host
            ``$HOME`` — see ``tests/test_home.py``'s identical
            ``_home_env`` isolation, required by every scenario below
            that touches ``--user`` (never omit ``home`` for one of
            those — the real ``$HOME`` must never be written to by this
            suite).
    """
    env = clean_env_dict()
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root if plugin_root is not None else REPO_ROOT)
    if workdir is not None:
        env["SHEPHERD_WORKDIR"] = str(workdir)
    if home is not None:
        env["SHEPHERD_HOME"] = str(home)
    return env


def run_init(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli init <args>`` under ``cwd``."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "init", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# --------------------------------------------------------------------------
# -h / --help / unknown flag.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("args", [["-h"], ["--help"]])
def test_help_variants_print_usage_and_exit_0(args: list[str], work_dir: Path) -> None:
    env = _init_env()
    proc = run_init(args, work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == (
        _USAGE_MARKER + "\n\n"
        "Scaffold the per-project shepherd namespace tree, create shepherd.db,\n"
        "register the host project, scaffold shepherd.toml, and run a closing\n"
        "doctor pass — one command, a fully configured project.\n\n"
        "Default: .shepherd/ (v5.0.0+). If either .shepherd/ or .artifacts/ already\n"
        "exists in the repo, that one is used (auto-detect). Use --artifacts to force\n"
        "the legacy .artifacts/ namespace for a NEW init.\n"
        "Legacy projects using root.db are detected automatically and left untouched.\n\n"
        "  --no-config   Skip scaffolding shepherd.toml.\n"
        "  --no-doctor   Skip the closing doctor pass.\n"
        "  --user        Also bootstrap ~/.shepherd (shepherd home init). Off by\n"
        "                default — the one step here that touches $HOME."
    )
    assert proc.stderr == ""
    assert not (work_dir / ".shepherd").exists()


def test_help_wins_even_after_other_tokens(work_dir: Path) -> None:
    """Bash parity: ``-h``/``--help`` found ANYWHERE in the arg list short-circuits immediately."""
    env = _init_env()
    proc = run_init(["--artifacts", "-h"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)
    assert not (work_dir / ".artifacts").exists()
    assert not (work_dir / ".shepherd").exists()


def test_unknown_flag_exits_1_with_bash_message(work_dir: Path) -> None:
    env = _init_env()
    proc = run_init(["--bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown init flag: --bogus"
    assert not (work_dir / ".shepherd").exists()


# --------------------------------------------------------------------------
# Happy path — bare invocation (no flags), bash-captured expected output.
# --------------------------------------------------------------------------
def test_bare_invocation_scaffolds_full_tree(work_dir: Path) -> None:
    env = _init_env()
    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    root = work_dir / ".shepherd"
    assert root.is_dir()

    for rel in _SCAFFOLD_DIR_NAMES:
        assert (root / rel).is_dir(), f"missing dir: {rel}"
    for rel in _GITKEEP_DIR_NAMES:
        assert (root / rel / ".gitkeep").is_file(), f"missing .gitkeep: {rel}"

    assert (root / ".gitignore").is_file()
    assert "shepherd.db" in (root / ".gitignore").read_text()
    assert (root / "CONVENTIONS.md").read_text() == NAMING_CONVENTIONS_MD.read_text()
    assert (root / "shepherd.db").is_file()
    assert (root / "project.json").is_file()


def test_bare_invocation_stdout_shape(work_dir: Path) -> None:
    """The pre-v6.4.2 opening two lines are still the FIRST two lines emitted --
    everything after them is the new seamless-bootstrap tail (config
    scaffold, closing summary, doctor pass); see
    `test_bare_invocation_full_seamless_bootstrap` for that tail's own
    content assertions."""
    env = _init_env()
    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) > 2
    assert lines[0] == f"shctx: initialized .shepherd/ at {work_dir / '.shepherd'}"
    assert lines[1].startswith("shctx: project_id = ")
    project_id = lines[1].removeprefix("shctx: project_id = ")
    assert len(project_id) == 36  # UUID shape


def test_bare_invocation_narrates_every_migration_to_stderr(work_dir: Path) -> None:
    """The narration lines (``shctx migrate: applying NNNN_*.sql``) match
    ``_lib.sh``'s ``shctx_apply_pending_migrations`` output exactly, one
    per shipped migration, in sorted order."""
    env = _init_env()
    proc = run_init([], work_dir, env)

    assert proc.returncode == 0
    expected = [f"shctx migrate: applying {f.name}" for f in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))]
    assert proc.stderr.splitlines() == expected


def test_schema_reaches_head(work_dir: Path) -> None:
    env = _init_env()
    proc = run_init([], work_dir, env)
    assert proc.returncode == 0, proc.stderr

    db_path = work_dir / ".shepherd" / "shepherd.db"
    max_version, count = _schema_versions(db_path)
    assert max_version == _max_migration_version()
    assert count == _shipped_migration_count() + 1  # +1 for 0001_init.sql's own self-insert


def test_projects_row_and_pidfile_are_consistent(work_dir: Path) -> None:
    env = _init_env()
    proc = run_init([], work_dir, env)
    assert proc.returncode == 0, proc.stderr

    db_path = work_dir / ".shepherd" / "shepherd.db"
    rows = _projects_rows(db_path)
    assert len(rows) == 1
    project_id, name, scope, tags, created_at, updated_at = rows[0]

    assert name == "work"
    assert json.loads(scope) == [str(work_dir)]
    assert tags == "[]"
    assert created_at == updated_at
    assert abs(created_at - int(time.time())) < 30

    pidfile = json.loads((work_dir / ".shepherd" / "project.json").read_text())
    assert pidfile["id"] == project_id
    assert isinstance(pidfile["scaffolded_at"], int)


# --------------------------------------------------------------------------
# --shepherd / --artifacts.
# --------------------------------------------------------------------------
def test_shepherd_flag_explicit_matches_default(work_dir: Path) -> None:
    env = _init_env()
    proc = run_init(["--shepherd"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert (work_dir / ".shepherd").is_dir()
    assert not (work_dir / ".artifacts").exists()


def test_artifacts_flag_creates_legacy_namespace(work_dir: Path) -> None:
    env = _init_env()
    proc = run_init(["--artifacts"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    root = work_dir / ".artifacts"
    assert root.is_dir()
    assert not (work_dir / ".shepherd").exists()
    for rel in _SCAFFOLD_DIR_NAMES:
        assert (root / rel).is_dir()
    assert (root / "shepherd.db").is_file()
    assert "shctx: initialized .artifacts/" in proc.stdout


def test_last_of_shepherd_and_artifacts_wins(work_dir: Path) -> None:
    """Bash parity: plain reassignment, last flag wins."""
    env = _init_env()
    proc = run_init(["--artifacts", "--shepherd"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert (work_dir / ".shepherd").is_dir()
    assert not (work_dir / ".artifacts").exists()


def test_auto_detect_prefers_existing_artifacts_namespace(work_dir: Path) -> None:
    """A bare (no-flag) init auto-detects a pre-existing ``.artifacts/`` namespace."""
    (work_dir / ".artifacts").mkdir()
    (work_dir / ".artifacts" / ".gitignore").touch()
    env = _init_env()

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert (work_dir / ".artifacts" / "shepherd.db").is_file()
    assert not (work_dir / ".shepherd").exists()
    assert "shctx: initialized .artifacts/" in proc.stdout


# --------------------------------------------------------------------------
# Conflict guard — both directions, byte-for-byte bash parity.
# --------------------------------------------------------------------------
def test_conflict_guard_artifacts_blocks_fresh_shepherd(work_dir: Path) -> None:
    (work_dir / ".artifacts").mkdir()
    (work_dir / ".artifacts" / ".gitignore").touch()
    env = _init_env()

    proc = run_init(["--shepherd"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == (
        "ERROR: .artifacts/ is already an initialized shctx namespace.\n"
        "  Creating .shepherd/ alongside it would cause a split-brain where shctx\n"
        "  data and shepherd.toml [paths] entries diverge.\n"
        "\n"
        "  To keep using .artifacts/ (recommended for existing projects):\n"
        "    shctx init --artifacts\n"
        "\n"
        "  To migrate to .shepherd/ (new default):\n"
        "    mv .artifacts .shepherd  # move your content first\n"
        "    shctx init --shepherd"
    )
    assert not (work_dir / ".shepherd").exists()


def test_conflict_guard_shepherd_blocks_fresh_artifacts(work_dir: Path) -> None:
    (work_dir / ".shepherd").mkdir()
    (work_dir / ".shepherd" / ".gitignore").touch()
    env = _init_env()

    proc = run_init(["--artifacts"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == (
        "ERROR: .shepherd/ is already an initialized shctx namespace.\n"
        "  Creating .artifacts/ alongside it would cause a split-brain.\n"
        "\n"
        "  To keep using .shepherd/ (recommended):\n"
        "    shctx init --shepherd"
    )
    assert not (work_dir / ".artifacts").exists()


def test_conflict_guard_only_fires_when_target_missing(work_dir: Path) -> None:
    """Re-running ``init`` on an EXISTING target namespace never triggers the guard,
    even when the other marker is also present (idempotent re-init, not a conflict)."""
    env = _init_env()
    first = run_init(["--shepherd"], work_dir, env)
    assert first.returncode == 0, first.stderr

    (work_dir / ".artifacts").mkdir()
    (work_dir / ".artifacts" / ".gitignore").touch()

    second = run_init(["--shepherd"], work_dir, env)
    assert second.returncode == 0, second.stderr


# --------------------------------------------------------------------------
# Idempotent re-init.
# --------------------------------------------------------------------------
def test_idempotent_reinit_preserves_project_id(work_dir: Path) -> None:
    env = _init_env()
    first = run_init([], work_dir, env)
    assert first.returncode == 0, first.stderr
    first_id = first.stdout.splitlines()[1].removeprefix("shctx: project_id = ")

    second = run_init([], work_dir, env)
    assert second.returncode == 0, second.stderr
    second_id = second.stdout.splitlines()[1].removeprefix("shctx: project_id = ")

    assert first_id == second_id

    db_path = work_dir / ".shepherd" / "shepherd.db"
    assert len(_projects_rows(db_path)) == 1  # INSERT OR IGNORE — no duplicate row


def test_idempotent_reinit_does_not_re_narrate_migrations(work_dir: Path) -> None:
    env = _init_env()
    first = run_init([], work_dir, env)
    assert first.returncode == 0
    assert first.stderr != ""  # every migration narrated on the fresh DB

    second = run_init([], work_dir, env)
    assert second.returncode == 0, second.stderr
    assert second.stderr == ""  # already at head — nothing to narrate


def test_idempotent_reinit_does_not_overwrite_gitignore_or_conventions(work_dir: Path) -> None:
    env = _init_env()
    run_init([], work_dir, env)
    gi_path = work_dir / ".shepherd" / ".gitignore"
    conv_path = work_dir / ".shepherd" / "CONVENTIONS.md"
    gi_path.write_text("# customized by the user\n")
    conv_path.write_text("# customized by the user\n")

    proc = run_init([], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert gi_path.read_text() == "# customized by the user\n"
    assert conv_path.read_text() == "# customized by the user\n"


# --------------------------------------------------------------------------
# project.json edge cases.
# --------------------------------------------------------------------------
def test_preexisting_pidfile_is_read_back_verbatim(work_dir: Path) -> None:
    root = work_dir / ".shepherd"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"id": "custom-project-id", "scaffolded_at": 123}))
    env = _init_env()

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx: project_id = custom-project-id" in proc.stdout
    # bash parity: an existing pidfile is read, never rewritten.
    assert json.loads((root / "project.json").read_text()) == {"id": "custom-project-id", "scaffolded_at": 123}


def test_pidfile_null_id_renders_as_the_string_null(work_dir: Path) -> None:
    """A present-but-JSON-``null`` ``"id"`` renders as the literal string
    ``null`` — ``jq -r '.id'``'s raw-output rendering, which the bash
    implementation printed on this exact fixture."""
    root = work_dir / ".shepherd"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"id": None}))
    env = _init_env()

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0
    assert "shctx: project_id = null" in proc.stdout


def test_malformed_pidfile_exits_1(work_dir: Path) -> None:
    root = work_dir / ".shepherd"
    root.mkdir()
    (root / "project.json").write_text("{not valid json")
    env = _init_env()

    proc = run_init([], work_dir, env)

    assert proc.returncode == 1
    assert "failed to parse" in proc.stderr
    assert "project.json" in proc.stderr


# --------------------------------------------------------------------------
# Self-heal — an existing, behind-HEAD DB gets gap-filled (v6.3.3 #200).
# --------------------------------------------------------------------------
def test_preexisting_partial_schema_db_gets_gap_filled(work_dir: Path) -> None:
    root = work_dir / ".shepherd"
    root.mkdir()
    db_path = root / "shepherd.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_BASE_SQL.read_text())
        conn.commit()
    finally:
        conn.close()
    # Only 0001 is recorded — every migrations/*.sql file reads as pending.
    env = _init_env()

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    max_version, count = _schema_versions(db_path)
    assert max_version == _max_migration_version()
    assert count == _shipped_migration_count() + 1
    expected = [f"shctx migrate: applying {f.name}" for f in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))]
    assert proc.stderr.splitlines() == expected


def test_hard_migration_failure_warns_but_does_not_abort_init(work_dir: Path, tmp_path: Path) -> None:
    """A genuinely broken migration file produces the ERROR + WARNING lines
    on stderr but ``init`` itself still exits 0 (bash parity: the
    ``|| echo WARNING`` in ``cmd_init.sh`` never causes the SCRIPT to
    abort — only ``shctx_apply_pending_migrations``'s own internal loop
    stops early)."""
    fake_root = tmp_path / "fake-plugin-root"
    schema_dir = fake_root / "skills" / "context" / "schema"
    migrations_dir = schema_dir / "migrations"
    references_dir = fake_root / "skills" / "context" / "references"
    scripts_dir = fake_root / "skills" / "context" / "scripts"
    migrations_dir.mkdir(parents=True)
    references_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)
    shutil.copyfile(SCHEMA_BASE_SQL, schema_dir / "0001_init.sql")
    shutil.copyfile(NAMING_CONVENTIONS_MD, references_dir / "naming-conventions.md")
    (migrations_dir / "0002_bad.sql").write_text("THIS IS NOT VALID SQL;;;")
    (scripts_dir / "shctx").write_text("#!/usr/bin/env bash\nexit 0\n")

    env = _init_env(plugin_root=fake_root)
    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx migrate: applying 0002_bad.sql" in proc.stderr
    assert "shctx migrate: ERROR applying 0002_bad.sql" in proc.stderr
    assert "shctx init: WARNING — schema migration incomplete; run 'shctx migrate'" in proc.stderr
    assert proc.stdout.startswith("shctx: initialized .shepherd/")


# --------------------------------------------------------------------------
# Auto-refresh trigger — native in-process indexer (no bash subprocess).
# --------------------------------------------------------------------------
def _make_canary_plugin_root(tmp_path: Path) -> Path:
    """A throwaway plugin root with the REAL schema and a CANARY ``refresh-artifacts.sh``.

    Layout: ``skills/context/{schema (real copy), references (real copy),
    scripts/{shctx, refresh-artifacts.sh (canary)}}`` — enough for
    ``_bootstrap_db``/``_copy_conventions`` to run against the real
    shipped schema. The canary script logs to ``$CALL_LOG`` if executed;
    the native ``_maybe_auto_refresh`` must never run it (the log staying
    absent is the load-bearing no-bash assertion).
    """
    fake_root = tmp_path / "fake-plugin-root"
    schema_dir = fake_root / "skills" / "context" / "schema"
    references_dir = fake_root / "skills" / "context" / "references"
    scripts_dir = fake_root / "skills" / "context" / "scripts"
    scripts_dir.mkdir(parents=True)
    references_dir.mkdir(parents=True)
    shutil.copytree(SCHEMA_DIR, schema_dir, dirs_exist_ok=True)
    shutil.copyfile(NAMING_CONVENTIONS_MD, references_dir / "naming-conventions.md")

    shctx_path = scripts_dir / "shctx"
    shctx_path.write_text("#!/usr/bin/env bash\nexit 0\n")
    shctx_path.chmod(shctx_path.stat().st_mode | stat.S_IEXEC)

    canary_path = scripts_dir / "refresh-artifacts.sh"
    canary_path.write_text('#!/usr/bin/env bash\necho "BASH-CANARY refresh-artifacts.sh" >> "$CALL_LOG"\nexit 0\n')
    canary_path.chmod(canary_path.stat().st_mode | stat.S_IEXEC)

    return fake_root


def _artifact_rows(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT kind, path, title FROM artifacts;").fetchall()
    finally:
        conn.close()


def test_auto_refresh_not_triggered_when_no_markdown_present(work_dir: Path, tmp_path: Path) -> None:
    fake_root = _make_canary_plugin_root(tmp_path)
    call_log = tmp_path / "calls.log"
    env = _init_env(plugin_root=fake_root)
    env["CALL_LOG"] = str(call_log)

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "detected" not in proc.stdout
    assert _artifact_rows(work_dir / ".shepherd" / "shepherd.db") == []
    assert not call_log.exists()


def test_auto_refresh_triggered_runs_native_indexer_not_bash(work_dir: Path, tmp_path: Path) -> None:
    fake_root = _make_canary_plugin_root(tmp_path)
    call_log = tmp_path / "calls.log"
    root = work_dir / ".shepherd" / "docs" / "plans"
    root.mkdir(parents=True)
    (root / "foo.plan.md").write_text("# Hello Plan\n")
    env = _init_env(plugin_root=fake_root)
    env["CALL_LOG"] = str(call_log)

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx: detected 2 pre-existing markdown file(s); auto-indexing" in proc.stdout
    assert "shctx refresh artifacts: ok" in proc.stdout
    # The rows were written by the native in-process indexer...
    assert _artifact_rows(work_dir / ".shepherd" / "shepherd.db") == [
        ("plan", ".shepherd/docs/plans/foo.plan.md", "Hello Plan")
    ]
    # ...and the bash sibling script was NEVER executed.
    assert not call_log.exists()


def test_auto_refresh_failure_propagates_exit_code(work_dir: Path, tmp_path: Path) -> None:
    """A failing artifacts refresh aborts ``init`` with the refresh's own
    nonzero exit code (bash parity: ``set -e`` on the trailing statement).
    Driven by a pre-existing DB already at schema HEAD whose ``artifacts``
    table was dropped — the refresh's INSERT then fails hard."""
    root = work_dir / ".shepherd"
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "foo.plan.md").write_text("# Hello Plan\n")
    db_path = root / "shepherd.db"
    build_full_schema_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE artifacts")
        conn.commit()
    finally:
        conn.close()

    proc = run_init([], work_dir, _init_env())

    assert proc.returncode == 1
    assert "shctx: detected 2 pre-existing markdown file(s); auto-indexing" in proc.stdout
    assert "no such table: artifacts" in proc.stderr


def test_auto_refresh_succeeds_without_scripts_dir(work_dir: Path, tmp_path: Path) -> None:
    """The native auto-refresh has NO dependency on the (retired) bash
    ``skills/context/scripts/`` tree: a schema-only plugin root (no
    ``scripts/`` at all) still indexes pre-existing markdown fine — the
    exact scenario that used to hard-fail with "bash shctx tooling not
    found" when this step shelled out."""
    fake_root = tmp_path / "schema-only-plugin-root"
    schema_dir = fake_root / "skills" / "context" / "schema"
    references_dir = fake_root / "skills" / "context" / "references"
    schema_dir.mkdir(parents=True)
    references_dir.mkdir(parents=True)
    shutil.copytree(SCHEMA_DIR, schema_dir, dirs_exist_ok=True)
    shutil.copyfile(NAMING_CONVENTIONS_MD, references_dir / "naming-conventions.md")

    root = work_dir / ".shepherd" / "docs" / "plans"
    root.mkdir(parents=True)
    (root / "foo.plan.md").write_text("# Hello Plan\n")
    env = _init_env(plugin_root=fake_root)

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh artifacts: ok" in proc.stdout
    assert _artifact_rows(work_dir / ".shepherd" / "shepherd.db") == [
        ("plan", ".shepherd/docs/plans/foo.plan.md", "Hello Plan")
    ]


# --------------------------------------------------------------------------
# v6.4.2 — the seamless bootstrap: config scaffold, closing summary, doctor
# pass, and the --no-config/--no-doctor/--user flags that opt in/out of them.
# --------------------------------------------------------------------------
def run_doctor(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli doctor <args>`` under ``cwd`` — the
    follow-up half of the "one command, fully configured, doctor passes"
    contract this section's tests exercise."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "doctor", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _bootstrap_summary_lines(stdout: str) -> list[str]:
    """The ``shctx init: bootstrap summary`` block's own indented lines
    (after its header, up to the next non-indented line or EOF)."""
    lines = stdout.splitlines()
    try:
        start = lines.index("shctx init: bootstrap summary") + 1
    except ValueError:
        return []
    end = start
    while end < len(lines) and lines[end].startswith("  "):
        end += 1
    return lines[start:end]


def test_bare_invocation_full_seamless_bootstrap(work_dir: Path) -> None:
    """``shepherd init`` ALONE takes a bare repo to a fully configured
    project: namespace tree, db at schema HEAD, a project row, and
    ``shepherd.toml`` all exist afterward — and a follow-up ``shepherd
    doctor`` reports no FAIL (the fresh-project refresh-zone WARNs are
    expected and are not a bootstrap defect — see
    ``shepherd_cli/commands/doctor.py``'s own module docstring)."""
    env = _init_env(home=work_dir.parent / "home")
    proc = run_init([], work_dir, env)
    assert proc.returncode == 0, proc.stderr

    root = work_dir / ".shepherd"
    assert root.is_dir()
    db_path = root / "shepherd.db"
    max_version, _count = _schema_versions(db_path)
    assert max_version == _max_migration_version()
    assert len(_projects_rows(db_path)) == 1
    toml_path = root / "shepherd.toml"
    assert toml_path.is_file()
    assert "[project]" in toml_path.read_text()

    assert "shctx init: bootstrap summary" in proc.stdout
    assert "shctx init: doctor pass" in proc.stdout

    doctor_proc = run_doctor([], work_dir, env)
    assert doctor_proc.returncode != 1, doctor_proc.stdout


def test_second_run_is_idempotent_and_reports_already_present(work_dir: Path) -> None:
    """Running ``shepherd init`` twice creates NOTHING the second time —
    same project row, same schema version, same ``shepherd.toml`` mtime —
    and the closing summary reports every step as already-present, never
    ``created``."""
    env = _init_env(home=work_dir.parent / "home")
    first = run_init([], work_dir, env)
    assert first.returncode == 0, first.stderr

    db_path = work_dir / ".shepherd" / "shepherd.db"
    toml_path = work_dir / ".shepherd" / "shepherd.toml"
    projects_before = _projects_rows(db_path)
    schema_before = _schema_versions(db_path)
    toml_mtime_before = toml_path.stat().st_mtime

    second = run_init([], work_dir, env)
    assert second.returncode == 0, second.stderr

    assert _projects_rows(db_path) == projects_before
    assert _schema_versions(db_path) == schema_before
    assert toml_path.stat().st_mtime == toml_mtime_before

    summary = _bootstrap_summary_lines(second.stdout)
    assert summary, second.stdout
    assert not any("created" in line for line in summary), summary
    assert any("namespace" in line and "already present" in line for line in summary), summary
    assert any(
        line.strip().startswith("db") and "already present" in line for line in summary
    ), summary
    assert any(
        line.strip().startswith("project") and "already registered" in line for line in summary
    ), summary
    assert any(
        "shepherd.toml" in line and "already present" in line for line in summary
    ), summary


def test_no_config_flag_skips_scaffold_but_doctor_still_runs(work_dir: Path) -> None:
    env = _init_env(home=work_dir.parent / "home")
    proc = run_init(["--no-config"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert not (work_dir / ".shepherd" / "shepherd.toml").exists()
    assert "shepherd.toml : skipped (--no-config)" in proc.stdout
    assert "shctx config: scaffolded" not in proc.stdout
    assert "shctx init: doctor pass" in proc.stdout  # the OTHER new step is unaffected


def test_no_doctor_flag_skips_doctor_pass_but_config_still_scaffolds(work_dir: Path) -> None:
    env = _init_env(home=work_dir.parent / "home")
    proc = run_init(["--no-doctor"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert (work_dir / ".shepherd" / "shepherd.toml").is_file()
    assert "shctx init: bootstrap summary" in proc.stdout
    assert "shctx init: doctor pass" not in proc.stdout
    assert "STATUS CATEGORY" not in proc.stdout  # the doctor report table itself never renders


def test_no_config_and_no_doctor_together_skip_both_on_disk_effects(work_dir: Path) -> None:
    """Bash-parity narrow behavior stays reachable: with both flags, the
    ON-DISK effect is byte-identical to the pre-v6.4.2 command (no
    ``shepherd.toml``, no doctor pass) — only the closing summary
    (unconditional, per the task's own flag list) is new stdout."""
    env = _init_env(home=work_dir.parent / "home")
    proc = run_init(["--no-config", "--no-doctor"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert not (work_dir / ".shepherd" / "shepherd.toml").exists()
    assert "shctx init: doctor pass" not in proc.stdout
    assert "shctx config:" not in proc.stdout
    lines = proc.stdout.splitlines()
    assert lines[0] == f"shctx: initialized .shepherd/ at {work_dir / '.shepherd'}"
    assert lines[1].startswith("shctx: project_id = ")
    summary = _bootstrap_summary_lines(proc.stdout)
    assert any("shepherd.toml" in line and "skipped (--no-config)" in line for line in summary)
    assert any("user tier" in line and "skipped" in line for line in summary)


def test_user_flag_bootstraps_home_and_reports_created(work_dir: Path) -> None:
    home_dir = work_dir.parent / "user-home"
    env = _init_env(home=home_dir)
    assert not home_dir.exists()

    proc = run_init(["--user"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert (home_dir / "profiles").is_dir()
    assert (home_dir / "templates").is_dir()
    summary = _bootstrap_summary_lines(proc.stdout)
    assert any("user tier" in line and "created" in line for line in summary), summary


def test_user_flag_off_by_default_never_touches_home(work_dir: Path) -> None:
    """``--user`` is opt-IN: a bare ``shepherd init`` must never create
    ``$SHEPHERD_HOME`` even though it is fully resolvable."""
    home_dir = work_dir.parent / "untouched-home"
    env = _init_env(home=home_dir)

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert not home_dir.exists()
    summary = _bootstrap_summary_lines(proc.stdout)
    assert any("user tier" in line and "skipped" in line for line in summary), summary


def test_user_flag_is_idempotent_on_second_run(work_dir: Path) -> None:
    home_dir = work_dir.parent / "user-home"
    env = _init_env(home=home_dir)

    first = run_init(["--user"], work_dir, env)
    assert first.returncode == 0, first.stderr

    second = run_init(["--user"], work_dir, env)
    assert second.returncode == 0, second.stderr

    summary = _bootstrap_summary_lines(second.stdout)
    assert any(
        "user tier" in line and "already present" in line for line in summary
    ), summary


def test_existing_shepherd_toml_is_never_clobbered(work_dir: Path) -> None:
    """A ``shepherd.toml`` an operator hand-edited BEFORE running
    ``shepherd init`` must survive byte-for-byte."""
    root = work_dir / ".shepherd"
    root.mkdir(parents=True)
    toml_path = root / "shepherd.toml"
    custom_content = "# hand-written, do not touch\n[project]\nname = \"custom\"\n"
    toml_path.write_text(custom_content)
    env = _init_env(home=work_dir.parent / "home")

    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert toml_path.read_text() == custom_content
    summary = _bootstrap_summary_lines(proc.stdout)
    assert any("shepherd.toml" in line and "already present" in line for line in summary), summary


def test_bootstrap_summary_reports_created_on_a_fresh_project(work_dir: Path) -> None:
    """The mirror image of the idempotent-second-run test: on a FIRST run
    every line reports ``created``/``registered``, never
    ``already``-anything."""
    env = _init_env(home=work_dir.parent / "home")
    proc = run_init([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    summary = _bootstrap_summary_lines(proc.stdout)
    assert summary, proc.stdout
    assert not any("already" in line for line in summary), summary
    assert any(line.strip().startswith("namespace") and "created" in line for line in summary)
    assert any(line.strip().startswith("db") and "created" in line for line in summary)
    assert any(line.strip().startswith("project") and "registered" in line for line in summary)
    assert any(line.strip().startswith("shepherd.toml") and "created" in line for line in summary)


def test_doctor_pass_matches_a_standalone_doctor_run(work_dir: Path) -> None:
    """The closing doctor pass calls :func:`shepherd_cli.commands.doctor.run`
    IN-PROCESS (imported, never reimplemented) — its report is therefore
    the SAME report machinery a standalone ``shepherd doctor`` run against
    the SAME now-bootstrapped project produces, not a hand-rolled subset
    of it. Compared structurally (row counts per status + the trailing
    tally line), not byte-for-byte: a ``du -h`` read between the two runs
    can legitimately round differently at KB granularity."""
    env = _init_env(home=work_dir.parent / "home")
    proc = run_init([], work_dir, env)
    assert proc.returncode == 0, proc.stderr

    doctor_proc = run_doctor([], work_dir, env)
    inline_report = proc.stdout.split("shctx init: doctor pass\n", 1)[1]

    assert inline_report.count("OK ") == doctor_proc.stdout.count("OK ")
    assert inline_report.count("WARN ") == doctor_proc.stdout.count("WARN ")
    assert inline_report.count("FAIL ") == doctor_proc.stdout.count("FAIL ")
    assert inline_report.splitlines()[-1] == doctor_proc.stdout.splitlines()[-1]
