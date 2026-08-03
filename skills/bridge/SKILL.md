---
name: bridge
slug: bridge
version: 6.4.2
description: "Cross-shepherd coordination contract: how a claude-shepherd and a codex-shepherd (or any future harness implementation) share runs, lanes, and custody through the filesystem artifact schema — never through harness internals. Use when two shepherd implementations touch the same repository or hand work across."
metadata:
  triggers:
    - "cross-shepherd"
    - "codex handoff"
    - "bridge contract"
---

# /bridge — the cross-shepherd coordination contract

Two shepherd implementations exist today — this plugin (Claude Code) and
`FL03/codex-shepherd` (Codex) — with a harness-agnostic `FL03/shepherd` as the
convergence target. This skill defines the ONE contract that lets any two of
them coordinate on a repository without knowing each other's harness. The
patterns here are CANONICAL: a change to this contract is replicated to every
implementation, and a capability that cannot be expressed through this
contract belongs to the implementation, not the bridge.

## Principle: the filesystem is the bus

Implementations never talk harness-to-harness (no shared task lists, no
teammate inboxes, no tool-name assumptions). They coordinate exclusively
through the project-visible artifact schema
(`skills/context/references/naming-conventions.md` — the canonical layout):

- `.shepherd/runs/{run}/run.json` — the shared run state. Written ONLY
  through an implementation's CLI (`shepherd run …` here), never latent-
  authored; `schema_version` gates compatibility (currently 1). A reader
  encountering a HIGHER schema_version than it knows MUST treat the run as
  foreign: read-only, no state writes, surface to its operator.
- `.shepherd/runs/{run}/seed.md`, `plan.md`, `lanes/{lane}/plan.md` — the
  intent artifacts. Prose contracts, identical shape in every
  implementation (the seed/plan/lane-plan templates are the normative
  scaffolds).
- `.shepherd/learnings/`, `.shepherd/ctx/` — durable knowledge, shared
  read, single-writer per file.

Identifier grammar everywhere: `[a-z0-9][a-z0-9-]*` — no path separators,
no `..`, no absolute paths. Timestamps live in `run.json`/manifests, never
in artifact bodies (byte-stable renders are the cache and diff contract).

**Config discovery is a bridge concern (v6.4.2).** A foreign harness
determining whether a repo uses shepherd at all — and where its
`shepherd.toml` lives — reads `<workdir>/shepherd.toml` (the harness-neutral
namespace shepherd owns), never `.claude/shepherd.toml`. `.claude/` is
Claude Code's own directory; a bridge participant reaching into it to
discover another implementation's binding is exactly the harness-internals
coupling this contract exists to rule out. `docs/configuration.md
§Resolution` has the full precedence chain and the migration path
(`shepherd config migrate`) off the legacy `.claude/`-rooted location; a
project's declared `[project].harnesses` list (same doc, `§[project]`) is
the companion piece — a machine-readable anchor stating which
implementations are known to operate here, read-only metadata that dispatch
never consults.

## Content contract vs. path contract (#252)

Sharing a path is not the same guarantee as sharing what's inside it. Two
implementations agreeing where an artifact lives (PATH-compatible) does not
mean they agree what sections it must carry (CONTENT-contracted) — and a
consumer that assumes the stronger guarantee on a path-only artifact will
read a well-formed empty box. Observed: a codex-shepherd-authored run puts a
real file at every `lanes/{lane}/plan.md` path (path contract satisfied) but
the file is a thin pointer doc with no `## Steps`, no `## Lane acceptance`,
no `## Deviations` (content contract violated) — a claude-shepherd conductor
booting onto it via `agents/conductor.md §Boot verification` Check 3 is told
to check off steps that don't exist.

| Artifact | Contract | Required shape |
|---|---|---|
| `run.json` | Content | `schema_version`-gated JSON; a reader seeing a HIGHER version than it knows treats the run as foreign (read-only) rather than assume the shape |
| `seed.md`, `plan.md` | Content | prose contract, identical shape in every implementation — the seed/plan templates ARE the normative scaffold |
| `lanes/{lane}/plan.md` | Content (#252) | MUST carry `## Steps` (per step: `- [ ]` actions + an `**Acceptance:**` line), `## Lane acceptance`, and an append-only `## Deviations` section. A file present at the right path with none of these is NOT a valid lane plan — a consuming implementation self-heals it from `plan.md`'s `## Lane projection` before executing rather than treat the empty shape as instruction (`agents/conductor.md §Boot verification` Check 3) |
| `.shepherd/learnings/`, `.shepherd/ctx/` | Path | durable knowledge, shared read, single-writer per file — internal shape is each implementation's own business |
| dispatch envelope (`dispatch/`) | Content | fixed `SHEPHERD_*` header grammar + `SHEPHERD_STATUS`/`SHEPHERD_EVIDENCE` completion footer (§Dispatch envelope below) — a file at the right path with a different header shape is not grammar-checked and is treated as unfinished |

When in doubt: an artifact this contract NAMES a required section or field
for is content-contracted — assume nothing about its interior. An artifact
it only names a PATH for is path-compatible only — the path is the whole
guarantee.

## Run id canonicality (v6.4.2)

The path contract above only holds if two implementations agree on the
path in the first place. `{run}` MUST be exactly the slug
`[branching].sprint_slug_pattern`/`patch_slug_pattern` derives for the
version in scope — no harness name, no implementation name, no ordinal
suffix appended (`skills/context/references/naming-conventions.md §Run
identity` has the full rule and the mechanized enforcement: refusal at
`run init`, `run canonicalize` to migrate, a `shctx lint` WARN for existing
violations).

This is load-bearing for custody, not cosmetic: custody (below) is
arbitrated through ONE `run.json` per run, by whichever shepherd created
it. A harness-suffixed run directory (`v039-dev0-codex-01` instead of the
canonical `v039-dev0`, an actual observed case) means each implementation
computes a *different* path for what should be the same run — there is no
longer one `run.json` to arbitrate through, so the two implementations
silently fork into parallel, uncoordinated work on the same version instead
of claiming lanes against a shared ledger. A reader encountering a
non-canonical run directory should treat it as a canonicality violation to
flag (`shctx lint`), not a second, independently valid run.

## Custody

Single-writer per path, claimed through `run.json`:

1. A shepherd claims a lane by registering it (`run lane add` /
   `run lane set --state=in-progress`) with its `worktree` and `branch`
   fields populated. A lane whose `state` is `in-progress` is FOREIGN to
   every other shepherd: no writes under `lanes/{lane}/`, no commits to its
   branch, no worktree access.
2. The run's root custodian is whichever shepherd created `run.json`
   (`run init`). Only the custodian mutates run-level fields (`status`,
   `seed`, `plan`) and executes cross-lane git integration. A non-custodian
   needing a run-level change writes a signal (below) and waits.
3. The #242 boundary-merge ledger (`run wave accept/merged/pending`) is
   custodian-only; a non-empty pending set blocks EVERY implementation's
   wave gate identically.

## Dispatch envelope (harness-agnostic)

When work crosses the bridge — one shepherd authoring work another will
execute — the request is a file under `.shepherd/runs/{run}/dispatch/`,
carrying the machine-readable header codex-shepherd proved:

```text
SHEPHERD_ROLE=<role>
SHEPHERD_NODE=<stable-node-id>
SHEPHERD_SCOPE=<paths-or-read-only>
SHEPHERD_ACCEPTANCE=<runnable-or-observable-check>
SHEPHERD_REPORT=<durable-report-path>
```

The executor answers at `SHEPHERD_REPORT` ending with the completion footer:

```text
SHEPHERD_STATUS=<DONE|DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT>
SHEPHERD_EVIDENCE=<non-empty pointer to verifiable evidence>
```

Both lines are grammar-checked by the consumer; a report without them is
unfinished. The four-status vocabulary is closed and shared with every
role's completion contract — no implementation adds a fifth status.

## Signals

Cross-shepherd nudges reuse the durable cross-session signal channel
(`shepherd signal send/poll`): kinds `seed-ready`, `run-handoff`,
`lane-claim`, `custody-request`. Signals are best-effort nudges — the
committed artifact is always the source of truth; NEVER wait on an ack.

## Non-goals

- No shared live messaging (SendMessage, inboxes) across harnesses.
- No cross-harness model/effort mapping — each implementation resolves its
  own `[models]` map; the bridge carries roles, never model ids.
- No loop/scheduling primitives — reconstructing loops from local
  primitives is each implementation's job (and the future `FL03/shepherd`
  core's, where this contract becomes the package boundary).

## See also

- `skills/context/references/naming-conventions.md` — the canonical
  artifact schema this contract rides on.
- `skills/shepherd/references/escalation.md` — in-harness escalation (the
  bridge never replaces it; a BLOCKED bridge report still escalates
  locally).
- `FL03/codex-shepherd` `docs/design.md` — the sibling implementation's
  transport-specific machinery (binding suffixes, encrypted-spawn
  workarounds) that deliberately stays OUT of this contract.
