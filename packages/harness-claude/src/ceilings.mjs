// packages/harness-claude/src/ceilings.mjs -- Claude's real dispatch ceilings, declared
// here rather than discovered at runtime (plan.md W4-S4/S5/S6 Action 3: "Declare each
// harness's real ceilings in config rather than discovering them at runtime" -- named
// explicitly for Codex's 3-descendant cap and Pi's absent team primitive; this is that same
// discipline applied to Claude's own two documented caps).
//
// Source: `skills/harness/SKILL.md` `## Workflow tool` -- "Hard caps: ~16 concurrent
// agents; 1,000 total dispatches per run." That skill is the research-verified platform
// capability map for this harness (its own header: "research-verified 2026-07-06 against
// the live docs"); `content/skills/harness/SKILL.md` deliberately does NOT carry these
// numbers (it stays a Claude-only pointer, RECONCILIATION.md row 2), so this module is
// where the concrete figures live for anything in `packages/harness-claude/` that needs
// them -- never re-derived, never hardcoded a second time.

export const CLAUDE_CEILINGS = Object.freeze({
  /** Hard cap on concurrently in-flight agents under one `Workflow` run. Approximate --
   *  the platform doc calls it "~16" -- so callers should treat this as a ceiling to stay
   *  under, not an exact quota to fill. */
  maxConcurrentAgents: 16,
  /** Hard cap on total agent dispatches (not concurrency) across one `Workflow` run's
   *  lifetime. */
  maxTotalDispatchesPerRun: 1000,
});
