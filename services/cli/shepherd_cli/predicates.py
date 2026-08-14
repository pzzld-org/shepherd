"""The ONE guard-predicate evaluator (DF-76): ``shepherd guard eval``'s engine.

Interprets ``content/predicates/*.toml`` (the harness-neutral guard-predicate
spec — four files: ``dedup-gate``, ``dispatch-scope``, ``git-custody``,
``write-boundary``) plus ``content/roles/*.md`` (per-role facts: tier,
``write_eligible``, ``capabilities``) into exactly one of three verdicts —
``allow``, ``deny``, ``unresolved`` — for either a normalized
``(role, predicate, action, context)`` tuple an adapter already resolved, or
a RAW tool call this module itself maps onto that tuple (:func:`Engine.evaluate`
below documents both request shapes; ``shepherd_cli.commands.guard`` is the
thin CLI wrapper around this module — stdin JSON in, stdout JSON out, no
predicate logic of its own).

Every one of the three harness adapters (Claude, Codex, Pi) shelled out to a
``shepherd guard eval`` CLI surface that never existed (DF-76's own finding)
and no plan step ever built — each hand-rolled its own interpreter
instead, including three separate copies of a git-subcommand tokenizer. This
module is that missing engine, and ``services/cli/shepherd_cli/`` — not
``crates/cli`` (a near-empty binary, one subcommand: ``Init``) — is where
``bin/shepherd``'s own header says the canonical CLI surface lives. A later
Rust port follows the pattern ``crates/core/src/run.rs`` already established
for ``models_run.py``: THIS module is the reference implementation and the
behavioral oracle; ``content/predicates/*.toml``'s ``[[example]]`` corpus
(replayed in full by ``shepherd guard test`` / :func:`Engine.run_conformance_suite`)
is the conformance suite that keeps any second implementation honest.

Ported from two prior, now-superseded per-harness interpreters (correctness
lives here now; collapsing THEIR duplicated logic onto this engine is a later
step, out of this step's file scope):

- ``packages/harness-codex/src/predicates.mjs`` — the data-driven
  ``EFFECT_HANDLERS`` table :data:`EFFECT_HANDLERS` below mirrors verbatim
  (same ten effect names, same semantics), plus its resolved FINDING against
  ``write-boundary.toml`` rule 1's wording ("denied outright" vs its own
  ``discovery-writes-its-one-declared-output-path`` example): read
  ``path_in_dispatch_write_scope`` as the decisive signal, not a literal
  outright reading of rule 1 alone. :func:`evaluate_predicate` preserves that
  same resolution (it is what makes every ``write-boundary.toml`` example
  pass, discovery's narrow report-path grant included).
- ``packages/harness-pi/src/guard.ts`` — the ONLY one of the two prior
  interpreters that ever emitted halt codes (Codex's ``evaluate()`` returns
  none). :func:`_write_boundary_halt_code` harvests its ``evalWriteBoundary``
  role-capability branch (a role's ``content/roles/<role>.md`` ``capabilities``
  decide ``DISCOVERY-WRITE-PATH`` vs no halt code at all — two
  ``write-boundary.toml`` examples share byte-identical ``context`` and
  differ only by ``role``, so this is not optional). Every other predicate's
  halt code is instead HARVESTED from the corpus itself
  (:func:`_harvest_halt_codes`): never hand-transcribed, so a TOML edit that
  drops or renames a halt code is caught by ``shepherd guard test``, not
  silently stale here.
- ``hooks/scripts/coder_git_guard.sh`` — :func:`extract_git_subcommands`
  ports its embedded python3 tokenizer line for line (global-option skip via
  ``takes_arg``, ``eval``/shell-``-c`` recursion, glued-metacharacter cut).

HALT CODES are never invented: a rule with no ``[[example]].halt_code``
anywhere in the corpus emits none, full stop (see :func:`_harvest_halt_codes`'s
docstring for exactly how "none" is distinguished from "not yet tested").
"""

from __future__ import annotations

import os
import re
import shlex
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from shepherd_cli.resolution import resolve_repo_root

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class PredicateError(Exception):
    """The ENGINE itself failed to reach a verdict — never a decision.

    Raised only for things a request could not possibly recover from on its
    own: ``content/`` cannot be located, a ``*.toml`` file carries no
    ``[predicate].id``, or a rule's ``effect`` names no known handler. The
    CLI (``shepherd_cli.commands.guard``) catches this at the process
    boundary and exits non-zero with NO verdict JSON printed — the contract's
    "exit != 0 means the ENGINE failed... never a verdict." An ordinary
    allow/deny/unresolved outcome is always a :class:`Verdict`, never this.
    """


# --------------------------------------------------------------------------
# content/roles/*.md — role facts (tier, write_eligible, capabilities)
# --------------------------------------------------------------------------

#: Transcribed, not read from frontmatter — tier is NOT a
#: ``content/roles/*.md`` field (mirrors ``packages/harness-pi/src/roles.mjs``'s
#: own ``ROLE_TIER``, whose header explains why: two prose sources —
#: ``skills/shepherd/SKILL.md`` §Dispatch law and
#: ``content/predicates/dispatch-scope.toml``'s own rule prose — carry this
#: fact, no machine-readable frontmatter field does).
ROLE_TIER: Mapping[str, str] = {
    "shepherd": "root",
    "planter": "meta",
    "conductor": "lane-lead",
    "engineer": "plan-author",
    "critic": "implementer",
    "coder": "implementer",
    "auditor": "implementer",
    "discovery": "implementer",
    "worker": "implementer",
}

#: ``dispatch-scope.toml`` rule ``plan-authorship-and-gating-are-root-tier-exclusive``'s
#: own target set, named verbatim in that rule's ``description``.
PLAN_OR_GATE_TARGET_ROLES: frozenset[str] = frozenset({"engineer", "critic"})

_FRONTMATTER_RE = re.compile(r"^---\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RoleFact:
    """One ``content/roles/<role>.md`` frontmatter, the fields this engine needs."""

    role: str
    write_eligible: bool
    dispatchable: bool
    capabilities: tuple[str, ...] = ()


def _extract_frontmatter(text: str) -> str | None:
    """The YAML block between a leading and matching ``---`` line, or None."""
    parts = _FRONTMATTER_RE.split(text)
    return parts[1] if len(parts) >= 3 else None


def load_role_facts(content_dir: str) -> dict[str, RoleFact]:
    """Parse every ``content/roles/*.md`` frontmatter into a :class:`RoleFact`.

    Args:
        content_dir: Absolute path to ``content/`` (parent of ``roles/``).

    Returns:
        ``{role_id: RoleFact}``, empty if ``content/roles/`` does not exist —
        a missing roles directory is a valid (if degraded) engine state for
        predicates that never need role facts, not a load-time failure.

    Raises:
        PredicateError: a ``*.md`` file carries no frontmatter block or no
            ``role:`` key — both mean the file is not a real role source and
            the engine cannot trust anything else it says either.
    """
    roles_dir = os.path.join(content_dir, "roles")
    facts: dict[str, RoleFact] = {}
    if not os.path.isdir(roles_dir):
        return facts
    for filename in sorted(os.listdir(roles_dir)):
        if not filename.endswith(".md"):
            continue
        text = Path(roles_dir, filename).read_text(encoding="utf-8")
        frontmatter_text = _extract_frontmatter(text)
        if frontmatter_text is None:
            raise PredicateError(f"{filename}: missing YAML frontmatter")
        frontmatter = yaml.safe_load(frontmatter_text) or {}
        role = frontmatter.get("role")
        if not role:
            raise PredicateError(f"{filename}: missing `role:` in frontmatter")
        facts[role] = RoleFact(
            role=role,
            write_eligible=bool(frontmatter.get("write_eligible", False)),
            dispatchable=bool(frontmatter.get("dispatchable", True)),
            capabilities=tuple(frontmatter.get("capabilities") or ()),
        )
    return facts


# --------------------------------------------------------------------------
# content/predicates/*.toml — the predicate corpus
# --------------------------------------------------------------------------

#: An example's canonical top-level keys — anything else (``target_role``,
#: ``target_branch``, ``path``, ``symbol``, ...) is a flattenable "extra" that
#: merges into its evaluation context. Mirrors
#: ``packages/harness-pi/test/guard-predicates.test.mjs``'s own
#: ``CANONICAL_EXAMPLE_KEYS``.
_CANONICAL_EXAMPLE_KEYS = frozenset({"name", "kind", "role", "action", "context", "result", "halt_code", "note"})


@dataclass(frozen=True, slots=True)
class Rule:
    """One ``[[rule]]`` table from a ``content/predicates/*.toml`` file."""

    id: str
    description: str
    subject: str
    action: str
    effect: str


@dataclass(frozen=True, slots=True)
class PredicateDoc:
    """One parsed ``content/predicates/*.toml`` file: its rules and its examples.

    ``examples`` stays a tuple of raw TOML tables (not a typed model) — the
    ``[[example]]`` shape is deliberately heterogeneous across the four files
    (``target_role``, ``target_branch``, ``path``, ``symbol`` each appear in
    exactly one file's corpus), and the only two consumers
    (:func:`Engine.run_conformance_suite`, ``shepherd guard explain``) both
    want the raw table, not a narrowed subset of it.
    """

    id: str
    version: int
    description: str
    rules: tuple[Rule, ...] = field(default_factory=tuple)
    examples: tuple[Mapping[str, object], ...] = field(default_factory=tuple)


def load_predicates(content_dir: str) -> dict[str, PredicateDoc]:
    """Parse every ``content/predicates/*.toml`` into a :class:`PredicateDoc`.

    Args:
        content_dir: Absolute path to ``content/`` (parent of ``predicates/``).

    Returns:
        ``{predicate_id: PredicateDoc}``, empty if ``content/predicates/``
        does not exist or holds zero ``*.toml`` files — deliberately not an
        error here (``shepherd guard test`` is the place a zero-corpus load
        is treated as a hard failure, DF-59; ``load_predicates`` itself stays
        a pure loader).

    Raises:
        PredicateError: a ``*.toml`` file carries no ``[predicate].id``.
    """
    predicates_dir = os.path.join(content_dir, "predicates")
    by_id: dict[str, PredicateDoc] = {}
    if not os.path.isdir(predicates_dir):
        return by_id
    for filename in sorted(os.listdir(predicates_dir)):
        if not filename.endswith(".toml"):
            continue
        with open(os.path.join(predicates_dir, filename), "rb") as fh:
            raw = tomllib.load(fh)
        predicate = raw.get("predicate") or {}
        predicate_id = predicate.get("id")
        if not predicate_id:
            raise PredicateError(f"{filename}: missing [predicate].id")
        rules = tuple(
            Rule(id=r["id"], description=r.get("description", ""), subject=r["subject"], action=r["action"], effect=r["effect"])
            for r in raw.get("rule", [])
        )
        by_id[predicate_id] = PredicateDoc(
            id=predicate_id,
            version=int(predicate.get("version", 1)),
            description=predicate.get("description", ""),
            rules=rules,
            examples=tuple(raw.get("example", [])),
        )
    return by_id


def flatten_example_context(example: Mapping[str, object]) -> dict[str, object]:
    """An example's top-level extras plus its ``context`` table, one dict.

    Exactly the merge ``packages/harness-codex/test/predicates.test.mjs`` and
    ``packages/harness-pi/test/guard-predicates.test.mjs`` both perform: a
    real caller assembling a decision context flattens ``target_role``/
    ``target_branch``/``path``/``symbol`` alongside the declared ``context``
    table. ``context`` wins on any key collision (there are none in the live
    corpus today, but an explicit decision context should out-rank an
    example's incidental top-level fields).
    """
    extras = {k: v for k, v in example.items() if k not in _CANONICAL_EXAMPLE_KEYS}
    return {**extras, **(example.get("context") or {})}


def resolve_content_dir() -> str | None:
    """Locate ``content/`` — ``$CLAUDE_PLUGIN_ROOT/content``, else walk up.

    Mirrors ``shepherd_cli.resolution``'s ``_find_via_plugin_root_then_walk_up``
    precedence exactly (same two-signal search: an explicit plugin root
    first, then upward from the resolved repo root) so this engine finds the
    same ``content/`` a Claude-plugin install and a bare repo clone both
    expect, without importing that module's private helper.

    Returns:
        The absolute path to ``content/``, or None if no candidate exists.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidate = os.path.join(plugin_root, "content")
        if os.path.isdir(os.path.join(candidate, "predicates")):
            return candidate

    current = resolve_repo_root()
    while True:
        candidate = os.path.join(current, "content")
        if os.path.isdir(os.path.join(candidate, "predicates")):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


# --------------------------------------------------------------------------
# The data-driven decision engine (ported from packages/harness-codex/src/predicates.mjs)
# --------------------------------------------------------------------------

Context = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Env:
    """Evaluation environment two ``dispatch-scope.toml`` effects need.

    ``flock_roles`` is read LIVE from ``content/roles/*.md`` (never a
    hand-transcribed set) so a role added or dropped there is reflected here
    on the next load, matching both prior interpreters' own "never drift
    from the source of truth" discipline.
    """

    flock_roles: frozenset[str]
    plan_or_gate_roles: frozenset[str] = PLAN_OR_GATE_TARGET_ROLES


def _deny_if_false(ctx: Context, env: Env) -> bool:
    return ctx.get("write_eligible") is False and ctx.get("path_in_dispatch_write_scope") is not True


def _deny_if_path_outside_scope(ctx: Context, env: Env) -> bool:
    return ctx.get("path_in_dispatch_write_scope") is False


def _allow_if_no_hit(ctx: Context, env: Env) -> bool:
    return False  # documentary: no-hit is the default allow, never a deny trigger


def _deny_if_hit_without_justification(ctx: Context, env: Env) -> bool:
    return ctx.get("dedup_hit") is True and ctx.get("justification_present") is not True


def _deny_if_target_outside_flock(ctx: Context, env: Env) -> bool:
    target = ctx.get("target_role")
    return isinstance(target, str) and target not in env.flock_roles


def _deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role(ctx: Context, env: Env) -> bool:
    return ctx.get("dispatcher_tier") == "lane-lead" and ctx.get("target_role") in env.plan_or_gate_roles


def _deny_if_dispatcher_is_implementer(ctx: Context, env: Env) -> bool:
    return ctx.get("dispatcher_tier") == "implementer"


def _deny_if_role_is_implementer(ctx: Context, env: Env) -> bool:
    return ctx.get("role_tier") == "implementer"


def _deny_if_branch_outside_own_lane(ctx: Context, env: Env) -> bool:
    return ctx.get("is_own_lane_branch") is False


def _deny_unless_root(ctx: Context, env: Env) -> bool:
    return ctx.get("role_tier") != "root"


#: Keyed by each rule's own ``effect`` string — verbatim port of
#: ``packages/harness-codex/src/predicates.mjs``'s ``EFFECT_HANDLERS``. Adding
#: a fifth predicate means adding entries here, never a bespoke evaluator.
EFFECT_HANDLERS: Mapping[str, Callable[[Context, Env], bool]] = {
    "deny_if_false": _deny_if_false,
    "deny_if_path_outside_scope": _deny_if_path_outside_scope,
    "allow_if_no_hit": _allow_if_no_hit,
    "deny_if_hit_without_justification": _deny_if_hit_without_justification,
    "deny_if_target_outside_flock": _deny_if_target_outside_flock,
    "deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role": _deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role,
    "deny_if_dispatcher_is_implementer": _deny_if_dispatcher_is_implementer,
    "deny_if_role_is_implementer": _deny_if_role_is_implementer,
    "deny_if_branch_outside_own_lane": _deny_if_branch_outside_own_lane,
    "deny_unless_root": _deny_unless_root,
}


def evaluate_predicate(
    predicate_id: str,
    action: str,
    context: Context,
    predicates: Mapping[str, PredicateDoc],
    env: Env,
) -> tuple[str, list[str]]:
    """Run every ``action``-scoped rule of one predicate against ``context``.

    Args:
        predicate_id: e.g. ``"write-boundary"``.
        action: the rule-scoping action, e.g. ``"fs.write"``, ``"dispatch"``,
            ``"vcs.write"``, ``"vcs.integrate"`` — only rules whose own
            ``action`` matches are evaluated (``git-custody.toml`` scopes two
            of its three rules to ``vcs.write`` and the third to
            ``vcs.integrate``; evaluating all three unconditionally would
            double-apply a ``vcs.write``-only rule to a ``vcs.integrate``
            request).
        context: the flattened decision context.
        predicates: the loaded corpus, from :func:`load_predicates`.
        env: the shared evaluation environment, from :class:`Env`.

    Returns:
        ``("allow", [])`` when no rule fires, else ``("deny", [rule_id, ...])``
        — every rule id that fired, in declaration order (usually one; see
        ``write-boundary.toml``'s two rules, which can both fire together).

    Raises:
        PredicateError: no such predicate, no rule scoped to ``action``, or a
            rule's ``effect`` names no known handler.
    """
    doc = predicates.get(predicate_id)
    if doc is None:
        raise PredicateError(f"no such predicate `{predicate_id}`")

    applicable = [rule for rule in doc.rules if rule.action == action]
    if not applicable:
        raise PredicateError(f"predicate `{predicate_id}` has no rule scoped to action `{action}`")

    fired: list[str] = []
    for rule in applicable:
        handler = EFFECT_HANDLERS.get(rule.effect)
        if handler is None:
            raise PredicateError(f"no handler for effect `{rule.effect}` (predicate `{predicate_id}`, rule `{rule.id}`)")
        if handler(context, env):
            fired.append(rule.id)
    return ("deny", fired) if fired else ("allow", [])


# --------------------------------------------------------------------------
# Halt codes — harvested from the corpus, never invented (see module docstring)
# --------------------------------------------------------------------------


def _harvest_halt_codes(predicates: Mapping[str, PredicateDoc], env: Env) -> dict[tuple[str, str], str | None]:
    """Build ``{(predicate_id, rule_id): halt_code_or_None}`` from the corpus.

    For every ``kind = "deny"`` example whose context fires EXACTLY ONE rule,
    records that rule's halt code (``None`` if the example declares none —
    an explicit, attested absence, e.g. ``dispatch-scope.toml``'s
    ``coder-attempts-to-dispatch-worker-for-a-missing-dependency`` example).
    A rule that never fires alone in any example (``git-custody.toml``'s
    ``lane-lead-owns-its-own-branch-only`` — every example that could exercise
    it also fires ``implementer-never-writes-git`` or fires nothing) simply
    never gets a table entry; :func:`_resolve_halt_code`'s plain ``.get()``
    then returns ``None`` for it too, so "never attested" and "attested as
    none" both correctly emit no halt code — never an invented one.

    Raises:
        PredicateError: two examples singleton-fire the same rule with two
            DIFFERENT halt codes — the corpus itself would be inconsistent.
    """
    table: dict[tuple[str, str], str | None] = {}
    for predicate_id, doc in predicates.items():
        for example in doc.examples:
            if example.get("result") != "deny":
                continue
            context = flatten_example_context(example)
            _, fired = evaluate_predicate(predicate_id, str(example["action"]), context, predicates, env)
            if len(fired) != 1:
                continue
            key = (predicate_id, fired[0])
            halt_code = example.get("halt_code")
            if key in table and table[key] != halt_code:
                raise PredicateError(
                    f"ambiguous halt code for {key}: {table[key]!r} vs {halt_code!r} (example `{example.get('name')}`)"
                )
            table[key] = halt_code
    return table


def _write_boundary_halt_code(context: Context, role: object, role_facts: Mapping[str, RoleFact]) -> str | None:
    """``write-boundary``'s halt code — harvested from ``packages/harness-pi/src/guard.ts``.

    The one predicate whose halt code cannot come from :func:`_harvest_halt_codes`
    alone: ``write-boundary.toml``'s ``discovery-writes-outside-its-declared-output-path``
    and ``critic-attempts-any-write`` examples share byte-identical ``context``
    (``write_eligible = false, path_in_dispatch_write_scope = false`` — both
    rules fire together) yet declare different outcomes (``DISCOVERY-WRITE-PATH``
    vs no halt code at all), because the deciding fact is the ROLE's
    ``content/roles/<role>.md`` ``capabilities``, not anything in ``context``.
    """
    if context.get("write_eligible") is True:
        return "SCOPE OVERFLOW"
    fact = role_facts.get(role) if isinstance(role, str) else None
    if fact is not None and "report-write" in fact.capabilities:
        return "DISCOVERY-WRITE-PATH"
    return None


def _resolve_halt_code(
    predicate_id: str,
    fired_rule_ids: list[str],
    context: Context,
    role: object,
    role_facts: Mapping[str, RoleFact],
    halt_table: Mapping[tuple[str, str], str | None],
) -> str | None:
    if predicate_id == "write-boundary":
        return _write_boundary_halt_code(context, role, role_facts)
    if len(fired_rule_ids) == 1:
        return halt_table.get((predicate_id, fired_rule_ids[0]))
    return None


# --------------------------------------------------------------------------
# Verdict — the exactly-one-of-three response shape
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Verdict:
    """One guard verdict: ``allow``, ``deny``, or ``unresolved`` — never a fourth shape."""

    decision: str
    predicate: str | None = None
    rule: str | None = None
    halt_code: str | None = None
    reason: str | None = None
    missing: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        """The exact stdout shape ``shepherd guard eval`` prints for this verdict."""
        out: dict[str, object] = {"decision": self.decision}
        if self.decision == "deny":
            if self.predicate is not None:
                out["predicate"] = self.predicate
            if self.rule is not None:
                out["rule"] = self.rule
            if self.halt_code is not None:
                out["halt_code"] = self.halt_code
            if self.reason is not None:
                out["reason"] = self.reason
        elif self.decision == "unresolved":
            if self.reason is not None:
                out["reason"] = self.reason
            if self.missing:
                out["missing"] = list(self.missing)
        return out


def _unresolved(reason: str, *missing: str) -> Verdict:
    return Verdict("unresolved", reason=reason, missing=tuple(missing))


# --------------------------------------------------------------------------
# Shape (b): raw tool call -> (predicate, action, context) mapping
# --------------------------------------------------------------------------

#: ``hooks/scripts/coder_git_guard.sh``'s ``READONLY_GIT_VERBS`` complement:
#: every mutating porcelain/plumbing verb that predicate git-custody's
#: ``vcs.write`` rules govern. ``rebase``/``merge``/``cherry-pick``/``worktree``
#: are split out below into :data:`_GIT_INTEGRATE_VERBS` — the same three-verb
#: split ``git-custody.toml``'s own header names verbatim
#: ("commit, push, rebase, merge, cherry-pick, worktree add/remove/prune").
_GIT_ALL_WRITE_VERBS = frozenset(
    {
        "add", "rm", "mv", "commit", "commit-tree", "merge", "merge-file", "merge-index", "rebase",
        "reset", "restore", "checkout", "checkout-index", "switch", "stash", "clean", "cherry-pick",
        "revert", "push", "pull", "fetch", "clone", "init", "gc", "prune", "repack", "apply", "am",
        "worktree", "remote", "tag", "branch", "config", "notes", "submodule", "update-ref",
        "update-index", "update-server-info", "replace", "filter-branch", "filter-repo", "fast-import",
        "sparse-checkout", "bisect", "format-patch", "request-pull", "write-tree", "hash-object",
        "symbolic-ref", "read-tree", "reflog", "send-pack", "receive-pack", "http-push", "http-fetch",
        "credential", "maintenance", "mergetool", "difftool", "commit-graph", "multi-pack-index",
        "pack-refs", "mktree", "mktag", "pack-objects", "unpack-objects", "prune-packed", "fsck",
    }
)
_GIT_INTEGRATE_VERBS = frozenset({"rebase", "merge", "cherry-pick", "worktree"})
_GIT_WRITE_VERBS = _GIT_ALL_WRITE_VERBS - _GIT_INTEGRATE_VERBS

#: ``hooks/scripts/coder_git_guard.sh``'s embedded tokenizer's own constants.
_GIT_GLOBAL_OPTS_TAKE_ARG = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--super-prefix"}
)
_SHELL_WRAPPERS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "env", "xargs"})
_MAX_RECURSION_DEPTH = 6


def extract_git_subcommands(command: str, *, _depth: int = 0) -> list[str]:
    """The canonical git-subcommand tokenizer, ported line for line from
    ``hooks/scripts/coder_git_guard.sh``'s embedded python3 snippet (its own
    comment: "python3 does the precise tokenization... walks tokens, skips
    git global options (``git -C x commit`` -> ``commit``), and RECURSES into
    shell-invoking wrappers (bash/sh/zsh/eval -c ``"<string>"``) so a write
    hidden in a quoted argument is not an opaque token. Each extracted
    subcommand is cut at the first shell metacharacter so a glued read
    (``git status;git log``) is not mis-read as one bogus subcommand."

    This is THE canonical tokenizer (the brief's own words) — every one of
    the three adapters' hand-rolled copies collapses onto this, not a
    fourth reimplementation. ``bash``'s ``READONLY_GIT_VERBS`` allowlist
    stays bash-side (this function only extracts subcommands; classifying
    one as read-only vs write is :data:`_GIT_WRITE_VERBS` /
    :data:`_GIT_INTEGRATE_VERBS` above, this engine's own concern).

    Args:
        command: the raw shell command string (e.g. ``tool_input.command``).
        _depth: recursion guard, mirrors the bash snippet's ``depth > 6``.

    Returns:
        Every git subcommand token found, lowercased, in encounter order.
    """
    out: list[str] = []
    if _depth > _MAX_RECURSION_DEPTH:
        return out
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()

    i, n = 0, len(tokens)
    while i < n:
        base = tokens[i].rsplit("/", 1)[-1]
        if base == "git":
            j = i + 1
            while j < n:
                opt = tokens[j]
                if opt in _GIT_GLOBAL_OPTS_TAKE_ARG:
                    j += 2
                    continue
                if opt.startswith("--") and "=" in opt:
                    j += 1
                    continue
                if opt.startswith("-"):
                    j += 1
                    continue
                subcommand = re.split(r"[;&|]", opt.lower())[0]
                if subcommand:
                    out.append(subcommand)
                break
            i = j + 1
        elif base == "eval":
            for k in range(i + 1, n):
                out.extend(extract_git_subcommands(tokens[k], _depth=_depth + 1))
            i += 1
        elif base in _SHELL_WRAPPERS:
            k = i + 1
            while k < n:
                if tokens[k] == "-c" and k + 1 < n:
                    out.extend(extract_git_subcommands(tokens[k + 1], _depth=_depth + 1))
                    k += 2
                    continue
                k += 1
            i += 1
        else:
            i += 1
    return out


# --------------------------------------------------------------------------
# The Engine — loads once, serves eval / test / explain
# --------------------------------------------------------------------------

_WRITE_TOOL_NAMES = frozenset({"Write", "Edit", "apply_patch"})
_DISPATCH_TOOL_NAMES = frozenset({"Agent", "Workflow"})


@dataclass(frozen=True, slots=True)
class Engine:
    """The loaded corpus + role facts + harvested halt-code table, ready to evaluate."""

    predicates: dict[str, PredicateDoc]
    env: Env
    role_facts: dict[str, RoleFact]
    halt_table: dict[tuple[str, str], str | None]

    def evaluate(self, payload: object) -> Verdict:
        """Evaluate one request — either accepted shape.

        Args:
            payload: the parsed stdin JSON body. Shape (a), normalized,
                is discriminated by a top-level ``predicate`` key; shape
                (b), a raw tool call, by a top-level ``tool_name`` key.

        Returns:
            Exactly one of allow / deny / unresolved — never raises for a
            malformed OR incomplete request; that is what ``unresolved``
            is for (DF-75).
        """
        if not isinstance(payload, Mapping):
            return _unresolved("request body is not a JSON object", "body")
        if "predicate" in payload:
            return self._evaluate_normalized(payload)
        if "tool_name" in payload:
            return self._evaluate_tool_call(payload)
        return _unresolved("request carries neither `predicate` nor `tool_name`", "predicate", "tool_name")

    # -- shape (a): normalized ------------------------------------------

    def _evaluate_normalized(self, payload: Mapping[str, object]) -> Verdict:
        predicate_id = payload.get("predicate")
        action = payload.get("action")
        role = payload.get("role")
        context = payload.get("context")

        if not isinstance(predicate_id, str) or not predicate_id:
            return _unresolved("missing `predicate`", "predicate")
        if predicate_id not in self.predicates:
            return _unresolved(f"no such predicate `{predicate_id}`", "predicate")
        if not isinstance(action, str) or not action:
            return _unresolved("missing `action`", "action")
        if "role" not in payload or role is None:
            return _unresolved("missing `role` -- cannot identify the acting role", "role")
        if context is None:
            context = {}
        if not isinstance(context, Mapping):
            return _unresolved("`context` must be a JSON object", "context")

        return self._decide(predicate_id, action, role, context)

    def _decide(self, predicate_id: str, action: str, role: object, context: Context) -> Verdict:
        try:
            result, fired = evaluate_predicate(predicate_id, action, context, self.predicates, self.env)
        except PredicateError as exc:
            return _unresolved(str(exc))
        if result == "allow":
            return Verdict("allow")

        halt_code = _resolve_halt_code(predicate_id, fired, context, role, self.role_facts, self.halt_table)
        doc = self.predicates[predicate_id]
        descriptions = [rule.description for rule in doc.rules if rule.id in fired]
        reason = " / ".join(descriptions) if descriptions else f"{predicate_id}: rule(s) {', '.join(fired)} fired"
        return Verdict("deny", predicate=predicate_id, rule=",".join(fired), halt_code=halt_code, reason=reason)

    # -- shape (b): raw tool call -----------------------------------------

    def _evaluate_tool_call(self, payload: Mapping[str, object]) -> Verdict:
        tool_name = payload.get("tool_name")
        role = payload.get("role")
        tool_input = payload.get("tool_input")
        if tool_input is None:
            tool_input = {}

        if not isinstance(tool_name, str) or not tool_name:
            return _unresolved("missing `tool_name`", "tool_name")
        if not isinstance(tool_input, Mapping):
            return _unresolved("`tool_input` must be a JSON object", "tool_input")

        if tool_name in _WRITE_TOOL_NAMES:
            return self._evaluate_write_tool(role)
        if tool_name == "Bash":
            return self._evaluate_bash_tool(role, tool_input)
        if tool_name in _DISPATCH_TOOL_NAMES:
            return self._evaluate_dispatch_tool(role, tool_input)
        return _unresolved(f"no (predicate, action) mapping known for tool `{tool_name}`", "tool_name mapping")

    def _evaluate_write_tool(self, role: object) -> Verdict:
        """``Write``/``Edit``/``apply_patch`` -> ``write-boundary``.

        A bare tool call never carries the dispatch's own declared
        ``write_scope`` (``write-boundary.toml`` rule ``path-in-declared-scope``'s
        own subject) -- there is no way to derive
        ``path_in_dispatch_write_scope`` from ``tool_input`` alone, so a
        write-eligible role (or a write_eligible=false role holding the
        narrow ``report-write`` exception) is genuinely unresolved: neither
        allow nor a specific deny is safely inferable. A role with NO write
        capability at all (``write_eligible=false`` and no ``report-write``)
        is the one case that resolves regardless of scope -- it always
        denies, matching ``write-boundary.toml``'s own
        ``critic-attempts-any-write`` example.
        """
        if role is None:
            return _unresolved("missing `role` -- cannot identify the acting role", "role")
        fact = self.role_facts.get(role) if isinstance(role, str) else None
        if fact is None:
            return _unresolved(f"unknown role `{role}`", "role_facts")
        if fact.write_eligible:
            return _unresolved(
                "cannot determine path_in_dispatch_write_scope from a bare tool call",
                "context.path_in_dispatch_write_scope",
            )
        if "report-write" in fact.capabilities:
            return _unresolved(
                "role holds a narrow report-write exception; cannot determine "
                "path_in_dispatch_write_scope from a bare tool call",
                "context.path_in_dispatch_write_scope",
            )
        return Verdict(
            "deny",
            predicate="write-boundary",
            rule="role-write-eligibility",
            halt_code=None,
            reason="role holds no write capability at all",
        )

    def _evaluate_bash_tool(self, role: object, tool_input: Mapping[str, object]) -> Verdict:
        """``Bash`` -> ``git-custody``, via :func:`extract_git_subcommands`.

        A read-only git invocation, or a command with no git in it at all,
        allows outright (matching ``coder_git_guard.sh``'s own
        ``pass_silent`` for exactly those two cases) -- no predicate lookup
        needed. A found git-integrate verb (rebase/merge/cherry-pick/
        worktree) takes priority over a plain write verb when both appear.
        """
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            return Verdict("allow")

        subcommands = extract_git_subcommands(command)
        if any(sc in _GIT_INTEGRATE_VERBS for sc in subcommands):
            action = "vcs.integrate"
        elif any(sc in _GIT_WRITE_VERBS for sc in subcommands):
            action = "vcs.write"
        else:
            return Verdict("allow")

        if role is None:
            return _unresolved("missing `role` -- cannot identify the acting role", "role")
        tier = ROLE_TIER.get(role) if isinstance(role, str) else None
        if tier is None:
            return _unresolved(f"unknown role `{role}`", "role")
        return self._decide("git-custody", action, role, {"role_tier": tier})

    def _evaluate_dispatch_tool(self, role: object, tool_input: Mapping[str, object]) -> Verdict:
        """``Agent``/``Workflow`` -> ``dispatch-scope``.

        ``subagent_type`` is Claude's own ``Task``/``Agent`` tool field for
        the dispatch target (confirmed live across ``agents/*.md``); a
        generic ``target_role``/``role`` key is accepted as a fallback for
        other harnesses' tool shapes.
        """
        target_role = tool_input.get("subagent_type") or tool_input.get("target_role") or tool_input.get("role")
        if not isinstance(target_role, str) or not target_role:
            return _unresolved("cannot determine the dispatch target role from `tool_input`", "tool_input.subagent_type")
        if role is None:
            return _unresolved("missing `role` -- cannot identify the dispatching role", "role")
        tier = ROLE_TIER.get(role) if isinstance(role, str) else None
        if tier is None:
            return _unresolved(f"unknown role `{role}`", "role")
        return self._decide("dispatch-scope", "dispatch", role, {"target_role": target_role, "dispatcher_tier": tier})

    # -- shepherd guard test ----------------------------------------------

    def run_conformance_suite(self) -> tuple[int, int, list[str]]:
        """Replay EVERY ``[[example]]`` across the loaded corpus through :meth:`evaluate`.

        Returns:
            ``(passed, total, failure_messages)`` — the falsifiability
            harness ``shepherd guard test`` reports. ``total == 0`` (an
            empty/missing predicates directory) is the caller's problem to
            reject (DF-59), not this method's -- it truthfully reports
            ``(0, 0, [])`` rather than a green ``0/0``.
        """
        passed = 0
        total = 0
        failures: list[str] = []
        for predicate_id, doc in self.predicates.items():
            for example in doc.examples:
                total += 1
                payload = {
                    "predicate": predicate_id,
                    "role": example.get("role"),
                    "action": example.get("action"),
                    "context": flatten_example_context(example),
                }
                verdict = self.evaluate(payload)
                expected_result = example.get("result")
                expected_halt = example.get("halt_code")
                ok = verdict.decision == expected_result
                if ok and expected_halt:
                    ok = verdict.halt_code == expected_halt
                if ok:
                    passed += 1
                else:
                    failures.append(
                        f"FAIL {predicate_id}/{example.get('name')}: expected result={expected_result!r} "
                        f"halt_code={expected_halt!r}, got decision={verdict.decision!r} halt_code={verdict.halt_code!r}"
                    )
        return passed, total, failures


def load_engine(content_dir: str | None = None) -> Engine:
    """Load the corpus + role facts once and build an :class:`Engine`.

    Args:
        content_dir: absolute path to ``content/``; defaults to
            :func:`resolve_content_dir`.

    Raises:
        PredicateError: ``content/`` cannot be located, or the corpus itself
            is inconsistent (see :func:`_harvest_halt_codes`).
    """
    resolved = content_dir or resolve_content_dir()
    if resolved is None:
        raise PredicateError(
            "cannot locate content/predicates -- set CLAUDE_PLUGIN_ROOT or run inside the shepherd repo"
        )
    predicates = load_predicates(resolved)
    role_facts = load_role_facts(resolved)
    env = Env(flock_roles=frozenset(role_facts))
    halt_table = _harvest_halt_codes(predicates, env)
    return Engine(predicates=predicates, env=env, role_facts=role_facts, halt_table=halt_table)


__all__ = [
    "Context",
    "Engine",
    "Env",
    "PredicateDoc",
    "PredicateError",
    "ROLE_TIER",
    "PLAN_OR_GATE_TARGET_ROLES",
    "Rule",
    "RoleFact",
    "Verdict",
    "evaluate_predicate",
    "extract_git_subcommands",
    "flatten_example_context",
    "load_engine",
    "load_predicates",
    "load_role_facts",
    "resolve_content_dir",
]
