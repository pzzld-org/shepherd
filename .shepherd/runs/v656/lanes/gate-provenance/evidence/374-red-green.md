# Gate provenance RED/GREEN evidence

Base: 6837e109ab618e3d22cb34c637de8ed7b7da7c69.

## RED against the unchanged hook

Command: bash hooks/tests/test_bash_post_ledger.sh

The old substring matcher returned exit 7. It created ledger rows for comment,
echo, printf, quoted text, alias, wrapper, and the failing gate. Concatenation
and missing command did not match. The ordinary post-hook telemetry control
passed.

## GREEN after deleting command-text gate authority

Command: bash hooks/tests/test_bash_post_ledger.sh

Result: 9/9 adversarial cases passed, 0 failed. Comment, echo, printf, quoted
text, concatenation, alias, wrapper, missing command, and failing gate produced
no gates-ran-* file. Ordinary bash_post telemetry remained present and
non-authoritative.

## Negative control

A scratch copy restored substring matching. Command:
HOOK_OVERRIDE=/tmp/shep-gate-provenance-negative.XXXXXX/bash_post.sh bash hooks/tests/test_bash_post_ledger.sh

The scratch matcher returned the expected non-zero result, rc=7. It produced
seven false ledger rows, while concatenation and missing command remained
unmatched:
  FAIL comment, echo, printf, quoted text, alias, wrapper, failing gate
  PASS concatenation, missing command, ordinary post-hook telemetry

## Scoped validation

- bash hooks/tests/test_bash_post_ledger.sh: passed, 9 executed cases.
- bash services/eval/tests/test_eval_pairs.sh: passed, 8 existing periodic pairs discovered.
- New gate-provenance eval files: deterministic content validation passed, 2 files checked.
- bash hooks/tests/run.sh: failed outside this lane in pre-existing test_harness_parity_generator.sh (6 assertions) and test_shepherd_native_resolver.sh (2 assertions); test_bash_post_ledger.sh passed within the 31-test run.
- git diff --check is recorded below after this evidence file was written.

## Authority boundary

The Bash post hook no longer reads command text or tool response status for gate
claims. Invocation and result states must come from explicit wave-owned
execution artifacts. No shell parser or outer-status inference was added.

## Worktree status at evidence capture

Command: git diff --check
Result: passed

Command: git status --short
 M docs/integration.md
 M hooks/scripts/bash_post.sh
 M hooks/tests/test_bash_post_ledger.sh
?? .shepherd/runs/v656/lanes/gate-provenance/
?? services/eval/evals/cases/v656/

Staged paths (must be empty):

## Auditor redo: 2026-08-22

The read-only auditor found two test gaps and one documentation ambiguity:

- The suite only inspected `gates-ran-*`, so a renamed command-text ledger such as
  `observed-gates-*` passed.
- No case supplied `tool_response.exit_code: 0`, so an outer-status success mutant
  passed.
- The `Unverified` table row overlapped the `Invoked` row by describing both a
  missing invocation and a missing result.

### Mutation RED before hardening

Both scratch mutants passed the then-current test, proving the gaps:

```text
HOOK_OVERRIDE=<renamed-ledger-mutant>/hooks/scripts/bash_post.sh \
  bash hooks/tests/test_bash_post_ledger.sh
RENAMED_MUTANT_RC=0

HOOK_OVERRIDE=<outer-status-mutant>/hooks/scripts/bash_post.sh \
  bash hooks/tests/test_bash_post_ledger.sh
OUTER_STATUS_MUTANT_RC=0
```

The renamed mutant wrote `observed-gates-${session}.jsonl` from command text. The
outer-status mutant wrote `gates-ran-${session}.jsonl` when
`tool_response.exit_code` was zero.

### REDO GREEN

`hooks/tests/test_bash_post_ledger.sh` now scans the complete active-run events
directory, permits only `hooks-*.jsonl`, and verifies every telemetry row is the
empty-fields `bash_post` pass event with no command, gate, status, provenance,
invocation, result, or tool payload keys. It adds an explicit outer-success case
with `tool_response.exit_code: 0`.

```text
bash hooks/tests/test_bash_post_ledger.sh
  10/10 adversarial cases passed, 0 failed

bash -n hooks/scripts/bash_post.sh hooks/tests/test_bash_post_ledger.sh hooks/tests/run.sh
  exit 0
```

The original comment, echo, printf, quoted-text, concatenation, alias, wrapper,
missing-command, and failing-gate cases remain present. The added outer-success
case is also rejected.

### Mutation GREEN after hardening

The same scratch mutants now fail for the intended reason:

```text
HOOK_OVERRIDE=<renamed-ledger-mutant>/hooks/scripts/bash_post.sh \
  bash hooks/tests/test_bash_post_ledger.sh
RENAMED_MUTANT_REDO_RC=10
FAIL ... unexpected non-telemetry artifact=.../observed-gates-s1.jsonl

HOOK_OVERRIDE=<outer-status-mutant>/hooks/scripts/bash_post.sh \
  bash hooks/tests/test_bash_post_ledger.sh
OUTER_STATUS_MUTANT_REDO_RC=1
FAIL ... outer success status ... unexpected non-telemetry artifact=.../gates-ran-s10.jsonl
```

### Scoped validation

- `bash hooks/tests/test_bash_post_ledger.sh`: passed, 10 cases executed.
- `bash hooks/tests/run.sh`: failed with the same two unrelated test identities
  already present at the base comparison: `test_harness_parity_generator.sh`
  (6 assertions) and `test_shepherd_native_resolver.sh` (2 assertions). The
  gate-provenance test passed inside the 31-test run. A whole-run byte-for-byte
  comparison is not meaningful because failure output embeds temporary paths and
  timestamps; the exact-base comparison reproduced those same parity and native
  resolver failures, and no gate-provenance failure.
- `bash services/eval/tests/test_eval_pairs.sh`: passed, 8 periodic pairs complete.
- Deterministic v656 gate-provenance eval content validation: passed, 2 files checked.
- `bash -n hooks/scripts/bash_post.sh hooks/tests/test_bash_post_ledger.sh hooks/tests/run.sh`: passed.
- `git diff --check`: passed.
- `git diff --cached --name-only`: empty.

The documentation table now states mutually exclusive evidence predicates:
`Unverified` has no explicit wave-owned invocation record, while `Invoked` has
an invocation record and no result record. Failed and passed require their
explicit non-zero and zero result records respectively.
