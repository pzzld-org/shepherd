---
title: gates restoration via broad sweep
description: |
  Lane 0 (and any wave whose mission is "restore the gates") never dispatches
  on the engineer's narrow-fix list. The conductor first runs every configured
  gate verbosely, captures the FULL latent error inventory, and briefs Lane 0
  with all errors — not just the four the engineer happened to find. This cuts
  the cascade-of-hot-fixes pattern.
---

# Doctrine — Gates Restoration via Broad Sweep

> Project-agnostic principle: when a build is broken, the engineer's narrow
> fix-list is a sample of the latent error inventory, not the whole of it.
> Front-loading discovery converts a serial cascade of hot-fix coders into
> a single broad-sweep lane with the full error set in scope.
>
> Field origin: shepherd v5.0.1 conductor feedback (axiom v0.3.0-dev.4 XL),
> §2.4 — seven serial iterations vs one broad-sweep dispatch. v5.0.3 codifies
> the prevention.

## The pattern this kills

```
Lane 0a → reveals 3 latent errors → Lane 0b
Lane 0b → reveals 2 latent errors → Lane 0c
Lane 0c → reveals 1 latent error  → Lane 0d
…
```

Each iteration is a full coder roundtrip (~5 min). The cascade is **not
parallelism-amenable** — the next error is only knowable after the current
fix lands. The fix is not faster coders; it is **front-loading discovery**.

## The rule

Whenever a sprint opens with broken gates (typical at dev.0 or after a
risky merge/cherry-pick), the conductor runs **GATES-DISCOVERY** as a
conductor-inline node BEFORE dispatching Lane 0 (or any wave whose mission
is "restore the gates"). The output of GATES-DISCOVERY is a **full latent
error inventory**, and the Lane 0 brief lists ALL errors — not the
engineer-found subset.

## GATES-DISCOVERY — conductor-inline procedure

```bash
# Run every configured gate verbosely; tee to a discovery report.
# {gates.check}, {gates.lint}, {gates.format} resolve from shepherd.toml.

mkdir -p {paths.reports}
report="{paths.reports}/$(date +%Y-%m-%d)-{sprint_slug}-gates-discovery.md"

{
  echo "# Gates discovery — {sprint_branch}"
  echo "_Generated $(date -u +%Y-%m-%dT%H:%M:%SZ)_"
  echo
  echo "## {gates.check}"
  {gates.check} 2>&1 || true
  echo
  echo "## {gates.lint}"
  {gates.lint} 2>&1 || true
  echo
  echo "## {gates.format}"
  {gates.format} 2>&1 || true
} | tee "$report"
```

Then:

1. **Parse** the report into a unified inventory: `(file:line, kind, code,
   sample fix)` per error.
2. **Group** by file scope so the inventory can be partitioned across
   parallel Lane 0 coders if the count is large enough.
3. **Brief Lane 0** with the FULL inventory — not the engineer's narrow
   list. The brief's `[ACCEPTANCE]` becomes "all gates pass after this lane
   lands" rather than "fix these four items".

## When to run GATES-DISCOVERY

| Trigger | Run discovery? |
|---|---|
| Sprint opens with red gates (any) | **Yes** — always |
| Engineer's plan lists "Lane 0 — restore gates" | **Yes** — even if list looks complete |
| Mid-sprint cherry-pick lands and gates go red | **Yes** — re-run before any hot-fix dispatch |
| Wave-gate fails with > 1 error class | **Yes** — broad-sweep before narrow fix |
| Gates were green before this dispatch | No — the fix is whatever the dispatch broke |

## When the rule does not apply

- **Single-error gates** (one compile error, fully diagnosed) — go ahead
  with the narrow fix. The doctrine targets cascades, not single bugs.
- **Logic bugs** discovered by tests that pass — those are not "gates"
  failures; treat as normal hot-fix dispatches.
- **Auditor findings post-merge** — those route through `HOTFIX` nodes per
  the Stage Graph, which is already its own broad-sweep mechanism.

## Pattern B is preserved

GATES-DISCOVERY is conductor-inline (no agent dispatch), so it does not
serialize parallel work. The Lane 0 dispatch that follows can still batch
multiple coders if the inventory partitions cleanly across file scopes.

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/pipeline.md` §II — Stage taxonomy
  (`WAVE-IMPL`, `HOTFIX`, and the new GATES-DISCOVERY conductor-inline
  node).
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/chain-repair.md` — the
  parent pattern of "verify before re-dispatching".
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/subtract-dont-add.md` —
  the related principle that the right fix is rarely "another lane".
