"""``shepherd report`` — READ-ONLY markdown report renderer Typer sub-app.

Native port of ``skills/context/scripts/cmd_report.sh``: materializes
markdown views from canonical SQLite rows across ``discovery_findings``,
``audit_findings``, ``escalations`` (+ the ``v_escalations_open`` view),
and ``teammates``. Thin synchronous Typer commands over an async data
layer, exactly like :mod:`shepherd_cli.commands.deliverable` — Typer/Click
commands are called synchronously, but Tortoise ORM's query API is async,
so every command wraps exactly one ``asyncio.run`` around
``async with db.lifespan(): ...``.

Per the #198-wave port contract this module is deliberately
self-contained: its Pydantic output schemas and async query/render helpers
live INLINE here rather than in :mod:`shepherd_cli.schemas` /
:mod:`shepherd_cli.queries` (disjoint file ownership keeps parallel ports
from colliding on shared modules). It imports :mod:`shepherd_cli.db`
(Tortoise lifecycle + schema self-heal), :mod:`shepherd_cli.resolution`
(``resolve_db_path``), the pre-existing :class:`shepherd_cli.models.Teammate`
(read-only — NOT redeclared, per the COLLISION RULE), and the four new
mirror models in :mod:`shepherd_cli.models_report`.

BASH QUIRK MIRRORED DELIBERATELY: ``cmd_report.sh`` checks the registry DB
file exists BEFORE it even parses which report ``<kind>`` was requested —
so ``shctx report`` with no arguments, or any subcommand, all fail with
``ERR: registry DB not found at <path>`` (exit 1) on a project that has
never been ``init``'d, even before usage is shown. This module's root
callback performs that same check first, for every invocation, before any
subcommand-specific logic runs — see :func:`_default`.

Every subcommand's markdown body is built as a flat list of exact output
LINES (never pre-joined multi-line blobs) so nested composition (``close``
embeds the ``audit``, ``escalation --open-only``, and ``teammates`` bodies
verbatim, exactly as bash's ``close`` branch does by re-invoking
``cmd_report.sh`` as a subprocess three times) reproduces bash's blank-line
spacing byte-for-byte. See :func:`_lines_close` for the composition.
"""

from __future__ import annotations

import asyncio
import json
import os

import typer
from pydantic import BaseModel, ConfigDict

from shepherd_cli import db
from shepherd_cli.models import Teammate
from shepherd_cli.models_report import AuditFinding, DiscoveryFinding, Escalation, EscalationOpen
from shepherd_cli.resolution import resolve_db_path

app = typer.Typer(
    add_completion=False,
    help="Markdown reports over discovery/audit findings, escalations, and the teammate roster (read-only).",
)

#: Verbatim bash-parity usage text — ``usage()`` in ``cmd_report.sh``.
#: Printed to stdout (bash's plain ``cat`` heredoc, no stderr redirection)
#: both when a required flag is missing (exit 2) and for the bare
#: no-subcommand / ``help`` / ``-h`` case (exit 0).
_USAGE = (
    "shctx report discovery --run=<id> [--sprint=<branch>]\n"
    "shctx report audit --sprint=<branch> [--concern=<c>] [--severity=<s>]\n"
    "shctx report escalation [--open-only]\n"
    "shctx report close --sprint=<branch>\n"
    "shctx report teammates [--team=<name>] [--stale-mins=<n>]"
)

#: Bash's ``CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN
#: 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END`` from ``cmd_report.sh``'s
#: audit ``ORDER BY`` — an ``info`` (or any other/NULL) severity falls
#: through to the same ``ELSE 5`` bucket as everything unrecognized, so it
#: is deliberately NOT a key in this map; :func:`_severity_rank` returns 5
#: for any severity absent here.
_SEVERITY_RANK: dict[str, int] = {"critical": 1, "high": 2, "medium": 3, "low": 4}


def _severity_rank(severity: str) -> int:
    """Bash-parity rank for the audit ``ORDER BY CASE severity ...`` clause.

    Args:
        severity: The ``audit_findings.severity`` value.

    Returns:
        1 for ``critical`` through 4 for ``low``; 5 for ``info`` or any
        other value (bash's ``ELSE 5``).
    """
    return _SEVERITY_RANK.get(severity, 5)


# --------------------------------------------------------------------------
# --json output schemas — mirror exactly the columns bash SELECTs for each
# report kind, nothing more (from_attributes=True so a Tortoise row model
# validates directly).
# --------------------------------------------------------------------------


class DiscoveryFindingOut(BaseModel):
    """One ``discovery_findings`` row as emitted by ``report discovery --json``.

    Mirrors bash's ``SELECT section, title, body, sources FROM
    discovery_findings ...`` column projection exactly.

    Attributes:
        section: The finding's section label, or None (bash's markdown
            renderer falls back to ``"General"`` for display only — the
            JSON payload keeps the raw NULL).
        title: The finding's title.
        body: The finding's free-text body.
        sources: Raw JSON-array/object text of source references, or None.
    """

    model_config = ConfigDict(from_attributes=True)

    section: str | None
    title: str
    body: str
    sources: str | None


class AuditFindingOut(BaseModel):
    """One ``audit_findings`` row as emitted by ``report audit --json``.

    Mirrors bash's ``SELECT concern, severity, hypothesis, falsification,
    confidence, finding, gh_issue FROM audit_findings ...`` column
    projection exactly, in severity-then-created_at sorted order.

    Attributes:
        concern: The audit concern category (free text).
        severity: One of ``critical``/``high``/``medium``/``low``/``info``.
        hypothesis: The hypothesis under test.
        falsification: The falsification attempt described, or None.
        confidence: One of ``low``/``medium``/``high``, or None.
        finding: The resulting finding (free text).
        gh_issue: The GitHub issue number this finding was filed as, or
            None if never filed.
    """

    model_config = ConfigDict(from_attributes=True)

    concern: str
    severity: str
    hypothesis: str
    falsification: str | None
    confidence: str | None
    finding: str
    gh_issue: int | None


class EscalationOpenOut(BaseModel):
    """One ``v_escalations_open`` row as emitted by ``report escalation --open-only --json``.

    Mirrors bash's ``SELECT id, role, phase, question, raised_at FROM
    v_escalations_open;`` column projection exactly.

    Attributes:
        id: The escalation's primary key.
        role: The role that raised the escalation.
        phase: The phase it was raised in, or None.
        question: The escalation question text.
        raised_at: Epoch timestamp it was raised at (see
            :mod:`shepherd_cli.models_report` for the unit note).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    phase: str | None
    question: str
    raised_at: int


class EscalationOut(BaseModel):
    """One ``escalations`` row as emitted by ``report escalation --json`` (no ``--open-only``).

    Mirrors bash's ``SELECT id, role, question, raised_at, resolved_at
    FROM escalations ORDER BY raised_at DESC;`` column projection exactly.

    Attributes:
        id: The escalation's primary key.
        role: The role that raised the escalation.
        question: The escalation question text.
        raised_at: Epoch timestamp it was raised at.
        resolved_at: Epoch timestamp it was resolved at, or None if still
            open.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    question: str
    raised_at: int
    resolved_at: int | None


class TeammateReportOut(BaseModel):
    """One ``teammates`` row as emitted by ``report teammates --json``.

    Mirrors bash's ``SELECT teammate_name, agent_type, status,
    last_seen_at FROM teammates WHERE ... ORDER BY spawned_at DESC;``
    column projection exactly.

    Attributes:
        teammate_name: The teammate's name.
        agent_type: The teammate's agent type.
        status: The teammate's raw ``status`` column value.
        last_seen_at: Epoch-milliseconds of the last heartbeat.
    """

    model_config = ConfigDict(from_attributes=True)

    teammate_name: str
    agent_type: str
    status: str
    last_seen_at: int


class CloseReportOut(BaseModel):
    """The ``report close --json`` payload: the three nested sections as data.

    Not a bash construct directly (bash's ``close`` only ever produces
    markdown by re-invoking itself as a subprocess three times) — this is
    the structured equivalent, composed from the same three queries
    :func:`_lines_close`'s markdown rendering uses.

    Attributes:
        sprint: The ``--sprint`` this close report was generated for.
        audit_findings: Every audit finding for this sprint, in the same
            severity-then-created_at order the markdown section uses.
        open_escalations: Every currently-open escalation (bash's
            ``escalation --open-only``), in ``raised_at`` ascending order.
        teammates: Every teammate row (bash's unfiltered ``teammates``
            call), in ``spawned_at`` descending order.
    """

    model_config = ConfigDict(from_attributes=True)

    sprint: str
    audit_findings: list[AuditFindingOut]
    open_escalations: list[EscalationOpenOut]
    teammates: list[TeammateReportOut]


# --------------------------------------------------------------------------
# Async fetch helpers.
# --------------------------------------------------------------------------


async def _fetch_discovery(run: str, sprint: str | None) -> list[DiscoveryFinding]:
    """Fetch discovery findings for one run, bash-parity filtered and ordered.

    Args:
        run: The ``discovery_run`` id to filter on (required).
        sprint: When given, additionally filter on ``sprint_branch``.

    Returns:
        Matching rows ordered by ``section`` then ``created_at`` ascending
        (sqlite orders NULL ``section`` first in ascending order, matching
        bash's plain ``ORDER BY section, created_at`` with no NULL
        handling of its own).
    """
    query = DiscoveryFinding.filter(discovery_run=run)
    if sprint:
        query = query.filter(sprint_branch=sprint)
    return list(await query.order_by("section", "created_at"))


async def _fetch_audit(sprint: str, concern: str | None, severity: str | None) -> list[AuditFinding]:
    """Fetch audit findings for one sprint, bash-parity filtered and ordered.

    Args:
        sprint: The ``sprint_branch`` to filter on (required).
        concern: When given, additionally filter on ``concern``.
        severity: When given, additionally filter on ``severity``.

    Returns:
        Matching rows sorted by the bash ``CASE severity ...`` rank (see
        :func:`_severity_rank`) then ``created_at``, both ascending. Sorted
        in Python rather than SQL because sqlite's ORM layer here has no
        native ``CASE WHEN`` ordering expression; the query itself still
        does all the filtering.
    """
    query = AuditFinding.filter(sprint_branch=sprint)
    if concern:
        query = query.filter(concern=concern)
    if severity:
        query = query.filter(severity=severity)
    rows = list(await query)
    rows.sort(key=lambda row: (_severity_rank(row.severity), row.created_at))
    return rows


async def _fetch_escalations_open() -> list[EscalationOpen]:
    """Fetch every currently-open escalation.

    Returns:
        Rows from the ``v_escalations_open`` view, ordered by
        ``raised_at`` ascending (explicit ``order_by`` rather than relying
        on the view's own embedded ``ORDER BY`` — see
        :class:`shepherd_cli.models_report.EscalationOpen`'s docstring).
    """
    return list(await EscalationOpen.all().order_by("raised_at"))


async def _fetch_escalations_all() -> list[Escalation]:
    """Fetch every escalation, resolved or not.

    Returns:
        Every ``escalations`` row, ordered by ``raised_at`` descending
        (bash: ``ORDER BY raised_at DESC``).
    """
    return list(await Escalation.all().order_by("-raised_at"))


async def _fetch_teammates(team: str | None) -> list[Teammate]:
    """Fetch teammates, optionally scoped to one team.

    Args:
        team: When given, filter to this ``team_name`` only (bash: ``WHERE
            team_name='$team'``); when None, no filter (bash: ``WHERE
            1=1``).

    Returns:
        Matching rows ordered by ``spawned_at`` descending (bash: ``ORDER
        BY spawned_at DESC``).
    """
    query = Teammate.all()
    if team:
        query = query.filter(team_name=team)
    return list(await query.order_by("-spawned_at"))


# --------------------------------------------------------------------------
# Markdown line renderers — each returns the EXACT stdout lines bash's
# corresponding branch would echo, as a flat list (never pre-joined), so
# nested composition in _lines_close reproduces bash's blank-line spacing
# exactly (see module docstring).
# --------------------------------------------------------------------------


def _lines_discovery(run: str, sprint: str | None, rows: list[DiscoveryFinding]) -> list[str]:
    """Render the ``discovery`` report body as a flat list of output lines.

    Args:
        run: The ``--run`` value (echoed into the header).
        sprint: The ``--sprint`` value, or None (adds a ``Sprint:`` line
            when given).
        rows: The findings to render, already in display order.

    Returns:
        The exact lines ``cmd_report.sh``'s ``discovery`` branch would
        echo: a header (+ optional sprint line) then a blank line, then
        one block per finding (section/title header, blank, body,
        optional blank+sources line, trailing blank).
    """
    lines = [f"# Discovery report — run `{run}`"]
    if sprint:
        lines.append(f"Sprint: `{sprint}`")
    lines.append("")
    for row in rows:
        lines.append(f"## {row.section or 'General'} — {row.title}")
        lines.append("")
        lines.append(row.body)
        if row.sources:
            lines.append("")
            lines.append(f"_sources_: `{row.sources}`")
        lines.append("")
    return lines


def _lines_audit(sprint: str, rows: list[AuditFinding]) -> list[str]:
    """Render the ``audit`` report body as a flat list of output lines.

    Args:
        sprint: The ``--sprint`` value (echoed into the header).
        rows: The findings to render, already in display order.

    Returns:
        The exact lines ``cmd_report.sh``'s ``audit`` branch would echo: a
        header then a blank line, then one block per finding
        (severity/concern/hypothesis header, optional "(filed as #N)"
        line, blank, Finding line, optional blank+Falsification line,
        optional blank+Confidence line, trailing blank).
    """
    lines = [f"# Audit report — sprint `{sprint}`", ""]
    for row in rows:
        lines.append(f"### [{row.severity} / {row.concern}] {row.hypothesis}")
        if row.gh_issue is not None:
            lines.append(f"(filed as #{row.gh_issue})")
        lines.append("")
        lines.append(f"**Finding:** {row.finding}")
        if row.falsification:
            lines.append("")
            lines.append(f"**Falsification attempt:** {row.falsification}")
        if row.confidence:
            lines.append("")
            lines.append(f"**Confidence:** {row.confidence}")
        lines.append("")
    return lines


def _lines_escalation(
    open_only: bool, open_rows: list[EscalationOpen], all_rows: list[Escalation]
) -> list[str]:
    """Render the ``escalation`` report body as a flat list of output lines.

    Args:
        open_only: When True, render only ``open_rows`` (bash's
            ``--open-only`` branch, one bullet per row with a raised-at
            suffix). When False, render ``all_rows`` instead (every
            escalation, OPEN/RESOLVED annotated, no raised-at suffix).
        open_rows: Open escalations (from :func:`_fetch_escalations_open`),
            used only when ``open_only`` is True.
        all_rows: Every escalation (from :func:`_fetch_escalations_all`),
            used only when ``open_only`` is False.

    Returns:
        The exact lines ``cmd_report.sh``'s ``escalation`` branch would
        echo: a header then a blank line, then one bullet line per row (no
        trailing blank line after the list, matching bash exactly).
    """
    lines = ["# Escalations", ""]
    if open_only:
        for row in open_rows:
            phase = row.phase or "?"
            lines.append(f"- **#{row.id} [{row.role}/{phase}]** {row.question} (raised: {row.raised_at})")
    else:
        for row in all_rows:
            status = "RESOLVED" if row.resolved_at is not None else "OPEN"
            lines.append(f"- **#{row.id} [{row.role}/{status}]** {row.question}")
    return lines


def _lines_teammates(rows: list[Teammate]) -> list[str]:
    """Render the ``teammates`` report body as a flat list of output lines.

    Args:
        rows: The teammates to render, already in display order.

    Returns:
        The exact lines ``cmd_report.sh``'s ``teammates`` branch would
        echo: a header then a blank line, then one bullet line per
        teammate (no trailing blank line, matching bash exactly).
    """
    lines = ["# Teammates", ""]
    for row in rows:
        lines.append(f"- **{row.teammate_name}** ({row.agent_type}) — status: {row.status} — last seen: {row.last_seen_at}")
    return lines


def _lines_close(
    sprint: str,
    audit_rows: list[AuditFinding],
    open_rows: list[EscalationOpen],
    teammate_rows: list[Teammate],
) -> list[str]:
    """Render the ``close`` composite report as a flat list of output lines.

    Bash-parity with ``cmd_report.sh``'s ``close`` branch, which literally
    re-invokes itself as a subprocess three times
    (``"$HERE/cmd_report.sh" audit --sprint="$sprint"``, ``escalation
    --open-only``, ``teammates``) and lets each subprocess's full stdout
    (including its own ``# ...`` header) flow straight into the combined
    output, separated by the close script's own ``echo`` blank lines. This
    function reproduces that byte-for-byte by splicing the three other
    renderers' own line lists in directly (each of which already starts
    with its own header line) rather than re-deriving a merged format.

    Args:
        sprint: The ``--sprint`` value (echoed into the header and passed
            through to the embedded audit report).
        audit_rows: Rows for the embedded audit section (already filtered
            to this sprint via :func:`_fetch_audit`, with no
            concern/severity filter — bash's ``close`` branch calls
            ``audit --sprint="$sprint"`` with no other flags).
        open_rows: Rows for the embedded open-escalations section (from
            :func:`_fetch_escalations_open`).
        teammate_rows: Rows for the embedded teammate-roster section (from
            :func:`_fetch_teammates` with no team filter — bash's
            ``close`` branch calls plain ``teammates`` with no flags).

    Returns:
        The exact lines ``cmd_report.sh``'s ``close`` branch would print.
    """
    lines = [f"# Close report — `{sprint}`", ""]
    lines.append("## Audit findings")
    lines.extend(_lines_audit(sprint, audit_rows))
    lines.append("")
    lines.append("## Open escalations")
    lines.extend(_lines_escalation(True, open_rows, []))
    lines.append("")
    lines.append("## Teammate roster")
    lines.extend(_lines_teammates(teammate_rows))
    return lines


# --------------------------------------------------------------------------
# Root callback — bash-parity DB-existence check (runs for EVERY
# invocation, before any subcommand) + no-subcommand usage.
# --------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Check the registry DB exists, then show usage if no subcommand was given.

    Bash-parity with ``cmd_report.sh``'s very first statement (before the
    ``usage()`` definition and before ``$1`` is even parsed):
    ``[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2;
    exit 1; }`` — this runs unconditionally, ahead of every subcommand
    including the no-subcommand/``help`` case, so a project that has never
    been ``init``'d fails the same way no matter what ``shctx report ...``
    invocation was attempted. Typer/Click callbacks run before the chosen
    subcommand's body, so putting this check here covers every subcommand
    in this app automatically.

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only
            when ``shepherd report`` is run with no subcommand.

    Raises:
        typer.Exit: code 1 (stderr message) if the resolved DB file does
            not exist. code 0 (usage on stdout) if no subcommand was given
            and the DB check passed.
    """
    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo(f"ERR: registry DB not found at {db_path}", err=True)
        raise typer.Exit(code=1)
    if ctx.invoked_subcommand is None:
        typer.echo(_USAGE)
        raise typer.Exit(code=0)


@app.command("help")
def help_cmd() -> None:
    """Print usage and exit 0 — bash-parity with the explicit ``help`` case.

    ``cmd_report.sh``'s ``case`` statement matches ``""|help|--help|-h``
    all to the same ``usage()`` (exit 0) branch; :func:`_default` already
    covers the bare no-subcommand case, this command covers the literal
    ``shctx report help`` invocation.

    Raises:
        typer.Exit: code 0, after printing usage.
    """
    typer.echo(_USAGE)
    raise typer.Exit(code=0)


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


async def _discovery_async(run: str, sprint: str | None, json_out: bool) -> None:
    """Fetch and print the discovery report.

    Args:
        run: The ``--run`` value (validated non-empty by the caller).
        sprint: The ``--sprint`` value, or None.
        json_out: When True, print a JSON array of :class:`DiscoveryFindingOut`
            instead of the markdown report.
    """
    async with db.lifespan():
        rows = await _fetch_discovery(run, sprint)
    if json_out:
        views = [DiscoveryFindingOut.model_validate(row) for row in rows]
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
    else:
        typer.echo("\n".join(_lines_discovery(run, sprint, rows)))


@app.command()
def discovery(
    run: str | None = typer.Option(None, "--run", help="The discovery_run id to report on (required)."),
    sprint: str | None = typer.Option(None, "--sprint", help="Restrict to this sprint_branch."),
    json_out: bool = typer.Option(
        False, "--json", help="Emit a JSON array of DiscoveryFindingOut instead of the markdown report."
    ),
) -> None:
    """Render the discovery-findings markdown report for one run.

    Args:
        run: Required (validated after parsing, not via Typer's
            ``required=True``, so bash's exact usage-on-stdout/exit-2
            contract is reproduced instead of Click's own required-option
            error).
        sprint: Optional additional filter on ``sprint_branch``.
        json_out: Emit JSON instead of markdown.

    Raises:
        typer.Exit: code 2 (usage text on stdout, bash parity) if ``run``
            is missing or empty.
    """
    if not run:
        typer.echo(_USAGE)
        raise typer.Exit(code=2)
    asyncio.run(_discovery_async(run=run, sprint=sprint, json_out=json_out))


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------


async def _audit_async(sprint: str, concern: str | None, severity: str | None, json_out: bool) -> None:
    """Fetch and print the audit report.

    Args:
        sprint: The ``--sprint`` value (validated non-empty by the caller).
        concern: The ``--concern`` value, or None.
        severity: The ``--severity`` value, or None.
        json_out: When True, print a JSON array of :class:`AuditFindingOut`
            instead of the markdown report.
    """
    async with db.lifespan():
        rows = await _fetch_audit(sprint, concern, severity)
    if json_out:
        views = [AuditFindingOut.model_validate(row) for row in rows]
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
    else:
        typer.echo("\n".join(_lines_audit(sprint, rows)))


@app.command()
def audit(
    sprint: str | None = typer.Option(None, "--sprint", help="The sprint_branch to report on (required)."),
    concern: str | None = typer.Option(None, "--concern", help="Restrict to this concern."),
    severity: str | None = typer.Option(None, "--severity", help="Restrict to this severity."),
    json_out: bool = typer.Option(
        False, "--json", help="Emit a JSON array of AuditFindingOut instead of the markdown report."
    ),
) -> None:
    """Render the audit-findings markdown report for one sprint.

    Args:
        sprint: Required (validated after parsing — same usage/exit-2
            contract as ``discovery``'s ``--run``).
        concern: Optional additional filter on ``concern``.
        severity: Optional additional filter on ``severity``.
        json_out: Emit JSON instead of markdown.

    Raises:
        typer.Exit: code 2 (usage text on stdout, bash parity) if
            ``sprint`` is missing or empty.
    """
    if not sprint:
        typer.echo(_USAGE)
        raise typer.Exit(code=2)
    asyncio.run(_audit_async(sprint=sprint, concern=concern, severity=severity, json_out=json_out))


# --------------------------------------------------------------------------
# escalation
# --------------------------------------------------------------------------


async def _escalation_async(open_only: bool, json_out: bool) -> None:
    """Fetch and print the escalations report.

    Args:
        open_only: When True, report only currently-open escalations (the
            ``v_escalations_open`` view); when False, report every
            escalation with an OPEN/RESOLVED annotation.
        json_out: When True, print a JSON array (:class:`EscalationOpenOut`
            rows if ``open_only``, else :class:`EscalationOut` rows)
            instead of the markdown report.
    """
    async with db.lifespan():
        if open_only:
            open_rows = await _fetch_escalations_open()
            all_rows: list[Escalation] = []
        else:
            open_rows = []
            all_rows = await _fetch_escalations_all()
    if json_out:
        if open_only:
            open_views = [EscalationOpenOut.model_validate(row) for row in open_rows]
            typer.echo(json.dumps([view.model_dump(mode="json") for view in open_views], indent=2))
        else:
            all_views = [EscalationOut.model_validate(row) for row in all_rows]
            typer.echo(json.dumps([view.model_dump(mode="json") for view in all_views], indent=2))
    else:
        typer.echo("\n".join(_lines_escalation(open_only, open_rows, all_rows)))


@app.command()
def escalation(
    open_only: bool = typer.Option(
        False, "--open-only", help="Report only currently-open escalations (v_escalations_open)."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit a JSON array instead of the markdown report."
    ),
) -> None:
    """Render the escalations markdown report.

    Args:
        open_only: Restrict to currently-open escalations only.
        json_out: Emit JSON instead of markdown.
    """
    asyncio.run(_escalation_async(open_only=open_only, json_out=json_out))


# --------------------------------------------------------------------------
# teammates
# --------------------------------------------------------------------------


async def _teammates_async(team: str | None, json_out: bool) -> None:
    """Fetch and print the teammate roster report.

    Args:
        team: The ``--team`` value, or None for every team.
        json_out: When True, print a JSON array of :class:`TeammateReportOut`
            instead of the markdown report.
    """
    async with db.lifespan():
        rows = await _fetch_teammates(team)
    if json_out:
        views = [TeammateReportOut.model_validate(row) for row in rows]
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
    else:
        typer.echo("\n".join(_lines_teammates(rows)))


@app.command()
def teammates(
    team: str | None = typer.Option(None, "--team", help="Restrict to this team_name."),
    stale_mins: int = typer.Option(
        5,
        "--stale-mins",
        help="Accepted for bash-CLI parity; has no effect (cmd_report.sh parses but never uses this flag either).",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit a JSON array of TeammateReportOut instead of the markdown report."
    ),
) -> None:
    """Render the teammate-roster markdown report.

    Args:
        team: Optional filter on ``team_name``.
        stale_mins: Parsed for bash-CLI parity only — ``cmd_report.sh``'s
            ``teammates`` branch accepts ``--stale-mins`` but never
            references the variable it sets, so this port mirrors that
            dead flag exactly rather than "fixing" it into having an
            effect bash never had.
        json_out: Emit JSON instead of markdown.
    """
    del stale_mins  # bash-parity dead flag — see docstring.
    asyncio.run(_teammates_async(team=team, json_out=json_out))


# --------------------------------------------------------------------------
# close
# --------------------------------------------------------------------------


async def _close_async(sprint: str, json_out: bool) -> None:
    """Fetch and print the composite close report.

    Args:
        sprint: The ``--sprint`` value (validated non-empty by the caller).
        json_out: When True, print a :class:`CloseReportOut` JSON object
            instead of the composed markdown report.
    """
    async with db.lifespan():
        audit_rows = await _fetch_audit(sprint, None, None)
        open_rows = await _fetch_escalations_open()
        teammate_rows = await _fetch_teammates(None)
    if json_out:
        payload = CloseReportOut(
            sprint=sprint,
            audit_findings=[AuditFindingOut.model_validate(row) for row in audit_rows],
            open_escalations=[EscalationOpenOut.model_validate(row) for row in open_rows],
            teammates=[TeammateReportOut.model_validate(row) for row in teammate_rows],
        )
        typer.echo(payload.model_dump_json(indent=2))
    else:
        typer.echo("\n".join(_lines_close(sprint, audit_rows, open_rows, teammate_rows)))


@app.command()
def close(
    sprint: str | None = typer.Option(None, "--sprint", help="The sprint_branch to close out (required)."),
    json_out: bool = typer.Option(
        False, "--json", help="Emit a CloseReportOut JSON object instead of the composed markdown report."
    ),
) -> None:
    """Render the composite close report: audit findings + open escalations + teammate roster.

    Args:
        sprint: Required (validated after parsing — same usage/exit-2
            contract as ``audit``'s ``--sprint``).
        json_out: Emit JSON instead of markdown.

    Raises:
        typer.Exit: code 2 (usage text on stdout, bash parity) if
            ``sprint`` is missing or empty.
    """
    if not sprint:
        typer.echo(_USAGE)
        raise typer.Exit(code=2)
    asyncio.run(_close_async(sprint=sprint, json_out=json_out))


__all__ = [
    "app",
    "DiscoveryFindingOut",
    "AuditFindingOut",
    "EscalationOpenOut",
    "EscalationOut",
    "TeammateReportOut",
    "CloseReportOut",
]
