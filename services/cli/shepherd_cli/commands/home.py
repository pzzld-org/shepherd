"""``shepherd home`` — bootstrap and inspect the optional user-level shepherd tier (issue #254).

v6.4.1 introduced a user-level tier at ``~/.shepherd`` (``SHEPHERD_HOME``
overridable) so a Rust/Python/... style guide and a template override could
be shared across every project on a machine, not re-declared per project:

- ``~/.shepherd/profiles/<profile>/style.md`` — read by
  :func:`shepherd_cli.profiles.resolve_style_path` as tier 3 of 4
  (project → legacy → user → bundled).
- ``~/.shepherd/templates/`` — read by
  :func:`shepherd_cli.render.template_search_paths` as tier 2 of 3
  (project → user → bundled).

Both were READ-ONLY lookups: nothing in the CLI ever created either path.
``resolve_user_home()``'s own docstring says the path "need not exist" —
true of every OTHER path that function-family resolves, but for this one
tier it meant the mechanism had no bootstrap verb at all. An operator who
wanted to carry one style profile across every project had to know the
undocumented path shape and ``mkdir -p`` it by hand. This module is that
missing bootstrap verb, plus the visibility half of the same issue: making
the four/three-tier resolution chain inspectable instead of implicit.

NEW command group, NO bash predecessor — unlike most of this package,
``cmd_home.sh`` never existed. There is therefore no bash-parity usage text
to reproduce byte-for-byte and no bash exit-code contract to match: this
module uses Typer/Click's own ``--help`` machinery (``add_completion=False``
is the only override, matching every other NEW-in-Python sub-app in this
package, e.g. :mod:`shepherd_cli.commands.loop`) rather than the
``help_option_names=[]`` + hand-rolled usage-heredoc pattern
:mod:`shepherd_cli.commands.ready`/:mod:`shepherd_cli.commands.prune` use to
reproduce THEIR bash predecessors' exact ``-h``/``--help`` text. A bare
``shepherd home`` (no subcommand) prints Typer's own help and exits 0
(``no_args_is_help=True``, Click's default for a Typer app with
subcommands and no callback of its own).

**Filesystem-only, no DB access.** Every subcommand here reads/writes
plain paths (``os.makedirs``/``os.path.isfile``/``shutil.copyfile``) — no
``shepherd_cli.db``, no ``db.lifespan()``, no Tortoise model. Hard rule 7's
"pure subprocess/filesystem command needs no lifespan" applies in full, the
same as :mod:`shepherd_cli.commands.ready`/:mod:`shepherd_cli.commands.sync`.

**Single source of truth, not a parallel chain.** ``home which`` renders
:func:`shepherd_cli.profiles.style_chain` / a
:mod:`shepherd_cli.render`-side equivalent
(:func:`shepherd_cli.render.template_search_chain`) — the SAME chain data
:func:`shepherd_cli.profiles.resolve_style_path` (and, transitively,
``shepherd style show``) picks a winner from. Nothing in this module
re-derives the four-tier/three-tier path shapes independently; see those
two modules' own docstrings for why (and for the ``bundled_styles_dir()``
duplication note — a small, deliberate, self-contained-module duplication
of :mod:`shepherd_cli.commands.style`'s private bundled-dir lookup, NOT a
cross-command-module import, per hard rule 9).
"""

from __future__ import annotations

import os
import shutil

import typer

from shepherd_cli import profiles, render
from shepherd_cli.resolution import resolve_user_home

app = typer.Typer(
    add_completion=False,
    help="Bootstrap and inspect the user-level shepherd home (~/.shepherd) — profiles/templates shared across every project.",
)


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------
@app.command("init")
def init(
    profile: list[str] = typer.Option(
        [],
        "--profile",
        help=(
            "Also seed ~/.shepherd/profiles/<name>/style.md from the bundled default "
            "(skills/context/styles/<name>.md). Repeatable; never overwrites an existing file."
        ),
    ),
) -> None:
    """Create ``~/.shepherd/profiles/`` and ``~/.shepherd/templates/`` if absent.

    Idempotent: a directory that already exists is reported as
    "already present" and left untouched — a second run creates nothing.
    Every path this invocation actually created is printed, one per line,
    plus the resolved home itself (created or not).

    Args:
        profile: Profile names to additionally seed from the bundled
            default. A profile whose user-tier file already exists is
            preserved (never overwritten) — the same "preserve, never
            clobber a project-local edit" contract
            :func:`shepherd_cli.commands.style._init_one` uses for the
            project tier. A profile with no bundled default is reported
            and skipped, not fatal — the other roots/profiles this
            invocation asked for still get created/seeded.
    """
    home = resolve_user_home()
    typer.echo(f"shepherd home: {home}")

    for path in (profiles.user_profiles_root(), render.user_templates_dir()):
        if os.path.isdir(path):
            typer.echo(f"  {path} already present")
        else:
            os.makedirs(path, exist_ok=True)
            typer.echo(f"  created {path}")

    if not profile:
        return

    bundled_dir = profiles.bundled_styles_dir()
    for name in profile:
        dst = os.path.join(profiles.user_profiles_root(), name, "style.md")
        if os.path.isfile(dst):
            typer.echo(f"  {dst} already exists (preserving)")
            continue
        src = os.path.join(bundled_dir, f"{name}.md")
        if not os.path.isfile(src):
            typer.echo(f"  no bundled style for {name} (skipped)", err=True)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        typer.echo(f"  wrote {dst}")


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------
def _profiles_present(profiles_root: str) -> list[str]:
    """Every profile with a real ``style.md`` under ``profiles_root``, sorted."""
    if not os.path.isdir(profiles_root):
        return []
    names = []
    for entry in sorted(os.listdir(profiles_root)):
        if os.path.isfile(os.path.join(profiles_root, entry, "style.md")):
            names.append(entry)
    return names


def _templates_present(templates_root: str) -> list[str]:
    """Every ``*.j2`` template path under ``templates_root``, relative, sorted."""
    if not os.path.isdir(templates_root):
        return []
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(templates_root):
        for filename in filenames:
            if filename.endswith(".j2"):
                found.append(os.path.relpath(os.path.join(dirpath, filename), templates_root))
    return sorted(found)


@app.command("show")
def show() -> None:
    """Print the resolved user home, whether it exists, and its contents. Read-only.

    Exits 0 whether or not ``~/.shepherd`` exists — a missing user home is
    the normal, unconfigured state (the tier is entirely optional), not an
    error condition.
    """
    home = resolve_user_home()
    typer.echo(f"user home: {home}")

    if not os.path.isdir(home):
        typer.echo("  status: not created (run 'shepherd home init')")
        return
    typer.echo("  status: present")

    profile_names = _profiles_present(profiles.user_profiles_root())
    if profile_names:
        typer.echo(f"  profiles ({len(profile_names)}): {', '.join(profile_names)}")
    else:
        typer.echo("  profiles: (none)")

    template_names = _templates_present(render.user_templates_dir())
    if template_names:
        typer.echo(f"  templates ({len(template_names)}): {', '.join(template_names)}")
    else:
        typer.echo("  templates: (none)")


# --------------------------------------------------------------------------
# which
# --------------------------------------------------------------------------
def _render_chain(chain: list[tuple[str, str, bool]]) -> None:
    """Print one precedence chain, marking the first ``exists`` tier as resolved.

    Args:
        chain: ``(tier_label, path, exists)`` rows in precedence order —
            :func:`shepherd_cli.profiles.style_chain` or
            :func:`shepherd_cli.render.template_search_chain`.
    """
    resolved_index = next((i for i, (_label, _path, exists) in enumerate(chain) if exists), None)
    label_width = max(len(label) for label, _path, _exists in chain)
    for index, (label, path, exists) in enumerate(chain):
        display_path = path if path else "(bundled root unknown)"
        if index == resolved_index:
            marker = "<- resolved"
        elif exists:
            marker = "(present)"
        else:
            marker = "(missing)"
        typer.echo(f"{label:<{label_width}}  {display_path}  {marker}")


@app.command("which")
def which(
    name: str = typer.Argument(..., help="Profile name (style chain), or template name with --template."),
    template: bool = typer.Option(
        False, "--template", help="Resolve NAME as a template (render.py's chain) instead of a style profile."
    ),
) -> None:
    """Print the full precedence chain for one profile's style, or one template, with the winning tier marked.

    Reuses :func:`shepherd_cli.profiles.style_chain` (style mode, four
    tiers: project/legacy/user/bundled) or
    :func:`shepherd_cli.render.template_search_chain` (``--template``,
    three tiers: project/user/bundled) — the SAME chain data
    ``resolve_style_path``/``render_template`` themselves resolve through,
    so the marked tier here can never disagree with what actually gets
    used.

    Args:
        name: The profile key (style mode) or template filename
            (``--template`` mode, e.g. ``handoff.md`` or
            ``handoff.md.j2`` — bare stems resolve the same ``.j2``-suffix
            fallback :func:`shepherd_cli.render.render_template` uses).
        template: Switch to template-chain mode.
    """
    if template:
        _render_chain(render.template_search_chain(name))
    else:
        _render_chain(profiles.style_chain(name, bundled_dir=profiles.bundled_styles_dir()))


__all__ = ["app"]
