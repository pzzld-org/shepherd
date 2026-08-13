#!/usr/bin/env node
// packages/compiler/test.mjs -- placeholder test for the content/ compiler.
//
// Intentionally failing. W0-S7 is the npm workspace skeleton only (manifests,
// READMEs, and the dependency-rule gate) -- there is no `compile()` yet to
// exercise. `npm test` in this package must stay red until W4-S3 lands the
// real emitter and replaces this file with `packages/compiler/test/*.test.mjs`
// (see plan.md W4-S3, which names `test/write-eligibility.test.mjs`
// explicitly).

class NotImplementedError extends Error {}

throw new NotImplementedError(
  "@fl03/compiler has no compile() implementation yet -- implemented in Wave 4 (see plan.md W4-S3)."
);
