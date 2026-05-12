---
title: work-bound-to-tracking
description: |
  Every sprint's majority of concrete work units must be justified by an existing
  tracking issue, and the tracking issue closes when the work lands and is proven.
  Language-primitive annotations (panic stubs, deprecation markers, compile-time
  sentinels) are the in-code contract that keeps the tracking surface honest across
  AI-driven workflows where inline comments rot silently.
introduced: v5.0.6
field-origin: axiom v0.3.1-dev.8a, 2026-05-12
---

# Work Bound to Tracking — Issue Anchoring + Language Primitives

## The principle

In a project driven by AI-agent sprints, the codebase IS the shared memory. An inline `// TODO` comment is invisible to the compiler, invisible at runtime, not grep-able alongside the work surface, and trivially misread by an agent as "intent that was already addressed". The result: work that was never done accumulates as ambiguous state.

The fix: replace every "intent not yet implemented" comment with a **language primitive** that names the GH issue, produces a compile warning OR a runtime signal, and disappears when the issue closes and the implementation lands.

---

## The doctrine

**Every sprint's majority of work units MUST be justified by a tracking issue.**

"Majority" means > 50% of coder lanes and > 50% of acceptance criteria have a `#N` anchor. Pure plumbing lanes (formatting passes, carry-forward deduplication, mechanical renames) do not require a backing issue. Every NEW feature, every bug fix, every intentional design gap DOES.

**Every intentional gap in production code MUST be expressed as a language primitive that cites the issue.**

The four categories of intentional gap — and the primitives that cover them:

| Category | When to use | What it does | Must cite |
|---|---|---|---|
| **Unimplemented path** — runtime | Code path exists in the type system but has no implementation this sprint | Panics at runtime with a descriptive message | `#N` in the message string |
| **Unsupported arm** — compile | A match arm or function overload is intentionally unsupported (not "not yet" but "by design, tracked") | Compile warning or runtime signal depending on language | `#N` |
| **Migration window** — deprecated | Existing code is being migrated away; callers should stop using it; the issue tracks the cutover | Compile deprecation warning with migration instructions | `#N` |
| **Issue-filed stub** — plain comment | No runtime or compile expression needed; the intent is a reference only | Inline comment citing issue, NOT a TODO/FIXME | `#N` |

### Language-specific primitives

| Language | Unimplemented path | Unsupported arm | Migration window |
|---|---|---|---|
| **Rust** | `todo!("see #{N}")` or `unimplemented!("{description}; see #{N}")` | `unimplemented!("{reason}; see #{N}")` | `#[deprecated(since = "{version}", note = "{instructions}; see #{N}")]` |
| **TypeScript/JS** | `throw new Error("TODO see #{N}")` | `throw new Error("{reason}; see #{N}")` | `/** @deprecated {instructions}; see #{N} */` |
| **Python** | `raise NotImplementedError("see #{N}")` | `raise NotImplementedError("{reason}; see #{N}")` | `warnings.warn("{instructions}; see #{N}", DeprecationWarning, stacklevel=2)` |
| **Go** | `panic("TODO see #{N}")` | `panic("{reason}; see #{N}")` | `// Deprecated: use Y instead; see #{N}` |
| **SQL/Migrations** | `-- NOT YET: see #{N}` (comment in migration file) | n/a | `-- DEPRECATED: see #{N}` |

The doctrine uses language-agnostic principle statements. Per-language detection greps live in the appropriate language skill, NOT here.

---

## The anti-patterns this replaces

| Anti-pattern | Problem | Replacement |
|---|---|---|
| `// TODO: implement someday` | No issue, no deadline, no agent-readable anchor | `todo!("see #{N}")` bound to a filed issue |
| `// FIXME: known bug` | Same problem | File issue; `todo!("see #{N}")` at the known-bug callsite |
| `// XXX: not sure about this` | Design ambiguity that never resolves | File issue or RFC-labeled discussion; link in code comment |
| `// HACK: temporary` | Technical debt that never gets addressed | File issue; mark deprecated if the pattern should be removed |

The auditor's `code-quality` concern greps for `TODO|FIXME|XXX|HACK` in lane-modified files and grade-caps the sprint on any hit (per `agents/auditor.md`). This doctrine explains WHY — those patterns are silent debt; language primitives with issue anchors are loud, trackable debt.

---

## The issue lifecycle contract

```
filed → in-sprint → implementation lands → acceptance criteria pass → issue closes
```

At each sprint close, the `completeness` auditor runs:
```bash
# Verify every `todo!/unimplemented!/raise NotImplementedError/panic("TODO` site
# cites an open GH issue:
rg "todo!\(|unimplemented!\(|raise NotImplementedError|panic\(\"TODO" --type rust
# For each match, verify the #N reference exists and the issue is open.
```

If a primitive site's issue is CLOSED but the primitive is still in the code:
- **LOW finding**: implementation was done but primitive wasn't removed (stale stub).
- **MEDIUM finding**: if the stub has existed across 2+ sprints post-issue-close (chronic stale).

If a primitive site's issue is OPEN:
- Normal carry-forward state — the issue is the tracking mechanism.

---

## The 4-primitives discipline in AI-driven workflows

When an agent reads the codebase:
- `todo!("see #1081")` is unambiguous: "there is planned work tracked at #1081; this is not a bug, it is a scheduled gap."
- `// TODO: implement someday` is hallucination opportunity: the agent cannot know if this was ever addressed, what its status is, or whether it's in-scope for the current sprint.

The primitives are the in-code contract that makes the codebase self-documenting to agents. They are NOT for the compiler's benefit alone — they are for the FLOCK's benefit. Engineers read them in Phase 0 mesh to understand the current implementation surface. Coders read them in Step 2 (verify `[CONTEXT-INVENTORY]`) to understand which gaps they're filling. Auditors read them at close to verify the sprint's implementation completeness.

---

## Enforcement

### @engineer (plan-time)
- Phase 0 mesh: `rg "todo!\(|unimplemented!\(" --type rust` (or equivalent per language) to enumerate all in-flight stubs and their issues. Surface this count in the mesh report.
- Every MUST-LAND lane that closes an issue must also verify its primitives are removed in `[ACCEPTANCE]`.

### @coder (implementation-time)
- When introducing a new stub, ALWAYS pair with `mcp__plugin_github_github__issue_write` to create or reference the backing issue.
- Never write `TODO` or `FIXME` as plain comments — use the language primitive or the GH issue directly.
- NEVER leave a stub without a `#N` reference.

### @auditor / `code-quality` (review-time)
- Grep for `TODO|FIXME|XXX|HACK` → any hit without a `#N` reference is a finding.
- Grep for stale primitives (primitive site's issue is closed) → LOW/MEDIUM finding.

### @auditor / `completeness` (close-time)
- Verify that every MUST-LAND lane's corresponding primitive was removed (acceptance grep must include the `rg ... → 0 hits` check for the stub).
- Verify the stub count did not GROW this sprint without matching new issues filed.

---

## Cross-doctrine references

- `doctrines/zero-duplicate-tolerance.md` — `[DO-NOT-DUPLICATE]` greps include primitive patterns; coders must not introduce a new `todo!()` for a concept that already has one
- `doctrines/carry-forward-refresh.md` — open stubs are tracked carry-forwards; chronic stubs get `chronic` label
- `doctrines/issue-ledger-awareness.md` — Phase 0 enumeration includes stub count as a ground-truth signal
- `agents/coder.md` Hard Prohibitions — `NEVER write a TODO or FIXME comment` is already encoded; this doctrine explains the WHY and provides the alternative
