# v6.4.5 secondary CLI retirement

## Verdict

The repository now contains one CLI implementation: the Rust `shepherd`
binary. The former Python Typer package and Bash `shctx` dispatcher, command
scripts, helpers, and tests are deleted. The conformance runner remains Python
only as a deterministic test utility and always launches the Rust binary.

The route inventory is retained as evidence in
`conformance/legacy-command-disposition.json`. It contains 106 former Python
leaf routes and 40 former Bash dispatcher groups. Each route is classified as
`native` or `retired`; no pending-parity category remains.

## Deleted surfaces

- `services/cli/**`: Python package metadata, Typer application, command and
  model modules, templates, tests, and Poetry lock/configuration files.
- `skills/context/scripts/**`: `shctx`, all `cmd_*.sh` dispatch targets,
  `_lib.sh`, the Python duplicate scanner, refresh helpers, and scaffold
  helper.
- The ignored local Python runtime and pytest cache were moved out of the
  checkout to `/tmp/shepherd-v645-retired-python-20260814` before the
  authority gate ran. No user-home files were changed.

## Authority contract

`scripts/check-cli-authority.py` now validates schema version 2, exact and
duplicate-free native/retired route disposition, absence of both retired
implementation roots, and an executable native-only `bin/shepherd` launcher.
Its self-test creates each resurrection attempt independently and proves that
both a Python console script and an executable `shctx` are rejected.

## Verification

- `python3 scripts/check-cli-authority.py --self-test` passed.
- `python3 scripts/check-cli-authority.py` passed: 106 Python routes, 40 Bash
  routes, 73 native Python-equivalent routes.
- `bash scripts/tests/test_cli_authority_gate.sh` passed.
- `python3 -m unittest discover -s conformance/tests -v` passed 3/3.
- `conformance/run.sh --impl=rust --verify-checksum` passed with checksum
  `3353e0fd4fffd5ab389755212428b1dad6a32b431f997fc6394aa75bc39ea43e`.
- `conformance/run.sh --impl=python --count` fails closed with exit 2 and
  `want rust`, proving the removed implementation cannot be selected.
- `conformance/run.sh --impl=rust --suite=guard-engine` passed 9/9.
- `git diff --check` and Python bytecode compilation for the retained harness
  and authority checker passed.

The full Rust replay currently passes 104/109. Five pre-existing `guard-cli`
golden-byte cases still differ from the current native guard output:
`deliverable-stalled/invalid-since-mins`, `deliverable-stalled/ok`,
`dups-check/clean`, `dups-check/usage-error`, and
`teammate-heartbeat/missing-command`. Those cases require the owning guard
slice to either align native output or intentionally refresh the native golden
bytes. They are not hidden by this retirement work.
