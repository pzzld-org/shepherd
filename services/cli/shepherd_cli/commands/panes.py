"""``shepherd panes`` — tmux pane observability Typer sub-app.

Native port of ``skills/context/scripts/cmd_panes.sh``: in-session
observability + cleanup over teammate tmux panes. Claude Code owns the
panes in ``teammateMode=tmux|auto`` (it opens one per teammate); this
command does NOT lay them out — it is the OBSERVABILITY + CLEANUP layer
over the ``teammates.tmux_pane_id`` column (written by ``shctx teammate
register --pane``), that column's first and only consumer.

Four verbs, mirroring the bash ``case`` arms exactly:

- ``status [--stale-mins=N]`` (alias ``dash``, hidden) — per-lane
  dashboard: liveness + last heartbeat phase + pane id, from
  ``v_teammates_live`` LEFT JOINed to the latest ``heartbeats`` row per
  teammate, ``ORDER BY v.status, v.teammate_name`` — the IDENTICAL SQL
  text ``cmd_panes.sh`` feeds ``sqlite3``, parameterized on the staleness
  threshold instead of interpolated. Ends with a blank line + the
  ``pane logs: ...`` footer, verbatim.
- ``capture [--lines=N]`` — snapshot each LIVE teammate pane (status in
  ``booting``/``active``/``idle``, pane id present, pane alive per
  ``tmux display``) to ``<ns>/logs/panes/<lane>.log`` via
  ``tmux capture-pane -p -t <pane> -S -<lines>``.
- ``tail <lane> [--lines=N]`` — print the tail of a captured lane log.
  Byte-parity with ``tail -n``: the selected lines are written verbatim
  (a log whose final line lacks a trailing newline stays that way), and
  a negative ``--lines`` behaves like ``tail -n -N`` (same as ``N``).
- ``prune [--closed-only]`` — kill orphan panes: a live pane whose
  teammate is ``crashed``/``retired``, or (without ``--closed-only``)
  whose pane cwd is a ``.worktrees/`` path that no longer exists. Never
  kills a pane whose teammate is live with an intact worktree.

Bash-parity behaviors reproduced deliberately:

- The registry-DB gate runs BEFORE dispatch for EVERY invocation —
  including bare ``shepherd panes``, ``-h``/``--help``, and ``help`` —
  exactly like the script-top ``[[ -f "$DB" ]] || ... exit 1`` guard:
  missing DB prints ``ERR: registry DB not found at <db> (run 'shctx
  init')`` to stderr and exits 1 even on a help request. The fail-soft
  schema self-heal (``shctx_ensure_migrated`` /
  :func:`shepherd_cli.db.ensure_migrated`) also runs before dispatch,
  per the v6.3.3 #200 contract, with the SAME #200 backstop: when the
  heal could not add ``declared_state`` (probed via
  ``pragma_table_info``), ``status`` degrades to a timing-only verdict
  and a literal ``-`` declared column rather than crashing.
- Bare ``shepherd panes`` / ``help`` / ``-h`` / ``--help`` print the
  verbatim ``usage()`` heredoc to STDOUT and exit 0 (Click's own help
  machinery is disabled via ``help_option_names=[]`` so the text matches
  byte-for-byte — the :mod:`shepherd_cli.commands.models` pattern).
- ``capture``/``prune`` degrade cleanly without tmux: missing binary
  prints the bash message (``tmux not available — ...``) and exits 0.
- ``capture`` truncates/creates the lane log file even when
  ``tmux capture-pane`` then FAILS (bash's ``> file`` redirection runs
  before the command) — the failed pane just isn't counted.
- ``status``'s heartbeat join keeps bash's exact edge case: two
  heartbeats tied at ``max(ts)`` for one teammate duplicate that lane's
  row (same SQL text, same behavior).
- Lane names are made filename-safe exactly like ``safe_name()``:
  every character outside ``A-Za-z0-9._-`` becomes ``_``, in both
  ``capture`` (write) and ``tail`` (lookup).

DOCUMENTED DEVIATIONS (additive / equivalent-not-byte-identical only):

1. ``status``'s table renderer reproduces MODERN sqlite3 (>= 3.34)
   ``-header -column`` output — auto-sized columns
   (``max(header, widest value)``), a dashed separator row, a two-space
   gutter, trailing pads kept, and NOTHING printed for an empty result
   set. Ancient sqlite3 builds (< 3.34, fixed 10-char columns with
   truncation) are not reproduced; against a modern sqlite3 the bytes
   match.
2. ``--json`` on the two read verbs (``status``, ``tail``) — additive
   per the port contract; bash has no JSON output here. ``status
   --json`` emits an array of :class:`PaneStatusRow` objects whose
   values mirror the table cells exactly (including the ``-``
   COALESCE placeholders); ``tail --json`` emits ``{"lane", "path",
   "lines"}``.
3. ``--run=<name>`` on ``status``/``capture``/``tail`` — the run-scoped
   artifact shim (same spec as
   :mod:`shepherd_cli.commands.models_graph`.``resolve_run``, duplicated
   here because ported command modules are self-contained): when a run
   is identifiable (``--run`` flag, ``SHEPHERD_RUN`` env, or a one-line
   ``<workdir>/runs/current`` marker), ``capture`` writes NEW logs to
   ``<workdir>/runs/<run>/logs/panes/`` (and ``status``'s footer points
   there); ``tail`` prefers the run-scoped log when that FILE exists and
   ALWAYS falls back to the legacy ``<workdir>/logs/panes/`` path.
   ``prune`` touches no log files, so it takes no ``--run``. With no
   identifiable run, behavior is byte-for-byte bash.
4. Flag/dispatch error TEXT is Click's, not bash's, at the same exit
   code 2: an unknown subcommand (bash: ``unknown subcommand: <x>`` +
   usage), an unknown flag (bash: ``unknown flag: <x>``), and a
   flag-like first ``tail`` token (bash would treat ``--lines=5`` as
   the LANE) all resolve to Click's own UsageError instead — the
   lock.py-documented scope decision. A NON-INTEGER ``--stale-mins``/
   ``--lines`` value also exits 2 (Click) where bash's ``set -u``
   arithmetic abort exits 1; and Click parses flags BEFORE the DB gate,
   where bash gates first.
5. A database error inside ``status`` (e.g. a pre-0007 DB missing
   ``v_teammates_live`` that self-heal could not repair) prints
   ``ERR: <db error>`` to stderr with exit 1 — equivalent to, not
   byte-identical with, the sqlite3 CLI's own stderr text + exit 1
   under ``set -e`` (the adapt.py-documented precedent).
6. ``capture``/``prune`` read teammates rows STRUCTURED (dict rows from
   parameterized SQL) instead of bash's ``IFS='|'`` line parsing, so a
   ``teammate_name`` containing ``|`` cannot corrupt the loop — strictly
   more correct, observably identical for any normal name. Similarly
   :func:`_safe_name` maps one multibyte CHARACTER to one ``_`` where
   ``tr -c`` (byte-oriented) would emit one ``_`` per UTF-8 byte — the
   same filename-safety guarantee.

All SQL is parameterized (``?``) — never string-interpolated (issue
#234 class). ``heartbeats`` has no Tortoise model; per the port
contract's rule 8, reads go through raw parameterized SQL on
``Tortoise.get_connection("default")`` (the mem.py/lock.py/adapt.py
pattern), inside :func:`shepherd_cli.db.lifespan`. No ``cmd_*.sh`` or
``_lib.sh`` is ever shelled out to; only the real ``tmux`` binary is
(exactly where bash did).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys

import typer
from pydantic import BaseModel, ConfigDict
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from shepherd_cli import db
from shepherd_cli.resolution import resolve_db_path, resolve_workdir

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": []},
    help="Tmux pane observability: status/capture/tail/prune over teammates.tmux_pane_id.",
)

#: Verbatim bash-parity usage text — ``usage()`` in ``cmd_panes.sh``.
#: Printed to stdout (bash parity: plain ``cat``, not stderr).
_USAGE = (
    "shctx panes status [--stale-mins=N]   per-lane dashboard (liveness + heartbeat + pane id)\n"
    "shctx panes capture [--lines=N]       snapshot each live teammate pane to <ns>/logs/panes/<lane>.log\n"
    "shctx panes tail <lane> [--lines=N]   print the tail of a captured lane log\n"
    "shctx panes prune [--closed-only]     kill orphan panes (closed teammates; else also worktree-gone)"
)

#: ``status``'s column aliases, in the exact SELECT order — drives both
#: the table render order and the ``--json`` key order.
_STATUS_COLUMNS = ("lane", "role", "status", "declared", "idle_s", "pane", "phase", "verdict")

#: Probe for the ``declared_state`` column (v6.3.3 #200 backstop) —
#: verbatim from ``cmd_panes.sh``'s ``pragma_table_info`` check.
_DECLARED_PROBE_SQL = "SELECT 1 AS present FROM pragma_table_info('teammates') WHERE name='declared_state' LIMIT 1"

#: The ``status`` query when ``declared_state`` exists — the IDENTICAL
#: SQL text ``cmd_panes.sh`` builds (declared branch), with the one
#: dynamic value (the staleness threshold in ms) as a ``?`` bind instead
#: of bash's ``$threshold_ms`` interpolation.
_STATUS_SQL_DECLARED = """\
SELECT v.teammate_name                         AS lane,
       v.agent_type                            AS role,
       v.status                                AS status,
       COALESCE(v.declared_state,'-')          AS declared,
       v.ms_since_seen/1000                    AS idle_s,
       COALESCE(v.tmux_pane_id,'-')            AS pane,
       COALESCE(h.phase,'-')                   AS phase,
       CASE
         WHEN v.declared_state = 'in-progress' THEN 'ok'
         WHEN v.declared_state = 'error'       THEN 'error'
         WHEN v.declared_state = 'complete'    THEN 'complete'
         WHEN v.declared_state = 'idle'        THEN 'idle'
         WHEN v.ms_since_seen > ? AND v.status IN ('booting','active')
              THEN 'presumed-crashed' ELSE 'ok' END AS verdict
FROM v_teammates_live v
LEFT JOIN heartbeats h
  ON h.teammate_id = v.id
 AND h.ts = (SELECT max(ts) FROM heartbeats WHERE teammate_id = v.id)
ORDER BY v.status, v.teammate_name"""

#: The ``status`` query for the #200 backstop (``declared_state`` still
#: missing after self-heal): literal ``-`` declared column, timing-only
#: verdict — verbatim from ``cmd_panes.sh``'s degraded branch.
_STATUS_SQL_TIMING_ONLY = """\
SELECT v.teammate_name                         AS lane,
       v.agent_type                            AS role,
       v.status                                AS status,
       '-'                                     AS declared,
       v.ms_since_seen/1000                    AS idle_s,
       COALESCE(v.tmux_pane_id,'-')            AS pane,
       COALESCE(h.phase,'-')                   AS phase,
       CASE WHEN v.ms_since_seen > ? AND v.status IN ('booting','active')
            THEN 'presumed-crashed' ELSE 'ok' END AS verdict
FROM v_teammates_live v
LEFT JOIN heartbeats h
  ON h.teammate_id = v.id
 AND h.ts = (SELECT max(ts) FROM heartbeats WHERE teammate_id = v.id)
ORDER BY v.status, v.teammate_name"""

#: ``capture``'s candidate rows — verbatim from ``cmd_panes.sh``.
_CAPTURE_ROWS_SQL = (
    "SELECT teammate_name, tmux_pane_id FROM teammates "
    "WHERE tmux_pane_id IS NOT NULL AND status IN ('booting','active','idle')"
)

#: ``prune``'s candidate rows — verbatim from ``cmd_panes.sh``.
_PRUNE_ROWS_SQL = "SELECT teammate_name, tmux_pane_id, status FROM teammates WHERE tmux_pane_id IS NOT NULL"

#: Filename-safe lane label: everything outside this class becomes ``_``
#: (bash: ``tr -c 'A-Za-z0-9._-' '_'``).
_UNSAFE_CHAR_RE = re.compile(r"[^A-Za-z0-9._-]")


class PaneStatusRow(BaseModel):
    """One ``status`` dashboard row (ADDITIVE ``--json`` view).

    Values mirror the plain-text table cells exactly, INCLUDING the
    ``-`` placeholders the SQL COALESCEs in for an undeclared state, a
    missing pane id, and a teammate with no heartbeat yet — the JSON
    view is the table, typed, not a differently-shaped re-query.

    Attributes:
        lane: ``teammates.teammate_name``.
        role: ``teammates.agent_type``.
        status: ``teammates.status`` (live rows only — the
            ``v_teammates_live`` view excludes ``crashed``/``retired``).
        declared: ``declared_state``, or ``"-"`` when undeclared (or when
            the column is missing entirely — the #200 backstop).
        idle_s: Whole seconds since ``last_seen_at`` (SQLite integer
            division of the view's ``ms_since_seen``).
        pane: ``tmux_pane_id``, or ``"-"`` when the teammate has none.
        phase: The latest heartbeat's ``phase``, or ``"-"``.
        verdict: One of ``ok``/``error``/``complete``/``idle``/
            ``presumed-crashed`` (bash CASE parity; declaration wins over
            the timing heuristic, #193/#200).
    """

    model_config = ConfigDict(from_attributes=True)

    lane: str
    role: str
    status: str
    declared: str
    idle_s: int
    pane: str
    phase: str
    verdict: str


# --------------------------------------------------------------------------
# Shared gates + path helpers.
# --------------------------------------------------------------------------
def _require_db() -> str:
    """Bash-parity script-top gate: DB file must exist; then fail-soft self-heal.

    Mirrors ``cmd_panes.sh`` lines 20-24 exactly, INCLUDING running for
    help/usage-only invocations: the DB-not-found error wins over a help
    request, and the #200 schema self-heal runs before every dispatch.

    Returns:
        The resolved database file path (exists).

    Raises:
        typer.Exit: With code 1 (and the verbatim bash stderr message) if
            the registry DB file does not exist.
    """
    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo(f"ERR: registry DB not found at {db_path} (run 'shctx init')", err=True)
        raise typer.Exit(code=1)
    db.ensure_migrated(db_path)  # fail-soft by contract, like shctx_ensure_migrated
    return db_path


def _safe_name(name: str) -> str:
    """Filename-safe lane label (bash ``safe_name``: ``tr -c 'A-Za-z0-9._-' '_'``).

    Args:
        name: A ``teammate_name`` (may contain slashes/spaces/anything).

    Returns:
        ``name`` with every character outside ``A-Za-z0-9._-`` replaced
        by ``_``. One multibyte character maps to ONE underscore (see
        module docstring deviation 6).
    """
    return _UNSAFE_CHAR_RE.sub("_", name)


def resolve_run(explicit: str | None = None) -> str | None:
    """Identify the active run, if any (run-scoped artifact shim).

    Duplicated from :func:`shepherd_cli.commands.models_graph.resolve_run`
    (self-contained command modules per the port contract) with the SAME
    precedence: the explicit ``--run=<name>`` flag value, then the
    ``SHEPHERD_RUN`` environment variable, then a one-line
    ``<workdir>/runs/current`` marker file. All three are ADDITIVE-only
    conventions — bash ``shctx`` has none of them, so their absence
    reproduces bash behavior exactly.

    Args:
        explicit: The ``--run`` flag value, when the caller parsed one.

    Returns:
        The run name, or None when no run is identifiable.
    """
    if explicit:
        return explicit
    env_run = os.environ.get("SHEPHERD_RUN", "")
    if env_run:
        return env_run
    marker = os.path.join(resolve_workdir(), "runs", "current")
    try:
        with open(marker, encoding="utf-8") as fh:
            first_line = fh.readline().strip()
    except OSError:
        return None
    return first_line or None


def _pane_log_dir(run: str | None, *, for_write: bool) -> str:
    """Resolve the pane-log directory, honoring the run-scoped shim.

    Args:
        run: The identified run (from :func:`resolve_run`), or None.
        for_write: True for ``capture`` (and ``status``'s footer, which
            names where NEW captures will land): the run-scoped dir is
            chosen whenever a run is identifiable, even though nothing
            exists there yet. ``tail``'s read path does NOT use this —
            its fallback is per-file (:func:`_tail_log_path`).

    Returns:
        ``<workdir>/runs/<run>/logs/panes`` when ``run`` is set and
        ``for_write`` is True, else the legacy ``<workdir>/logs/panes``
        (bash's ``PANE_LOG_DIR``). Need not exist on disk.
    """
    workdir = resolve_workdir()
    if run and for_write:
        return f"{workdir}/runs/{run}/logs/panes"
    return f"{workdir}/logs/panes"


def _tail_log_path(run: str | None, filename: str) -> str:
    """Resolve one lane log for reading: run-scoped when present, else legacy.

    The "ALWAYS fall back to reading legacy paths" rule, applied
    per-FILE (a run may have captured only some lanes): the run-scoped
    candidate wins only when that exact file exists.

    Args:
        run: The identified run, or None.
        filename: The safe lane filename, e.g. ``"lane-1.log"``.

    Returns:
        The path ``tail`` should read (need not exist — the caller's
        not-found handling covers a lane never captured anywhere).
    """
    workdir = resolve_workdir()
    if run:
        candidate = f"{workdir}/runs/{run}/logs/panes/{filename}"
        if os.path.isfile(candidate):
            return candidate
    return f"{workdir}/logs/panes/{filename}"


# --------------------------------------------------------------------------
# tmux helpers (the ONLY external binary this module shells to, like bash).
# --------------------------------------------------------------------------
def _have_tmux() -> bool:
    """``command -v tmux`` — is a tmux binary on PATH?"""
    return shutil.which("tmux") is not None


def _pane_alive(pane: str) -> bool:
    """Bash ``pane_alive``: ``tmux display -p -t <pane> '#{pane_id}'`` succeeds?

    Args:
        pane: The tmux pane id (e.g. ``"%3"``).

    Returns:
        True when tmux exits 0 for the pane; False on a nonzero exit or
        an exec failure (tmux vanishing between the PATH check and the
        call degrades like a dead pane, never a crash).
    """
    try:
        proc = subprocess.run(
            ["tmux", "display", "-p", "-t", pane, "#{pane_id}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


def _pane_current_path(pane: str) -> str:
    """The pane's ``#{pane_current_path}``, or ``""`` on any failure.

    Bash parity: ``cwd="$(tmux display -p -t "$pane"
    '#{pane_current_path}' 2>/dev/null || true)"`` — a failed lookup
    yields an empty string (which matches no ``.worktrees/`` pattern),
    never an error.

    Args:
        pane: The tmux pane id.

    Returns:
        The pane's current working directory with the trailing newline
        stripped (command-substitution parity), or ``""``.
    """
    try:
        proc = subprocess.run(
            ["tmux", "display", "-p", "-t", pane, "#{pane_current_path}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.rstrip("\n")


# --------------------------------------------------------------------------
# DB fetches (raw parameterized SQL inside the shared lifespan).
# --------------------------------------------------------------------------
async def _fetch_rows(sql: str, params: list[object] | None = None) -> list[dict]:
    """Run one SELECT inside ``db.lifespan`` and return dict rows.

    Args:
        sql: The parameterized SQL text (``?`` placeholders only).
        params: Bind values, or None for a parameterless query.

    Returns:
        The result rows as dicts keyed by the SELECT aliases.
    """
    async with db.lifespan():
        connection = Tortoise.get_connection("default")
        return await connection.execute_query_dict(sql, params or [])


async def _status_rows(threshold_ms: int) -> list[dict]:
    """Fetch the ``status`` dashboard rows, with the #200 degrade probe.

    Args:
        threshold_ms: Staleness threshold in milliseconds
            (``stale_mins * 60 * 1000``), bound as the one ``?`` in the
            verdict CASE.

    Returns:
        Dashboard rows keyed by :data:`_STATUS_COLUMNS`, in bash's exact
        ``ORDER BY v.status, v.teammate_name`` order.

    Raises:
        typer.Exit: With code 1 (``ERR: <db error>`` on stderr) when the
            query itself fails — e.g. a pre-0007 DB missing
            ``v_teammates_live`` that self-heal could not repair (module
            docstring deviation 5).
    """
    async with db.lifespan():
        connection = Tortoise.get_connection("default")
        try:
            probe = await connection.execute_query_dict(_DECLARED_PROBE_SQL)
            has_declared = bool(probe)
        except OperationalError:
            has_declared = False  # bash: 2>/dev/null on the probe -> degraded branch
        sql = _STATUS_SQL_DECLARED if has_declared else _STATUS_SQL_TIMING_ONLY
        try:
            return await connection.execute_query_dict(sql, [threshold_ms])
        except OperationalError as exc:
            typer.echo(f"ERR: {exc}", err=True)
            raise typer.Exit(code=1) from exc


# --------------------------------------------------------------------------
# Rendering.
# --------------------------------------------------------------------------
def _cell_text(value: object) -> str:
    """Render one SQL result cell as sqlite3's column mode would print it."""
    return "" if value is None else str(value)


def _render_column_table(rows: list[dict]) -> str | None:
    """Render rows exactly like modern sqlite3 ``-header -column`` mode.

    Reproduces sqlite3 >= 3.34 column mode byte-for-byte for this
    query's all-text/integer cells: each column is left-justified to
    ``max(len(header), widest value)``, columns join on a two-space
    gutter, a dashed separator row sits under the header, EVERY cell is
    padded (trailing whitespace is kept, matching sqlite3), and an empty
    result set renders as nothing at all (sqlite3 prints no header for
    zero rows — verified against sqlite3 3.45).

    Args:
        rows: Dict rows keyed by :data:`_STATUS_COLUMNS`, already in
            display order.

    Returns:
        The rendered table WITHOUT a trailing newline (callers print via
        ``typer.echo``), or None for an empty result set.
    """
    if not rows:
        return None
    records = [[_cell_text(row[column]) for column in _STATUS_COLUMNS] for row in rows]
    widths = [len(column) for column in _STATUS_COLUMNS]
    for record in records:
        for index, value in enumerate(record):
            widths[index] = max(widths[index], len(value))
    lines = ["  ".join(column.ljust(width) for column, width in zip(_STATUS_COLUMNS, widths, strict=True))]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend(
        "  ".join(value.ljust(width) for value, width in zip(record, widths, strict=True)) for record in records
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Subcommand implementations.
# --------------------------------------------------------------------------
def _status_impl(stale_mins: int, run: str | None, json_out: bool) -> None:
    """``status``/``dash``: print the per-lane dashboard + footer.

    Args:
        stale_mins: ``--stale-mins`` (default 5) — minutes of silence
            before an undeclared ``booting``/``active`` row reads
            ``presumed-crashed``.
        run: ``--run`` (additive shim) — affects only which pane-log
            directory the footer names.
        json_out: ADDITIVE ``--json``: emit a JSON array of
            :class:`PaneStatusRow` instead of the table + footer.
    """
    _require_db()
    threshold_ms = stale_mins * 60 * 1000
    rows = asyncio.run(_status_rows(threshold_ms))
    if json_out:
        views = [PaneStatusRow(**row) for row in rows]
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
        return
    table = _render_column_table(rows)
    if table is not None:
        typer.echo(table)
    typer.echo("")
    log_dir = _pane_log_dir(resolve_run(run), for_write=True)
    typer.echo(f"pane logs: {log_dir}/<lane>.log   (refresh: shctx panes capture; watch: /loop 30s shctx panes status)")


@app.command()
def status(
    stale_mins: int = typer.Option(
        5,
        "--stale-mins",
        help="Minutes of silence before an undeclared booting/active lane reads presumed-crashed.",
    ),
    run: str | None = typer.Option(
        None,
        "--run",
        help="ADDITIVE run-scoped shim: name the run whose pane-log dir the footer points at.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="ADDITIVE (not in cmd_panes.sh): emit a JSON array of PaneStatusRow instead of the table.",
    ),
) -> None:
    """Per-lane dashboard: liveness + last heartbeat phase + pane id.

    Bash parity with ``cmd_panes.sh``'s ``status|dash`` arm, including
    the #200 timing-only degrade when ``declared_state`` is missing.

    Args:
        stale_mins: Staleness threshold in minutes (default 5).
        run: Additive run-scoped shim (footer path only).
        json_out: Additive JSON output.
    """
    _status_impl(stale_mins=stale_mins, run=run, json_out=json_out)


@app.command("dash", hidden=True)
def dash(
    stale_mins: int = typer.Option(
        5,
        "--stale-mins",
        help="Minutes of silence before an undeclared booting/active lane reads presumed-crashed.",
    ),
    run: str | None = typer.Option(
        None,
        "--run",
        help="ADDITIVE run-scoped shim: name the run whose pane-log dir the footer points at.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="ADDITIVE (not in cmd_panes.sh): emit a JSON array of PaneStatusRow instead of the table.",
    ),
) -> None:
    """Alias for ``status`` (bash parity: the ``status|dash)`` case arm).

    Hidden because bash's ``usage()`` does not list it either.

    Args:
        stale_mins: Staleness threshold in minutes (default 5).
        run: Additive run-scoped shim (footer path only).
        json_out: Additive JSON output.
    """
    _status_impl(stale_mins=stale_mins, run=run, json_out=json_out)


@app.command()
def capture(
    lines: int = typer.Option(
        200,
        "--lines",
        help="Scrollback lines to capture per pane (tmux capture-pane -S -N).",
    ),
    run: str | None = typer.Option(
        None,
        "--run",
        help="ADDITIVE run-scoped shim: write logs under <workdir>/runs/<run>/logs/panes/.",
    ),
) -> None:
    """Snapshot each live teammate pane to ``<ns>/logs/panes/<lane>.log``.

    Bash parity with ``cmd_panes.sh``'s ``capture`` arm: candidates are
    teammates with a pane id and status in ``booting``/``active``/
    ``idle``; a dead pane is skipped; a failed ``tmux capture-pane``
    still truncates the lane log (redirection parity) but is not
    counted. Without tmux on PATH, prints the bash degradation message
    and exits 0.

    Args:
        lines: ``--lines`` (default 200).
        run: Additive run-scoped shim for the log directory.
    """
    _require_db()
    if not _have_tmux():
        typer.echo("tmux not available — nothing to capture (teammateMode is in-process?)")
        return
    log_dir = _pane_log_dir(resolve_run(run), for_write=True)
    os.makedirs(log_dir, exist_ok=True)
    rows = asyncio.run(_fetch_rows(_CAPTURE_ROWS_SQL))
    captured = 0
    for row in rows:
        name = row["teammate_name"]
        pane = row["tmux_pane_id"]
        if not pane:
            continue
        if not _pane_alive(pane):
            continue
        log_path = os.path.join(log_dir, f"{_safe_name(name)}.log")
        try:
            # Open first so the file is created/truncated even when tmux
            # then fails — bash's `tmux ... > file || continue` parity.
            with open(log_path, "w", encoding="utf-8") as fh:
                proc = subprocess.run(
                    ["tmux", "capture-pane", "-p", "-t", pane, "-S", f"-{lines}"],
                    stdout=fh,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        except OSError:
            continue
        if proc.returncode != 0:
            continue
        captured += 1
    typer.echo(f"captured {captured} live pane(s) → {log_dir}/")


@app.command()
def tail(
    lane: str | None = typer.Argument(None, metavar="LANE", help="Lane (teammate) name to tail."),
    lines: int = typer.Option(40, "--lines", help="Lines to print from the end of the lane log."),
    run: str | None = typer.Option(
        None,
        "--run",
        help="ADDITIVE run-scoped shim: prefer <workdir>/runs/<run>/logs/panes/ when the lane log exists there.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help='ADDITIVE (not in cmd_panes.sh): emit {"lane", "path", "lines"} instead of raw text.',
    ),
) -> None:
    """Print the tail of a captured lane log.

    Bash parity with ``cmd_panes.sh``'s ``tail`` arm, byte-for-byte with
    ``tail -n`` on the selected lines (a final line without a trailing
    newline stays that way; a negative ``--lines`` behaves like
    ``tail -n -N``, i.e. the same as ``N``; ``--lines=0`` prints
    nothing).

    Args:
        lane: The lane name; required (validated after parsing so bash's
            exact ``usage: shctx panes tail ...`` stderr line is
            reproduced, exit 2).
        lines: ``--lines`` (default 40).
        run: Additive run-scoped shim (per-file read preference with
            legacy fallback).
        json_out: Additive JSON output.

    Raises:
        typer.Exit: Code 2 with the bash usage line when ``lane`` is
            missing; code 1 with the bash ``no capture for ...`` message
            when the lane log does not exist; code 1 with ``ERR: <os
            error>`` if the log exists but cannot be read.
    """
    _require_db()
    if not lane:
        typer.echo("usage: shctx panes tail <lane> [--lines=N]", err=True)
        raise typer.Exit(code=2)
    log_path = _tail_log_path(resolve_run(run), f"{_safe_name(lane)}.log")
    if not os.path.isfile(log_path):
        typer.echo(f"no capture for '{lane}' yet — run: shctx panes capture", err=True)
        raise typer.Exit(code=1)
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError as exc:
        typer.echo(f"ERR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    count = abs(lines)  # tail -n -N == tail -n N; tail -n 0 prints nothing
    if json_out:
        selected = content.splitlines()[-count:] if count > 0 else []
        typer.echo(json.dumps({"lane": lane, "path": log_path, "lines": selected}, indent=2))
        return
    kept = content.splitlines(keepends=True)[-count:] if count > 0 else []
    sys.stdout.write("".join(kept))


@app.command()
def prune(
    closed_only: bool = typer.Option(
        False,
        "--closed-only",
        help="Only kill panes of crashed/retired teammates; skip the worktree-gone heuristic.",
    ),
) -> None:
    """Kill orphan panes — closed teammates, or (default) also worktree-gone ones.

    Bash parity with ``cmd_panes.sh``'s ``prune`` arm: candidates are
    ALL teammates carrying a pane id (any status); an already-dead pane
    is skipped; a ``crashed``/``retired`` teammate's live pane is an
    orphan; otherwise (without ``--closed-only``) a pane whose cwd
    contains ``/.worktrees/`` and no longer exists on disk is an orphan.
    Each successful ``tmux kill-pane`` prints the bash ``killed orphan
    pane ...`` line; a failed kill is silent and uncounted. Never kills
    a live teammate's intact pane. Without tmux on PATH, prints the
    bash degradation message and exits 0.

    Args:
        closed_only: ``--closed-only``.
    """
    _require_db()
    if not _have_tmux():
        typer.echo("tmux not available — no panes to prune")
        return
    rows = asyncio.run(_fetch_rows(_PRUNE_ROWS_SQL))
    killed = 0
    for row in rows:
        name = row["teammate_name"]
        pane = row["tmux_pane_id"]
        status_value = row["status"]
        if not pane:
            continue
        if not _pane_alive(pane):
            continue  # pane already gone — nothing to do
        orphan = status_value in ("crashed", "retired")
        if not orphan and not closed_only:
            # worktree-gone heuristic: pane cwd is a .worktrees/ path that
            # no longer exists. `in` is exactly bash's */.worktrees/* glob
            # (a leading-`.worktrees/` cwd with no slash before it matches
            # NEITHER — the glob requires a literal '/' first).
            cwd = _pane_current_path(pane)
            if "/.worktrees/" in cwd and not os.path.isdir(cwd):
                orphan = True
        if orphan:
            try:
                proc = subprocess.run(["tmux", "kill-pane", "-t", pane], stderr=subprocess.DEVNULL, check=False)
            except OSError:
                continue
            if proc.returncode == 0:
                killed += 1
                typer.echo(f"killed orphan pane {pane} ({name}, status={status_value})")
    typer.echo(f"pruned {killed} orphan pane(s)")


# --------------------------------------------------------------------------
# Usage / help / bare dispatch (bash `""|help|--help|-h) usage;;` parity).
# --------------------------------------------------------------------------
def _help_callback(value: bool) -> None:
    """Eager ``-h``/``--help`` handler: DB gate, then usage, exit 0.

    Bash parity: the script-top DB gate runs BEFORE the ``case`` arm
    that prints usage, so a missing registry DB beats a help request
    (exit 1). With a DB present, prints the verbatim ``usage()`` text to
    stdout and exits 0. Registered as an eager Click option callback
    (the :mod:`shepherd_cli.commands.models` pattern) because this
    sub-app disables Click's own help machinery entirely
    (``help_option_names=[]``) to keep the text byte-for-byte.

    Args:
        value: True when ``-h``/``--help`` was passed.

    Raises:
        typer.Exit: Code 1 (missing DB) or code 0 (usage printed).
    """
    if value:
        _require_db()
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
    """Bare ``shepherd panes``: DB gate, then usage, exit 0.

    Bash parity: an empty ``$1`` falls into the ``""|help|--help|-h)``
    arm — usage on stdout, exit 0 — but only AFTER the script-top DB
    gate (a missing DB exits 1 first).

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only
            when no subcommand was given.
        help_: Unused directly; the eager callback handles ``-h``/
            ``--help`` and exits before this body runs.

    Raises:
        typer.Exit: Code 1 (missing DB) or code 0 (usage printed) when
            invoked without a subcommand.
    """
    if ctx.invoked_subcommand is None:
        _require_db()
        typer.echo(_USAGE)
        raise typer.Exit(code=0)


@app.command("help")
def help_cmd() -> None:
    """Print usage and exit 0 (bash parity: the ``help`` word), after the DB gate.

    Raises:
        typer.Exit: Code 1 (missing DB) or code 0 (usage printed).
    """
    _require_db()
    typer.echo(_USAGE)
    raise typer.Exit(code=0)


__all__ = ["app", "PaneStatusRow"]
