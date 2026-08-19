# L2 / D5 (#323) — W0-GATE reproduction, recorded before any fix

Measured in `.worktrees/v651-l2-dispatch-scope` at base `c7cc9c0`, against a binary built
from THIS tree (G3), not the ambient `PATH`:

```
$ cargo build --locked -p shepherd-cli --bin shepherd
$ export PATH="$PWD/target/debug:$PATH"
$ which shepherd
/Users/jo3/src/pzzld/shepherd/.worktrees/v651-l2-dispatch-scope/target/debug/shepherd
$ shepherd --version
shepherd-cli 6.5.1
```

(The ambient `~/.cargo/bin/shepherd` is 6.5.0 — Class A. Every verdict below is this tree's.)

## The defect, verbatim

```
$ for t in planter shepherd root engineer critic coder; do
    printf '{"tool_name":"Agent","role":"conductor","tool_input":{"subagent_type":"%s"}}' "$t" \
      | shepherd guard eval
  done

conductor -> planter
{"decision": "allow"}
conductor -> shepherd
{"decision": "allow"}
conductor -> root
{"decision": "deny", "predicate": "dispatch-scope", "rule": "closed-flock-only", "halt_code": "DISPATCH-OFF-FLOCK", "reason": "The dispatch target MUST be one of the nine content/roles/*.md role ids; any other value is refused on sight."}
conductor -> engineer
{"decision": "deny", "predicate": "dispatch-scope", "rule": "plan-authorship-and-gating-are-root-tier-exclusive", "halt_code": "WRONG-TIER-DISPATCH", "reason": "Only the root orchestrator (shepherd) may dispatch the plan-author (engineer) or gating (critic) roles for sprint-plan authorship/gating; a lane-executor lead (conductor) invoking either directly is refused."}
conductor -> critic
{"decision": "deny", "predicate": "dispatch-scope", "rule": "plan-authorship-and-gating-are-root-tier-exclusive", "halt_code": "WRONG-TIER-DISPATCH", "reason": "Only the root orchestrator (shepherd) may dispatch the plan-author (engineer) or gating (critic) roles for sprint-plan authorship/gating; a lane-executor lead (conductor) invoking either directly is refused."}
conductor -> coder
{"decision": "allow"}
```

**REPRODUCED.** A lane-executor lead may currently dispatch `planter` (which holds
`AskUserQuestion`, the operator channel) and `shepherd` (the root orchestrator). Both
return a bare `allow`.

The carrier-prefixed form behaves identically — `carrier_role` at
`crates/core/src/guard/engine.rs:534` strips `shepherd:`, so the hole is not a
prefix-parsing artifact:

```
  shepherd:planter     -> {"decision": "allow"}
  shepherd:shepherd    -> {"decision": "allow"}
  shepherd:critic      -> {"decision": "deny", … "WRONG-TIER-DISPATCH" …}
  shepherd:coder       -> {"decision": "allow"}
```

## Which rule denies which target (plan L2-S1 [CONTEXT-INVENTORY] asked this be recorded)

| Target | Decision | Rule that fired | Halt code |
|---|---|---|---|
| `planter` | allow | none | — |
| `shepherd` | allow | none | — |
| `root` | deny | `closed-flock-only` | `DISPATCH-OFF-FLOCK` |
| `engineer` | deny | `plan-authorship-and-gating-are-root-tier-exclusive` | `WRONG-TIER-DISPATCH` |
| `critic` | deny | `plan-authorship-and-gating-are-root-tier-exclusive` | `WRONG-TIER-DISPATCH` |
| `coder` | allow | none | — |

`root` is **not** a role id (`role_tier`, `crates/core/src/guard/engine.rs:538-547`, has no
`root` arm; `shepherd` is the id whose tier is `root`). `conductor -> root` is therefore
refused as off-flock by `deny_if_target_outside_flock` (`:657-660`), a different mechanism
from the one D5 is about. A test asserting only `decision == "deny"` for `root` pins the
wrong mechanism. Every test this lane adds asserts the `rule` and `halt_code`, not just the
decision.

## Correction C3 verified independently

`content/predicates/dispatch-scope.toml` names no role in any `subject` or `effect`. Its
`plan-authorship-and-gating-are-root-tier-exclusive` rule carries prose and
`effect = "deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role"`. The enforced
list is Rust, `crates/core/src/guard/engine.rs:661-666`:

```rust
"deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role" => {
    context.get("dispatcher_tier").and_then(GuardValue::as_str) == Some("lane-lead")
        && matches!(
            context.get("target_role").and_then(GuardValue::as_str),
            Some("engineer" | "critic")
        )
}
```

Editing only the TOML changes nothing an operator can observe. The seed's claim is false and
the verdicts above are the proof.

## The bypass-by-payload-shape path is already closed

```
$ printf '{"tool_name":"Workflow","role":"conductor","tool_input":{"script":"const r = await agent(\"engineer\")"}}' | shepherd guard eval
{"decision": "deny", "predicate": "dispatch-scope", "rule": "plan-authorship-and-gating-are-root-tier-exclusive", "halt_code": "WRONG-TIER-DISPATCH", "reason": "a lane-executor lead must DECLARE the roles it dispatches: pass `target_role` (or `subagent_type`) in `tool_input`. …"}
```

`restricted_by_target_rule` (`:530-532`) makes an undeclared target a denial for a lane
lead. Widening the `matches!` arm inherits that protection automatically — no second rule is
needed, and none is added.

## The `test_native_cli_contract.sh` failure, same file scope

```
$ printf '{"tool_name":"Workflow","role":"shepherd","tool_input":{"script":"const r = await agent(\"x\")"}}' | shepherd guard eval
{"decision": "allow"}
```

`hooks/tests/test_native_cli_contract.sh:82-88` asserts this is `unresolved`. It is `allow`.
The assertion is the v6.4.5 contract (`ee682ec`); the behaviour is the v6.4.6 contract
(`f3d44b0`, the `tool_name != "Workflow"` carve-out at `:401`, protected by seed decision
D1). The test is wrong, not the engine. Confirmed NOT a regression from this sprint: root
measured the same failure on clean `d666aeb`.

---

# Post-fix verification (conductor-run, not the implementer's self-report)

## The defect is closed

```
conductor -> planter   {"decision": "deny", "rule": "plan-authorship-and-gating-are-root-tier-exclusive", "halt_code": "WRONG-TIER-DISPATCH"}
conductor -> shepherd  {"decision": "deny", same rule, same halt code}
conductor -> root      {"decision": "deny", "rule": "closed-flock-only", "halt_code": "DISPATCH-OFF-FLOCK"}   (mechanism unchanged)
conductor -> coder     {"decision": "allow"}                                                                   (sanctioned dispatch intact)
```

## Falsification of the rewritten `test_native_cli_contract.sh` assertion

The plan's L2-S1 action 5 prescribes reverting `crates/core/src/guard/engine.rs:401` in a
scratch worktree. **A conductor cannot do that** — the guard denies the instrument:

```
$ git worktree add --detach <path>
[shepherd] Rebase/merge/cherry-pick onto the shared integration branch, and worktree
add/remove/prune, are denied to every role except the top-level orchestrator (shepherd).
```

That is `git-custody` / `cross-lane-integration-is-root-exclusive` working correctly, so the
prescribed method is unavailable to the role the plan assigns it to. Falsified without
mutating any tree instead, which is stronger because it exercises the shipping binary:

The carve-out is `if target.is_none() && tool_name != "Workflow"`. Reverting it sends the
payload down the `unresolved` branch. `Agent` is the other member of `DISPATCH_TOOL_NAMES`,
so the identical payload sent as `Agent` executes exactly the branch a revert would take:

```
  Workflow (carve-out at :401 applies)  -> {"decision": "allow"}
  Agent    (same branch, carve-out off) -> {"decision": "unresolved", "reason": "cannot determine the dispatch target role from `tool_input`", "missing": ["tool_input.subagent_type"]}
```

The rewritten assertion greps for `"decision": "allow"`. Without the carve-out the verdict is
`unresolved`, so the assertion fails. **Falsifiable, and it fails for the intended reason.**

## Suite counts (G4 — every count visible and non-zero)

```
$ cargo test -p shepherd-core --locked --features full
ok. 5 passed | ok. 4 passed | ok. 15 passed | ok. 68 passed
ok. 25 passed | ok. 7 passed | ok. 6 passed | ok. 0 passed      => 130 passed, 0 failed
```

`--features full` is load-bearing. Bare `cargo test -p shepherd-core` prints
`test result: ok. 0 passed` three times, because `guard`, `dispatch`, `portable_dispatch`
and `run_state` sit behind unmet `required-features` (`crates/core/Cargo.toml:21-39`). That
is the plan's Class A failure, live, in a single-crate invocation. `--all-features` is not an
option either: it enables `nightly = []` (`crates/core/Cargo.toml:111`) and fails `E0554` on
the pinned stable 1.97.0 toolchain.

```
$ bash hooks/tests/test_native_cli_contract.sh
PASS: test_native_cli_contract (16 assertions ran, 0 failed)     EXIT=0

$ bash hooks/tests/run.sh | tail -1
FAIL: hooks/tests/run.sh (29/29 tests ran, 1 failed)
```

**2 failures -> 1.** `test_native_cli_contract.sh` passes. The one remaining failure is
`test_workflow_meta_gate.sh`, whose `NEGATIVE control: could not recover
686084d:workflows/wave.js from git history` is `l6-gate-wiring`'s `L6-S1` by name. `W1-GATE`
is satisfied exactly: "at most 1 failure, `test_workflow_meta_gate.sh`, which L6 owns".

```
$ cargo fmt --check                                               -> clean
$ cargo clippy --workspace --all-targets --locked --features full -> no errors, no warnings
$ python3 scripts/generate-compiler-package-content.py --check
ok: compiler package content has 23 byte-exact sources            EXIT=0
```
