#!/usr/bin/env node
// packages/harness-pi/test/extension-detectors.test.mjs -- run directly:
//   node --experimental-strip-types test/extension-detectors.test.mjs
// Unit tests for src/extension.ts's pure bash-command detectors, independent of a live
// ExtensionAPI -- see test/guard-predicates.test.mjs for the predicate corpus itself and
// test/team-primitive-absent.test.mjs for the extension factory's end-to-end fail-closed
// behavior.

import assert from "node:assert/strict";
import { buildDispatchScopeCheck, buildGitCustodyCheck, buildWriteBoundaryCheck, parseGitInvocation } from "../src/extension.ts";

// parseGitInvocation
assert.deepEqual(parseGitInvocation("git commit -m x"), { subcommand: "commit", args: ["-m", "x"] });
assert.deepEqual(parseGitInvocation("cd worktree && git push origin agent-v645-l5-harness"), {
  subcommand: "push",
  args: ["origin", "agent-v645-l5-harness"],
});
assert.deepEqual(parseGitInvocation("git -C /repo rebase main"), { subcommand: "rebase", args: ["main"] });
assert.equal(parseGitInvocation("ls -la"), undefined, "a non-git command must not be detected as one");
assert.equal(parseGitInvocation("echo git-is-just-a-word"), undefined, "a bare word containing `git` must not false-positive");

// buildGitCustodyCheck
{
  const write = buildGitCustodyCheck("conductor", "git commit -m x", "agent-v645-l5-harness");
  assert.deepEqual(write, { predicateId: "git-custody", role: "conductor", action: "vcs.write", context: { is_own_lane_branch: true } });

  const crossLanePush = buildGitCustodyCheck("conductor", "git push origin other-lane-branch", "agent-v645-l5-harness");
  assert.equal(crossLanePush.context.is_own_lane_branch, false, "pushing a different branch than the declared lane branch must flag out-of-lane");

  const integrate = buildGitCustodyCheck("shepherd", "git rebase v645-dev0", undefined);
  assert.equal(integrate.action, "vcs.integrate");

  const worktreeAdmin = buildGitCustodyCheck("shepherd", "git worktree add ../lane2", undefined);
  assert.equal(worktreeAdmin.action, "vcs.integrate", "worktree add/remove/prune is a vcs.integrate action");

  assert.equal(buildGitCustodyCheck("coder", "npm test", undefined), undefined, "a non-git bash command must not build a check at all");
}

// buildDispatchScopeCheck
{
  const check = buildDispatchScopeCheck("conductor", "SHEPHERD_ROLE=coder pi --print --tools read,bash");
  assert.deepEqual(check, { predicateId: "dispatch-scope", role: "conductor", action: "dispatch", context: { target_role: "coder" } });
  assert.equal(buildDispatchScopeCheck("coder", "grep -rn pi-mono ."), undefined, "a command merely mentioning `pi` as a substring must not false-positive");
}

// buildWriteBoundaryCheck
{
  const inScope = buildWriteBoundaryCheck("coder", "packages/harness-pi/src/x.mjs", "packages/harness-pi");
  assert.equal(inScope.context.path_in_dispatch_write_scope, true);
  const outOfScope = buildWriteBoundaryCheck("coder", "crates/core/src/x.rs", "packages/harness-pi");
  assert.equal(outOfScope.context.path_in_dispatch_write_scope, false);
}

console.log("ok: extension.ts's bash-command detectors verified");
