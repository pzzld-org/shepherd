// packages/harness-claude/src/model.mjs -- resolves a role's abstract `model_hint`
// (content/roles/*.md; carried through @fl03/compiler's `claude` target unresolved, see
// packages/compiler/src/targets/claude.mjs's field comment) onto Claude's concrete `model:`
// frontmatter value. This resolution is genuinely per-harness adapter work
// (discovery-d1-harness.md `## Core vs adapter split (b)` names "per-role model pinning" as
// exactly that split), so it lives here, not in the compiler.
//
// The mapping is not guessed: it is read off the CURRENTLY COMMITTED `agents/*.md` --
// this repo's own hand-maintained, reference-implementation tree -- by pairing each file's
// `model:` value against its `content/roles/<role>.md` counterpart's `model_hint:` value.
// Every one of the 9 roles agrees with exactly one of the three cases below (verified via
// `rg -n '^model_hint:' content/roles/*.md` cross-referenced against `rg -n '^model:'
// agents/*.md` at authorship time), so this is a transcription, not an invention:
//
//   model_hint       model:        example roles
//   standard         sonnet        auditor, coder, conductor, critic, discovery, worker
//   reasoning-high    opus[1m]      engineer, planter
//   inherit-caller    inherit       shepherd (root)
//
// `opus[1m]` (an extended-context Opus variant, not a member of the `sonnet|opus|haiku|fable`
// enum plan.md's own [CONTEXT-INVENTORY] names) and `inherit` (root's sentinel: run as the
// calling session's own model rather than spawning a pinned one) are BOTH legal values in
// the live tree today -- the plan's "closed enum" framing is a simplification this adapter
// does not repeat.

const MODEL_BY_HINT = Object.freeze({
  standard: "sonnet",
  "reasoning-high": "opus[1m]",
  "inherit-caller": "inherit",
});

/**
 * @param {string} modelHint one of `content/roles/*.md`'s `model_hint` values.
 * @returns {string} the resolved Claude `model:` frontmatter value.
 */
export function resolveModel(modelHint) {
  const model = MODEL_BY_HINT[modelHint];
  if (!model) {
    throw new Error(
      `unknown model_hint \`${modelHint}\` -- expected one of ${Object.keys(MODEL_BY_HINT).join(", ")}`
    );
  }
  return model;
}
