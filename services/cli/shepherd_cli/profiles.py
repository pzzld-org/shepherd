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

from shepherd_cli.resolution import resolve_user_home, resolve_workdir

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


def resolve_style_path(
    profile: str,
    *,
    workdir: str | None = None,
    bundled_dir: str | None = None,
) -> tuple[str, str] | None:
    """Resolve a profile's style file through the four-tier chain.

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
    candidates: list[tuple[str, str]] = [
        (canonical_style_path(profile, workdir), SOURCE_PROJECT),
        (legacy_style_path(profile, workdir), SOURCE_LEGACY),
        (os.path.join(user_profiles_root(), profile, "style.md"), SOURCE_USER),
    ]
    if bundled_dir:
        candidates.append((os.path.join(bundled_dir, f"{profile}.md"), SOURCE_BUNDLED))
    for path, source in candidates:
        if os.path.isfile(path):
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
    "canonical_style_path",
    "legacy_style_path",
    "list_profiles",
    "project_profiles_root",
    "resolve_style_path",
    "user_profiles_root",
]
