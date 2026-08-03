"""``shepherd loop`` — Loop-Until-Done state + focus record Typer sub-app.

Native port of ``skills/context/scripts/cmd_loop.sh`` (v6.0.9 #134 / Item
A0): SQLite-backed loop lifecycle state (``loops`` + ``loop_iterations``,
migration ``0012_loop_state.sql``) and the per-sprint / per-lane focus
record (``focus``, migrations ``0013_focus.sql`` + ``0017_focus_lane.sql``,
PK ``(sprint, lane)``). Backs ``/shepherd:loop`` and the FOCUS-LOOP
runtime — loop state is canonical (survives compaction) so the focus loop
never loses its place across context resets.

Bash ``case`` arm -> Typer command map::

    init        -> ``loop init``        (register a loop, print loop-id)
    native-cmd  -> ``loop native-cmd``  (emit the exact native /loop line)
    status      -> ``loop status``      (one loop + iteration history)
    record      -> ``loop record``      (append one iteration, idempotent)
    close       -> ``loop close``       (finalize with terminal status)
    list        -> ``loop list``        (loops for this project)
    focus       -> ``loop focus upsert|show``  (nested Typer group; bare
                   ``loop focus`` defaults to ``show``, matching bash's
                   ``focussub="${1:-show}"``)

**#234 regression — parameterized SQL everywhere.** Bash built every
statement by string interpolation with the ``_txt()`` quote-doubling
helper; ``loop focus upsert`` still broke on an ``--objective`` containing
an apostrophe (the issue-#234 class). This module binds EVERY value —
including ``--objective``/``--task``/``--summary`` and all focus columns —
as a ``?`` parameter through Tortoise's
``get_connection("default").execute_query(...)`` (the
:mod:`shepherd_cli.commands.mem` / :mod:`shepherd_cli.commands.lock` raw-SQL
pattern), so apostrophes, double quotes, semicolons, and pipes round-trip
byte-identically and the injection-shaped failure path is structurally
unreachable. ``tests/test_loop.py`` carries the regression test.

**No Tortoise models, deliberately.** The ``focus`` table is ALREADY
mirrored by :class:`shepherd_cli.models_dash.Focus` (read-only, two
columns) — redeclaring it with more fields would collide in the same
Tortoise app (the ``models_dash.py`` collision rule), and ``loops`` /
``loop_iterations`` writes need columns no existing model declares. Per
the ``lock.py`` precedent (its ``locks_history`` note), ALL reads/writes
here go through raw parameterized SQL on the default connection; the
pydantic models below type only the ``--json`` output payloads.

**Project-id resolution deviation** (matches
:mod:`shepherd_cli.commands.lock` / :mod:`shepherd_cli.commands.mem`
exactly): ``cmd_loop.sh`` computes ``pid=$(shctx_project_id)``
UNCONDITIONALLY at the top of the script, before dispatching to ANY
subcommand, under ``set -eu -o pipefail`` — so every subcommand (including
``focus show``, which never uses the project id) fails with exit 1 when no
project is registered. This module reproduces that prerequisite-gate
ordering (:func:`_require_project_id` runs first in every handler) but
resolves the active project via ``SELECT id FROM projects LIMIT 1``
(:class:`shepherd_cli.models.Project`) instead of reading the
``project.json`` sidecar, because that table is what the shared test
harness and every other ported command group scope through. In a healthy
project the two always agree (both written together by ``shctx init``).

Documented deviations from bash (all narrow; everything else is
byte-parity, including the em-dash in ``native-cmd``'s in-session note):

1. **Unknown subcommand / unknown option -> exit 2** with Click's own
   message, not bash's ``ERROR: unknown arg: ...`` / ``ERROR: unknown
   subcommand`` at exit 1. Same documented deviation class as
   ``lock.py``'s unrecognized-subcommand note: reproducing bash's exact
   text/exit-code would mean subclassing Typer's vendored Click machinery.
   Likewise ``-h`` (bash's short help alias) is not registered — ``--help``
   only, matching every sibling sub-app — and per-command ``--help`` text
   is Typer's, not bash's usage() block (both exit 0, like bash).
2. **Day-sequence parse off-by-one fixed**: bash computed the next
   ``loop-YYYYMMDD-NNN`` sequence with ``CAST(substr(id,16) AS INTEGER)``
   — position 16 drops the FIRST digit of the 3-digit sequence (``-123``
   reads as ``23``), silently mis-computing MAX at >= 100 loops/day. This
   port uses the correct ``substr(id,15)``. Identical for the first 99
   loops of a day.
3. **Values containing ``|`` render correctly**: bash split sqlite's
   pipe-delimited rows with ``IFS='|'``, so a ``|`` in task/summary/
   objective corrupted every text/md rendering. This port reads typed
   columns; no splitting.
4. **DB constraint errors** (e.g. ``record --iteration=0`` violating
   ``CHECK(iteration > 0)``) surface as ``ERROR: <driver message>`` on
   stderr with exit 1, instead of the raw ``sqlite3 -bail`` CLI stderr
   (same non-zero outcome, different text).
5. **``--json`` wins over ``--md``** when both are passed (bash was
   last-flag-wins). ``--all`` wins over ``--active`` likewise.
6. ``--new-findings`` is accepted as an additive alias of bash's exact
   ``--new_findings`` spelling.
7. **``jq -e`` parity kept on purpose**: ``--obligations``/``--invariants``
   values of ``null`` or ``false`` are rejected as "not valid JSON"
   exactly like bash's ``jq -e .`` (which exits non-zero when the last
   output is ``null``/``false``), even though they ARE valid JSON texts.
8. **Run-scoped artifacts: not applicable.** This command's state lives
   entirely in SQLite (``loops``/``loop_iterations``/``focus``); it never
   reads or writes ``<workdir>/graph/`` files, so the
   ``<workdir>/runs/{run}/`` migration shim other ports carry has nothing
   to shim here.

Timestamps are epoch SECONDS throughout (``loops.created_at``,
``loop_iterations.recorded_at``, ``focus.updated_at``), matching
``_lib.sh``'s ``shctx_now`` (``date +%s``).
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from typing import Any

import typer
from pydantic import BaseModel
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError, OperationalError

from shepherd_cli import db
from shepherd_cli.models import Project

app = typer.Typer(
    add_completion=False,
    help="Loop-Until-Done state (loops/loop_iterations) + focus record (focus table).",
)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Bare ``shepherd loop`` -> help text, exit 0 (bash parity).

    ``cmd_loop.sh`` prints ``usage()`` and exits 0 for a bare ``shctx
    loop`` (and ``-h``/``--help``). Click's ``no_args_is_help`` exits 2 on
    current Click (``NoArgsIsHelpError`` is a ``UsageError``), so this
    callback reproduces bash's exit 0 explicitly.

    Args:
        ctx: ``invoked_subcommand`` is None only for a bare ``loop``.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)

focus_app = typer.Typer(
    add_completion=False,
    help="Read/write the focus record for a sprint, or a lane within it.",
)
app.add_typer(focus_app, name="focus")

#: Valid ``--kind`` values (``loops.kind`` CHECK vocabulary).
_KINDS = ("focus", "convergence", "watch", "generic")

#: Valid ``loop close --status`` terminal values.
_CLOSE_STATUSES = ("converged", "cap-reached", "aborted")

#: ``_bool()`` parity: true/1 -> 1, false/0 -> 0 for ``new_findings``.
_BOOL_MAP = {"true": 1, "1": 1, "false": 0, "0": 0}

#: ``_num()`` parity: bash's ``^[0-9]+$`` integer gate.
_NUM_RE = re.compile(r"[0-9]+")


class LoopIterationOut(BaseModel):
    """One iteration entry inside :class:`LoopStatusOut` (``status --json``).

    Field order matches the bash ``json_object`` key order exactly.
    """

    iteration: int
    new_findings: int | None
    summary: str | None
    recorded_at: int


class LoopStatusOut(BaseModel):
    """The ``loop status --json`` payload (bash's ``json_object`` mirror)."""

    id: str
    kind: str | None
    task: str | None
    agent: str | None
    max_iterations: int
    until_field: str
    interval: str | None
    status: str
    created_at: int
    iterations: list[LoopIterationOut]


class LoopListItemOut(BaseModel):
    """One element of the ``loop list --json`` array."""

    id: str
    kind: str | None
    task: str | None
    agent: str | None
    max_iterations: int
    status: str
    created_at: int


class FocusShowOut(BaseModel):
    """The ``loop focus show --json`` payload.

    ``obligations``/``invariants`` carry the PARSED JSON value (bash wraps
    the stored TEXT in sqlite's ``json()`` so it embeds as real JSON, not
    a quoted string) — ``Any`` because the stored document may be an
    array, object, number, or string.
    """

    sprint: str
    lane: str
    objective: str | None
    active_node: str | None
    ready_set: str | None
    obligations: Any
    invariants: Any
    updated_at: int


def _now_s() -> int:
    """Return epoch seconds, matching ``_lib.sh``'s ``shctx_now`` (``date +%s``)."""
    return int(time.time())


def _fail(message: str) -> None:
    """Print ``message`` to stderr and exit 1 (bash's ``echo >&2; exit 1``).

    Args:
        message: The full bash-parity error line, INCLUDING its
            ``ERROR: `` prefix (the bash messages carry it themselves).

    Raises:
        typer.Exit: Always, with code 1.
    """
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _dot(value: object) -> str:
    """Render a nullable column like bash's ``${var:-·}`` middle-dot fallback.

    Args:
        value: The column value (None for SQL NULL; bash sees NULL as an
            empty field after its ``IFS='|'`` split, so empty string and
            None both dot out).

    Returns:
        ``str(value)`` for a non-empty value, else ``"·"``.
    """
    if value is None or value == "":
        return "·"
    return str(value)


def _current_sprint() -> str:
    """The current git branch name, or ``"unknown"``.

    Parity with ``_lib.sh``'s ``current_sprint`` (``git rev-parse
    --abbrev-ref HEAD 2>/dev/null || printf 'unknown'``) — used by
    ``focus show`` when ``--sprint`` is omitted.

    Returns:
        The branch name, or ``"unknown"`` when git is unavailable, errors,
        or prints nothing.
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
        out = result.stdout.strip()
        if out:
            return out
    return "unknown"


async def _require_project_id() -> str:
    """Resolve the active project id, or exit 1 (bash-parity prerequisite gate).

    See the module docstring's "Project-id resolution deviation":
    ``cmd_loop.sh`` runs ``pid=$(shctx_project_id)`` before dispatching to
    ANY subcommand, so every handler here calls this FIRST, inside
    ``db.lifespan()``. Message/exit identical to
    :func:`shepherd_cli.commands.lock._require_project_id`.

    Returns:
        The active project id.

    Raises:
        typer.Exit: With code 1 if no project is registered.
    """
    project = await Project.all().first()
    if project is None:
        typer.echo("ERROR: no project registered — run 'shctx init' first", err=True)
        raise typer.Exit(code=1)
    return project.id


def _validate_json_option(value: str, flag: str) -> None:
    """Reject a non-JSON ``--obligations``/``--invariants`` value (jq -e parity).

    Bash pipes the value through ``jq -e .``, which exits non-zero BOTH
    for unparseable input AND for a top-level ``null``/``false`` (jq's
    ``-e`` semantics) — this reproduces that exactly (documented
    deviation-list item 7: kept on purpose).

    Args:
        value: The raw option value (empty = not supplied = no check).
        flag: The flag name for the error message, e.g. ``"--obligations"``.

    Raises:
        typer.Exit: With code 1 and ``ERROR: <flag> is not valid JSON``.
    """
    if not value:
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        _fail(f"ERROR: {flag} is not valid JSON")
        return
    if parsed is None or parsed is False:
        _fail(f"ERROR: {flag} is not valid JSON")


def _fmt(json_out: bool, md_out: bool) -> str:
    """Collapse the ``--json``/``--md`` flag pair to one format token.

    Args:
        json_out: ``--json`` was passed.
        md_out: ``--md`` was passed.

    Returns:
        ``"json"``, ``"md"``, or ``"text"``; ``--json`` wins over ``--md``
        when both are passed (documented deviation-list item 5).
    """
    if json_out:
        return "json"
    if md_out:
        return "md"
    return "text"


def _parse_stored_json(value: object) -> Any:
    """Parse a stored ``focus.obligations``/``invariants`` TEXT column.

    The 0013/0017 schema CHECK-guarantees these columns are NULL or valid
    JSON, so the fallback branch is unreachable for a healthy DB; a
    hand-corrupted value degrades to the raw string rather than crashing
    (bash's ``json()`` would abort the whole query there).

    Args:
        value: The stored column value (None or a JSON text).

    Returns:
        The parsed JSON value, None for NULL, or the raw string if
        (impossibly, per the CHECK) unparseable.
    """
    if value is None:
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return str(value)


# ---------------------------------------------------------------------------
# init — register a new loop, emit the loop-id
# ---------------------------------------------------------------------------
async def _init_async(
    task: str,
    max_value: str,
    kind: str,
    agent: str,
    until_field: str,
    interval: str,
    self_paced: bool,
) -> None:
    """Register a new loop; print its day-scoped id (``loop-YYYYMMDD-NNN``).

    Validation order matches bash exactly: project gate, then the
    ``--self-paced``/``--interval`` mutual-exclusion check, then ``--max``
    required, then ``--max`` positive-integer, then ``--kind`` vocabulary.

    Args:
        task: ``--task`` (empty -> NULL, bash ``_txt``).
        max_value: ``--max`` as the RAW string (validated here with bash's
            exact regex + message, not by Typer's own int coercion).
        kind: ``--kind`` (default ``"generic"``).
        agent: ``--agent`` (empty -> NULL).
        until_field: ``--until`` (default ``"new_findings"``; stored
            verbatim, even empty — bash interpolates it raw, not via
            ``_txt``).
        interval: ``--interval`` (empty -> NULL).
        self_paced: ``--self-paced`` — stores the ``'self-paced'`` pacing
            sentinel; mutually exclusive with a fixed ``--interval``.

    Raises:
        typer.Exit: Code 1 on any validation failure (bash-parity
            messages) or DB constraint error.
    """
    async with db.lifespan():
        project_id = await _require_project_id()

        if self_paced:
            if interval and interval != "self-paced":
                _fail("ERROR: --self-paced and --interval=<dur> are mutually exclusive")
            interval = "self-paced"

        if not max_value:
            _fail("ERROR: loop init requires --max=<N>")
        if _NUM_RE.fullmatch(max_value) is None or int(max_value) <= 0:
            _fail(f"ERROR: --max must be a positive integer (got '{max_value}')")

        if kind not in _KINDS:
            _fail(f"ERROR: --kind must be focus|convergence|watch|generic (got '{kind}')")

        today = time.strftime("%Y%m%d")
        connection = Tortoise.get_connection("default")
        # substr(id,15) — the full 'NNN' suffix (bash's substr(id,16) was
        # off by one; documented deviation-list item 2).
        rows = await connection.execute_query_dict(
            "SELECT COALESCE(MAX(CAST(substr(id,15) AS INTEGER)),0) + 1 AS seq"
            " FROM loops WHERE project_id=? AND id LIKE ?",
            [project_id, f"loop-{today}-%"],
        )
        seq = int(rows[0]["seq"]) if rows and rows[0]["seq"] is not None else 1
        loop_id = f"loop-{today}-{seq:03d}"

        try:
            await connection.execute_query(
                "INSERT INTO loops"
                " (id, project_id, kind, task, agent, max_iterations, until_field,"
                "  interval, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                [
                    loop_id,
                    project_id,
                    kind,
                    task or None,
                    agent or None,
                    int(max_value),
                    until_field,
                    interval or None,
                    _now_s(),
                ],
            )
        except (IntegrityError, OperationalError) as exc:
            _fail(f"ERROR: {exc}")

    typer.echo(loop_id)


@app.command("init")
def init_cmd(
    task: str = typer.Option("", "--task", help="What the loop is working toward."),
    max_value: str = typer.Option("", "--max", help="Iteration cap (positive integer). Required."),
    kind: str = typer.Option("generic", "--kind", help="focus|convergence|watch|generic."),
    agent: str = typer.Option("", "--agent", help="worker|discovery|orchestrator."),
    until_field: str = typer.Option(
        "new_findings", "--until", help="Convergence field (default new_findings)."
    ),
    interval: str = typer.Option("", "--interval", help="Fixed pacing, e.g. '5m'; empty = in-session."),
    self_paced: bool = typer.Option(
        False,
        "--self-paced",
        help="Store the 'self-paced' pacing sentinel (native /loop picks the delay); mutually exclusive with --interval.",
    ),
) -> None:
    """Register a new loop. Prints the loop-id (e.g. loop-20260609-001) on stdout."""
    asyncio.run(_init_async(task, max_value, kind, agent, until_field, interval, self_paced))


# ---------------------------------------------------------------------------
# native-cmd — emit the exact native /loop invocation, read from stored pacing
# ---------------------------------------------------------------------------
async def _native_cmd_async(loop_id: str, command: str) -> None:
    """Print the exact native ``/loop`` invocation for a loop.

    Deterministic — fully determined by the loop's stored ``interval`` +
    the resume command, so it lives in code, never rebuilt by the model
    per wake (agent-excellence Rule 7, per the bash header). Branches::

        ''/none/in-session  =>  in-session note (no native schedule)
        self-paced/auto     =>  /loop <command>
        anything else       =>  /loop <interval> <command>

    Args:
        loop_id: ``--id`` (required).
        command: ``--command`` override; defaults to
            ``/shepherd:loop --resume <loop-id>``.

    Raises:
        typer.Exit: Code 1 when ``--id`` is missing or the loop is not
            found for this project.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not loop_id:
            _fail("ERROR: loop native-cmd requires --id=<loop-id>")
        connection = Tortoise.get_connection("default")
        rows = await connection.execute_query_dict(
            "SELECT COALESCE(interval,'') AS interval FROM loops WHERE id=? AND project_id=?",
            [loop_id, project_id],
        )
        if not rows:
            _fail(f"ERROR: loop not found: {loop_id}")
        interval = str(rows[0]["interval"])

    resume = command if command else f"/shepherd:loop --resume {loop_id}"
    if interval in ("", "none", "in-session"):
        typer.echo("(in-session drive — no native /loop schedule; shepherd drives the iteration directly)")
    elif interval in ("self-paced", "auto"):
        typer.echo(f"/loop {resume}")
    else:
        typer.echo(f"/loop {interval} {resume}")


@app.command("native-cmd")
def native_cmd_cmd(
    loop_id: str = typer.Option("", "--id", help="The loop-id. Required."),
    command: str = typer.Option(
        "", "--command", help="Resume command override (default '/shepherd:loop --resume <loop-id>')."
    ),
) -> None:
    """Print the exact native /loop invocation for this loop, from its stored pacing."""
    asyncio.run(_native_cmd_async(loop_id, command))


# ---------------------------------------------------------------------------
# status — show one loop + iteration history
# ---------------------------------------------------------------------------
async def _status_async(loop_id: str, fmt: str) -> None:
    """Show one loop's header + iteration history (text / ``--md`` / ``--json``).

    Args:
        loop_id: ``--id`` (required).
        fmt: ``"text"`` | ``"md"`` | ``"json"``.

    Raises:
        typer.Exit: Code 1 when ``--id`` is missing or the loop is not
            found for this project.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not loop_id:
            _fail("ERROR: loop status requires --id=<loop-id>")
        connection = Tortoise.get_connection("default")
        rows = await connection.execute_query_dict(
            "SELECT id,kind,task,agent,max_iterations,until_field,interval,status,created_at"
            " FROM loops WHERE id=? AND project_id=?",
            [loop_id, project_id],
        )
        if not rows:
            _fail(f"ERROR: loop not found: {loop_id}")
        row = rows[0]
        iterations = await connection.execute_query_dict(
            "SELECT iteration, new_findings, summary, recorded_at"
            " FROM loop_iterations WHERE loop_id=? ORDER BY iteration",
            [loop_id],
        )

    if fmt == "json":
        payload = LoopStatusOut(
            id=row["id"],
            kind=row["kind"],
            task=row["task"],
            agent=row["agent"],
            max_iterations=row["max_iterations"],
            until_field=row["until_field"],
            interval=row["interval"],
            status=row["status"],
            created_at=row["created_at"],
            iterations=[
                LoopIterationOut(
                    iteration=it["iteration"],
                    new_findings=it["new_findings"],
                    summary=it["summary"],
                    recorded_at=it["recorded_at"],
                )
                for it in iterations
            ],
        )
        typer.echo(payload.model_dump_json())
        return

    if fmt == "md":
        typer.echo(f"## Loop: {row['id']}")
        typer.echo(
            f"- kind: {_dot(row['kind'])}\n"
            f"- task: {_dot(row['task'])}\n"
            f"- agent: {_dot(row['agent'])}\n"
            f"- max: {row['max_iterations']}\n"
            f"- until: {row['until_field']}\n"
            f"- interval: {row['interval'] or 'none'}\n"
            f"- status: **{row['status']}**\n"
            f"- created_at: {row['created_at']}"
        )
        typer.echo("")
        typer.echo("### Iterations")
        if not iterations:
            typer.echo("_(none yet)_")
            return
        typer.echo("| # | new_findings | summary | recorded_at |")
        typer.echo("|---|---|---|---|")
        for it in iterations:
            nf_label = "true" if it["new_findings"] == 1 else "false"
            typer.echo(
                f"| {it['iteration']} | {nf_label} | {_dot(it['summary'])} | {it['recorded_at']} |"
            )
        return

    # text
    typer.echo(
        f"id={row['id']} kind={row['kind'] or 'generic'} status={row['status']}"
        f" max={row['max_iterations']} until={row['until_field']}"
    )
    typer.echo(
        f"task={_dot(row['task'])} agent={_dot(row['agent'])}"
        f" interval={row['interval'] or 'none'} created_at={row['created_at']}"
    )
    if iterations:
        typer.echo("iterations:")
        for it in iterations:
            nf_label = "true" if it["new_findings"] == 1 else "false"
            summary = it["summary"] if it["summary"] else "none"
            typer.echo(
                f"  [{it['iteration']}] new_findings={nf_label}"
                f" recorded_at={it['recorded_at']} summary={summary}"
            )
    else:
        typer.echo("iterations: (none yet)")


@app.command("status")
def status_cmd(
    loop_id: str = typer.Option("", "--id", help="The loop-id. Required."),
    json_out: bool = typer.Option(False, "--json", help="Emit the loop + iterations as one JSON object."),
    md_out: bool = typer.Option(False, "--md", help="Markdown rendering."),
) -> None:
    """Show loop header + iteration history."""
    asyncio.run(_status_async(loop_id, _fmt(json_out, md_out)))


# ---------------------------------------------------------------------------
# record — append one iteration result (idempotent on loop_id + iteration)
# ---------------------------------------------------------------------------
async def _record_async(loop_id: str, iteration: str, new_findings: str, summary: str) -> None:
    """Append one iteration row (``INSERT OR REPLACE`` — idempotent).

    Check order matches bash exactly: required flags, loop-exists, THEN
    ``--new_findings`` vocabulary, THEN ``--iteration`` integer shape.
    ``--iteration=0`` passes bash's ``_num`` regex and dies on the schema's
    ``CHECK(iteration > 0)`` — reproduced here via deviation-list item 4.

    Args:
        loop_id: ``--id`` (required).
        iteration: ``--iteration`` raw string (bash ``_num`` validation).
        new_findings: ``--new_findings`` raw string (true|false|1|0).
        summary: ``--summary`` (empty -> NULL).

    Raises:
        typer.Exit: Code 1 on any validation failure, unknown loop, or DB
            constraint error.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not loop_id:
            _fail("ERROR: loop record requires --id=<loop-id>")
        if not iteration:
            _fail("ERROR: loop record requires --iteration=<N>")
        if not new_findings:
            _fail("ERROR: loop record requires --new_findings=<true|false|0|1>")

        connection = Tortoise.get_connection("default")
        exists = await connection.execute_query_dict(
            "SELECT 1 AS one FROM loops WHERE id=? AND project_id=? LIMIT 1",
            [loop_id, project_id],
        )
        if not exists:
            _fail(f"ERROR: loop not found: {loop_id}")

        nf = _BOOL_MAP.get(new_findings)
        if nf is None:
            _fail(f"ERROR: --new_findings must be true|false|1|0 (got '{new_findings}')")
        if _NUM_RE.fullmatch(iteration) is None:
            _fail(f"ERROR: --iteration must be a positive integer (got '{iteration}')")

        try:
            await connection.execute_query(
                "INSERT OR REPLACE INTO loop_iterations"
                " (loop_id, iteration, new_findings, summary, recorded_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [loop_id, int(iteration), nf, summary or None, _now_s()],
            )
        except (IntegrityError, OperationalError) as exc:
            _fail(f"ERROR: {exc}")

    typer.echo(f"loop record: {loop_id} iteration {iteration} new_findings={new_findings}")


@app.command("record")
def record_cmd(
    loop_id: str = typer.Option("", "--id", help="The loop-id. Required."),
    iteration: str = typer.Option("", "--iteration", help="Iteration number (positive integer). Required."),
    new_findings: str = typer.Option(
        "",
        "--new_findings",
        "--new-findings",
        help="true|false|1|0. Required. (--new-findings is an additive alias.)",
    ),
    summary: str = typer.Option("", "--summary", help="One-line iteration summary."),
) -> None:
    """Append one iteration record (idempotent on loop_id + iteration)."""
    asyncio.run(_record_async(loop_id, iteration, new_findings, summary))


# ---------------------------------------------------------------------------
# close — finalize a loop with terminal status
# ---------------------------------------------------------------------------
async def _close_async(loop_id: str, status: str) -> None:
    """Finalize a loop, writing its terminal status.

    Args:
        loop_id: ``--id`` (required).
        status: ``--status`` — one of :data:`_CLOSE_STATUSES`.

    Raises:
        typer.Exit: Code 1 on missing flags, invalid status, or unknown
            loop.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not loop_id:
            _fail("ERROR: loop close requires --id=<loop-id>")
        if not status:
            _fail("ERROR: loop close requires --status=<converged|cap-reached|aborted>")
        if status not in _CLOSE_STATUSES:
            _fail(f"ERROR: --status must be converged|cap-reached|aborted (got '{status}')")

        connection = Tortoise.get_connection("default")
        exists = await connection.execute_query_dict(
            "SELECT 1 AS one FROM loops WHERE id=? AND project_id=? LIMIT 1",
            [loop_id, project_id],
        )
        if not exists:
            _fail(f"ERROR: loop not found: {loop_id}")

        await connection.execute_query(
            "UPDATE loops SET status=? WHERE id=?",
            [status, loop_id],
        )
        count_rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS n FROM loop_iterations WHERE loop_id=?",
            [loop_id],
        )
        iterations = count_rows[0]["n"] if count_rows else 0

    typer.echo(f"loop close: {loop_id} status={status} iterations={iterations}")


@app.command("close")
def close_cmd(
    loop_id: str = typer.Option("", "--id", help="The loop-id. Required."),
    status: str = typer.Option("", "--status", help="converged|cap-reached|aborted. Required."),
) -> None:
    """Finalize a loop."""
    asyncio.run(_close_async(loop_id, status))


# ---------------------------------------------------------------------------
# list — list loops for this project
# ---------------------------------------------------------------------------
async def _list_async(show_all: bool, fmt: str) -> None:
    """List loops for this project (default: active only, newest first, cap 50).

    Args:
        show_all: True for ``--all`` (every status), False for the
            ``--active`` default.
        fmt: ``"text"`` | ``"md"`` | ``"json"``.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        connection = Tortoise.get_connection("default")
        where = "project_id=?"
        params: list[object] = [project_id]
        if not show_all:
            where += " AND status=?"
            params.append("active")
        rows = await connection.execute_query_dict(
            "SELECT id,kind,task,agent,max_iterations,status,created_at FROM loops"
            f" WHERE {where} ORDER BY created_at DESC, id DESC LIMIT 50",  # noqa: S608 - `where` is built from fixed literals above; every value is a ? bind
            params,
        )

    if fmt == "json":
        items = [
            LoopListItemOut(
                id=r["id"],
                kind=r["kind"],
                task=r["task"],
                agent=r["agent"],
                max_iterations=r["max_iterations"],
                status=r["status"],
                created_at=r["created_at"],
            ).model_dump()
            for r in rows
        ]
        typer.echo(json.dumps(items, separators=(",", ":"), ensure_ascii=False))
        return

    if not rows:
        typer.echo("_(no loops found)_")
        return

    if fmt == "md":
        typer.echo(f"## Loops ({'all' if show_all else 'active'})")
        typer.echo("")
        typer.echo("| id | kind | status | task | agent | max | created_at |")
        typer.echo("|---|---|---|---|---|---|---|")
        for r in rows:
            task_cell = r["task"][:40] if r["task"] is not None else "·"
            typer.echo(
                f"| {r['id']} | {_dot(r['kind'])} | {r['status']} | {task_cell}"
                f" | {_dot(r['agent'])} | {r['max_iterations']} | {r['created_at']} |"
            )
        return

    # text
    for r in rows:
        task_cell = r["task"][:50] if r["task"] is not None else "·"
        typer.echo(
            f"{r['id']}  {r['status']}  kind={r['kind'] or 'generic'}"
            f"  max={r['max_iterations']}  agent={r['agent'] or '·'}  task={task_cell}"
        )


@app.command("list")
def list_cmd(
    active: bool = typer.Option(False, "--active", help="Only active loops (the default)."),
    show_all: bool = typer.Option(False, "--all", help="Every status."),
    json_out: bool = typer.Option(False, "--json", help="Emit a JSON array."),
    md_out: bool = typer.Option(False, "--md", help="Markdown table."),
) -> None:
    """List loops for this project (default: active)."""
    del active  # --active is the default; only --all changes the filter (deviation-list item 5)
    asyncio.run(_list_async(show_all, _fmt(json_out, md_out)))


# ---------------------------------------------------------------------------
# focus — read / upsert the focus record (thin wrapper on the `focus` table)
# ---------------------------------------------------------------------------
#: (column, option-value) pairs `focus upsert` may patch — fixed allow-list,
#: never user input (the column name is the ONLY interpolated token in the
#: UPDATE below; every value is a ? bind).
_FOCUS_PATCH_COLUMNS = ("objective", "active_node", "ready_set", "obligations", "invariants")


async def _focus_upsert_async(
    sprint: str,
    lane: str,
    objective: str,
    active_node: str,
    ready_set: str,
    obligations: str,
    invariants: str,
) -> None:
    """Create or patch the focus record for ``(sprint, lane)``.

    Existing row: patch ONLY the supplied (non-empty) columns, keep the
    rest, always bump ``updated_at`` -> ``focus upsert: refreshed <label>``.
    No row: insert (empty values -> NULL, bash ``_txt``) ->
    ``focus upsert: created <label>``. ``lane=''`` is the sprint-level
    record; ``<label>`` is ``sprint`` or ``sprint/lane``.

    This is the #234 regression site: every value is a ``?`` bind, so an
    ``--objective`` with apostrophes/quotes/semicolons round-trips
    byte-identically (see the module docstring).

    Args:
        sprint: ``--sprint`` (required).
        lane: ``--lane`` (empty = sprint-level record).
        objective: ``--objective``.
        active_node: ``--active-node``.
        ready_set: ``--ready-set``.
        obligations: ``--obligations`` (validated as JSON, jq -e parity).
        invariants: ``--invariants`` (validated as JSON, jq -e parity).

    Raises:
        typer.Exit: Code 1 when ``--sprint`` is missing or a JSON column
            value fails validation.
    """
    async with db.lifespan():
        await _require_project_id()
        if not sprint:
            _fail("ERROR: focus upsert requires --sprint=<branch>")
        _validate_json_option(obligations, "--obligations")
        _validate_json_option(invariants, "--invariants")

        label = f"{sprint}/{lane}" if lane else sprint
        connection = Tortoise.get_connection("default")
        exists = await connection.execute_query_dict(
            "SELECT 1 AS one FROM focus WHERE sprint=? AND lane=? LIMIT 1",
            [sprint, lane],
        )
        if exists:
            supplied = {
                "objective": objective,
                "active_node": active_node,
                "ready_set": ready_set,
                "obligations": obligations,
                "invariants": invariants,
            }
            for column in _FOCUS_PATCH_COLUMNS:
                value = supplied[column]
                if value:
                    await connection.execute_query(
                        f"UPDATE focus SET {column}=? WHERE sprint=? AND lane=?",  # noqa: S608 - column from the fixed _FOCUS_PATCH_COLUMNS allow-list, value is a ? bind
                        [value, sprint, lane],
                    )
            await connection.execute_query(
                "UPDATE focus SET updated_at=? WHERE sprint=? AND lane=?",
                [_now_s(), sprint, lane],
            )
            typer.echo(f"focus upsert: refreshed {label}")
        else:
            await connection.execute_query(
                "INSERT INTO focus"
                " (sprint,lane,objective,active_node,ready_set,obligations,invariants,updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    sprint,
                    lane,
                    objective or None,
                    active_node or None,
                    ready_set or None,
                    obligations or None,
                    invariants or None,
                    _now_s(),
                ],
            )
            typer.echo(f"focus upsert: created {label}")


async def _focus_show_async(sprint: str, lane: str, fmt: str) -> None:
    """Show the focus record for ``(sprint, lane)``.

    ``--sprint`` omitted -> the current git branch (``current_sprint``,
    falling back to ``"unknown"``). No matching row prints
    ``_(no focus record for: <label>)_`` and exits 0.

    Args:
        sprint: ``--sprint`` (empty = current branch).
        lane: ``--lane`` (empty = sprint-level record).
        fmt: ``"text"`` | ``"md"`` | ``"json"``.
    """
    async with db.lifespan():
        await _require_project_id()
        target = sprint if sprint else _current_sprint()
        label = f"{target}/{lane}" if lane else target
        connection = Tortoise.get_connection("default")
        rows = await connection.execute_query_dict(
            "SELECT sprint,lane,objective,active_node,ready_set,obligations,invariants,updated_at"
            " FROM focus WHERE sprint=? AND lane=?",
            [target, lane],
        )

    if not rows:
        typer.echo(f"_(no focus record for: {label})_")
        return
    row = rows[0]

    if fmt == "json":
        payload = FocusShowOut(
            sprint=row["sprint"],
            lane=row["lane"],
            objective=row["objective"],
            active_node=row["active_node"],
            ready_set=row["ready_set"],
            obligations=_parse_stored_json(row["obligations"]),
            invariants=_parse_stored_json(row["invariants"]),
            updated_at=row["updated_at"],
        )
        typer.echo(payload.model_dump_json())
        return

    if fmt == "md":
        lane_suffix = f" / {row['lane']}" if row["lane"] else ""
        typer.echo(f"## Focus record — {row['sprint']}{lane_suffix}")
        typer.echo(f"- **objective:** {_dot(row['objective'])}")
        typer.echo(f"- **active_node:** {_dot(row['active_node'])}")
        typer.echo(f"- **ready_set:** {_dot(row['ready_set'])}")
        typer.echo(f"- **obligations:** {_dot(row['obligations'])}")
        typer.echo(f"- **invariants:** {_dot(row['invariants'])}")
        typer.echo(f"- **updated_at:** {row['updated_at']}")
        return

    # text
    typer.echo(
        f"sprint={row['sprint']} lane={_dot(row['lane'])} active_node={_dot(row['active_node'])}"
        f" ready_set={_dot(row['ready_set'])} updated_at={row['updated_at']}"
    )
    typer.echo(f"objective={_dot(row['objective'])}")
    typer.echo(f"obligations={_dot(row['obligations'])}")
    typer.echo(f"invariants={_dot(row['invariants'])}")


@focus_app.callback(invoke_without_command=True)
def _focus_default(ctx: typer.Context) -> None:
    """No focus subcommand -> ``show`` (bash parity: ``focussub="${1:-show}"``).

    Bash treats a bare ``shctx loop focus`` as ``focus show`` for the
    current branch. Note the bash default engages ONLY with zero
    arguments — ``loop focus --sprint=X`` errors in bash too (unknown
    focus subcommand, exit 1; here Click's own no-such-option, exit 2 —
    deviation-list item 1) — so this callback deliberately declares no
    options.

    Args:
        ctx: ``invoked_subcommand`` is None only for a bare
            ``loop focus``.
    """
    if ctx.invoked_subcommand is None:
        asyncio.run(_focus_show_async(sprint="", lane="", fmt="text"))


@focus_app.command("upsert")
def focus_upsert_cmd(
    sprint: str = typer.Option("", "--sprint", help="Sprint branch (required)."),
    lane: str = typer.Option("", "--lane", help="Lane id; omit for the sprint-level record."),
    objective: str = typer.Option("", "--objective", help="North-star paragraph."),
    active_node: str = typer.Option("", "--active-node", help="Current Stage-Graph node id."),
    ready_set: str = typer.Option("", "--ready-set", help="Comma-joined node ids."),
    obligations: str = typer.Option("", "--obligations", help="JSON: open lanes, undrained mail, pending gates."),
    invariants: str = typer.Option("", "--invariants", help="JSON: hold-true rules."),
    json_out: bool = typer.Option(False, "--json", help="Accepted for bash parity; no effect on upsert."),
    md_out: bool = typer.Option(False, "--md", help="Accepted for bash parity; no effect on upsert."),
) -> None:
    """Upsert the focus record for a sprint, or a lane within it."""
    del json_out, md_out  # bash parses --json/--md for both focus subcommands; upsert ignores them
    asyncio.run(
        _focus_upsert_async(sprint, lane, objective, active_node, ready_set, obligations, invariants)
    )


@focus_app.command("show")
def focus_show_cmd(
    sprint: str = typer.Option("", "--sprint", help="Sprint branch; defaults to the current git branch."),
    lane: str = typer.Option("", "--lane", help="Lane id; omit for the sprint-level record."),
    objective: str = typer.Option("", "--objective", help="Accepted for bash parity; no effect on show."),
    active_node: str = typer.Option("", "--active-node", help="Accepted for bash parity; no effect on show."),
    ready_set: str = typer.Option("", "--ready-set", help="Accepted for bash parity; no effect on show."),
    obligations: str = typer.Option("", "--obligations", help="Accepted for bash parity; no effect on show."),
    invariants: str = typer.Option("", "--invariants", help="Accepted for bash parity; no effect on show."),
    json_out: bool = typer.Option(False, "--json", help="Emit the record as one JSON object."),
    md_out: bool = typer.Option(False, "--md", help="Markdown rendering."),
) -> None:
    """Show the focus record for a sprint, or a lane within it."""
    del objective, active_node, ready_set, obligations, invariants  # bash parses these for show too, then ignores them
    asyncio.run(_focus_show_async(sprint, lane, _fmt(json_out, md_out)))


__all__ = [
    "app",
    "LoopIterationOut",
    "LoopStatusOut",
    "LoopListItemOut",
    "FocusShowOut",
]
