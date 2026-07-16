"""``shepherd dash`` — one-glance sprint dashboard (bash: ``cmd_dash.sh``, v6.1.5 #13).

Native port of ``skills/context/scripts/cmd_dash.sh``: a thin, READ-ONLY
COMPOSITION over primitives every other ``shctx`` subcommand already owns —
no new table, no new subsystem, no write path anywhere in this module.
Every section reads from a table/view/file another command (or this port's
sibling modules) already reads:

* ``SPRINT``/``FOCUS`` -- ``schema_versions`` + the ``focus`` table (0013 /
  0017).
* ``GRAPH`` -- ``<workdir>/graph/state.json``, rendered by SHELLING OUT to
  the sibling bash script ``cmd_graph.sh status`` (the Stage-Graph walker
  is not ported to this CLI; this module never reimplements it).
* ``TEAMMATES`` -- ``teammates`` (0007), filtered/computed the same way
  the ``v_teammates_live`` VIEW is, via the already-ported
  :class:`shepherd_cli.models.Teammate` model.
* ``SIGNALS`` -- ``session_signals`` (0020), pending (unconsumed)
  cross-session nudges per recipient.
* ``ESCALATION`` -- ``v_escalations_open`` (0007), via
  :class:`shepherd_cli.models_report.EscalationOpen`.
* ``LOOPS`` -- ``v_loops_active`` (0012).
* ``ADAPT`` -- ``v_sprint_metrics_avg`` (0010) + ``mem_entries`` (kind=
  ``'prior'``).
* ``EVAL`` -- ``eval_runs``/``v_eval_latest`` (0018), only when the table
  exists AND at least one run has been recorded for the active project
  (omit-if-empty).
* ``STALE`` -- ``index_issues``/``index_prs`` refresh staleness.

Built to be looped at a cadence (``/shepherd:loop <interval> shctx dash``);
degrades cleanly on a missing DB, missing graph state, or a missing/
unreadable ``project.json`` — never raises, never exits non-zero except
via the top-level Typer/Click machinery itself (there is no bash-parity
non-zero exit branch in ``cmd_dash.sh`` at all: every guard in this module
mirrors a bash branch that prints a degraded line and moves on, or (the
missing-DB case) prints one line and exits 0).

**No subcommands, no flags, no ``-h``/``--help`` handling.** ``cmd_dash.sh``
never inspects ``$@`` at all -- not even to look for ``-h``/``--help`` --
so ANY arguments given to ``shctx dash`` (including ``-h``, ``--help``,
``--json``, or pure garbage) are silently ignored and the full dashboard
still renders, exit 0. This module mirrors that exactly via
``context_settings={"allow_extra_args": True, "ignore_unknown_options":
True, "help_option_names": []}`` (disabling Click's own ``--help``
interception, matching ``commands/search.py``/``commands/sync.py``) plus a
hidden catch-all ``args`` parameter whose value is never read anywhere in
this module's body.

Raw-SQL notes (hard rule #8), read before touching this module:

* ``SIGNALS`` groups ``session_signals`` by ``recipient`` and orders by
  ``COUNT(*) DESC`` -- a genuine ``GROUP BY`` + aggregate ``ORDER BY``.
  Empirically (verified against a scratch SQLite DB during this port),
  SQLite's tie-break order for equal counts under this exact query shape
  is NOT alphabetical, NOT first-insertion order, and not reproducible by
  re-sorting a Python-side ``Counter`` with any obvious secondary key --
  it is whatever SQLite's own query planner happens to produce for a
  ``GROUP BY`` with no covering index. Reimplementing the aggregation via
  the ORM's ``.annotate()``/``.group_by()`` would risk generating
  subtly different SQL (different column projection order, different
  join/temp-table shape) that could pick a different tie-break. This
  section therefore runs bash's EXACT SQL text through
  ``Tortoise.get_connection("default").execute_query_dict()`` --
  guaranteeing byte-identical results and ordering, since it is the
  identical query against the identical SQLite engine either way.
* ``ADAPT``'s sprint-metrics line involves ``CAST(ROUND(...) AS INTEGER)``
  on two averaged floats. SQLite's ``ROUND()`` and Python's built-in
  ``round()`` use DIFFERENT tie-breaking rules for exact ``.5`` values
  (SQLite rounds half away from zero; Python's ``round()`` rounds half to
  even/"banker's rounding"). Computing the average in Python and rounding
  it there would silently diverge from bash on those tie cases. This
  section instead lets SQLite itself do the rounding, via the same raw-
  connection ``execute_query_dict()`` pattern, with bash's exact
  expression text.
* ``EVAL``'s ``sqlite_master`` existence probe for ``eval_runs`` is the
  canonical raw-SQL case named in hard rule #8 outright. Once past that
  probe, this section also reads ``v_eval_latest`` via the same raw
  connection rather than declaring a fourth mirror model in
  :mod:`shepherd_cli.models_dash` for a single, rarely-exercised,
  omit-if-empty section -- consistent with hard rule #8's "no model
  module for a pure raw-SQL command" allowance, scoped here to just this
  one section rather than the whole module.

Everything else (``SPRINT``'s schema version, ``FOCUS``, ``TEAMMATES``,
``ESCALATION``, ``LOOPS``, ``STALE``, ``ADAPT``'s ``mem_entries`` prior
count/lesson) goes through the ORM, reusing already-mapped models wherever
one exists (per the collision rule) and the two new ones declared in
:mod:`shepherd_cli.models_dash` (``Focus``, ``LoopActive``) otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.models import SchemaVersion, Teammate
from shepherd_cli.models_dash import Focus, LoopActive
from shepherd_cli.models_mem import MemEntry
from shepherd_cli.models_report import EscalationOpen
from shepherd_cli.models_status import IndexIssue, IndexPR
from shepherd_cli.resolution import (
    find_bash_shctx,
    resolve_db_path,
    resolve_repo_root,
    resolve_workdir,
)

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    # cmd_dash.sh never inspects $@ at all -- no -h/--help branch exists to
    # mirror, so Click's own --help interception must be disabled the same
    # way commands/search.py and commands/sync.py disable it, and any
    # tokens given must be swallowed rather than rejected as unknown
    # options (ignore_unknown_options/allow_extra_args below).
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
    help="One-glance sprint dashboard: sprint/focus, graph, teammates, signals, escalations, loops, adapt, eval, stale.",
)

_LOCK_FILENAME = "shepherd.lock"
_PROJECT_JSON_FILENAME = "project.json"
_GRAPH_STATE_RELPATH = os.path.join("graph", "state.json")

#: jq -r's raw-output rendering of JSON `null` -- the literal three-char
#: string bash observes when project.json's "id" key is present-but-null
#: or altogether absent (see :func:`_project_id`).
_JQ_NULL = "null"

#: The middle-dot bash substitutes for a NULL eval_runs.subject_ref
#: (`COALESCE(subject_ref,'·')` in cmd_dash.sh's EVAL query).
_MIDDLE_DOT = "·"


# --------------------------------------------------------------------------
# Small bash-parity helpers.
# --------------------------------------------------------------------------
def _age(then: int, now_s: int) -> str:
    """Render a human age string from an epoch-SECONDS timestamp.

    Bash parity with ``cmd_dash.sh``'s ``_age()`` helper::

        _age() {
          local then="${1:-}" now d
          [[ -z "$then" || "$then" == "0" || "$then" == "-" ]] && { echo "-"; return 0; }
          now="$(shctx_now)"; d=$(( now - then ))
          (( d < 0 )) && d=0
          if   (( d < 90 ));     then echo "${d}s"
          elif (( d < 5400 ));   then echo "$(( d/60 ))m"
          elif (( d < 172800 )); then echo "$(( d/3600 ))h"
          else                        echo "$(( d/86400 ))d"; fi
        }

    Every call site in this module passes ``then`` as an ``int`` (never
    bash's raw empty-string/``"-"`` shapes -- those collapse to the
    ``COALESCE(..., 0)`` default of ``0`` at the query layer already, so
    the ``then == 0`` check below covers bash's whole "-z || == 0 || ==
    -" guard for every real call site).

    Args:
        then: The epoch-SECONDS timestamp to measure age from, or ``0``
            for "never" (bash's ``COALESCE(MAX(...), 0)`` / "no rows"
            shape).
        now_s: The current time in epoch SECONDS, shared across a single
            dashboard render so every age in the output is measured
            against the same instant (bash re-reads ``shctx_now()`` per
            call, but within one invocation those calls are effectively
            simultaneous; sharing one ``now_s`` here is equivalent and
            avoids a theoretical off-by-one-second flake across
            sections).

    Returns:
        ``"-"`` for ``then == 0``; otherwise ``"<n>s"``/``"<n>m"``/
        ``"<n>h"``/``"<n>d"`` per bash's exact thresholds (``< 90`` ->
        seconds, ``< 5400`` -> minutes, ``< 172800`` -> hours, else
        days), with ``d`` clamped to a minimum of ``0`` (a future-dated
        timestamp never renders as negative).
    """
    if then == 0:
        return "-"
    d = now_s - then
    if d < 0:
        d = 0
    if d < 90:
        return f"{d}s"
    if d < 5400:
        return f"{d // 60}m"
    if d < 172800:
        return f"{d // 3600}h"
    return f"{d // 86400}d"


def _current_branch() -> str:
    """Return the current git branch name, bash-parity with ``current_sprint()``.

    Bash: ``git rev-parse --abbrev-ref HEAD 2>/dev/null || printf
    'unknown'``.

    Returns:
        The current branch name (or ``"HEAD"`` in a detached-HEAD state,
        exactly as ``git rev-parse --abbrev-ref`` itself would render
        it), or ``"unknown"`` if git is unavailable, not installed, or
        the command otherwise fails.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    # $(...) strips only trailing newlines, not all trailing whitespace.
    return result.stdout.rstrip("\n")


def _lock_path(workdir: str) -> str:
    """Resolve the live lock file's path.

    Bash parity with ``_lib.sh``'s ``shctx_lock_path``:
    ``$(shctx_artifacts_root)/shepherd.lock``.

    Args:
        workdir: The resolved shepherd work directory
            (:func:`shepherd_cli.resolution.resolve_workdir`'s return
            value).

    Returns:
        The absolute path to ``shepherd.lock`` (need not exist on disk).
    """
    return os.path.join(workdir, _LOCK_FILENAME)


def _project_id(workdir: str) -> str:
    """Resolve the active project id, tolerating every failure bash tolerates.

    Bash parity with ``cmd_dash.sh``'s ``apid="$(shctx_project_id
    2>/dev/null || true)"`` -- ``_lib.sh``'s ``shctx_project_id`` reads
    ``<workdir>/project.json`` via ``jq -r '.id'``, but ``cmd_dash.sh``
    calls it wrapped in ``2>/dev/null || true``, so EVERY failure mode
    (missing file, unparseable JSON, ``jq`` erroring on a non-object
    top-level value) degrades to an empty ``apid`` rather than aborting
    the dashboard -- unlike :mod:`shepherd_cli.commands.query`'s
    ``_read_project_id``, which raises ``typer.Exit`` on those same
    failures (that command's bash twin does NOT suppress
    ``shctx_project_id``'s own error/exit).

    One JSON shape is NOT a failure, though, and must NOT collapse to
    empty: a present, valid, object-shaped ``project.json`` whose ``id``
    key is JSON ``null`` or altogether absent. ``jq -r '.id'`` renders
    that as the literal three-character string ``"null"`` (its raw-
    output text form of JSON ``null``), with exit code 0 -- so
    ``apid="null"`` (non-empty!) in that case, and the ``ADAPT``/``EVAL``
    sections below DO run, just scoped to a ``project_id`` that will
    never match any real row (bash-parity "harmless no-op scoping", not
    a skip).

    Args:
        workdir: The resolved shepherd work directory.

    Returns:
        The project id string; ``"null"`` for the present-but-null/
        absent-key shape described above; or ``""`` for every other
        failure (missing file, unparseable JSON, non-object top-level
        JSON value) -- callers treat ``""`` as "no project id" via a
        plain truthiness check, matching bash's ``[[ -n "$apid" ]]``.
    """
    path = os.path.join(workdir, _PROJECT_JSON_FILENAME)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        # jq -r '.id' errors on a non-object top-level value (e.g. a JSON
        # array or scalar) -- under cmd_dash.sh's `2>/dev/null || true`
        # that is exactly the same degrade-to-empty outcome as a missing
        # file, NOT the present-but-null "null" string case below.
        return ""
    raw_id = data.get("id")
    return _JQ_NULL if raw_id is None else str(raw_id)


# --------------------------------------------------------------------------
# Section renderers. Each prints its own bash-parity line(s) directly
# (rather than returning a value the caller formats) so the print order in
# _dash_async mirrors cmd_dash.sh's top-to-bottom script order exactly.
# --------------------------------------------------------------------------
async def _schema_version() -> int | None:
    """Return ``MAX(version) FROM schema_versions``.

    Returns:
        The highest applied migration version, or None if
        ``schema_versions`` has no rows (bash: ``schema="$(shctx_sql
        'SELECT MAX(version) FROM schema_versions;' 2>/dev/null ||
        echo '?')"`` -- an empty/NULL result and a query error both
        collapse to the same ``"?"`` rendering at the print site, via
        bash's ``${schema:-?}`` default-value expansion).
    """
    row = await SchemaVersion.all().order_by("-version").first()
    return row.version if row is not None else None


async def _focus_objective(branch: str) -> str:
    """Return the current sprint's truncated, newline-stripped objective.

    Bash parity with ``cmd_dash.sh``'s ``FOCUS`` line::

        obj="$(shctx_sql "SELECT COALESCE(substr(replace(replace(objective,
              char(10),' '),char(13),' '),1,76),'') FROM focus WHERE
              sprint='$branch' LIMIT 1;" 2>/dev/null || true)"

    Args:
        branch: The current sprint branch name (:func:`_current_branch`'s
            return value).

    Returns:
        The objective with every ``\\n``/``\\r`` replaced by a space,
        truncated to 76 characters -- or ``""`` if no ``focus`` row
        matches ``branch``, or the matching row's ``objective`` is
        ``NULL`` (bash's ``COALESCE(...,'')`` collapses both to the
        empty string, and the caller's ``[[ -n "$obj" ]]`` then skips
        printing the ``FOCUS`` line entirely for either case).
    """
    row = await Focus.filter(sprint=branch).first()
    if row is None or row.objective is None:
        return ""
    return row.objective.replace("\n", " ").replace("\r", " ")[:76]


def _render_graph_section(workdir: str) -> None:
    """Print the ``GRAPH`` section, delegating to the bash ``cmd_graph.sh status`` sibling.

    Bash::

        gstate="$(shctx_artifacts_root)/graph/state.json"
        if [[ -f "$gstate" ]]; then
          echo "GRAPH"
          bash "$HERE/cmd_graph.sh" status 2>/dev/null | sed 's/^/  /' || echo "  (graph status error)"
        else
          echo "GRAPH       (no stage-graph state — solo / pre-extract)"
        fi

    The pipeline's ``|| echo ...`` fires on the PIPELINE's exit status
    (``set -o pipefail``), which is ``cmd_graph.sh status``'s own exit
    code whenever it is non-zero (``sed`` essentially never fails). That
    exit status is independent of whether ``cmd_graph.sh`` had already
    written partial output to stdout before failing -- any such partial
    output was already piped through ``sed`` (indented, printed) BEFORE
    the ``||`` branch additionally fires, so a failing ``cmd_graph.sh``
    that still printed something can legitimately produce BOTH the
    indented partial output AND the ``"  (graph status error)"`` line.
    This function reproduces that: print every stdout line (2-space
    indented, including blank lines -- ``sed 's/^/  /'`` indents an
    empty line into two bare spaces too, not nothing) unconditionally
    when present, THEN separately check the exit code for the error
    line.

    Args:
        workdir: The resolved shepherd work directory -- used to locate
            ``graph/state.json`` (bash: ``shctx_artifacts_root()`` /
            ``resolve_workdir()``, the exact same resolution this port's
            own ``resolve_workdir()`` performs, so this is passed in
            rather than re-resolved).
    """
    gstate = os.path.join(workdir, _GRAPH_STATE_RELPATH)
    if not os.path.isfile(gstate):
        typer.echo("GRAPH       (no stage-graph state — solo / pre-extract)")
        return

    typer.echo("GRAPH")
    shctx_path = find_bash_shctx()
    if shctx_path is None:
        # The bash shctx tooling itself cannot be located -- equivalent to
        # cmd_graph.sh failing to even start; degrade the same way bash's
        # own pipeline failure branch would.
        typer.echo("  (graph status error)")
        return
    graph_script = os.path.join(os.path.dirname(shctx_path), "cmd_graph.sh")
    try:
        result = subprocess.run(
            ["bash", graph_script, "status"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        typer.echo("  (graph status error)")
        return

    if result.stdout:
        for line in result.stdout.splitlines():
            typer.echo(f"  {line}")
    if result.returncode != 0:
        typer.echo("  (graph status error)")


async def _render_teammates_section(now_ms: int) -> None:
    """Print the ``TEAMMATES`` section: live count + compact roster.

    Bash::

        tline="$(shctx_sql "
          SELECT teammate_name||':'||COALESCE(agent_type,'?')||':'||status||':'||(ms_since_seen/1000)||'s'
          FROM v_teammates_live ORDER BY teammate_name;" 2>/dev/null || true)"

    Reuses :class:`shepherd_cli.models.Teammate` directly (per the
    porting notes' "REUSE Teammate (v_teammates_live)") rather than
    mapping the ``v_teammates_live`` VIEW as a second model: the view is
    exactly ``teammates`` filtered to ``status NOT IN ('crashed',
    'retired')`` plus one computed column, ``ms_since_seen``, that
    :meth:`shepherd_cli.models.Teammate.ms_since_seen` already computes
    identically (``now_ms - last_seen_at``).

    Args:
        now_ms: The current time in epoch MILLISECONDS, shared across
            every roster row so ``ms_since_seen`` is computed against a
            single consistent instant (mirrors
            :meth:`~shepherd_cli.models.Teammate.ms_since_seen`'s own
            docstring guidance, and the view's single
            ``strftime('%s','now')*1000`` call shared across all its
            rows).
    """
    rows = await Teammate.filter(status__not_in=["crashed", "retired"]).order_by("teammate_name")
    if not rows:
        typer.echo("TEAMMATES   none live")
        return
    typer.echo(f"TEAMMATES   {len(rows)} live")
    for row in rows:
        agent_type = row.agent_type if row.agent_type is not None else "?"
        # Integer division truncating toward zero, matching bash's $(( ms/1000 ))
        # (ms_since_seen is never negative in practice, so // == bash trunc here).
        secs = row.ms_since_seen(now_ms) // 1000
        typer.echo(f"              {row.teammate_name}:{agent_type}:{row.status}:{secs}s")


async def _render_signals_section() -> None:
    """Print the ``SIGNALS`` section: pending cross-session nudges per recipient.

    See the module docstring's raw-SQL notes for why this section runs
    bash's exact ``GROUP BY``/``ORDER BY COUNT(*) DESC`` query text
    through a raw connection rather than the ORM.
    """
    conn = Tortoise.get_connection("default")
    rows = await conn.execute_query_dict(
        "SELECT recipient||': '||COUNT(*) AS line FROM session_signals "
        "WHERE consumed_at IS NULL GROUP BY recipient ORDER BY COUNT(*) DESC;"
    )
    if not rows:
        typer.echo("SIGNALS     none pending")
        return
    typer.echo("SIGNALS     pending")
    for row in rows:
        typer.echo(f"              {row['line']}")


async def _render_escalation_section(now_s: int) -> None:
    """Print the ``ESCALATION`` section: open count + oldest age.

    Bash::

        ec="$(shctx_sql 'SELECT COUNT(*) FROM v_escalations_open;' 2>/dev/null || echo 0)"
        if [[ "${ec:-0}" -gt 0 ]]; then
          eo="$(shctx_sql 'SELECT MIN(raised_at) FROM v_escalations_open;' 2>/dev/null || echo 0)"
          printf 'ESCALATION  %s open (oldest %s)\\n' "$ec" "$(_age "$eo")"
        else
          echo "ESCALATION  none open"
        fi

    Uses :class:`shepherd_cli.models_report.EscalationOpen`. ``MIN(
    raised_at)`` is computed by ordering ascending and taking the first
    row's ``raised_at`` -- equivalent for a NOT-NULL column, and
    consistent with that model's own docstring guidance to apply
    ``order_by("raised_at")`` explicitly rather than relying on the
    view's embedded ``ORDER BY``.

    Args:
        now_s: The current time in epoch SECONDS, forwarded to
            :func:`_age`.
    """
    count = await EscalationOpen.all().count()
    if count <= 0:
        typer.echo("ESCALATION  none open")
        return
    oldest = await EscalationOpen.all().order_by("raised_at").first()
    oldest_raised = oldest.raised_at if oldest is not None else 0
    typer.echo(f"ESCALATION  {count} open (oldest {_age(oldest_raised, now_s)})")


async def _render_loops_section() -> None:
    """Print the ``LOOPS`` section: active loops with iteration progress.

    Bash::

        lline="$(shctx_sql "
          SELECT COALESCE(kind,'loop')||' '||COALESCE(latest_iteration,0)||'/'||max_iterations||
                 ' (find='||COALESCE(total_findings,0)||')'
          FROM v_loops_active ORDER BY created_at;" 2>/dev/null || true)"

    Uses :class:`shepherd_cli.models_dash.LoopActive`.
    """
    rows = await LoopActive.all().order_by("created_at")
    if not rows:
        typer.echo("LOOPS       none active")
        return
    typer.echo("LOOPS       active")
    for row in rows:
        kind = row.kind if row.kind is not None else "loop"
        latest = row.latest_iteration if row.latest_iteration is not None else 0
        findings = row.total_findings if row.total_findings is not None else 0
        typer.echo(f"              {kind} {latest}/{row.max_iterations} (find={findings})")


async def _render_adapt_section(project_id: str) -> None:
    """Print the ``ADAPT`` section: measured sprint-metrics averages + priors.

    Bash (the whole block is skipped -- no ``ADAPT`` output at all --
    when ``apid`` is empty)::

        apid="$(shctx_project_id 2>/dev/null || true)"
        if [[ -n "$apid" ]]; then
          arow="$(shctx_sql "SELECT n||'|'||CAST(ROUND(COALESCE(avg_lane_count,0)) AS INTEGER)||'|'||
                 CAST(ROUND(COALESCE(avg_wall_minutes,0)) AS INTEGER)
                 FROM v_sprint_metrics_avg WHERE project_id='$apid';" 2>/dev/null || true)"
          pri="$(shctx_sql "SELECT count(*) FROM mem_entries WHERE project_id='$apid' AND kind='prior';" 2>/dev/null || echo 0)"
          an="${arow%%|*}"
          if [[ -n "$an" && "$an" != "0" ]]; then
            IFS='|' read -r an al aw <<< "$arow"
            printf 'ADAPT       %s sprint(s)  lanes~%s  wall~%sm  priors=%s\\n' "$an" "$al" "$aw" "${pri:-0}"
            lesson="$(shctx_sql "SELECT substr(replace(title,'prior: ',''),1,58) FROM mem_entries
                       WHERE project_id='$apid' AND kind='prior' ORDER BY created_at DESC, id DESC LIMIT 1;" 2>/dev/null || true)"
            [[ -n "$lesson" ]] && printf '              latest: %s\\n' "$lesson"
          elif [[ "${pri:-0}" -gt 0 ]]; then
            printf 'ADAPT       priors=%s (no sprint metrics yet)\\n' "$pri"
          else
            echo "ADAPT       no history yet (first cycle lands at close)"
          fi
        fi

    See the module docstring's raw-SQL notes for why ``arow`` (the
    ``n|lanes|wall`` triple) is fetched via a raw connection instead of
    averaging + rounding in Python (SQLite ``ROUND()`` vs Python
    ``round()`` tie-break divergence on exact ``.5`` values).
    ``mem_entries`` reads use :class:`shepherd_cli.models_mem.MemEntry`
    -- plain string ops (``replace``/slice), with no rounding-parity
    risk.

    Args:
        project_id: :func:`_project_id`'s return value. An empty string
            means the WHOLE section is omitted (bash: the ``if [[ -n
            "$apid" ]]`` guard), not merely its sub-branches.
    """
    if not project_id:
        return

    conn = Tortoise.get_connection("default")
    metrics_rows = await conn.execute_query_dict(
        "SELECT n||'|'||CAST(ROUND(COALESCE(avg_lane_count,0)) AS INTEGER)||'|'||"
        "CAST(ROUND(COALESCE(avg_wall_minutes,0)) AS INTEGER) AS arow "
        "FROM v_sprint_metrics_avg WHERE project_id=?;",
        [project_id],
    )
    arow = metrics_rows[0]["arow"] if metrics_rows else ""
    pri = await MemEntry.filter(project_id=project_id, kind="prior").count()

    # Bash: an="${arow%%|*}" -- everything before the first '|' (empty
    # string if arow itself is empty/unset).
    an = arow.split("|", 1)[0] if arow else ""
    if an and an != "0":
        _an, al, aw = arow.split("|")
        typer.echo(f"ADAPT       {_an} sprint(s)  lanes~{al}  wall~{aw}m  priors={pri}")
        lesson_row = (
            await MemEntry.filter(project_id=project_id, kind="prior").order_by("-created_at", "-id").first()
        )
        if lesson_row is not None:
            lesson = lesson_row.title.replace("prior: ", "")[:58]
            if lesson:
                typer.echo(f"              latest: {lesson}")
    elif pri > 0:
        typer.echo(f"ADAPT       priors={pri} (no sprint metrics yet)")
    else:
        typer.echo("ADAPT       no history yet (first cycle lands at close)")


async def _render_eval_section(project_id: str) -> None:
    """Print the ``EVAL`` section: latest recorded quality verdict, omit-if-empty.

    Bash::

        if [[ -n "${apid:-}" ]] && [[ -n "$(shctx_sql "SELECT 1 FROM sqlite_master
             WHERE type='table' AND name='eval_runs' LIMIT 1;" 2>/dev/null || true)" ]]; then
          erow="$(shctx_sql "SELECT kind||' '||COALESCE(subject_ref,'·')||' '||score||'/'||threshold||' '||
                   CASE passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END
                   FROM v_eval_latest WHERE project_id='$apid' ORDER BY created_at DESC, id DESC LIMIT 1;" 2>/dev/null || true)"
          if [[ -n "$erow" ]]; then
            ecount="$(shctx_sql "SELECT count(*) FROM v_eval_latest WHERE project_id='$apid';" 2>/dev/null || echo 0)"
            printf 'EVAL        latest: %s  (%s scored)\\n' "$erow" "$ecount"
          fi
        fi

    See the module docstring's raw-SQL notes for why this whole section
    -- ``sqlite_master`` probe included -- runs through a raw connection
    rather than declaring a fourth mirror model.

    Args:
        project_id: :func:`_project_id`'s return value. An empty string
            skips this section entirely, same as ``ADAPT``.
    """
    if not project_id:
        return

    conn = Tortoise.get_connection("default")
    exists_rows = await conn.execute_query_dict(
        "SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='eval_runs' LIMIT 1;"
    )
    if not exists_rows:
        return

    erow_rows = await conn.execute_query_dict(
        "SELECT kind||' '||COALESCE(subject_ref,?)||' '||score||'/'||threshold||' '||"
        "CASE passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END AS erow "
        "FROM v_eval_latest WHERE project_id=? ORDER BY created_at DESC, id DESC LIMIT 1;",
        [_MIDDLE_DOT, project_id],
    )
    if not erow_rows:
        return
    erow = erow_rows[0]["erow"]

    count_rows = await conn.execute_query_dict(
        "SELECT COUNT(*) AS c FROM v_eval_latest WHERE project_id=?;",
        [project_id],
    )
    ecount = count_rows[0]["c"] if count_rows else 0
    typer.echo(f"EVAL        latest: {erow}  ({ecount} scored)")


async def _render_stale_section(now_s: int) -> None:
    """Print the ``STALE`` section: GitHub cache freshness (issues + PRs).

    Bash::

        gi="$(shctx_sql 'SELECT COALESCE(MAX(refreshed_at),0) FROM index_issues;' 2>/dev/null || echo 0)"
        gp="$(shctx_sql 'SELECT COALESCE(MAX(refreshed_at),0) FROM index_prs;'    2>/dev/null || echo 0)"
        printf 'STALE       issues=%s  prs=%s\\n' "$(_age "$gi")" "$(_age "$gp")"

    Unconditional -- unlike every other section below ``SPRINT``, there
    is no empty/degraded branch here at all; it always prints, using
    :func:`_age`'s ``then == 0`` -> ``"-"`` handling for the "never
    refreshed" case.

    Args:
        now_s: The current time in epoch SECONDS, forwarded to
            :func:`_age`.
    """
    gi_row = await IndexIssue.all().order_by("-refreshed_at").first()
    gp_row = await IndexPR.all().order_by("-refreshed_at").first()
    gi = gi_row.refreshed_at if gi_row is not None else 0
    gp = gp_row.refreshed_at if gp_row is not None else 0
    typer.echo(f"STALE       issues={_age(gi, now_s)}  prs={_age(gp, now_s)}")


# --------------------------------------------------------------------------
# Top-level driver.
# --------------------------------------------------------------------------
async def _dash_async() -> None:
    """Render the full dashboard, in ``cmd_dash.sh``'s exact top-to-bottom order.

    Section order (bash-parity, NOT alphabetical): header line, then --
    only if a registry DB exists -- ``SPRINT``, ``FOCUS`` (omit-if-
    empty), ``GRAPH``, ``TEAMMATES``, ``SIGNALS``, ``ESCALATION``,
    ``LOOPS``, ``ADAPT`` (omit-if-no-project-id), ``EVAL`` (omit-if-
    empty/no-table/no-project-id), ``STALE``.

    Raises:
        typer.Exit: Code 0, after printing the header line and the "no
            registry DB" message, if no database file exists at the
            resolved path (bash: ``[[ ! -f "$db" ]]`` -> one line ->
            ``exit 0`` -- NOT an error exit, unlike every other ported
            command's missing-DB branch, which exits 1).
    """
    proj = os.path.basename(resolve_repo_root())
    branch = _current_branch()
    ts = time.strftime("%H:%M:%S")
    typer.echo(f"═══ SHEPHERD DASH ═══  {proj}  @{branch}  {ts}")

    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo("  (no registry DB — run 'shctx init'; dashboard limited to git state)")
        raise typer.Exit(code=0)

    workdir = resolve_workdir()
    now_s = int(time.time())
    now_ms = now_s * 1000

    async with db.lifespan(db_path):
        schema_version = await _schema_version()
        schema_str = str(schema_version) if schema_version is not None else "?"
        lockstate = "HELD" if os.path.isfile(_lock_path(workdir)) else "free"
        typer.echo(f"SPRINT      schema=v{schema_str}  lock={lockstate}")

        obj = await _focus_objective(branch)
        if obj:
            typer.echo(f"FOCUS       {obj}…")

        _render_graph_section(workdir)

        await _render_teammates_section(now_ms)
        await _render_signals_section()
        await _render_escalation_section(now_s)
        await _render_loops_section()

        project_id = _project_id(workdir)
        await _render_adapt_section(project_id)
        await _render_eval_section(project_id)

        await _render_stale_section(now_s)


@app.callback(invoke_without_command=True)
def dash(
    args: list[str] = typer.Argument(
        None,
        hidden=True,
        help="Ignored -- cmd_dash.sh never inspects its own arguments either.",
    ),
) -> None:
    """One-glance sprint dashboard: sprint/focus, graph, teammates, signals, escalations, loops, adapt, eval, stale.

    Native port of ``shctx dash`` (``cmd_dash.sh``). Every argument given
    (flags included -- ``-h``, ``--help``, anything) is silently ignored,
    matching bash's script, which never reads ``$@`` at all; the full
    dashboard always renders.

    Args:
        args: Every token given after ``dash`` on the command line, or
            None/empty for a bare ``shepherd dash``. Never read -- kept
            only so Click has somewhere to put stray tokens instead of
            rejecting them.
    """
    asyncio.run(_dash_async())


__all__ = ["app"]
