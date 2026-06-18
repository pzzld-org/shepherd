# Field-shape dedup — the third leg of the mechanical shape-gate set

**Name-matching dedup cannot see a deliberately renamed duplicate.** The existing
anti-duplication stack (`index_symbols`, `queries/dedup-check.sql`,
`hooks/scripts/dedup_write_guard.sh`, and the conductor's `DEDUP-GATE` in
`zero-duplicate-tolerance.md`) all key on the *identifier*. They fire only when a
second definition **reuses the first one's name**. They are blind to the most
common large-workspace rot: a **second type for an existing concept under a
different name** — the rename-to-evade-dedup shadow.

It compiles green. No clippy lint, no test, no name-grep catches it. The duplicate
just accumulates and drifts until two subsystems silently disagree about the shape
of the same concept.

> A 2026-06-17 field-shape audit of one workspace (FL03/axiom) found **22 such
> clusters**: an orphaned canonical with zero consumers sitting next to a live
> shadow carrying all the traffic; four different `OpenPosition` shapes; three
> fill-event types; `EquityPoint` defined twice with different fields. Eight
> carried confessional doc-comments — *"mirrors the shape of X but defined locally
> to avoid a cross-crate dependency"*, *"named Y not X to avoid a collision."*

`shctx dups` (#157) closes that gap. It is the **third leg** of the mechanical
shape-gate set:

| Gate | Detects | Keyed on |
|---|---|---|
| `dep-hygiene` | cross-tier dependency edges | the dep DAG |
| `check-impls-defs` | definitions buried in `impl` blocks | AST position |
| **`shctx dups`** | **same-shape / different-name types** | **field shape** |

## What it does

`shctx dups` parses every `pub struct` / `pub enum` in the workspace and
fingerprints each by its **field set** — `(field_name, normalized_type)` pairs —
then clusters by similarity. Detection is **structural, not nominal**: a shadow
that restated `Uuid → String`, `DateTime → String`, `f64` field-for-field under a
new name still surfaces.

### Similarity metric

Weighted Jaccard over the typed-field set, **blended** with the field-NAME set so a
shadow whose field NAMES match (even when the types were restated) is still caught:

```
sim(a, b) = name_weight · jaccard(field_names) + (1 − name_weight) · jaccard(typed_pairs)
```

`name_weight` defaults to `0.5`. The threshold defaults to `0.7`. Both are tunable
per project (`[dups]` in `shepherd.toml`). Field-less shapes (unit / marker
structs) and shapes below `dups_min_fields` (default 2) are excluded — a marker
type has no shape to compare, and one-field shapes are pure noise.

### The three modes

1. **`shctx dups scan [--threshold F] [--fail-on …] [--update] [--json]`** — the
   workspace census. Clusters similar shapes, reports each cluster's members
   (`file:line`, consumer count), pairwise similarity, and a **suggested
   canonical** (the member in the lowest dep tier — a foundation-tier package, or
   the de-facto canonical carrying the traffic). `--update` persists the corpus to
   `index_struct_shapes` (so `check` is fast). `--fail-on
   {medium|high|foundation-blocking}` returns a non-zero exit for close-gates / CI.
   The headline severity, `foundation-blocking`, fires when an **orphan canonical
   (zero consumers) sits beside a live shadow** — the exact axiom pattern.

2. **`shctx dups check <file> | --stdin --as <path>`** — the authoring-time gate.
   Extracts a candidate's NEW defs and reports any existing corpus type with
   similarity ≥ threshold — *"`PositionRow { token_id, side, entry_price, size }`
   is 0.85-similar to `axiom_types::OpenPositionSnapshot` — reuse it?"* Exits `5`
   above the block threshold. This is what a subagent leans on instead of
   *remembering* every pre-built struct: the match is surfaced at the moment it
   writes, by shape, with the canonical home to import.

3. **`shctx dups registry show|allow|pin|update`** — the curated layer. A
   `concept → canonical home` pin map plus a **DO-NOT-MERGE allow-list** of
   intentional distinct-role twins (an order-direction `Side` vs an outcome
   `YesNo`; a venue REST `Fill` vs a backtest `SimFill`) so legitimate twins are
   never re-flagged. Feeds both `scan` and `check`. Lives at
   `<ns>/dups-registry.json` (tracked; operator-curated).

## Integration seams

- **PreToolUse(Write|Edit) hook** (`hooks/scripts/dups_write_guard.sh`) → runs
  `dups check` for every `@coder` `.rs` write. Config `[dups].dups_hook`:
  `off | warn` (default — surfaces `additionalContext`) `| block` (denies a
  match ≥ block-threshold). Fails open at every step — non-coder, non-rust,
  no python3, empty corpus → silent pass; it can only ever block on a real match.
  This is the shape-shaped sibling of `dedup_write_guard.sh`.
- **Corpus freshness** — `shctx refresh --scope=shapes` (folded into `refresh
  --all`, and thus `sprint open`) keeps `index_struct_shapes` current, so the
  authoring gate and the census both read a live corpus.
- **Close gate** — add `shctx dups scan --fail-on foundation-blocking` to
  `[gates].extra` (or run it at CLOSE) to make a new shadow fail the sprint.
- **Planter mesh row** — `shctx dups scan` is the deterministic dedup census that
  *replaces* the bespoke "9 read-only field-shape finders + synthesis" Workflow
  the audit used to need. Run it once per plant to seed the registry
  (`shctx dups registry update`).
- **Coder Phase-0** — a coder introducing types may run `dups check` on its own
  drafts before writing, exactly as it runs the name-dedup grep (Startup Protocol
  Step 3). The hook is the backstop; Phase-0 self-check is the cheaper first pass.

## The reuse story (why this is not just a blocker)

The operator's standing complaint is that subagents on large projects keep
**re-inventing structs they could have reused, because no one remembers every name
or invocation.** Memory does not scale; a shape index does. `dups check` turns
"did someone already model this?" from a recall problem into a deterministic lookup
keyed on the very thing the coder is about to type — the field set. The answer
arrives *as the coder writes*, names the canonical home, and offers to import it.

## Anti-patterns

- **"Clippy is green, so there's no duplicate."** — Wrong; the entire point is the
  class of duplicates that compile green. A shape gate, not subagent discipline,
  is what catches them.
- **"`dups` replaces name-dedup."** — Wrong; they are complementary legs. Name
  collisions are still cheaper to catch by name. `dups` adds the shape leg.
- **"Two same-shape types are always a bug."** — Wrong; intentional distinct-role
  twins exist. That is what the DO-NOT-MERGE allow-list is for — but the default is
  to flag, and the burden is on the operator to allow-list, not on the gate to
  guess.
- **"Just lower the threshold to catch everything."** — Wrong; below ~0.6 the
  false-positive rate on small shapes drowns the signal. Tune `name_weight` and
  `min_fields` first; allow-list the rest.

## See also

- `doctrines/zero-duplicate-tolerance.md` — the name-keyed dedup stack this extends
- `doctrines/wrapper-must-earn.md` — a special case (a wrapper is a one-field shadow)
- `doctrines/subtract-dont-add.md` — duplicates accrete LOC; SUBTRACT enforces deletion
- `skills/context/scripts/cmd_dups.sh` + `dups-core.py` — the implementation
- `skills/context/schema/migrations/0015_struct_shapes.sql` — the corpus table
- `hooks/scripts/dups_write_guard.sh` — the PreToolUse authoring gate
