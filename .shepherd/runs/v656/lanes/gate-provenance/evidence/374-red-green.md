# Gate provenance RED/GREEN evidence

Base: 6837e109ab618e3d22cb34c637de8ed7b7da7c69.

## RED against the unchanged hook

Command: bash hooks/tests/test_bash_post_ledger.sh

The old substring matcher returned exit 7. It created ledger rows for comment,
echo, printf, quoted text, alias, wrapper, and the failing gate. Concatenation
and missing command did not match. The ordinary post-hook telemetry control
passed.

## Superseded GREEN after deleting command-text gate authority

Command: bash hooks/tests/test_bash_post_ledger.sh

**Superseded result:** 9/9 adversarial cases passed, 0 failed. This obsolete
pre-redo count omitted the later outer-success case. The auditor redo below is
the current authoritative result: 10/10. Comment, echo, printf, quoted text,
concatenation, alias, wrapper, missing command, and failing gate produced no
gates-ran-* file. Ordinary bash_post telemetry remained present and
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

- **Superseded:** the initial `bash hooks/tests/test_bash_post_ledger.sh` result reported 9 executed cases; the current authoritative redo is 10/10 below.
- **Superseded:** the pre-registration `bash services/eval/tests/test_eval_pairs.sh` result found 8 existing periodic pairs; current revalidation finds 9.
- New gate-provenance eval files: deterministic content validation passed, 2 files checked.
- bash hooks/tests/run.sh: failed outside this lane in pre-existing test_harness_parity_generator.sh (6 assertions) and test_shepherd_native_resolver.sh (2 assertions); test_bash_post_ledger.sh passed within the 31-test run.
- git diff --check is recorded below after this evidence file was written.

## Authority boundary

The Bash post hook no longer reads command text or tool response status for gate
claims. Invocation and result states must come from explicit wave-owned
execution artifacts. No shell parser or outer-status inference was added. The
current tree does not contain a wave-owned gate artifact writer or reader; the
absence and its scope blocker are recorded below rather than replaced with a
prose claim.

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
- **Superseded:** the auditor redo's `bash services/eval/tests/test_eval_pairs.sh` result found 8 periodic pairs; current revalidation finds 9.
- Deterministic v656 gate-provenance eval content validation: passed, 2 files checked.
- `bash -n hooks/scripts/bash_post.sh hooks/tests/test_bash_post_ledger.sh hooks/tests/run.sh`: passed.
- `git diff --check`: passed.
- `git diff --cached --name-only`: empty.

The documentation table now states mutually exclusive evidence predicates:
`Unverified` has no explicit wave-owned invocation record, while `Invoked` has
an invocation record and no result record. Failed and passed require their
explicit non-zero and zero result records respectively.

## Superseded HIGH/BLOCKER: truthful artifact was absent

The investigation found no existing wave-owned gate invocation/result artifact
mechanism to connect. `scripts/gate.sh:31-40` executes each step and aggregates
its process status, but emits no per-gate invocation record, result record,
`attempt_id`, or latest-attempt resolver. The existing
`.shepherd/runs/<run>/events/hooks-YYYY-MM-DD.jsonl` sink is ordinary hook
telemetry. The registry `artifacts` table and dispatch `result_artifact` fields
cover durable files and child reports, not gate attempts. No native writer or
reader exists in the current tree.

This is not fixed by `bash_post.sh`, and adding a shell parser or interpreting
outer Bash status would restore the rejected authority. The declared
`gate-provenance` scope in `plan.md:295-302` is limited to the hook, hook tests,
this document, and the two case files; it does not include `scripts/gate.sh`,
the native core/CLI artifact contract, or a new artifact service. Root must create a
separate native task for that contract, wire the gate runner to it, and test
attempt correlation plus latest-result retry semantics. Until then, only the
absence of truthful gate proof is established; a passed gate state must remain
unverified.

## Repair revalidation: 2026-08-22T17:28:41Z

The requested eval registration was completed through the existing stateless
Claude-judge runner and rubric contract. The shared eval runner, new rubric, and
deterministic pair test are outside the original gate-provenance path list and
are called out here rather than hidden. Root Task #7 subsequently added the
separate wave-owned artifact writer/reader and its gate-wired regression test.

- `bash hooks/tests/test_bash_post_ledger.sh`: passed, 10/10 adversarial cases.
- Nested unexpected-artifact mutation: rejected with rc=10; the first failure named `.shepherd/runs/v100-dev0/events/nested`.
- `bash services/eval/tests/test_gate_provenance_eval_pair.sh`: passed, 16/16 deterministic checks.
- `bash services/eval/tests/test_eval_pairs.sh`: passed, 9 periodic pairs discovered.
- `bash services/eval/tests/test_eval_rubrics.sh`: passed, 11 rubrics valid.
- `bash services/eval/tests/run.sh`: passed, 6/6 deterministic eval tests.
- `bash -n hooks/scripts/bash_post.sh hooks/tests/test_bash_post_ledger.sh hooks/tests/run.sh services/eval/evals/run_eval.sh services/eval/tests/test_gate_provenance_eval_pair.sh`: passed.
- `jq empty services/eval/rubrics/gate-provenance.rubric.json`: passed.
- `bash hooks/tests/run.sh`: failed, 31/31 test files ran; `test_harness_parity_generator.sh` failed 6 assertions. `test_bash_post_ledger.sh` passed 10/10; no gate-provenance failure occurred.
- `git diff --check`: passed.
- `git diff --cached --name-only`: empty; no paths were staged.

Residual status: the native truthful-provenance HIGH/BLOCKER above remains open
and is returned to root. The eval pair is wired, but it evaluates the contract;
it cannot manufacture the missing wave-owned invocation/result artifact.


## Root Task #7 resolution: truthful gate artifact implemented

Root resolved the returned blocker without changing the Bash hook or inferring
execution from command text. `scripts/gate-artifact.py` derives a run/wave/lane/
gate-owned JSONL path, appends a unique invocation before starting the exact
argv, appends the correlated result after completion, and preserves the process
exit code. `status` resolves the last invocation by append order, so an
incomplete retry remains `Invoked` even after an older pass. Unknown,
contradictory, duplicate, malformed, oversized, and symlinked evidence fails
closed.

Deterministic verification:

- `python3 scripts/tests/test-gate-artifact.py`: 7/7 passed.
- `python3 scripts/check-gate-wiring.py`: 62 reachable test files, 0 unreferenced scripts.
- `bash services/eval/tests/run.sh`: 6/6 passed; gate-provenance pair 18/18.
- `bash hooks/tests/test_bash_post_ledger.sh`: 10/10 passed.
- `bash -n ...`, `jq empty ...`, and `git diff --check`: passed.
- Gate `hooks`: artifact attempt `f5fcb5e1b1bceaa4f2b2568f0aac4e7e`, explicit result `Passed`, exit 0.
- Gate `artifact-contract`: attempt `1f65ec2e393c82480497023846331281`, explicit result `Passed`, exit 0.
- Gate `eval-contracts`: attempt `7a6c5e7a58012f5972eef4a43b06f0e4`, explicit result `Passed`, exit 0.

The prior truthful-provenance HIGH/BLOCKER is closed by executable evidence,
not by the documentation claim. The three operational JSONL artifacts remain
run evidence rather than tracked source.

## Root REDO 2: independent falsifiability review

Independent clean-process review #66 returned `REDO` with five HIGH findings:

1. arbitrary successful commands could certify a declared gate;
2. a concurrent retry could be appended while status returned an older pass;
3. status could follow a symlinked artifact ancestor;
4. short or non-newline-terminated JSONL could be accepted;
5. `services/eval/tests` was outside repository gate reachability.

Root accepted all five. `scripts/gate-artifact.py` now requires status callers to
supply the exact expected argv after `--`, uses the script location as repository
root, traverses every artifact ancestor with descriptor-relative `O_NOFOLLOW`,
locks the artifact for reads and appends, loops until the full payload is written,
requires newline framing, and rejects exit codes outside 0..255. This adds no
command registry, shell parser, or duplicate gate policy map.

`scripts/gate.sh fast` now executes `services/eval/tests/run.sh`.
`scripts/check-gate-wiring.py` discovers the existing globbed service eval runner
without enumerating tests. The gate-provenance eval test executes the artifact
behavioral suite and asserts command binding, concurrency, framing, and wiring.
Docs, good/bad cases, and the rubric describe the same contract.

### REDO 2 focused evidence

- gate artifact behavioral suite: `11/11` passed;
- gate-provenance deterministic pair: `25/25` passed;
- periodic eval contract suite: `6/6` passed;
- gate wiring: `67` test files reachable, `0` unreferenced scripts;
- gate wiring negative controls: `6/6` passed;
- Python syntax and `git diff --check`: passed.

### Canonical command-bound gate

Monitor #72 ran the canonical command through the repaired writer:

```text
scripts/gate.sh fast
```

The process exited 0 and reported `gate (fast): green in 22s`. An independent
status read supplied the same expected argv and resolved:

```json
{"attempt_id":"c9f2111530aa1e65a20cb4876801da04","command":["scripts/gate.sh","fast"],"exit_code":0,"schema":"shepherd.gate-attempt/1","state":"passed"}
```

Artifact:
`.shepherd/runs/v656/lanes/gate-provenance/evidence/gates/w1-redo2-fast.jsonl`.

### Fresh independent REDO verdict

Fresh bounded read-only reviewer workflow
`3864809a-c1e7-4066-a990-474e52c3b9ae` returned `PASS` with no BLOCKER/HIGH
and no edits. It independently falsified exact argv binding, latest-attempt
selection, symlink traversal, framing, complete writes, exit preservation,
retry semantics, test reachability, hook authority, and docs/eval parity.
Monitor #72 and prior reports were not supplied as review evidence.
