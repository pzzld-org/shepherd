# Historical pre-rebase reproduction

This file preserves the original `6837e109...` reproduction only. It is not
final-state evidence. Current base, implementation, projection, and gate results
are recorded in `status-and-diff.md`, `implementation-verification.md`, and
`issue-369-authored-spawn.md`.

HEAD: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
CONTEXT: current initialized project; requested run and seed are absent

$ test ! -e .shepherd/runs/v0.1.0-dev.0 && echo absent
absent

$ target/debug/shepherd run show v0.1.0-dev.0
exit=2
stdout:
stderr:
ERROR: unsafe run id `v0.1.0-dev.0`

$ target/debug/shepherd seed verify .shepherd/runs/v0.1.0-dev.0/seed.md
exit=2
stdout:
stderr:
ERR: no such file: .shepherd/runs/v0.1.0-dev.0/seed.md
