"""Tests for shepherd_cli.resolution — path resolution mirroring
skills/context/scripts/_lib.sh's shctx_db_path / resolve_workdir precedence
exactly.

Every assertion runs shepherd_cli.resolution's functions inside a fresh
``${PY} -c`` subprocess (see conftest.resolve_fields) rather than importing
shepherd_cli into the pytest process, so cwd and env are exactly what
production resolution.py sees — no bleed-through from pytest's own state.
"""

from __future__ import annotations

from pathlib import Path

from conftest import clean_env_dict, resolve_fields


def test_shctx_db_env_wins_over_workdir_files(tmp_path: Path) -> None:
    """SHCTX_DB always wins, even when <workdir>/shepherd.db and root.db exist."""
    workdir = tmp_path / ".shepherd"
    workdir.mkdir()
    (workdir / "shepherd.db").write_text("")
    (workdir / "root.db").write_text("")
    override_db = tmp_path / "explicit-override.db"
    override_db.write_text("")

    env = clean_env_dict()
    env["SHCTX_DB"] = str(override_db)
    result = resolve_fields(("resolve_db_path",), env, cwd=tmp_path)

    assert result["resolve_db_path"] == str(override_db)


def test_workdir_absolute_used_as_is(tmp_path: Path) -> None:
    """An absolute SHEPHERD_WORKDIR is used verbatim, ignoring repo root."""
    target = tmp_path / "somewhere" / "else"
    target.mkdir(parents=True)

    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(target)
    result = resolve_fields(("resolve_workdir",), env, cwd=tmp_path)

    assert result["resolve_workdir"] == str(target)


def test_workdir_relative_resolves_against_repo_root(tmp_path: Path) -> None:
    """A relative SHEPHERD_WORKDIR resolves against resolve_repo_root().

    tmp_path is not inside a git repo, so resolve_repo_root() falls back to
    os.getcwd() — pinned here to tmp_path via the subprocess cwd.
    """
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = "rel-workdir"
    result = resolve_fields(("resolve_repo_root", "resolve_workdir"), env, cwd=tmp_path)

    assert result["resolve_repo_root"] == str(tmp_path)
    assert result["resolve_workdir"] == str(tmp_path / "rel-workdir")


def test_root_override_relative_resolves_against_repo_root(tmp_path: Path) -> None:
    """SHCTX_ROOT_OVERRIDE (legacy) is relative-to-repo-root, like SHEPHERD_WORKDIR."""
    env = clean_env_dict()
    env["SHCTX_ROOT_OVERRIDE"] = "legacy-artifacts"
    result = resolve_fields(("resolve_workdir",), env, cwd=tmp_path)

    assert result["resolve_workdir"] == str(tmp_path / "legacy-artifacts")


def test_shepherd_workdir_takes_priority_over_root_override(tmp_path: Path) -> None:
    """When both are set, SHEPHERD_WORKDIR (public, first-class) wins."""
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = "new-namespace"
    env["SHCTX_ROOT_OVERRIDE"] = "legacy-namespace"
    result = resolve_fields(("resolve_workdir",), env, cwd=tmp_path)

    assert result["resolve_workdir"] == str(tmp_path / "new-namespace")


def test_shepherd_dir_precedence_over_artifacts(tmp_path: Path) -> None:
    """With no env override, an existing .shepherd/ wins over an existing .artifacts/."""
    (tmp_path / ".shepherd").mkdir()
    (tmp_path / ".artifacts").mkdir()

    result = resolve_fields(("resolve_workdir",), clean_env_dict(), cwd=tmp_path)

    assert result["resolve_workdir"] == str(tmp_path / ".shepherd")


def test_artifacts_dir_used_when_shepherd_absent(tmp_path: Path) -> None:
    """A lone existing .artifacts/ (no .shepherd/) is auto-detected."""
    (tmp_path / ".artifacts").mkdir()

    result = resolve_fields(("resolve_workdir",), clean_env_dict(), cwd=tmp_path)

    assert result["resolve_workdir"] == str(tmp_path / ".artifacts")


def test_defaults_to_shepherd_when_neither_namespace_exists(tmp_path: Path) -> None:
    """With no env override and neither dir on disk, .shepherd/ is the default."""
    result = resolve_fields(("resolve_workdir",), clean_env_dict(), cwd=tmp_path)

    assert result["resolve_workdir"] == str(tmp_path / ".shepherd")


def test_db_path_prefers_shepherd_db_over_root_db(tmp_path: Path) -> None:
    """resolve_db_path() prefers <workdir>/shepherd.db when both files exist."""
    workdir = tmp_path / ".shepherd"
    workdir.mkdir()
    (workdir / "shepherd.db").write_text("")
    (workdir / "root.db").write_text("")

    result = resolve_fields(("resolve_db_path",), clean_env_dict(), cwd=tmp_path)

    assert result["resolve_db_path"] == str(workdir / "shepherd.db")


def test_db_path_falls_back_to_root_db_when_only_it_exists(tmp_path: Path) -> None:
    """Legacy projects with only root.db (no shepherd.db yet) keep resolving to it."""
    workdir = tmp_path / ".shepherd"
    workdir.mkdir()
    (workdir / "root.db").write_text("")

    result = resolve_fields(("resolve_db_path",), clean_env_dict(), cwd=tmp_path)

    assert result["resolve_db_path"] == str(workdir / "root.db")


def test_db_path_defaults_to_shepherd_db_when_neither_file_exists(tmp_path: Path) -> None:
    """A brand-new namespace with no DB file yet defaults to shepherd.db (new-project default)."""
    workdir = tmp_path / ".shepherd"
    workdir.mkdir()

    result = resolve_fields(("resolve_db_path",), clean_env_dict(), cwd=tmp_path)

    assert result["resolve_db_path"] == str(workdir / "shepherd.db")


# --------------------------------------------------------------------------
# Worktree resolution (#221/#231) + user-level home.
# --------------------------------------------------------------------------
def _init_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a real git repo with one linked worktree.

    Returns:
        (main_root, worktree_root) — the primary checkout and a linked
        worktree at a sibling path, with one commit so worktree add works.
    """
    import subprocess as sp

    main = tmp_path / "main"
    main.mkdir()
    env = clean_env_dict()
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
    ):
        sp.run(args, cwd=main, env=env, check=True, capture_output=True)
    wt = tmp_path / "lane-wt"
    sp.run(
        ["git", "worktree", "add", "-q", str(wt), "-b", "lane-1", "main"],
        cwd=main, env=env, check=True, capture_output=True,
    )
    return main, wt


def test_repo_root_from_linked_worktree_resolves_main_checkout(tmp_path: Path) -> None:
    """#221/#231: from a linked worktree, resolve_repo_root() returns the MAIN
    worktree root (via --git-common-dir), never the worktree's own path — the
    divorced per-worktree shepherd.db class of bug."""
    main, wt = _init_repo_with_worktree(tmp_path)

    result = resolve_fields(("resolve_repo_root", "in_subworktree"), clean_env_dict(), cwd=wt)

    assert result["resolve_repo_root"] == str(main.resolve())
    assert result["in_subworktree"] is True


def test_repo_root_from_primary_worktree_unchanged(tmp_path: Path) -> None:
    """From the primary checkout (including a subdir), resolution is the repo root."""
    main, _wt = _init_repo_with_worktree(tmp_path)
    sub = main / "src"
    sub.mkdir()

    at_root = resolve_fields(("resolve_repo_root", "in_subworktree"), clean_env_dict(), cwd=main)
    at_sub = resolve_fields(("resolve_repo_root", "in_subworktree"), clean_env_dict(), cwd=sub)

    assert at_root["resolve_repo_root"] == str(main.resolve())
    assert at_root["in_subworktree"] is False
    assert at_sub["resolve_repo_root"] == str(main.resolve())
    assert at_sub["in_subworktree"] is False


def test_workdir_from_linked_worktree_binds_main_namespace(tmp_path: Path) -> None:
    """The full #231 scenario: a git-tracked .shepherd/ exists in both checkouts;
    resolve_workdir() from the worktree must bind the MAIN checkout's namespace."""
    main, wt = _init_repo_with_worktree(tmp_path)
    (main / ".shepherd").mkdir()
    (wt / ".shepherd").mkdir()  # tracked subtree exists in the worktree checkout too

    result = resolve_fields(("resolve_workdir",), clean_env_dict(), cwd=wt)

    assert result["resolve_workdir"] == str((main / ".shepherd").resolve())


def test_user_home_defaults_and_env_override(tmp_path: Path) -> None:
    """resolve_user_home(): SHEPHERD_HOME overrides; default is ~/.shepherd."""
    env = clean_env_dict()
    env["SHEPHERD_HOME"] = str(tmp_path / "custom-home")
    overridden = resolve_fields(("resolve_user_home",), env, cwd=tmp_path)
    assert overridden["resolve_user_home"] == str(tmp_path / "custom-home")

    env2 = clean_env_dict()
    env2.pop("SHEPHERD_HOME", None)
    env2["HOME"] = str(tmp_path / "fake-user")
    default = resolve_fields(("resolve_user_home",), env2, cwd=tmp_path)
    assert default["resolve_user_home"] == str(tmp_path / "fake-user" / ".shepherd")
