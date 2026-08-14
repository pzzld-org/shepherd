// packages/harness-pi/src/models.mjs -- resolves a role's abstract `model_hint`
// (content/roles/*.md: standard|reasoning-high|inherit-caller) to Pi's `--model <pattern>`
// subprocess flag ("Model pattern or ID (supports \"provider/id\" and optional
// \":<thinking>\")" -- `pi --help`, confirmed against the installed 0.84.1 binary at
// /opt/homebrew/bin/pi). The Claude-side slug per hint is
// skills/context/references/model-map.md's `[models]` table (root/planter/engineer =
// "opus[1m]", the rest = "sonnet"); Pi's flag takes a BARE model id, not Claude's
// extended-context annotation, so "opus[1m]" becomes "opus".

const CLAUDE_MODEL_SLUG_BY_HINT = Object.freeze({
  standard: "sonnet",
  "reasoning-high": "opus[1m]",
  // `inherit-caller` (shepherd/root only) is never spawned as a `pi` subprocess by this
  // adapter -- root IS the running session, matching model-map.md's "`root` is advisory":
  // "a [models].root key cannot rebind an already-running session."
  "inherit-caller": undefined,
});

/** Strips Claude's extended-context annotation. `toBareModelId("opus[1m]")` -> `"opus"`. */
export function toBareModelId(claudeSlug) {
  return claudeSlug.replace(/\[[^\]]*\]$/, "");
}

/**
 * @param {string} modelHint one of content/roles/*.md's `model_hint` values.
 * @returns {string|undefined} the bare id for Pi's `--model` flag, or `undefined` when the
 *   role is never spawned as its own subprocess (`inherit-caller`).
 */
export function resolvePiModelFlag(modelHint) {
  if (!(modelHint in CLAUDE_MODEL_SLUG_BY_HINT)) {
    throw new Error(`unknown model_hint \`${modelHint}\` -- expected one of ${Object.keys(CLAUDE_MODEL_SLUG_BY_HINT).join(", ")}`);
  }
  const slug = CLAUDE_MODEL_SLUG_BY_HINT[modelHint];
  return slug === undefined ? undefined : toBareModelId(slug);
}
