## CODER REPORT

- Lane: W8-L3 (contradiction-ledger fix wave, `L3` = findings #9 + #17)
- Skills loaded: none of the language skills applied — target is a single
  Markdown doctrine file (`code-style` has no Markdown-specific ledger; no
  `[SKILLS]` entry was resolvable for a `.md` file-scope, so the edit
  followed the ledger's own prose conventions verbatim: bold lead sentences,
  backtick-quoted paths/symbols, em-dash asides, matching the surrounding
  file's existing style)
- Files touched (created/modified/deleted): `/Users/jo3/src/fl03/shepherd/skills/context/references/naming-conventions.md` (modified)
- LOC delta: +31 / -16 (net +15; this is a `.md` doctrine file — the ONE-LOC
  rule's production-Rust-line count does not apply)
- Acceptance grep results:
  - Finding #9 (`learnings/` added to tracked list, paired with `ctx/`):
    `grep -n "learnings/" skills/context/references/naming-conventions.md`
    → 3 hits (§One knowledge silo qualifier, §Layout tracked-list entry,
    §Layout citation sentence) — PASS
  - Finding #17 (`reports/`/`audits/` flipped from "ignored" to "tracked",
    verified against real `.gitignore`, not the brief's stale line numbers):
    `grep -c '| ignored |' skills/context/references/naming-conventions.md`
    on the six `{run_dir}/reports/*` and `{run_dir}/audits/*` table rows →
    0 remaining "ignored" hits among those six rows, all now read "tracked"
    — PASS. Cross-checked live `.gitignore:98-102`
    (`!.shepherd/runs/*/reports/`, `!.shepherd/runs/*/reports/*.md`,
    `!.shepherd/runs/*/audits/`, `!.shepherd/runs/*/audits/*.md`) — matches.
  - "Briefly say why" requirement: new paragraph after the existing v6.4.4
    run-scoped-path paragraph states the DF-61 rationale and cites
    `skills/shepherd/SKILL.md §Principles` DURABLE ARTIFACT verbatim
    ("every top-tier dispatch MUST terminate in exactly one durable
    artifact … reasoning that lives only in a transcript is spend without
    impact") — PASS, citation verified present at `skills/shepherd/SKILL.md:128`.
- Halts encountered: none
- Summary: Fixed both findings inside the single exclusive file. #17: the
  six `{run_dir}/reports/*` / `{run_dir}/audits/*` table rows flipped from
  "ignored" to "tracked," plus a new short paragraph explaining the DF-61
  rationale (every expensive dispatch's output is the durable artifact per
  `SKILL.md §Principles`), and the downstream "tracked/ignored split"
  summary paragraph (previously still listing `reports/`/`audits/` as
  disposable run state) was corrected in the same pass so the file doesn't
  contradict itself two paragraphs later. #9: added `learnings/` to the
  §Layout tracked-directory list alongside `ctx/`, citing
  `skills/bridge/SKILL.md §Principle: the filesystem is the bus` (verified
  exact heading text, not "§Artifact schema" as I initially assumed).
  Discovered in passing that this created tension with this same file's own
  "`ctx/` is the ONLY knowledge silo" hard-rule sentence (§One knowledge
  silo, v6.4.4) — resolved it in-file (same exclusive-scope file, not scope
  overflow) by adding one qualifying sentence: `learnings/` is the
  bridge cross-shepherd-shared counterpart paired with `ctx/`, not a second
  general-purpose silo, so the v6.4.4 hard rule (`ctx/` is the one place
  *this implementation's own* cross-run knowledge lives) still holds.
  Verified `learnings/` is not wired into any `[paths]` config key, script,
  or `docs/configuration.md` schema row (grepped `learnings` across
  `*.py`/`*.sh`/`*.toml`/`docs/*.md` — zero hits outside `bridge/SKILL.md`
  and this file), so I did not claim it is scaffolded or lint-enforced —
  only that it is a bridge-paired durable/tracked path, matching exactly
  what finding #9's resolution text asked for and no more. No build/test
  commands were run per the resource-discipline instruction; the only
  compile-time-relevant fact for the central verifier is that this is a
  pure Markdown edit with no code, config, or script changes, so no build
  step touches it.
- Reporter: coder-W8-L3 @ 2026-08-13T00:00:00Z

## INSIGHTS

- kind: gap — `skills/bridge/SKILL.md:39,78` cites `.shepherd/learnings/` as a durable, tracked, bridge-shared path, but no `[paths]` config key, scaffold command, or `docs/configuration.md` schema row implements it anywhere in the codebase (grepped `*.py`/`*.sh`/`*.toml`/`docs/*.md`) — it is prose-only. A future lane should either wire it up (config key + `shepherd run init`/`shctx init` scaffold + `docs/configuration.md` row) or demote bridge's claim to "planned" until it is. Filing this now rather than silently patching around it since the fix I made (adding it to `naming-conventions.md`'s tracked list) documents a path nothing in the runtime actually creates.
