# Gate-provenance final acceptance

## Root REDO disposition

The initial independent review found five HIGH defects: labels were not bound
to commands, concurrent status could resolve an older pass, status followed
symlinked parents, incomplete JSONL could be accepted, and service eval tests
were not gate-reachable. The repaired protocol binds verifier-supplied exact
argv without a command registry or shell parser; owns artifacts beneath the
script-resolved repository root; uses descriptor-relative no-follow traversal,
locked reads/appends, complete writes, strict newline framing, and exit codes
`0..255`; resolves the latest matching attempt; and wires behavioral eval tests
into the fast gate.

## Verification

Monitor #72 completed with exit code 0 after the REDO:

- gate artifact behavioral suite: `11/11` passed;
- gate-provenance deterministic pair: `25/25` passed;
- periodic eval contract suite: `6/6` passed;
- gate wiring: `67` test files reachable and `0` unreferenced scripts;
- gate wiring mutation controls: `6/6` passed;
- canonical `scripts/gate.sh fast`: green in `22s`;
- command-bound artifact attempt `c9f2111530aa1e65a20cb4876801da04`
  resolved exact argv `["scripts/gate.sh","fast"]`, state `passed`, exit `0`;
- Python syntax and `git diff --check`: passed.

## Independent verdict

Fresh bounded read-only reviewer workflow
`3864809a-c1e7-4066-a990-474e52c3b9ae` returned `PASS` with no BLOCKER/HIGH
and no edits. It did not use Monitor #72 or prior reports as evidence.

## Acceptance

Accepted for root commit and integration. No threshold changed. Hook telemetry
remains non-authoritative. Final cross-harness and exact-pushed-commit
acceptance remains release-level work.
