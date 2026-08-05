"""Ledger custody + step/verdict join — deterministic core (v6.4.3, #261/#262).

Codifies ``auditor-verdicts.txt``, a field convention from live sprints
(FL03/axiom) that the plugin never wrote down anywhere — precisely why both
#261 (custody: which physical copy is THE ledger) and #262 (nothing ever
joins the ledger against the lane plans, so it can show what IS recorded but
never what is MISSING) were possible. See
``skills/context/.../v643-ledger-spec.md`` for the full contract; this
module is spec section 5's pure-function core, unchanged in shape from that
spec's function list.

Pure functions only: no typer, no ``sys.exit``, no subprocess, no database.
The only IO this module performs is reading a lane-plan file it is handed a
path to (:func:`enumerate_plan_steps`) and resolving a path via
``shepherd_cli.resolution``/``shepherd_cli.models_run`` (:func:`ledger_path`)
— never writing, never enumerating git worktrees itself, never printing.
``commands/run.py`` (a follow-on change, NOT this module) stays a thin typer
wrapper: it enumerates ``git worktree list --porcelain``, reads the files
this module is handed as text, and turns this module's return values into
stdout/stderr/exit codes. That split is the CLAUDE.md latent-vs-deterministic
rule made concrete: the join is same-input-same-output, so it is a tested
pure function, never prose an agent re-derives on every run.

LEDGER LINE GRAMMAR (spec section 2)
=====================================
One verdict per line, POSITIONAL fields, whitespace-separated::

    <lane> <scope> <verdict> [free prose ...]

``<verdict>`` is field 3 ONLY. Two field incidents shaped this module and
each has an explicitly-named regression test in ``tests/test_verdicts.py``:

- A confidently-wrong implementation once grepped ``PASS|REDO|FAIL``
  anywhere on the line instead of reading field 3 positionally. A real PASS
  row's free-form prose read ``"REDO iter 2 cleared"`` — a grep-based
  reader misreads that row as REDO. :func:`parse_ledger_line` tokenizes the
  line and validates ONLY the third token against the verdict vocabulary;
  it never substring-searches the raw line.
- The LAST matching row wins, never the first. A cleared ``REDO -> PASS``
  loop is the NORMAL shape of a lane that failed a step, was told to redo
  it, and passed on retry — a first-wins reader reports that step as still
  failing forever. :func:`resolve_step_verdict` (and :func:`join`, which
  calls it once per step) always take the LAST row in file order among a
  step's matching rows.

STEP-ID JOIN (spec section 4, #262)
=====================================
Reading the ledger top-to-bottom shows what verdicts exist; it cannot show
what is MISSING, because there is nothing to notice the absence against.
:func:`enumerate_plan_steps` reads the lane plans (the independent source of
truth for which steps exist) and :func:`join` matches each enumerated step
against the parsed ledger rows, producing four independent finding
categories: ``NO-VERDICT`` (a real step with zero matching rows — the #262
headline case), ``UNRESOLVED-VERDICT`` (a step whose LAST verdict is REDO or
FAIL), ``ORPHAN-VERDICT`` (a ledger row naming a lane/wave/step in NO lane
plan — the reverse direction, and the exact shape of a second #262 field
incident: a step minted in the task list but never written into any lane
plan), and ``MALFORMED-ROW`` (a ledger line :func:`parse_ledger` could not
parse — reported, never silently dropped, never crashed on).

Sub-step rollup (``w2-s1g2``, ``w2-s1b`` both resolve against parent step
``w2-s1``) needs no special-casing at match time: :func:`parse_ledger_line`
already discards a step token's trailing suffix at PARSE time, keeping only
the parent step number, so a sub-step row and its parent step's exact-match
row are indistinguishable once parsed — both simply have ``LedgerRow.step``
equal to the parent step number.

WORKTREE LEDGER CUSTODY (spec section 1)
==========================================
:func:`ledger_path` is the ONE way to compute the canonical, absolute,
primary-checkout path to a run's ledger — delegating to
``shepherd_cli.models_run.run_dir`` (itself built on
``shepherd_cli.resolution.resolve_workdir`` /
``resolve_repo_root``, which already resolves to the MAIN worktree via
``git rev-parse --git-common-dir`` even when called from a linked worktree,
#221/#231) rather than composing ``.shepherd/runs/<run>/...`` as a plain
relative path — which is reachable, and WRONG, from inside every linked
worktree as an Nth physical copy nothing distinguishes.

:func:`compare_worktree_ledgers` is the mechanical divergence check
(``shepherd run ledger check``'s engine, not built here) at its purest: it
takes already-read ledger TEXT (never touches git or the filesystem itself)
and reports every row a worktree copy holds that the primary lacks. A
worktree that is merely BEHIND (primary has rows the worktree lacks — every
lane's normal state between merges) is never flagged; only a worktree AHEAD
of the primary on some row is a finding, because merging that worktree's
branch could silently drop a sibling lane's verdict row that only the
worktree's copy ever recorded.
"""

from __future__ import annotations

import glob
import os
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from shepherd_cli.models_run import run_dir as _resolve_run_dir

#: The ledger's fixed filename within a run directory (spec section 1).
LEDGER_FILENAME = "auditor-verdicts.txt"

#: Closed verdict vocabulary (spec section 2), in the order a lane normally
#: moves through them: a step earns a REDO before it clears to PASS, or
#: fails outright.
Verdict = Literal["PASS", "REDO", "FAIL"]
VERDICTS: tuple[Verdict, ...] = ("PASS", "REDO", "FAIL")

#: A verdict that leaves a step NOT resolved clean (spec section 4.4,
#: UNRESOLVED-VERDICT). PASS is deliberately absent from this set.
_UNRESOLVED_VERDICTS: frozenset[str] = frozenset({"REDO", "FAIL"})

#: Closed finding-category vocabulary (spec section 4.4).
FindingKind = Literal["NO-VERDICT", "UNRESOLVED-VERDICT", "ORPHAN-VERDICT", "MALFORMED-ROW"]
FINDING_KINDS: tuple[FindingKind, ...] = (
    "NO-VERDICT",
    "UNRESOLVED-VERDICT",
    "ORPHAN-VERDICT",
    "MALFORMED-ROW",
)

# --------------------------------------------------------------------------
# Ledger line grammar (spec section 2). Compiled once at import time.
# --------------------------------------------------------------------------
#: ``<lane>`` — ``L<digits>``, case-insensitive. Whole-token match only —
#: this is validated against an already whitespace-split token, never
#: searched for within the raw line.
_LANE_RE = re.compile(r"[Ll](?P<num>\d+)")

#: ``<verdict>`` — one of PASS/REDO/FAIL, case-insensitive, whole-token
#: match only. Validated against field 3 alone (see :func:`parse_ledger_line`)
#: — NEVER searched for anywhere else on the line; see the module docstring.
_VERDICT_RE = re.compile(r"PASS|REDO|FAIL", re.IGNORECASE)

#: ``<scope>`` — a bare wave (``w3``: ``step`` group is None, subsumes every
#: step of that lane in that wave), a step (``w3-s1``), or a sub-step
#: (``w2-s1g2``, ``w2-s1b``: anything trailing the step's digits). The
#: trailing ``suffix`` group is captured but deliberately unused after
#: parsing — a sub-step rolls up to its parent step by simply not being
#: distinguished from an exact step match; see the module docstring's
#: "Sub-step rollup" note.
_SCOPE_RE = re.compile(r"[Ww](?P<wave>\d+)(?:-[Ss](?P<step>\d+)(?P<suffix>.*))?", re.IGNORECASE)

#: ``W<digits>-L<digits>-S<digits>`` — the plan-file spelling of a step id
#: (spec section 3), e.g. ``W3-L4-S1``, typically as a
#: ``### W3-L4-S1: title`` heading (``templates/lane-plan.md.j2``).
_PLAN_STEP_ID_RE = re.compile(r"\bW(?P<wave>\d+)-L(?P<lane>\d+)-S(?P<step>\d+)\b", re.IGNORECASE)


# --------------------------------------------------------------------------
# Value types.
# --------------------------------------------------------------------------
class LedgerRow(BaseModel):
    """One successfully parsed ``auditor-verdicts.txt`` line (spec section 2).

    Frozen (immutable, hashable) — a parsed row is a fact about one line of
    a specific ledger read, never mutated after :func:`parse_ledger_line`
    builds it.
    """

    model_config = ConfigDict(frozen=True)

    lane: str  #: Normalized lane spelling, e.g. ``"L4"`` (always uppercase ``L``).
    lane_num: int  #: The same lane, as an int — what step-id matching actually joins on.
    scope: str  #: The original scope token, lowercased (e.g. ``"w3-s1g2"``), for display.
    wave: int  #: The scope's wave number.
    step: int | None  #: The scope's step number; None for a bare-wave row (``w3``).
    verdict: Verdict  #: Normalized to uppercase.
    prose: str  #: Free-form text after the verdict field. ``""`` when the row carries none.
    line_no: int  #: 1-based source line number within the ledger text. 0 when unset
    #: (a :class:`LedgerRow` built directly by a caller of
    #: :func:`parse_ledger_line`, outside of :func:`parse_ledger`'s
    #: line-numbered loop, never learns its own line number).
    raw: str  #: The original, unmodified source line (no trailing newline).


class MalformedRow(BaseModel):
    """One ``auditor-verdicts.txt`` line that failed the grammar (spec section 2).

    Reported, never silently dropped and never a crash — see
    :func:`parse_ledger`.
    """

    model_config = ConfigDict(frozen=True)

    line_no: int  #: 1-based source line number.
    raw: str  #: The original, unmodified source line.
    reason: str  #: A short, specific diagnosis (which field failed, and why).


class StepId(BaseModel):
    """One step identifier, join key between lane plans and the ledger (spec section 3).

    ``W{wave}-L{lane}-S{step}`` (plan spelling) <-> ``L{lane} w{wave}-s{step}``
    (ledger spelling) name the SAME step; this type is the shared, spelling-
    independent representation both :func:`enumerate_plan_steps` and
    :func:`parse_ledger_line` reduce down to.
    """

    model_config = ConfigDict(frozen=True)

    wave: int
    lane: int
    step: int

    @property
    def plan_id(self) -> str:
        """The plan-file spelling, e.g. ``"W3-L4-S1"``."""
        return f"W{self.wave}-L{self.lane}-S{self.step}"

    @property
    def ledger_scope(self) -> str:
        """The ledger scope-token spelling of an EXACT match, e.g. ``"w3-s1"``."""
        return f"w{self.wave}-s{self.step}"


class Finding(BaseModel):
    """One join finding (spec section 4.4) — always exactly one of :data:`FINDING_KINDS`."""

    model_config = ConfigDict(frozen=True)

    kind: FindingKind
    detail: str  #: Human-readable one-line description.
    step: str | None = None  #: Plan-spelling step id, when the finding is step-scoped.
    line_no: int | None = None  #: Source ledger line, when the finding is row-scoped.
    raw: str | None = None  #: The row's original source line, when row-scoped.


class StepResult(BaseModel):
    """One row of the per-step ``step verdict source-line`` table (spec section 4.5)."""

    model_config = ConfigDict(frozen=True)

    step: str  #: Plan-spelling step id, e.g. ``"W3-L4-S1"``.
    verdict: Verdict | None  #: None when the step has zero matching ledger rows.
    line_no: int | None  #: The winning row's source line; None when ``verdict`` is None.
    raw: str | None  #: The winning row's original source line; None when ``verdict`` is None.


class JoinResult(BaseModel):
    """:func:`join`'s full result: the per-step table plus every finding."""

    model_config = ConfigDict(frozen=True)

    steps: list[StepResult]
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        """True iff every step resolved clean and no finding of any kind fired.

        The pure-function equivalent of ``shepherd run wave verify``'s exit
        0 (True here) vs exit 6 (False here, findings present) — the CLI
        wrapper maps this directly to its exit code and never re-derives
        the "clean" condition itself.
        """
        return not self.findings


class Divergence(BaseModel):
    """One row a linked worktree's ledger copy holds that the primary lacks (spec section 1.2)."""

    model_config = ConfigDict(frozen=True)

    worktree: str  #: Whichever label/path the caller used to key its ``worktrees`` mapping.
    row: str  #: The normalized row text (spec section 1.2: trailing-whitespace-stripped).


# --------------------------------------------------------------------------
# Ledger line grammar.
# --------------------------------------------------------------------------
def parse_ledger_line(line: str) -> LedgerRow | None:
    """Parse one ``auditor-verdicts.txt`` line into a :class:`LedgerRow`.

    POSITIONAL parsing only (spec section 2): the line is whitespace-split
    into at most 4 tokens (``lane``, ``scope``, ``verdict``, then everything
    remaining as free prose); each of the first three tokens is validated
    against ITS OWN vocabulary alone. The verdict is read from token 3 and
    nowhere else — this function never substring-searches or greps the raw
    line for ``PASS``/``REDO``/``FAIL``, which is exactly what would
    misparse a PASS row whose prose happens to contain the word "REDO" (a
    real field incident; see the module docstring).

    Args:
        line: One line of ledger text (with or without a trailing newline;
            leading/trailing whitespace is stripped before parsing).

    Returns:
        The parsed row, or None for BOTH a comment/blank line AND a line
        that does not match the grammar — this function alone cannot tell
        those two apart from its return value. A caller that needs the
        distinction (comment: silently skip; malformed: report) should use
        :func:`parse_ledger`, whose ``(rows, malformed)`` return makes it
        explicit. ``line_no`` on the returned row is always 0 (this
        function sees one line in isolation, never its position in a
        larger text) — :func:`parse_ledger` fills it in.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    parts = stripped.split(None, 3)
    if len(parts) < 3:
        return None

    lane_token, scope_token, verdict_token = parts[0], parts[1], parts[2]
    prose = parts[3] if len(parts) > 3 else ""

    lane_match = _LANE_RE.fullmatch(lane_token)
    if lane_match is None:
        return None
    lane_num = int(lane_match.group("num"))

    verdict_match = _VERDICT_RE.fullmatch(verdict_token)
    if verdict_match is None:
        return None
    verdict = verdict_match.group(0).upper()

    scope_match = _SCOPE_RE.fullmatch(scope_token)
    if scope_match is None:
        return None
    wave = int(scope_match.group("wave"))
    step_group = scope_match.group("step")
    step = int(step_group) if step_group is not None else None

    return LedgerRow(
        lane=f"L{lane_num}",
        lane_num=lane_num,
        scope=scope_token.lower(),
        wave=wave,
        step=step,
        verdict=verdict,  # type: ignore[arg-type]  # already validated against VERDICTS above
        prose=prose,
        line_no=0,
        raw=line,
    )


def _malformed_reason(raw: str) -> str:
    """A short, specific diagnosis for a line :func:`parse_ledger_line` rejected.

    Re-walks the same tokenizing/validation :func:`parse_ledger_line`
    itself performs, but returns a description instead of ``None`` — kept
    as a deliberate second pass (rather than threading a reason string
    through ``parse_ledger_line``'s single ``LedgerRow | None`` return)
    so that function's public contract stays exactly the spec's declared
    shape, while :func:`parse_ledger`'s ``MALFORMED-ROW`` findings still
    stay actionable instead of a bare "didn't parse".

    Args:
        raw: The original line text. Only ever called on a line that is
            neither blank nor a comment and for which
            ``parse_ledger_line(raw) is None`` (see :func:`parse_ledger`).

    Returns:
        A one-line, human-readable diagnosis of which field failed.
    """
    parts = raw.strip().split(None, 3)
    if len(parts) < 3:
        return "fewer than 3 fields (need: lane scope verdict [prose])"
    lane_token, scope_token, verdict_token = parts[0], parts[1], parts[2]
    if _LANE_RE.fullmatch(lane_token) is None:
        return f"invalid lane token {lane_token!r} (expected L<digits>)"
    if _VERDICT_RE.fullmatch(verdict_token) is None:
        return f"invalid verdict token {verdict_token!r} (expected PASS|REDO|FAIL)"
    if _SCOPE_RE.fullmatch(scope_token) is None:
        return f"invalid scope token {scope_token!r} (expected w<digits> or w<digits>-s<digits>[suffix])"
    return "does not match the ledger grammar"  # defensive fallback; unreachable in practice


def parse_ledger(text: str) -> tuple[list[LedgerRow], list[MalformedRow]]:
    """Parse a full ``auditor-verdicts.txt``'s text into rows + malformed lines.

    Blank lines and lines whose first non-space character is ``#`` are
    comments: skipped entirely, never counted as malformed (spec section
    2). Every other line is parsed via :func:`parse_ledger_line`; a line
    that function rejects becomes a :class:`MalformedRow` (reported, never
    silently dropped, never crashed on) rather than raising or vanishing.

    Args:
        text: The full ledger file's text.

    Returns:
        ``(rows, malformed)`` — parsed rows in file order (each with
        ``line_no`` set to its 1-based source line), and malformed lines
        in file order.
    """
    rows: list[LedgerRow] = []
    malformed: list[MalformedRow] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        row = parse_ledger_line(raw)
        if row is None:
            malformed.append(MalformedRow(line_no=line_no, raw=raw, reason=_malformed_reason(raw)))
            continue
        rows.append(row.model_copy(update={"line_no": line_no}))
    return rows, malformed


# --------------------------------------------------------------------------
# Lane-plan step enumeration (spec section 3).
# --------------------------------------------------------------------------
def enumerate_plan_steps(run_dir: str) -> list[StepId]:
    """Enumerate every step id declared across a run's lane plans.

    Reads ``{run_dir}/lanes/*/plan.md`` (sorted by lane directory name for
    determinism) and regex-scans each file's whole text for
    ``W<digits>-L<digits>-S<digits>`` tokens (spec section 3) — a step
    normally appears as a ``### W3-L4-S1: title`` heading, but this
    enumerates every occurrence anywhere in the file, not just headings.
    Deduplicates globally (a step id repeated within or across lane plan
    files is listed once) and preserves FIRST-SEEN order.

    Args:
        run_dir: The run's directory (e.g. ``models_run.run_dir(run,
            workdir)``) — this function does not resolve it itself.

    Returns:
        Every distinct step id, first-seen order.

    Raises:
        FileNotFoundError: ``{run_dir}/lanes`` does not exist — the #262
            "run or lane-plan directory missing" case a CLI wrapper maps
            to exit 5.
    """
    lanes_dir = os.path.join(run_dir, "lanes")
    if not os.path.isdir(lanes_dir):
        raise FileNotFoundError(f"no lane-plan directory: {lanes_dir}")

    seen: set[tuple[int, int, int]] = set()
    steps: list[StepId] = []
    for plan_path in sorted(glob.glob(os.path.join(lanes_dir, "*", "plan.md"))):
        with open(plan_path, "r", encoding="utf-8") as handle:
            text = handle.read()
        for match in _PLAN_STEP_ID_RE.finditer(text):
            key = (int(match.group("wave")), int(match.group("lane")), int(match.group("step")))
            if key in seen:
                continue
            seen.add(key)
            steps.append(StepId(wave=key[0], lane=key[1], step=key[2]))
    return steps


# --------------------------------------------------------------------------
# Step <-> ledger-row resolution (spec section 4.3) + the full join (4.4/4.5).
# --------------------------------------------------------------------------
def _last_matching_row(step: StepId, rows: Sequence[LedgerRow]) -> LedgerRow | None:
    """The LAST row in ``rows`` (file order) that resolves ``step`` (spec section 4.3).

    A row matches when its lane and wave equal ``step``'s, and it is
    either a bare-wave row (``row.step is None`` — subsumes every step of
    that lane in that wave) or names ``step``'s exact step number.
    Sub-step rows (``w2-s1g2``) need no separate branch here: they already
    have ``row.step`` set to the PARENT step number by
    :func:`parse_ledger_line`, so they satisfy the exact-step branch
    directly — see the module docstring's "Sub-step rollup" note.

    Args:
        step: The step to resolve.
        rows: Parsed ledger rows, in file order.

    Returns:
        The last matching row, or None if no row matches at all (the
        #262 ``NO-VERDICT`` case).
    """
    match: LedgerRow | None = None
    for row in rows:
        if row.lane_num != step.lane or row.wave != step.wave:
            continue
        if row.step is not None and row.step != step.step:
            continue
        match = row  # last-wins: every later match overwrites the previous one.
    return match


def resolve_step_verdict(step: StepId, rows: Sequence[LedgerRow]) -> Verdict | None:
    """One step's resolved verdict: the LAST matching ledger row's verdict.

    Never the first. A cleared ``REDO -> PASS`` loop is the normal shape of
    a step that failed once and passed on retry; a first-wins reader would
    report that step as still failing. See the module docstring and
    :func:`_last_matching_row`.

    Args:
        step: The step to resolve.
        rows: Parsed ledger rows, in file order.

    Returns:
        The winning row's verdict, or None when no row matches at all.
    """
    winner = _last_matching_row(step, rows)
    return winner.verdict if winner is not None else None


def join(
    steps: Sequence[StepId],
    rows: Sequence[LedgerRow],
    *,
    malformed: Sequence[MalformedRow] = (),
) -> JoinResult:
    """The step/ledger join (spec section 4): what the ledger alone cannot show.

    For every enumerated step, resolves its last-wins verdict
    (:func:`resolve_step_verdict`) and records a ``NO-VERDICT`` finding
    (zero matching rows) or an ``UNRESOLVED-VERDICT`` finding (last verdict
    is REDO or FAIL) as appropriate. Separately, every well-formed row
    naming a lane/wave/step that matches NO enumerated step becomes an
    ``ORPHAN-VERDICT`` finding — the reverse direction, catching a step
    that was minted in a task list but never written into any lane plan. A
    bare-wave row (``w3``) is an orphan only when its lane has NO steps in
    that wave at all; it is never orphaned merely for not matching one
    particular step, since a bare-wave row legitimately subsumes every
    step of that lane in that wave. ``malformed`` (typically
    :func:`parse_ledger`'s second return value) is folded in verbatim as
    ``MALFORMED-ROW`` findings, so a single :class:`JoinResult` carries
    every finding category from spec section 4.4 in one place — pass
    nothing (the default, an empty tuple) to get the step-based findings
    alone.

    Args:
        steps: Every step to check for a verdict (e.g.
            :func:`enumerate_plan_steps`'s return, optionally filtered to
            one wave by the caller).
        rows: Parsed, well-formed ledger rows (e.g. :func:`parse_ledger`'s
            first return value).
        malformed: Malformed ledger lines to fold in as ``MALFORMED-ROW``
            findings (e.g. :func:`parse_ledger`'s second return value).
            Defaults to none.

    Returns:
        The per-step table plus every finding, in this fixed order:
        step-based findings (``NO-VERDICT``/``UNRESOLVED-VERDICT``, in
        step order), then ``ORPHAN-VERDICT`` (in row order), then
        ``MALFORMED-ROW`` (in the order given).
    """
    step_results: list[StepResult] = []
    findings: list[Finding] = []

    for step in steps:
        plan_id = step.plan_id
        winner = _last_matching_row(step, rows)
        if winner is None:
            step_results.append(StepResult(step=plan_id, verdict=None, line_no=None, raw=None))
            findings.append(
                Finding(kind="NO-VERDICT", detail=f"{plan_id}: no matching ledger row", step=plan_id)
            )
            continue
        step_results.append(
            StepResult(step=plan_id, verdict=winner.verdict, line_no=winner.line_no, raw=winner.raw)
        )
        if winner.verdict in _UNRESOLVED_VERDICTS:
            findings.append(
                Finding(
                    kind="UNRESOLVED-VERDICT",
                    detail=f"{plan_id}: last verdict is {winner.verdict}",
                    step=plan_id,
                    line_no=winner.line_no,
                    raw=winner.raw,
                )
            )

    known_exact = {(s.lane, s.wave, s.step) for s in steps}
    known_waves = {(s.lane, s.wave) for s in steps}  # lane has >=1 step in this wave, any step number.
    for row in rows:
        if row.step is not None:
            if (row.lane_num, row.wave, row.step) not in known_exact:
                findings.append(
                    Finding(
                        kind="ORPHAN-VERDICT",
                        detail=(
                            f"L{row.lane_num} {row.scope}: no matching step "
                            "in any lane plan"
                        ),
                        step=f"W{row.wave}-L{row.lane_num}-S{row.step}",
                        line_no=row.line_no,
                        raw=row.raw,
                    )
                )
        elif (row.lane_num, row.wave) not in known_waves:
            findings.append(
                Finding(
                    kind="ORPHAN-VERDICT",
                    detail=f"L{row.lane_num} w{row.wave}: lane has no steps in this wave",
                    step=None,
                    line_no=row.line_no,
                    raw=row.raw,
                )
            )

    for bad in malformed:
        findings.append(
            Finding(kind="MALFORMED-ROW", detail=f"line {bad.line_no}: {bad.reason}", line_no=bad.line_no, raw=bad.raw)
        )

    return JoinResult(steps=step_results, findings=findings)


# --------------------------------------------------------------------------
# Ledger custody (spec section 1).
# --------------------------------------------------------------------------
def ledger_path(run: str, workdir: str | None = None) -> str:
    """The canonical, absolute, PRIMARY-checkout path to one run's ledger.

    ``{run_dir}/auditor-verdicts.txt`` where ``{run_dir}`` is
    ``shepherd_cli.models_run.run_dir(run, workdir)`` — deliberately
    delegated rather than re-composed, so this always names the exact same
    directory every other run-scoped artifact lives under, resolved
    through ``resolve_workdir()``/``resolve_repo_root()``'s existing
    primary-worktree binding (#221/#231). This is THE verb every agent
    should use instead of composing ``.shepherd/runs/<run>/...`` as a
    plain relative path, which resolves to a DIFFERENT, divorced physical
    copy from inside every linked worktree (#261) — nothing distinguishes
    that copy from the primary one until it diverges.

    Args:
        run: The run identifier.
        workdir: Optional workdir override (tests; a caller that already
            resolved a non-default workdir).

    Returns:
        The absolute ledger path (need not exist on disk).

    Raises:
        shepherd_cli.models_run.RunIdError: ``run`` is outside the closed
            ``[a-z0-9-]`` grammar.
    """
    return os.path.join(_resolve_run_dir(run, workdir), LEDGER_FILENAME)


def _normalize_ledger_rows(text: str) -> list[str]:
    """Ledger text -> comparable row strings for divergence comparison ONLY.

    Spec section 1.2: strip trailing whitespace per line, skip blank lines
    and ``#``-comment lines (a line is a comment when its first non-space
    character is ``#``, matching spec section 2's comment rule — leading
    whitespace is inspected to detect that, but not stripped from the
    stored/compared row itself). This is intentionally NOT
    :func:`parse_ledger`'s grammar parse — divergence comparison is byte
    content equality after this normalization, never a semantic parse; a
    line that would be MALFORMED-ROW to :func:`parse_ledger` still
    participates here.

    Args:
        text: One ledger copy's full text.

    Returns:
        Comparable row strings, in file order (not deduplicated here —
        callers that need a set for membership testing build one
        themselves).
    """
    rows: list[str] = []
    for line in text.splitlines():
        trailing_stripped = line.rstrip()
        probe = trailing_stripped.lstrip()
        if not probe or probe.startswith("#"):
            continue
        rows.append(trailing_stripped)
    return rows


def compare_worktree_ledgers(
    primary_text: str,
    worktrees: Mapping[str, str | None],
) -> list[Divergence]:
    """The mechanical worktree-ledger divergence check (spec section 1.2).

    FAILS (returns a non-empty list) on any row a linked worktree's ledger
    copy holds that the primary's copy lacks — the destructive case: a
    lane wrote a verdict only its own copy carries, and boundary-merging
    it can silently drop sibling lane rows the primary never had a chance
    to union-merge in. NEVER flags a worktree that is merely BEHIND the
    primary (primary has rows the worktree lacks) — that is every lane's
    normal state between merges, and is not returned as a divergence at
    all. A worktree with no ledger copy at all (``None`` in ``worktrees``)
    is fine, not a finding, and is skipped entirely.

    This function performs NO IO and no git calls itself — it takes
    already-read text, so the CLI wrapper (``git worktree list
    --porcelain`` + reading each copy's file, if present) stays the only
    place that touches git or the filesystem for this check.

    Args:
        primary_text: The primary checkout's ledger text.
        worktrees: Maps a worktree label (its path, typically) to that
            worktree's ledger text, or None when it has no copy at all.

    Returns:
        One :class:`Divergence` per (worktree, row) pair where ``row``
        (normalized per :func:`_normalize_ledger_rows`) appears in that
        worktree's copy but not in the primary's — empty when clean.
        Ordered by worktree label (sorted), then by the worktree's own
        row order; a row repeated more than once within one worktree copy
        is reported once for that worktree.
    """
    primary_rows = set(_normalize_ledger_rows(primary_text))
    divergences: list[Divergence] = []
    for label in sorted(worktrees):
        wt_text = worktrees[label]
        if wt_text is None:
            continue  # absent copy is fine, not a finding.
        for row in dict.fromkeys(_normalize_ledger_rows(wt_text)):  # de-dup, preserve order
            if row not in primary_rows:
                divergences.append(Divergence(worktree=label, row=row))
    return divergences


__all__ = [
    "FINDING_KINDS",
    "LEDGER_FILENAME",
    "VERDICTS",
    "Divergence",
    "Finding",
    "FindingKind",
    "JoinResult",
    "LedgerRow",
    "MalformedRow",
    "StepId",
    "StepResult",
    "Verdict",
    "compare_worktree_ledgers",
    "enumerate_plan_steps",
    "join",
    "ledger_path",
    "parse_ledger",
    "parse_ledger_line",
    "resolve_step_verdict",
]
