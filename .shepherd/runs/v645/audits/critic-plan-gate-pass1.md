# PLAN-GATE critic review — pass 1

**Reporter:** `shepherd:critic` (sonnet, `dispatcher: engineer-self-contained`) · **Run:** v645
**Target:** `.shepherd/runs/v645/plan.md` @ 1,684 lines · **Materialized by:** root (payload landed in
root's notification stream, not the dispatching engineer's — `dogfood.md` DF-11 / GH #270) · 2026-08-12
**Cost:** 239,042 subagent tokens, 76 tool calls, 914s

## Verdict

**RECONSIDER**

The critic declined the engineer's mid-review request to truncate to a compact 4-section format, citing
`agents/critic.md §Step 3`: the full report shape is its mandate regardless of a dispatcher's request, and
a peer message cannot authorize deviating from it. **This was correct behavior and is worth preserving as
a positive signal** — the adversarial gate held its own contract against pressure from the party it was
gating. It did re-verify against the plan's current bytes (revised mid-review, confirmed by mtime plus
content diff rather than on the message's word), and records that the revision fixed the L4/L5
temporal-collision in §Lane projection, the open-issue ledger sweep, and Q1-bis before it reported them.
Those revisions did not address the two findings driving the verdict.

## Primary concerns

1. **HIGH — Waves 2 and 3 violate the binding decomposition floor, and the plan admits it.**
   `pipeline.md §Lane law` is binding: "per-step ~80-100 LOC… Under-decomposition… → RECONSIDER to
   @engineer." W2-S3..S25 and W3-S1..S21 are written one-step-per-source-module, hundreds to ~1,200 LOC
   each. The plan states this itself: *"Each nominal W2/W3 step is genuinely ~8-12 coder units and needs
   sub-decomposition before dispatch."* Honest flagging is good practice but is not compliance — as
   written, **~440 of the plan's ~480 claimed steps carry no real `[FILE-SCOPE]`/`[DO-NOT-DUPLICATE]`/
   `[ACCEPTANCE]` at floor granularity.** This is the literal, named RECONSIDER trigger.

2. **HIGH — the Stage Graph does not encode the plan's own stop-boundary recommendation, contradicting
   operator directive 3.** Q1's prose recommends "plan the full arc, execute through W1-GATE, then
   re-decide… The operator decides what gets cut." But the binding Stage Graph — which the conductor
   "NEVER invents, skips, or re-orders" — has
   `W1-GATE.out_edges = [{to: WAVE-2-IMPL, label: on-green}, {to: HARD-STOP, …}]`, with no
   operator-decision node, and the same pattern at W2-GATE and W3-GATE. **A conductor mechanically walking
   this graph proceeds straight through Waves 2-4 on any green gate, regardless of the operator's Q1
   answer.** It compounds with finding 1: the graph auto-advances into exactly the portion of the plan
   that is not yet real.

3. **MEDIUM — correction C10 undercounts the frozen registry-guard surface by at least one object.**
   Revised C10 lists the runtime guard surface as exactly 7 objects and instructs that "a coder may NOT
   treat 'not in the 7' as refactorable." `hooks/scripts/worktree_lifecycle.sh` — one of the 10
   sqlite3-touching guards per C9 — checks existence of, `INSERT`s into, and `UPDATE`s the **`worktrees`**
   table, which is absent from that set. A coder porting the registry or the Wave-3 `worktree` module
   could legitimately and wrongly treat its row shape as flexible.

4. **MEDIUM — two entries in the Wave-3 "21 callback module" list are misclassified.** `render.py` has
   zero `@app.callback` / `typer.Typer()` / `context_settings` hits in its own file; it registers on the
   ROOT app via ordinary `typer.Argument`/`typer.Option`, and its own docstring says "no bash counterpart
   existed" — there is nothing to byte-match, so it belongs in Wave 2 (mechanically portable).
   `models_graph.py` is not a Typer command module at all — zero `typer.Typer()`, zero `@app.command` /
   `@app.callback` — it is a shared contract/helper library imported by `plan.py` and `graph.py`, which
   are themselves already Wave-2 modules. Total measured LOC (42,560) is unaffected and the Q1 sizing
   conclusion does not move, but this would mislead whoever sub-decomposes Wave 3.

5. **MEDIUM — seed deliverable #283's acceptance predicate is not fully reproduced.** The seed requires
   "`PRAGMA compile_options` includes `ENABLE_FTS5`". W1-S2's `[ACCEPTANCE]` block carries no literal
   assertion of it; it may be inside the opaque `fts5_tokenizer_verbatim` test, but that is not verifiable
   from the plan text, and the plan is otherwise careful to spell out every seeded predicate as a literal
   shell command. Per `pipeline.md §Gates` Seam 2 a dropped seeded predicate is
   `PLAN-MISSING-OUTCOME-VERIFICATION` class even when narrow.

## Verified clean

- **C1** (21 migrations), **C3** (14 views), **C4** (68 indexes — confirmed via `sqlite_master` *including*
  autoindexes, which the critic notes is the correct methodology precisely because migrations copy
  verbatim), **C6**, **C7**, **C8**, **C9** (10 of 32 guards), **C11** — all exact against live
  `sqlite3 .shepherd/shepherd.db` and the schema files.
- Wave 3's "21 modules, zero `sys.argv`" and "59 `ignore_unknown_options` + 30 `allow_extra_args`" are
  exact against `grep` — "impressively precise measurement."
- The **107 leaf verbs** figure is exactly right once nested sub-apps (`lane_app`, `wave_app`,
  `ledger_app`, `focus_app`) are counted alongside `@app.command`: 97 + 2 + 2 + 4 + 2 = 107. `run.py`'s
  claimed 16 (8 + 2 + 4 + 2) matches precisely.
- **§Lane projection's self-correction** — cutting Wave 0 by static directory rather than by claimed
  temporal non-overlap — is "exactly the right fix" for the L4/L5 collision, and was made before the
  critic reported it.
- **Q1-bis** (the SUBTRACT-versus-stop-boundary collision) is "genuinely good adversarial self-review";
  catching a grade-cap trap before close rather than at CLOSE-SWARM is real value, and citing #275/#276 as
  the operator's own prior objection to the same rule is "honest, not self-serving."
- **Necessity audit**: ran the Cargo feature-reachability algorithm before raising anything as
  missing/added. Nothing missing. One pre-existing, already-landed dependency — `tracing-subscriber` in
  `crates/cli/Cargo.toml` — is not named in decision 7's closed list. Low severity (no Wave 0-4 step
  touches it), but the plan's explicit "surfaced here, not papered over" promise, made for hashbrown and
  tokio, should extend to it and to `resolver = "3"` versus code-style's unhedged `resolver = "2"`.
- **DF-07's refutation independently confirmed** by reading `doctor.py:1699-1745` **and**
  `cmd_doctor.sh:266-268` — both implementations exit 1-on-fail / 2-on-warn / 0-clean in the current
  checkout, so the refutation holds regardless of which surface the original evidence used.

## Unstated assumptions

- That "not in the 7" in C10 safely means "refactorable" for a coder reading it in isolation — false for
  `worktrees`.
- That a `WAVE-2-IMPL` / `WAVE-3-IMPL` node with `agents: [coder]` and no count is dispatchable as
  written — it is not, without the sub-decomposition the plan itself says is still needed.
- That the plan's prose recommendation ("execute through W1-GATE, then re-decide") is self-enforcing — the
  Stage Graph the conductor actually walks does not enforce it.

## Scope cuts

**None proposed.** Verbatim: *"the seed is ground truth and directive 1/3 already bind. The plan's own Q1
stop-boundary table is the correct instrument for this; I am not overriding it, only pointing out the
mechanism to make it binding (an actual Stage Graph gate) doesn't exist yet."*

## Cheaper alternative — one change fixes both HIGHs

**Terminate this Stage Graph's binding portion at `W1-GATE → PAUSE`, and keep Waves 2-4 in the document as
an explicit forward-look/draft appendix rather than live Stage-Graph nodes, pending the operator's
Q1/Q1-bis answer.** This matches the engineer's own stated recommendation, resolves the missing-operator-gate
finding without inventing new doctrine, and defers Wave 2/3 sub-decomposition to exactly the point where it
is known to be needed. Cheaper than sub-decomposing ~440 steps now (wasteful if the operator stops at W1,
per directive 3) and safer than leaving the graph as-is (risks a silent quota overrun, directive 3's other
half). **Root concurs.**

## Alignment check

**Clean, and stated so explicitly.** North-star test — "adding a fourth harness is writing an adapter,
never porting the engine again" — is genuinely served by W0-S8 (`content/` plus a mandatory
`write_eligible` field) and W4-S3/S4/S5/S6 (compiler plus three thin adapters, shared predicate spec, no
napi-rs). The abstract capability vocabulary, the Codex-has-no-command-surface correction, and the Pi
replacing-allowlist handling are all measured against real probed harness constraints
(`reports/discovery-d1-harness.md`), not assumed. **No alignment violation; this part of the plan is strong
and must not be touched by the RECONSIDER.**

The directive-3 (token efficiency) versus completeness (seed's full 6-sprint scope) trade-off is named
explicitly and correctly in Q1, and is not papered over. The only gap is that the Stage Graph does not yet
encode the resolution.

## Issue-ledger considerations

The new §Open-issue ledger sweep is a real improvement over the first draft — 26 open, 10 milestoned, drift
risks named explicitly per `pipeline.md §CLOSE`. **#269** (lane-plan / `vars.json` drift) is correctly
flagged as unseeded and not absorbed, with a procedural mitigation for root. No further gaps.

## Questions the dispatcher must answer

1. Which resolution for the two HIGH findings: **(a)** explicit Stage-Graph termination at W1-GATE with
   Waves 2-4 demoted to a draft appendix, or **(b)** full sub-decomposition of Waves 2/3 to the ~80-100 LOC
   floor before this plan is READY? *(a) is cheaper and matches the engineer's own Q1.*
2. Is `worktrees` confirmed as an 8th frozen guard object, or is there a reason `worktree_lifecycle.sh`'s
   dependency on its exact shape does not matter?
3. Move `render.py` to Wave 2 and fold `models_graph.py` into the `plan.py`/`graph.py` Wave-2 steps?
4. Accept Q1-bis Option 1 — amend the seed with `expected_loc_delta` / `subtract_floor` before Wave 0
   starts? **This needs sign-off before W0-GATE regardless of the verdict.** Root's note: a seed amendment
   is planter/root territory and the SUBTRACT pre-authorization is an operator call — it travels to the
   operator at the plan gate alongside the Q1 stop-boundary.

## Pattern echoes

No `shctx adapt priors` data available — the registry adaptation-priors table is empty, per the plan's own
"Proof of dispatch" note. No `prior:<id>` citations to check.

## Durable record

The critic wrote its findings to the registry: `audit_findings` rows 1-10 and `deliverables` row 1, with
the live SQL used for each falsification stored in each row's `falsification` column.
