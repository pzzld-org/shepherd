// packages/harness-pi/src/extension.ts -- the Pi guard layer: a genuine second interpreter
// of content/predicates/*.toml (decision 1, discovery-d1-harness.md), since Pi has no
// hooks.json module at all ("hooks do not exist as a module, they are extensions" --
// discovery-d1-harness.md's Pi probe, confirmed against primary docs in
// discovery-harness-portability.md §2). Registers exactly ONE pi.on('tool_call', ...)
// handler (content/RECONCILIATION.md's dedup grep target: "exactly one guard interpreter
// per harness").
//
// Role identity: Pi has no native per-role dispatch primitive (D1: "a role = a CLI
// invocation"), so src/dispatch.mjs sets SHEPHERD_ROLE and SHEPHERD_SCOPE in the subprocess
// environment before spawning `pi` for a given role -- the same two dispatch-envelope field
// names skills/bridge/SKILL.md already defines for cross-harness handoffs, reused here
// rather than inventing a second env-var convention. FAILS CLOSED when SHEPHERD_ROLE is
// unset: an unidentified session gets no write/git/dispatch capability through this guard,
// never every capability by default -- an unenforceable-by-omission guard is exactly the
// silent-non-enforcement defect this step's brief warns against.
//
// NAMED GAP -- dedup-gate is NOT wired here, even though src/guard.ts implements and tests
// it against its full corpus. A dedup-gate verdict needs a resolved *symbol name* plus a
// registry hit (`shctx query dedup-check --name=<symbol>`, skills/context/SKILL.md), and the
// write/edit tool_call event Pi actually delivers ({path, content} / {path, edits[]}, see
// src/pi-types.ts) carries neither. Extracting "the one new public symbol this write
// introduces" from raw file content is language-aware static analysis this guard layer does
// not perform -- across every content language shepherd coders touch, that is a real,
// separate piece of work, not a one-line addition. Emitting a wired handler that always
// allows (or always denies) here would look complete while enforcing nothing; leaving it
// explicitly unwired, and saying so, is the honest result the brief asks for.
//
// Git-custody and dispatch-scope detection both parse a `bash` command string (Pi has no
// dedicated git or subprocess-spawn tool -- both ride the one `bash` tool). This is a
// heuristic, like any regex-based command guard (including shepherd's own bash-hook guards
// on Claude): a determined adversarial prompt could obfuscate a git/`pi` invocation past it.
// It is real, tested enforcement against the corpus's shape of commands, not a no-op.

import type { ExtensionAPI, ToolCallEvent, ToolCallEventResult } from "./pi-types.ts";
import { evaluate, type GuardCheck, type RoleFact } from "./guard.ts";
import { loadRoleFacts } from "./roles.mjs";

const GIT_WRITE_SUBCOMMANDS = new Set(["commit", "push"]);
const GIT_INTEGRATE_SUBCOMMANDS = new Set(["rebase", "merge", "cherry-pick"]);
const GIT_FLAGS_TAKING_A_VALUE = new Set(["-C", "--git-dir", "--work-tree"]);

/** Splits "a && b; c | d" into independent segments -- each may itself invoke `git`/`pi`. */
function splitShellSegments(command: string): string[] {
  return command.split(/&&|\|\||[;|]/);
}

/** Locates a `git <subcommand> [args...]` invocation inside a bash command, if any. */
export function parseGitInvocation(command: string): { subcommand: string; args: string[] } | undefined {
  for (const segment of splitShellSegments(command)) {
    const tokens = segment.trim().split(/\s+/).filter(Boolean);
    const gitIdx = tokens.indexOf("git");
    if (gitIdx === -1) continue;
    let i = gitIdx + 1;
    while (i < tokens.length && tokens[i].startsWith("-")) {
      i += GIT_FLAGS_TAKING_A_VALUE.has(tokens[i]) ? 2 : 1;
    }
    if (i < tokens.length) return { subcommand: tokens[i], args: tokens.slice(i + 1) };
  }
  return undefined;
}

function lastNonFlagArg(args: string[]): string | undefined {
  const nonFlags = args.filter((a) => !a.startsWith("-"));
  return nonFlags.at(-1);
}

/** @param laneBranch this dispatch's own lane branch (SHEPHERD_LANE_BRANCH), if known. */
export function buildGitCustodyCheck(role: string, command: string, laneBranch: string | undefined): GuardCheck | undefined {
  const invocation = parseGitInvocation(command);
  if (!invocation) return undefined;
  const { subcommand, args } = invocation;

  if (GIT_WRITE_SUBCOMMANDS.has(subcommand)) {
    // `commit` always writes to whatever branch is currently checked out -- there is no
    // separate "target branch" argument to extract, so it is always this dispatch's own
    // lane branch by construction. Only `push` can name a DIFFERENT branch than the one
    // checked out (`git push origin <branch>`), so only it gets compared.
    let isOwnLaneBranch = true;
    if (subcommand === "push" && laneBranch !== undefined) {
      const targetBranch = lastNonFlagArg(args);
      if (targetBranch !== undefined) isOwnLaneBranch = targetBranch === laneBranch;
    }
    return { predicateId: "git-custody", role, action: "vcs.write", context: { is_own_lane_branch: isOwnLaneBranch } };
  }
  const isWorktreeAdmin = subcommand === "worktree" && ["add", "remove", "prune"].includes(args[0] ?? "");
  if (GIT_INTEGRATE_SUBCOMMANDS.has(subcommand) || isWorktreeAdmin) {
    return { predicateId: "git-custody", role, action: "vcs.integrate", context: {} };
  }
  return undefined;
}

// A nested `pi` invocation IS a dispatch attempt on this harness (D1: "a role = a CLI
// invocation" -- there is no other dispatch mechanism to detect).
const PI_INVOCATION = /(^|[\s;&|])pi(\s|$)/;
const SHEPHERD_ROLE_ASSIGNMENT = /SHEPHERD_ROLE=(\S+)/;

export function buildDispatchScopeCheck(role: string, command: string): GuardCheck | undefined {
  if (!PI_INVOCATION.test(command)) return undefined;
  const targetRole = SHEPHERD_ROLE_ASSIGNMENT.exec(command)?.[1] ?? "unknown";
  return { predicateId: "dispatch-scope", role, action: "dispatch", context: { target_role: targetRole } };
}

export function buildWriteBoundaryCheck(role: string, path: string, scope: string | undefined): GuardCheck {
  const prefixes = (scope ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const inScope = prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`) || path.startsWith(prefix));
  return {
    predicateId: "write-boundary",
    role,
    action: "fs.write",
    context: { write_eligible: true, path_in_dispatch_write_scope: inScope },
  };
}

/**
 * @param contentDir absolute path to content/ (this step's file_scope.may_read).
 */
export default function shepherdGuardExtension(pi: ExtensionAPI, contentDir: string): void {
  const roleFactsRaw = loadRoleFacts(contentDir);
  const roleFacts = new Map<string, RoleFact>(
    Array.from(roleFactsRaw).map(([role, fact]) => [role, { writeEligible: fact.writeEligible, capabilities: fact.capabilities }])
  );

  pi.on("tool_call", (event: ToolCallEvent): ToolCallEventResult | undefined => {
    const role = process.env.SHEPHERD_ROLE;
    if (!role) {
      if (event.toolName === "write" || event.toolName === "edit" || event.toolName === "bash") {
        return { block: true, reason: "SHEPHERD_ROLE is unset -- guard cannot resolve role identity, denying by default" };
      }
      return undefined;
    }

    if (event.toolName === "write" || event.toolName === "edit") {
      const check = buildWriteBoundaryCheck(role, event.input.path, process.env.SHEPHERD_SCOPE);
      // write_eligible is a role fact, not a per-call one -- resolve it here rather than in
      // the pure builder above, which stays testable without a live roleFacts map.
      check.context.write_eligible = roleFacts.get(role)?.writeEligible ?? false;
      const verdict = evaluate(check, roleFacts);
      if (!verdict.allow) return { block: true, reason: verdict.reason };
      return undefined;
    }

    if (event.toolName === "bash") {
      const gitCheck = buildGitCustodyCheck(role, event.input.command, process.env.SHEPHERD_LANE_BRANCH);
      if (gitCheck) {
        const verdict = evaluate(gitCheck, roleFacts);
        if (!verdict.allow) return { block: true, reason: verdict.reason };
        return undefined;
      }
      const dispatchCheck = buildDispatchScopeCheck(role, event.input.command);
      if (dispatchCheck) {
        const verdict = evaluate(dispatchCheck, roleFacts);
        if (!verdict.allow) return { block: true, reason: verdict.reason };
        return undefined;
      }
    }

    return undefined;
  });
}
