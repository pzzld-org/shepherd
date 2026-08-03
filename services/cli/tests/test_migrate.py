"""Subprocess parity tests for ``shepherd migrate`` (bash: ``cmd_migrate.sh``).

Bash parity target: ``skills/context/scripts/cmd_migrate.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli migrate
...``), never by importing ``shepherd_cli`` into the pytest process
itself — matching every other command's test suite in this package.

Two independent branches under test:

1. **Default schema-migration gap-fill.** Seeded via
   ``conftest.build_partial_schema_db`` (a DB left behind at
   ``schema_versions = {1}`` even though migration 0007's tables already
   exist on disk — the exact #200 fixture shape) and
   ``conftest.build_full_schema_db`` (already at shipped HEAD). Assertions
   are anchored against the REAL ``skills/context/schema/migrations/``
   directory's shipped file set (:data:`_SHIPPED_MIGRATIONS`), so this
   suite automatically tracks any future migration added to the repo
   without needing an update — exactly like ``test_self_heal.py``'s
   ``shipped_versions`` set.
2. **``--layout v2`` filesystem migration.** No database at all — built
   against an isolated ``SHEPHERD_WORKDIR`` tree with legacy
   ``plans/``/``reports/``/``root.db*`` content, verifying the
   move/rename/skip/create counts and (via a real throwaway git repo) the
   ``git mv`` vs. plain-``mv`` branch inside :func:`shepherd_cli.commands.
   migrate._mv_file`.

A crucial coexistence wrinkle this suite must route around: EVERY other
ported command's ``db.lifespan()`` silently self-heals a behind schema
before that command's own logic ever runs (:func:`shepherd_cli.db.
ensure_migrated`). ``shepherd migrate`` itself does NOT open
``db.lifespan()`` at all (see its module docstring) — it drives its own
synchronous connection specifically so this suite can observe real
gap-fill progress output. No other command is exercised here, so this
wrinkle only matters as context for why ``migrate`` looks different from
every sibling test module.
"""

from __future__ import annotations

import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest
from conftest import (
    CLI_ROOT,
    MIGRATIONS_DIR,
    PY,
    build_full_schema_db,
    build_partial_schema_db,
    cli_env,
    clean_env_dict,
    run_cli,
)

#: Every shipped migration file, sorted by filename — the same set + order
#: shepherd_cli.commands.migrate._shipped_migrations() and bash's own
#: nullglob loop would visit. Computed once at import time so every test
#: automatically tracks the real repo's migrations/ directory.
_SHIPPED_MIGRATIONS: list[str] = sorted(p.name for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
_SHIPPED_COUNT = len(_SHIPPED_MIGRATIONS)
_SHIPPED_HEAD_VERSION = max(int(name[:4]) for name in _SHIPPED_MIGRATIONS)

assert _SHIPPED_COUNT > 0, "expected at least one migrations/NNNN_*.sql file in the real repo"


def _schema_versions(db_path: Path) -> set[int]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in conn.execute("SELECT version FROM schema_versions")}
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Default branch: schema-migration gap-fill.
# --------------------------------------------------------------------------
def test_full_schema_db_reports_no_migrations_pending(tmp_path: Path) -> None:
    """An already-current DB: bash's ``shctx migrate: no migrations pending (at version N)``."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)

    env = cli_env(db_path)
    proc = run_cli(["migrate"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"shctx migrate: no migrations pending (at version {_SHIPPED_HEAD_VERSION})"
    # No progress lines when nothing was applied.
    assert "applying" not in proc.stderr


def test_partial_schema_db_catches_up_to_head(tmp_path: Path) -> None:
    """The #200 fixture (schema_versions={1} only): every shipped migration applies."""
    db_path = tmp_path / "shepherd.db"
    build_partial_schema_db(db_path)
    assert _schema_versions(db_path) == {1}

    env = cli_env(db_path)
    proc = run_cli(["migrate"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"shctx migrate: applied {_SHIPPED_COUNT} migration(s)"

    # Progress lines land on stderr, one per shipped migration, in filename
    # (== version) order — mirrors _lib.sh's `echo ... >&2` inside the loop.
    expected_progress = [f"shctx migrate: applying {name}" for name in _SHIPPED_MIGRATIONS]
    actual_progress = [line for line in proc.stderr.splitlines() if line.startswith("shctx migrate: applying ")]
    assert actual_progress == expected_progress

    # schema_versions now covers every shipped migration plus the base row.
    assert _schema_versions(db_path) == {1} | {int(name[:4]) for name in _SHIPPED_MIGRATIONS}


def test_second_migrate_after_catchup_reports_no_pending(tmp_path: Path) -> None:
    """Idempotence: a second `migrate` run after gap-fill finds nothing left to do."""
    db_path = tmp_path / "shepherd.db"
    build_partial_schema_db(db_path)
    env = cli_env(db_path)

    first = run_cli(["migrate"], env)
    assert first.returncode == 0, first.stderr

    second = run_cli(["migrate"], env)
    assert second.returncode == 0, second.stderr
    assert second.stdout.rstrip("\n") == f"shctx migrate: no migrations pending (at version {_SHIPPED_HEAD_VERSION})"
    assert second.stderr == ""


def test_no_migrations_dir_prints_message_and_exits_0(tmp_path: Path) -> None:
    """No `skills/context/schema/migrations/` reachable at all: bash's `no migrations dir`.

    Mirrors test_ready.py's `test_missing_bash_shctx_tooling_exits_1`
    technique: point CLAUDE_PLUGIN_ROOT at an empty directory and run from
    a cwd outside any git repo (so both the plugin-root-relative lookup
    AND the walk-up-from-repo-root fallback in
    shepherd_cli.resolution.find_migrations_dir() fail to find the real
    tree) — never touches the database at all (bash: the `[[ -d "$migdir"
    ]] || { echo "no migrations dir"; exit 0; }` guard runs before
    `current=$(shctx_sql ...)`).
    """
    env = cli_env(tmp_path / "unused.db")
    empty_root = tmp_path / "no-plugin-here"
    empty_root.mkdir()
    env["CLAUDE_PLUGIN_ROOT"] = str(empty_root)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "workdir")

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "migrate"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == "no migrations dir"
    assert proc.stderr == ""
    # And, per the fixture's own claim, unused.db was never even created.
    assert not (tmp_path / "unused.db").exists()


def test_missing_schema_versions_table_is_a_hard_failure(tmp_path: Path) -> None:
    """A DB file that exists but has no `schema_versions` table at all: hard error, exit 1.

    Bash: `current=$(shctx_sql "SELECT COALESCE(MAX(version),0) FROM
    schema_versions;")` errors under `sqlite3 -bail` and, under `set -e`,
    aborts the whole script before the apply loop (and its "applying
    ..." progress lines) ever runs. This port's equivalent:
    :func:`shepherd_cli.commands.migrate._read_current_version` raises
    `sqlite3.OperationalError`, caught and converted to a stderr message +
    exit 1 by :func:`_default_migrate` -- see its docstring for why the
    exact bash sqlite3 CLI error text is not reproduced verbatim.
    """
    db_path = tmp_path / "shepherd.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY);")
        conn.commit()
    finally:
        conn.close()

    env = cli_env(db_path)
    proc = run_cli(["migrate"], env)

    assert proc.returncode == 1
    assert "no such table" in proc.stderr.lower()
    assert proc.stdout == ""


def test_unrecognized_layout_value_is_rejected_from_any_position(tmp_path: Path) -> None:
    """`--layout=<bad>` errors, even when it isn't the first token (bash: whole-argv scan)."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    env = cli_env(db_path)

    proc = run_cli(["migrate", "somethingelse", "--layout=bogus"], env)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "ERROR: unknown --layout value (only 'v2' and 'v3' supported)"
    assert proc.stdout == ""


def test_layout_alone_without_v2_falls_through_to_default_migrate(tmp_path: Path) -> None:
    """`--layout` with no (or wrong) second token is silently ignored -- default branch runs."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    env = cli_env(db_path)

    proc = run_cli(["migrate", "--layout"], env)

    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == f"shctx migrate: no migrations pending (at version {_SHIPPED_HEAD_VERSION})"


@pytest.mark.parametrize("help_flag", ["-h", "--help"])
def test_help_flag_falls_through_to_default_migrate(tmp_path: Path, help_flag: str) -> None:
    """`-h`/`--help` are unrecognized tokens to cmd_migrate.sh -- it never special-cases them.

    Proves Click's own auto-generated --help text (which would NOT be
    bash parity) is disabled via help_option_names=[] and the flag is
    just ignored, falling through to a real migration run.
    """
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    env = cli_env(db_path)

    proc = run_cli(["migrate", help_flag], env)

    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == f"shctx migrate: no migrations pending (at version {_SHIPPED_HEAD_VERSION})"
    assert "Usage:" not in proc.stdout
    assert "--help" not in proc.stdout


# --------------------------------------------------------------------------
# --layout v2 branch (filesystem only, no database).
# --------------------------------------------------------------------------
def _layout_env(workdir: Path) -> dict[str, str]:
    """A subprocess env with SHEPHERD_WORKDIR pinned, no SHCTX_DB needed."""
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def _run_migrate_layout_v2(cwd: Path, env: dict[str, str], *, one_token: bool = False) -> subprocess.CompletedProcess[str]:
    args = ["--layout=v2"] if one_token else ["--layout", "v2"]
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "migrate", *args],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("one_token", [False, True])
def test_layout_v2_moves_plans_and_reports_and_renames_db(tmp_path: Path, one_token: bool) -> None:
    """The full happy path: legacy plans/reports/root.db* -> the v6.1.0 layout.

    Exercised as a plain (non-git) tree, so every file move goes through
    :func:`shepherd_cli.commands.migrate._mv_file`'s plain-``mv`` branch
    (see :func:`test_layout_v2_uses_git_mv_for_a_tracked_file` for the
    git-tracked branch). Both the two-token (`--layout v2`) and
    one-token (`--layout=v2`) argv forms are parametrized here since bash
    treats them identically (`cmd_migrate.sh`'s ``||`` check).
    """
    workdir = tmp_path / "ws" / ".shepherd"
    workdir.mkdir(parents=True)
    (workdir / "plans").mkdir()
    (workdir / "plans" / "a.seed.md").write_text("a")
    (workdir / "reports").mkdir()
    (workdir / "reports" / "2024-01-01-x.md").write_text("r")
    (workdir / "root.db").write_text("db")
    (workdir / "root.db-wal").write_text("wal")

    env = _layout_env(workdir)
    proc = _run_migrate_layout_v2(tmp_path, env, one_token=one_token)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert lines[0] == f"shctx migrate --layout v2: workdir = {workdir}"
    # created=5, NOT 7: docs/plans and docs/reports are already created as a
    # SIDE EFFECT of _mv_dir_contents's own `mkdir -p "$dst"` (step 1/2, run
    # before step 4's dir-scaffolding loop), so step 4 finds them already
    # present and does not recount/re-.gitkeep them -- a quirk this port
    # mirrors exactly from cmd_migrate.sh's own `[[ ! -d "$wd/$d" ]]` check.
    assert lines[-1] == "shctx migrate --layout v2: done — moved=4 skipped=0 created=5"

    assert (workdir / "docs" / "plans" / "a.seed.md").read_text() == "a"
    assert not (workdir / "plans" / "a.seed.md").exists()
    assert (workdir / "docs" / "reports" / "2024-01-01-x.md").read_text() == "r"
    assert (workdir / "shepherd.db").read_text() == "db"
    assert (workdir / "shepherd.db-wal").read_text() == "wal"
    assert not (workdir / "root.db").exists()
    assert not (workdir / "root.db-wal").exists()

    for d in ("archive", "scripts", "templates", "types", "cache"):
        assert (workdir / d / ".gitkeep").is_file()


def test_layout_v2_skips_when_destination_already_exists(tmp_path: Path) -> None:
    """A pre-existing destination file is never clobbered -- counted as SKIP."""
    workdir = tmp_path / "ws" / ".shepherd"
    workdir.mkdir(parents=True)
    (workdir / "plans").mkdir()
    (workdir / "plans" / "a.seed.md").write_text("legacy")
    (workdir / "docs" / "plans").mkdir(parents=True)
    (workdir / "docs" / "plans" / "a.seed.md").write_text("already-here")
    (workdir / "root.db").write_text("legacy-db")
    (workdir / "shepherd.db").write_text("already-here-db")

    env = _layout_env(workdir)
    proc = _run_migrate_layout_v2(tmp_path, env)

    assert proc.returncode == 0, proc.stderr
    assert "SKIP (dest exists)" in proc.stdout
    # created=6: docs/plans was pre-created by this test's own setup (with a
    # colliding file already in it), so step 4 finds it already present and
    # does not recount it; docs/reports IS freshly created here since this
    # test never touches reports/ at all. See the happy-path test's comment
    # for the general "mkdir -p in step 1/2 pre-empts step 4" quirk.
    assert proc.stdout.rstrip("\n").splitlines()[-1] == "shctx migrate --layout v2: done — moved=0 skipped=2 created=6"

    # Neither destination was overwritten, neither source was removed.
    assert (workdir / "docs" / "plans" / "a.seed.md").read_text() == "already-here"
    assert (workdir / "plans" / "a.seed.md").read_text() == "legacy"
    assert (workdir / "shepherd.db").read_text() == "already-here-db"
    assert (workdir / "root.db").read_text() == "legacy-db"


def test_layout_v2_is_idempotent_on_second_run(tmp_path: Path) -> None:
    """Running --layout v2 twice: the second run creates/moves/renames nothing."""
    workdir = tmp_path / "ws" / ".shepherd"
    workdir.mkdir(parents=True)
    (workdir / "plans").mkdir()
    (workdir / "plans" / "a.seed.md").write_text("a")
    env = _layout_env(workdir)

    first = _run_migrate_layout_v2(tmp_path, env)
    assert first.returncode == 0, first.stderr

    second = _run_migrate_layout_v2(tmp_path, env)
    assert second.returncode == 0, second.stderr
    assert second.stdout.rstrip("\n").splitlines()[-1] == "shctx migrate --layout v2: done — moved=0 skipped=0 created=0"


def test_layout_v2_uses_git_mv_for_a_tracked_file(tmp_path: Path) -> None:
    """A git-tracked legacy file is moved with `git mv` (stays tracked, no untracked/deleted pair)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)

    workdir = repo / ".shepherd"
    workdir.mkdir()
    (workdir / "plans").mkdir()
    tracked = workdir / "plans" / "tracked.seed.md"
    tracked.write_text("tracked content")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True)

    env = _layout_env(workdir)
    proc = _run_migrate_layout_v2(repo, env)

    assert proc.returncode == 0, proc.stderr
    assert (workdir / "docs" / "plans" / "tracked.seed.md").read_text() == "tracked content"
    assert not tracked.exists()

    # git mv preserves history/tracking in the index -- the new path shows
    # up as a plain tracked file (git status --porcelain reports nothing
    # for it once the move is the only outstanding change and is already
    # staged), and `git ls-files` includes the new path but not the old one.
    tracked_files = subprocess.run(
        ["git", "ls-files"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert ".shepherd/docs/plans/tracked.seed.md" in tracked_files
    assert ".shepherd/plans/tracked.seed.md" not in tracked_files

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout
    # A staged rename (R) is the git-mv signature; a plain `mv` would instead
    # show a deleted old path (D) plus an untracked new path (??). New
    # scaffold dirs (archive/, cache/, ...) also show up as untracked (??)
    # lines here since they were never `git add`ed -- irrelevant to this
    # assertion, which only checks the rename line's presence.
    assert "R  .shepherd/plans/tracked.seed.md -> .shepherd/docs/plans/tracked.seed.md" in status


def test_layout_v2_uses_plain_mv_for_an_untracked_file(tmp_path: Path) -> None:
    """A file NOT tracked by git (no repo at all) moves via a plain filesystem move."""
    workdir = tmp_path / "ws" / ".shepherd"
    workdir.mkdir(parents=True)
    (workdir / "plans").mkdir()
    (workdir / "plans" / "untracked.plan.md").write_text("untracked content")

    env = _layout_env(workdir)
    proc = _run_migrate_layout_v2(tmp_path, env)

    assert proc.returncode == 0, proc.stderr
    assert (workdir / "docs" / "plans" / "untracked.plan.md").read_text() == "untracked content"
    assert not (workdir / "plans" / "untracked.plan.md").exists()


# --------------------------------------------------------------------------
# No-subcommand behavior (bash: cmd_migrate.sh reads no subcommand verb at
# all -- the whole surface is flags, and bare `migrate` runs the default
# schema-migration branch).
# --------------------------------------------------------------------------
def test_bare_migrate_with_no_args_runs_default_branch(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    env = cli_env(db_path)

    proc = run_cli(["migrate"], env)

    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == f"shctx migrate: no migrations pending (at version {_SHIPPED_HEAD_VERSION})"


def test_unrecognized_extra_tokens_are_silently_ignored(tmp_path: Path) -> None:
    """Any token that isn't a recognized --layout shape is a silent no-op (bash: `*) ;;`)."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    env = cli_env(db_path)

    proc = run_cli(["migrate", "bogus", "extra", "tokens"], env)

    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == f"shctx migrate: no migrations pending (at version {_SHIPPED_HEAD_VERSION})"


# --------------------------------------------------------------------------
# --layout v3 (v6.4.1 run-scoped artifacts + profiles) — NEW, no bash twin.
# --------------------------------------------------------------------------
def _run_migrate(args: list[str], env: dict[str, str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Drive ``shepherd migrate <args>`` as a subprocess (general form)."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "migrate", *args],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("one_token", [False, True])
def test_layout_v3_moves_seeds_plans_and_styles(tmp_path: Path, one_token: bool) -> None:
    """docs/plans seeds+plans land in runs/<slug>/; styles land in profiles/."""
    workdir = tmp_path / "ws" / ".shepherd"
    plans = workdir / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "v641-dev0.seed.md").write_text("seed body")
    (plans / "v641-dev0.plan.md").write_text("plan body")
    (plans / "v641.seed.md").write_text("arc seed")
    styles = workdir / "styles"
    styles.mkdir()
    (styles / "python.md").write_text("py style")

    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    args = ["--layout=v3"] if one_token else ["--layout", "v3"]
    proc = _run_migrate(args, env, cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert (workdir / "runs" / "v641-dev0" / "seed.md").read_text() == "seed body"
    assert (workdir / "runs" / "v641-dev0" / "plan.md").read_text() == "plan body"
    assert (workdir / "runs" / "v641" / "seed.md").read_text() == "arc seed"
    assert (workdir / "profiles" / "python" / "style.md").read_text() == "py style"
    assert not (plans / "v641-dev0.seed.md").exists()
    assert not (styles / "python.md").exists()
    assert "moved=4" in proc.stdout


def test_layout_v3_skips_bad_slugs_and_existing_destinations(tmp_path: Path) -> None:
    """A slug outside the run-id grammar stays put; collisions are SKIPs."""
    workdir = tmp_path / "ws" / ".shepherd"
    plans = workdir / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "2026-05-20-v517-Canonical_State.plan.md").write_text("dated spec-style")
    (plans / "v641-dev0.seed.md").write_text("incoming")
    existing_run = workdir / "runs" / "v641-dev0"
    existing_run.mkdir(parents=True)
    (existing_run / "seed.md").write_text("already here")

    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    proc = _run_migrate(["--layout", "v3"], env, cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert (plans / "2026-05-20-v517-Canonical_State.plan.md").exists()  # never moved
    assert (plans / "v641-dev0.seed.md").exists()  # collision -> SKIP, source kept
    assert (existing_run / "seed.md").read_text() == "already here"  # never clobbered
    assert "SKIP" in proc.stdout


def test_layout_v3_is_idempotent_on_second_run(tmp_path: Path) -> None:
    workdir = tmp_path / "ws" / ".shepherd"
    plans = workdir / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "v641-dev0.seed.md").write_text("seed body")

    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    first = _run_migrate(["--layout", "v3"], env, cwd=tmp_path)
    second = _run_migrate(["--layout", "v3"], env, cwd=tmp_path)

    assert first.returncode == 0 and second.returncode == 0
    assert "moved=1" in first.stdout
    assert "moved=0" in second.stdout
    assert (workdir / "runs" / "v641-dev0" / "seed.md").read_text() == "seed body"


def test_layout_bogus_value_names_both_supported_layouts(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    env = cli_env(db_path)

    proc = _run_migrate(["--layout=v9"], env, cwd=tmp_path)

    assert proc.returncode == 1
    assert "only 'v2' and 'v3' supported" in proc.stderr
