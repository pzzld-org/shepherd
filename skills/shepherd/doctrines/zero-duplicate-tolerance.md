# Zero-duplicate tolerance — dedup is a conductor pre-dispatch gate

**Duplicate code never lands.** Not because coders self-halt (they often
don't), not because auditors catch it at close (too late, drift already
shipped), but because the conductor runs the anti-duplication greps
**before the Agent batch fires** and blocks dispatch on any non-zero result.

This elevates anti-duplication from a coder-side last-line-of-defense to a
conductor-side pre-flight gate. The pre-4.2.0 model trusted coders to halt on
`DUPLICATION RISK` — and they often didn't, or halted *after* burning context
on a partial implementation. The 4.2.0 model removes that trust by running
the gate one tier upstream.

## The operator's bar

> "If I see another line of duplicate code I will uninstall Claude Code immediately."

## Three layers of defense (each independently sufficient)

### Layer 1 — Engineer pre-population (planning time)

The engineer's plan MUST populate `[CONTEXT-INVENTORY]` AND `[DO-NOT-DUPLICATE]`
for every coder lane (`agents/engineer.md` §"plan-quality bar"). The engineer:

1. **Reads `{paths.ctx}/canonical-types.md`** FIRST — the workspace's
   authoritative type catalog (every public type/trait/function/constant and its owning package).
2. **For every new identifier a lane will introduce**, runs the
   language-specific detection grep at plan-time and embeds it in
   `[DO-NOT-DUPLICATE]` with the expected count.
3. **For every existing symbol a lane will reuse**, cites it in
   `[CONTEXT-INVENTORY]` with absolute path + one-line description.

A plan whose `[DO-NOT-DUPLICATE]` is empty for a lane introducing new types
is a process violation — reject back to engineer.

### Layer 2 — Conductor pre-dispatch gate (THE PRIMARY DEFENSE)

**Before firing any WAVE-IMPL Agent batch, the conductor runs every
`[DO-NOT-DUPLICATE]` grep itself** — not the coder — inline, sequentially per
lane, output captured.

```bash
for grep_pattern in lane.do_not_duplicate:
    hits = run(grep_pattern)
    if hits != expected_count:
        BLOCK DISPATCH
```

If any grep returns `N > expected`: dispatch is BLOCKED (no coder context
burned) and the conductor surfaces the conflict:

```
DEDUP-GATE BLOCK — Lane <id>: pattern `<pattern>` returned N=<hits> > expected=<expected>.
Existing locations: <paths>
Resolution options:
  (a) Convert lane to "wire to existing": reuse <existing-symbol-at-path>
  (b) Replace existing implementation: re-scope to delete prior + author canonical (operator approval required)
  (c) Extend existing: amend brief to extend prior implementation in place
  (d) Operator-justified divergence: note in [CONTEXT-INVENTORY] why two implementations are warranted (rare; defaults NO)
Conductor recommendation: <a|b|c|d>
```

The conductor amends the lane brief per the operator's choice, then
re-runs the gate. The batch fires only when every lane's greps return the expected count.

Graph node: `DEDUP-GATE` (`pipeline.md` §II), in_predicates from PLAN-GATE
on-green, sequential by design, out_edges `on-pass` → WAVE-1-IMPL and
`on-block` → DEDUP-RECONCILE (conductor inline).

**Layer 2 SQL fast-path (v5.0.0+).** When `.artifacts/root.db` is present,
run `shctx query dedup-check --name=<symbol>` first. A hit pre-blocks
dispatch citing `file_path:line`; a miss falls through to the slower grep.
The grep remains the contract; SQL is a cheap pre-filter (`doctrines/context-registry.md`).

### Layer 3 — Coder self-halt (fallback)

The coder's `Startup Protocol` Step 3 still runs the dedup greps as a
**fallback** — Layer 2 should have caught any duplication first. If the coder
finds a risk the conductor missed, it halts with `DUPLICATION RISK: <pattern>
hit N times` and the conductor re-evaluates (file as an engineer-quality
finding for the auditor's `completeness` concern). Coder self-halt is a
tripwire, not a contract; Layer 2 carries the contract.

### Layer 4 — Field-shape gate (the renamed-shadow leg, v6.1.8 #157)

Layers 1–3 key on the **identifier** and are blind to a *second type for an
existing concept under a different name* — the rename-to-evade-dedup shadow
that compiles green. **`shctx dups`** closes that gap by clustering `pub
struct`/`pub enum` definitions on **field shape** (weighted Jaccard over
`(field_name, normalized_type)`, with a field-name-match bonus). `dups check`
runs in a PreToolUse(Write|Edit) hook (`dups_write_guard.sh`) so a coder is
told *"this is 0.85-similar to `pkg::ExistingType` — reuse it?"* at authoring
time; `dups scan --fail-on foundation-blocking` is a CLOSE/CI census. Full
detail: `doctrines/shape-dedup.md`.

## The canonical-types index (`{paths.ctx}/canonical-types.md`)

The workspace knowledge silo is the conductor's anti-duplication memory.
Every patch's dev.0 fires a `WORKER-IO` node — `canonical-types-refresh` —
that walks the workspace and emits/updates the catalog:

```markdown
# Canonical types — workspace authoritative catalog
Last refreshed: <date> at sprint <sprint_branch>

## By package
### crates/circuits
- `DriftCircuit` (struct) — handles drift-state transitions
- `Tick` (trait) — circuit tick interface

## By concept (deduplication index)
| Concept | Canonical home | Aliases to AVOID |
|---|---|---|
| Drift detection | `crates/circuits::DriftCircuit` | DriftDetector, DriftHandler, DriftMonitor |
```

Subsequent sprints' Phase 0 mesh reads this catalog BEFORE the open-issue
ledger sweep. The engineer's `[CONTEXT-INVENTORY]` MUST cite from it when a
lane touches a known concept. The auditor's `dependency-topology` concern
verifies the catalog is current at sprint close.

## Skill auto-attachment (the right tools, every time)

A coder produces high-quality output ONLY when the right skills are loaded.
Skill loading must be **mechanical**, not "engineer remembers to add it":

### Conductor responsibility (NOT engineer's, NOT coder's)

For every coder dispatch, the conductor MECHANICALLY computes `[SKILLS]`:

```
[SKILLS] := [skills.mandatory]                                 # always (e.g., code-style)

for path in [FILE-SCOPE].MAY_MODIFY:
    for (pattern, skill_list) in [skills.detection]:
        if path matches pattern:
            [SKILLS] += skill_list
            break

for domain in detect_domains([FILE-SCOPE]):                    # finance, payments, supabase, ...
    [SKILLS] += [skills.by_domain][domain]

[SKILLS] := dedupe([SKILLS])
```

The engineer's plan MAY suggest skills; the conductor's computation is
authoritative — it adds missing entries, and warns then keeps-or-drops any
suggestion outside the detection patterns depending on whether
`[CONTEXT-INVENTORY]` justifies it.

### Required-skills floor (per file-scope language)

Every coder brief MUST contain at minimum:

- `code-style` (always — operator's per-language preferences)
- The matching primary-language skill, auto-derived from extension
  (.rs→`rust`, .py→`python`, .ts/.tsx→`typescript`, .go→`go`)

If the file scope spans multiple languages, EVERY matching language skill
loads (multi-language coder briefs are valid and common).

### Domain skill detection

Per `[skills.detection]` in `shepherd.toml`:

```toml
[skills.detection]
"crates/finance/**"    = ["finance"]
"crates/payments/**"   = ["payments", "billing"]
"db/migrations/**"     = ["supabase:supabase"]
"crates/wasm-host/**"  = ["webassembly"]
```

The conductor walks `[FILE-SCOPE]` against these patterns and union-merges
the resulting skill set into `[SKILLS]`.

### Brief-Validity Checklist enforcement

The Brief-Validity Checklist (`references/agent-briefs.md`) now includes:

- [ ] `[SKILLS]` matches the conductor's mechanical computation (engineer's suggestions are a SUBSET, never a SUPERSET-with-omissions)?
- [ ] Every primary-language file in `[FILE-SCOPE]` has its language skill in `[SKILLS]`?
- [ ] Every `[skills.detection]` pattern matching a `[FILE-SCOPE]` path contributes its skills?

A brief failing this is a process violation — the conductor recomputes and re-verifies before dispatch.

### Code-style auto-attachment (v5.0.0+)

The mechanical `[SKILLS]` computation is augmented by a `[CODE-STYLE]` block:
for every language in `[FILE-SCOPE]`, the conductor reads
`.artifacts/styles/<lang>.md` (project-local override, bootstrapped via
`shctx style init <lang>` if missing) and prepends it verbatim as
`[CODE-STYLE]`. The bundled `code-style` skill stays in `[SKILLS]`; project
rules win on conflict. Delivers operator-specific conventions per dispatch
without bloating the universal skill.

## Build-on-one-another consistency (cross-coder coherence)

When a wave has N parallel coders, their outputs must compose cleanly:

1. **`[CONTEXT-INVENTORY]` cites are SHARED across the wave.** If Lane A
   introduces a symbol Lane B will consume, Lane B cites it `(introduced this
   wave by Lane A)` even before it exists.
2. **Public-API touch-points are single-writer.** Two lanes touching a
   re-export are sequenced, not parallel — the conductor's parallel-safety
   check catches this.
3. **Naming conventions are language-skill-derived, not coder-invented.**
   `code-style:<lang>` + the language skill is the entire bar; no coder
   decides naming locally.
4. **Cross-coder dependency edges are graph-encoded.** A lane depending on a
   prior lane is `WAVE-2-IMPL`, not `WAVE-1-IMPL` — later waves cite earlier outputs as if they exist.

Each coder brief loads exactly the matching primary-language skill +
`code-style:<language>.md` + detected domain skills — never cross-injected
(a Rust coder never loads TypeScript patterns). Polyglot workspaces split
into per-language lanes; a multi-language single lane is an anti-pattern (too
many skills, diluted focus).

## Auditor enforcement at close

The `dependency-topology` and `code-quality` auditors verify dedup discipline:

- **Wrapper-grep gate** (`wrapper-must-earn.md`) — the language-skill's wrapper-detection grep
- **Dedup-grep gate** (this doctrine) — re-runs every `[DO-NOT-DUPLICATE]` grep against the post-sprint workspace
- **Canonical-types staleness** — verifies the catalog includes every new public type (finding if missing)
- **Skill-attachment audit** — verifies every coder dispatch's `[SKILLS]` matched the mechanical computation

Any violation → `DUPLICATION-DRIFT` finding, grade-cap C+.

## Anti-patterns

- **"The coder will run the greps; conductor doesn't need to."** Wrong — coder-side halt is the fallback; the conductor's pre-dispatch gate is the contract.
- **"`[DO-NOT-DUPLICATE]` is empty because the lane is small."** Wrong — any new identifier makes the grep mandatory.
- **"The engineer's `[SKILLS]` list is good enough."** Wrong — the conductor recomputes mechanically.
- **"We don't need `{paths.ctx}/canonical-types.md` for a small project."** Wrong — mandatory past 5 packages; below that the conductor walks the package tree at Phase 0 instead.
- **"This duplicate is fine because the operator can refactor later."** Wrong — the operator's bar is zero.
- **"Lane B can introduce its own version since Lane A's symbol isn't merged yet."** Wrong — cross-wave coordination is graph-encoded; Lane B waits and cites Lane A's symbol.

## See also

- `pipeline.md` §II — `DEDUP-GATE` node type
- `doctrines/shape-dedup.md` — field-shape dedup (`shctx dups`, the renamed-shadow leg)
- `doctrines/stage-graph.md` — graph-encoded dispatch
- `doctrines/wrapper-must-earn.md` — wrapper-grep gate (a special case of dedup)
- `doctrines/subtract-dont-add.md` — duplicates accrete LOC; SUBTRACT enforces deletion
- `agents/engineer.md` — plan-quality bar requires `[CONTEXT-INVENTORY]` + `[DO-NOT-DUPLICATE]` per lane
- `agents/coder.md` — Startup Protocol Step 3 (fallback dedup)
- `references/agent-briefs.md` — Brief-Validity Checklist (now enforces auto-attachment)
- `flock.md` §II.@coder — Required-Skills Matrix
- `planter.md` §IX-ter — Phase 0 dedup-grep gate (canonical mesh row)
