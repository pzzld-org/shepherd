"""Profile resolution — ``profiles/{profile}/style.md`` across three tiers.

v6.4.1 restructure (operator directive, 2026-08-02): the flat
``<workdir>/styles/<lang>.md`` layout becomes a directory per profile —
``<workdir>/profiles/<profile>/style.md`` — so user-specific instructions
can live ALONGSIDE the language-standard style file inside the profile
directory (future: ``instructions.md``, tool configs, references). A
profile is usually a language (``rust``, ``python``) but the shape is
general.

Resolution chain for a profile's style, first hit wins:

1. project ``<workdir>/profiles/<profile>/style.md``
2. project legacy ``<workdir>/styles/<profile>.md`` (pre-v6.4.1 layout;
   ``shepherd migrate --layout v3`` moves it)
3. user ``~/.shepherd/profiles/<profile>/style.md`` (``SHEPHERD_HOME``
   honored — user-level defaults shared across projects)
4. bundled ``skills/context/styles/<profile>.md`` (plugin defaults)

Writes ALWAYS target tier 1 (the project canonical path) — the chain is
read-side only, so a project edit can never silently land in the user or
bundled tier.
"""

from __future__ import annotations

import os

from shepherd_cli.resolution import resolve_repo_root, resolve_user_home, resolve_workdir

#: Source labels, in resolution order, as reported by ``style list``.
SOURCE_PROJECT = "project"
SOURCE_LEGACY = "legacy"
SOURCE_USER = "user"
SOURCE_BUNDLED = "bundled"


def project_profiles_root(workdir: str | None = None) -> str:
    """The project-level profiles root: ``<workdir>/profiles``."""
    return os.path.join(workdir if workdir is not None else resolve_workdir(), "profiles")


def user_profiles_root() -> str:
    """The user-level profiles root: ``~/.shepherd/profiles``."""
    return os.path.join(resolve_user_home(), "profiles")


def canonical_style_path(profile: str, workdir: str | None = None) -> str:
    """The WRITE target for a profile's style (project tier).

    Args:
        profile: The profile key, e.g. ``"python"``.
        workdir: Optional workdir override (tests).

    Returns:
        ``<workdir>/profiles/<profile>/style.md`` (need not exist).
    """
    return os.path.join(project_profiles_root(workdir), profile, "style.md")


def legacy_style_path(profile: str, workdir: str | None = None) -> str:
    """The pre-v6.4.1 flat path: ``<workdir>/styles/<profile>.md``."""
    return os.path.join(
        workdir if workdir is not None else resolve_workdir(), "styles", f"{profile}.md"
    )


def bundled_styles_dir() -> str:
    """Locate the bundled style-guide source directory (``skills/context/styles``).

    Duplicated from :mod:`shepherd_cli.commands.style`'s identically-purposed
    ``_resolve_bundled_styles_dir`` — self-contained-module convention (hard
    rule #9: no cross-command-module imports beyond this shared
    ``shepherd_cli`` layer), not an oversight. Exposed here, not only there,
    so ``shepherd home`` (issue #254) can resolve the SAME bundled root the
    ``style`` command group already does, without importing across command
    modules or re-deriving the walk-up logic a second, possibly-diverging
    way.

    Precedence, mirroring ``_lib.sh``'s ``shctx_skill_root``:

    1. ``SHCTX_SKILL_ROOT`` (the dispatcher exports this), if set.
    2. ``CLAUDE_PLUGIN_ROOT`` + ``/skills/context``, if set (a real
       plugin install, not a dev checkout).
    3. Otherwise, walk up from the resolved repo root looking for
       ``skills/context/styles``.

    Returns:
        The resolved bundled-styles directory path (need not exist on
        disk — callers check file existence themselves).
    """
    skill_root_env = os.environ.get("SHCTX_SKILL_ROOT", "")
    if skill_root_env:
        return os.path.join(skill_root_env, "styles")

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        return os.path.join(plugin_root, "skills", "context", "styles")

    root = resolve_repo_root()
    current = root
    while True:
        candidate = os.path.join(current, "skills", "context", "styles")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.join(root, "skills", "context", "styles")
        current = parent


def style_chain(
    profile: str,
    *,
    workdir: str | None = None,
    bundled_dir: str | None = None,
) -> list[tuple[str, str, bool]]:
    """Every tier's candidate path for one profile's style, as data.

    The single source of truth :func:`resolve_style_path` is built ON TOP
    OF this — not a parallel chain — so the two can never drift apart.
    Added for issue #254's ``shepherd home which``, which needs to SHOW
    the chain (every tier, resolved or not), not just pick a winner.

    Args:
        profile: The profile key.
        workdir: Optional workdir override (tests).
        bundled_dir: The bundled ``styles/`` directory (see
            :func:`bundled_styles_dir`); None reports the bundled tier as
            an empty, non-existent candidate rather than omitting the row
            entirely — a caller that wants to SHOW all four tiers (even
            an unresolvable bundled one) always gets four rows back.

    Returns:
        ``(tier_label, path, exists)`` for project/legacy/user/bundled,
        in that fixed precedence order — four entries, always.
    """
    candidates: list[tuple[str, str]] = [
        (SOURCE_PROJECT, canonical_style_path(profile, workdir)),
        (SOURCE_LEGACY, legacy_style_path(profile, workdir)),
        (SOURCE_USER, os.path.join(user_profiles_root(), profile, "style.md")),
        (SOURCE_BUNDLED, os.path.join(bundled_dir, f"{profile}.md") if bundled_dir else ""),
    ]
    return [(label, path, bool(path) and os.path.isfile(path)) for label, path in candidates]


def resolve_style_path(
    profile: str,
    *,
    workdir: str | None = None,
    bundled_dir: str | None = None,
) -> tuple[str, str] | None:
    """Resolve a profile's style file through the four-tier chain.

    Built on :func:`style_chain` — the first tier reporting ``exists``
    wins; this function does not construct its own candidate list.

    Args:
        profile: The profile key.
        workdir: Optional workdir override (tests).
        bundled_dir: The bundled ``styles/`` directory, when the caller
            has resolved it (``style.py`` owns that lookup); None skips
            the bundled tier.

    Returns:
        ``(path, source)`` for the first existing file — source is one
        of ``project``/``legacy``/``user``/``bundled`` — or None when no
        tier has it.
    """
    for source, path, exists in style_chain(profile, workdir=workdir, bundled_dir=bundled_dir):
        if exists:
            return path, source
    return None


def list_profiles(
    *,
    workdir: str | None = None,
    bundled_dir: str | None = None,
) -> list[tuple[str, str]]:
    """Enumerate every known profile with its winning source tier.

    Args:
        workdir: Optional workdir override (tests).
        bundled_dir: Optional bundled ``styles/`` directory to include.

    Returns:
        Sorted ``(profile, source)`` pairs — one entry per profile, the
        source being the tier :func:`resolve_style_path` would pick.
    """
    names: set[str] = set()

    project_root = project_profiles_root(workdir)
    if os.path.isdir(project_root):
        for entry in os.listdir(project_root):
            if os.path.isfile(os.path.join(project_root, entry, "style.md")):
                names.add(entry)

    legacy_root = os.path.join(workdir if workdir is not None else resolve_workdir(), "styles")
    if os.path.isdir(legacy_root):
        for entry in os.listdir(legacy_root):
            if entry.endswith(".md"):
                names.add(entry[: -len(".md")])

    user_root = user_profiles_root()
    if os.path.isdir(user_root):
        for entry in os.listdir(user_root):
            if os.path.isfile(os.path.join(user_root, entry, "style.md")):
                names.add(entry)

    if bundled_dir and os.path.isdir(bundled_dir):
        for entry in os.listdir(bundled_dir):
            if entry.endswith(".md"):
                names.add(entry[: -len(".md")])

    resolved: list[tuple[str, str]] = []
    for name in sorted(names):
        hit = resolve_style_path(name, workdir=workdir, bundled_dir=bundled_dir)
        if hit is not None:
            resolved.append((name, hit[1]))
    return resolved


__all__ = [
    "SOURCE_BUNDLED",
    "SOURCE_LEGACY",
    "SOURCE_PROJECT",
    "SOURCE_USER",
    "bundled_styles_dir",
    "canonical_style_path",
    "legacy_style_path",
    "list_profiles",
    "project_profiles_root",
    "resolve_style_path",
    "style_chain",
    "user_profiles_root",
]
