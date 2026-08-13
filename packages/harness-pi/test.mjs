#!/usr/bin/env node
// packages/harness-pi/test.mjs -- placeholder test for the Pi coding agent
// adapter.
//
// Intentionally failing. W0-S7 is the npm workspace skeleton only -- there is
// no adapter logic yet to exercise. `npm test` in this package must stay red
// until W4-S6 lands the real adapter (see plan.md W4-S6).

class NotImplementedError extends Error {}

throw new NotImplementedError(
  "@fl03/harness-pi has no adapter logic yet -- implemented in Wave 4 (see plan.md W4-S6)."
);
