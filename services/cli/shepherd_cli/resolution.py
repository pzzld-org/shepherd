"""Path resolution for the shepherd CLI.

Mirrors ``skills/context/scripts/_lib.sh`` EXACTLY — same precedence, same
environment variables, same defaults — so a project's ``.shepherd``/
``.artifacts`` namespace and DB file resolve identically whether reached
through the bash ``shctx`` tooling or this Python CLI. Any change here
that diverges from ``_lib.sh`` reintroduces the split-brain class of bug
``_lib.sh`` itself calls out (both namespaces resolving to different
paths depending on which tool ran).

This module does no I/O beyond ``git rev-parse``, filesystem existence
checks, and directory listings — it never touches the database.
"""

from __future__ import annotations

import os
import subprocess
import sys

# Filenames this module walks the directory tree looking for, relative to
# a candidate repo root. Kept as constants so the two walk-up callers
# (find_migrations_dir / find_schema_base / find_bash_shctx) can't drift
# from each other on the relative path shape.
_MIGRATIONS_RELPATH = os.path.join("skills", "context", "schema", "migrations")
_SCHEMA_BASE_RELPATH = os.path.join("skills", "context", "schema", "0001_init.sql")
_BASH_SHCTX_RELPATH = os.path.join("skills", "context", "scripts", "shctx")


def _git_rev_parse(flag: str) -> str | None:
    """Run ``git rev-parse <flag>`` and return its stripped stdout, or None.

    Returns:
        The command's first-line output when git exits 0 with non-empty
        output; None when git is unavailable, errors, or prints nothing.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", flag],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        out = result.stdout.strip()
        if out:
            return out
    return None


def resolve_repo_root() -> str:
    """Resolve the repository root shared by every worktree.

    Mirrors ``_lib.sh``'s ``shctx_repo_root`` (#221/#231): the shepherd
    registry (SQLite DB) and config are shared per-repo across ALL
    worktrees, but ``git rev-parse --show-toplevel`` returns the CURRENT
    worktree's root — from a linked worktree (every concurrent conductor
    lane) that scaffolds a divorced, empty per-worktree DB. Resolve to the
    MAIN worktree via ``--git-common-dir`` (which points at the shared
    ``.git`` even from a linked worktree); its parent is the main worktree
    root. Fall back to ``--show-toplevel``, then ``os.getcwd()``, when git
    is unavailable or the cwd is not inside a repo.

    Returns:
        The absolute main-worktree root path, or ``os.getcwd()`` fallback.
    """
    common = _git_rev_parse("--git-common-dir")
    if common:
        if not os.path.isabs(common):
            common = os.path.join(os.getcwd(), common)
        main = os.path.dirname(os.path.normpath(common))
        if main and os.path.isdir(main):
            return main
    top = _git_rev_parse("--show-toplevel")
    if top:
        return top
    return os.getcwd()


def in_subworktree() -> bool:
    """True when the cwd is inside a LINKED worktree (not the primary).

    Mirrors ``_lib.sh``'s ``shctx_in_subworktree`` (#221): the shared
    registry still resolves to the main worktree via
    :func:`resolve_repo_root`; this is the signal ``doctor`` uses to
    surface that scoping to the operator.

    Returns:
        True when ``--git-dir`` and ``--git-common-dir`` disagree; False
        outside a repo or in the primary worktree.
    """
    git_dir = _git_rev_parse("--git-dir")
    git_common = _git_rev_parse("--git-common-dir")
    if not git_dir or not git_common:
        return False
    # git may print one path relative and the other absolute for the same
    # directory (e.g. "../.git" vs "/repo/.git" from a subdir of the primary
    # checkout) — compare canonical paths, not raw strings.
    return os.path.realpath(git_dir) != os.path.realpath(git_common)


def resolve_user_home() -> str:
    """Resolve the user-level shepherd home directory (``~/.shepherd``).

    The user-level home holds cross-project state: the global DB
    (issue #239) and user-scoped profiles
    (``~/.shepherd/profiles/<profile>/style.md``) that project-level
    ``.shepherd/profiles/`` entries override. ``SHEPHERD_HOME`` overrides
    the default for tests and relocated installs.

    Returns:
        The resolved user-level shepherd home path (need not exist).
    """
    env_home = os.environ.get("SHEPHERD_HOME", "")
    if env_home:
        return env_home
    return os.path.join(os.path.expanduser("~"), ".shepherd")


def resolve_workdir() -> str:
    """Resolve the project-local shepherd work directory.

    Mirrors ``_lib.sh``'s ``resolve_workdir`` precedence exactly:

    1. ``SHEPHERD_WORKDIR`` (public, first-class): absolute paths are used
       as-is; relative paths resolve against the repo root via plain
       string concatenation (matching the bash ``"$root/$WORKDIR"``, not
       ``os.path.join`` normalization).
    2. ``SHCTX_ROOT_OVERRIDE`` (legacy, e.g. ``init --artifacts``): always
       treated as relative to the repo root.
    3. Otherwise auto-detect: prefer an existing ``.shepherd/``, then an
       existing ``.artifacts/``.
    4. Default to ``.shepherd/`` (the v5.0.0+ default for a fresh init).

    When both ``.shepherd/`` and ``.artifacts/`` exist (the split-brain
    state ``_lib.sh`` warns about), a warning is written to stderr unless
    ``SHCTX_QUIET`` is set — mirroring the bash warning verbatim.

    Returns:
        The resolved work directory path (need not exist on disk).
    """
    root = resolve_repo_root()

    env_workdir = os.environ.get("SHEPHERD_WORKDIR", "")
    if env_workdir:
        if env_workdir.startswith("/"):
            return env_workdir
        return f"{root}/{env_workdir}"

    root_override = os.environ.get("SHCTX_ROOT_OVERRIDE", "")
    if root_override:
        return f"{root}/{root_override}"

    shepherd_dir = f"{root}/.shepherd"
    artifacts_dir = f"{root}/.artifacts"
    if os.path.isdir(shepherd_dir):
        if os.path.isdir(artifacts_dir) and not os.environ.get("SHCTX_QUIET"):
            sys.stderr.write(
                f"shctx WARNING: both .shepherd/ and .artifacts/ exist in {os.path.basename(root)}.\n"
            )
            sys.stderr.write("  Using .shepherd/ (detected by precedence). Run 'shctx doctor' for details.\n")
        return shepherd_dir
    if os.path.isdir(artifacts_dir):
        return artifacts_dir
    return shepherd_dir


def resolve_db_path() -> str:
    """Resolve the project database file path.

    Mirrors ``_lib.sh``'s ``shctx_db_path``: ``SHCTX_DB`` wins outright
    (tests and tooling pointing at a specific DB file must resolve to the
    SAME path everywhere, including the self-heal helpers — v6.3.3
    #200). Otherwise prefers an existing ``<workdir>/shepherd.db``, falls
    back to an existing ``<workdir>/root.db`` (legacy projects untouched),
    and defaults to ``<workdir>/shepherd.db`` when neither exists yet.

    Returns:
        The resolved database file path (need not exist on disk).
    """
    env_db = os.environ.get("SHCTX_DB", "")
    if env_db:
        return env_db

    workdir = resolve_workdir()
    shepherd_db = f"{workdir}/shepherd.db"
    root_db = f"{workdir}/root.db"
    if os.path.isfile(shepherd_db):
        return shepherd_db
    if os.path.isfile(root_db):
        return root_db
    return shepherd_db


def _find_via_plugin_root_then_walk_up(relpath: str, *, is_dir: bool) -> str | None:
    """Shared lookup: ``$CLAUDE_PLUGIN_ROOT/<relpath>``, else walk up from the repo root.

    Args:
        relpath: Path relative to a plugin/repo root, e.g.
            ``skills/context/schema/migrations``.
        is_dir: True to check the candidate is a directory, False to check
            it is a regular file.

    Returns:
        The first existing candidate path, or None if neither the
        ``CLAUDE_PLUGIN_ROOT``-relative path nor any ancestor of the repo
        root contains it.
    """
    exists = os.path.isdir if is_dir else os.path.isfile

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidate = os.path.join(plugin_root, relpath)
        if exists(candidate):
            return candidate

    current = resolve_repo_root()
    while True:
        candidate = os.path.join(current, relpath)
        if exists(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def find_migrations_dir() -> str | None:
    """Locate the SQL migrations directory.

    Mirrors ``_lib.sh``'s ``shctx_skill_root``-relative migration lookup:
    prefers ``$CLAUDE_PLUGIN_ROOT/skills/context/schema/migrations``, else
    walks up from the repo root looking for
    ``skills/context/schema/migrations``.

    Returns:
        The migrations directory path, or None if it cannot be found.
    """
    return _find_via_plugin_root_then_walk_up(_MIGRATIONS_RELPATH, is_dir=True)


def find_schema_base() -> str | None:
    """Locate the baseline schema file (``0001_init.sql``).

    Prefers ``$CLAUDE_PLUGIN_ROOT/skills/context/schema/0001_init.sql``,
    else walks up from the repo root looking for
    ``skills/context/schema/0001_init.sql``.

    Returns:
        The path to ``0001_init.sql``, or None if it cannot be found.
    """
    return _find_via_plugin_root_then_walk_up(_SCHEMA_BASE_RELPATH, is_dir=False)


def find_bash_shctx() -> str | None:
    """Locate the bash ``shctx`` dispatcher script.

    Prefers ``$CLAUDE_PLUGIN_ROOT/skills/context/scripts/shctx``, else
    walks up from the repo root looking for
    ``skills/context/scripts/shctx``. Used by ``shepherd_cli.__main__`` to
    shim un-ported subcommands through to the bash implementation.

    Returns:
        The path to the ``shctx`` script, or None if it cannot be found.
    """
    return _find_via_plugin_root_then_walk_up(_BASH_SHCTX_RELPATH, is_dir=False)


def resolve_session_id() -> str | None:
    """Resolve the current session id, if any.

    Checks ``SHEPHERD_SESSION_ID`` (public, first-class) then
    ``CLAUDE_SESSION_ID`` (the ambient Claude Code session, when this CLI
    runs inside one).

    Returns:
        The resolved session id, or None if neither environment variable
        is set.
    """
    return os.environ.get("SHEPHERD_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID") or None


__all__ = [
    "resolve_repo_root",
    "in_subworktree",
    "resolve_user_home",
    "resolve_workdir",
    "resolve_db_path",
    "find_migrations_dir",
    "find_schema_base",
    "find_bash_shctx",
    "resolve_session_id",
]
