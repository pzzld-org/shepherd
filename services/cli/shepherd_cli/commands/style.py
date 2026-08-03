"""``shepherd style`` — style-guide init/show/list/edit Typer sub-app.

Bash source of truth: ``skills/context/scripts/cmd_style.sh`` (subcommands
``init|show|list|edit``), built on ``skills/context/scripts/_lib.sh``'s
``shctx_project_id``/``shctx_now``/``shctx_sql``/``shctx_skill_root``/
``shctx_uuid7`` helpers. Thin synchronous Typer command over an async data
layer, following :mod:`shepherd_cli.commands.mem`'s pattern: this module is
deliberately SELF-CONTAINED — its Pydantic output schema and its async
query helpers live inline here rather than in :mod:`shepherd_cli.schemas` /
:mod:`shepherd_cli.queries`.

WHY A SINGLE VARIADIC COMMAND, NOT FOUR ``@app.command()``s
=============================================================
``cmd_style.sh`` is one ``case "$sub" in ... esac`` block with parity
requirements that don't match Typer/Click's own subcommand-dispatch
defaults:

- **Default subcommand is ``list``, not a usage print.**
  ``sub="${1:-list}"`` — a bare ``shctx style`` runs ``list`` and exits
  with whatever ``list`` exits (0 unless something is very wrong), NOT a
  0-exit usage message like ``deliverable``/``signal``, and NOT a 1-exit
  usage error like ``mem``. This is a THIRD, distinct no-subcommand
  contract in this package, so it gets its own dispatcher rather than
  reusing either precedent.
- **Unknown subcommand exits 1, not Click's default 2.** The ``*)``
  branch prints ``"ERROR: usage: shctx style <init|show|list|edit>"`` to
  stderr and exits 1. Registering ``init``/``show``/``list``/``edit`` as
  separate ``@app.command()``s would hand unknown-subcommand handling to
  Click's own ``UsageError`` machinery, which exits 2 with a different
  message — wrong on both counts.

So this module registers ZERO ``@app.command()``s and instead defines one
``@app.callback(invoke_without_command=True)`` that captures every
remaining token as a raw ``list[str]`` (Click's ``nargs=-1`` via
``context_settings={"ignore_unknown_options": True}``, so a token like
``--all`` is captured literally instead of raising "no such option") and
dispatches on ``argv[0]`` exactly like bash's ``case`` statement —
including running ``list`` when ``argv`` is empty. ``--json`` (a value-add
this CLI offers beyond bash on ``list``/``show``, per the #198-wave
contract that every read command gets one) is deliberately NOT declared as
its own ``typer.Option`` alongside that catch-all argument: empirically
(verified against this project's vendored Click, typer 0.27), once a
``nargs=-1`` argument starts consuting tokens, a *later* recognized option
on the command line gets swallowed into the positional list instead of
being parsed as the option — so ``shepherd style list --json`` would leave
``json_out`` False and ``--json`` sitting in ``argv``. Detecting/stripping
the literal ``"--json"`` token from the raw ``argv`` list, by hand, before
dispatch, sidesteps that Click parsing gotcha entirely and works
regardless of where ``--json`` appears on the command line.

TWO DELIBERATE, DOCUMENTED DEVIATIONS FROM A BYTE-FOR-BYTE BASH PORT
=====================================================================
1. **Project-id resolution.** ``cmd_style.sh`` resolves ``project_id`` via
   ``shctx_project_id()`` (reads ``<workdir>/project.json`` through
   ``jq``) UNCONDITIONALLY at the top of the script, before dispatching to
   ANY subcommand — so even ``list``/``show`` (which touch no SQL in
   bash's plain-text mode) fail with that error if ``project.json`` is
   missing. This module instead mirrors
   :mod:`shepherd_cli.commands.mem`'s ``_require_project_id()`` approach —
   ``SELECT id FROM projects LIMIT 1`` against the ``projects`` table —
   because that table is what the shared test harness
   (:func:`tests.conftest.insert_project`) and every other ported command
   group scope through, not the JSON sidecar file. In a healthy project
   the two always resolve to the same id: both are written once,
   together, by ``shctx init``. The ORDERING is still bash-parity exact:
   project-id resolution happens before ANY subcommand dispatch,
   including an unrecognized one, so a missing project blocks
   ``list``/``show`` exactly as it does in bash. See
   :func:`_require_project_id`.
2. **Row id generation.** ``_lib.sh``'s ``shctx_uuid7`` builds a UUIDv7
   from ``date +%s%3N`` + ``/dev/urandom``. :func:`_uuid7` below is an
   independent, equally-valid UUIDv7 generator over the stdlib
   ``time``/``os.urandom`` (copied verbatim from
   :func:`shepherd_cli.commands.mem._uuid7` — the third
   self-contained module in this package that needs one, per this
   package's own "skillify repeated success" convention) — NOT
   byte-for-byte identical to bash's construction, but every id it
   produces is a spec-compliant, monotonically-sortable-by-creation-time
   UUIDv7, which is the only property either tool's rows or tests ever
   depend on.

Timestamps are epoch SECONDS throughout (``styles.created_at`` /
``updated_at``), matching ``_lib.sh``'s ``shctx_now`` (``date +%s``) — NOT
the epoch-millisecond unit ``teammates``/``deliverables``/
``session_signals`` use.

**WRITE-SAFETY (#250): only ``show``/``list`` are read-only.** ``init``
and ``edit`` both write (``_upsert_row``, plus ``init``'s file copy and
``edit``'s editor launch after a possible seed) and keep the
:func:`shepherd_cli.db.lifespan` default (``migrate=True``) — a fresh
project's first ``style init`` is exactly the self-heal-on-write case
that default exists for. ``show``/``list`` open the DB with
``migrate=False`` and pre-check :func:`shepherd_cli.db.schema_is_current`
first: a behind schema is refused loudly (one stderr line, exit 1)
instead of silently bumping a live project's schema version just because
an operator asked to read a style guide. See :func:`_style_async`.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import shutil
import subprocess
import time

import typer
from pydantic import BaseModel, ConfigDict
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.models import Project
from shepherd_cli.models_style import Style
from shepherd_cli.profiles import (
    canonical_style_path,
    legacy_style_path,
    list_profiles,
    resolve_style_path,
)
from shepherd_cli.resolution import resolve_db_path, resolve_repo_root, resolve_workdir

app = typer.Typer(
    add_completion=False,
    help="Style guide init/show/list/edit commands (bash: cmd_style.sh).",
)

#: Verbatim bash-parity error for an unrecognized subcommand — the ``*)``
#: default branch of ``cmd_style.sh`` prints this to stderr and exits 1.
#: Unlike ``deliverable``/``signal`` (0-exit usage on no args) or ``mem``
#: (1-exit usage on NO args too), style's no-args case runs ``list``
#: instead — this message is reachable ONLY via an unrecognized
#: subcommand name, never via a bare ``shepherd style``.
_USAGE_ERR = "ERROR: usage: shctx style <init|show|list|edit>"

#: The four subcommand names ``cmd_style.sh``'s ``case`` statement
#: recognizes — anything else falls through to :data:`_USAGE_ERR`.
_KNOWN_SUBCOMMANDS = ("init", "show", "list", "edit")

#: The two subcommands that never write (#250) — see the module
#: docstring's WRITE-SAFETY note. ``init``/``edit`` are not in this set:
#: both upsert a ``styles`` row (and may copy a bundled file into place),
#: so they keep :func:`shepherd_cli.db.lifespan`'s default self-heal.
_READ_ONLY_SUBCOMMANDS = ("show", "list")

#: #250 refusal message — this module's ``show``/``list`` open the DB with
#: ``migrate=False``, so a behind schema is reported this way instead of
#: being silently self-healed.
_SCHEMA_BEHIND_MSG = "schema is behind the shipped migrations; run: shepherd migrate"


# --------------------------------------------------------------------------
# Pydantic output schema.
# --------------------------------------------------------------------------
class StyleRow(BaseModel):
    """One ``styles`` row, as emitted by ``shepherd style list --json``.

    Mirrors every column of the ``styles`` table (see
    :class:`shepherd_cli.models_style.Style`) — bash's plain-text ``list``
    only ever prints filenames (``ls`` on the work directory's
    ``styles/`` folder), so this richer JSON shape is the value-add this
    CLI offers beyond bash, not a bash output it is matching byte-for-byte.

    Attributes:
        id: The row's UUIDv7-shaped primary key.
        project_id: The owning project's id.
        language: The style's language key, e.g. ``"python"``.
        source_path: Absolute path to the copied-in style guide in the
            project's work directory.
        active: ``1`` if active, ``0`` otherwise (the raw stored
            integer, not coerced to ``bool`` — see
            :class:`shepherd_cli.models_style.Style`'s docstring).
        created_at: Epoch seconds this row was first inserted.
        updated_at: Epoch seconds this row was last touched by an
            ``init``/``edit`` upsert.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    language: str
    source_path: str
    active: int
    created_at: int
    updated_at: int


# --------------------------------------------------------------------------
# Small stdlib helpers.
# --------------------------------------------------------------------------
def _now() -> int:
    """Return the current wall-clock time in epoch seconds.

    Returns:
        The current time as whole seconds since the Unix epoch, matching
        the unit ``_lib.sh``'s ``shctx_now`` (``date +%s``) uses for
        ``styles.created_at``/``updated_at``.
    """
    return int(time.time())


def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for a new ``styles`` row.

    Copied verbatim from :func:`shepherd_cli.commands.mem._uuid7` — see
    that function's docstring for the full rationale (independent,
    equally-valid UUIDv7 generator; not byte-for-byte identical to
    bash's ``shctx_uuid7`` construction, but spec-compliant and
    time-sortable, the only properties either tool's rows depend on).

    Returns:
        A lowercase, hyphenated UUIDv7 string, e.g.
        ``"018f4d2e-1234-7abc-89de-0123456789ab"``.
    """
    ts_ms = int(time.time() * 1000)
    raw = bytearray(16)
    raw[0:6] = ts_ms.to_bytes(6, "big")
    rand = os.urandom(10)
    raw[6] = 0x70 | (rand[0] & 0x0F)  # version nibble (0111) + 4 random bits
    raw[7] = rand[1]
    raw[8] = 0x80 | (rand[2] & 0x3F)  # variant bits (10) + 6 random bits
    raw[9:16] = rand[3:10]
    hex_str = raw.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


def _resolve_bundled_styles_dir() -> str:
    """Locate the bundled style-guide source directory (``skills/context/styles``).

    Mirrors ``_lib.sh``'s ``shctx_skill_root`` precedence for this one
    relative path (``<skill_root>/styles``):

    1. ``SHCTX_SKILL_ROOT`` (the dispatcher exports this — see
       ``_lib.sh``'s own comment on why it's preferred), if set.
    2. ``CLAUDE_PLUGIN_ROOT`` + ``/skills/context``, if set (a real
       plugin install, not a dev checkout).
    3. Otherwise, walk up from the resolved repo root looking for
       ``skills/context/styles`` — the practical equivalent of
       ``_lib.sh``'s final fallback (a path relative to ``_lib.sh``'s own
       location), adapted for this module's different file location
       (``shepherd_cli/commands/style.py`` has no ``skills/context``
       sibling of its own to resolve relative to, unlike the bash
       ``_lib.sh`` it mirrors).

    Not exposed by :mod:`shepherd_cli.resolution` (that module owns
    migrations-dir/schema-base/bash-shctx lookups only, per the #198
    disjoint-file-ownership contract for this porting wave) — this
    module's own narrow need for ONE more ``skills/context``-relative
    path is intentionally kept local rather than added to the shared
    module.

    Returns:
        The resolved bundled-styles directory path (need not exist on
        disk — callers check file existence themselves, matching bash's
        own lazy ``[[ -f "$src" ]]`` checks rather than failing here).
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


# --------------------------------------------------------------------------
# Inline async data layer (self-contained per the port's instructions).
# --------------------------------------------------------------------------
async def _active_project_id() -> str | None:
    """Return the sole registered project's id, or None if none exists.

    See the module docstring's deviation note #1: this queries the
    ``projects`` table (``SELECT id FROM projects LIMIT 1``, no
    ``ORDER BY``) rather than reading ``<workdir>/project.json`` the way
    ``cmd_style.sh``'s own ``shctx_project_id()`` does.

    Returns:
        The first ``projects.id``, or None if no project is registered.
    """
    project = await Project.all().first()
    return project.id if project is not None else None


async def _require_project_id() -> str:
    """Resolve the active project id, or exit 1 (bash-parity prerequisite gate).

    Bash parity: ``cmd_style.sh`` computes ``project_id=$(shctx_project_id)``
    UNCONDITIONALLY at the top of the script, before dispatching to any
    subcommand (even an unrecognized one), under ``set -eu -o pipefail`` —
    so a missing project aborts every subcommand with exit 1 before any
    subcommand-specific argument validation runs. :func:`_style_async`
    calls this FIRST, inside ``db.lifespan()``, before dispatching on
    ``argv[0]``, to preserve that exact ordering.

    Returns:
        The active project id.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if no project is
            registered.
    """
    project_id = await _active_project_id()
    if project_id is None:
        typer.echo("ERROR: no project registered — run 'shctx init' first", err=True)
        raise typer.Exit(code=1)
    return project_id


async def _upsert_row(lang: str, path: str, project_id: str, now: int) -> None:
    """Insert or update one ``styles`` row for ``(project_id, lang)``.

    Bash parity with ``cmd_style.sh``'s ``upsert_row``:

    .. code-block:: sql

        INSERT INTO styles (id,project_id,language,source_path,active,created_at,updated_at)
        VALUES (?,?,?,?,1,?,?)
        ON CONFLICT(project_id,language) DO UPDATE
          SET source_path=excluded.source_path, updated_at=excluded.updated_at

    A raw parameterized query, not the Tortoise ORM's ``get_or_create``/
    ``update_or_create`` — this is exactly the "ORM is a poor fit"
    case the port's ground rules call out: sqlite's ``ON CONFLICT ...
    DO UPDATE`` with a partial column list (preserving ``id``,
    ``created_at``, and ``active`` unchanged on a re-init) has no clean
    Tortoise equivalent. Unlike bash's own naive string-interpolated SQL
    (which never escapes a single quote in ``lang``/``path``), every
    value here is parameter-bound — a strict safety improvement with zero
    behavior change for the only inputs that ever reach this function in
    practice (bundled language keys and filesystem paths, never
    user-controlled free text containing a quote).

    Args:
        lang: The style's language key, e.g. ``"python"``.
        path: The absolute destination path the style guide was copied
            to (``<workdir>/styles/<lang>.md``).
        project_id: The owning project's id.
        now: Epoch seconds to stamp both ``created_at`` and
            ``updated_at`` with on a fresh insert (an ``ON CONFLICT``
            update only touches ``updated_at``, leaving the original
            row's ``created_at`` untouched — sqlite's ``excluded.*``
            resolves to the ATTEMPTED insert's values only for the
            columns the ``SET`` clause names).
    """
    connection = Tortoise.get_connection("default")
    await connection.execute_query(
        "INSERT INTO styles (id, project_id, language, source_path, active, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT(project_id, language) DO UPDATE "
        "SET source_path=excluded.source_path, updated_at=excluded.updated_at",
        [_uuid7(), project_id, lang, path, now, now],
    )


async def _init_one(lang: str, project_id: str, now: int, src_dir: str, dst_dir: str) -> None:
    """Copy one bundled style guide into the work directory and upsert its row.

    Bash parity with ``cmd_style.sh``'s ``init_one``: preserves an
    existing destination file untouched (never overwrites a
    project-local edit) but ALWAYS upserts the tracking row, even when
    the file already existed — so re-running ``init`` after a manual
    ``updated_at``-worthy change still refreshes the row's
    ``updated_at``.

    Args:
        lang: The style's language key, e.g. ``"python"``.
        project_id: The owning project's id.
        now: Epoch seconds for the upsert (see :func:`_upsert_row`).
        src_dir: The bundled skill's ``styles/`` source directory.
        dst_dir: The project work directory's ``styles/`` destination
            directory.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if
            ``<src_dir>/<lang>.md`` does not exist — bash-parity with
            ``[[ -f "$src" ]] || { echo "ERROR: no bundled style for
            $lang" >&2; return 1; }``.
    """
    src = os.path.join(src_dir, f"{lang}.md")
    # v6.4.1 profiles layout: new writes target the project canonical
    # profiles/<lang>/style.md (shepherd_cli.profiles). An EXISTING file in
    # either project tier — canonical or the pre-v6.4.1 flat legacy
    # styles/<lang>.md — is preserved in place (never overwritten, never
    # relocated; `shepherd migrate --layout v3` owns relocation).
    dst = canonical_style_path(lang)
    legacy = legacy_style_path(lang)
    if not os.path.isfile(src):
        typer.echo(f"ERROR: no bundled style for {lang}", err=True)
        raise typer.Exit(code=1)
    if os.path.isfile(dst):
        typer.echo(f"shctx style: {dst} already exists (preserving)")
    elif os.path.isfile(legacy):
        dst = legacy
        typer.echo(f"shctx style: {dst} already exists (preserving)")
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        typer.echo(f"shctx style: wrote {dst}")
    await _upsert_row(lang, dst, project_id, now)


async def _run_init(rest: list[str], project_id: str, now: int, src_dir: str, dst_dir: str) -> None:
    """Handle ``style init <lang|--all>``.

    Args:
        rest: Arguments after ``"init"`` — ``rest[0]`` is the language,
            or the literal ``"--all"``.
        project_id: The owning project's id.
        now: Epoch seconds shared across every row this invocation
            upserts — bash-parity: ``now=$(shctx_now)`` is computed ONCE
            at the top of the script, so an ``init --all`` run stamps
            every language's row with the SAME timestamp, not a
            per-language one.
        src_dir: The bundled skill's ``styles/`` source directory.
        dst_dir: The project work directory's ``styles/`` destination
            directory.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if ``rest`` is
            empty — bash: ``"ERROR: usage: shctx style init
            <lang|--all>"``. Also propagates :func:`_init_one`'s
            code-1 exit for any bundled-style-missing language,
            stopping the ``--all`` loop at the first failure (bash-parity:
            ``set -e`` aborts the ``for`` loop on ``init_one``'s first
            non-zero return).
    """
    arg = rest[0] if rest else ""
    if not arg:
        typer.echo("ERROR: usage: shctx style init <lang|--all>", err=True)
        raise typer.Exit(code=1)
    if arg == "--all":
        for src_path in sorted(glob.glob(os.path.join(src_dir, "*.md"))):
            lang = os.path.basename(src_path)[: -len(".md")]
            await _init_one(lang, project_id, now, src_dir, dst_dir)
    else:
        await _init_one(arg, project_id, now, src_dir, dst_dir)


async def _run_show(rest: list[str], dst_dir: str, json_out: bool) -> None:
    """Handle ``style show <lang>``.

    Args:
        rest: Arguments after ``"show"`` — ``rest[0]`` is the language.
        dst_dir: The project work directory's ``styles/`` destination
            directory.
        json_out: When True, print ``{"language", "source_path",
            "content"}`` instead of the raw file content — a value-add
            beyond bash's plain ``cat``.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if ``rest`` is
            empty (bash: ``"ERROR: usage: shctx style show <lang>"``),
            or if ``<dst_dir>/<lang>.md`` does not exist (bash: ``cat``'s
            own "No such file or directory" to stderr, exit 1 — this
            reproduces that shape rather than a bespoke ``ERROR:``
            message, since that IS what bash's ``show`` prints).
    """
    arg = rest[0] if rest else ""
    if not arg:
        typer.echo("ERROR: usage: shctx style show <lang>", err=True)
        raise typer.Exit(code=1)
    # v6.4.1: resolve through the four-tier chain (project profiles ->
    # legacy styles/ -> user profiles -> bundled) instead of one flat path.
    hit = resolve_style_path(arg, bundled_dir=_resolve_bundled_styles_dir())
    if hit is None:
        missing = canonical_style_path(arg)
        typer.echo(f"cat: {missing}: No such file or directory", err=True)
        raise typer.Exit(code=1)
    path, source = hit
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        typer.echo(f"cat: {path}: No such file or directory", err=True)
        raise typer.Exit(code=1) from exc
    if json_out:
        typer.echo(
            json.dumps(
                {"language": arg, "source_path": path, "source": source, "content": content},
                indent=2,
            )
        )
        return
    typer.echo(content, nl=False)


async def _run_list(project_id: str, dst_dir: str, json_out: bool) -> None:
    """Handle ``style list``.

    Args:
        project_id: The owning project's id (only used for the
            ``--json`` path — see below).
        dst_dir: The project work directory's ``styles/`` destination
            directory.
        json_out: When True, print a JSON array of :class:`StyleRow`
            (queried from the ``styles`` table, ordered by ``language``)
            instead of bash's plain ``ls`` output — a value-add beyond
            bash, which has no ``--json`` on this subcommand.

    Text-mode bash parity: ``[[ -d "$dst_dir" ]] && ls "$dst_dir" ||
    echo "(no styles initialized)"``. In practice ``dst_dir`` always
    exists by the time this runs (:func:`_style_async` unconditionally
    ``mkdir -p``'s it before dispatch, exactly like bash), so the
    ``else`` branch is effectively unreachable — mirrored anyway for
    structural fidelity with the bash script, not because it is expected
    to trigger.
    """
    if json_out:
        rows = await Style.filter(project_id=project_id).order_by("language")
        views = [StyleRow.model_validate(row) for row in rows]
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
        return
    # v6.4.1: enumerate profiles across all four tiers, annotated with the
    # winning source, instead of a flat ls of one directory.
    profiles = list_profiles(bundled_dir=_resolve_bundled_styles_dir())
    if profiles:
        for name, source in profiles:
            typer.echo(f"{name}\t{source}")
    else:
        typer.echo("(no styles initialized)")


async def _run_edit(rest: list[str], project_id: str, now: int, src_dir: str, dst_dir: str) -> None:
    """Handle ``style edit <lang>``.

    Bash parity with ``cmd_style.sh``'s ``edit`` branch: if the
    destination file doesn't exist yet, ``init_one`` runs first (so
    editing a never-initialized language seeds it from the bundled
    source, then opens the seeded copy); then ``"${EDITOR:-vi}"`` is
    launched on the file as a single literal executable name (bash's
    quoted ``"$EDITOR"`` does not shell-split a multi-word ``EDITOR``
    value — ``subprocess.run([editor, dst])`` mirrors that exactly,
    passing ``EDITOR``'s raw value as one argv[0] token rather than
    splitting it on whitespace).

    Args:
        rest: Arguments after ``"edit"`` — ``rest[0]`` is the language.
        project_id: The owning project's id (only used if ``init_one``
            runs).
        now: Epoch seconds for the upsert, if ``init_one`` runs.
        src_dir: The bundled skill's ``styles/`` source directory.
        dst_dir: The project work directory's ``styles/`` destination
            directory.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if ``rest`` is
            empty (bash: ``"ERROR: usage: shctx style edit <lang>"``);
            propagates :func:`_init_one`'s code-1 exit if the language
            has no bundled source AND no existing destination file; with
            the editor subprocess's own exit code if it is non-zero
            (bash: the editor's exit status is the script's own, being
            the last command run).
    """
    arg = rest[0] if rest else ""
    if not arg:
        typer.echo("ERROR: usage: shctx style edit <lang>", err=True)
        raise typer.Exit(code=1)
    # Edit the existing project-tier file in place (canonical first, then
    # the legacy flat path); seed the canonical path from the bundle only
    # when NEITHER exists. Relocation stays `migrate --layout v3`'s job.
    dst = canonical_style_path(arg)
    if not os.path.isfile(dst):
        legacy = legacy_style_path(arg)
        if os.path.isfile(legacy):
            dst = legacy
        else:
            await _init_one(arg, project_id, now, src_dir, dst_dir)
    editor = os.environ.get("EDITOR") or "vi"
    result = subprocess.run([editor, dst], check=False)  # noqa: S603 - EDITOR is an operator-controlled env var, bash-parity invocation.
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


# --------------------------------------------------------------------------
# Dispatcher + Typer wiring.
# --------------------------------------------------------------------------
async def _style_async(argv: list[str], json_out: bool) -> None:
    """Resolve the project, then dispatch on ``argv[0]`` exactly like ``cmd_style.sh``'s ``case``.

    Args:
        argv: The raw remaining command-line tokens after ``style``
            (with any ``--json`` token already stripped by the
            callback), e.g. ``["init", "python"]`` or ``[]``.
        json_out: Whether ``--json`` was present anywhere on the command
            line (``list``/``show`` only — ``init``/``edit`` ignore it,
            matching bash, which has no ``--json`` concept at all).

    Raises:
        typer.Exit: Propagated from whichever subcommand handler ran;
            code 1 with :data:`_USAGE_ERR` on stderr if ``argv[0]`` is
            not one of :data:`_KNOWN_SUBCOMMANDS` (bash's ``*)`` branch).
            Also code 1 with :data:`_SCHEMA_BEHIND_MSG` on stderr, for
            ``show``/``list`` only, if the DB's schema is behind the
            shipped migrations (#250) — checked BEFORE ``db.lifespan``
            opens, since those two subcommands open it with
            ``migrate=False`` (see the module docstring).
    """
    sub = argv[0] if argv else "list"
    rest = argv[1:]
    read_only = sub in _READ_ONLY_SUBCOMMANDS

    if read_only and not db.schema_is_current(resolve_db_path()):
        typer.echo(_SCHEMA_BEHIND_MSG, err=True)
        raise typer.Exit(code=1)

    async with db.lifespan(migrate=not read_only):
        project_id = await _require_project_id()
        now = _now()
        src_dir = _resolve_bundled_styles_dir()
        dst_dir = os.path.join(resolve_workdir(), "styles")
        os.makedirs(dst_dir, exist_ok=True)

        if sub == "init":
            await _run_init(rest, project_id, now, src_dir, dst_dir)
            return
        if sub == "show":
            await _run_show(rest, dst_dir, json_out)
            return
        if sub == "list":
            await _run_list(project_id, dst_dir, json_out)
            return
        if sub == "edit":
            await _run_edit(rest, project_id, now, src_dir, dst_dir)
            return

    typer.echo(_USAGE_ERR, err=True)
    raise typer.Exit(code=1)


@app.callback(invoke_without_command=True, context_settings={"ignore_unknown_options": True})
def style(
    args: list[str] = typer.Argument(
        None,
        help="Subcommand + args: 'init <lang|--all>' | 'show <lang>' | 'list' | 'edit <lang>'. Defaults to 'list'.",
    ),
) -> None:
    """Style guide init/show/list/edit — native port of ``shctx style``.

    See the module docstring for why this is ONE variadic callback
    rather than four ``@app.command()``s: bash's default-to-``list`` and
    exit-1-on-unknown-subcommand contracts don't match Typer/Click's own
    subcommand-dispatch defaults, and a formal ``--json`` ``typer.Option``
    declared alongside a catch-all ``nargs=-1`` argument is unreliably
    parsed by this project's vendored Click when ``--json`` appears AFTER
    the first positional token — so ``--json`` is detected by hand from
    the raw ``args`` list instead.

    Args:
        args: Every token after ``style`` on the command line, in order,
            with NOTHING pre-parsed as flags/options by Click (see
            ``context_settings={"ignore_unknown_options": True}`` on this
            callback, which is what makes a token like ``--all`` land
            here as a literal string instead of raising "no such
            option"). ``None``/empty means a bare ``shepherd style`` —
            dispatched as ``list``, per bash's ``sub="${1:-list}"``.
    """
    raw = list(args or [])
    json_out = "--json" in raw
    if json_out:
        raw = [token for token in raw if token != "--json"]
    asyncio.run(_style_async(raw, json_out=json_out))


__all__ = ["app", "StyleRow"]
