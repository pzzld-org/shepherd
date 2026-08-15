# CODER REPORT — W0-S8 (content/ single-source tree + drift reconciliation)

- Lane: l5-harness
- Skills loaded: code-style
- Halts encountered: none
- Reporter: shepherd:coder @ 2026-08-13T00:46:03Z

## Files changed

All NEW (`content/` did not exist before this dispatch). Nothing outside `content/` was
touched — confirmed via `git status --porcelain` showing every other in-worktree change
(`.github/workflows/boundaries.yml`, `commands/spawn.md`, `hooks/scripts/_lib.sh`,
`hooks/scripts/agent_invocation_tagger.sh`, `hooks/scripts/session_open.sh`,
`hooks/tests/test_engineer_self_contained.sh`, `hooks/tests/test_v644_wiring.sh`,
`skills/harness/SKILL.md`, `skills/shepherd/SKILL.md`, `.github/scripts/`, `package.json`,
`packages/`) belongs to sibling coders in this same wave, all pre-existing before I started
and none edited by me.

```
content/RECONCILIATION.md
content/predicates/dedup-gate.toml
content/predicates/dispatch-scope.toml
content/predicates/git-custody.toml
content/predicates/write-boundary.toml
content/roles/auditor.md
content/roles/coder.md
content/roles/conductor.md
content/roles/critic.md
content/roles/discovery.md
content/roles/engineer.md
content/roles/planter.md
content/roles/shepherd.md
content/roles/worker.md
content/skills/adaptation/SKILL.md
content/skills/bridge/SKILL.md
content/skills/context/SKILL.md
content/skills/harness/SKILL.md
content/skills/motivation/SKILL.md
content/skills/shepherd/SKILL.md
content/skills/thinking/SKILL.md
```

21 files, 0 deleted.

## LOC delta

+1202 / -0 (all-new markdown/TOML; `wc -l` sum across every file listed above).

**Governance note, not an escalation:** the brief's `~260 LOC (estimate only)` figure is
stated against the coder protocol's `ONE-LOC rule`, whose counted unit is explicitly
"every production `*.rs` line" (`agents/coder.md §LOC budget`). This step touches zero
`*.rs` files — `content/` is markdown + TOML, `[FILE-SCOPE]` names nothing else — so the
dispatcher's deterministic `loc-count.py` measurement will report `0` production-Rust LOC
for this step regardless of the 1202 markdown/TOML lines above. I did not adjudicate a
budget conflict or cut anything to fit one (no deliverable was trimmed — all 9 roles, all
7 skills, 4 predicate files with concrete ALLOW+DENY examples, and the reconciliation doc
with a real decision on all 5 required rows are present in full, per `[ACTIONS]` 1–4). I'm
surfacing the interpretation transparently per `LOC-BUDGET-GOVERNANCE` discipline rather
than silently assuming it — if the dispatcher weighs markdown/TOML volume against the
"largest step in the batch" framing differently, that's a call for review, not something I
resolved unilaterally by cutting scope.

## Acceptance outputs

Run from the worktree root (`/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness`),
verbatim stdout + exit code:

```
$ test -f content/RECONCILIATION.md && echo PASS
PASS
exit: 0
```

```
$ for f in agents/*.md; do test -f "content/roles/$(basename $f)" || { echo "MISSING $f"; exit 1; }; done && echo "PASS (all 9 present)"
PASS (all 9 present)
exit: 0
```

```
$ python3 - <<'EOF'
import glob,re,sys
bad=[f for f in glob.glob('content/roles/*.md') if not re.search(r'^write_eligible:\s*(true|false)$', open(f).read(), re.M)]
assert not bad, f"roles missing write_eligible: {bad}"
print(f"ok: {len(glob.glob('content/roles/*.md'))} roles carry write_eligible")
EOF
ok: 9 roles carry write_eligible
exit: 0
```

Supplementary checks I ran beyond the brief's literal `[ACCEPTANCE]` block, to hold the
bar higher than "the three greps pass":

- All 4 `content/predicates/*.toml` files parse cleanly under `tomllib` and each carries
  ≥1 `kind = "allow"` and ≥1 `kind = "deny"` example (`dedup-gate`: 2 allow/1 deny;
  `dispatch-scope`: 2 allow/3 deny; `git-custody`: 2 allow/2 deny; `write-boundary`:
  2 allow/3 deny).
- All 16 `content/roles/*.md` + `content/skills/*/SKILL.md` files have a well-formed,
  `yaml.safe_load`-valid frontmatter block.
- `git rev-parse HEAD` after every write still equals the base commit
  `5be42280615c8dc5321061798240f476dffed645` — I performed zero git operations.
- `rg` for `TODO|FIXME|XXX|HACK` across `content/` returns nothing.

## Deviations

None from `[FILE-SCOPE]`/`[NON-GOALS]`. One documented judgment call, not a deviation:
`content/roles/conductor.md` is `write_eligible: true` despite conductor's `agents/
conductor.md` `tools:` frontmatter granting neither `Write` nor `Edit` — a literal
"has-the-tool" derivation would have misclassified it. Conductor commits + pushes its own
lane branch and writes narrowly under its own lane directory, both via `Bash`, not a
general write tool; Codex's `explorer`/`worker` split is about whether the *role* can
mutate the filesystem/repo at all, not which token performs it. I followed the brief's own
explicit classification (`coder`/`engineer`/`conductor`/`worker` write-eligible) over a
naive literal-frontmatter-grep, and documented the exception in full inside
`content/roles/conductor.md` itself (`## write_eligible: true — the documented exception`)
rather than silently reconciling the tension. `RECONCILIATION.md §write_eligible` states
the same reasoning at the tree level.

## Staged GH commands

None — this step made no GitHub-facing changes.

## Notes

- `[CONTEXT-INVENTORY]` verification: `.shepherd/runs/v645/reports/discovery-d1-harness.md`
  was read in full before writing anything (its §Engineer follow-up drift matrix is the
  direct input to `RECONCILIATION.md`'s 5-row decision table). No `{paths.ctx}/canonical-
  types.md` exists in this repo (walked the tree per the coder protocol's fallback); not
  applicable regardless since no Rust symbols were introduced this step.
- `[DO-NOT-DUPLICATE]` tripwire re-run before writing: `rg -n 'name: (engineer|coder|
  critic|auditor|worker|discovery)' agents/` returned exactly 6 files
  (`auditor.md coder.md critic.md discovery.md engineer.md worker.md`), matching the
  brief's expected count — no `DUPLICATION RISK`.
- Content design: every `content/roles/*.md` cites the shared capability-vocabulary legend
  in `RECONCILIATION.md` rather than restating it 9 times (token discipline); every
  `content/skills/*/SKILL.md` carries a `portability:` frontmatter field
  (`cross-harness` / `claude-only` / `unverified`) so a later-wave adapter knows, without
  re-deriving it, which digests are safe to compile for a non-Claude harness today and
  which still need independent discovery work first (`RECONCILIATION.md §Residual`).
- `content/predicates/*.toml` intentionally stays declarative data (no embedded logic) so
  both a future Rust engine and Pi's TS guard layer can interpret the same file, per the
  discovery report's core-vs-adapter split ("guard-predicate evaluation... MUST live in
  shared core").
