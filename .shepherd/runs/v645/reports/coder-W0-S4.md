# CODER REPORT — W0-S4 (HALTED)

- Lane: W0-S4 — model slugs are translated by the engine, not by each dispatcher (DF-03)
- Skills loaded: `code-style` (loaded successfully). `python` — **HALT: not found**.
- Files touched: none (halted at Step 1, before Step 4 — no Write/Edit performed)
- LOC delta: +0 / -0
- Acceptance grep results: not run (blocked before implementation)
- Halts encountered: **`BRIEF INVALID — skill \`python\` listed in [SKILLS] not found. Halting.`**
- Reporter: coder-W0-S4 @ 2026-08-12T00:00:00Z (session clock; see task dispatch timestamp for wall-clock)

## What happened

Step 0.5 passed clean: `pwd` = `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l4-conformance`,
`git rev-parse HEAD` = `5be42280615c8dc5321061798240f476dffed645`, matches
`[BASE-COMMIT-EXPECTED]` exactly. Worktree was clean (`git status --short` empty) before and
remains clean after this halt — zero writes made.

Step 1 (Load skills) failed. The brief's authoritative `[SKILLS]` line
(`.shepherd/runs/v645/plan.md:820`) reads:

```
**[SKILLS]** `code-style`, `python`
```

`code-style` loaded successfully (confirmed via `Skill(code-style)` — full ledger content
returned, including the `python.md` per-language preferences pointer).

`python` does **not** resolve. Direct proof:

```
Skill(python) → error: "Unknown skill: python"
```

I cross-checked this wasn't a listing gap before halting (three independent checks, all
negative):

1. `find /Users/jo3/.claude/plugins -iname "SKILL.md" | xargs grep -l "^name: *python$"` — no
   hits anywhere across `claude-plugins-official`, `shepherd`, `ponytail`, or `pzzld`
   marketplaces/caches.
2. Directory scan for anything python-named under any installed skill tree turned up only
   `code-style/python.md` (Joe's per-language *preference ledger*, not a language-mastery
   skill — its own `SKILL.md` explicitly says it "complements (does not replace) the
   language-mastery skills (`rust`, `webassembly`, etc.)") and unrelated Sentry
   Python-SDK docs.
3. The live `Skill` tool call itself returned `Unknown skill: python` — definitive, not
   inferred.

Per `agents/coder.md` §Skills to load (verbatim, matches my system prompt exactly):

> Listed skill not installed → halt `BRIEF INVALID — skill \`<slug>\` listed in [SKILLS] not
> found. Halting.`

This is the first branch of that rule (a skill IS listed, but ISN'T installed) — distinct from
the second branch (`[FILE-SCOPE]` language missing from `[SKILLS]` entirely →
`BRIEF-AMENDMENT REQUEST`), which does not apply here since `python` *is* present in the list.
The instruction is explicit: "load every entry, never substitute" and "don't self-elect" a
domain skill that's missing. I did not write `models.py` or `test_models.py`, and did not
proceed past Step 1.

## Scope of the finding — this is very likely wave-wide, not W0-S4-specific

I mapped every `[SKILLS]` line in `.shepherd/runs/v645/plan.md` against Wave 0's step headers:

| Step | `[SKILLS]` line | Language token |
|---|---|---|
| W0-S1 | `code-style`, `markdown` | `markdown` — not installed |
| W0-S2 | `code-style`, `shell` | `shell` — not installed |
| W0-S3 | `code-style`, `python` | `python` — not installed |
| **W0-S4** | `code-style`, `python` | **`python` — not installed (this step)** |
| W0-S5 | `code-style`, `markdown` | `markdown` — not installed |
| W0-S6 | `code-style`, `shell` | `shell` — not installed |
| W0-S7 | `code-style`, `typescript` | `typescript` — not installed |
| W0-S8 | `code-style`, `markdown` | `markdown` — not installed |
| W0-S9 | `code-style`, `shell`, `python` | both — not installed |
| W0-S10 | `code-style`, `markdown` | `markdown` — not installed |
| W0-S11 | `code-style`, `shell` | `shell` — not installed |
| W0-S12 | `code-style`, `shell` | `shell` — not installed |
| W0-S13 | `code-style`, `shell` | `shell` — not installed |
| W0-S14 | `code-style`, `python` | `python` — not installed |
| W0-S15 | `code-style`, `shell` | `shell` — not installed |

I confirmed via a full plugin/marketplace scan (`claude-plugins-official`, `shepherd`,
`ponytail`, `pzzld`, all cached versions) that **no** Claude Code skill named `python`,
`shell`, or `markdown` exists anywhere in this installation. `typescript` was not directly
re-verified but is absent from the "available skills" system-reminder listing the same way the
other three are, so I expect it fails identically. The only genuine installed
language-mastery skills in this environment are `rust`, `webassembly`, and the
language-agnostic `typing` skill — i.e. every Wave-0 step whose `[FILE-SCOPE]` is `.py`/`.sh`/
`.md`/`.ts` is built on a `[SKILLS]` entry the plan expects to exist and this installation does
not provide.

I am flagging this rather than silently treating `code-style`'s `python.md` file as a
substitute, per "Conductor computes `[SKILLS]` mechanically — load every entry, never
substitute" and "Domain skill helps but is omitted → request amendment, don't self-elect."

## Recommendation (not adjudicated — conductor's call)

Two non-exclusive fixes, either resolves this step and likely the rest of Wave 0's non-Rust
steps in one pass:

1. **Plan fix**: strip the bare language tokens (`python`, `shell`, `markdown`, `typescript`)
   from every `[SKILLS]` line where no matching installed skill exists, leaving `code-style`
   alone to cover those languages (its own doc already says it "applies the shared principles"
   and per-language ledger file when no mastery skill exists) — re-verify against
   `agents/coder.md`'s exact halt/no-halt branching before re-dispatch.
2. **Installation fix**: install/author `python`/`shell`/`markdown`/`typescript` language-
   mastery skills (mirroring how `rust` and `webassembly` are structured) if the intent was for
   coders to actually load language-specific mastery content beyond `code-style`.

I did not make this call myself — this is exactly the `LOC-BUDGET-GOVERNANCE`-adjacent class of
"budget/scope/governance interpretation" I'm instructed to escalate, not adjudicate.

## Everything else, for when this is unblocked

Once `[SKILLS]` is corrected and I'm re-dispatched, Steps 2-5 are straightforward from the
brief and I already have the context loaded:

- `_resolve_role`/`ModelRoleResolution`, `MODELS_ROLES`, `_OPUS_ROLES`, `_model_default` in
  `services/cli/shepherd_cli/commands/models.py` — read plan, not yet re-verified live (Step 2
  CONTEXT-INVENTORY grep was not run — blocked before Step 2).
- DEDUP-GATE grep (`rg -n 'opus\[1m\]' --include='*.py' services/cli`, expected 4) — not run
  (blocked before Step 3).
- Plan to build: one `_HARNESS_TRANSLATION` table (role → {claude, codex, pi} slug) inside
  `models.py`; `--harness` option on `resolve()` defaulting to `None`/omitted preserving today's
  raw-intent-slug output byte-for-byte; grep `services/cli/` for existing `.codex.toml` /
  `reasoning_effort` / harness-spelling conventions before inventing `claude`/`codex`/`pi` value
  spellings or Codex profile names — none of this was done yet since Step 1 never completed.

## Reporter

coder-W0-S4, halted at Startup Protocol Step 1, before any Write/Edit call.
