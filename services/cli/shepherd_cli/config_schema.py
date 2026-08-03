"""Validated ``shepherd.toml`` schema — pydantic v2 models + a file validator.

WHY THIS EXISTS (v6.4.2)
=========================
Every ``shepherd.toml`` tier (see :mod:`shepherd_cli.commands.config`'s
5-tier precedence chain) is today hand-edited and unvalidated: a typo'd
key — ``pahts.docs`` instead of ``paths.docs``, ``dupshook`` instead of
``dups_hook``, ``driver = "githubworkflow"`` instead of
``"github-workflow"`` — silently falls through :func:`_cfg_get`'s
line-scan or :mod:`tomllib`'s parse and the operator gets a QUIET WRONG
ANSWER: the built-in default, with no signal anything was misspelled.
That is precisely the failure class CLAUDE.md's deterministic-space rule
exists to kill — "a typo'd key silently falls through to a default" is
not a judgment call, it has one correct behavior (reject, name the typo,
suggest the fix), so it belongs in a script, not in an operator's head or
an agent's latent guess about what the file "probably" meant.

This module is that script. It defines the FULL documented
``shepherd.toml`` surface (every table in ``docs/configuration.md``,
cross-checked against this repo's own self-hosted dogfood config
``.claude/shepherd.toml`` and the bundled ``examples/minimal/shepherd.toml``
— together the three sources the schema below is derived from) as a tree
of pydantic v2 ``BaseModel``s, every field individually optional with the
documented default (a single TOML file is legitimately PARTIAL — the
whole point of the 5-tier :func:`~shepherd_cli.commands.config._cfg_get`
resolution is that a ``shepherd.local.toml`` may override exactly one
key), then wraps ``ShepherdConfig.model_validate`` in
:func:`validate_config_text` / :func:`validate_config_file` to turn raw
pydantic ``ValidationError``s into operator-readable
:class:`ConfigIssue` rows: FILE + ``[section.sub].key`` + what was wrong
+ (for an unknown key/section) a ``difflib``-computed did-you-mean + (for
an enum/``Literal`` field) the allowed set.

DESIGN NOTE — why every model uses ``extra="forbid"``
========================================================
Two categories of table exist in this schema, and they get different
strictness:

- **Closed-vocabulary tables** (``[project]``, ``[branching]``,
  ``[gates]``, ``[release]``, ``[spawn]``, ...): the key set is fixed and
  documented. Every such section is a ``BaseModel`` with
  ``ConfigDict(extra="forbid")`` — an unrecognized key is ALWAYS an
  error, never silently ignored, which is what makes an unknown-key
  report possible at all.
- **Open-vocabulary tables** (``[mcp]``, ``[cli]``,
  ``[skills.by_domain]``, ``[skills.detection]``): the key set is
  genuinely unbounded by design — ``[mcp]`` accepts a boolean for ANY
  MCP server name a project happens to have configured, ``[skills.
  by_domain]`` maps ANY domain name a project invents to a skill-slug
  list. These are modeled as plain ``dict[str, bool]`` / ``dict[str,
  list[str]]`` fields, not nested ``BaseModel``s — a typo'd key here
  (``"grafanna"``) is indistinguishable from a legitimately new server
  name shepherd hasn't heard of yet, so ``extra="forbid"``'s unknown-key
  detection would be actively wrong here, not merely unhelpful.

CONSERVATISM ON ``required``
==============================
Almost every field below carries the exact default
``docs/configuration.md`` documents (cross-checked against the two
worked examples this module was derived from). The ONE field with no
sensible standalone default is ``[project].name`` (docs marks it
``*(required)*`` for a COMPLETE, resolved config) — even that is
``str | None = None`` here, because a single TOML TIER is not required
to be a complete config on its own (a ``shepherd.local.toml`` overriding
only ``[spawn].max_parallel`` is valid and carries no ``[project]``
table at all). "Required" in the pydantic sense is reserved for fields
that are meaningless without their siblings within the SAME inline
table — ``[[gates.extra]]``'s ``name``/``cmd`` pair (see
:class:`GateExtraEntry`) is the only such case in this schema.
"""

from __future__ import annotations

import difflib
import re
import tomllib
import types
import typing
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# --------------------------------------------------------------------------
# [project]
# --------------------------------------------------------------------------
class ProjectConfig(BaseModel):
    """``[project]`` — identity (``docs/configuration.md`` §``[project]``).

    Attributes:
        name: Repo/project name. Documented as required for a COMPLETE
            resolved config, but optional here — see the module
            docstring's conservatism note.
        language: ``rust|python|typescript|go|mixed`` per the docs table,
            PLUS ``"markdown"`` — this repo's own self-hosted dogfood
            config (``.claude/shepherd.toml``) sets
            ``language = "markdown"`` (the shepherd plugin's own primary
            content is doctrine + shell, not compiled code), so the
            documented enum is extended by one value to keep that config
            validating clean.
        description: Free text.
        harnesses: Which shepherd implementations operate in this repo,
            e.g. ``["claude-code", "codex"]``. DECLARATIVE metadata only
            (v6.4.2): a machine-readable anchor for the bridge contract so
            an implementation can distinguish "no other harness is
            configured here" from "a sibling is declared and may hold
            custody" before it inspects ``run.json``. No feature reads it
            for dispatch. Deliberately an open list of free strings rather
            than a closed enum — a new harness must not fail validation on
            a repo that names it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    language: Literal["rust", "python", "typescript", "go", "mixed", "markdown"] = "rust"
    description: str = ""
    harnesses: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# [branching]
# --------------------------------------------------------------------------
class BranchingConfig(BaseModel):
    """``[branching]`` — branch topology.

    Attributes:
        patch_branch_pattern: Patch-arc branch name template.
        sprint_branch_pattern: Sprint branch name template.
        patch_slug_pattern: Filesystem-safe patch slug (dots collapsed).
        sprint_slug_pattern: Filesystem-safe sprint slug.
        sprints_per_patch: Sprints per patch arc (``dev.{sprints_per_patch}``
            closes to a release).
        main_branch: The trunk branch name.
        release_tag_pattern: Release tag template.
        allow_direct_main_commit: MUST NEVER be ``true`` except solo
            bootstrap — kept a plain ``bool`` (not further restricted)
            since the schema's job is shape validation, not policy
            enforcement.
    """

    model_config = ConfigDict(extra="forbid")

    patch_branch_pattern: str = "v{X}.{Y}.{Z}"
    sprint_branch_pattern: str = "v{X}.{Y}.{Z}-dev.{N}"
    patch_slug_pattern: str = "v{X}{Y}{Z}"
    sprint_slug_pattern: str = "v{X}{Y}{Z}-dev{N}"
    sprints_per_patch: int = 10
    main_branch: str = "main"
    release_tag_pattern: str = "v{X}.{Y}.{Z}"
    allow_direct_main_commit: bool = False


# --------------------------------------------------------------------------
# [gates] / [[gates.extra]]
# --------------------------------------------------------------------------
class GateExtraEntry(BaseModel):
    """One ``[[gates.extra]]`` supplementary gate.

    Both fields are genuinely required WITHIN one entry — a gate with no
    name can't be reported and a gate with no command does nothing — the
    one place in this schema besides the root where a bare
    (non-``Optional``) field is deliberate; see the module docstring's
    conservatism note.

    Attributes:
        name: The gate's short label, surfaced in wave/close reports.
        cmd: The shell command to run.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    cmd: str


class GatesConfig(BaseModel):
    """``[gates]`` — between-wave validation.

    Attributes:
        check: Build/typecheck command; empty skips. No single canonical
            default exists (docs: "project-specific") — defaults to the
            empty (skip) string here.
        lint: Lint command; empty skips.
        format: Format command; empty skips.
        extra: Supplementary gates run after the primary three pass.
            ``docs/configuration.md`` and ``examples/rust-service/
            shepherd.toml`` both use a LIST of ``{name, cmd}`` tables
            (``[[gates.extra]]``); this repo's own self-hosted dogfood
            config (``.claude/shepherd.toml``) instead writes
            ``[gates.extra]`` as a single TABLE mapping gate name -> cmd
            string. Both are real, both must validate — accepted as a
            ``list[GateExtraEntry] | dict[str, str]`` union rather than
            picking one shape and failing the dogfood regression check.
        target_clean_threshold_gb: Auto-clean ``target/`` above this size;
            ``0`` disables.
        subtract_paths: Globs scoping SUBTRACT-DON'T-ADD to production
            source. No fixed default (project-specific); defaults to
            empty here.
    """

    model_config = ConfigDict(extra="forbid")

    check: str = ""
    lint: str = ""
    format: str = ""
    extra: list[GateExtraEntry] | dict[str, str] = Field(default_factory=list)
    target_clean_threshold_gb: int = 20
    subtract_paths: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# [dups]
# --------------------------------------------------------------------------
class DupsConfig(BaseModel):
    """``[dups]`` — field-shape dedup (``shctx dups``).

    Not in the task's literal "sections to cover" list, but present
    (either populated, in ``examples/rust-service/shepherd.toml``, or as
    a header-only empty table, in ``examples/minimal/shepherd.toml``) —
    omitting it would make the bundled minimal template fail its own
    "validates clean" regression, so it is covered per the module
    docstring's "full documented surface" scope.

    Attributes:
        dups_threshold: Cluster/report/check similarity floor, 0..1.
        dups_block: Hook DENY threshold, 0..1.
        dups_name_weight: Field-name vs typed-pair Jaccard weight, 0..1.
        dups_min_fields: Ignore shapes below N fields.
        dups_hook: ``off|warn|block`` — PreToolUse(Write|Edit) behavior.
        dups_registry: Concept -> canonical pins / DO-NOT-MERGE allow-list
            path.
    """

    model_config = ConfigDict(extra="forbid")

    dups_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dups_block: float = Field(default=0.85, ge=0.0, le=1.0)
    dups_name_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    dups_min_fields: int = 2
    dups_hook: Literal["off", "warn", "block"] = "warn"
    dups_registry: str = ".shepherd/dups-registry.json"


# --------------------------------------------------------------------------
# [paths]
# --------------------------------------------------------------------------
class PathsConfig(BaseModel):
    """``[paths]`` — artifact locations, relative to the repo root.

    Attributes:
        plans: Cross-run plan docs.
        reports: Cross-run report docs.
        docs: General docs root.
        ctx: Context registry scratch dir.
        runs: Per-run artifact root (``{run_dir}`` = ``{runs}/{run}``).
    """

    model_config = ConfigDict(extra="forbid")

    plans: str = ".shepherd/docs/plans"
    reports: str = ".shepherd/docs/reports"
    docs: str = ".shepherd/docs"
    ctx: str = ".shepherd/ctx"
    runs: str = ".shepherd/runs"


# --------------------------------------------------------------------------
# [skills] (+ open-vocabulary sub-tables)
# --------------------------------------------------------------------------
class SkillsConfig(BaseModel):
    """``[skills]`` — local-skill integration.

    ``by_domain``/``detection`` are OPEN-vocabulary maps (any domain name
    a project invents -> a skill-slug list / glob-pattern list) — see the
    module docstring's open-vs-closed-vocabulary note. They are plain
    ``dict[str, list[str]]``, not nested models, so an unrecognized
    domain name is never flagged as an "unknown key".

    Attributes:
        mandatory: Skill slugs that MUST appear in every ``[SKILLS]``
            block.
        by_domain: Domain name -> skill-slug list.
        detection: Domain name -> glob-pattern list, matched against
            ``[FILE-SCOPE]``.
    """

    model_config = ConfigDict(extra="forbid")

    mandatory: list[str] = Field(default_factory=lambda: ["code-style"])
    by_domain: dict[str, list[str]] = Field(default_factory=dict)
    detection: dict[str, list[str]] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# [ledger]
# --------------------------------------------------------------------------
class LedgerConfig(BaseModel):
    """``[ledger]`` — issue-ledger awareness.

    Attributes:
        phase_0_full_ledger: When true, every sprint open enumerates +
            classifies the FULL open-issue space, not just the current
            milestone.
        classify_into: The classification buckets Phase 0 sorts issues
            into.
        non_issue_labels: Labels that exempt an issue from
            ``blocking-this-sprint`` classification.
        carry_forward_file: Interpolated path to the per-patch
            carry-forward doc.
        chronic_threshold_patches: Patches an issue must survive
            unresolved to be flagged chronic.
    """

    model_config = ConfigDict(extra="forbid")

    phase_0_full_ledger: bool = True
    classify_into: list[str] = Field(
        default_factory=lambda: [
            "blocking-this-sprint",
            "labeled-non-issue",
            "tracking-future",
            "drift-risk",
        ]
    )
    non_issue_labels: list[str] = Field(
        default_factory=lambda: ["wontfix", "tracking-future", "design-question", "rfc"]
    )
    carry_forward_file: str = "{paths.plans}/v{X}.{Y}.{Z}-carry-forwards.md"
    chronic_threshold_patches: int = 2


# --------------------------------------------------------------------------
# [release]
# --------------------------------------------------------------------------
class ReleaseConfig(BaseModel):
    """``[release]`` — release pipeline.

    Attributes:
        driver: ``conductor`` (shepherd drives it) | ``github-workflow``
            (GH Actions does) | ``operator`` (notes only).
        release_notes_path: Interpolated path to the release notes doc.
        workflow_file: Required when ``driver="github-workflow"``.
        devlast_guard: ``block|warn|off`` — refuses a branch numbered
            >= ``sprints_per_patch``.
    """

    model_config = ConfigDict(extra="forbid")

    driver: Literal["conductor", "github-workflow", "operator"] = "github-workflow"
    release_notes_path: str = "{paths.docs}/v{X}.{Y}.{Z}-release-notes.md"
    workflow_file: str = ".github/workflows/release.yml"
    devlast_guard: Literal["block", "warn", "off"] = "block"


# --------------------------------------------------------------------------
# [tmux]
# --------------------------------------------------------------------------
class TmuxConfig(BaseModel):
    """``[tmux]`` — teammate pane observability.

    Attributes:
        pane_cleanup: ``on|off`` — reap panes of closed teammates at
            SessionEnd.
    """

    model_config = ConfigDict(extra="forbid")

    pane_cleanup: Literal["on", "off"] = "on"


# --------------------------------------------------------------------------
# [memory]
# --------------------------------------------------------------------------
class MemoryConfig(BaseModel):
    """``[memory]`` — memory + doctrine paths.

    Attributes:
        project_memory: Read-only auto-memory path.
        project_doctrines: Project DRIFT rules, loaded into every flock
            dispatch.
    """

    model_config = ConfigDict(extra="forbid")

    project_memory: str = "~/.claude/projects/<project>/memory"
    project_doctrines: str = ".claude/doctrines"


# --------------------------------------------------------------------------
# [context] (+ sub-tables)
# --------------------------------------------------------------------------
class ContextRefreshConfig(BaseModel):
    """``[context.refresh]`` — registry refresh staleness.

    Attributes:
        ttl_minutes: Past this age, callers re-refresh before trusting a
            cached row.
    """

    model_config = ConfigDict(extra="forbid")

    ttl_minutes: int = 30


class ContextLockConfig(BaseModel):
    """``[context.lock]`` — single-writer lock staleness.

    Attributes:
        stale_after_minutes: A lock older than this (with a dead PID) is
            reap-eligible. No canonical default is documented in
            ``docs/configuration.md`` prose; ``120`` matches this repo's
            own dogfood config, the best available evidence.
    """

    model_config = ConfigDict(extra="forbid")

    stale_after_minutes: int = 120


class ContextNamingConfig(BaseModel):
    """``[context.naming]`` — ``shctx lint`` overrides.

    Per ``skills/context/references/naming-conventions.md`` §Configuration
    overrides (the current, authoritative shape — supersedes an older
    per-artifact-pattern sketch in a historical design doc).

    Attributes:
        strict: Fail ``shctx status`` on a lint violation instead of
            merely reporting it.
        extra_patterns: Additional accepted filename globs.
        ignore_paths: Subtrees ``shctx lint`` skips entirely.
    """

    model_config = ConfigDict(extra="forbid")

    strict: bool = False
    extra_patterns: list[str] = Field(default_factory=list)
    ignore_paths: list[str] = Field(default_factory=list)


class ContextConfig(BaseModel):
    """``[context]`` — context registry.

    Attributes:
        enabled: DB-optional pre-migration; refused post-migration.
        db_path: SQLite registry file.
        lock_path: Single-writer lock file.
        project_id_path: Stable ``project_id`` file.
        auto_refresh: Additive triggers that fire ``refresh --scope=all``
            automatically.
        announce_shctx_path: ``on|off`` — surfaces the resolved ``shctx``
            path.
        announce_core_doctrine: ``on|off`` — points to the operating
            philosophy doc.
        announce_adaptation: ``on|off`` — surfaces sprint/prior counts +
            newest lesson + trend alert.
        refresh: ``[context.refresh]`` sub-table.
        lock: ``[context.lock]`` sub-table.
        naming: ``[context.naming]`` sub-table.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    db_path: str = ".shepherd/shepherd.db"
    lock_path: str = ".shepherd/shepherd.lock"
    project_id_path: str = ".shepherd/project.json"
    auto_refresh: list[
        Literal["on-sprint-open", "on-engineer-dispatch", "on-close-finalize", "on-wave-gate"]
    ] = Field(default_factory=lambda: ["on-sprint-open"])
    announce_shctx_path: Literal["on", "off"] = "on"
    announce_core_doctrine: Literal["on", "off"] = "on"
    announce_adaptation: Literal["on", "off"] = "on"
    refresh: ContextRefreshConfig = Field(default_factory=ContextRefreshConfig)
    lock: ContextLockConfig = Field(default_factory=ContextLockConfig)
    naming: ContextNamingConfig = Field(default_factory=ContextNamingConfig)


# --------------------------------------------------------------------------
# [hooks]
# --------------------------------------------------------------------------
class HooksConfig(BaseModel):
    """``[hooks]`` — local skill / hook integration.

    Attributes:
        on_every_dispatch: Skills loaded by every flock agent.
        on_conductor_only: Conductor-only skills.
        on_engineer_only: Engineer-only skills.
        on_planter_only: Planter-only skills.
        quiet_warnings: Suppress informational ``additionalContext``
            (still logged).
        flag_handrolled_fanout: ``dispatch_guard.sh`` Check 6 — warn on a
            hand-rolled flock fan-out.
        workflow_model_guard: ``block|warn|off`` — dispatch-model-pin
            gate.
        teammate_heartbeat: ``on|off`` — PreToolUse auto-stamp of
            ``last_seen_at``.
    """

    model_config = ConfigDict(extra="forbid")

    on_every_dispatch: list[str] = Field(default_factory=lambda: ["code-style"])
    on_conductor_only: list[str] = Field(default_factory=list)
    on_engineer_only: list[str] = Field(default_factory=lambda: ["workflow"])
    on_planter_only: list[str] = Field(default_factory=list)
    quiet_warnings: bool = False
    flag_handrolled_fanout: bool = False
    workflow_model_guard: Literal["block", "warn", "off"] = "block"
    teammate_heartbeat: Literal["on", "off"] = "on"


# --------------------------------------------------------------------------
# [spawn]
# --------------------------------------------------------------------------
class SpawnConfig(BaseModel):
    """``[spawn]`` — teammate-spawn coordination.

    Attributes:
        coordinate_drive_guard: ``block|warn|off`` — Stop-hook backstop.
        wave_ack_timeout_sec: Wait before continuing without a wave-ack.
        cross_dep_timeout_sec: Escalates CROSS-DEP-WAIT.
        max_parallel: Upper bound on ``--parallel <N>``.
        dashboard_cadence: ``shctx dash`` loop interval (duration string).
        staged_timeout_minutes: ``--staged`` poll timeout before
            STAGED-TIMEOUT.
        lead_effort: Effort injected into lead sessions at spawn. Kept as
            a plain ``str`` (not a closed ``Literal``) — the docs
            describe an open, evolving effort vocabulary (``"ultracode"``,
            ``"max"``, ``"high"``, ..., or ``"off"`` to leave it unchanged)
            rather than a fixed enum.
        stale_sweep_minutes: Reboot horizon for the lead-session-start
            liveness sweep; ``0`` disables.
    """

    model_config = ConfigDict(extra="forbid")

    coordinate_drive_guard: Literal["block", "warn", "off"] = "block"
    wave_ack_timeout_sec: int = 60
    cross_dep_timeout_sec: int = 300
    max_parallel: int = 4
    dashboard_cadence: str = "3m"
    staged_timeout_minutes: int = 90
    lead_effort: str = "ultracode"
    stale_sweep_minutes: int = 60


# --------------------------------------------------------------------------
# [autorun]
# --------------------------------------------------------------------------
class AutorunConfig(BaseModel):
    """``[autorun]`` — unattended sequential walks.

    Attributes:
        min_grade: Letter-grade floor for continuing an unattended walk.
        on_grade_floor: ``abort|pause|continue``.
        inter_sprint_pause: ``brief|signoff|none``.
    """

    model_config = ConfigDict(extra="forbid")

    min_grade: str = "B"
    on_grade_floor: Literal["abort", "pause", "continue"] = "abort"
    inter_sprint_pause: Literal["brief", "signoff", "none"] = "brief"


# --------------------------------------------------------------------------
# [compaction]
# --------------------------------------------------------------------------
class CompactionConfig(BaseModel):
    """``[compaction]`` — compaction resilience.

    Attributes:
        precompact_snapshot: ``on|off`` — PreCompact hook snapshot;
            never blocks compaction.
        snapshot_retention: Snapshots retained per namespace; ``0`` =
            unlimited.
    """

    model_config = ConfigDict(extra="forbid")

    precompact_snapshot: Literal["on", "off"] = "on"
    snapshot_retention: int = 5


# --------------------------------------------------------------------------
# [focus]
# --------------------------------------------------------------------------
class FocusConfig(BaseModel):
    """``[focus]`` — focus loop rehydration.

    Attributes:
        rehydrate: ``on|off`` — re-inject the latest precompact snapshot
            after compaction.
        heartbeat_actions: Soft self-prompt: re-anchor after ~N actions;
            ``0`` disables.
        heartbeat_interval: ``""`` (off) or a duration string (e.g.
            ``"45m"``) — deterministic wall-clock re-anchor via native
            ``/loop``.
        loop_max_default: Default ``max_iterations`` for FOCUS-LOOP
            (Pattern 6). Not in the ``docs/configuration.md`` table but
            exercised in ``examples/rust-service/shepherd.toml``.
    """

    model_config = ConfigDict(extra="forbid")

    rehydrate: Literal["on", "off"] = "on"
    heartbeat_actions: int = 20
    heartbeat_interval: str = ""
    loop_max_default: int = 8


# --------------------------------------------------------------------------
# [close]
# --------------------------------------------------------------------------
class CloseConfig(BaseModel):
    """``[close]`` — close-phase behavior.

    Attributes:
        autonomous_sentinel: ``off|on`` — ``on`` alone does nothing; the
            seed MUST ALSO declare ``close: autonomous-sentinel`` plus a
            complete ``sentinel_rails`` block (enforced elsewhere, not by
            this schema).
    """

    model_config = ConfigDict(extra="forbid")

    autonomous_sentinel: Literal["off", "on"] = "off"


# --------------------------------------------------------------------------
# [eval]
# --------------------------------------------------------------------------
class EvalConfig(BaseModel):
    """``[eval]`` — latent-output eval harness (``services/eval``).

    Attributes:
        eval_judge_model: Model alias; empty string means "use ``opus``"
            (never a silent downgrade).
        eval_on_close: ``on|off`` — auto-runs the reflection eval at
            CLOSE-FINALIZE.
    """

    model_config = ConfigDict(extra="forbid")

    eval_judge_model: str = ""
    eval_on_close: Literal["on", "off"] = "off"


# --------------------------------------------------------------------------
# [models]
# --------------------------------------------------------------------------
class ModelsConfig(BaseModel):
    """``[models]`` — per-role subagent model map.

    Every role field is a free-text model alias/slug, not a closed
    ``Literal`` — the set of valid model slugs is external and evolving
    (``skills/context/references/model-map.md`` is the source of truth
    at dispatch time; validating it here would mean re-deriving and
    keeping in sync with that list, which is exactly the kind of drift
    this schema exists to avoid introducing).

    Attributes:
        root: Advisory only — names the model the live root session
            SHOULD run.
        planter: Model for the planter role.
        engineer: Model for the engineer role.
        conductor: Model for the conductor role.
        critic: Model for the critic role.
        discovery: Model for the discovery role.
        coder: Model for the coder role.
        auditor: Model for the auditor role.
        worker: Model for the worker role.
    """

    model_config = ConfigDict(extra="forbid")

    root: str = "opus[1m]"
    planter: str = "opus[1m]"
    engineer: str = "opus[1m]"
    conductor: str = "sonnet"
    critic: str = "sonnet"
    discovery: str = "sonnet"
    coder: str = "sonnet"
    auditor: str = "sonnet"
    worker: str = "sonnet"


# --------------------------------------------------------------------------
# [prune]
# --------------------------------------------------------------------------
class PruneConfig(BaseModel):
    """``[prune]`` — workdir + registry GC retention windows.

    Attributes:
        logs_days: Age floor for ``logs/events-*.jsonl`` +
            ``logs/hooks/*.jsonl``.
        dispatch_days: Age floor for stale ``dispatch/<sprint>/`` dirs.
        snapshots_keep: Precompact snapshots retained, newest-first.
        findings_sprints: Keep discovery/audit findings for the last N
            sprints.
    """

    model_config = ConfigDict(extra="forbid")

    logs_days: int = 60
    dispatch_days: int = 30
    snapshots_keep: int = 20
    findings_sprints: int = 6


# --------------------------------------------------------------------------
# [seed]
# --------------------------------------------------------------------------
class SeedConfig(BaseModel):
    """``[seed]`` — seed authoring gate.

    Not in ``docs/configuration.md`` (undocumented there at time of
    writing); ``seed_gate`` is a real, exercised key
    (``hooks/scripts/seed_preflight_check.sh``, ``skills/shepherd/
    references/seed-template.md`` §Verification).

    Attributes:
        seed_gate: ``block|warn|off`` — the ``PreToolUse(Write)``
            SEED-GATE hook's enforcement level.
    """

    model_config = ConfigDict(extra="forbid")

    seed_gate: Literal["block", "warn", "off"] = "block"


# --------------------------------------------------------------------------
# [preflight]
# --------------------------------------------------------------------------
class PreflightConfig(BaseModel):
    """``[preflight]`` — entry-command preflight.

    Not in ``docs/configuration.md``; derived from this repo's own
    ``.claude/shepherd.toml``, the only observed usage.

    Attributes:
        auto_invoke: The preflight check to auto-run. Kept a plain
            ``str`` (only ``"doctor"`` is attested) rather than a closed
            enum, since no second value is documented anywhere.
    """

    model_config = ConfigDict(extra="forbid")

    auto_invoke: str = "doctor"


# --------------------------------------------------------------------------
# [stage_graph] (+ [stage_graph.intro_wave])
# --------------------------------------------------------------------------
class StageGraphIntroWaveConfig(BaseModel):
    """``[stage_graph.intro_wave]`` — INTRO-COMBO-WAVE defaults.

    Not in ``docs/configuration.md``; derived from this repo's own
    ``.claude/shepherd.toml`` (§``skills/shepherd/references/pipeline.md``
    §Combo waves documents the BEHAVIOR, not the TOML shape). Defaults
    below match the dogfood config, the only observed instance.

    Attributes:
        enabled: Always-on under ``/shepherd:spawn`` when true.
        default_discoveries: Default ``@discovery`` lane topics.
        default_intro_auditors: Default intro-mode ``@auditor`` lane
            topics.
        disable_for_tshirt: T-shirt sizes that skip the intro wave in
            SOLO mode only (each ``--parallel``/``--auto`` sibling still
            certifies its own context fresh).
        parallel_max: Upper bound on total intro-wave lanes.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    default_discoveries: list[str] = Field(default_factory=list)
    default_intro_auditors: list[str] = Field(default_factory=list)
    disable_for_tshirt: list[str] = Field(default_factory=list)
    parallel_max: int = 5


class StageGraphConfig(BaseModel):
    """``[stage_graph]`` — Stage Graph walk defaults.

    Not in ``docs/configuration.md``; see :class:`StageGraphIntroWaveConfig`.

    Attributes:
        default_wave_count: Default number of implementation waves.
        hotfix_max_iterations: REDO/HOTFIX loop cap before
            REDO-CAP-EXCEEDED / HARD-STOP.
        walk_trace_enabled: Whether the conductor's walk emits a trace
            log.
        intro_wave: ``[stage_graph.intro_wave]`` sub-table.
    """

    model_config = ConfigDict(extra="forbid")

    default_wave_count: int = 2
    hotfix_max_iterations: int = 3
    walk_trace_enabled: bool = True
    intro_wave: StageGraphIntroWaveConfig = Field(default_factory=StageGraphIntroWaveConfig)


# --------------------------------------------------------------------------
# [mcp] / [cli] — open-vocabulary boolean maps (NOT nested models; see the
# module docstring's open-vs-closed-vocabulary design note).
# --------------------------------------------------------------------------
_MCP_TYPE = dict[str, bool]
_CLI_TYPE = dict[str, bool]


# --------------------------------------------------------------------------
# Root document.
# --------------------------------------------------------------------------
class ShepherdConfig(BaseModel):
    """The full ``shepherd.toml`` surface — one tier's worth.

    Every field is independently optional/defaulted (see the module
    docstring), so ``ShepherdConfig.model_validate({})`` succeeds and
    equals the all-defaults config: a file that sets nothing is valid by
    construction, exactly like an absent file resolving to built-in
    defaults per ``docs/configuration.md`` §Defaults.

    Attributes:
        project: ``[project]``.
        branching: ``[branching]``.
        paths: ``[paths]``.
        gates: ``[gates]`` (+ ``[[gates.extra]]``).
        dups: ``[dups]``.
        skills: ``[skills]`` (+ ``by_domain``/``detection``).
        mcp: ``[mcp]`` — open-vocabulary server-name -> bool map.
        cli: ``[cli]`` — open-vocabulary binary-name -> bool map.
        ledger: ``[ledger]``.
        release: ``[release]``.
        tmux: ``[tmux]``.
        memory: ``[memory]``.
        context: ``[context]`` (+ ``refresh``/``lock``/``naming``).
        hooks: ``[hooks]``.
        spawn: ``[spawn]``.
        autorun: ``[autorun]``.
        compaction: ``[compaction]``.
        focus: ``[focus]``.
        close: ``[close]``.
        eval: ``[eval]``.
        models: ``[models]``.
        prune: ``[prune]``.
        seed: ``[seed]``.
        preflight: ``[preflight]``.
        stage_graph: ``[stage_graph]`` (+ ``intro_wave``).
    """

    model_config = ConfigDict(extra="forbid")

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    branching: BranchingConfig = Field(default_factory=BranchingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    dups: DupsConfig = Field(default_factory=DupsConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    mcp: _MCP_TYPE = Field(default_factory=dict)
    cli: _CLI_TYPE = Field(default_factory=dict)
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    tmux: TmuxConfig = Field(default_factory=TmuxConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    spawn: SpawnConfig = Field(default_factory=SpawnConfig)
    autorun: AutorunConfig = Field(default_factory=AutorunConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    focus: FocusConfig = Field(default_factory=FocusConfig)
    close: CloseConfig = Field(default_factory=CloseConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    prune: PruneConfig = Field(default_factory=PruneConfig)
    seed: SeedConfig = Field(default_factory=SeedConfig)
    preflight: PreflightConfig = Field(default_factory=PreflightConfig)
    stage_graph: StageGraphConfig = Field(default_factory=StageGraphConfig)


#: Every top-level table name this schema recognizes, in declaration order
#: — used by :func:`_convert_error`'s did-you-mean for an unknown SECTION.
KNOWN_SECTIONS: tuple[str, ...] = tuple(ShepherdConfig.model_fields.keys())


# --------------------------------------------------------------------------
# Validation report types.
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ConfigIssue:
    """One problem found in one config file.

    Attributes:
        path: ``[section.sub].key`` (or ``[section]`` for a whole
            unrecognized section) locating the problem within the file.
            Empty string for a file-level problem (unreadable file,
            invalid TOML syntax) that predates any key-level location.
        kind: One of ``"parse_error"``, ``"read_error"``,
            ``"unknown_section"``, ``"unknown_key"``, ``"missing_field"``,
            ``"invalid_value"``.
        message: Human-readable description of the problem.
        bad_value: The offending value's ``repr()``, when known.
        allowed: The allowed value set, for an enum/``Literal`` field
            violation.
        suggestion: The did-you-mean candidate, for an unknown
            key/section.
    """

    path: str
    kind: str
    message: str
    bad_value: str | None = None
    allowed: tuple[str, ...] | None = None
    suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigFileReport:
    """The validation result for one config file (one precedence tier).

    Attributes:
        file: The file path (or another caller-supplied label) this
            report describes.
        ok: True iff ``issues`` is empty.
        issues: Every problem found, in the order pydantic reported them.
    """

    file: str
    ok: bool
    issues: tuple[ConfigIssue, ...]


# --------------------------------------------------------------------------
# Model-tree introspection (did-you-mean candidates + allowed-value sets).
# --------------------------------------------------------------------------
def _unwrap_to_model(annotation: object) -> type[BaseModel] | None:
    """Peel ``Optional``/``list`` wrappers off ``annotation`` to find a ``BaseModel``.

    Args:
        annotation: A resolved (non-string) type annotation, e.g. a
            pydantic ``FieldInfo.annotation`` value.

    Returns:
        The innermost ``BaseModel`` subclass, or None when ``annotation``
        never wraps one (a plain ``str``/``dict``/``list[str]``/... leaf).
    """
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        for arg in typing.get_args(annotation):
            if arg is type(None):
                continue
            found = _unwrap_to_model(arg)
            if found is not None:
                return found
        return None
    if origin is list:
        args = typing.get_args(annotation)
        return _unwrap_to_model(args[0]) if args else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _find_literal_args(annotation: object) -> tuple[object, ...] | None:
    """Find the ``Literal[...]`` allowed-value tuple inside ``annotation``, if any.

    Handles a bare ``Literal[...]``, ``Optional[Literal[...]]``, and
    ``list[Literal[...]]`` (e.g. ``[context].auto_refresh``).

    Args:
        annotation: A resolved (non-string) type annotation.

    Returns:
        The ``Literal[...]`` args tuple, or None when no ``Literal``
        appears anywhere in ``annotation``.
    """
    origin = typing.get_origin(annotation)
    if origin is Literal:
        return typing.get_args(annotation)
    if origin is typing.Union or origin is types.UnionType:
        for arg in typing.get_args(annotation):
            found = _find_literal_args(arg)
            if found is not None:
                return found
        return None
    if origin is list:
        args = typing.get_args(annotation)
        return _find_literal_args(args[0]) if args else None
    return None


def _resolve_container_model(root: type[BaseModel], loc_prefix: tuple[object, ...]) -> type[BaseModel] | None:
    """Walk ``loc_prefix`` from ``root`` to the ``BaseModel`` governing that nesting level.

    Args:
        root: The model class to start from (always :class:`ShepherdConfig`
            in this module).
        loc_prefix: A pydantic error ``loc`` tuple with the FINAL segment
            already dropped (the segment being looked up, not the
            container it lives in). Integer segments (list indices) are
            skipped — they don't change which model governs the level,
            since the list's item model was already resolved by the
            field lookup one step earlier.

    Returns:
        The governing model class, or None when the path leads through a
        non-model field (e.g. into ``[mcp]``'s open ``dict[str, bool]``)
        or an unresolvable segment.
    """
    current: type[BaseModel] | None = root
    for segment in loc_prefix:
        if isinstance(segment, int):
            continue
        if current is None:
            return None
        field = current.model_fields.get(str(segment))
        if field is None:
            return None
        current = _unwrap_to_model(field.annotation)
    return current


def _resolve_field(root: type[BaseModel], loc: tuple[object, ...]):
    """Resolve the pydantic ``FieldInfo`` an error ``loc`` tuple points at.

    Trailing int segments (list indices) are stripped first: a
    ``list[Literal[...]]`` field like ``[context].auto_refresh`` reports a
    bad ITEM's error at ``loc=("context", "auto_refresh", 0)`` — the
    offending FIELD is still ``auto_refresh`` (whose annotation
    :func:`_find_literal_args` already knows how to unwrap a list from),
    not something one level deeper that doesn't exist.

    Args:
        root: The model class to start from (:class:`ShepherdConfig`).
        loc: A full pydantic error ``loc`` tuple, including the final
            (offending) segment.

    Returns:
        The ``FieldInfo`` for the offending key, or None when it can't be
        resolved (an open-vocabulary ``dict`` value, a bad list-item shape
        with no leading key at all, or an unresolvable path).
    """
    trimmed = loc
    while trimmed and isinstance(trimmed[-1], int):
        trimmed = trimmed[:-1]
    if not trimmed:
        return None
    container = _resolve_container_model(root, trimmed[:-1])
    if container is None:
        return None
    return container.model_fields.get(str(trimmed[-1]))


def _known_keys(model: type[BaseModel] | None) -> tuple[str, ...]:
    """The declared field names of ``model``, or an empty tuple when ``model`` is None."""
    if model is None:
        return ()
    return tuple(model.model_fields.keys())


def _suggest(name: str, candidates: tuple[str, ...]) -> str | None:
    """A single ``difflib`` did-you-mean candidate for ``name`` among ``candidates``.

    Args:
        name: The unrecognized key/section name as written in the file.
        candidates: The known key/section names at that nesting level.

    Returns:
        The best fuzzy match, or None when nothing scores above the
        cutoff (``difflib.get_close_matches``' default-ish ``0.6``).
    """
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _format_path(loc: tuple[object, ...]) -> str:
    """Render a pydantic error ``loc`` tuple as ``[section.sub].key``.

    Args:
        loc: A pydantic ``ErrorDetails["loc"]`` tuple.

    Returns:
        ``"[section.sub].key"`` for a nested key, ``"[section]"`` for a
        bare unrecognized top-level section, or ``"[section.sub][N]"``
        when the offending element is itself a whole list item (its
        ``loc`` ends in an int, not a key name). Empty string for an
        empty ``loc`` (a whole-document-level problem).
    """
    if not loc:
        return ""
    *prefix, last = loc
    section_parts = [str(p) for p in prefix if not isinstance(p, int)]
    if isinstance(last, int):
        base = f"[{'.'.join(section_parts)}]" if section_parts else ""
        return f"{base}[{last}]"
    if section_parts:
        return f"[{'.'.join(section_parts)}].{last}"
    return f"[{last}]"


# --------------------------------------------------------------------------
# Error conversion.
# --------------------------------------------------------------------------
def _convert_error(err: dict) -> ConfigIssue:
    """Convert one ``pydantic.ValidationError.errors()`` row to a :class:`ConfigIssue`.

    Args:
        err: One entry from ``ValidationError.errors()``.

    Returns:
        The corresponding :class:`ConfigIssue`.
    """
    loc = tuple(err["loc"])
    err_type = err["type"]
    path = _format_path(loc)

    if err_type == "extra_forbidden":
        key = str(loc[-1]) if loc else ""
        container = _resolve_container_model(ShepherdConfig, loc[:-1])
        known = _known_keys(container)
        suggestion = _suggest(key, known)
        is_section = len(loc) == 1
        kind = "unknown_section" if is_section else "unknown_key"
        noun = "section" if is_section else "key"
        message = f"unknown {noun} '{key}'"
        if suggestion:
            message += f" (did you mean '{suggestion}'?)"
        return ConfigIssue(path=path, kind=kind, message=message, suggestion=suggestion)

    if err_type == "missing":
        key = str(loc[-1]) if loc else ""
        return ConfigIssue(path=path, kind="missing_field", message=f"missing required key '{key}'")

    field = _resolve_field(ShepherdConfig, loc)
    allowed = _find_literal_args(field.annotation) if field is not None else None
    bad_value = repr(err.get("input"))
    key = str(loc[-1]) if loc and not isinstance(loc[-1], int) else path
    if allowed:
        # Build our own message rather than pydantic's own ("Input should be
        # 'a', 'b' or 'c'") — naming the KEY explicitly (pydantic's message
        # never does) and listing the allowed set exactly once instead of
        # in both prose and the structured `allowed` field.
        allowed_display = ", ".join(repr(a) for a in allowed)
        message = f"'{key}' got {bad_value} — allowed: {allowed_display}"
    else:
        message = str(err.get("msg", "invalid value"))
    return ConfigIssue(
        path=path,
        kind="invalid_value",
        message=message,
        bad_value=bad_value,
        allowed=tuple(str(a) for a in allowed) if allowed else None,
    )


# --------------------------------------------------------------------------
# Public API.
# --------------------------------------------------------------------------
#: Key names that carry a credential by convention. Matched case-insensitively
#: against the LEAF key name anywhere in the document.
_SECRET_KEY_RE = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|access[_-]?key|private[_-]?key"
    r"|credential|auth[_-]?key|client[_-]?secret|webhook[_-]?url)",
    re.IGNORECASE,
)

#: A shell/env interpolation in a VALUE: ``$VAR`` or ``${VAR}``. Config is not
#: shell -- shepherd never expands these -- so one here is either a leaked
#: machine-specific value or a misunderstanding; both belong in *.local.toml.
_ENV_REF_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")

#: Literal credential shapes worth catching even under an innocuous key name.
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def _walk_scalars(node: object, prefix: str = "") -> "list[tuple[str, object]]":
    """Flatten a parsed TOML document to ``(dotted.path, scalar)`` pairs.

    Args:
        node: A parsed TOML value (dict, list, or scalar).
        prefix: The dotted path accumulated so far.

    Returns:
        Every scalar leaf with its dotted path. List elements are indexed
        (``key[0]``) so a finding names the exact element.
    """
    found: list[tuple[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found += _walk_scalars(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += _walk_scalars(value, f"{prefix}[{index}]")
    else:
        found.append((prefix, node))
    return found


def scan_tracked_secrets(document: dict, *, file_label: str) -> list[ConfigIssue]:
    """Find credential-shaped content in a config file that git TRACKS.

    v6.4.2 layering (operator directive): ``shepherd.toml`` and
    ``shepherd.<harness>.toml`` are committed, so they must carry only
    portable project/harness knobs. Anything machine-specific or secret --
    credentials, and env-var references, which shepherd never expands
    anyway -- belongs in ``shepherd.local.toml``, which is gitignored.

    This is a HYGIENE gate, not a security boundary: it catches the
    plausible mistake (a token pasted into the tracked file because that
    is the file the operator had open), not a determined exfiltration. A
    finding is reported against the tracked file with the fix named, so
    the operator moves the key rather than committing it.

    Only ever called for tracked tiers -- ``*.local.toml`` is exactly
    where these values are SUPPOSED to live, so flagging them there would
    invert the contract.

    Args:
        document: The parsed TOML document.
        file_label: The file the findings are reported against.

    Returns:
        One issue per offending scalar, in document order. Values are
        never echoed back: a leaked secret must not be duplicated into a
        log or a CI transcript by the very check that found it.
    """
    issues: list[ConfigIssue] = []
    for dotted, value in _walk_scalars(document):
        leaf = dotted.rsplit(".", 1)[-1].split("[")[0]
        if _SECRET_KEY_RE.search(leaf):
            issues.append(
                ConfigIssue(
                    path=dotted,
                    kind="tracked_secret",
                    message=(
                        f"{file_label} is tracked in git, so it must not carry a "
                        f"credential-shaped key; move '{dotted}' to shepherd.local.toml"
                    ),
                )
            )
            continue
        if not isinstance(value, str):
            continue
        if _SECRET_VALUE_RE.search(value):
            issues.append(
                ConfigIssue(
                    path=dotted,
                    kind="tracked_secret",
                    message=(
                        f"{file_label} is tracked in git and '{dotted}' looks like a "
                        f"credential; move it to shepherd.local.toml"
                    ),
                )
            )
        elif _ENV_REF_RE.search(value):
            issues.append(
                ConfigIssue(
                    path=dotted,
                    kind="tracked_env_ref",
                    message=(
                        f"'{dotted}' references an environment variable, which shepherd "
                        f"never expands; {file_label} is tracked in git, so machine-specific "
                        f"values belong in shepherd.local.toml"
                    ),
                )
            )
    return issues


def validate_config_text(text: str, *, file_label: str) -> ConfigFileReport:
    """Validate raw TOML text against :class:`ShepherdConfig`.

    Args:
        text: The file's raw text.
        file_label: The path/label to stamp onto the returned report and
            (by the caller, via :func:`format_report`) every rendered
            issue line — every issue must be traceable to the FILE it
            came from, since the same key may be set across up to 5
            precedence tiers.

    Returns:
        A :class:`ConfigFileReport` — ``ok=True`` with no issues on a
        clean file; otherwise one :class:`ConfigIssue` per problem
        (parse failure short-circuits with a single ``"parse_error"``
        issue, since a syntactically invalid file has no field-level
        structure to walk).
    """
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        issue = ConfigIssue(path="", kind="parse_error", message=f"invalid TOML syntax: {exc}")
        return ConfigFileReport(file=file_label, ok=False, issues=(issue,))

    try:
        ShepherdConfig.model_validate(raw)
    except ValidationError as exc:
        issues = tuple(_convert_error(err) for err in exc.errors())
        return ConfigFileReport(file=file_label, ok=False, issues=issues)

    return ConfigFileReport(file=file_label, ok=True, issues=())


def validate_config_tier(path: str, *, tracked: bool) -> ConfigFileReport:
    """Validate one tier file, adding the tracked-secret gate when it is committed.

    Args:
        path: The file to validate.
        tracked: True when git tracks this file (``shepherd.toml`` and
            ``shepherd.<harness>.toml`` inside the repo). ``*.local.toml``
            is gitignored and the user/XDG tiers live outside the repo, so
            all of those pass ``False`` — they are exactly where a
            machine-specific or secret value is SUPPOSED to live.

    Returns:
        The schema report, with any tracked-secret findings appended.
    """
    report = validate_config_file(path)
    if not tracked:
        return report
    if report.issues and report.issues[0].kind in {"read_error", "parse_error"}:
        return report  # unreadable/unparseable -- nothing to scan, and already reported
    try:
        with open(path, "rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return report
    extra = scan_tracked_secrets(document, file_label=path)
    if not extra:
        return report
    issues = (*report.issues, *extra)
    return ConfigFileReport(file=report.file, ok=False, issues=issues)


def validate_config_file(path: str) -> ConfigFileReport:
    """Validate the ``shepherd.toml`` at ``path``.

    Args:
        path: The file to read and validate.

    Returns:
        A :class:`ConfigFileReport`. An unreadable file (missing,
        permission-denied, not valid UTF-8) reports a single
        ``"read_error"`` issue rather than raising — this function is a
        boundary, callers (the ``config validate`` CLI subcommand) drive
        it over N candidate paths and must not abort on the first
        problem.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        issue = ConfigIssue(path="", kind="read_error", message=f"cannot read file: {exc}")
        return ConfigFileReport(file=path, ok=False, issues=(issue,))
    return validate_config_text(text, file_label=path)


def format_report(report: ConfigFileReport) -> str:
    """Render one :class:`ConfigFileReport` as a human-readable multi-line block.

    Every line names the file (``report.file``) and, for a field-level
    issue, the ``[section].key`` path — the "must name the FILE and the
    ``[section].key``" requirement, satisfied at the render layer so
    :class:`ConfigIssue` itself can stay a plain structured record (also
    consumed directly, unrendered, by ``--json``).

    Args:
        report: The report to render.

    Returns:
        ``"<file>: OK\\n"`` when clean; otherwise a header line plus one
        indented ``"  - <path> <message>"`` line per issue, newline
        terminated.
    """
    if report.ok:
        return f"{report.file}: OK\n"
    lines = [f"{report.file}: {len(report.issues)} issue(s)"]
    for issue in report.issues:
        location = f" {issue.path}" if issue.path else ""
        lines.append(f"  -{location} {issue.message}")
    return "\n".join(lines) + "\n"


def report_to_dict(report: ConfigFileReport) -> dict:
    """Render one :class:`ConfigFileReport` as a JSON-serializable dict.

    Args:
        report: The report to render.

    Returns:
        A dict with keys ``file``, ``ok``, ``issues`` (a list of dicts,
        one per :class:`ConfigIssue`, ``None`` in place of any unset
        optional field).
    """
    return {
        "file": report.file,
        "ok": report.ok,
        "issues": [
            {
                "path": issue.path,
                "kind": issue.kind,
                "message": issue.message,
                "bad_value": issue.bad_value,
                "allowed": list(issue.allowed) if issue.allowed else None,
                "suggestion": issue.suggestion,
            }
            for issue in report.issues
        ],
    }


__all__ = [
    "ShepherdConfig",
    "ProjectConfig",
    "BranchingConfig",
    "GatesConfig",
    "GateExtraEntry",
    "DupsConfig",
    "PathsConfig",
    "SkillsConfig",
    "LedgerConfig",
    "ReleaseConfig",
    "TmuxConfig",
    "MemoryConfig",
    "ContextConfig",
    "ContextRefreshConfig",
    "ContextLockConfig",
    "ContextNamingConfig",
    "HooksConfig",
    "SpawnConfig",
    "AutorunConfig",
    "CompactionConfig",
    "FocusConfig",
    "CloseConfig",
    "EvalConfig",
    "ModelsConfig",
    "PruneConfig",
    "SeedConfig",
    "PreflightConfig",
    "StageGraphConfig",
    "StageGraphIntroWaveConfig",
    "KNOWN_SECTIONS",
    "ConfigIssue",
    "ConfigFileReport",
    "validate_config_text",
    "validate_config_file",
    "format_report",
    "report_to_dict",
]
