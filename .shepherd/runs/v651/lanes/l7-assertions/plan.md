# Lane l7-assertions — v651 wave 3 (self-healed from plan.md:1017-1060)

- worktree: `.worktrees/v651-l7-assertions` · branch `v651-l7-assertions` · base `5b6f226`
- step: `L7-S1` · deliverables: D9 (#318 Family A), #340 (Family B)
- file scope: `hooks/**`, `scripts/**` wholesale (lane runs alone)
- escalate to: root (`main`)

## Measured ground truth (classifier: evidence/classify.py)

| set | count | note |
|---|---|---|
| `rg -Fq` total occurrences | 118 | plan.md's number; includes guarded sites |
| `rg -Fq` unguarded, plan filter | 52 | plan acceptance filter; MISSES one site |
| bare `rg` all flags (classifier) | 70 | 53 `-Fq` + 15 `-q` + 2 `-Fxq` |
| bare `[[ ]]` / `(( ))` (classifier) | 10 | NOT 13 |
| excluded: function-return position | 3 | `hooks/scripts/_lib.sh:120,369,450` |

Convertible total: **80**.

## Corrections to the dispatch brief (all confirmed by root)

1. `hooks/scripts/_lib.sh:120,369,450` are predicate function RETURN VALUES, not
   assertions. `is_shepherd_project`, `quiet_warnings`, `in_subworktree` each end in a
   `[[ ]]` whose exit status IS the boolean result. Converting them would hard-exit on the
   negative branch — `quiet_warnings` documents its default as false, so every hook would
   die whenever the operator had not set it. l12 made this file ship, so it would have
   landed in the delivered plugin. Root withdrew both claims; #340 corrected to 10.
2. Bare `rg -q` and `rg -Fxq` are the same defect as `rg -Fq`. The plan's acceptance filter
   greps the literal `rg -Fq` only and therefore cannot see them. Approved into this lane.
3. Plan filter undercounts `rg -Fq` by one: it drops
   `test-release-installer-powershell-contract.sh:21` because the *search pattern* contains
   the literal `if `. Same whole-line-scan bug that produced the wrong 17 and the flawed
   l11 self-lint. True bare `rg -Fq` count is 53, not 52.
4. G7's shared helper under `hooks/tests/lib/` is NOT built. Deviation approved by root:
   a `[[ ]]` condition cannot reach a helper without `eval`. Inline is one line per site,
   so C4/G7's intent (convert, do not expand) holds. Two L7-S1 acceptance lines
   (`ls hooks/tests/lib/`, `! grep -q '== lib'`) are therefore VACATED BY DEVIATION — not
   satisfied by creating an empty directory.

## Fix shape

```bash
rg -Fq 'pat' "$f" || { rc=$?; printf 'FAIL: <requirement> (rg rc=%s)\n' "$rc" >&2; exit 1; }
[[ cond ]]        || { printf 'FAIL: <requirement>\n' >&2; exit 1; }
```
Existing command text copied verbatim; only the guard is appended. rc=1 = absent,
rc=2 = could not read (G5).

## Waves

- **A** (dispatched): `l7-gitflow` test-gitflow-workflow.sh (36) · `l7-release`
  powershell-contract.sh (23) + installers (1) + assets (2) + distribution-license (4) ·
  `l7-codex` codex-marketplace.sh (9) + cli_authority_gate.sh (5)
- **B**: `hooks/tests/lint_shell_assertions.sh` — bans bare line-initial `[[ ]]`, `(( ))`,
  `rg -q|-Fq|-Fxq` in `hooks/**` + `scripts/**`, carrying the function-return exclusion.
  Two-sided falsification: unmutated fixture CLEAN, then injected bare assertion non-zero.

## Pre-existing reds at base (NOT caused by this lane)

- `test-release-distribution-license.sh` rc=1 — needs `npm ci --ignore-scripts`.
- `test_cli_authority_gate.sh` rc=1 — `$transport` resolves under `bin/`, deleted by l13's
  revert; `rg` exits 2. Script is UNGATED (absent from gate.sh, workflows, hooks/tests).
