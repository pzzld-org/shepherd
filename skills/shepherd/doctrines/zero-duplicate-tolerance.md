# Zero-duplicate tolerance — dedup is a conductor pre-dispatch gate

**Duplicate code never lands.** Not because coders self-halt (they often don't), not because auditors catch it at close (too late, drift already shipped), but because the conductor runs the anti-duplication greps **before the Agent batch fires** and blocks dispatch on any non-zero result.

This doctrine elevates anti-duplication from a coder-side last-line-of-defense to a conductor-side pre-flight gate. The pre-4.2.0 model trusted coders to halt on `DUPLICATION RISK` — and they often didn't, or they halted *after* burning context on a partial implementation. The 4.2.0 model removes that trust by running the gate one tier upstream.

## The operator's bar

> "If I see another line of duplicate code I will uninstall Claude Code immediately."

That is the bar. This doctrine codifies what shepherd does to clear it.

## Three layers of defense (each independently sufficient)

### Layer 1 — Engineer pre-population (planning time)

The engineer's plan MUST populate `[CONTEXT-INVENTORY]` AND `[DO-NOT-DUPLICATE]` for every coder lane (per `agents/engineer.md` §"plan-quality bar"). The engineer:

1. **Reads `{paths.ctx}/canonical-types.md`** as the FIRST input to every plan-time decision. This file is the workspace's authoritative type catalog — every public type, trait, function, constant, and which package owns it.
2. **For every new identifier the lane will introduce**, runs the language-specific detection grep at plan-time and embeds it in `[DO-NOT-DUPLICATE]` with the expected count.
3. **For every existing symbol the lane will reuse**, cites it in `[CONTEXT-INVENTORY]` with absolute path + one-line description.

A plan whose `[DO-NOT-DUPLICATE]` is empty for a lane that introduces new types is a process violation — reject back to engineer.

### Layer 2 — Conductor pre-dispatch gate (THE PRIMARY DEFENSE)

**Before firing any WAVE-IMPL Agent batch, the conductor runs every `[DO-NOT-DUPLICATE]` grep itself.** Not the coder; the conductor. Inline. Sequentially per lane. Output captured.

```bash
# For each lane in the wave:
for grep_pattern in lane.do_not_duplicate:
    hits = run(grep_pattern)
    if hits != expected_count:
        BLOCK DISPATCH
```

If any grep returns `N > expected`:

1. **Dispatch is BLOCKED.** The Agent batch does NOT fire. No coder context burned.
2. **The conductor surfaces the conflict** with a structured block:
   ```
   DEDUP-GATE BLOCK — Lane <id>: pattern `<pattern>` returned N=<hits> > expected=<expected>.
   Existing locations: <paths>
   Resolution options:
     (a) Convert lane to "wire to existing": replace planned new-type introduction with reuse of <existing-symbol-at-path>
     (b) Replace existing implementation: lane re-scoped to delete prior + author canonical (operator approval required)
     (c) Extend existing: amend brief to extend prior implementation in place
     (d) Operator-justified divergence: explicit note in [CONTEXT-INVENTORY] explaining why two implementations are warranted (rare; defaults to NO)
   Conductor recommendation: <a|b|c|d>
   ```
3. **The conductor amends the lane brief** (per the operator's chosen option) BEFORE re-running the gate.
4. **The Agent batch fires only when every grep across every lane returns the expected count.**

This is a graph node: `DEDUP-GATE` (per `pipeline.md` §II), in_predicates from PLAN-GATE on-green, parallel_with nothing (sequential by design), out_edges `on-pass` → WAVE-1-IMPL and `on-block` → DEDUP-RECONCILE (conductor inline).

**Layer 2 SQL fast-path (v5.0.0+).** When `.artifacts/root.db` is present, run `shctx query dedup-check --name=<symbol>` first. A hit pre-blocks dispatch (citing `file_path:line` from the DB). A miss falls through to the slower grep. The grep remains the contract; SQL is a cheap pre-filter. See `doctrines/context-registry.md`.

### Layer 3 — Coder self-halt (fallback)

The coder's `Startup Protocol` Step 3 still runs the dedup greps. This is now a **fallback** — the conductor's pre-dispatch gate should have caught any duplication before Step 3 ever runs. If the coder finds a duplication risk the conductor missed, it halts with `DUPLICATION RISK: <pattern> hit N times` and the conductor re-evaluates (the engineer's `[DO-NOT-DUPLICATE]` was incomplete — file as engineer-quality finding for the auditor's `completeness` concern).

Coder self-halt is a tripwire, not a contract. Layer 2 carries the contract.

## The canonical-types index (`{paths.ctx}/canonical-types.md`)

The workspace knowledge silo is the conductor's anti-duplication memory. Every patch's dev.0 fires a `WORKER-IO` node — `canonical-types-refresh` — that walks the workspace and emits/updates `{paths.ctx}/canonical-types.md`:

```markdown
# Canonical types — workspace authoritative catalog

Last refreshed: <date> at sprint <sprint_branch>

## By package

### crates/circuits
- `DriftCircuit` (struct) — handles drift-state transitions
- `DriftConfig` (struct) — config for DriftCircuit
- `Tick` (trait) — circuit tick interface

### crates/engine
- `Allocator` (struct) — allocates capital across bots
- ...

## By concept (deduplication index)

| Concept | Canonical home | Aliases to AVOID |
|---|---|---|
| Drift detection | `crates/circuits::DriftCircuit` | DriftDetector, DriftHandler, DriftMonitor |
| Order book snapshot | `crates/market::OrderBook` | Book, MarketBook, OrderbookSnapshot |
| ... | | |
```

Subsequent sprints' Phase 0 mesh reads `{paths.ctx}/canonical-types.md` BEFORE running the open-issue ledger sweep. The engineer's `[CONTEXT-INVENTORY]` for every new lane MUST cite from this catalog when the lane touches a known concept.

The auditor's `dependency-topology` concern verifies the catalog is current at sprint close.

## Skill auto-attachment (the right tools, every time)

A coder produces high-quality output ONLY when the right skills are loaded. Skill loading must be **mechanical**, not "engineer remembers to add it":

### Conductor responsibility (NOT engineer's, NOT coder's)

For every coder dispatch, the conductor MECHANICALLY computes `[SKILLS]` per the following algorithm:

```
[SKILLS] := [skills.mandatory]                                 # always (e.g., code-style)

for path in [FILE-SCOPE].MAY_MODIFY:
    for (pattern, skill_list) in [skills.detection]:
        if path matches pattern:
            [SKILLS] += skill_list
            break

for domain in detect_domains([FILE-SCOPE]):                    # finance, polymarket, supabase, ...
    [SKILLS] += [skills.by_domain][domain]

[SKILLS] := dedupe([SKILLS])
```

The engineer's plan MAY suggest skills; the conductor's mechanical computation is authoritative. If the engineer suggested a subset, the conductor adds the missing entries. If the engineer suggested skills outside the detection patterns, the conductor warns and either keeps them (if the engineer's plan justifies them in `[CONTEXT-INVENTORY]`) or drops them.

### Required-skills floor (per file-scope language)

Every coder brief MUST contain at minimum:

- `code-style` (always — operator's per-language preferences)
- The matching primary-language skill (`rust`, `python`, `typescript`, `go`, ...) — auto-derived from extension (.rs → `rust`, .py → `python`, .ts/.tsx → `typescript`, .go → `go`)

If the file scope spans multiple languages, EVERY matching language skill loads (multi-language coder briefs are valid and common).

### Domain skill detection

Per `[skills.detection]` in `shepherd.toml`:

```toml
[skills.detection]
# Path patterns → skill slugs
"crates/finance/**"    = ["finance"]
"crates/polymarket/**" = ["polymarket", "trader"]
"db/migrations/**"     = ["supabase:supabase"]
"crates/wasm-host/**"  = ["webassembly"]
```

The conductor walks `[FILE-SCOPE]` against these patterns and union-merges the resulting skill set into `[SKILLS]`.

### Brief-Validity Checklist enforcement

The Brief-Validity Checklist (in `references/agent-briefs.md`) now includes:

- [ ] `[SKILLS]` matches the conductor's mechanical computation (engineer's suggestions are a SUBSET, never a SUPERSET-with-omissions)?
- [ ] Every primary-language file in `[FILE-SCOPE]` has its language skill in `[SKILLS]`?
- [ ] Every `[skills.detection]` pattern matching a `[FILE-SCOPE]` path contributes its skills?

A brief failing this is a process violation — the conductor recomputes and re-verifies before dispatch.

### Code-style auto-attachment (v5.0.0+)

The mechanical `[SKILLS]` computation is augmented by a `[CODE-STYLE]` block. For every language detected in `[FILE-SCOPE]`:

1. Conductor reads `.artifacts/styles/<lang>.md` (project-local override).
2. Block is prepended to the coder brief verbatim under `[CODE-STYLE]`.
3. If the file is missing, conductor runs `shctx style init <lang>` to bootstrap from the plugin default.
4. The bundled `code-style` skill remains in `[SKILLS]`. Project rules (the block) override skill rules on conflict.

This delivers operator-specific code conventions to every coder dispatch without bloating the universal `code-style` skill.

## Build-on-one-another consistency (cross-coder coherence)

When a wave has N parallel coders, their outputs must compose cleanly. Discipline:

1. **`[CONTEXT-INVENTORY]` cites are SHARED across the wave.** If Lane A introduces a new public symbol and Lane B will consume it, Lane B's `[CONTEXT-INVENTORY]` cites Lane A's symbol with `(introduced this wave by Lane A)` — even though it doesn't exist yet at dispatch time. Lane B knows what to expect.
2. **Public-API touch-points are single-writer.** If two lanes both touch a re-export, they're sequenced — not parallel. The conductor's pre-dispatch parallel-safety check catches this.
3. **Naming conventions are language-skill-derived, not coder-invented.** `code-style:<lang>` carries the operator's preferences (snake_case vs camelCase, `Result<T, E>` vs `Either<E, T>`, etc.). Loading `code-style` AND the language skill is the entire bar — no coder decides naming locally.
4. **Cross-coder dependency edges are graph-encoded.** If Lane B depends on Lane A landing first, the Stage Graph encodes Lane B as `WAVE-2-IMPL` not `WAVE-1-IMPL`. Wave-N+1 lanes can `[CONTEXT-INVENTORY]`-cite wave-N outputs as if they exist; they will by the time the lane fires.

## Adapt-to-target-language enforcement

Every coder brief loads:
1. The matching primary-language skill (idioms, build commands, type system)
2. `code-style:<language>.md` (operator's per-language preferences)
3. Domain skills as detected

This is the entire stack. A coder writing Rust loads `rust` + `code-style` (its `rust.md` ledger) + any domain skills. A coder writing TypeScript loads `typescript` + `code-style` + domain skills. The framework does NOT inject Rust patterns into TypeScript work or vice versa.

If the workspace is polyglot (e.g., Rust backend + TypeScript frontend), each coder lane is single-language by `[FILE-SCOPE]` design. The engineer's plan splits multi-language work into per-language lanes; multi-language single lanes are an anti-pattern (load too many skills, dilute coder focus).

## Auditor enforcement at close

The `dependency-topology` and `code-quality` auditors verify dedup discipline:

- **Wrapper-grep gate** (per `wrapper-must-earn.md`) — runs the language-skill's wrapper-detection grep
- **Dedup-grep gate** (per this doctrine) — re-runs every `[DO-NOT-DUPLICATE]` grep from every lane against the post-sprint workspace
- **Canonical-types staleness** — verifies `{paths.ctx}/canonical-types.md` includes every new public type introduced by the sprint (writes a finding if missing)
- **Skill-attachment audit** — verifies every coder dispatch's `[SKILLS]` matched the mechanical computation (reads dispatch logs / brief artifacts)

Any violation of any of these → `DUPLICATION-DRIFT` finding, grade-cap C+.

## Anti-patterns

- **"The coder will run the greps; conductor doesn't need to."** — Wrong; coder-side halt is the fallback. The conductor's pre-dispatch gate is the contract.
- **"`[DO-NOT-DUPLICATE]` is empty because the lane is small."** — Wrong; if the lane introduces ANY new identifier, the grep is mandatory.
- **"The engineer's `[SKILLS]` list is good enough."** — Wrong; conductor recomputes mechanically.
- **"We don't need `{paths.ctx}/canonical-types.md` for a small project."** — Wrong; the moment the workspace exceeds 5 packages, the catalog is mandatory. Below that, the conductor walks the package tree at Phase 0 instead.
- **"This duplicate is fine because the operator can refactor later."** — Wrong; the operator's bar is zero. Refactoring later is the failure mode this doctrine exists to prevent.
- **"Lane B can introduce its own version since Lane A's symbol isn't merged yet."** — Wrong; cross-wave coordination is graph-encoded. Lane B waits for Lane A and cites its symbol.

## See also

- `pipeline.md` §II — `DEDUP-GATE` node type
- `doctrines/stage-graph.md` — graph-encoded dispatch
- `doctrines/wrapper-must-earn.md` — wrapper-grep gate (a special case of dedup)
- `doctrines/subtract-dont-add.md` — duplicates accrete LOC; SUBTRACT enforces deletion
- `agents/engineer.md` — plan-quality bar requires `[CONTEXT-INVENTORY]` + `[DO-NOT-DUPLICATE]` per lane
- `agents/coder.md` — Startup Protocol Step 3 (fallback dedup)
- `references/agent-briefs.md` — Brief-Validity Checklist (now enforces auto-attachment)
- `flock.md` §II.@coder — Required-Skills Matrix
- `planter.md` §IX-ter — Phase 0 dedup-grep gate (canonical mesh row)
