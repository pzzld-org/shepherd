---
name: context
---

# context — the per-project registry

A per-project registry backs dedup detection, GitHub/issue-tracker state caching,
telemetry, and locks. Abstracted here from Claude's own `shctx` CLI + SQLite file into the
registry CONCEPT any harness implements with its own local store.

## Canonical state model

The registry is canonical for operational/ephemeral state; the filesystem covers
human-authored durable artifacts (seeds, plans, reports); a rendered markdown report is a
VIEW over registry rows, never the reverse — a role must not treat a markdown report as
canonical output, and must verify a write landed by querying the row directly rather than
re-reading its own rendered view. A new kind of operational state lands via a registry
schema change, never an ad hoc file path.

## Dedup

Name-keyed dedup catches a reused identifier directly but is blind to a type restated
under a new name; a structural/shape-based scan closes that gap by clustering on field-name
and field-type similarity above a configurable threshold, with a pinnable allow-list for
deliberate near-duplicates. Detection is registry-owned; gate ENFORCEMENT (the pre-dispatch
duplicate check every implementer step re-runs as a tripwire) is a dispatch-pipeline
concern, not this skill's.

## Cache telemetry

Per-dispatch token usage rolls up into a cache-hit-rate signal, `null` when unmeasured
(never `0`, which would mean "measured and expensive") — a sprint-wide rate below a floor
surfaces as a review-time finding, but telemetry alone never caps a grade; it measures
caching health, not correctness.

## Event log

Every guard/hook decision (deny, warn, pass) appends one line to a per-day event log with
role, session, and a truncated reason — secrets scrubbed before the write, never rotated
automatically. A registry health-check preflight reads this log alongside git state, plan
freshness, and lock state to report a fast pass/warn/fail summary.

## Workdir hygiene

A prune operation reclaims accreted state without touching outcomes: dry-run by default
(writes a plan, deletes nothing), a confirm flag moves eligible targets somewhere
reversible rather than deleting outright. Eligibility requires ALL of: not the current
branch, a terminal state, and past an age floor — the live focus record, pinned/doctrine
memory entries, and any unresolved escalation or pending deliverable are never eligible.

## Artifact schema

The canonical layout — namespace selection, the run directory's fixed sub-paths, per-role
write ownership, identifier sanitization, and the tracked-vs-ignored split — is the SAME
schema `bridge`'s cross-harness contract rides on; this skill owns the registry that
indexes it, not the schema itself.
