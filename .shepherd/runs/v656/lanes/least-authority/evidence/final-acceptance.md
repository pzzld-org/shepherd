# Least-authority final acceptance

## Root REDO disposition

The initial independent review demonstrated that complete root facts plus
`write_scope: ["*.md"]` still allowed opaque Bash such as `echo hi > outside`.
That contradicted `content/roles/shepherd.md`: root never writes anything but
root-level Markdown. The shared Rust guard now treats complete root facts as
identity validation, not opaque shell authority. Recognized git custody remains
a separate explicit path.

## Verification

Monitor #70 completed with exit code 0 after the REDO:

- `cargo fmt --all -- --check`
- `cargo test --locked -p shepherd-core --features full --test guard`
- `cargo test --locked -p shepherd-cli --test claude_hook_cli`
- `bash services/eval/tests/run.sh`: `6/6 passed`
- `python3 scripts/generate-compiler-package-content.py --check`: `24 byte-exact sources`
- `git diff --check`

The focused suites cover universal `write_scope: ["**"]`, explicit empty
non-writable scope, exact single-path `report-write`, incomplete root facts,
complete-root opaque Bash denial, root-level Markdown allowance, nested and
non-Markdown denial, and recognized git custody.

## Independent verdict

Fresh bounded read-only reviewer run
`0c6c43ca-05e9-4968-ad27-aa99e80b609b` returned `PASS` with no BLOCKER/HIGH.
Its only LOW cited a stale evidence line claiming formatting failed; Monitor
#70's later `cargo fmt --all -- --check` result supersedes that line.

## Acceptance

Accepted for root commit and integration. No threshold was changed. Final
cross-harness and exact-pushed-commit acceptance remains release-level work.
