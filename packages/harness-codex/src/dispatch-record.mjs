// packages/harness-codex/src/dispatch-record.mjs -- Codex's missing analog of
// hooks/scripts/agent_invocation_tagger.sh + `current_role()` (hooks/scripts/_lib.sh) --
// DF-75's role-resolution half (part 1/2; the engine-relay half lives in src/guard.mjs).
// Claude tags a dispatch at PreToolUse(Agent) by writing a record keyed by the dispatch
// call's own `tool_use_id`, then every later Bash/Write call inside that dispatch resolves
// its role by reading the record back. Codex has NO Claude-shaped identifier available at
// spawn time -- `agent_id` is assigned by the Codex runtime only once `spawn_agent` /
// `collaborationspawn_agent` returns -- so this module ties the same pattern to Codex's own
// wire shape instead of inventing an env-var-injection scheme:
//
//   PostToolUse(spawn_agent|collaborationspawn_agent) carries BOTH the original
//   `tool_input` (the role-bearing `task_name`/`message` the dispatcher supplied) AND
//   `tool_response` (the runtime-assigned `agent_id`) in ONE event -- so the record can be
//   written keyed by `agent_id` in a single hook firing, no two-phase pending/commit state
//   needed. Every LATER tool call made by that spawned agent then carries `agent_id` (and
//   `agent_type`) directly on ITS OWN hook payload -- Codex's native equivalent of "which
//   dispatch does this nested call belong to."
//
// VERIFIED, not guessed (the coder brief's own bar: "do not ship a correlation you have not
// seen work"). Three converging sources, none of them a live trace of this exact package
// (no live Codex session was available to this dispatch), but all independently confirming
// the same wire shape:
//   1. `.shepherd/runs/v645/reports/discovery-harness-portability.md` (this sprint's own
//      @discovery pass, official-docs-sourced): Codex's stable, on-by-default hook taxonomy
//      includes `PostToolUse`, `SubagentStart`, `SubagentStop`; and names the CONFIRMED
//      community-converged workaround for Codex's MultiAgentV2 spawn (`spawn_agent`
//      defaults to full-history fork, which rejects `agent_type`/`model` overrides --
//      `github.com/openai/codex/issues/20077`): "encode the role in `task_name`... inject
//      the real role/model metadata through a `PreToolUse` hook instead of the `spawn_agent`
//      call." `task_name` is therefore the load-bearing, real-world field to parse a role
//      from, not an invented convention.
//   2. The installed, ENABLED, actively-used sibling plugin
//      `~/.codex/plugins/cache/codex-shepherd/codex-shepherd/1.0.2` (a full separate
//      governance product targeting the SAME `spawn_agent`/`collaborationspawn_agent`
//      primitives) reads exactly `event.get("agent_id")` / `event.get("agent_type")` off
//      PreToolUse/PostToolUse/SubagentStart/SubagentStop payloads as its own correlation
//      key, and its own `task_name` grammar is `shepherd_<role>_<node>` (`hooks/protocol.py`
//      `TASK_NAME_PATTERN`) -- confirmed working via that package's own e2e-tested
//      `tests/gate/test_governance.py` assertions and `/private/tmp/codex-shepherd-subagent-e2e-*`
//      fixture directories recorded in `~/.codex/config.toml`.
//   3. `strings /opt/homebrew/bin/codex` (the installed `codex-cli 0.147.0` binary itself)
//      embeds `agent_id`, `agent_type`, `agent_transcript_path`, and a
//      `codex.multi_agent.spawn` field set (`agent_type`, `reasoning_effort`,
//      `fork_context`, `agent_id`, `nickname`) as real wire-model fields, plus
//      `PostToolUseCommandOutputWire` / `tool_response` -- both independently present in the
//      shipped binary, not inferred from either external source above.
//
// `# @<role>` header parsing (mirrors agent_invocation_tagger.sh's own regex) is kept as a
// SECOND signal, tried only when `task_name` does not carry the `shepherd_<role>_<node>`
// shape -- content/roles/*.md is this repo's own source of truth for role identity, not the
// sibling package's task_name grammar, so a dispatch that only sets `message`/`prompt` still
// resolves.

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";

/** Codex's two known spawn-primitive tool names -- `spawn_agent` is the confirmed-live
 * MultiAgentV2 tool (`developers.openai.com/codex/config-reference`, `strings` on the
 * installed binary); `collaborationspawn_agent` is kept for parity with the installed
 * `codex-shepherd@1.0.2` sibling's own matcher and this package's pre-existing module
 * header, which already named both. */
const SPAWN_TOOL_NAMES = Object.freeze(new Set(["spawn_agent", "collaborationspawn_agent"]));

const TASK_NAME_ROLE_RE = /^shepherd_([a-z][a-z0-9]*)_/;
const MESSAGE_ROLE_RE = /^#\s*@([a-z][a-z0-9-]*)\b/m;

/** @param {string} toolName @returns {boolean} */
export function isSpawnTool(toolName) {
  return SPAWN_TOOL_NAMES.has(toolName);
}

/**
 * Parse the role a dispatcher intended for a `spawn_agent`/`collaborationspawn_agent`
 * call, trying `tool_input.task_name`'s `shepherd_<role>_<node>` shape first (the
 * confirmed-live community convention -- see module header source 1), then a `# @<role>`
 * header in the first 100 lines of `tool_input.message`/`.prompt` (mirrors
 * agent_invocation_tagger.sh's own parse). `"unknown"` when neither resolves -- written to
 * the record as-is, never omitted, so a read later always finds a record (module header:
 * "no two-phase pending/commit state needed") and the deny path stays the specific
 * "no such role" case rather than the louder "no record at all" one.
 *
 * @param {Record<string, unknown>|undefined} toolInput
 * @returns {string}
 */
export function parseIntendedRole(toolInput) {
  const input = toolInput && typeof toolInput === "object" ? toolInput : {};
  const taskName = typeof input.task_name === "string" ? input.task_name : "";
  const fromTaskName = TASK_NAME_ROLE_RE.exec(taskName);
  if (fromTaskName) return fromTaskName[1];

  const message = typeof input.message === "string" ? input.message : typeof input.prompt === "string" ? input.prompt : "";
  const head = message.split("\n").slice(0, 100).join("\n");
  const fromMessage = MESSAGE_ROLE_RE.exec(head);
  return fromMessage ? fromMessage[1] : "unknown";
}

/**
 * Codex's `spawn_agent` tool response carries the runtime-assigned agent identity, either
 * as a JSON string or an already-parsed object (mirrors the installed
 * `codex-shepherd@1.0.2`'s own `response_document`/`spawn_response_agent_id`, which probes
 * both `agent_id` and `id` -- the binary's own `codex.multi_agent.spawn` field set confirms
 * `agent_id`; `id` is kept as a defensive fallback name, never assumed alone).
 *
 * @param {unknown} toolResponse
 * @returns {string|null}
 */
export function extractAgentId(toolResponse) {
  let doc = toolResponse;
  if (typeof doc === "string") {
    try {
      doc = JSON.parse(doc);
    } catch {
      return null;
    }
  }
  if (!doc || typeof doc !== "object") return null;
  const id = doc.agent_id ?? doc.id;
  return typeof id === "string" && id ? id : null;
}

/** Repo root: walk up from `startDir` for a `.git` entry (dir or file -- a worktree's
 * `.git` is a file), falling back to `startDir` itself when none is found. Deliberately
 * dependency-free (no `git` subprocess) -- this runs on every guarded PreToolUse call. */
function findRepoRoot(startDir) {
  let dir = startDir;
  for (;;) {
    if (existsSync(join(dir, ".git"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return startDir;
    dir = parent;
  }
}

/**
 * The namespace directory Codex dispatch records live under -- mirrors
 * `hooks/scripts/_lib.sh`'s `resolve_namespace` precedence (`SHEPHERD_WORKDIR` ->
 * `SHCTX_ROOT_OVERRIDE` -> an existing `.shepherd`/`.artifacts` -> default `.shepherd`),
 * ported to Node rather than shared with it (that function is bash, not requireable here).
 *
 * @param {string} [cwd]
 * @returns {string}
 */
export function resolveDataDir(cwd = process.cwd()) {
  const repoRoot = findRepoRoot(cwd);
  const workdir = process.env.SHEPHERD_WORKDIR;
  if (workdir) return isAbsolute(workdir) ? workdir : join(repoRoot, workdir);
  const override = process.env.SHCTX_ROOT_OVERRIDE;
  if (override) return join(repoRoot, override);
  for (const candidate of [".shepherd", ".artifacts"]) {
    const path = join(repoRoot, candidate);
    if (existsSync(path)) return path;
  }
  return join(repoRoot, ".shepherd");
}

/** `agent_id` is Codex-runtime-assigned, not shepherd-controlled -- hash it before it ever
 * touches a filename so no value that reaches here can path-traverse. */
function recordPath(dataDir, agentId) {
  const key = createHash("sha256").update(agentId).digest("hex");
  return join(dataDir, "dispatch", "codex", `${key}.json`);
}

/**
 * Write the dispatch record a later `resolveRole` read keys on. Always called with a role
 * (possibly `"unknown"` -- see `parseIntendedRole`), never skipped, so DF-75's "record
 * missing" deny path stays reserved for a dispatch this hook never observed at all.
 *
 * @param {string} dataDir
 * @param {string} agentId
 * @param {string} role
 * @returns {{agent_id: string, agent_role: string, recorded_at: number}}
 */
export function writeDispatchRecord(dataDir, agentId, role) {
  const path = recordPath(dataDir, agentId);
  mkdirSync(dirname(path), { recursive: true });
  const record = { agent_id: agentId, agent_role: role, recorded_at: Date.now() / 1000 };
  writeFileSync(path, `${JSON.stringify(record)}\n`, "utf8");
  return record;
}

/**
 * @param {string} dataDir
 * @param {string} agentId
 * @returns {{agent_id: string, agent_role: string, recorded_at: number}|null} `null` on a
 *   missing OR corrupt record -- both are DF-75's "record missing" case; a partially-written
 *   or unreadable record must never be treated as a resolved role.
 */
export function readDispatchRecord(dataDir, agentId) {
  const path = recordPath(dataDir, agentId);
  if (!existsSync(path)) return null;
  try {
    const record = JSON.parse(readFileSync(path, "utf8"));
    return record && typeof record.agent_role === "string" ? record : null;
  } catch {
    return null;
  }
}

/**
 * PostToolUse(spawn_agent|collaborationspawn_agent) handler: extract the assigned
 * `agent_id` from the response and the intended role from the original request, then write
 * the record in one shot. Returns `null` (no-op) when Codex reported no agent id at all --
 * nothing to key a record on, so DF-75's "marker present, record missing" deny is exactly
 * what a later call from that (never-identified) agent will hit.
 *
 * @param {{toolInput?: unknown, toolResponse?: unknown, dataDir: string}} args
 * @returns {{agent_id: string, agent_role: string, recorded_at: number}|null}
 */
export function recordSpawnDispatch({ toolInput, toolResponse, dataDir }) {
  const agentId = extractAgentId(toolResponse);
  if (!agentId) return null;
  const role = parseIntendedRole(toolInput);
  return writeDispatchRecord(dataDir, agentId, role);
}

/**
 * The three-way DF-75 role resolution: no marker (root/operator session, never dispatched)
 * -> `"no-marker"`; a marker with a resolved record -> `"resolved"`; a marker with no
 * record at all -> `"missing-record"` (the regression case this whole module exists to
 * close -- previously a silent allow).
 *
 * @param {string|null|undefined} agentId `PreToolUse` payload's own `agent_id` field.
 * @param {string} dataDir
 * @returns {{kind: "no-marker"}|{kind: "resolved", role: string, agentId: string}|{kind: "missing-record", agentId: string}}
 */
export function resolveRole(agentId, dataDir) {
  if (typeof agentId !== "string" || !agentId) return { kind: "no-marker" };
  const record = readDispatchRecord(dataDir, agentId);
  if (!record) return { kind: "missing-record", agentId };
  return { kind: "resolved", role: record.agent_role, agentId };
}
