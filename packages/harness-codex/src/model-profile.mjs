// packages/harness-codex/src/model-profile.mjs -- resolves each content/roles/*.md
// `model_hint` into a Codex `[models]`/`[profiles."<name>"]` pin. compile('codex') passes
// `model_hint` through UNRESOLVED (packages/compiler/src/targets/codex.mjs never reads it;
// the W4-S3 assumptions doc names this "adapter work, not compiler work"), so this module is
// where that resolution actually happens for Codex.
//
// WHY THE PROFILE NAME IS `model_hint` ITSELF, NOT A CLAUDE MODEL TOKEN. The dispatch brief
// warns "opus[1m] maps to opus; the [1m] suffix is Claude-Code-specific and must not leak
// into a Codex profile" -- but `agents/*.md`'s concrete `model: opus[1m]`/`model: sonnet`
// pins live outside this adapter's declared file scope (`packages/compiler/`, `content/**`
// only) and outside content/'s own source of truth (content/roles/*.md carries `model_hint`,
// never a concrete model id). Cross-referencing `agents/*.md` here would smuggle in a second,
// unauthorized source of truth for exactly the fact this sprint's content/ unification exists
// to centralize. Naming the profile after content/'s own harness-neutral `model_hint` value
// satisfies the instruction two ways at once: it is "a NAME, not a model id" by construction,
// and zero Claude-specific syntax (`[1m]`, `sonnet`, `opus`) can leak in because none is ever
// read. A concrete Codex `model =` engine id (e.g. the live `gpt-5.6-sol` observed in the
// installed `codex-shepherd@1.0.2` bundle) is deliberately NOT emitted here for the same
// reason skill-emit.mjs omits a fabricated `description`: content/ carries no per-harness
// model catalog, and inventing one would be exactly the unverified claim the coder protocol
// forbids. `reasoning_effort` alone is set, from Codex's own native minimal|low|medium|high
// vocabulary (confirmed live at `~/.codex/config.toml`'s `model_reasoning_effort` key).

/** content/roles/shepherd.md's unique `model_hint` -- root is excluded from the Codex table
 * before profile resolution ever runs (packages/compiler/src/targets/codex.mjs's own
 * `ROOT_MODEL_HINT` filter, mirrored here so this module never has to resolve it). */
export const ROOT_MODEL_HINT = "inherit-caller";

const PROFILES = Object.freeze({
  standard: Object.freeze({ name: "standard", reasoningEffort: "medium" }),
  "reasoning-high": Object.freeze({ name: "reasoning-high", reasoningEffort: "high" }),
});

/**
 * @param {string} modelHint a non-root `content/roles/*.md` `model_hint` value.
 * @returns {{name: string, reasoningEffort: string}}
 */
export function resolveProfile(modelHint) {
  const profile = PROFILES[modelHint];
  if (!profile) {
    throw new Error(
      `no Codex profile mapping for model_hint \`${modelHint}\` -- expected one of ` +
        `${Object.keys(PROFILES).join(", ")} (\`${ROOT_MODEL_HINT}\` is root-only and must ` +
        `already be filtered out before resolveProfile is called)`
    );
  }
  return profile;
}

/** @returns {{name: string, reasoningEffort: string}[]} every known profile, `name` order. */
export function allProfiles() {
  return Object.values(PROFILES).sort((a, b) => a.name.localeCompare(b.name));
}
