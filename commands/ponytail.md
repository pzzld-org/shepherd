---
name: ponytail
description: "Senior-engineer review→refine→verify pass on a target (diff, path, file, or PR), outside the sprint pipeline. Runs the senior-engineering standard (doctrines/senior-engineering.md) through @auditor (+ optional @coder), fully adapted to the project and user (styles, doctrines, config, adaptation priors). Review-only by default; --apply to refine."
argument-hint: "[target] [--mode review|refine] [--apply] [--since <ref>] [--concerns <list>] [--max <N>] [--cement] [--no-approval]"
allowed-tools: Bash, Edit, Glob, Grep, Read, AskUserQuestion, Skill, Write, Agent, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, WebFetch, WebSearch, mcp__plugin_github_github__get_file_contents, mcp__plugin_github_github__get_commit, mcp__plugin_github_github__issue_read, mcp__plugin_github_github__pull_request_read, mcp__plugin_github_github__search_code
---

# /shepherd:ponytail — Senior-engineer review→refine→verify

Run the **senior-engineering operating standard** (`doctrines/senior-engineering.md`)
over a target, on demand, **outside** the sprint pipeline. `@auditor` reviews as a
senior reviewer (intent-first, root-vs-symptom, blast-radius-weighted, conformance-
graded); optionally `@coder` applies the accepted findings conforming to THIS
project and THIS user; then `@auditor` re-verifies. It is the on-demand twin of the
always-on standard that v6.1.6 cements into the auditor/coder profiles.

This is workflow **Pattern 3 (Adversarial Verification)** composed with **Pattern 4
(Generate-And-Filter)**, bounded as the **AUDITOR-REFINE** loop
(`references/loop-templates.md`). It reuses the flock — it adds no role.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `[target]` | current branch vs base | What to review: a path (file/dir), a diff range, a PR (`#NNN`), or empty (working tree + branch diff vs the merge-base with `{patch_branch}`/`{main_branch}`) |
| `--mode review\|refine` | `[ponytail].default_mode` (`review`) | `review` = read-only senior report; `refine` = review → apply → re-verify |
| `--apply` | off | Alias for `--mode refine` |
| `--since <ref>` | merge-base | Diff base for range targets |
| `--concerns <list>` | auto-detected | Override the concern split (e.g. `code-quality,data-flow`) |
| `--max <N>` | `[ponytail].max_verify_iterations` (`3`) | Cap on the review↔refine↔re-verify loop |
| `--cement` | off | Persist durable conventions observed during the pass into project memory / the style ledger (conform-the-project) |
| `--no-approval` | off | Skip the apply-approval gate (only when the operator wants unattended refine) |

## Step 0 — Orient, resolve target, load conformance

1. **Read `.claude/shepherd.toml`** (or `.local.toml`) — `[gates]`, `[skills]`,
   `[paths]`, `[ledger]`. Missing → warn + use `docs/configuration.md` defaults.
2. **Read `[ponytail]` config** via `cfg_get`: `senior_standard`, `default_mode`,
   `max_verify_iterations`, `apply_requires_approval`, `conformance_sources`.
3. **WORKFLOW SELF-CHECK** (`doctrines/workflow-tool-self-check.md §I`): is the
   token `Workflow` in your visible tool list? **NEVER `ToolSearch` for it.** Record
   `workflow_tool=present|absent`. Present → the review/verify fan-out (≥2 auditors)
   compiles out-of-context; absent (web/remote, #146) → in-context `Agent(...)` batch.
4. **Resolve `[target]`:**
   - empty → `git diff $(git merge-base HEAD {patch_branch})...HEAD` **plus** uncommitted (`git diff` + `git diff --cached`). Clean tree → HALT `PONYTAIL-NO-TARGET`.
   - a path → review files under it (respect `[FILE-SCOPE]` semantics).
   - `--since <ref>` → `git diff <ref>...HEAD`.
   - `#NNN` → fetch the PR diff via `mcp__plugin_github_github__pull_request_read`.
   - unresolvable → HALT `PONYTAIL-TARGET-UNRESOLVED`.
5. **Auto-detect concerns** from the target's file types (per `agents/auditor.md`
   concern catalog), unless `--concerns` overrides. A focused target is usually 1–3
   concerns, NOT the full close swarm.
6. **Load conformance sources** per `senior-engineering.md §V` precedence (the
   `conformance_sources` order): project doctrines (`.claude/doctrines/*.md`),
   `[CODE-STYLE]` ledger (`.artifacts/styles/<lang>.md`) for each language in the
   target, the `code-style` skill, `shctx adapt priors --lessons --md`, and the
   surrounding code's observed conventions.

## Step 1 — REVIEW (senior @auditor, read-only)

Dispatch `@auditor` (`subagent_type: "shepherd:auditor"`, one per concern;
parallel-safe → ONE batch; compile if `workflow_tool=present`). Each brief carries,
in cache-stable order:

- `[SENIOR-STANDARD]` — pointer to `doctrines/senior-engineering.md` (the eight
  primitives), NOT a re-paste (`doctrines/brief-cache-discipline.md`).
- `[TARGET]` — the resolved diff / paths.
- `[CODE-STYLE]` + project-doctrine excerpts + `[DB-CONTEXT]` priors — the §V
  conformance ladder for the languages in scope.
- The **senior-review checklist** (the eight primitives as concrete questions):
  intent reconstructed? root vs symptom? blast-radius & reversibility weighted?
  tradeoff named? conforms top-down (§V)? systemic-risk cluster (§VI)? bounded
  (§VII)? read-only/tier preserved (§VIII)?

Auditor output = findings (Hypothesis + Falsification + Confidence **plus** the
senior dimensions: `intent`, `root|symptom`, `blast_radius`, `conformance`), a
`## Systemic risk` note if §VI triggers, and a conformance verdict. **`review`
mode stops here** — surface the report and end.

## Step 2 — REFINE (optional @coder apply; refine mode / --apply only)

1. **Approval gate:** if `apply_requires_approval = true` and not `--no-approval`,
   surface the accepted findings and use `AskUserQuestion` to confirm applying them.
   Declined → fall back to the review report and HALT `PONYTAIL-APPLY-UNAPPROVED`
   (not an error — a chosen stop).
2. Dispatch `@coder` (`shepherd:coder`) per accepted finding's `Suggested hot-fix
   lane`, **file-disjoint**, each in its own worktree, conforming to §V. Coders take
   the **root** fix (§II), **justify the tradeoff** in the report (§IV), and stay
   **bounded** (§VII) — no gold-plating untouched code.
3. **Gate** (conductor-inline, sequential per `doctrines/cargo-sequential-gates.md`):
   rebase coder worktrees → `{gates.format}` → `{gates.check}` → `{gates.lint}`.
   Red after the iteration cap → surface, do not loop past `--max`.

## Step 3 — VERIFY (re-audit; the adversarial loop)

Re-dispatch `@auditor` over the changed surface: confirm each accepted finding is
**resolved**, no **regressions** introduced, and re-run any seeded acceptance
predicates in scope (`doctrines/outcome-enforcement.md §Seam 3`). Loop Step 2↔3
until `new_findings: false` **or** `--max` is reached (bounded — `references/loop-
templates.md §AUDITOR-REFINE`). Hitting the cap with findings still open → HALT
`PONYTAIL-LOOP-CAP` and surface the remaining findings (do not loop forever).

## Step 4 — REPORT (+ optional --cement)

Emit:

```
## PONYTAIL REPORT
- Target: <diff range | paths | PR #NNN>
- Concerns: <list>           | workflow_tool: present|absent | fanout: compiled|in-context
- Findings: CRITICAL=N HIGH=N MEDIUM=N LOW=N  (resolved=R deferred=D)
- Systemic risk: <one line or "none">
- Refine: <skipped | N findings applied, gates green|red>
- Conformance: <conforms | deviations: …>  (§V ladder)
- LOC delta: +A/-B
```

**`--cement`** — persist the durable conventions the pass surfaced so future flock
work conforms (the "conform to the project and user" persistence), reusing existing
runtime, no new state engine:

- `shctx mem add --kind=feedback --tags=convention …` — record each recurring
  project idiom / style decision observed (deduped).
- Operator-confirmed: append the distilled idioms to `.artifacts/styles/<lang>.md`
  (the `[CODE-STYLE]` ledger the conductor injects) via `shctx style edit <lang>`.
- Surface them at the next plant/mesh through the adaptation read protocol
  (`doctrines/adaptation-loop.md`).

## Halt codes

| Code | Trigger |
|---|---|
| `PONYTAIL-NO-TARGET` | empty target and a clean tree — nothing to review |
| `PONYTAIL-TARGET-UNRESOLVED` | path / PR / range does not resolve |
| `PONYTAIL-APPLY-UNAPPROVED` | refine requested, operator declined the apply gate → review-only report |
| `PONYTAIL-LOOP-CAP` | `--max` reached with findings still open → surface remaining |
| `SENIOR-STANDARD-MISUSE` | auditor attempted an edit / coder self-gated or expanded scope (`senior-engineering.md §VIII`) |

## Examples

```bash
/shepherd:ponytail                       # senior review of the current branch vs base (read-only)
/shepherd:ponytail src/payments --apply  # review + refine the payments module, conforming to project/user
/shepherd:ponytail #142 --concerns data-flow,dependency-topology   # senior review of PR #142
/shepherd:ponytail --since v6.1.5 --mode refine --max 2            # review→refine a release range, capped
/shepherd:ponytail src/ --cement         # review + persist observed conventions to the style ledger
```

## See also

- `doctrines/senior-engineering.md` — the operative standard (the eight primitives + the §V conformance ladder + `[ponytail]` config).
- `agents/auditor.md` / `agents/coder.md` — the always-on cement of the same standard.
- `references/loop-templates.md §AUDITOR-REFINE` — the bounded review↔refine↔verify loop.
- `doctrines/workflow-patterns.md` — Pattern 3 (Adversarial Verification) + Pattern 4 (Generate-And-Filter).
- `doctrines/outcome-enforcement.md §Seam 3` — seeded-predicate re-verification the VERIFY phase re-runs.
- `doctrines/workflow-tool-self-check.md` — the Step 0 self-check.
- `docs/configuration.md §[ponytail]` — config schema + defaults.
