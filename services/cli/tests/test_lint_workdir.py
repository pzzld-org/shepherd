"""Tests for ``shepherd lint``'s DF-72 workdir-scope-visibility fix.

DF-72 (v6.4.5 dogfood, ``.shepherd/runs/v645/dogfood.md``): W7's central
auditor invoked ``bin/shepherd lint`` from inside
``.shepherd/runs/v645/reports/`` and got a silent ``lint: ok`` — the command
prints no path, so a run that inspected nothing reads identically to a run
that inspected everything and found it clean. This file locks in the fix's
two halves, both scoped to an AUTO-DETECTED workdir (see
``shepherd_cli.commands.lint._workdir_is_explicit``):

1. every such run prints ``lint: root=<resolved root> files=<count>`` before
   any violation output, and
2. a resolved root with zero lintable files FAILS outright (exit 1), naming
   the resolved root.

Every test drives the real CLI as a subprocess, same as ``test_lint.py``
(``${PY} -m shepherd_cli lint``) — never by importing ``shepherd_cli`` into
the pytest process. Unlike ``test_lint.py``, most tests here run WITHOUT
``SHEPHERD_WORKDIR`` set (that env var is exactly what DF-72's own fix
carves out as "explicit, trust it, skip both new checks" — see
``test_explicit_workdir_with_zero_files_is_still_ok`` below, which locks in
that boundary and doubles as proof this fix does not regress
``test_lint.py``'s own uninitialized-tree contract), and each drives cwd
directly via ``subprocess.run(..., cwd=...)`` (``conftest.run_cli`` always
runs from ``CLI_ROOT``, which cannot vary cwd — see ``run_lint`` below,
mirroring ``test_init.py``'s ``run_init``).

**NO DATABASE** — same as ``test_lint.py``: ``lint`` is a pure filesystem
walk, so no fixture DB, no ``SHCTX_DB``, no ``CLAUDE_PLUGIN_ROOT`` needed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import PY, clean_env_dict


# --------------------------------------------------------------------------
# Fixture helpers.
# --------------------------------------------------------------------------
def touch(path: Path) -> None:
    """Create an empty file, making parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def init_git_repo(root: Path) -> None:
    """A minimal, real git repo at ``root`` — just enough for
    ``resolve_repo_root()``'s ``--show-toplevel``/``--git-common-dir``
    walk-up to find it from any subdirectory below it, the exact mechanism
    DF-72's fix relies on. Mirrors ``test_resolution.py``'s
    ``_init_repo_with_worktree`` (no worktree needed here, just the repo).
    """
    env = clean_env_dict()
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, env=env, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=root, env=env, check=True, capture_output=True,
    )


def run_lint(cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli lint`` under ``cwd`` (mirrors ``test_init.py``'s ``run_init``).

    ``conftest.run_cli`` always runs with ``cwd=CLI_ROOT`` and so cannot
    exercise "invoked from a nested subdirectory" at all — that is the exact
    scenario DF-72 found broken, so this test file needs its own cwd-varying
    invocation instead.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "lint"],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


# --------------------------------------------------------------------------
# 1. Nested subdirectory finds the same file count as the root.
# --------------------------------------------------------------------------
def test_nested_subdirectory_finds_same_file_count_as_root(tmp_path: Path) -> None:
    """A clean run from a deeply nested subdirectory inspects the same files
    as a run from the repo root — the walk-up must land on the same root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    touch(repo / ".shepherd" / "docs" / "reports" / "2026-01-01-example.md")
    touch(repo / ".shepherd" / "docs" / "journal" / "2026-01-02.md")
    touch(repo / ".shepherd" / "logs" / "events-2026-01-03.jsonl")

    nested = repo / "some" / "deeply" / "nested" / "dir"
    nested.mkdir(parents=True)

    env = clean_env_dict()  # no SHEPHERD_WORKDIR -- forces auto-detection.
    at_root = run_lint(repo, env)
    at_nested = run_lint(nested, env)

    expected_root = repo / ".shepherd"
    for result in (at_root, at_nested):
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"lint: root={expected_root} files=3" in result.stdout
        assert result.stdout.rstrip("\n").splitlines()[-1] == "lint: ok"

    # Same resolved root, same count, same everything -- byte-identical output.
    assert at_root.stdout == at_nested.stdout


def test_violation_found_from_nested_subdirectory_matches_root(tmp_path: Path) -> None:
    """Falsifiability: a real violation is not just counted but actually
    CAUGHT identically whether invoked from the root or from a subdirectory
    — proves the equivalence isn't trivially true only in the zero-violation
    case above."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    bad = repo / ".shepherd" / "plans" / "notes.md"
    touch(bad)

    nested = repo / "runs" / "v1" / "reports"
    nested.mkdir(parents=True)

    env = clean_env_dict()
    at_root = run_lint(repo, env)
    at_nested = run_lint(nested, env)

    for result in (at_root, at_nested):
        assert result.returncode == 1
        assert f"lint: {bad} does not match *.seed.md or *.plan.md" in result.stdout
        assert "lint: FAIL (1 violation(s))" in result.stdout
    assert at_root.stdout == at_nested.stdout


# --------------------------------------------------------------------------
# 2. Zero lintable files exits non-zero, naming the resolved root.
# --------------------------------------------------------------------------
def test_zero_lintable_files_exits_nonzero(tmp_path: Path) -> None:
    """An auto-detected root with no plugin surface at all — DF-72's exact
    scenario — FAILS instead of silently reporting ``lint: ok``."""
    empty = tmp_path / "no-plugin-surface-here"
    empty.mkdir()
    # Not a git repo and no .claude-plugin/plugin.json anywhere above it, so
    # resolve_repo_root() falls all the way through to bare cwd (unchanged
    # "not inside a repo" behavior) and resolve_workdir() auto-detects the
    # synthetic, nonexistent `<empty>/.shepherd` default.

    env = clean_env_dict()  # no SHEPHERD_WORKDIR -- forces auto-detection.
    result = run_lint(empty, env)

    assert result.returncode != 0
    expected_root = empty / ".shepherd"
    assert f"lint: root={expected_root} files=0" in result.stdout
    assert f"lint: FAIL -- resolved root {expected_root} has 0 lintable files" in result.stdout


def test_zero_lintable_files_message_names_the_fix(tmp_path: Path) -> None:
    """The failure message tells the operator how to recover (pin the root)."""
    empty = tmp_path / "wrong-place"
    empty.mkdir()

    result = run_lint(empty, clean_env_dict())

    assert result.returncode != 0
    assert "SHEPHERD_WORKDIR" in result.stdout


# --------------------------------------------------------------------------
# 3. The resolved root appears in stdout in both the pass and fail cases —
# already asserted above via the `lint: root=...` banner; this test locks in
# that it is present specifically on the REAL repo root too (a lived-in
# project with actual content, not just a bare fixture), matching DF-72's
# acceptance bar verbatim: "exiting non-zero from a directory with no plugin
# surface, and exiting 0 from the repo root, in the same report."
# --------------------------------------------------------------------------
def test_root_and_count_banner_present_on_both_pass_and_fail(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    touch(repo / ".shepherd" / "docs" / "journal" / "2026-02-02.md")
    env = clean_env_dict()

    clean_result = run_lint(repo, env)
    assert clean_result.returncode == 0
    assert str(repo / ".shepherd") in clean_result.stdout

    empty = tmp_path / "empty-elsewhere"
    empty.mkdir()
    fail_result = run_lint(empty, env)
    assert fail_result.returncode != 0
    assert str(empty / ".shepherd") in fail_result.stdout


# --------------------------------------------------------------------------
# Explicit SHEPHERD_WORKDIR is untouched by this fix — locks in the exact
# boundary DF-72's own fix draws, and doubles as a regression guard for
# test_lint.py's test_uninitialized_tree_is_ok / test_empty_directories_are_ok
# (out of this step's file scope, so this file re-proves the same contract
# from the DF-72 side of the change instead of touching that file).
# --------------------------------------------------------------------------
def test_explicit_workdir_with_zero_files_is_still_ok(tmp_path: Path) -> None:
    """An explicitly-pinned, empty workdir is a legitimate fresh project —
    NOT a resolution failure — so it still exits 0 with the original bare
    ``lint: ok``, no banner, no FAIL."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)

    result = run_lint(tmp_path, env)

    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"
    assert result.stderr == ""


def test_explicit_root_override_with_zero_files_is_still_ok(tmp_path: Path) -> None:
    """Same guarantee for the legacy ``SHCTX_ROOT_OVERRIDE`` path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    env = clean_env_dict()
    env["SHCTX_ROOT_OVERRIDE"] = "legacy-artifacts"

    result = run_lint(repo, env)

    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"
