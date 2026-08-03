"""``shepherd adapt`` — SQLite-canonical adaptation loop Typer sub-app.

Native port of ``skills/context/scripts/cmd_adapt.sh`` (v6.0.4 #94/#95;
v6.0.8; v6.0.9 #87; v6.2.0 reflect), the adaptation loop over three
tables: ``sprint_metrics`` (migration ``0010_sprint_metrics.sql``, plus
its ``v_sprint_metrics_avg`` view), ``audit_findings`` (migration
``0007_canonical_state.sql``), and ``mem_entries`` with
``kind='prior'`` (migration ``0011_mem_entries_prior_kind.sql``), plus
the ``compile_runs`` table/``v_compile_runs_sprint`` view (migration
``0014_compile_runs.sql``) for the ``report --compile-telemetry``
subsection.

Five real ``@app.command()``s (``roll``/``reflect``/``priors``/
``report``/``recommend``), exactly like :mod:`shepherd_cli.commands.lock`
— NOT one callback dispatching on a positional string (see lock.py's
module docstring for why that shape cannot parse per-verb options under
Click's Group model). A bare ``shepherd adapt`` prints the bash usage
heredoc verbatim to stdout and exits 0, matching ``cmd_adapt.sh``'s
``""|-h|--help) usage; exit 0`` arm.

Where the bash script's OUTPUT is itself built by SQL (the report table
rows, the lessons lines, the ``json_group_array`` payloads, the
compile-telemetry rollup), this module runs the IDENTICAL SQL text —
parameterized on ``project_id``/``sprint`` instead of interpolated — and
prints the result cells verbatim, so number/text rendering matches the
``sqlite3`` CLI byte-for-byte (both funnel through SQLite's own
``%!.15g`` real-to-text conversion; scalar averages are fetched via
``CAST(... AS TEXT)`` for the same reason). Where bash post-processes
through ``jq`` (the ``--json`` payloads built with ``jq -cn``),
:func:`_jq_number` reproduces jq's number rendering (an integral double
prints bare, ``75`` not ``75.0``) and ``json.dumps(...,
separators=(",", ":"), ensure_ascii=False)`` reproduces ``jq -c``'s
compact, raw-UTF-8 output.

Deliberate, documented deviations from a byte-for-byte bash port:

1. **Project-id resolution** (matches :mod:`shepherd_cli.commands.mem`'s
   documented deviation #1 exactly): ``cmd_adapt.sh`` computes
   ``pid=$(shctx_project_id)`` UNCONDITIONALLY before dispatching to ANY
   subcommand, under ``set -eu -o pipefail`` — so every subcommand fails
   with exit 1 if the project is missing. This module reproduces that
   exact prerequisite-gate ordering (:func:`_require_project_id` runs
   first in every handler, before subcommand-specific validation), but
   resolves the active project via ``SELECT id FROM projects LIMIT 1``
   rather than reading the ``project.json`` sidecar file, because that
   table is what the shared test harness
   (:func:`tests.conftest.insert_project`) and every other ported command
   group scope through. In a healthy project the two always agree (both
   written once, together, by ``shctx init``).
2. **Unknown args / unknown subcommand**: bash prints ``ERROR: unknown
   arg: <a>`` (or ``ERROR: unknown subcommand: adapt <sub>``) to stderr
   and exits 1; Click resolves these to its own UsageError (exit 2)
   before any code of ours runs. Same scope decision lock.py documents.
3. **Conflicting flags**: bash's ``for arg`` loops make the LAST of
   ``--metrics``/``--lessons``/``--all`` (and of ``--json``/``--md``)
   win positionally. Boolean Typer options cannot observe ordering, so
   this module uses a fixed precedence instead: content ``--metrics`` >
   ``--lessons`` > ``--all`` (default), format ``--json`` > ``--md``,
   and for ``report``, ``--trends`` > ``--compile-telemetry`` > plain
   (which IS bash's evaluation order for those two flags).
4. **Per-subcommand ``-h``/``--help``**: bash prints the shared usage
   heredoc and exits 0; Typer prints its own per-command help, also
   exit 0.
5. **Constraint violations** (e.g. ``--size=bogus`` rejected by
   ``sprint_metrics``'s CHECK): bash surfaces ``sqlite3 -bail``'s own
   ``Runtime error ...`` stderr text with exit 1; this module prints
   ``ERROR: <db error>`` to stderr with the same exit 1 — equivalent,
   not byte-identical.

Run-scoped artifact note (``<workdir>/runs/{run}/`` migration): this
command reads/writes ONLY database rows and stdout — it has no
``<workdir>/graph/`` (or any other file) state, so the runs/{run}
compat shim does not apply here.

All SQL is parameterized (``?``) — never string-interpolated (issue
#234 class). ``sprint_metrics``/``audit_findings``/``compile_runs`` have
no Tortoise models; per the port contract's rule 8 all reads/writes go
through raw parameterized SQL on
``Tortoise.get_connection("default")``, exactly
:mod:`shepherd_cli.commands.mem`'s ``_search_entries`` /
:mod:`shepherd_cli.commands.lock`'s ``locks_history`` pattern.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time

import typer
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError, OperationalError

from shepherd_cli import db
from shepherd_cli.models import Project

app = typer.Typer(
    add_completion=False,
    help="Adaptation loop: roll/reflect/priors/report/recommend over sprint_metrics + priors.",
)

#: Verbatim bash usage heredoc (``cmd_adapt.sh``'s ``usage()``), printed
#: to stdout with exit 0 on a bare ``shepherd adapt`` invocation.
_USAGE = """\
shctx adapt <roll|priors|report|recommend> [args]   (v6.0.4 #94/#95; v6.0.8)

  roll --sprint=<branch> [--grade=G --size=XS|S|M|L|XL --lanes=N --waves=N
                          --loc-add=N --loc-del=N --wall-min=R --api=N]
      Record one sprint_metrics row (idempotent) + harvest HIGH/CRITICAL
      audit_findings into mem_entries(kind='prior'). Run at CLOSE-FINALIZE.
      Touches recurring priors' last-seen + prunes stale unpinned priors
      (SHCTX_ADAPT_DECAY_SPRINTS, default 6; pinned priors are never pruned).
      Pass --wall-min (sprint elapsed minutes) + --api: they power the
      cost-rising trend (§VI(c)) and Check 8 sizing — both stay dormant on NULL.

  reflect --sprint=<branch> --note="<lesson>" [--pin]
      Store the conductor's one-line close reflection ("what I'd do differently
      next sprint") as a kind='prior' lesson tagged ["reflection"]. The note is
      latent synthesis; storage/dedup/decay are deterministic. Idempotent per
      sprint. Surfaces in the close report, the dash, session_open, and the next
      sprint's [DB-CONTEXT] brief. Run once per close, after roll.

  priors [--metrics|--lessons|--all] [--json|--md]
      --metrics  measured averages: avg_sprint_minutes, avg_api_per_sprint,
                 avg_lane_count (empty ⇒ caller uses static defaults).
      --lessons  recent kind='prior' lessons (cap 10) for brief injection.
      --all      both (default). --json for tooling, --md for briefs.

  report [--md|--json] [--trends] [--compile-telemetry]
      Materialized sprint-patterns table + averages. --trends emits a
      deterministic TREND ALERT over the last 3 sprints (recurring HIGH/
      CRITICAL concern, grade trending down, cost rising sharply); nothing
      when history is insufficient. Mechanizes adaptation-loop.md §VI.
      --compile-telemetry emits the "## Compile-down telemetry" close-
      report subsection (per-segment faithfulness, peak concurrency, seam
      outcomes, degradation events) from the compile_runs table (migration
      0014). Emits nothing gracefully when no runs recorded. Mirrors the
      "## Cache telemetry" precedent (migration 0006, v_cache_usage).

  recommend [--md|--json]
      Dispatch RECOMMENDATION from measured averages + recurring priors:
      suggested lane count, t-shirt size band, watch-concerns. Empty store
      ⇒ "no history yet, use defaults".

Doctrine: skills/adaptation/SKILL.md (SQLite-canonical),
          skills/adaptation/SKILL.md (harvest→inject)."""

#: Matches ``_num``'s bash regex ``^[0-9]+(\.[0-9]+)?$`` exactly — a
#: non-negative decimal with an optional fractional part (no sign, no
#: leading dot, no exponent).
_NUMERIC_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")

#: Default decay window (sprint closes) when ``SHCTX_ADAPT_DECAY_SPRINTS``
#: is unset or malformed — bash's ``window="${SHCTX_ADAPT_DECAY_SPRINTS:-6}"``.
_DEFAULT_DECAY_SPRINTS = 6


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Print the bash usage heredoc and exit 0 when no subcommand is given.

    Bash parity: ``cmd_adapt.sh``'s ``case "$sub" in ""|-h|--help)
    usage; exit 0`` arm — a bare invocation is a 0-exit usage print to
    STDOUT (unlike mem's usage ERROR to stderr).

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only
            when ``shepherd adapt`` is run with no subcommand.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(_USAGE)


# --------------------------------------------------------------------------
# Small shared helpers (deliberately duplicated across ported modules —
# every command module is self-contained per the port contract).
# --------------------------------------------------------------------------
def _now() -> int:
    """Return the current wall-clock time in epoch seconds.

    Returns:
        The current time as whole seconds since the Unix epoch, matching
        ``_lib.sh``'s ``shctx_now`` (``date +%s``) — the unit
        ``sprint_metrics.created_at`` and ``mem_entries``'s timestamps
        use. Computed ONCE per command invocation (bash computes ``now``
        once at script start), so a roll's metrics row, harvested
        priors, and recurrence touches all share one timestamp.
    """
    return int(time.time())


def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for a new ``mem_entries`` row.

    Bash generates ids via ``_lib.sh``'s ``shctx_uuid7``. This is the
    same independent stdlib generator :mod:`shepherd_cli.commands.mem`
    and :mod:`shepherd_cli.commands.lock` duplicate — spec-compliant and
    timestamp-sortable, which is the only property any caller depends
    on, never an exact bit pattern.

    Returns:
        A lowercase, hyphenated UUIDv7 string.
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


async def _require_project_id() -> str:
    """Resolve the active project id, or exit 1 (bash-parity prerequisite gate).

    See the module docstring's deviation #1: ``cmd_adapt.sh`` computes
    ``pid=$(shctx_project_id)`` before dispatching to ANY subcommand
    under ``set -eu``, so a missing project aborts every subcommand with
    exit 1 BEFORE any subcommand-specific validation (a missing
    ``--sprint`` is never even checked without a project). Every async
    handler calls this FIRST, inside ``db.lifespan()``.

    Returns:
        The active project id.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if no project is
            registered.
    """
    project = await Project.all().first()
    if project is None:
        typer.echo("ERROR: no project registered — run 'shctx init' first", err=True)
        raise typer.Exit(code=1)
    return project.id


async def _fetch(sql: str, params: list[object]) -> list[dict[str, object]]:
    """Run one parameterized SELECT and return its rows as dicts.

    Args:
        sql: The SQL text with ``?`` placeholders.
        params: Positional bind values.

    Returns:
        The result rows, column order preserved.
    """
    connection = Tortoise.get_connection("default")
    return await connection.execute_query_dict(sql, params)


async def _scalar(sql: str, params: list[object]) -> object:
    """Run one parameterized SELECT and return the first row's first column.

    Args:
        sql: The SQL text with ``?`` placeholders.
        params: Positional bind values.

    Returns:
        The first column of the first row, or None when the query
        returns no rows (mirrors bash capturing empty sqlite3 output).
    """
    rows = await _fetch(sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


async def _execute(sql: str, params: list[object]) -> None:
    """Run one parameterized write statement.

    Args:
        sql: The SQL text with ``?`` placeholders.
        params: Positional bind values.
    """
    connection = Tortoise.get_connection("default")
    await connection.execute_query(sql, params)


def _jq_number(text: object) -> int | float:
    """Parse a sqlite-rendered number the way ``jq --argjson`` would re-emit it.

    Bash pipes sqlite's text rendering of a number into ``jq -cn
    --argjson``; jq parses it as a double and prints an integral double
    bare (``75``, never ``75.0``). Feeding sqlite's ``CAST(... AS
    TEXT)`` output through ``float()`` and collapsing integral values to
    ``int`` reproduces that dataflow exactly (including the 15
    significant digits sqlite's ``%!.15g`` truncation keeps — parsing
    the TEXT, not the raw double, is what makes deep decimals match).

    Args:
        text: The sqlite-rendered numeric text (or an already-numeric
            value from a COUNT column).

    Returns:
        An ``int`` when the value is integral, else a ``float`` whose
        ``json.dumps`` rendering (shortest round-trip) matches jq's.
    """
    value = float(str(text))
    if value.is_integer():
        return int(value)
    return value


def _jq_compact(payload: object) -> str:
    """Serialize a payload exactly as ``jq -c`` would print it.

    Args:
        payload: The JSON-serializable payload (dict key order is
            preserved, matching jq's object construction order).

    Returns:
        Compact JSON — no whitespace, raw UTF-8 (jq does not
        ``\\uXXXX``-escape non-ASCII).
    """
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _numeric_or_none(value: str | None, label: str) -> int | float | None:
    """Validate a ``--<label>`` numeric flag exactly like bash's ``_num``.

    Args:
        value: The raw flag value; None or ``""`` means "not given".
        label: The flag label for the error message (bash passes e.g.
            ``loc-add``, matching the flag spelling).

    Returns:
        None for an absent/empty value (bound as SQL NULL); an ``int``
        for an integral value, else a ``float`` — either way SQLite's
        column affinity stores the same value bash's numeric literal
        would.

    Raises:
        typer.Exit: With code 1 and bash's exact stderr message
            (``ERROR: --<label> must be numeric (got '<v>')``) when the
            value does not match ``^[0-9]+(\\.[0-9]+)?$``.
    """
    if value is None or value == "":
        return None
    if not _NUMERIC_RE.match(value):
        typer.echo(f"ERROR: --{label} must be numeric (got '{value}')", err=True)
        raise typer.Exit(code=1)
    if "." in value:
        return float(value)
    return int(value)


def _current_sprint() -> str:
    """Return the current git branch name, or ``"unknown"``.

    Bash parity with ``_lib.sh``'s ``current_sprint``:
    ``git rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown'``
    — run in the process's cwd; any git failure (not a repo, unborn
    branch, git absent) falls back to the literal ``unknown``.

    Returns:
        The branch name (whatever git printed, newline-stripped), or
        ``"unknown"``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


# --------------------------------------------------------------------------
# roll — write metrics row + harvest priors
# --------------------------------------------------------------------------
async def _decay_priors(project_id: str, now: int) -> int:
    """Prune unpinned ``prior`` rows un-refreshed across the decay window.

    Bash parity with ``cmd_adapt.sh``'s ``_decay_priors``: the window is
    ``SHCTX_ADAPT_DECAY_SPRINTS`` sprint CLOSES (default 6; a malformed
    value falls back to 6), gap-based on the close cadence rather than
    wall-clock — a prior is stale once MORE than ``window`` recorded
    closes carry a ``created_at`` strictly newer than the prior's
    ``updated_at``. Collision-proof against same-second rolls (a prior
    refreshed THIS close has ``updated_at = now``, so zero closes are
    newer). Pinned priors are NEVER pruned. Graceful when fewer than 2
    closes are recorded (no cadence to measure): prunes nothing,
    returns 0.

    Args:
        project_id: The scoping project id.
        now: Unused by the SQL itself; accepted for signature symmetry
            with the caller's single-timestamp discipline.

    Returns:
        The number of priors pruned (counted with the same predicate
        immediately before the DELETE, matching bash's two-statement
        count-then-delete).
    """
    del now  # decay is cadence-based, not clock-based
    raw_window = os.environ.get("SHCTX_ADAPT_DECAY_SPRINTS", "")
    window = int(raw_window) if re.fullmatch(r"[0-9]+", raw_window) else _DEFAULT_DECAY_SPRINTS

    nsprints = await _scalar(
        "SELECT count(*) FROM sprint_metrics WHERE project_id=?;", [project_id]
    )
    if int(nsprints or 0) < 2:
        return 0

    count = await _scalar(
        """SELECT count(*) FROM mem_entries m
           WHERE m.project_id=? AND m.kind='prior' AND m.pinned=0
             AND (SELECT count(*) FROM sprint_metrics s
                  WHERE s.project_id=? AND s.created_at > m.updated_at) > ?;""",
        [project_id, project_id, window],
    )
    await _execute(
        """DELETE FROM mem_entries
           WHERE project_id=? AND kind='prior' AND pinned=0
             AND (SELECT count(*) FROM sprint_metrics s
                  WHERE s.project_id=? AND s.created_at > mem_entries.updated_at) > ?;""",
        [project_id, project_id, window],
    )
    return int(count or 0)


async def _roll_async(
    sprint: str | None,
    grade: str | None,
    size: str | None,
    lanes: str | None,
    waves: str | None,
    loc_add: str | None,
    loc_del: str | None,
    wall_min: str | None,
    api: str | None,
) -> None:
    """Record one ``sprint_metrics`` row + harvest HIGH/CRITICAL findings.

    Bash parity with ``_cmd_roll``: (1) an idempotent
    ``INSERT OR REPLACE`` keyed on ``UNIQUE(project_id, sprint_branch)``
    with a compact ``{"high":H,"critical":C}`` findings summary; (2)
    every HIGH/CRITICAL ``audit_findings`` row for the sprint becomes a
    ``mem_entries(kind='prior')`` lesson deduped by title — a recurrence
    refreshes the existing prior's ``updated_at`` (last-seen) instead of
    re-inserting; (3) stale unpinned priors are pruned via
    :func:`_decay_priors`; (4) the one-line summary is printed.

    Args:
        sprint: ``--sprint`` (required).
        grade: ``--grade`` (empty/absent -> NULL).
        size: ``--size`` (empty/absent -> NULL; an invalid value is
            rejected by the table CHECK at insert time, like bash).
        lanes: ``--lanes`` (numeric or absent).
        waves: ``--waves`` (numeric or absent).
        loc_add: ``--loc-add`` (numeric or absent).
        loc_del: ``--loc-del`` (numeric or absent).
        wall_min: ``--wall-min`` (numeric or absent — explicit-only; a
            NULL keeps the cost trend dormant rather than guessing).
        api: ``--api`` (numeric or absent).

    Raises:
        typer.Exit: Code 1 if no project is registered, ``--sprint`` is
            missing, a numeric flag is malformed, or the DB rejects the
            row (CHECK constraint — see module deviation #5).
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not sprint:
            typer.echo("ERROR: adapt roll requires --sprint=<branch>", err=True)
            raise typer.Exit(code=1)

        now = _now()
        grade_value = grade if grade else None
        size_value = size if size else None
        lanes_value = _numeric_or_none(lanes, "lanes")
        waves_value = _numeric_or_none(waves, "waves")
        loc_add_value = _numeric_or_none(loc_add, "loc-add")
        loc_del_value = _numeric_or_none(loc_del, "loc-del")
        wall_value = _numeric_or_none(wall_min, "wall-min")
        api_value = _numeric_or_none(api, "api")

        high = await _scalar(
            "SELECT count(*) FROM audit_findings WHERE project_id=? AND sprint_branch=? AND severity='high';",
            [project_id, sprint],
        )
        critical = await _scalar(
            "SELECT count(*) FROM audit_findings WHERE project_id=? AND sprint_branch=? AND severity='critical';",
            [project_id, sprint],
        )
        findings_json = _jq_compact({"high": int(high or 0), "critical": int(critical or 0)})

        try:
            await _execute(
                """INSERT OR REPLACE INTO sprint_metrics
                     (project_id, sprint_branch, grade, sprint_size, lane_count, wave_count,
                      loc_add, loc_del, wall_minutes, api_calls, findings_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                [
                    project_id, sprint, grade_value, size_value, lanes_value, waves_value,
                    loc_add_value, loc_del_value, wall_value, api_value, findings_json, now,
                ],
            )
        except (IntegrityError, OperationalError) as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        # Harvest HIGH/CRITICAL findings -> mem_entries(kind='prior'),
        # deduped by title. The gist transform (substr 240 + newline
        # collapse) runs in SQL, verbatim from bash, for identical text.
        findings = await _fetch(
            """SELECT id, concern, severity,
                      replace(replace(substr(finding,1,240),char(10),' '),char(13),' ') AS gist
               FROM audit_findings
               WHERE project_id=? AND sprint_branch=?
                 AND severity IN ('high','critical') ORDER BY id;""",
            [project_id, sprint],
        )
        harvested = 0
        for finding in findings:
            concern = str(finding["concern"])
            title = f"prior: {concern}"
            dup = await _scalar(
                "SELECT 1 FROM mem_entries WHERE project_id=? AND kind='prior' AND title=? LIMIT 1;",
                [project_id, title],
            )
            if dup is not None:
                # Recurrence: refresh last-seen so decay never prunes a
                # still-recurring lesson; skip the re-insert.
                await _execute(
                    "UPDATE mem_entries SET updated_at=? WHERE project_id=? AND kind='prior' AND title=?;",
                    [now, project_id, title],
                )
                continue
            body = f"[{finding['severity']}] sprint {sprint}: {finding['gist']}"
            tags = _jq_compact([concern])
            await _execute(
                """INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
                   VALUES (?, ?, 'prior', ?, ?, ?, 0, ?, ?);""",
                [_uuid7(), project_id, title, body, tags, now, now],
            )
            harvested += 1

        pruned = await _decay_priors(project_id, now)

    typer.echo(
        f"adapt roll: sprint_metrics row ({sprint}) + {harvested} prior(s) harvested + {pruned} stale prior(s) pruned"
    )


@app.command()
def roll(
    sprint: str | None = typer.Option(None, "--sprint", help="Sprint branch (required)."),
    grade: str | None = typer.Option(None, "--grade", help="Sprint grade (e.g. A/B/C)."),
    size: str | None = typer.Option(None, "--size", help="T-shirt size: XS|S|M|L|XL."),
    lanes: str | None = typer.Option(None, "--lanes", help="Lane count (numeric)."),
    waves: str | None = typer.Option(None, "--waves", help="Wave count (numeric)."),
    loc_add: str | None = typer.Option(None, "--loc-add", help="Lines added (numeric)."),
    loc_del: str | None = typer.Option(None, "--loc-del", help="Lines deleted (numeric)."),
    wall_min: str | None = typer.Option(None, "--wall-min", help="Sprint elapsed minutes (numeric; explicit-only)."),
    api: str | None = typer.Option(None, "--api", help="API call count (numeric)."),
) -> None:
    """Write one sprint_metrics row + harvest HIGH/CRITICAL findings into priors.

    Bash parity with ``cmd_adapt.sh``'s ``roll`` arm. Run at
    CLOSE-FINALIZE; idempotent on ``UNIQUE(project_id, sprint_branch)``.
    """
    asyncio.run(
        _roll_async(
            sprint=sprint, grade=grade, size=size, lanes=lanes, waves=waves,
            loc_add=loc_add, loc_del=loc_del, wall_min=wall_min, api=api,
        )
    )


# --------------------------------------------------------------------------
# reflect — store the conductor's one-line close reflection
# --------------------------------------------------------------------------
async def _reflect_async(sprint: str | None, note: str | None, pin: bool) -> None:
    """Store/update the sprint's close reflection as a tagged prior.

    Bash parity with ``_cmd_reflect``: title-keyed idempotence per
    sprint (``prior: reflection (<sprint>)``); the body collapses
    newlines/carriage returns to spaces (bash ``tr '\\n\\r' '  '``); an
    update preserves an existing pin via ``pinned=MAX(pinned, <pin>)``
    so re-running a close WITHOUT ``--pin`` never silently unpins.

    Args:
        sprint: ``--sprint`` (required).
        note: ``--note`` (required).
        pin: ``--pin``.

    Raises:
        typer.Exit: Code 1 if no project is registered, or ``--sprint``
            / ``--note`` is missing (bash's exact stderr messages, in
            bash's exact order — sprint checked first).
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not sprint:
            typer.echo("ERROR: adapt reflect requires --sprint=<branch>", err=True)
            raise typer.Exit(code=1)
        if not note:
            typer.echo("ERROR: adapt reflect requires --note=<lesson>", err=True)
            raise typer.Exit(code=1)

        now = _now()
        title = f"prior: reflection ({sprint})"
        note_one_line = note.replace("\n", " ").replace("\r", " ")
        body = f"[reflection] sprint {sprint}: {note_one_line}"
        tags = _jq_compact(["reflection"])
        pin_value = 1 if pin else 0

        dup = await _scalar(
            "SELECT id FROM mem_entries WHERE project_id=? AND kind='prior' AND title=? LIMIT 1;",
            [project_id, title],
        )
        if dup is not None:
            await _execute(
                "UPDATE mem_entries SET body=?, pinned=MAX(pinned,?), updated_at=? WHERE id=?;",
                [body, pin_value, now, dup],
            )
            message = f"adapt reflect: updated reflection for {sprint}"
        else:
            entry_id = _uuid7()
            await _execute(
                """INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
                   VALUES (?, ?, 'prior', ?, ?, ?, ?, ?, ?);""",
                [entry_id, project_id, title, body, tags, pin_value, now, now],
            )
            message = f"adapt reflect: stored reflection for {sprint} (id {entry_id})"
    typer.echo(message)


@app.command()
def reflect(
    sprint: str | None = typer.Option(None, "--sprint", help="Sprint branch (required)."),
    note: str | None = typer.Option(None, "--note", help="One-line close reflection (required)."),
    pin: bool = typer.Option(False, "--pin", help="Pin the reflection (never decays)."),
) -> None:
    """Store a one-line close reflection as a kind='prior' lesson tagged ["reflection"].

    Bash parity with ``cmd_adapt.sh``'s ``reflect`` arm. Idempotent per
    sprint; a re-run updates in place and preserves an existing pin.
    """
    asyncio.run(_reflect_async(sprint=sprint, note=note, pin=pin))


# --------------------------------------------------------------------------
# priors — read metrics averages + lesson priors
# --------------------------------------------------------------------------
async def _metrics_row(project_id: str) -> dict[str, object] | None:
    """Fetch the project's ``v_sprint_metrics_avg`` row, sqlite-text-rendered.

    The four averages are fetched BOTH as ``CAST(... AS TEXT)`` (SQLite's
    own ``%!.15g`` rendering — what bash captured from the sqlite3 CLI
    and printed verbatim in text/md formats) and derived numerically
    from those texts for the jq-shaped JSON (see :func:`_jq_number`).

    Args:
        project_id: The scoping project id.

    Returns:
        The row dict (keys ``n``/``awm``/``aac``/``alc``/``ald`` as
        text), or None when there is no row or ``n`` is 0 (bash's two
        graceful-empty guards).
    """
    rows = await _fetch(
        """SELECT n,
                  CAST(COALESCE(avg_wall_minutes,0) AS TEXT) AS awm,
                  CAST(COALESCE(avg_api_calls,0)    AS TEXT) AS aac,
                  CAST(COALESCE(avg_lane_count,0)   AS TEXT) AS alc,
                  CAST(COALESCE(avg_loc_delta,0)    AS TEXT) AS ald
           FROM v_sprint_metrics_avg WHERE project_id=?;""",
        [project_id],
    )
    if not rows:
        return None
    row = rows[0]
    if not row["n"]:
        return None
    return row


async def _emit_metrics(project_id: str, fmt: str) -> str | None:
    """Render the metrics averages, or None when the store is empty.

    Bash parity with ``_emit_metrics``: no row / ``n=0`` emits nothing
    (the caller falls back to static defaults / omits the section).

    Args:
        project_id: The scoping project id.
        fmt: ``"json"``, ``"md"``, or anything else for the key=value
            text default.

    Returns:
        The rendered block (no trailing newline), or None to emit
        nothing.
    """
    row = await _metrics_row(project_id)
    if row is None:
        return None
    n = int(str(row["n"]))
    awm, aac, alc, ald = (str(row["awm"]), str(row["aac"]), str(row["alc"]), str(row["ald"]))
    if fmt == "json":
        return _jq_compact(
            {
                "n": n,
                "avg_sprint_minutes": _jq_number(awm),
                "avg_api_per_sprint": _jq_number(aac),
                "avg_lane_count": _jq_number(alc),
                "avg_loc_delta": _jq_number(ald),
            }
        )
    if fmt == "md":
        return (
            f"### Dispatch priors — measured ({n} prior sprint(s))\n"
            f"- avg_sprint_minutes: {awm}\n- avg_api_per_sprint: {aac}\n- avg_lane_count: {alc}"
        )
    return (
        f"n={n}\navg_sprint_minutes={awm}\navg_api_per_sprint={aac}\n"
        f"avg_lane_count={alc}\navg_loc_delta={ald}"
    )


#: The lessons feed's JSON payload — verbatim from ``_emit_lessons``'s
#: ``json`` arm (parameterized on project_id); the sqlite ``json_group_array``
#: cell is printed as-is, so its compact rendering matches bash exactly.
_LESSONS_JSON_SQL = """\
SELECT json_group_array(json_object('id',id,'title',title,'body',body,'tags',json(tags)))
FROM (SELECT id,title,body,tags FROM mem_entries
      WHERE project_id=? AND kind='prior'
      ORDER BY created_at DESC, id DESC LIMIT 10);"""

#: Line-shaped lessons feeds — verbatim from ``_emit_lessons``'s ``md``
#: and text arms; each row IS one already-rendered output line.
_LESSONS_MD_SQL = """\
SELECT '- **' || title || '** _(id: ' || id || ')_ — ' || body AS line
FROM mem_entries WHERE project_id=? AND kind='prior'
ORDER BY created_at DESC, id DESC LIMIT 10;"""

_LESSONS_TEXT_SQL = """\
SELECT '[' || id || '] ' || title || ' — ' || body AS line
FROM mem_entries WHERE project_id=? AND kind='prior'
ORDER BY created_at DESC, id DESC LIMIT 10;"""


async def _emit_lessons(project_id: str, fmt: str) -> str | None:
    """Render the recent lesson priors (cap 10), or None when none exist.

    Bash parity with ``_emit_lessons``: omit-if-empty.

    Args:
        project_id: The scoping project id.
        fmt: ``"json"``, ``"md"``, or anything else for the text default.

    Returns:
        The rendered block (no trailing newline), or None to emit
        nothing.
    """
    any_prior = await _scalar(
        "SELECT 1 FROM mem_entries WHERE project_id=? AND kind='prior' LIMIT 1;", [project_id]
    )
    if any_prior is None:
        return None
    if fmt == "json":
        cell = await _scalar(_LESSONS_JSON_SQL, [project_id])
        return str(cell)
    if fmt == "md":
        rows = await _fetch(_LESSONS_MD_SQL, [project_id])
        return "\n".join(["### Priors / lessons carried forward", *(str(r["line"]) for r in rows)])
    rows = await _fetch(_LESSONS_TEXT_SQL, [project_id])
    return "\n".join(str(r["line"]) for r in rows)


async def _priors_async(content: str, fmt: str) -> None:
    """Print the requested priors view.

    Args:
        content: ``"metrics"``, ``"lessons"``, or ``"all"``.
        fmt: ``"json"``, ``"md"``, or ``"text"``.

    Raises:
        typer.Exit: Code 1 if no project is registered.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if content == "metrics":
            block = await _emit_metrics(project_id, fmt)
            if block is not None:
                typer.echo(block)
            return
        if content == "lessons":
            block = await _emit_lessons(project_id, fmt)
            if block is not None:
                typer.echo(block)
            return
        # all
        if fmt == "json":
            metrics_json = await _emit_metrics(project_id, "json")
            lessons_json = await _emit_lessons(project_id, "json")
            payload = {
                "metrics": json.loads(metrics_json) if metrics_json is not None else None,
                "lessons": json.loads(lessons_json) if lessons_json is not None else [],
            }
            typer.echo(_jq_compact(payload))
            return
        for block in (
            await _emit_metrics(project_id, fmt),
            await _emit_lessons(project_id, fmt),
        ):
            if block is not None:
                typer.echo(block)


@app.command()
def priors(
    metrics: bool = typer.Option(False, "--metrics", help="Measured averages only (spawn Check 8 feed)."),
    lessons: bool = typer.Option(False, "--lessons", help="Recent kind='prior' lessons only (cap 10)."),
    all_content: bool = typer.Option(False, "--all", help="Both (the default)."),
    json_out: bool = typer.Option(False, "--json", help="JSON output for tooling."),
    md: bool = typer.Option(False, "--md", help="Markdown output for briefs."),
) -> None:
    """Read priors at sprint open: measured averages + lesson priors.

    Bash parity with ``cmd_adapt.sh``'s ``priors`` arm, graceful when
    empty (emits nothing so the caller falls back to static defaults).
    Conflicting content/format flags follow the fixed precedence
    documented in the module docstring (deviation #3), not bash's
    positional last-wins.
    """
    del all_content  # --all is the default; only kept for CLI parity.
    content = "metrics" if metrics else ("lessons" if lessons else "all")
    fmt = "json" if json_out else ("md" if md else "text")
    asyncio.run(_priors_async(content=content, fmt=fmt))


# --------------------------------------------------------------------------
# report — materialized sprint-patterns view (+ --trends / --compile-telemetry)
# --------------------------------------------------------------------------
#: Verbatim from ``_cmd_report``'s json arm (parameterized): the cell IS
#: the printed output line.
_REPORT_JSON_SQL = """\
SELECT json_group_array(json_object(
  'sprint',sprint_branch,'grade',grade,'size',sprint_size,
  'lanes',lane_count,'waves',wave_count,'loc_add',loc_add,
  'loc_del',loc_del,'wall_minutes',wall_minutes,'api_calls',api_calls,
  'findings',json(findings_json),'created_at',created_at))
FROM (SELECT * FROM sprint_metrics WHERE project_id=?
      ORDER BY created_at DESC, id DESC LIMIT 20);"""

#: Verbatim from ``_cmd_report``'s md arm: each row IS one rendered
#: markdown table line.
_REPORT_MD_ROWS_SQL = """\
SELECT '| ' || sprint_branch
    || ' | ' || COALESCE(grade,'·')
    || ' | ' || COALESCE(sprint_size,'·')
    || ' | ' || COALESCE(lane_count,'·')
    || ' | ' || COALESCE(wave_count,'·')
    || ' | ' || COALESCE(CAST(wall_minutes AS INTEGER),'·')
    || ' | ' || COALESCE(api_calls,'·')
    || ' | ' || COALESCE(findings_json,'·') || ' |' AS line
FROM sprint_metrics WHERE project_id=?
ORDER BY created_at DESC, id DESC LIMIT 20;"""

#: The reusable last-3-closes CTE from ``_emit_trends`` (parameterized on
#: project_id), prefixed to each of the three signal queries below.
_TRENDS_LAST3_CTE = """\
WITH last3 AS (
  SELECT sprint_branch, grade, wall_minutes, api_calls, created_at, id,
         ROW_NUMBER() OVER (ORDER BY created_at DESC, id DESC) AS rn
  FROM sprint_metrics WHERE project_id=?
  ORDER BY created_at DESC, id DESC LIMIT 3)"""

_TRENDS_CONCERN_SQL = _TRENDS_LAST3_CTE + """
SELECT af.concern FROM audit_findings af
WHERE af.project_id=? AND af.severity IN ('high','critical')
  AND af.sprint_branch IN (SELECT sprint_branch FROM last3)
GROUP BY af.concern
HAVING COUNT(DISTINCT af.sprint_branch) = 3
ORDER BY af.concern LIMIT 1;"""

_TRENDS_GRADE_SQL = _TRENDS_LAST3_CTE + """,
g AS (SELECT rn,
        CASE substr(UPPER(grade),1,1)
          WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2
          WHEN 'D' THEN 3 WHEN 'E' THEN 4 WHEN 'F' THEN 5 END AS gr
      FROM last3)
SELECT CASE WHEN
  (SELECT gr FROM g WHERE rn=1) > (SELECT gr FROM g WHERE rn=2)
  AND (SELECT gr FROM g WHERE rn=2) > (SELECT gr FROM g WHERE rn=3)
  AND (SELECT count(*) FROM g WHERE gr IS NOT NULL) = 3
THEN 1 ELSE 0 END AS fired;"""

_TRENDS_COST_SQL = _TRENDS_LAST3_CTE + """
SELECT CASE WHEN
  ((SELECT wall_minutes FROM last3 WHERE rn=1) >=
     1.5 * (SELECT wall_minutes FROM last3 WHERE rn=3)
   AND (SELECT wall_minutes FROM last3 WHERE rn=3) > 0)
  OR
  ((SELECT api_calls FROM last3 WHERE rn=1) >=
     1.5 * (SELECT api_calls FROM last3 WHERE rn=3)
   AND (SELECT api_calls FROM last3 WHERE rn=3) > 0)
THEN 1 ELSE 0 END AS fired;"""


async def _emit_trends(project_id: str, fmt: str) -> None:
    """Emit the deterministic TREND ALERT over the last 3 closes, if any fires.

    Bash parity with ``_emit_trends`` (mechanizes adaptation-loop.md
    §VI): (a) a HIGH/CRITICAL concern recurring across ALL of the last 3
    sprints, (b) grade trending strictly worse, (c) cost rising sharply
    (newest wall/api >= 1.5x the oldest). Fewer than 3 recorded closes,
    or no signal firing, emits nothing (graceful) — and NEVER exits
    non-zero (the bash trailing-``&&``-under-``set -e`` regression this
    port keeps structurally impossible).

    Args:
        project_id: The scoping project id.
        fmt: ``"json"`` or ``"md"``.
    """
    n3 = await _scalar(
        """SELECT count(*) FROM (SELECT 1 FROM sprint_metrics
           WHERE project_id=? ORDER BY created_at DESC, id DESC LIMIT 3);""",
        [project_id],
    )
    if int(n3 or 0) < 3:
        return

    concern = await _scalar(_TRENDS_CONCERN_SQL, [project_id, project_id])
    grade_down = await _scalar(_TRENDS_GRADE_SQL, [project_id])
    cost_up = await _scalar(_TRENDS_COST_SQL, [project_id])
    concern_text = "" if concern is None else str(concern)
    grade_fired = str(grade_down) == "1"
    cost_fired = str(cost_up) == "1"

    if not concern_text and not grade_fired and not cost_fired:
        return

    if fmt == "json":
        typer.echo(
            _jq_compact(
                {
                    "trend_alert": True,
                    "recurring_concern": bool(concern_text),
                    "concern": concern_text,
                    "grade_trending_down": grade_fired,
                    "cost_rising": cost_fired,
                }
            )
        )
        return

    typer.echo("### TREND ALERT — last 3 sprints (`shctx adapt report --trends`)")
    typer.echo("")
    if concern_text:
        typer.echo(
            f"- **Recurring concern:** `{concern_text}` raised HIGH/CRITICAL in all of the last 3 sprints — give it a dedicated lane / acceptance criterion."
        )
    if grade_fired:
        typer.echo(
            "- **Grade trending DOWN** across the last 3 sprints — scope may be outrunning capacity; size the next sprint smaller."
        )
    if cost_fired:
        typer.echo(
            "- **Cost rising sharply** (newest ≥ 1.5× oldest wall/api over 3 sprints) — review lane fan-out and wave count."
        )


#: Verbatim from ``_emit_compile_telemetry``'s json arm (parameterized).
_COMPILE_JSON_SQL = """\
SELECT json_group_array(json_object(
  'segment',               segment,
  'runs',                  runs,
  'node_count',            node_count,
  'max_agents',            max_agents,
  'avg_peak_concurrency',  ROUND(avg_peak_concurrency,1),
  'concurrency_ceiling',   concurrency_ceiling,
  'faithfulness_pass_rate',ROUND(faithfulness_pass_rate,2),
  'soundness_failures',    soundness_failures,
  'completeness_failures', completeness_failures,
  'determinism_failures',  determinism_failures,
  'seam_exports_present',  seam_exports_present,
  'seam_exports_consumed', seam_exports_consumed,
  'degradation_events',    degradation_events,
  'recovered_events',      recovered_events,
  'degradation_causes',    degradation_causes
))
FROM v_compile_runs_sprint
WHERE project_id=? AND sprint=?
ORDER BY segment;"""

#: Verbatim from ``_emit_compile_telemetry``'s md arm: each row IS one
#: rendered markdown table line.
_COMPILE_MD_ROWS_SQL = """\
SELECT
  '| ' || segment
|| ' | ' || runs
|| ' | ' || COALESCE(node_count,'·')
|| ' | ' || COALESCE(max_agents,'·')
|| ' | ' || COALESCE(CAST(ROUND(avg_peak_concurrency) AS INTEGER),'·')
          || '/' || concurrency_ceiling
|| ' | ' || CASE
               WHEN faithfulness_pass_rate IS NULL THEN '·'
               WHEN faithfulness_pass_rate = 1.0   THEN '✓'
               ELSE 'FAIL(' ||
                 CASE WHEN soundness_failures    > 0 THEN 'S' ELSE '' END ||
                 CASE WHEN completeness_failures > 0 THEN 'C' ELSE '' END ||
                 CASE WHEN determinism_failures  > 0 THEN 'D' ELSE '' END ||
               ')'
             END
|| ' | ' || COALESCE(degradation_events,'0')
|| ' | ' || COALESCE(recovered_events,'·')
|| ' | ' || CASE
               WHEN seam_exports_present IS NULL THEN '·'
               WHEN seam_exports_consumed = seam_exports_present
                AND seam_exports_present > 0 THEN 'ok'
               ELSE COALESCE(CAST(seam_exports_consumed AS TEXT),'·')
                    || '/' || COALESCE(CAST(seam_exports_present AS TEXT),'·')
             END
|| ' |' AS line
FROM v_compile_runs_sprint
WHERE project_id=? AND sprint=?
ORDER BY segment;"""

_COMPILE_DEGRADE_ROWS_SQL = """\
SELECT '- **' || segment || '**: '
    || COALESCE(degradation_causes,'(cause unrecorded)')
    || ' — ' || COALESCE(recovered_events,0)
    || '/' || degradation_events || ' recovered' AS line
FROM v_compile_runs_sprint
WHERE project_id=? AND sprint=?
  AND degradation_events > 0
ORDER BY segment;"""


async def _emit_compile_telemetry(project_id: str, fmt: str) -> None:
    """Emit the "## Compile-down telemetry" close-report subsection.

    Bash parity with ``_emit_compile_telemetry`` (v6.0.9 #87): reads the
    ``v_compile_runs_sprint`` rollup for the CURRENT git branch
    (:func:`_current_sprint`), excluding ``parse_error`` rows. Graceful
    (emits nothing) when the ``compile_runs`` table is absent (migration
    0014 never applied — possible only when the migrations dir itself is
    unavailable, since :func:`shepherd_cli.db.ensure_migrated` self-heals
    otherwise) or when no rows exist for this project+sprint.

    Args:
        project_id: The scoping project id.
        fmt: ``"json"`` or ``"md"``.
    """
    table_exists = await _scalar(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='compile_runs';", []
    )
    if int(table_exists or 0) != 1:
        return

    sprint_branch = _current_sprint()
    any_row = await _scalar(
        """SELECT 1 FROM compile_runs
           WHERE project_id=? AND sprint=? AND parse_error IS NULL LIMIT 1;""",
        [project_id, sprint_branch],
    )
    if any_row is None:
        return

    if fmt == "json":
        cell = await _scalar(_COMPILE_JSON_SQL, [project_id, sprint_branch])
        typer.echo(str(cell))
        return

    typer.echo("## Compile-down telemetry (`shctx adapt report --compile-telemetry`)")
    typer.echo("")
    typer.echo("| segment | runs | nodes | agents | peak_conc/ceil | §IV ok | degrade | recovered | seam |")
    typer.echo("|---|---|---|---|---|---|---|---|---|")
    for row in await _fetch(_COMPILE_MD_ROWS_SQL, [project_id, sprint_branch]):
        typer.echo(str(row["line"]))
    typer.echo("")

    degrade_count = await _scalar(
        """SELECT COALESCE(SUM(degradation_events),0)
           FROM v_compile_runs_sprint WHERE project_id=? AND sprint=?;""",
        [project_id, sprint_branch],
    )
    if int(degrade_count or 0) > 0:
        typer.echo("**Degradation events** (direct-dispatch fallback activated):")
        for row in await _fetch(_COMPILE_DEGRADE_ROWS_SQL, [project_id, sprint_branch]):
            typer.echo(str(row["line"]))
        typer.echo("")


async def _report_async(fmt: str, trends: bool, compile_telemetry: bool) -> None:
    """Render the sprint-patterns report (or a --trends/--compile-telemetry view).

    Bash parity with ``_cmd_report``, including its dispatch order:
    ``--trends`` wins over ``--compile-telemetry`` wins over the plain
    report.

    Args:
        fmt: ``"json"`` or ``"md"``.
        trends: ``--trends``.
        compile_telemetry: ``--compile-telemetry``.

    Raises:
        typer.Exit: Code 1 if no project is registered.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if trends:
            await _emit_trends(project_id, fmt)
            return
        if compile_telemetry:
            await _emit_compile_telemetry(project_id, fmt)
            return

        if fmt == "json":
            cell = await _scalar(_REPORT_JSON_SQL, [project_id])
            typer.echo(str(cell))
            return

        count = await _scalar(
            "SELECT count(*) FROM sprint_metrics WHERE project_id=?;", [project_id]
        )
        if int(count or 0) == 0:
            typer.echo("_(no sprint metrics recorded yet — first adaptation cycle lands at this sprint's close)_")
            return

        typer.echo("## Sprint patterns (SQLite-canonical — `shctx adapt report`)")
        typer.echo("")
        typer.echo("| sprint | grade | size | lanes | waves | wall_min | api | findings |")
        typer.echo("|---|---|---|---|---|---|---|---|")
        for row in await _fetch(_REPORT_MD_ROWS_SQL, [project_id]):
            typer.echo(str(row["line"]))
        typer.echo("")
        metrics_block = await _emit_metrics(project_id, "md")
        if metrics_block is not None:
            typer.echo(metrics_block)


@app.command()
def report(
    md: bool = typer.Option(False, "--md", help="Markdown output (the default)."),
    json_out: bool = typer.Option(False, "--json", help="JSON output for tooling."),
    trends: bool = typer.Option(False, "--trends", help="Deterministic TREND ALERT over the last 3 closes."),
    compile_telemetry: bool = typer.Option(
        False, "--compile-telemetry", help="Per-segment compile-down telemetry for the current sprint."
    ),
) -> None:
    """Render the materialized sprint-patterns view (or --trends / --compile-telemetry).

    Bash parity with ``cmd_adapt.sh``'s ``report`` arm. Conflicting
    format flags follow the module docstring's fixed precedence
    (deviation #3).
    """
    del md  # md is the default; the flag exists for CLI parity only.
    fmt = "json" if json_out else "md"
    asyncio.run(_report_async(fmt=fmt, trends=trends, compile_telemetry=compile_telemetry))


# --------------------------------------------------------------------------
# recommend — concrete dispatch recommendation
# --------------------------------------------------------------------------
#: Verbatim from ``_emit_recommend``'s watch-concerns query
#: (parameterized). SQLite permits the DISTINCT-with-outside-ORDER-BY
#: shape in the subquery; running the same SQL keeps whatever it does
#: identical between the bash and Python paths.
_RECOMMEND_CONCERNS_SQL = """\
SELECT group_concat(c, ', ') FROM (
  SELECT DISTINCT json_extract(tags,'$[0]') AS c
  FROM mem_entries
  WHERE project_id=? AND kind='prior'
    AND json_extract(tags,'$[0]') IS NOT NULL
  ORDER BY updated_at DESC, id DESC LIMIT 5);"""


async def _recommend_async(fmt: str) -> None:
    """Render the dispatch recommendation from measured averages + priors.

    Bash parity with ``_emit_recommend``: suggested lanes (measured
    average rounded via SQLite's own ROUND — half-away-from-zero, floor
    1), a t-shirt band from the measured average wall minutes, and up to
    5 recurring watch-concerns. Empty store emits the graceful
    "no history yet, use defaults" note. Never exits non-zero on a
    healthy recommendation with no watch-concerns (the bash
    trailing-``&&`` regression, kept structurally impossible here).

    Args:
        fmt: ``"json"`` or ``"md"``.

    Raises:
        typer.Exit: Code 1 if no project is registered.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        row = await _metrics_row(project_id)
        if row is None:
            if fmt == "json":
                typer.echo(_jq_compact({"history": False, "note": "no history yet, use defaults"}))
            else:
                typer.echo("_(no history yet, use defaults)_")
            return

        n = int(str(row["n"]))
        awm = float(str(row["awm"]))
        alc = float(str(row["alc"]))

        # Lanes + band computed by SQLite itself (bash interpolated the
        # captured averages back into SQL) — same ROUND/CASE semantics.
        derived = await _fetch(
            """SELECT MAX(1, CAST(ROUND(?) AS INTEGER)) AS lanes,
                      CASE
                        WHEN ? < 30  THEN 'XS'
                        WHEN ? < 60  THEN 'S'
                        WHEN ? < 120 THEN 'M'
                        WHEN ? < 240 THEN 'L'
                        ELSE 'XL' END AS band;""",
            [alc, awm, awm, awm, awm],
        )
        lanes = int(str(derived[0]["lanes"]))
        band = str(derived[0]["band"])

        concerns_raw = await _scalar(_RECOMMEND_CONCERNS_SQL, [project_id])
        concerns = "" if concerns_raw is None else str(concerns_raw)

    if fmt == "json":
        typer.echo(
            _jq_compact(
                {
                    "history": True,
                    "n": n,
                    "suggested_lanes": lanes,
                    "size_band": band,
                    "watch_concerns": concerns,
                }
            )
        )
        return

    typer.echo(f"### Dispatch recommendation — measured ({n} prior sprint(s))")
    typer.echo(f"- suggested lanes: {lanes} _(measured avg_lane_count {alc:.1f})_")
    typer.echo(f"- t-shirt band: {band} _(measured avg {awm:.0f} min/sprint)_")
    if concerns:
        typer.echo(f"- watch-concerns: {concerns}")


@app.command()
def recommend(
    md: bool = typer.Option(False, "--md", help="Markdown output (the default)."),
    json_out: bool = typer.Option(False, "--json", help="JSON output for tooling."),
) -> None:
    """Turn measured averages + recurring priors into a dispatch recommendation.

    Bash parity with ``cmd_adapt.sh``'s ``recommend`` arm. Empty store
    prints "no history yet, use defaults" (graceful).
    """
    del md  # md is the default; the flag exists for CLI parity only.
    fmt = "json" if json_out else "md"
    asyncio.run(_recommend_async(fmt=fmt))


__all__ = ["app"]
