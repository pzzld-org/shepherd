# #368 Pi tool-call identifier bootstrap evidence

**Base:** a03c384
**Transport:** parent persistence fallback because the running Pi extension rejects compound tool-call IDs.

## Root cause

`packages/harness-pi/src/extension.mjs` forwarded opaque Pi/OpenAI `toolCallId` into the typed component's strict native identifier validation. The adapter now maps only that opaque correlation value to `pi-tool-<sha256>` with Node `crypto`. Session, project, run, lane, role, agent, and agent-type validation are unchanged.

## RED

`SHEPHERD_COMPONENT_WASM=/tmp/v656-368-target/wasm32-wasip2/release/shepherd_component.wasm node packages/harness-pi/test.mjs` exited 1. Four of five files passed; `extension-guard.test.mjs` failed because `call_*|fc_*` reached native validation as an unsafe session ID.

## GREEN

The same command exited 0: 5/5 test files passed. Adversarial coverage includes standard compound IDs, 1,024-byte IDs, control characters, missing/non-string IDs, distinct-token checks, wrong session, wrong tool response, malformed native response, and raw-ID exclusion.

Rust correlation gates:

- `cargo test -p shepherd-core --features full --test portable_dispatch`: 7 passed.
- `cargo test -p shepherd-component`: 1 unit, 13 integration, and 1 doc test passed.

The first Rust attempt failed before compilation because a stale `sccache` daemon retained context-mode's deleted temp directory. Re-running with `RUSTC_WRAPPER=` passed; no code change addressed that environment failure.

## Negative control

A scratch mutation returning one constant token made the Pi suite exit 1. The original source was restored in a `finally` block and the green suite was rerun. A deliberate SHA-256 collision fixture is not practical; distinct inputs plus wrong-response correlation are the falsifiable controls. Cross-agent identity is not present in Pi's tool-call event and is therefore not fabricated in this test.

## Eval

- Deterministic eval gates: 4/4 passed; 7 periodic pairs complete; 9 rubrics valid.
- Live `pi-tool-correlation` eval: good 96/100, bad 20/100, threshold 80, margin 76.

## Remaining gate

The running Pi session still uses the pre-fix extension and reproduced the same rejection on a live `Write` probe. Restart Pi from this checkout, then repeat the normal Write/Edit probe. #370 role registration remains untouched until that gate passes.
