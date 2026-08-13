"""Run-state schema + atomic IO for ``.shepherd/runs/{run}/run.json``.

The run directory is the standard home for ALL run-scoped artifacts
(v6.4.1 artifact schema — ``skills/context/references/naming-conventions.md``):

    runs/{run}/
      run.json          # THIS module's document — CLI-written, validated
      seed.md           # planter output
      mesh.md           # planter mesh report
      plan.md           # engineer master plan
      phase0.md         # engineer Phase-0 mesh
      lanes/{lane}/plan.md   # conductor-OWNED lane plan
      graph/            # stage-graph state (ephemeral)
      dispatch/         # dispatch contracts + dispatcher-patch ledger (ephemeral)
      reports/ audits/  # materialized role output (ephemeral)
      close.md handoff.md    # terminal records

Design rules (from the codex-shepherd port-back review):

- ``run.json`` is NEVER latent-space-written: this module is the one CLI
  writer, so a CLI-originated write cannot invent its own field shapes.
  It is NOT the one *reader* — ``skills/bridge/SKILL.md`` names other
  shepherd implementations (prior bash versions, codex-shepherd) that
  read and write the same file with their own field sets. #247: a
  brand-new closed (``extra="forbid"``) schema rejected 100% of run.json
  files measured on live runs (33 and 17 validation errors on two
  runs), because every mutator goes through :func:`load_run`. The fix
  is a tolerant reader (:func:`normalize_run_document`) plus an open
  (``extra="allow"``) schema on both :class:`RunState` and
  :class:`LaneState`, so unknown fields — this CLI's own future fields
  included — round-trip through load -> save untouched instead of being
  silently dropped.
- Writes are atomic: tempfile in the target directory -> fsync ->
  ``os.replace`` -> fsync(dir). A crashed writer never leaves a torn file.
- Identifiers are sanitized to ``[a-z0-9][a-z0-9-]*`` — no ``..``, no
  path separators, no absolute paths, matching the artifact-schema rules.
- The ``lanes[].accepted_commit``/``merged`` pair is the #242
  boundary-merge ledger: WAVE-COMPLETE acceptance records the commit,
  the boundary merge marks it merged, and the wave gate asserts the
  pending set (accepted, unmerged) is EMPTY before any gate goes green.
- **#1 GATE-EXIT-CODE-MISMATCH / DF-63**: the pending-set check above is
  BLIND to a lane that was never ``run lane add``-ed at all -- zero rows
  is trivially "not pending", so an omitted registration used to make
  ``wave pending`` exit GREENER, not redder. ``RunState.missing_declared_
  lanes`` closes that hole by reading the run's OWN plan.md ``## Lane
  projection`` table (:func:`parse_declared_lane_ids`) as the independent
  source of what the run actually committed to shipping, so the gate has
  something to compare the ledger against besides the ledger itself.

CANONICAL RUN IDS (#P4, 2026-08-03 operator directive)
=========================================================
``skills/context/references/naming-conventions.md`` (~line 47) already states
the law: ``{run}`` IS the sprint slug (patch-arc runs: the patch slug),
generated from ``[branching].sprint_slug_pattern``/``patch_slug_pattern`` —
NEVER invented ad hoc. Nothing enforced it until now: FL03/axiom's live run
directory is ``v039-dev0-codex-01`` — a harness name and an ordinal welded
onto the slug. That is not cosmetic — ``skills/bridge/SKILL.md`` has two
shepherd implementations SHARING one run and arbitrating custody through
``run.json``; a harness-suffixed directory means each implementation creates
its OWN run and silently works in parallel instead of coordinating, the
exact failure the bridge contract exists to prevent.

:func:`derive_run_id` / :func:`is_canonical_run_id` / :func:`suggest_canonical_id`
make the law mechanical. :func:`is_canonical_run_id` is a SEPARATE, pattern-
SHAPE concern from :func:`validate_id`'s ``[a-z0-9][a-z0-9-]*`` grammar — the
grammar check is the security/path-safety hard error (never bypassable);
canonicality is a naming-convention check the CLI commands (``run init``'s
refusal, ``run canonicalize``, ``shepherd lint``'s WARN) layer on top of it,
not a replacement for it.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
import time

from pydantic import BaseModel, ConfigDict, Field

from shepherd_cli.resolution import resolve_repo_root, resolve_workdir

#: Closed identifier grammar for run and lane ids (artifact-schema rule).
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Closed run status vocabulary, in lifecycle order.
RUN_STATUSES: tuple[str, ...] = ("planted", "planned", "executing", "closing", "closed")

#: Closed lane state vocabulary (mirrors teammate declared_state semantics).
LANE_STATES: tuple[str, ...] = ("pending", "in-progress", "complete", "error")

#: The canonical per-run subdirectories, in the order
#: ``skills/context/references/naming-conventions.md §Run layout`` lists them.
#: Every run gets ALL of these at ``run init`` so a run's shape is identical
#: from creation, whoever creates it and whatever the sprint does or skips.
#:
#: Before v6.4.3 only ``lanes/`` was scaffolded and the rest appeared if and
#: when something happened to write into them — so "does this run have a
#: reports/ dir" answered "did this sprint dispatch a read-only role", not
#: "is this a run". A layout that materializes as a side effect of activity
#: cannot be relied on by anything that reads it.
#:
#: All four beyond ``lanes/`` hold DISPOSABLE run state and are gitignored
#: (the durable/disposable split in that same section): the directories exist
#: on disk for predictability, and git carries only the durable artifacts.
RUN_SUBDIRS: tuple[str, ...] = ("lanes", "graph", "dispatch", "reports", "audits")

#: The durable, git-TRACKED run-scoped artifacts, keyed to their writer
#: (``naming-conventions.md §Ownership``). Fixed names — the directory
#: carries the run identity, so these take no slug prefix. Presence is NOT
#: required (a run has no ``close.md`` until it closes); this tuple is the
#: closed vocabulary of what may legitimately sit at a run's top level.
RUN_TRACKED_FILES: tuple[str, ...] = (
    "seed.md",      # planter
    "mesh.md",      # planter
    "plan.md",      # engineer (materialized by root)
    "phase0.md",    # engineer (materialized by root)
    "close.md",     # root
    "handoff.md",   # root
)


class RunIdError(ValueError):
    """Raised for an identifier outside the closed ``[a-z0-9-]`` grammar."""


def validate_id(value: str, *, what: str = "id") -> str:
    """Validate one run/lane identifier against the closed grammar.

    Args:
        value: Candidate identifier.
        what: Label used in the error message (``run``/``lane``).

    Returns:
        The validated identifier, unchanged.

    Raises:
        RunIdError: On empty, uppercase, path-separator, ``..``, or
            absolute-path shapes.
    """
    if not value or not _ID_PATTERN.fullmatch(value):
        raise RunIdError(
            f"invalid {what} id: {value!r} (lowercase ASCII letters, digits, hyphens; "
            "must start alphanumeric; no path separators)"
        )
    return value


# --------------------------------------------------------------------------
# #P4 — canonical run-id derivation. See the module docstring's "CANONICAL
# RUN IDS" section for the why; everything below is the how.
# --------------------------------------------------------------------------
#: Documented defaults (``docs/configuration.md`` ``[branching]`` table) —
#: used whenever no config tier sets the corresponding key.
_DEFAULT_SPRINT_SLUG_PATTERN = "v{X}{Y}{Z}-dev{N}"
_DEFAULT_PATCH_SLUG_PATTERN = "v{X}{Y}{Z}"

#: A version or branch string shaped like ``v{X}.{Y}.{Z}[-dev.{N}]`` (the
#: ``*_branch_pattern`` defaults) — the ONE input shape :func:`derive_run_id`
#: accepts. The leading ``v`` is optional so a bare ``0.3.9-dev.0`` (no
#: branch prefix) also parses.
_VERSION_RE = re.compile(r"^v?(?P<X>\d+)\.(?P<Y>\d+)\.(?P<Z>\d+)(?:-dev\.(?P<N>\d+))?$")

#: The four fixed slug-pattern placeholders (``docs/configuration.md``:
#: "``{X}{Y}{Z}{N}`` are fixed integer placeholders"). Anything else in a
#: pattern string is matched/emitted literally.
_PLACEHOLDER_RE = re.compile(r"\{[XYZN]\}")


class RunIdDerivationError(ValueError):
    """Raised when a version/branch string cannot become a canonical run id."""


def _read_toml_key_last_match(path: str, key: str) -> str:
    """One file's ``cfg_get``-parity value for ``key`` — last match wins, ``""`` if unset/missing.

    Args:
        path: A candidate ``shepherd.toml``/``shepherd.local.toml`` path.
        key: The bare (section-agnostic) key to look for.

    Returns:
        The extracted value (:func:`shepherd_cli.commands.config._extract_cfg_value`),
        or ``""`` if the file doesn't exist, can't be read, or has no
        matching line.
    """
    if not os.path.isfile(path):
        return ""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except (OSError, UnicodeDecodeError):
        return ""
    matched: str | None = None
    for line in lines:
        if pattern.match(line):
            matched = line
    if matched is None:
        return ""
    from shepherd_cli.commands.config import _extract_cfg_value  # local: avoid any import cycle

    return _extract_cfg_value(matched)


def _slug_pattern(key: str, default: str, *, workdir: str | None) -> str:
    """Resolve one ``[branching]`` slug-pattern key via the CLI's shared config accessor.

    Delegates to :func:`shepherd_cli.commands.config._cfg_get` — the ONE
    5-tier ``shepherd.toml`` reader every other command already uses (see
    that module's "v6.4.2 HARNESS-NEUTRAL PRECEDENCE CONTRACT") — rather
    than opening a hardcoded ``.claude/shepherd.toml`` path here, so a
    future relocation of where ``shepherd.toml`` lives is inherited
    automatically with no change needed in this module.

    ``_cfg_get`` resolves its own workdir-relative tiers (1-2) internally
    via :func:`shepherd_cli.resolution.resolve_workdir`, with no override
    parameter of its own. When an explicit ``workdir`` is given here
    (tests; a caller that already resolved a non-default workdir), its two
    workdir-relative tiers (``shepherd.local.toml``/``shepherd.toml``) are
    checked FIRST, ahead of ``_cfg_get``'s own resolution — mirroring
    :func:`shepherd_cli.commands.config._config_search_paths`'s tier-1/2
    shape exactly (same two filenames, same precedence) without
    duplicating that module's full 5-tier list. Every other tier (legacy
    ``.claude/``, ``$XDG_CONFIG_HOME``) is workdir-independent, so falling
    through to ``_cfg_get`` for those is always correct regardless of
    ``workdir``.

    Args:
        key: ``"sprint_slug_pattern"`` or ``"patch_slug_pattern"``.
        default: The documented default (``docs/configuration.md``) to
            fall back to when no tier sets a non-empty value.
        workdir: Optional workdir override.

    Returns:
        The resolved pattern string.
    """
    if workdir is not None:
        for candidate in (
            os.path.join(workdir, "shepherd.local.toml"),
            os.path.join(workdir, "shepherd.toml"),
        ):
            value = _read_toml_key_last_match(candidate, key)
            if value:
                return value

    from shepherd_cli.commands.config import _cfg_get  # local: avoid any import cycle

    value = _cfg_get(key, resolve_repo_root())
    return value or default


def _parse_version_components(version_or_branch: str) -> dict[str, str | None]:
    """Extract ``X``/``Y``/``Z``/``N`` from a ``v{X}.{Y}.{Z}[-dev.{N}]`` string.

    Args:
        version_or_branch: A version (``v0.3.9-dev.0``) or branch name
            (``v6.4.1-dev.0``) in the ``*_branch_pattern`` shape.

    Returns:
        A ``{"X": ..., "Y": ..., "Z": ..., "N": ...}`` dict; ``N`` is None
        when no ``-dev.{N}`` suffix was present (a patch-arc input).

    Raises:
        RunIdDerivationError: ``version_or_branch`` doesn't match the
            expected shape at all.
    """
    match = _VERSION_RE.fullmatch(version_or_branch.strip())
    if match is None:
        raise RunIdDerivationError(
            f"cannot derive a run id from {version_or_branch!r} "
            "(expected v{X}.{Y}.{Z} or v{X}.{Y}.{Z}-dev.{N})"
        )
    return match.groupdict()


def _fill_slug_pattern(pattern: str, components: dict[str, str | None]) -> str:
    """Substitute ``{X}``/``{Y}``/``{Z}``/``{N}`` in ``pattern`` with parsed components.

    Args:
        pattern: A slug-pattern template.
        components: :func:`_parse_version_components`'s return value.

    Returns:
        The filled-in slug — components are substituted as their bare
        decimal string, UN-PADDED (see :func:`derive_run_id`'s docstring
        for the resulting double-digit-component ambiguity, documented
        deliberately rather than papered over with arbitrary padding).

    Raises:
        RunIdDerivationError: ``pattern`` references ``{N}`` but
            ``components["N"]`` is None (a patch-arc/bare-version input
            fed to a pattern that needs a sprint number).
    """

    def _substitute(match: re.Match[str]) -> str:
        placeholder = match.group(0)[1:-1]  # "{X}" -> "X"
        value = components.get(placeholder)
        if value is None:
            raise RunIdDerivationError(
                f"pattern {pattern!r} needs a {{{placeholder}}} component, but the input has "
                "none (a patch-arc version has no -dev.{N} suffix — pass kind='patch-arc')"
            )
        return value

    return _PLACEHOLDER_RE.sub(_substitute, pattern)


def derive_run_id(version: str, *, kind: str = "sprint", workdir: str | None = None) -> str:
    """Derive THE canonical run id for a version/branch — never invent one ad hoc.

    ``skills/context/references/naming-conventions.md`` (~line 47): ``{run}``
    IS the sprint slug (patch-arc runs: the patch slug), generated from
    ``[branching].sprint_slug_pattern``/``patch_slug_pattern`` — this is
    that generator, made mechanical. Pure and deterministic: no I/O beyond
    one config read (:func:`_slug_pattern`); the same ``version``/``kind``/
    config always produces the same id.

    DOUBLE-DIGIT COMPONENT AMBIGUITY (documented, not a bug): the default
    patterns glue ``X``/``Y``/``Z`` together with no separator
    (``v{X}{Y}{Z}-dev{N}``). Components are substituted as their bare
    decimal string, un-padded — ``v0.3.10-dev.2`` (``Z=10``, a two-digit
    component) yields ``v0310-dev2``, not a zero-padded or fixed-width
    alternative. This is inherently unparseable back into discrete X/Y/Z
    values from the slug alone (``v0310`` could equally be read as
    0/31/0 or 03/1/0) — by design, this module never attempts that
    reverse parse: :func:`is_canonical_run_id` only shape-matches (any
    digit run in that position), it never recovers components. A project
    that mints double-digit sprint/patch numbers and needs unambiguous
    slugs should configure a separator into its own
    ``sprint_slug_pattern``/``patch_slug_pattern``.

    Args:
        version: A version or branch string shaped like
            ``v{X}.{Y}.{Z}[-dev.{N}]`` (``v0.3.9-dev.0``, or a branch name
            in the same shape, e.g. ``v6.4.1-dev.0``).
        kind: ``"sprint"`` (uses ``sprint_slug_pattern``; REQUIRES a
            ``-dev.{N}`` component in ``version``) or ``"patch-arc"``
            (uses ``patch_slug_pattern``; a ``-dev.{N}`` suffix, if
            present, is parsed but ignored since the patch pattern never
            references ``{N}``).
        workdir: Optional workdir override — see :func:`_slug_pattern`.

    Returns:
        The canonical run id.

    Raises:
        RunIdDerivationError: ``kind`` is neither ``"sprint"`` nor
            ``"patch-arc"``; ``version`` doesn't match the expected
            shape; or ``kind="sprint"`` was given a version/branch with
            no ``-dev.{N}`` component.
    """
    if kind not in ("sprint", "patch-arc"):
        raise RunIdDerivationError(f"invalid kind: {kind!r} (sprint | patch-arc)")
    components = _parse_version_components(version)
    key, default = (
        ("sprint_slug_pattern", _DEFAULT_SPRINT_SLUG_PATTERN)
        if kind == "sprint"
        else ("patch_slug_pattern", _DEFAULT_PATCH_SLUG_PATTERN)
    )
    pattern = _slug_pattern(key, default, workdir=workdir)
    return _fill_slug_pattern(pattern, components)


def _pattern_to_regex(pattern: str, *, anchor_end: bool = True) -> re.Pattern[str]:
    """Compile a ``[branching]`` slug-pattern template into a matching regex.

    Every ``{X}``/``{Y}``/``{Z}``/``{N}`` placeholder becomes ``\\d+``;
    every other character is matched literally (``re.escape``d). The
    default pattern glues ``X``/``Y``/``Z`` together with no separator,
    so the compiled regex for adjacent placeholders is several consecutive
    ``\\d+`` groups with no way to tell where one component ends and the
    next begins from the id string alone — deliberate, see
    :func:`derive_run_id`'s docstring: this module forward-generates and
    shape-matches, never reverse-parses.

    Args:
        pattern: A ``sprint_slug_pattern``/``patch_slug_pattern`` value.
        anchor_end: True for a full-string match
            (:func:`is_canonical_run_id`); False to match only a leading
            prefix (:func:`_canonical_prefix`'s harness-suffix
            stripping) — still anchored at the start either way.

    Returns:
        The compiled regex.
    """
    parts = ["^"]
    pos = 0
    for match in _PLACEHOLDER_RE.finditer(pattern):
        parts.append(re.escape(pattern[pos : match.start()]))
        parts.append(r"\d+")
        pos = match.end()
    parts.append(re.escape(pattern[pos:]))
    if anchor_end:
        parts.append("$")
    return re.compile("".join(parts))


def is_canonical_run_id(run_id: str, workdir: str | None = None) -> bool:
    """Does ``run_id`` match the SHAPE the configured slug patterns can produce?

    A pure pattern-shape check, independent of :func:`validate_id`'s
    ``[a-z0-9][a-z0-9-]*`` path-safety grammar — see the module docstring's
    "CANONICAL RUN IDS" section for why those are two separate concerns.
    Never raises, even for a grammar-invalid string; it simply returns
    False.

    Args:
        run_id: The candidate run id (any string).
        workdir: Optional workdir override — see :func:`_slug_pattern`.

    Returns:
        True iff ``run_id`` fully matches either the configured
        ``sprint_slug_pattern`` or ``patch_slug_pattern`` shape. An
        invented id, or an otherwise-canonical id with an extra
        harness-name/ordinal suffix glued on (``v039-dev0-codex-01``),
        both return False.
    """
    sprint_pattern = _slug_pattern("sprint_slug_pattern", _DEFAULT_SPRINT_SLUG_PATTERN, workdir=workdir)
    patch_pattern = _slug_pattern("patch_slug_pattern", _DEFAULT_PATCH_SLUG_PATTERN, workdir=workdir)
    return bool(
        _pattern_to_regex(sprint_pattern).fullmatch(run_id)
        or _pattern_to_regex(patch_pattern).fullmatch(run_id)
    )


def _canonical_prefix(run_id: str, *, workdir: str | None = None) -> str | None:
    """The longest PROPER canonical-pattern prefix of ``run_id``, if any.

    Used by :func:`suggest_canonical_id` to strip a harness-name/ordinal
    suffix (the ``-codex-01`` in ``v039-dev0-codex-01``): both the sprint
    and patch slug-pattern regexes are tried as a start-anchored (not
    end-anchored) match; the longer of the two hits wins when both match,
    since the more specific sprint pattern (with its trailing ``-dev{N}``)
    legitimately consumes more of the string than the bare patch pattern
    would for the same input.

    Args:
        run_id: The candidate (already known non-canonical) run id.
        workdir: Optional workdir override — see :func:`_slug_pattern`.

    Returns:
        The longest matching prefix shorter than ``run_id`` itself, or
        None when neither pattern matches any leading prefix at all (a
        fully invented id has no canonical form to suggest).
    """
    sprint_pattern = _slug_pattern("sprint_slug_pattern", _DEFAULT_SPRINT_SLUG_PATTERN, workdir=workdir)
    patch_pattern = _slug_pattern("patch_slug_pattern", _DEFAULT_PATCH_SLUG_PATTERN, workdir=workdir)
    best: str | None = None
    for pattern in (sprint_pattern, patch_pattern):
        match = _pattern_to_regex(pattern, anchor_end=False).match(run_id)
        if match is None:
            continue
        candidate = match.group(0)
        if candidate == run_id:
            continue  # a full match means run_id IS already canonical, not a suffix to strip.
        if best is None or len(candidate) > len(best):
            best = candidate
    return best


def suggest_canonical_id(run_id: str, *, workdir: str | None = None) -> str | None:
    """Best-effort canonical id for ``run_id`` — the ``run canonicalize`` engine.

    Args:
        run_id: The run id to canonicalize.
        workdir: Optional workdir override — see :func:`_slug_pattern`.

    Returns:
        ``run_id`` unchanged when it is already canonical (nothing to
        rename — :func:`is_canonical_run_id` is True); the longest
        recognizable sprint/patch-pattern prefix of ``run_id`` when it
        carries a harness-name/ordinal suffix on an otherwise-canonical
        shape (e.g. ``v039-dev0-codex-01`` -> ``v039-dev0``); or None
        when ``run_id`` has no recognizable canonical-pattern prefix at
        all — not automatically fixable, needs ``shepherd run rename``
        with an explicit destination chosen by a human.
    """
    if is_canonical_run_id(run_id, workdir):
        return run_id
    return _canonical_prefix(run_id, workdir=workdir)


# --------------------------------------------------------------------------
# #1 GATE-EXIT-CODE-MISMATCH / DF-63 -- ledger-completeness check. See the
# module docstring's #242 bullet above: `pending_merges()` alone cannot see
# a lane that was never `run lane add`-ed, because zero ledger rows reads
# as "not pending" rather than "missing". Everything below reads the run's
# OWN plan.md `## Lane projection` table as the independent declared-lane
# source `RunState.missing_declared_lanes` (below `pending_merges`) joins
# against.
# --------------------------------------------------------------------------
#: The run plan's ``## Lane projection`` section heading -- any header
#: level, case-insensitive (prose casing drifts; the anchor should not).
_LANE_PROJECTION_HEADING_RE = re.compile(r"^#{1,6}\s*lane projection\s*$", re.IGNORECASE)

#: ANY markdown heading, any level -- bounds :func:`parse_declared_lane_ids`'s
#: table scan to the ``## Lane projection`` section itself. Without this the
#: scan runs to end-of-file: a plan whose section renders empty (``run
#: init``'s ``templates/plan.md.j2`` -- the section holds only a Jinja
#: comment until PLAN-GATE appends the table) then wanders into later
#: sections and adopts the first pipe-table it finds there, headed
#: ``lane_id`` or not.
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s")

#: One markdown table separator cell (``---``, ``:--``, ``--:``, ``:-:``)
#: -- distinguishes a table's header row from its first DATA row without
#: hardcoding a column count.
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


def parse_declared_lane_ids(plan_text: str) -> list[str]:
    """The declared lane ids from a run plan's ``## Lane projection`` table.

    Pure text parsing, no IO -- callers (``commands/run.py``'s ``wave
    pending``) read ``plan.md`` themselves and pass its text in. DF-63's
    measured defect: a lane can be fully worked (worktree, branch,
    WAVE-COMPLETE-accepted) and still never appear in ``run.json`` because
    nobody ran ``run lane add`` for it -- the #242 pending-set check is
    then blind to it BY CONSTRUCTION (zero ledger rows is trivially "not
    pending", not "missing"). This function reads the one independent
    source that knows what the run actually committed to shipping: the
    plan's own lane table (``.shepherd/runs/v645/plan.md`` §Lane
    projection is the canonical shape this mirrors: ``| lane_id |
    member_steps | file_scope.exclusive | parallel_with |``), so a
    completeness check has something to compare the ledger against besides
    the ledger itself.

    Args:
        plan_text: The full text of a run's ``plan.md``.

    Returns:
        Declared lane ids in table order, lowercased and stripped of
        backtick/emphasis decoration (plan prose `` `L1-engine` `` becomes
        ``"l1-engine"``, matching the lowercase grammar
        :func:`validate_id` already holds registered lane ids to). Empty
        when the plan has no ``## Lane projection`` section, the section
        (bounded by the next markdown heading of any level) has no table,
        that table isn't headed ``lane_id``, or the table has zero data
        rows -- none of those are errors: a plan that predates or omits
        the section has nothing declared to check ledger completeness
        against. The section bound also means a table in a LATER section
        (a lane-status table, a deviations table -- anything else headed
        ``lane_id``) is never mistaken for the declared-lane table just
        because ``## Lane projection`` itself rendered empty.
    """
    lines = plan_text.splitlines()
    heading_idx: int | None = None
    for i, line in enumerate(lines):
        if _LANE_PROJECTION_HEADING_RE.match(line.strip()):
            heading_idx = i
            break
    if heading_idx is None:
        return []

    lane_ids: list[str] = []
    saw_header = False
    saw_separator = False
    for line in lines[heading_idx + 1 :]:
        stripped = line.strip()
        if _MARKDOWN_HEADING_RE.match(stripped):
            break  # next section -- Lane projection ended, table or not.
        if not stripped or not stripped.startswith("|"):
            if saw_header:
                break  # blank line or prose after the table ends the section.
            continue  # prose between the heading and the table.
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not saw_header:
            saw_header = True
            if not cells or cells[0].strip("`* ").lower() != "lane_id":
                break  # the first table after the heading isn't the lane table.
            continue
        if not saw_separator:
            saw_separator = True
            if cells and all(_TABLE_SEPARATOR_CELL_RE.match(c) for c in cells if c):
                continue  # the `|---|---|` separator row -- no lane id here.
        if not cells or not cells[0]:
            continue
        lane_id = cells[0].strip("`* ").lower()
        if lane_id:
            lane_ids.append(lane_id)
    return lane_ids


class LaneState(BaseModel):
    """One lane's registration + boundary-merge ledger row.

    #247: ``extra="allow"`` — other shepherd implementations (and future
    CLI fields) attach lane keys this model does not name; a load->save
    round trip must preserve them rather than silently drop them.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    plan: str = ""  # repo-relative lanes/{lane}/plan.md path
    worktree: str = ""
    branch: str = ""
    state: str = "pending"
    accepted_commit: str | None = None  # 242 ledger: WAVE-COMPLETE-accepted sha
    merged: bool = False  # 242 ledger: boundary merge landed the sha
    updated_at: int = 0


class RunState(BaseModel):
    """The ``run.json`` document — the machine state of one run.

    #247: ``extra="allow"`` — see the module docstring. This model names
    the fields the CLI itself reads/writes; every other top-level key a
    document carries (``decisions``, ``blockers``, ``acceptance``, ...)
    is preserved verbatim through :func:`load_run` / :func:`save_run`
    instead of being rejected or dropped.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    run: str
    kind: str = "sprint"  # sprint | patch-arc
    branch: str = ""
    base: str = ""
    seed: str = ""  # repo-relative seed.md path, "" until planted
    plan: str = ""  # repo-relative plan.md path, "" until planned
    status: str = "planted"
    lanes: list[LaneState] = Field(default_factory=list)
    updated_at: int = 0

    def lane(self, lane_id: str) -> LaneState | None:
        """Look up one lane by id.

        Args:
            lane_id: The lane identifier.

        Returns:
            The matching lane, or None.
        """
        for lane in self.lanes:
            if lane.id == lane_id:
                return lane
        return None

    def pending_merges(self) -> list[LaneState]:
        """The #242 pending set: lanes accepted but not yet boundary-merged.

        Returns:
            Lanes with a recorded ``accepted_commit`` and ``merged`` False.
            A non-empty return at a wave gate is a mechanical stop.
        """
        return [lane for lane in self.lanes if lane.accepted_commit and not lane.merged]

    def missing_declared_lanes(self, plan_text: str) -> list[str]:
        """#1 GATE-EXIT-CODE-MISMATCH / DF-63: declared lanes with no ledger row.

        The completeness half of the #242 wave gate, alongside
        :meth:`pending_merges`: a lane the run's plan declares
        (:func:`parse_declared_lane_ids`) but that was never
        ``run lane add``-ed has ZERO rows in ``self.lanes`` -- invisible to
        ``pending_merges`` by construction, since that check only ever
        looks AT registered rows, never for absent ones. This is the other
        half: it looks for absence.

        Args:
            plan_text: The run's ``plan.md`` text -- pass ``""`` when the
                run has no plan.md yet; an empty plan declares no lanes,
                so the return is always empty in that case, never a crash.

        Returns:
            Declared lane ids (:func:`parse_declared_lane_ids` order,
            already lowercased) absent from ``self.lanes`` -- empty when
            every declared lane is registered, including when the plan
            declares none at all. A non-empty return at a wave gate is a
            mechanical stop, exactly like a non-empty :meth:`pending_merges`.
        """
        declared = parse_declared_lane_ids(plan_text)
        registered = {lane.id.lower() for lane in self.lanes}
        return [lane_id for lane_id in declared if lane_id not in registered]


def runs_root(workdir: str | None = None) -> str:
    """The runs directory under the resolved (or given) workdir."""
    return os.path.join(workdir if workdir is not None else resolve_workdir(), "runs")


def run_dir(run: str, workdir: str | None = None) -> str:
    """One run's directory: ``<workdir>/runs/<run>``.

    Args:
        run: The run identifier (validated).
        workdir: Optional workdir override (tests).

    Returns:
        The absolute run directory path (need not exist).
    """
    return os.path.join(runs_root(workdir), validate_id(run, what="run"))


def lane_dir(run: str, lane: str, workdir: str | None = None) -> str:
    """One lane's directory: ``<workdir>/runs/<run>/lanes/<lane>``."""
    return os.path.join(run_dir(run, workdir), "lanes", validate_id(lane, what="lane"))


def scaffold_run_layout(run: str, workdir: str | None = None) -> list[str]:
    """Create every canonical subdirectory of a run, idempotently.

    The single writer of :data:`RUN_SUBDIRS`, so ``run init`` and any repair
    path cannot drift on which directories a run is supposed to have.

    Args:
        run: The run identifier (validated by :func:`run_dir`).
        workdir: Optional workdir override (tests).

    Returns:
        The subdirectory names that did NOT exist and were created, in
        :data:`RUN_SUBDIRS` order — empty when the layout was already
        complete, which is what makes this safe to call on an existing run.
    """
    base = run_dir(run, workdir)
    created: list[str] = []
    for name in RUN_SUBDIRS:
        target = os.path.join(base, name)
        if not os.path.isdir(target):
            created.append(name)
        os.makedirs(target, exist_ok=True)
    return created


def missing_run_subdirs(run: str, workdir: str | None = None) -> list[str]:
    """The canonical subdirectories a run is missing, in canonical order.

    The read-only half of :func:`scaffold_run_layout` — used by the
    ``run layout`` verb to report drift without repairing it, so an operator
    can see what a ``--repair`` would do before running it.

    Args:
        run: The run identifier.
        workdir: Optional workdir override (tests).

    Returns:
        Missing subdirectory names; empty when the layout is complete.
    """
    base = run_dir(run, workdir)
    return [n for n in RUN_SUBDIRS if not os.path.isdir(os.path.join(base, n))]


def run_state_path(run: str, workdir: str | None = None) -> str:
    """The ``run.json`` path for one run."""
    return os.path.join(run_dir(run, workdir), "run.json")


def atomic_write_json(path: str, payload: dict[str, object]) -> None:
    """Write JSON atomically: tempfile -> fsync -> replace -> fsync(dir).

    Args:
        path: Destination file path; parent directories are created.
        payload: JSON-ready document (sorted keys on disk).
    """
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".run-json-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _coerce_epoch(value: object) -> int:
    """Coerce a legacy ``updated_at`` value into unix epoch seconds.

    Args:
        value: An ``int``/``float`` epoch, an ISO8601 string (bash and
            codex-shepherd both write ``updated_at`` as ISO8601 text),
            or anything else.

    Returns:
        The integer epoch. ``0`` for anything that cannot be parsed —
        this function never raises.
    """
    if isinstance(value, bool):
        return 0  # bool is an int subclass; never a meaningful timestamp.
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return 0
    text = value.strip()
    if not text:
        return 0
    try:
        return int(text)  # an epoch already serialized as a string.
    except ValueError:
        pass
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return int(parsed.timestamp())


def normalize_run_document(raw: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    """Normalize a legacy/foreign ``run.json`` document to the current shape.

    #247: prior shepherd versions and the sibling codex-shepherd
    implementation write ``run.json`` with a different field shape for
    three keys. This is a pure function (no IO, no pydantic) precisely
    so each divergence is independently unit-testable:

    - ``run_id`` (legacy) -> ``run`` (current), only when ``run`` is not
      already present.
    - ``lanes`` as a ``dict`` keyed by lane id (legacy) -> the current
      ``list[LaneState]`` shape, injecting the dict key as each lane's
      ``id`` (deterministic: the key always wins over an inline ``id``
      the lane dict might also carry) and sorting by id.
    - ``updated_at`` as an ISO8601 string (legacy) -> int epoch seconds
      via :func:`_coerce_epoch`.

    Every other key — the 27+ extra top-level fields legacy documents
    carry (``decisions``, ``blockers``, ``acceptance``, ...) — passes
    through untouched; :class:`RunState`'s ``extra="allow"`` config is
    what preserves them, not this function.

    Args:
        raw: The parsed JSON document, as-is off disk.

    Returns:
        A ``(normalized_document, applied)`` pair. ``applied`` lists the
        migrations this call actually performed, in a fixed
        ``["run_id->run", "lanes:dict->list", "updated_at:iso->epoch"]``
        order (never dict-iteration order) — empty when ``raw`` was
        already canonical.
    """
    doc = dict(raw)
    applied: list[str] = []

    if "run" not in doc and "run_id" in doc:
        doc["run"] = doc.pop("run_id")
        applied.append("run_id->run")

    lanes = doc.get("lanes")
    if isinstance(lanes, dict):
        normalized_lanes: list[object] = []
        for lane_id in sorted(lanes):
            lane_doc = lanes[lane_id]
            if isinstance(lane_doc, dict):
                lane_doc = dict(lane_doc)
            else:
                lane_doc = {}
            lane_doc["id"] = lane_id  # the dict key is authoritative, not any inline "id".
            normalized_lanes.append(lane_doc)
        doc["lanes"] = normalized_lanes
        applied.append("lanes:dict->list")

    if isinstance(doc.get("updated_at"), str):
        doc["updated_at"] = _coerce_epoch(doc["updated_at"])
        applied.append("updated_at:iso->epoch")

    return doc, applied


def load_run_with_migrations(run: str, workdir: str | None = None) -> tuple[RunState, list[str]]:
    """Load + tolerantly validate one run's ``run.json``, reporting migrations.

    Args:
        run: The run identifier.
        workdir: Optional workdir override (tests).

    Returns:
        ``(state, applied)`` — the validated run state, and the ordered
        list of :func:`normalize_run_document` migrations that were
        actually applied (empty when the document was already
        canonical).

    Raises:
        FileNotFoundError: No ``run.json`` for this run.
        json.JSONDecodeError: The file is not valid JSON.
        pydantic.ValidationError: The (normalized) document still fails
            schema validation.
    """
    path = run_state_path(run, workdir)
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        # Valid JSON, but not an object (e.g. a bare list/string/number) --
        # not this function's shape to normalize; let pydantic reject it
        # with its own "Input should be a valid dictionary" ValidationError
        # rather than normalize_run_document crashing on a non-dict.
        return RunState.model_validate(raw), []
    normalized, applied = normalize_run_document(raw)
    return RunState.model_validate(normalized), applied


def load_run(run: str, workdir: str | None = None) -> RunState:
    """Load + tolerantly validate one run's ``run.json``.

    A thin wrapper over :func:`load_run_with_migrations` for callers
    that don't need the applied-migrations list (e.g. every mutator
    other than ``run show``/``run migrate``).

    Args:
        run: The run identifier.
        workdir: Optional workdir override (tests).

    Returns:
        The validated run state, normalized per :func:`normalize_run_document`.

    Raises:
        FileNotFoundError: No ``run.json`` for this run.
        json.JSONDecodeError: The file is not valid JSON.
        pydantic.ValidationError: The (normalized) document still fails
            schema validation.
    """
    state, _applied = load_run_with_migrations(run, workdir)
    return state


def save_run(state: RunState, workdir: str | None = None) -> str:
    """Persist one run's state atomically, stamping ``updated_at``.

    Args:
        state: The run state to persist (``state.run`` names the target).
        workdir: Optional workdir override (tests).

    Returns:
        The path written.
    """
    state.updated_at = int(time.time())
    path = run_state_path(state.run, workdir)
    atomic_write_json(path, state.model_dump(mode="json"))
    return path


def list_runs(workdir: str | None = None) -> list[str]:
    """Enumerate run ids with a ``run.json``, sorted.

    Returns:
        Sorted run ids (directory names under ``runs/`` carrying a
        ``run.json`` — never an mtime scan).
    """
    root = runs_root(workdir)
    if not os.path.isdir(root):
        return []
    found = []
    for name in sorted(os.listdir(root)):
        if _ID_PATTERN.fullmatch(name) and os.path.isfile(os.path.join(root, name, "run.json")):
            found.append(name)
    return found


__all__ = [
    "LANE_STATES",
    "RUN_STATUSES",
    "LaneState",
    "RunIdDerivationError",
    "RunIdError",
    "RunState",
    "atomic_write_json",
    "derive_run_id",
    "is_canonical_run_id",
    "lane_dir",
    "list_runs",
    "load_run",
    "load_run_with_migrations",
    "normalize_run_document",
    "parse_declared_lane_ids",
    "run_dir",
    "run_state_path",
    "runs_root",
    "save_run",
    "suggest_canonical_id",
    "validate_id",
]
