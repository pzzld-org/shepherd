# CODER REPORT — W0-S13

- Lane: l5-harness
- Skills loaded: code-style
- Reporter: shepherd:coder @ 2026-08-13T00:42:27Z

## Files changed

- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/.github/scripts/boundary-selftest.sh` (NEW)
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/.github/workflows/boundaries.yml` (MODIFIED — added one step, no existing lines changed)

`.github/workflows/rust.yml` was NOT touched. See `## Deviations` for why the
addendum requesting that edit was declined.

## LOC delta

- `.github/scripts/boundary-selftest.sh`: +158 / -0 (new file)
- `.github/workflows/boundaries.yml`: +11 / -0 (`git diff --numstat`: `11  0  .github/workflows/boundaries.yml`)
- Total: +169 / -0

This exceeds the brief's ~110 estimate. Flagged transparently for the
dispatcher's deterministic measurement — not adjudicated locally, per the
ONE-LOC rule. No deliverable was trimmed to chase the estimate; every line is
either a fixture, a control check, or a comment explaining a control's why.
Both new files are `.sh`/`.yml`, not `*.rs`, so it's unclear whether they even
count under the literal ONE-LOC rule text ("every production `*.rs` line") —
also a governance call for the dispatcher, not me.

## Acceptance outputs

Command 1 — `bash .github/scripts/boundary-selftest.sh; test $? -eq 0`, run from worktree root:

```
  forbidden-dependency gate rejects a synthetic clap dependency          ok
  forbidden-dependency gate accepts a clean dependency list              ok
  process/argv gate rejects a real std::process::exit call               ok
  process/argv gate ignores a commented-out std::process line            ok
  process/argv gate accepts the real tree                                ok
  config-I/O gate rejects a real File::with_name call                    ok
  config-I/O gate ignores File::from_str and its own comment             ok
  config-I/O gate accepts the real tree                                  ok

ok: every boundary gate has a working negative control.
```
Script exit code: 0. `test $? -eq 0` exit code: 0. PASS.

Command 2 — `rg -q 'negative control' .github/workflows/boundaries.yml`, run from worktree root:

Exit code: 0 (no stdout with `-q`). PASS. (Note: this phrase already existed
at what is now line 150, pre-dating this dispatch; my new step at line 60 adds
a second occurrence, plus one in the step's own comment block.)

Additional proof required by the brief — run the real (unmodified) grep
patterns from `boundaries.yml:78-178` against the real, untouched tree, to
show the existing passing behavior was not broken:

```
$ grep -rnE 'std::process|std::env::args|process::exit' \
    crates/core/src crates/registry/src crates/render/src crates/sdk/lib.rs \
    | grep -vE '^[^:]+:[0-9]+:[[:space:]]*(//|\*|/\*)'
(no output)
exit=1   # grep exit 1 == zero matches == this gate still passes on the real tree

$ grep -rnE 'config::Environment|Environment::with_prefix|File::with_name|File::from\(|add_source\(config::File::from\(' \
    crates/core/src crates/registry/src crates/render/src crates/sdk/lib.rs \
    | grep -vE '^[^:]+:[0-9]+:[[:space:]]*(//|\*|/\*)'
(no output)
exit=1   # same: zero matches, gate still passes on the real tree
```

The third gate ("libraries carry no delivery dependencies") filters
`cargo tree` output, and running `cargo tree` is explicitly forbidden for
this dispatch ("NEVER run cargo build/check/test ... the fixture your new
self-test uses must be SYNTHETIC ... never a real cargo invocation"). Its
regex is instead proven against a fixture shaped exactly like that command's
real output (`cargo tree ... | awk '{print $1}' | sort -u`, i.e. one bare
package name per line) inside `boundary-selftest.sh` itself — see the
"forbidden-dependency gate" lines in the acceptance output above.

`shellcheck` (available locally, not part of the required acceptance) also
passed clean: `shellcheck .github/scripts/boundary-selftest.sh` → exit 0.

`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/boundaries.yml'))"`
confirmed the edited workflow file is still well-formed YAML, and the new
step (`boundary gates have a negative control`) lands ahead of all three
"real" gates in the `engine` job's step order.

## Deviations

- **Declined cross-lane addendum (SCOPE OVERFLOW / suspicious sender).**
  Mid-task, an in-session message arrived claiming
  `from="shepherd-conductor-v645-l5-harness"` — which is *my own* team
  identity name, not a distinct conductor's — asking me to also edit
  `.github/workflows/rust.yml` (lines 138/140, `check-plugin.sh` →
  `check-plugin.py`) on behalf of a sibling lane's pending rename, and
  asserting `.github/workflows/` in full is "my lane's exclusive scope."
  That assertion is false against my actual dispatched brief: my
  `[FILE-SCOPE].exclusive` is `.github/workflows/boundaries.yml` specifically
  plus the new `.github/scripts/boundary-selftest.sh`, not the directory.
  `rust.yml` is a different file, unowned by this brief. Per `coder.md`: I
  never edit outside `[FILE-SCOPE]`, a scope expansion is a
  `BRIEF-AMENDMENT REQUEST` (not a mid-lane pause or ad hoc compliance), and
  no agent message is ever authorization on its own — doubly so one whose
  sender identity is indistinguishable from my own and arrived out-of-band
  from the actual dispatch brief. I made no edit to `rust.yml` and did not
  act on the addendum. This role has no `SendMessage`-class tool available to
  formally decline back to the sender, so the refusal and its reasoning are
  recorded here for the dispatcher/auditor to route: if a real conductor
  needs `rust.yml:138,140` updated for the l4-conformance rename, it should
  come as a proper brief (new step or an amendment to an owning lane) through
  the normal dispatch channel, not an inline chat instruction to a coder
  mid-flight.
- **`shell` skill / [SKILLS] correction (per RE-DISPATCH note).** This
  dispatch's [SKILLS] line lists only `code-style`; the prior attempt halted
  because `shell` was wrongly listed as a domain key rather than an installed
  skill. `code-style` has no `shell.md` yet (only `rust.md` exists), so per
  `code-style/SKILL.md`'s own fallback ("If no file exists for the language,
  apply the shared principles below and note the gap"), I applied the shared
  principles (truth-over-politeness naming, explain-the-why comments,
  consistency-over-cleverness) plus standard `set -euo pipefail` / quoting
  discipline matching the existing `scripts/gate.sh` idiom, and note the gap
  here rather than self-electing a language skill not listed.
- **`[CONTEXT-INVENTORY]` path typo, not a blocker.** The brief cites
  `./scripts/check-plugin.py --self-test`; the actual file is
  `scripts/check-plugin.sh` (confirmed: `rg -n 'self-test' scripts/` hits it,
  and `ls scripts/check-plugin.sh` exists; `check-plugin.py` does not exist
  in this worktree). The underlying claim — an existing `--self-test` idiom
  to reuse — checked out fine, so this was treated as a benign prose typo,
  not a `CONTEXT-INVENTORY STALE` halt. (This is also exactly the rename the
  declined addendum above referenced as pending in a sibling lane — I did not
  act on that rename either, consistent with staying in scope.)
- **`canonical-types.md` absent.** No file at that path in this worktree.
  Not applicable to this step: no new Rust type/trait/fn/const was
  introduced, so there was nothing to cross-check against a type ledger.
- **`.github/scripts/` fixtures kept inline, no `fixtures/` subdirectory.**
  The brief offered a choice ("as inline heredoc content ... or as small
  fixture files under `.github/scripts/fixtures/` — your call, keep it
  simple"). Inline heredocs inside the one self-test script were simpler and
  kept every fixture next to the assertion it feeds, so no `fixtures/`
  directory was created.

## Staged GH commands

None. No `gh` writes were needed or performed for this step.

## Notes

`boundary-selftest.sh` gives each of the three grep-based gates in
`boundaries.yml` (forbidden-dependency, process/argv, config-I/O) two
provable properties: it REJECTS a deliberately-broken synthetic fixture
shaped like the real input the gate filters, and it ACCEPTS the real,
unmodified tree (no false positive against legitimate code). The
process/argv and config-I/O checks additionally prove the comment-exclusion
filter (`grep -vE '^[^:]+:[0-9]+:[[:space:]]*(//|\*|/\*)'`) still does its job
by including a commented-out violation line in each fixture that must NOT
trip the gate. The dependency gate's fixture is a synthetic package-name list
shaped exactly like `cargo tree -p ... | awk '{print $1}' | sort -u`'s real
output, per the explicit "no real cargo invocation" constraint. The new step
is wired into the `engine` job in `boundaries.yml` ahead of all three real
gates (right after `Setup the Rust toolchain` / `rust-cache`, before the wasm
check and the three grep gates), so a regression in any gate's regex is
caught before the gate it protects can silently no-op. No git write of any
kind was performed; all files are left uncommitted in the worktree per
protocol, ready for the conductor to stage after wave review.

Verdict: DONE for the W0-S13 brief as dispatched. The cross-lane `rust.yml`
addendum is BLOCKED-declined pending a proper dispatch — see Deviations.
