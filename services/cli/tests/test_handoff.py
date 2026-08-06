"""Subprocess parity tests for ``shepherd handoff`` (create/list/show).

Bash parity target: ``skills/context/scripts/cmd_handoff.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli handoff
...``), never by importing ``shepherd_cli`` into the pytest process.

``create``'s "What landed" section shells out to real ``git`` in the
process's own cwd (``git rev-parse --abbrev-ref HEAD`` / ``git log
--oneline``) — exactly like bash. Rather than run every test from THIS
repo's own working tree (whose branch/commit history is real, shared, and
not test-controlled), every ``create`` test that cares about branch/commit
resolution builds an isolated, throwaway git repo (see :func:`git_repo`)
and launches the CLI with that repo as ``cwd`` directly via
``subprocess.run`` (conftest's ``run_cli`` hard-codes ``cwd=CLI_ROOT``, so
it is bypassed here the same way ``test_sprint.py``'s
``test_missing_bash_shctx_tooling_exits_1`` bypasses it).

``create``'s registry metrics (``artifacts``/``mem_entries``/
``locks_history`` row counts, ``v_open_issues``/``v_drift_risk`` view row
counts) are read from a ``project.json`` FILE in the resolved shepherd
work directory (``_lib.sh``'s ``shctx_project_id``), NOT the ``projects``
table — exactly like ``shctx query`` (see ``test_query.py``'s module
docstring for the same pattern). Every test that needs non-zero metrics
therefore sets ``SHEPHERD_WORKDIR`` to an isolated tmp directory holding a
``project.json`` whose ``id`` matches the fixture DB's seeded
``projects.id`` row.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import PY, build_full_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Fixture DB + workdir/project.json + raw-sqlite3 seed helpers.
# --------------------------------------------------------------------------


def _insert_row(db_path: Path, table: str, values: dict[str, object]) -> None:
    """Insert one row into ``table``, keeping only columns that actually exist.

    Schema-tolerant like ``conftest.insert_teammate`` / ``test_query.py``'s
    identically-named helper: reads ``PRAGMA table_info(table)`` and
    silently drops any key in ``values`` that isn't a real column.

    Args:
        db_path: The fixture DB to write into.
        table: Table name (test-controlled constant, never user input).
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
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row."""
    return insert_project(db_path)


def seed_metrics(db_path: Path, project_id: str) -> None:
    """Seed rows so every one of ``create``'s five metrics is non-zero.

    * 2 ``artifacts`` rows.
    * 3 ``mem_entries`` rows.
    * 1 ``locks_history`` row.
    * 2 OPEN ``index_issues`` rows (-> ``v_open_issues`` = 2), one of which
      carries a ``"high"`` label (-> ``v_drift_risk`` = 1), plus 1 CLOSED
      issue that must count toward neither view.
    """
    now = int(time.time())
    for i in range(2):
        _insert_row(
            db_path, "artifacts",
            {
                "id": f"art-{i}", "project_id": project_id, "kind": "doc",
                "path": f"docs/art-{i}.md", "sprint_branch": "feature-x",
                "title": f"Artifact {i}", "hash": f"hash-{i}",
                "created_at": now, "updated_at": now,
            },
        )
    for i in range(3):
        _insert_row(
            db_path, "mem_entries",
            {
                "id": f"mem-{i}", "project_id": project_id, "kind": "note",
                "title": f"Note {i}", "body": "body text", "tags": "[]",
                "pinned": 0, "created_at": now, "updated_at": now,
            },
        )
    _insert_row(
        db_path, "locks_history",
        {
            "project_id": project_id, "session_id": "sess-1", "mode": "sprint",
            "acquired_at": now, "released_at": now, "released_by": "normal",
        },
    )
    _insert_row(
        db_path, "index_issues",
        {
            "id": "iss-open-1", "project_id": project_id, "source": "github",
            "number": 1, "title": "Open issue, no risk label", "state": "open",
            "labels": "[]", "assignees": "[]", "url": "https://example.com/1",
            "created_at": now, "updated_at": now, "refreshed_at": now,
        },
    )
    _insert_row(
        db_path, "index_issues",
        {
            "id": "iss-open-2", "project_id": project_id, "source": "github",
            "number": 2, "title": "Open issue, high risk", "state": "open",
            "labels": '["high"]', "assignees": "[]", "url": "https://example.com/2",
            "created_at": now, "updated_at": now, "refreshed_at": now,
        },
    )
    _insert_row(
        db_path, "index_issues",
        {
            "id": "iss-closed-1", "project_id": project_id, "source": "github",
            "number": 3, "title": "Closed issue", "state": "closed",
            "labels": '["critical"]', "assignees": "[]", "url": "https://example.com/3",
            "created_at": now, "updated_at": now, "refreshed_at": now,
        },
    )


def handoff_env(db_path: Path, workdir: Path, *, project_id: str | None = None) -> dict[str, str]:
    """The environment for driving ``shepherd handoff`` against one fixture DB.

    Args:
        db_path: The sqlite file (drives ``SHCTX_DB`` via :func:`cli_env`).
        workdir: An isolated tmp directory to use as the shepherd work
            directory (``SHEPHERD_WORKDIR``) — this is both where
            ``project.json`` is read from AND where ``docs/handoffs/``
            gets created.
        project_id: When given, writes ``project.json`` with this id.
            When None (default), no ``project.json`` is written at all —
            drives the "not initialized -> every metric is 0" path.

    Returns:
        A full subprocess environment. ``CLAUDE_PLUGIN_ROOT`` is left at
        ``cli_env``'s default (the real repo root), so
        ``find_bash_shctx()``/the template lookup resolve against the
        REAL ``skills/context/`` tree unless a test overrides it.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if project_id is not None:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def run_cli_cwd(args: Sequence[str], env: dict[str, str], cwd: Path, *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    """Run the shepherd CLI as a subprocess with an EXPLICIT ``cwd``.

    ``conftest.run_cli`` hard-codes ``cwd=CLI_ROOT``; ``create``'s git-log
    resolution needs a caller-controlled, isolated git repo as cwd instead
    (see the module docstring), so this bypasses it the same way
    ``test_sprint.py``'s ``test_missing_bash_shctx_tooling_exits_1`` does.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", *args],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """An isolated, throwaway git repo: 2 commits, checked out on ``feature-x``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("a")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "first commit")
    _git(repo, "checkout", "-q", "-b", "feature-x")
    (repo / "b.txt").write_text("b")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "second commit")
    return repo


@pytest.fixture
def fake_plugin_root_no_template(tmp_path: Path) -> Path:
    """A ``CLAUDE_PLUGIN_ROOT`` whose ``shctx`` exists but has no ``references/`` dir.

    Drives ``_template_path()`` resolving to a real, non-None path that
    nonetheless does not exist on disk — the "ERROR: template missing"
    branch of ``_do_create``.
    """
    scripts_dir = tmp_path / "fake-plugin-root" / "skills" / "context" / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "shctx").write_text("#!/usr/bin/env bash\nexit 0\n")
    return scripts_dir.parent.parent.parent


# --------------------------------------------------------------------------
# Top-level dispatch: no-subcommand / -h / --help / help / unknown.
# --------------------------------------------------------------------------


def test_no_subcommand_shows_usage_and_exits_0(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["handoff"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == (
        "shctx handoff <create|list|show> [args]\n"
        "\n"
        "  create [--branch=<name>] [--out=<path>]\n"
        "      Emit a filled-in handoff template at\n"
        "      ${shctx_artifacts_root}/docs/handoffs/<YYYY-MM-DD>-<branch>-close-handoff.md.\n"
        "\n"
        "  list\n"
        "      List existing handoffs (newest first).\n"
        "\n"
        "  show [<branch|date>]\n"
        "      Print the most recent handoff matching the substring (no arg = newest)."
    )


@pytest.mark.parametrize("flag", ["-h", "--help", "help"])
def test_h_help_and_help_word_all_show_usage_and_exit_0(db_path: Path, project_id: str, flag: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["handoff", flag], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx handoff <create|list|show> [args]" in proc.stdout


def test_unknown_subcommand_exits_1_with_usage_on_stderr(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["handoff", "bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown handoff sub: bogus" in proc.stderr
    assert "shctx handoff <create|list|show> [args]" in proc.stderr


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------


def test_create_happy_path_writes_file_with_counts_and_prints_path(
    db_path: Path, project_id: str, git_repo: Path, tmp_path: Path
) -> None:
    seed_metrics(db_path, project_id)
    workdir = tmp_path / "wd"
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli_cwd(["handoff", "create"], env, cwd=git_repo)
    assert proc.returncode == 0, proc.stderr

    printed_path = proc.stdout.rstrip("\n")
    out_file = Path(printed_path)
    assert out_file.is_file()
    assert out_file.parent == workdir / "docs" / "handoffs"
    assert out_file.name.endswith("-feature-x-close-handoff.md")

    content = out_file.read_text()
    assert "# Sprint handoff — feature-x" in content
    assert "| Branch | `feature-x` |" in content
    assert "[FILL IN]" in content  # north star / carry-forwards / next focus / files
    assert "first commit" in content
    assert "second commit" in content
    assert "| Artifacts (created/modified) | 2 |" in content
    assert "| Memory entries written | 3 |" in content
    assert "| Lock acquisitions | 1 |" in content
    assert "| Open issues (registry view) | 2 |" in content
    assert "| Drift-risk items (registry view) | 1 |" in content
    # No unrendered placeholder tokens survive.
    assert "{{" not in content


def test_create_no_project_json_all_counts_zero(
    db_path: Path, project_id: str, git_repo: Path, tmp_path: Path
) -> None:
    seed_metrics(db_path, project_id)  # seeded, but must never be read (no project.json)
    workdir = tmp_path / "wd"
    env = handoff_env(db_path, workdir, project_id=None)
    assert not (workdir / "project.json").exists()

    proc = run_cli_cwd(["handoff", "create"], env, cwd=git_repo)
    assert proc.returncode == 0, proc.stderr

    content = Path(proc.stdout.rstrip("\n")).read_text()
    assert "| Artifacts (created/modified) | 0 |" in content
    assert "| Memory entries written | 0 |" in content
    assert "| Lock acquisitions | 0 |" in content
    assert "| Open issues (registry view) | 0 |" in content
    assert "| Drift-risk items (registry view) | 0 |" in content


def test_create_explicit_branch_flag_overrides_git_branch(
    db_path: Path, project_id: str, git_repo: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli_cwd(["handoff", "create", "--branch=custom-branch"], env, cwd=git_repo)
    assert proc.returncode == 0, proc.stderr

    out_file = Path(proc.stdout.rstrip("\n"))
    assert out_file.name.endswith("-custom-branch-close-handoff.md")
    assert "| Branch | `custom-branch` |" in out_file.read_text()
    # Bash parity: a branch that isn't a valid git ref falls back to a
    # bare `git log --oneline -n 10` (HEAD) for the commits section, not
    # "(no commits)" — it never matches the ref-verify branch either way.
    assert "second commit" in out_file.read_text()


def test_create_explicit_out_flag(db_path: Path, project_id: str, git_repo: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    out_path = tmp_path / "custom-out.md"
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli_cwd(["handoff", "create", f"--out={out_path}"], env, cwd=git_repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == str(out_path)
    assert out_path.is_file()


def test_create_unknown_flag_exits_1(db_path: Path, project_id: str, tmp_path: Path) -> None:
    env = handoff_env(db_path, tmp_path / "wd", project_id=project_id)
    proc = run_cli(["handoff", "create", "--nope=1"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown flag: --nope=1" in proc.stderr


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_create_help_flag_shows_usage_and_exits_0_ignoring_later_flags(
    db_path: Path, project_id: str, tmp_path: Path, flag: str
) -> None:
    env = handoff_env(db_path, tmp_path / "wd", project_id=project_id)
    # --nope=1 would otherwise be an unknown-flag error -- proves -h/--help
    # short-circuits the loop the instant it's seen, exactly like bash.
    proc = run_cli(["handoff", "create", flag, "--nope=1"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx handoff <create|list|show> [args]" in proc.stdout
    # No file was ever written.
    assert not (tmp_path / "wd" / "docs" / "handoffs").exists()


def test_create_missing_template_exits_1(
    db_path: Path, project_id: str, fake_plugin_root_no_template: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = handoff_env(db_path, workdir, project_id=project_id)
    env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root_no_template)

    proc = run_cli(["handoff", "create"], env)
    assert proc.returncode == 1
    assert "ERROR: template missing:" in proc.stderr
    assert "handoff-template.md" in proc.stderr


def test_create_bad_out_directory_exits_1(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = handoff_env(db_path, workdir, project_id=project_id)
    bad_out = tmp_path / "does" / "not" / "exist" / "handoff.md"

    proc = run_cli(["handoff", "create", f"--out={bad_out}"], env)
    assert proc.returncode == 1
    assert "ERROR: failed to write handoff:" in proc.stderr
    assert not bad_out.exists()


def test_create_default_branch_falls_back_to_unknown_outside_a_git_repo(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    non_repo_cwd = tmp_path / "not-a-repo"
    non_repo_cwd.mkdir()
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli_cwd(["handoff", "create"], env, cwd=non_repo_cwd)
    assert proc.returncode == 0, proc.stderr

    out_file = Path(proc.stdout.rstrip("\n"))
    assert out_file.name.endswith("-unknown-close-handoff.md")
    assert "(no commits)" in out_file.read_text()


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


def test_list_no_handoffs_dir_prints_message(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "list"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"(no handoffs at {workdir / 'docs' / 'handoffs'})"


def test_list_empty_handoffs_dir_prints_message(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "list"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"(no handoffs at {hroot})"


def test_list_multiple_sorted_newest_first(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    oldest = hroot / "2026-01-01-a-close-handoff.md"
    middle = hroot / "2026-01-02-b-close-handoff.md"
    newest = hroot / "2026-01-03-c-close-handoff.md"
    for path, offset in ((oldest, 0), (middle, 10), (newest, 20)):
        path.write_text("content")
        mtime = time.time() - 1000 + offset
        os_utime(path, mtime)
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "list"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n").splitlines() == [newest.name, middle.name, oldest.name]


def test_list_ignores_extra_args(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    (hroot / "2026-01-01-a-close-handoff.md").write_text("content")
    env = handoff_env(db_path, workdir, project_id=project_id)

    # Bash parity: cmd_list's body never reads "$@" -- any extra token,
    # including something that looks like a flag, is silently ignored.
    proc = run_cli(["handoff", "list", "-h", "--whatever", "garbage"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "2026-01-01-a-close-handoff.md"


def os_utime(path: Path, mtime: float) -> None:
    """Set both atime and mtime, for deterministic ``ls -1t``-order fixtures."""
    os.utime(path, (mtime, mtime))


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------


def test_show_no_handoffs_dir_prints_message_exits_0(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "show"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"(no handoffs at {workdir / 'docs' / 'handoffs'})"


def test_show_empty_handoffs_dir_prints_message_exits_0(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "show"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"(no handoffs at {hroot})"


def test_show_no_arg_prints_most_recent(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    older = hroot / "2026-01-01-a-close-handoff.md"
    newer = hroot / "2026-01-02-b-close-handoff.md"
    older.write_text("older content\n")
    newer.write_text("newer content\n")
    os_utime(older, time.time() - 1000)
    os_utime(newer, time.time() - 10)
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "show"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "newer content\n"


def test_show_pattern_matches_substring(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    (hroot / "2026-01-01-feature-a-close-handoff.md").write_text("A content\n")
    (hroot / "2026-01-02-feature-b-close-handoff.md").write_text("B content\n")
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "show", "feature-a"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "A content\n"


def test_show_no_match_exits_1_with_message_on_stdout(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    (hroot / "2026-01-01-feature-a-close-handoff.md").write_text("A content\n")
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "show", "no-such-branch"], env)
    assert proc.returncode == 1
    # Bash parity: the "(no handoff matching ...)" message is a plain
    # `echo` -- stdout, not stderr.
    assert proc.stdout.rstrip("\n") == "(no handoff matching 'no-such-branch')"
    assert proc.stderr == ""


def test_show_content_matches_file_bytes_exactly(db_path: Path, project_id: str, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    hroot = workdir / "docs" / "handoffs"
    hroot.mkdir(parents=True)
    exact = "line one\nline two\nline three\n"
    (hroot / "2026-01-01-x-close-handoff.md").write_text(exact)
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "show"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == exact


# --------------------------------------------------------------------------
# v6.4.4 — a handoff is RUN-SCOPED: {run_dir}/handoff.md, not docs/handoffs/.
# --------------------------------------------------------------------------
def _make_run(workdir: Path, run: str) -> Path:
    """Create a run directory the way `shepherd run init` would (dir + run.json)."""
    rdir = workdir / "runs" / run
    rdir.mkdir(parents=True)
    (rdir / "run.json").write_text(json.dumps({"schema_version": 1, "run": run, "status": "closing"}))
    return rdir


def test_create_writes_into_the_run_dir_when_the_run_exists(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """The default target is `{run_dir}/handoff.md` — derived, not invented.

    `derive_run_id` runs the same `[branching]` slug pattern `run init` uses, so
    the handoff lands in the directory the planter already created instead of
    the CROSS-RUN docs tree.
    """
    workdir = tmp_path / "wd"
    workdir.mkdir()
    rdir = _make_run(workdir, "v644-dev0")
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "create", "--branch=v6.4.4-dev.0"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(rdir / "handoff.md")
    assert (rdir / "handoff.md").is_file()
    # Nothing was ledgered into the cross-run tree.
    assert not (workdir / "docs" / "handoffs").exists()


def test_create_falls_back_to_legacy_when_the_run_dir_is_absent(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """No run directory on disk -> legacy path, NOT an invented run dir.

    Materializing `runs/<slug>/` here would create a run that `run init` never
    made and `list_runs` cannot see (no run.json) — worse than a legacy write.
    """
    workdir = tmp_path / "wd"
    workdir.mkdir()
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "create", "--branch=v6.4.4-dev.0"], env)

    assert proc.returncode == 0, proc.stderr
    assert "docs/handoffs" in proc.stdout
    assert not (workdir / "runs").exists()


def test_create_falls_back_for_a_branch_with_no_canonical_run_id(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """A non-version branch (hotfix, ad-hoc) has no derivable run — legacy path."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "create", "--branch=hotfix-login-crash"], env)

    assert proc.returncode == 0, proc.stderr
    assert "docs/handoffs" in proc.stdout
    assert "hotfix-login-crash-close-handoff.md" in proc.stdout


def test_list_shows_run_scoped_and_legacy_handoffs_together(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """`list` reads both trees, and qualifies run-scoped entries by run id.

    Every run-scoped handoff is named `handoff.md`, so a bare basename would
    print N identical, useless lines.
    """
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (_make_run(workdir, "v644-dev0") / "handoff.md").write_text("run scoped")
    (_make_run(workdir, "v643-dev0") / "handoff.md").write_text("older run")
    legacy = workdir / "docs" / "handoffs"
    legacy.mkdir(parents=True)
    (legacy / "2026-01-01-old-branch-close-handoff.md").write_text("legacy")
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "list"], env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.split()
    assert "v644-dev0/handoff.md" in lines
    assert "v643-dev0/handoff.md" in lines
    assert "2026-01-01-old-branch-close-handoff.md" in lines


def test_show_finds_a_run_scoped_handoff_by_run_id(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """`show <pattern>` matches on the full path, so the run id is searchable."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (_make_run(workdir, "v644-dev0") / "handoff.md").write_text("body of the v644 handoff")
    env = handoff_env(db_path, workdir, project_id=project_id)

    proc = run_cli(["handoff", "show", "v644-dev0"], env)

    assert proc.returncode == 0, proc.stderr
    assert "body of the v644 handoff" in proc.stdout
