## CODER REPORT

- Lane: W8-L7 (contradiction-ledger Finding #11 — `ctx-cmd-path-vs-invocation`)
- Skills loaded: code-style (markdown/command-doc conventions; no language-specific code body in scope)
- Files touched (created/modified/deleted): `/Users/jo3/src/fl03/shepherd/commands/ctx.md` (modified)
- LOC delta: +0 / -1
- Acceptance grep results:
  - `rg -n "bin/shepherd" commands/ctx.md` → 0 hits (PASS — dead resolution fully removed, matches ledger's expected count of 0 post-fix)
  - Manual read-verification that Step 1 (former lines 19-26, now 18-25) never consumes the resolved CLI path before deleting Step 0 item 3 → confirmed: Step 1 only ever invokes `shctx` subcommands (`shctx init`, `shctx doctor`, `shctx refresh --all`, etc.); no variable or reference to the Step-0-resolved path exists anywhere else in the file → PASS
  - Step 0 now reads as a clean 2-item list (skill load, config read) with no orphaned numbering or dangling reference → PASS
- Halts encountered: none
- Summary: Removed the dead `Resolve the CLI path: ${CLAUDE_PLUGIN_ROOT}/bin/shepherd` line (former Step 0 item 3) from `commands/ctx.md`. Confirmed via full-file read and grep that this was the sole mention of `bin/shepherd` in the file and that Step 1 exclusively dispatches to `shctx`, never the resolved path — the resolution was genuinely unreachable code, not a wiring bug. This is a pure markdown-doc deletion (no code/build surface); no compile-time confirmation is needed from the central verifier for this file, though the verifier should confirm no other file in the wave re-adds a reference to the now-removed Step-0 resolution.
- Reporter: coder-W8-L7 @ 2026-08-13T17:20:00Z
