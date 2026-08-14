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
- **#294 lost-update race**: every mutator above is ``load_run()`` ->
  in-memory mutate -> ``save_run()`` -- two independent entry points with
  caller-controlled code running in between, no serialization. PROVEN:
  two barrier-synchronized OS processes each ``load_run``, append a
  distinct ``LaneState``, ``save_run`` -- both read the same pre-write
  (empty) state, and the second writer's ``save_run`` silently
  overwrote the first's, dropping a lane with no exception, no warning,
  exit 0 on both. The atomic tempfile+rename in :func:`atomic_write_json`
  protects a single writer against a CRASH; it does nothing for two
  writers racing the same read-modify-write cycle.
  :func:`load_run_with_migrations` now acquires a ``.run.json.lock``
  sidecar advisory lock (``fcntl.flock`` -- portable across macOS and
  Linux identically, unlike ``fcntl.lockf`` whose semantics differ) and
  holds it across the caller's mutation; :func:`save_run` consumes that
  held lock (or acquires its own, for a standalone write with no
  preceding load in this process) around the atomic replace, then
  releases it. A crashed holder is never fatal: ``flock`` is owned by
  the open file description, not the process, so the kernel releases it
  the instant every fd referencing it closes -- SIGKILL included -- and
  the next acquire succeeds near-instantly with no timeout involved. A
  bounded wait (:class:`RunLockTimeout`, 30s) only guards the different
  case of a genuinely slow but still-LIVE holder, so a caller fails
  loudly instead of hanging forever. See
  ``services/cli/tests/test_run_concurrency.py`` for the reproduction
  (two-process, N-process contention, and killed-holder recovery).

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
import fcntl
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


class RunLockTimeout(TimeoutError):
    """#294: a run's ``.run.json.lock`` advisory lock could not be acquired in time.

    Distinguishes "another writer is genuinely mid-transaction and still
    alive" (this) from a crashed holder, which never reaches this path at
    all -- ``flock`` is released by the kernel the instant a crashed
    process's file descriptors close (SIGKILL included), so the very
    next acquire attempt after a crash succeeds immediately, with no
    timeout involved.
    """


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


# --------------------------------------------------------------------------
# #294 -- the read-modify-write lock. ``fcntl.flock`` (never ``fcntl.lockf``:
# their semantics diverge across POSIX flavors, and this must behave
# identically on macOS and Linux) taken on a ``.run.json.lock`` sidecar next
# to the document it guards -- named to match the issue's own suggested
# convention and this project's existing bash-side lock-file idiom
# (``skills/context/scripts/cmd_lock.sh``), though the mechanism here is
# kernel-arbitrated rather than that script's manual PID/age reap, which is
# unnecessary once the OS itself guarantees crash release (see
# :class:`RunLockTimeout`). The lock is never written to and never read for
# content -- existence + an exclusive hold is the entire protocol.
# --------------------------------------------------------------------------
#: Worst-case wait for a contended lock still held by a LIVE writer before
#: giving up loudly. Not the crash-recovery path -- see :class:`RunLockTimeout`.
_LOCK_TIMEOUT_S = 30.0

#: Poll interval while waiting for a contended lock.
_LOCK_POLL_S = 0.02


def _lock_sidecar_path(json_path: str) -> str:
    """The advisory-lock sidecar path for one ``run.json``: ``.run.json.lock``."""
    parent, name = os.path.split(json_path)
    return os.path.join(parent, f".{name}.lock")


def _acquire_lock(json_path: str, *, timeout: float = _LOCK_TIMEOUT_S) -> int:
    """Blocking-with-timeout acquire of one run's exclusive advisory lock.

    ``flock`` locks the OPEN FILE DESCRIPTION, not the path or the
    process -- it survives a directory rename (:func:`_rename_run` reuses
    the same fd across the move via the pending-lock handoff below) and
    is released by the kernel the instant every fd referencing it closes,
    including on ``SIGKILL``. That kernel guarantee is what makes a
    crashed holder non-fatal; ``timeout`` only bounds how long this call
    waits on a genuinely slow but LIVE holder before failing loudly
    instead of hanging forever.

    Args:
        json_path: The ``run.json`` path being protected — the lock file
            lives alongside it (:func:`_lock_sidecar_path`).
        timeout: Seconds to wait for a contended lock before raising.

    Returns:
        The open, locked file descriptor. The caller owns it and must
        eventually release it via :func:`_release_lock`.

    Raises:
        RunLockTimeout: Still held by another live writer after ``timeout``.
    """
    lock_path = _lock_sidecar_path(json_path)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise RunLockTimeout(
                    f"timed out after {timeout}s waiting for the run lock at "
                    f"{lock_path!r} (held by another live writer -- a crashed "
                    "holder releases immediately, see RunLockTimeout)"
                ) from None
            time.sleep(_LOCK_POLL_S)


def _release_lock(fd: int) -> None:
    """Release + close a lock fd returned by :func:`_acquire_lock`."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


#: The lock this PROCESS currently holds mid read-modify-write cycle, if
#: any -- ``(json_path at acquire time, fd)``. Every CLI mutator's shape is
#: exactly ``load_run() -> mutate in memory -> save_run()``
#: (``commands/run.py``'s ``lane_add_cmd``/``lane_set_cmd``/
#: ``wave_accept_cmd``/``set_cmd``/...), synchronous and single-threaded
#: within one process -- this project's concurrency is cross-PROCESS (see
#: the module docstring's #294 entry), never cross-thread -- so at most ONE
#: such transaction is ever in flight per process, and this module-level
#: slot is enough to carry the held lock from
#: :func:`load_run_with_migrations`, across the caller's mutation code (in
#: a different module), to :func:`save_run` — with neither function's
#: signature changing.
_pending_lock: tuple[str, int] | None = None


def _begin_read_transaction(json_path: str) -> None:
    """Acquire ``json_path``'s lock for the read half of load -> mutate -> save.

    Releases any lock this process is still holding from an earlier,
    never-saved :func:`load_run_with_migrations` call first (a read-only
    command like ``run show`` invoked twice in one process) — otherwise a
    second same-process acquire on the same inode would block on itself
    forever, since ``flock`` grants no same-process reentrancy across
    independently opened file descriptors.
    """
    global _pending_lock
    if _pending_lock is not None:
        _release_lock(_pending_lock[1])
        _pending_lock = None
    _pending_lock = (json_path, _acquire_lock(json_path))


def _end_read_transaction() -> None:
    """Drop a read transaction's lock without a save (the load itself failed)."""
    global _pending_lock
    if _pending_lock is not None:
        _release_lock(_pending_lock[1])
        _pending_lock = None


def _same_lock_file(fd: int, json_path: str) -> bool:
    """Does open ``fd`` refer to the SAME inode as ``json_path``'s lock sidecar?

    Identity by ``(st_dev, st_ino)`` rather than trusting path equality —
    a mid-transaction directory rename (:func:`_rename_run`) legitimately
    changes the path while the open file description (and its lock) keep
    referring to the identical file, now reachable only under the new
    path.
    """
    try:
        target = os.stat(_lock_sidecar_path(json_path))
    except FileNotFoundError:
        return False
    held = os.fstat(fd)
    return (held.st_dev, held.st_ino) == (target.st_dev, target.st_ino)


def _consume_pending_lock(json_path: str) -> int:
    """The fd to hold while :func:`save_run` writes ``json_path``.

    Reuses this process's pending lock from a matching
    :func:`load_run_with_migrations` call when one is open FOR THE SAME
    FILE — verified by inode (:func:`_same_lock_file`), not path
    equality, so a mid-transaction directory rename (:func:`_rename_run`,
    where ``json_path`` at save time legitimately differs from the path
    the lock was acquired under) still correctly reuses the moved lock.
    A pending lock for a genuinely DIFFERENT file — e.g. a read-only
    :func:`load_run_with_migrations` call this process never followed
    with a save, before an unrelated ``save_run`` for some other run —
    is released rather than misapplied to protect the wrong write, and a
    fresh lock is acquired for ``json_path`` instead. Also the path taken
    for a standalone write with no preceding load in this process at all
    (``run init``'s first-ever write for a brand-new run).
    """
    global _pending_lock
    if _pending_lock is not None:
        _, fd = _pending_lock
        _pending_lock = None
        if _same_lock_file(fd, json_path):
            return fd
        _release_lock(fd)
    return _acquire_lock(json_path)


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

    #294: on success, this holds ``run.json``'s advisory lock past return
    -- it is the read half of the load -> mutate -> save critical section,
    and :func:`save_run` is the only function that releases it (see
    :data:`_pending_lock`). A run.json that does not exist yet is never
    locked at all (the ``FileNotFoundError`` fast path is unchanged: no
    lock file, no run directory, created as a side effect of a failed
    read) — only an ALREADY-existing document is protected, since only a
    mutator's read side needs the hold.
    """
    path = run_state_path(run, workdir)
    locked = os.path.isfile(path)
    if locked:
        _begin_read_transaction(path)
    try:
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
    except BaseException:
        # No successful load means no subsequent save_run to release this
        # -- drop it here so a caller that retries load_run in the same
        # process (or simply calls it again, e.g. a read-only command run
        # twice) never self-deadlocks on its own still-held lock.
        if locked:
            _end_read_transaction()
        raise


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

    #294: this is the write half + release point of the load -> mutate ->
    save critical section. Reuses this process's still-open lock from a
    matching :func:`load_run_with_migrations` call when one is pending
    (the normal mutator shape), or acquires a fresh one for a standalone
    write with no preceding load in this process (``run init``). Either
    way the lock is held for the full :func:`atomic_write_json` call and
    released unconditionally afterward, even on write failure.
    """
    state.updated_at = int(time.time())
    path = run_state_path(state.run, workdir)
    fd = _consume_pending_lock(path)
    try:
        atomic_write_json(path, state.model_dump(mode="json"))
    finally:
        _release_lock(fd)
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
    "RunLockTimeout",
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
