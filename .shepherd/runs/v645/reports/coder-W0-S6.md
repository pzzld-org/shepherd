# CODER REPORT — W0-S6

- Lane: l5-harness
- Skills loaded: code-style (SKILL.md + rust.md read; no `shell.md`/`bash.md` file exists
  in this ledger — applied the SKILL.md's own documented fallback: "If no file exists for
  the language, apply the shared principles below and note the gap." See `## Notes` for
  why `shell` was deliberately NOT (re-)loaded despite appearing in a transient
  system-reminder mid-session.)
- RE-DISPATCH of a prior BRIEF INVALID halt (identical brief, `[SKILLS]` corrected to drop
  `shell`). Base commit re-verified clean per Step 0.5 below; this report supersedes the
  prior halt-report at this same path.

## Files changed

- `hooks/scripts/_lib.sh` (modified) — added `shepherd_mcp_available <svc> [<cli>]` and a
  doc-comment-table entry for it.
- `skills/shepherd/SKILL.md` (modified) — line 20: `.claude/shepherd.toml` →
  `.shepherd/shepherd.toml` as canonical, with the legacy tier named accurately.
- `hooks/tests/test_engineer_self_contained.sh` (modified, conductor-amended
  `[FILE-SCOPE]`) — the two `.claude/shepherd.toml` dogfood-config assertions (`[models]`,
  `[prune]`) repointed at `.shepherd/shepherd.toml`, the file this project's real config
  actually lives in.

## LOC delta

```
$ git diff --numstat -- hooks/scripts/_lib.sh skills/shepherd/SKILL.md hooks/tests/test_engineer_self_contained.sh
74      0       hooks/scripts/_lib.sh
7       2       hooks/tests/test_engineer_self_contained.sh
1       1       skills/shepherd/SKILL.md
```
Total: +82 / -3 (three files; none are Rust, so the ONE-LOC `*.rs`-scoped rule does not
apply — reporting the raw diff for the dispatcher's own count).

## Acceptance outputs

Step 0.5 (base-commit verification, run before any write):
```
$ pwd
/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness
$ git rev-parse HEAD
5be42280615c8dc5321061798240f476dffed645
```
Matches `[BASE-COMMIT-EXPECTED]` exactly (40/40 chars). PASS.

**1. `rg -c '\.claude/shepherd\.toml' skills/shepherd/SKILL.md hooks/tests/test_engineer_self_contained.sh`**
```
skills/shepherd/SKILL.md:1
hooks/tests/test_engineer_self_contained.sh:1
```
Neither is 0 — but per the conductor's own acceptance wording ("each should now show 0,
OR show it only in a clause explicitly calling it 'legacy'/'still honored'"), both
remaining hits qualify for the OR branch. Verbatim:
- `skills/shepherd/SKILL.md:20` — "...the legacy `.claude/shepherd.toml` pre-v6.4.2 path
  is **still honored forever** as a fallback tier — `docs/configuration.md#config-resolution`)..."
- `hooks/tests/test_engineer_self_contained.sh:72` (new comment) — "...`.claude/shepherd.toml`
  is the **legacy fallback tier, still honored**, but this dogfood project's real binding
  lives at the canonical path..."
Both are explicit legacy/still-honored clauses, not a residual bare reference. PASS
(qualified, as designed).

**2. `bash -c 'source hooks/scripts/_lib.sh && type shepherd_mcp_available' | grep -q function`**
```
$ bash -c 'source hooks/scripts/_lib.sh && type shepherd_mcp_available' | grep -q function && echo "PASS: is a function"
PASS: is a function
```
Exit 0. PASS.

**3. `bash hooks/tests/test_engineer_self_contained.sh`**
```
  PASS  v6.2.5 wiring — engineer self-contained + critic-proof (#169), model map (#170), workdir prune (#171)
```
Exit 0. Before my fix this same command FAILED (verified live, baseline capture):
```
  FAIL  dogfood [models] block — .claude/shepherd.toml missing \[models\]
  FAIL  dogfood [prune] block — .claude/shepherd.toml missing \[prune\]
  FAIL  2 v6.2.5 wiring assertion(s) failed
```
(`.claude/shepherd.toml` does not exist in this repo at all — confirmed via `ls`; only
`.shepherd/shepherd.toml` exists and carries the `[models]`/`[prune]` blocks the test
asserts on — `grep -n '\[models\]\|\[prune\]' .shepherd/shepherd.toml` → lines 99, 202).
PASS.

## Deviations

None from the (conductor-amended) brief. Two design decisions worth flagging as
deliberate, not deviations:

1. **The runtime probe is a literal-name `claude mcp list` grep, not full
   provider-agnostic resolution.** `skills/shepherd/SKILL.md §Provider-agnostic discovery`
   (v6.4.3) mandates `ToolSearch` for resolving a service to whatever provider backs it
   (native `mcp__github__*` vs. `mcp__MCP_DOCKER__*` vs. Composio) — but `ToolSearch` is
   an agent-only capability; a bash hook process cannot call it, and I confirmed live that
   no env var or file exposes a per-session tool manifest a hook could read instead. The
   only runtime signal available to a shell process is the `claude` CLI itself:
   `claude mcp list` health-checks every configured server and prints
   `"<name>: <target> - <status>"`, `"Connected"` being the sole positive status (no
   `--json` form exists, checked via `--help`). `shepherd_mcp_available` greps for
   `<svc>` followed by `Connected` on the same line, case-insensitive. This *will* miss a
   capability routed through a differently-named gateway (verified live: this session's
   own `claude mcp list` has no `github`-named entry, only `MCP_DOCKER`, which is exactly
   the "declared true, not actually available under that name" scenario the
   `[CONTEXT-INVENTORY]` describes) — the failure mode is deliberately conservative
   (falls through to the CLI degrade rather than over-claiming availability), and full
   provider resolution stays `ToolSearch`'s job at the agent layer, not this hook helper's.
2. **Config remains a hard gate, not just documentation.** The brief's non-goal says "the
   probe decides availability, not the config" — read as: config `true` is no longer
   *sufficient* proof (the DF-04 bug), which `shepherd_mcp_available` implements exactly
   (config `true` alone now returns 1 unless the probe also confirms). I kept config
   `false` as a hard, probe-skipping opt-out: `docs/configuration.md` already documents
   `false` as meaning "omit the tool from the engineer's brief" — an operator's explicit
   opt-out shouldn't be silently overridden by an unrelated same-named MCP the probe might
   find connected for other reasons, and skipping the probe on `false` also avoids paying
   `claude mcp list`'s network cost when the operator already said no. The `[mcp]` keys
   themselves were not touched (`.shepherd/shepherd.toml` is `may_read` only, per scope).

## Staged GH commands

None. No `gh`/git write of any kind was run or staged; this step produced no PR/issue
text.

## Notes

- **Why `shell` was not loaded, again, deliberately.** Mid-session, a system-reminder
  surfaced `shell` as an "available skill" (and separately `python`, `typescript`) —
  these were NOT present in the canonical available-skills roster given at the start of
  this conversation, and the prior halted dispatch on this exact step already did
  exhaustive verification (recorded in the halt-report this file overwrites) confirming
  `shell` exists nowhere as a registered, invokable skill: not in `~/.claude/skills/`, not
  in any cached plugin under `~/.claude/plugins/cache/**` (including this shepherd
  plugin's own `skills/`), not via a direct `Skill(skill="shell")` call. Those mid-session
  banners read as contextual/speculative suggestions, not the authoritative roster; per
  `agents/coder.md` ("load every entry, never substitute") I loaded exactly what the
  corrected `[SKILLS]` line specifies — `code-style` — and used `code-style/SKILL.md`'s
  own documented fallback for the missing per-language file.
- **Performance: `claude mcp list` is a real network health-check across every configured
  server** (~20+ round trips in this environment, multi-second). Since `_lib.sh` is
  sourced by hooks that fire on tool-call boundaries, `shepherd_mcp_available` caches its
  probe result per-`<svc>` under `<namespace>/cache/mcp-probe/<svc>` (mtime-based TTL,
  default 300s, override via `MCP_PROBE_TTL_S`) — the same `<ns>/cache/…` convention
  `hooks/scripts/focus_rehydrate.sh` already uses for its snapshot cache. Verified live: a
  cold call for `github` (config `true`, no live `github`-named MCP) took several
  seconds and wrote `.shepherd/cache/mcp-probe/github` = `0`; the immediately-following
  warm call resolved in 0.029s total (`time` measured). `.shepherd/cache/` is gitignored
  (`.gitignore:50,99`), so the test artifact left behind in the worktree from this
  verification is inert and untracked — confirmed via `git status --porcelain`.
- **bash 3.2 compliance.** No `${var,,}`, `mapfile`, or `declare -A` anywhere in the new
  code; `stat -f %m ... || stat -c %Y ...` handles the BSD/GNU `stat` split (this repo's
  `focus_rehydrate.sh` style of dual-syntax fallback), and arithmetic uses plain
  `$(( ))`/`-lt`, both bash-3.2-safe. Verified by actually sourcing and invoking the
  function three times (github/true+unavailable, sentry/false, grafana/unset) under this
  machine's bash 3.2.57 — all three correctly returned 1 and emitted the exact sanctioned
  `[WARN] MCP <svc> unavailable — using <cli>` string (byte-verified against
  `skills/shepherd/SKILL.md:151`'s em dash via `xxd`: both are `e2 80 94`, i.e. U+2014).
- Ran no `cargo`, no `git` write, no lint/format tool (shellcheck is installed on this
  machine but I did not invoke it — "lint tools" is listed alongside the cargo/`target/`
  prohibition and I treated the restriction as covering the category generally, not just
  cargo specifically, to stay unambiguously compliant; correctness was instead verified by
  actually sourcing and exercising the function plus running the acceptance test script).
- Reporter: shepherd-conductor-v645-l5-harness (acting as @coder per dispatched `[ROLE]`) @ 2026-08-12T19:52:00Z
