# Shell — project code style

Project-local at `.shepherd/styles/shell.md` (or legacy `.artifacts/`); injected as `[CODE-STYLE]` into briefs scoping `.sh`/`.bash` files. Edit freely — lives next to the project.

## Error handling
- Every script begins `set -eu -o pipefail` immediately after the shebang. No exceptions.
- `IFS=$'\n\t'` when iterating filenames/multi-line output. Trap `EXIT` for idempotent cleanup, `ERR` for diagnostics on long scripts.
- Check return codes when non-zero exit is meaningful — never rely on `set -e` inside conditionals. `${var:?error message}` for required variables.

## Ownership & state
- Default values via `${var:-default}`/`${var:=default}` — never silent empty-string fallthrough.
- Locals declared `local` inside functions; globals uppercase, locals lowercase; `readonly` for constants.
- Temp files via `mktemp`/`mktemp -d`, cleanup via `trap` immediately after creation. No `cd` without an exit guard — subshell or `cd` back on exit.

## Layout
- Bash-only: `#!/usr/bin/env bash`. POSIX-only: `#!/bin/sh`, avoid bashisms.
- Scripts > 100 lines restructure into functions with `main "$@"` at the bottom; long scripts get a `usage()` for `-h`/`--help` and on argument errors.
- Library shell code (sourced) lives in `_lib.sh` siblings.

## Quoting & expansion
- Quote every variable expansion (`"$var"`, `"$@"`, `"${arr[@]}"`) — unquoted is a bug unless justified.
- `[[ ... ]]` over `[ ... ]`; `(( ... ))` for arithmetic, never `expr`/`let`. Command substitution `$(cmd)`, never backticks.
- Arrays (`arr=(...)`) for lists, never space-separated strings.

## Tooling
- `shellcheck` MUST pass with no warnings; new `# shellcheck disable=SCnnnn` needs inline `# reason: ...`. `shfmt -i 2 -ci -bn` formats. Tests use `bats-core` or `_assert.sh`; non-trivial branching gets smoke-level tests.

## Documentation
- Top-of-file comment: purpose, usage, required env vars, exit codes. Functions > 5 lines get a purpose/args/return comment; non-obvious one-liners get a *why* comment.

## Common patterns to AVOID (operator-flagged)
- Parsing `ls` output — use globs or `find -print0 | xargs -0`. `cat file | cmd` (UUOC) — use `cmd < file`.
- Building paths with string concatenation instead of a glob or `find`.
- `eval` on user input (injection) — use arrays for command construction.
- `rm -rf "$var/"` without `${var:?}` — empty `$var` deletes from `/`. `which` — use `command -v` (POSIX).
