# Shell — project code style

This file is project-local at `.artifacts/styles/shell.md`. The conductor injects its content into every coder brief whose `[FILE-SCOPE]` includes shell scripts (`.sh`, `.bash`). Edit freely; lives next to the project, not the user.

## Error handling
- Every script begins with `set -eu -o pipefail` immediately after the shebang. No exceptions.
- `IFS=$'\n\t'` when iterating over filenames or multi-line output to avoid word-splitting surprises.
- Trap on `EXIT` for cleanup; trap on `ERR` for diagnostics when the script is long. Cleanup is idempotent.
- Check return codes explicitly when a non-zero exit is meaningful (`if ! cmd; then ...; fi`). Don't rely on `set -e` for control flow inside conditionals.
- Use `${var:?error message}` for required variables — fails fast with a clear cause.

## Ownership & state
- Default values via `${var:-default}` or `${var:=default}`. Never silent empty-string fallthrough.
- All variables intended to be local are declared `local` inside functions. Globals are uppercase, locals lowercase.
- `readonly` for constants. No reassignment of shell builtins or `PATH` without preserving the prior value.
- Temporary files via `mktemp` (files) or `mktemp -d` (directories). Cleanup is registered via `trap` immediately after creation.
- No `cd` without an exit guard — scripts that change directory either run the work in a `(subshell)` or `cd` back on exit.

## Layout
- Bash-only scripts use `#!/usr/bin/env bash`. POSIX-only scripts use `#!/bin/sh` and avoid bashisms.
- Scripts > 100 lines are restructured into functions with a `main "$@"` dispatch at the bottom.
- Long scripts get a `usage()` function called for `-h`/`--help` and on argument errors.
- Library shell code (sourced) lives in `_lib.sh` siblings; entry-point scripts source the library.

## Quoting & expansion
- Quote every variable expansion: `"$var"`, `"$@"`, `"${arr[@]}"`. Unquoted expansion is a bug unless explicitly justified.
- `[[ ... ]]` over `[ ... ]` for tests. `[[ ]]` is safer for empty variables and supports pattern matching.
- `(( ... ))` for arithmetic. No `expr`, no `let` outside `(( ))`.
- Command substitution uses `$(cmd)`, never backticks.
- Use arrays (`arr=(...)`) for lists. Never store space-separated lists in a single variable.

## Tooling
- `shellcheck` MUST pass with no warnings. New `# shellcheck disable=SCnnnn` requires an inline `# reason: ...` comment.
- `shfmt -i 2 -ci -bn` formats. Indent is 2 spaces; case branches are indented; binary operators at line start when wrapping.
- Tests use `bats-core` or a project-defined `_assert.sh` harness. Every script with non-trivial branching has at least smoke-level tests.

## Documentation
- Top-of-file comment block: one-line purpose, usage, required env vars, exit codes.
- Functions > 5 lines have a comment block: purpose, args (`$1`, `$2`, ...), return convention.
- Non-obvious one-liners get a comment explaining the *why* — the *what* is in the syntax.

## Common patterns to AVOID (operator-flagged)
- Missing `set -eu -o pipefail` — silent failures cascade.
- Unquoted variable expansion — word-splitting and glob bugs.
- Parsing `ls` output — use globs (`for f in *.txt`) or `find -print0 | xargs -0`.
- `cat file | cmd` (UUOC) — use `cmd < file` or `cmd file`.
- Building paths with string concatenation when a glob or `find` would be clearer.
- `eval` on user input — code injection. Use arrays for command construction.
- `rm -rf "$var/"` without `${var:?}` — empty `$var` deletes from `/`.
- `which` for command lookup — use `command -v` (POSIX, more reliable).
