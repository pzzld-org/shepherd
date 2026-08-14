// packages/harness-pi/src/dispatch.mjs -- Pi has no native per-role dispatch primitive
// (discovery-d1-harness.md: "absent as file-declared roles; a role = a CLI invocation
// (`pi --system-prompt`/`--append-system-prompt` + `--model` + `--tools`)"), and `setModel()`
// is session-global (discovery-harness-portability.md §3: "session-global (--model, one
// process per role)"), so per-role model pinning costs one `pi` subprocess per role rather
// than a frontmatter flag. This module builds that subprocess's argv + env; it never spawns
// one -- spawning is the caller's job, so this stays a pure, unit-testable builder.
//
// `--append-system-prompt <path>` resolves to the FILE'S CONTENTS when the path exists on
// disk (confirmed against the installed 0.84.1 binary's own resource-loader:
// `resolvePromptInput` calls `readFileSync` when `existsSync(input)`), so passing the
// materialized `prompts/<role>.md` path is correct, not a guess.
//
// `SHEPHERD_ROLE`/`SHEPHERD_SCOPE` reuse skills/bridge/SKILL.md §Dispatch envelope's own
// field names for the same purpose (role identity, declared write scope) rather than
// inventing a second env-var convention -- src/extension.ts's guard layer reads the same
// two variables at tool_call time.

import { resolvePiModelFlag } from "./models.mjs";
import { resolvePiTools } from "./tools.mjs";

/**
 * @param {import("./roles.mjs").RoleFact} role
 * @param {{promptPath: string, writeScope?: string, binary?: string}} options
 *   `promptPath` is the materialized `prompts/<role>.md` (see src/materialize.mjs).
 * @returns {{argv: string[], env: Record<string,string>, unsupportedCapabilities: string[]}}
 */
export function buildRoleInvocation(role, options) {
  if (!role.dispatchable) {
    throw new Error(`role \`${role.role}\` is dispatchable: false -- it is a session root/meta tier, never spawned as its own subprocess`);
  }
  if (!options.promptPath) {
    throw new Error("options.promptPath is required -- it carries the role's system-prompt content");
  }

  const binary = options.binary ?? "pi";
  const model = resolvePiModelFlag(role.modelHint);
  const { tools, unsupported } = resolvePiTools(role.capabilities);

  const argv = [binary, "--print", "--append-system-prompt", options.promptPath, "--tools", tools.join(",")];
  if (model) argv.push("--model", model);

  const env = { SHEPHERD_ROLE: role.role };
  if (options.writeScope) env.SHEPHERD_SCOPE = options.writeScope;

  return { argv, env, unsupportedCapabilities: unsupported };
}
