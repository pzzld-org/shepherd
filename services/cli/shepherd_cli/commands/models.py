"""``shepherd models`` — per-role subagent model map Typer sub-app.

Native port of ``skills/context/scripts/cmd_models.sh``: PURE CONFIG, NO
DATABASE. Resolves each flock/meta role (``root``, ``planter``, ``engineer``,
``conductor``, ``critic``, ``discovery``, ``coder``, ``auditor``, ``worker``)
to the model slug it dispatches with, reading the ``[models]`` section of
``shepherd.toml`` with the SAME local -> project -> XDG precedence
``_lib.sh``'s ``cfg_section_get`` uses, falling back to the built-in
defaults (``root``/``planter``/``engineer`` = ``opus[1m]``; the rest =
``sonnet``) when a role has no explicit key.

This module never opens a database connection — it is the one command
group in this CLI that is 100% filesystem + config, matching
``cmd_models.sh``'s own lack of any ``shctx_sql``/``shctx_db_path`` call.
Every function here is plain synchronous Python; there is no
``asyncio.run``/``db.lifespan`` boundary to cross (hard rule #7's
"pure-config command with no DB access needs no lifespan" case).

Bash parity is the bar for both subcommands:

- ``resolve <role>`` — echoes the resolved model slug for one role.
  Missing ``<role>`` exits 2 with ``ERROR: usage: shctx models resolve
  <role>`` on stderr; an unrecognized role exits 2 with ``ERROR: unknown
  role: <role> (valid: ...)`` on stderr.
- ``show [--md|--json]`` — prints the full resolved 9-role table plus a
  per-row ``config``/``default`` source flag, in one of three formats
  (plain text is the default).
- The bare no-subcommand invocation (``shctx models`` with no further
  args) is a SPECIAL case in ``cmd_models.sh``: unlike most other
  ``cmd_*.sh`` scripts (whose ``""|help)`` branch prints a usage blurb),
  ``cmd_models.sh``'s dispatch routes an empty ``$1`` into the SAME
  branch as ``show`` — i.e. bare ``shctx models`` prints the resolved
  table in plain-text format and exits 0, exactly like ``shctx models
  show`` with no flags. ``-h``/``--help``/``help`` are the ones that
  print the ``usage()`` blurb and exit 0 (mirrored here via an eager
  ``-h``/``--help`` option plus an explicit ``help`` subcommand).

One deliberate ADDITIVE deviation from ``cmd_models.sh`` (documented, not
silent): ``resolve`` gains an optional ``--json`` flag bash's ``resolve``
branch does not have, per hard rule #7 ("Provide --json on every read
command"). Omitting ``--json`` reproduces bash's exact bare-slug stdout
byte-for-byte; passing it is new, additive behavior only, never invoked by
any bash-parity code path.
"""

from __future__ import annotations

import json
import os
import tomllib

import typer
from pydantic import BaseModel, ConfigDict

from shepherd_cli.resolution import resolve_repo_root

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": []},
    help="Per-role subagent model map (resolve one role, or show the full table).",
)

#: Canonical role set, in ``cmd_models.sh``'s exact ``MODELS_ROLES`` order —
#: both the validity check in ``resolve`` and the row order in ``show``
#: iterate this tuple.
MODELS_ROLES: tuple[str, ...] = (
    "root",
    "planter",
    "engineer",
    "conductor",
    "critic",
    "discovery",
    "coder",
    "auditor",
    "worker",
)

#: Roles whose built-in default is ``opus[1m]`` (``_model_default``'s first
#: case arm in ``cmd_models.sh``). Every other role in :data:`MODELS_ROLES`
#: defaults to ``sonnet``.
_OPUS_ROLES = frozenset({"root", "planter", "engineer"})

#: Verbatim bash-parity usage text — ``usage()`` in ``cmd_models.sh``.
#: Printed to stdout (bash parity: plain ``cat``, not stderr) on
#: ``resolve``/``show``/`` -h``/``--help``/``help``.
_USAGE = (
    "shctx models <resolve|show> [args]\n"
    "\n"
    "  resolve <role>        Echo the resolved model slug for one role\n"
    "                        (explicit [models].<role> key, else built-in default).\n"
    "                        Roles: root planter engineer conductor critic\n"
    "                               discovery coder auditor worker\n"
    "  show [--md|--json]    Print the full resolved 9-role table + source per row.\n"
    "\n"
    "The [models] block in .claude/shepherd.toml is the single map; unset roles fall\n"
    "to the built-in defaults (root/planter/engineer = opus[1m]; the rest = sonnet).\n"
    "See docs/configuration.md §models."
)

#: Trailing footer of the plain-text ``show`` rendering, verbatim from
#: ``cmd_models.sh``'s final ``printf`` in the text-format branch.
_TEXT_FOOTER = (
    "root is advisory (your live session model). The 8 spawned roles are\n"
    "hard-driven: each dispatching tier injects `shctx models resolve <role>` as\n"
    "the model pin. See docs/configuration.md §models."
)

#: Trailing footer of the ``--md`` rendering, verbatim from ``cmd_models.sh``.
_MD_FOOTER = (
    "_root is advisory: it names the model your live session should run; "
    "a config key cannot rebind a running main-chat session._"
)


class ModelRoleResolution(BaseModel):
    """One resolved ``(role, model, source)`` triple.

    Mirrors one row of ``cmd_models.sh``'s ``_model_row`` output: the
    role's resolved model slug plus where it came from.

    Attributes:
        role: The role name, one of :data:`MODELS_ROLES`.
        model: The resolved model slug, e.g. ``"opus[1m]"`` or
            ``"sonnet"``.
        source: ``"config"`` when an explicit ``[models].<role>`` key was
            found (local -> project -> XDG precedence); ``"default"``
            when no override was found and the built-in default was
            used.
    """

    model_config = ConfigDict(from_attributes=True)

    role: str
    model: str
    source: str


def _model_default(role: str) -> str:
    """Return the built-in default model slug for one role.

    Bash parity with ``cmd_models.sh``'s ``_model_default``: only called
    for roles already validated against :data:`MODELS_ROLES` by every
    caller in this module, so the bash ``*) echo "";;`` unreachable-in-
    practice arm has no Python equivalent here.

    Args:
        role: A role name from :data:`MODELS_ROLES`.

    Returns:
        ``"opus[1m]"`` for ``root``/``planter``/``engineer``; ``"sonnet"``
        for every other role.
    """
    return "opus[1m]" if role in _OPUS_ROLES else "sonnet"


def _config_search_paths(repo_root: str) -> tuple[str, str, str]:
    """The three config file paths checked, in precedence order.

    Bash parity with ``_lib.sh``'s ``cfg_section_get`` file loop:
    ``.claude/shepherd.local.toml`` (per-key local override) ->
    ``.claude/shepherd.toml`` (project) -> ``$XDG_CONFIG_HOME/shepherd.toml``
    (user global, falling back to ``$HOME/.config`` when
    ``XDG_CONFIG_HOME`` is unset or empty — the same ``${VAR:-default}``
    semantics bash uses, reproduced here via ``or`` short-circuiting on
    both an absent AND an empty-string environment variable).

    Args:
        repo_root: The resolved repository root (``shctx_repo_root`` /
            :func:`shepherd_cli.resolution.resolve_repo_root`).

    Returns:
        The three candidate file paths, in the order they must be tried.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or ""
    if not xdg_config_home:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        xdg_config_home = os.path.join(home, ".config")
    return (
        os.path.join(repo_root, ".claude", "shepherd.local.toml"),
        os.path.join(repo_root, ".claude", "shepherd.toml"),
        os.path.join(xdg_config_home, "shepherd.toml"),
    )


def _cfg_section_get(section: str, key: str, repo_root: str) -> str | None:
    """Read one ``key`` under one ``[section]``, by the shared config precedence.

    Bash parity with ``_lib.sh``'s ``cfg_section_get``: the FIRST file (in
    local -> project -> XDG order) that both exists AND has a non-empty
    value for ``[section].key`` wins; a file that exists but omits the
    section/key, or sets it to an empty string, is skipped in favor of
    the next file in the precedence chain (mirroring bash's
    ``[[ -n "$v" ]] || continue`` per-file check).

    Uses stdlib ``tomllib`` for real TOML parsing rather than bash's
    line-oriented ``awk`` scan — a strict superset for the simple
    ``[section]`` / ``key = "value"`` shape ``cmd_models.sh`` and its
    config docs describe; a malformed TOML file is treated as absent
    (skipped) rather than raising, so one broken config file never takes
    down a read-only resolve/show call.

    Args:
        section: The TOML table name, e.g. ``"models"``.
        key: The key within that table, e.g. a role name.
        repo_root: The resolved repository root, for locating the local/
            project config files.

    Returns:
        The value as a string (non-string TOML values are coerced via
        ``str()``, matching bash's all-text ``grep``-based reads), or
        None if no candidate file has a non-empty value for this key.
    """
    for path in _config_search_paths(repo_root):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        section_table = data.get(section)
        if not isinstance(section_table, dict):
            continue
        value = section_table.get(key)
        if value is None:
            continue
        value_str = str(value)
        if value_str:
            return value_str
    return None


def _resolve_role(role: str, repo_root: str) -> ModelRoleResolution:
    """Resolve one role to its model slug and source.

    Args:
        role: A role name from :data:`MODELS_ROLES` (not re-validated
            here; callers validate against :data:`MODELS_ROLES` first).
        repo_root: The resolved repository root.

    Returns:
        The role's :class:`ModelRoleResolution` — ``source="config"``
        when an explicit ``[models].<role>`` key was found, else
        ``source="default"`` with the built-in default slug.
    """
    configured = _cfg_section_get("models", role, repo_root)
    if configured:
        return ModelRoleResolution(role=role, model=configured, source="config")
    return ModelRoleResolution(role=role, model=_model_default(role), source="default")


def _resolve_all(repo_root: str) -> list[ModelRoleResolution]:
    """Resolve every role in :data:`MODELS_ROLES`, in that exact order.

    Args:
        repo_root: The resolved repository root.

    Returns:
        One :class:`ModelRoleResolution` per role, in ``MODELS_ROLES``
        order (bash parity with ``cmd_models.sh``'s ``for r in
        $MODELS_ROLES`` loop order).
    """
    return [_resolve_role(role, repo_root) for role in MODELS_ROLES]


def _render_text(rows: list[ModelRoleResolution]) -> str:
    """Render rows as bash-parity plain text (``show``'s default format).

    Column formatting mirrors ``printf '  %-10s %-10s (%s)\\n'`` exactly:
    two leading spaces, role left-justified to 10 columns, one space,
    model left-justified to 10 columns, one space, then ``(source)``.

    Args:
        rows: Resolved rows, already in display order.

    Returns:
        The full multi-line report: header, one row per role, then the
        advisory footer — matching ``cmd_models.sh``'s text branch
        exactly (including the blank line the footer's leading ``\\n``
        produces).
    """
    lines = ["shepherd model map (resolved)"]
    lines.extend(f"  {row.role:<10} {row.model:<10} ({row.source})" for row in rows)
    lines.append("")
    lines.append(_TEXT_FOOTER)
    return "\n".join(lines)


def _render_md(rows: list[ModelRoleResolution]) -> str:
    """Render rows as a bash-parity markdown table (``show --md``).

    Args:
        rows: Resolved rows, already in display order.

    Returns:
        A markdown table (header + separator + one row per role) plus
        the advisory footer, matching ``cmd_models.sh``'s ``--md`` branch
        exactly.
    """
    lines = ["| role | model | source |", "|---|---|---|"]
    lines.extend(f"| {row.role} | `{row.model}` | {row.source} |" for row in rows)
    lines.append("")
    lines.append(_MD_FOOTER)
    return "\n".join(lines)


def _render_json(rows: list[ModelRoleResolution]) -> str:
    """Render rows as a bash-parity JSON object keyed by role (``show --json``).

    Bash parity with ``cmd_models.sh``'s ``--json`` branch: a single JSON
    object (NOT an array), one ``"role": {"model": ..., "source": ...}``
    entry per role in :data:`MODELS_ROLES` order, comma-separated with no
    trailing comma — reproduced here by hand rather than via
    ``json.dumps(..., indent=2)`` (whose per-key multi-line expansion
    would not match bash's one-line-per-role ``printf`` shape byte for
    byte).

    Args:
        rows: Resolved rows, already in display order.

    Returns:
        The JSON text, still valid JSON overall (each individual value is
        produced via ``json.dumps`` for correct escaping) even though the
        surrounding structure is assembled manually to match bash's exact
        layout.
    """
    entries = [
        f'  "{row.role}": {{"model": {json.dumps(row.model)}, "source": {json.dumps(row.source)}}}'
        for row in rows
    ]
    return "{\n" + ",\n".join(entries) + "\n}"


def _render(fmt: str, repo_root: str) -> str:
    """Resolve every role and render it in the requested format.

    Args:
        fmt: One of ``"text"``, ``"md"``, or ``"json"``.
        repo_root: The resolved repository root.

    Returns:
        The fully rendered report string (no trailing newline; callers
        print it via ``typer.echo``, which appends exactly one).
    """
    rows = _resolve_all(repo_root)
    if fmt == "json":
        return _render_json(rows)
    if fmt == "md":
        return _render_md(rows)
    return _render_text(rows)


def _help_callback(value: bool) -> None:
    """Eager ``-h``/``--help`` handler shared by the group and ``show``.

    Bash parity with ``cmd_models.sh``'s ``-h|--help|help) usage; exit
    0;;`` branch: prints the verbatim ``usage()`` text to stdout and
    exits 0, short-circuiting before any subcommand body runs. Registered
    as an eager Click option callback (mirroring ``shepherd_cli.app``'s
    ``--version``/``-V`` pattern) rather than Typer/Click's own automatic
    ``--help`` machinery, which this sub-app disables entirely via
    ``context_settings={"help_option_names": []}`` so its output can
    match ``cmd_models.sh`` byte-for-byte instead of Click's
    autogenerated help text.

    Args:
        value: True when ``-h``/``--help`` was passed.

    Raises:
        typer.Exit: code 0, after printing the usage text, when ``value``
            is True.
    """
    if value:
        typer.echo(_USAGE)
        raise typer.Exit(code=0)


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    help_: bool = typer.Option(
        False,
        "-h",
        "--help",
        callback=_help_callback,
        is_eager=True,
        expose_value=False,
        help="Show usage and exit.",
    ),
) -> None:
    """Print the resolved model table when invoked with no subcommand.

    Bash parity with ``cmd_models.sh``'s dispatch: an empty ``$1`` falls
    into the SAME ``show|"")`` branch as the ``show`` subcommand itself
    (plain-text format, no flags) — UNLIKE most other ``cmd_*.sh``
    scripts, whose no-subcommand branch prints a usage blurb instead.
    ``-h``/``--help`` are handled separately, above, by
    :func:`_help_callback` (eager, so they short-circuit before this body
    runs regardless of ``ctx.invoked_subcommand``).

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only
            when ``shepherd models`` is run with no subcommand.
        help_: Unused directly (the eager callback handles it and exits
            before this parameter would otherwise be read); present only
            so Click parses ``-h``/``--help`` as a recognized option
            instead of an unknown-option error.

    Raises:
        typer.Exit: code 0, after printing the resolved table, when no
            subcommand was given.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(_render("text", resolve_repo_root()))
        raise typer.Exit(code=0)


@app.command("help")
def help_cmd() -> None:
    """Print usage and exit 0 (bash parity: ``cmd_models.sh``'s ``help`` word).

    Raises:
        typer.Exit: code 0, always, after printing the usage text.
    """
    typer.echo(_USAGE)
    raise typer.Exit(code=0)


@app.command()
def resolve(
    role: str | None = typer.Argument(
        None,
        metavar="ROLE",
        help=f"Role to resolve. One of: {', '.join(MODELS_ROLES)}.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help=(
            "ADDITIVE (not in cmd_models.sh): emit {\"role\", \"model\", \"source\"} "
            "as JSON instead of the bare model slug."
        ),
    ),
) -> None:
    """Echo the resolved model slug for one role.

    Native port of ``cmd_models.sh``'s ``resolve`` branch: explicit
    ``[models].<role>`` key (local -> project -> XDG precedence) wins,
    else the built-in default for that role.

    Args:
        role: The role to resolve; required (validated after parsing, not
            via Typer's ``required=True``, so bash's exact ``ERROR:
            usage: ...`` message on a missing argument is reproduced
            verbatim rather than Click's own "missing argument" error).
        json_out: ADDITIVE convenience flag, not present in
            ``cmd_models.sh``: when set, print
            ``{"role": ..., "model": ..., "source": ...}`` instead of the
            bare model slug. Omitting it reproduces bash's exact output.

    Raises:
        typer.Exit: code 2 (stderr message, bash parity) if ``role`` is
            missing/empty, or is not one of :data:`MODELS_ROLES`.
    """
    if not role:
        typer.echo("ERROR: usage: shctx models resolve <role>", err=True)
        raise typer.Exit(code=2)
    if role not in MODELS_ROLES:
        typer.echo(f"ERROR: unknown role: {role} (valid: {' '.join(MODELS_ROLES)})", err=True)
        raise typer.Exit(code=2)

    resolved = _resolve_role(role, resolve_repo_root())
    if json_out:
        typer.echo(json.dumps(resolved.model_dump(mode="json"), indent=2))
    else:
        typer.echo(resolved.model)


@app.command()
def show(
    md: bool = typer.Option(False, "--md", help="Emit a markdown table instead of plain text."),
    json_out: bool = typer.Option(
        False, "--json", help="Emit a JSON object (keyed by role) instead of plain text."
    ),
    help_: bool = typer.Option(
        False,
        "-h",
        "--help",
        callback=_help_callback,
        is_eager=True,
        expose_value=False,
        help="Show usage and exit.",
    ),
) -> None:
    """Print the full resolved 9-role table, with a source flag per row.

    Native port of ``cmd_models.sh``'s ``show`` branch. With neither
    ``--md`` nor ``--json``, prints the plain-text table (the same output
    bare ``shepherd models`` prints).

    Args:
        md: Emit a markdown table.
        json_out: Emit a JSON object keyed by role. Takes precedence over
            ``--md`` if both are given (bash's arg-parsing loop lets the
            LAST flag win in whatever order they appear on the command
            line; this reproduces the common case of exactly one format
            flag being passed).
        help_: Unused directly; the eager callback handles ``-h``/
            ``--help`` and exits before this parameter would otherwise be
            read.

    Raises:
        typer.Exit: code 0 always (bash parity: this subcommand never
            fails).
    """
    fmt = "json" if json_out else ("md" if md else "text")
    typer.echo(_render(fmt, resolve_repo_root()))


__all__ = ["app", "MODELS_ROLES", "ModelRoleResolution"]
