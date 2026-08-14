// packages/harness-claude/src/guard-serve-engine.mjs -- one live `bin/shepherd guard serve`
// child process, plus a serialized request queue against it (T2-serve-wiring). SHARED between
// packages/harness-claude and packages/harness-codex -- consumed indirectly by
// packages/harness-codex (via guard-serve-broker.mjs, cross-imported from
// packages/harness-codex/hooks/scripts/shepherd_guard.mjs and its own test/ suite) exactly the
// way packages/harness-codex/src/materialize.mjs already imports ../../compiler/src/compile.mjs;
// this is not a new precedent.
//
// Ported from packages/harness-pi/src/guard-client.ts's `GuardClient`/`LineChannel` -- same
// spawn/ready-line/serialized-queue/sticky-death shape, deliberately NOT imported directly:
// harness-pi declares `"engines": {"node": ">=22.6.0"}` and runs its tests with
// `node --experimental-strip-types` because `guard-client.ts` is TypeScript; harness-claude and
// harness-codex both declare `"engines": {"node": ">=20"}` and their real hook entrypoints are
// invoked directly by the host CLI as `node <script>.mjs` with no type-stripping flag (that
// command line is `hooks/hooks.json`'s / `buildGuardHooksEntry()`'s own contract, not something
// this step owns) -- importing pi's `.ts` file here would silently require raising that public
// engines contract for both packages, a change this step's file scope does not license. See this
// step's CODER REPORT assumptions.
//
// ONE behavioral difference from pi's `GuardClient`, deliberate: pi's `evaluate()` returns a
// translated `{allow, haltCode, reason}` `GuardVerdict` because pi's own extension only ever
// needs a boolean. Claude's and Codex's `interpretEngineResult()` (packages/harness-claude/src/
// guard.mjs, packages/harness-codex/src/guard.mjs) already parse the RAW engine verdict shape
// (`{decision, predicate, rule, halt_code, reason}`) into two DIFFERENT wire shapes (Claude's
// flat `{permissionDecision}`, Codex's nested `{hookSpecificOutput}`) -- collapsing that
// distinction inside this transport would either lose it or force a third, unified shape neither
// harness actually emits. So `evaluate()` here returns a transport-envelope
// `{ok: true, engineResult: <raw parsed line>} | {ok: false, detail: <string>}`: the raw engine
// JSON passes through untouched on success, exactly what `interpretEngineResult()` already
// expects, and every transport-level failure (dead child, malformed line, an `{"error":...}`
// line from `guard serve`'s own `_malformed_line_response`) collapses to the SAME `{ok:false,
// detail}` shape `guard-serve-client.mjs` also uses for connection-level failures -- one envelope,
// one place each caller has to branch on it.

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

/**
 * A minimal async line channel over a child's stdout -- buffers eagerly so no `line` event can
 * arrive before a reader is waiting for it. Verbatim port of
 * packages/harness-pi/src/guard-client.ts's `LineChannel`.
 */
class LineChannel {
  #buffered = [];
  #waiters = [];
  #closed = false;

  constructor(child) {
    createInterface({ input: child.stdout }).on("line", (line) => this.#push(line));
    child.once("close", () => this.#end());
  }

  #push(line) {
    const waiter = this.#waiters.shift();
    if (waiter) waiter(line);
    else this.#buffered.push(line);
  }

  #end() {
    this.#closed = true;
    while (this.#waiters.length > 0) this.#waiters.shift()?.(undefined);
  }

  next() {
    if (this.#buffered.length > 0) return Promise.resolve(this.#buffered.shift());
    if (this.#closed) return Promise.resolve(undefined);
    return new Promise((resolve) => this.#waiters.push(resolve));
  }
}

/**
 * One live `shepherd guard serve` child process, plus a serialized request queue against it.
 * Sticky-dead once the child exits or its stdout closes: EVERY subsequent `evaluate()` call for
 * the rest of this instance's life returns `{ok:false,...}`, matching
 * packages/harness-pi/src/guard-client.ts's `GuardClient` -- an engine crash never gets a silent
 * auto-retry mid-instance; a fresh instance (`GuardServeEngine.spawn()` again) is the only way
 * back to a live engine. `packages/harness-claude/src/guard-serve-broker.mjs` owns deciding what
 * to do with a now-permanently-dead instance (tear the broker down so the NEXT client spawns a
 * fresh one, rather than deny for the rest of an idle-timeout window).
 */
export class GuardServeEngine {
  #child;
  #lines;
  #pending = Promise.resolve();
  #deathReason;

  constructor(child, lines) {
    this.#child = child;
    this.#lines = lines;
    child.once("exit", (code, signal) => {
      this.#deathReason ??= `guard serve exited (code=${code ?? "null"}, signal=${signal ?? "null"})`;
    });
    child.stderr.on("data", (chunk) => process.stderr.write(`[guard serve] ${chunk}`));
    // A request can race the child's death: `#evaluateOne` checks `#deathReason` before writing,
    // but that flag is only set once the `exit` event has actually landed, so a write against a
    // pipe whose other end JUST closed can still hit the wire first. Node's writable streams
    // raise a broken-pipe write as an ASYNC `error` event, and an EventEmitter's default behavior
    // for an `error` event with no listener is to throw -- unhandled, that would crash this
    // entire broker process (every OTHER in-flight/queued request along with it), which is
    // strictly worse than the fail-closed answer this class already owes every caller. This
    // listener's only job is to make sure that never happens; `#evaluateOne`'s own catch around
    // `stdin.write` (below) is what actually turns THIS request into a `{ok:false}` reply.
    child.stdin.on("error", () => {
      this.#deathReason ??= "guard serve's stdin closed (engine unavailable)";
    });
  }

  /** @returns {string|undefined} set once the underlying child has died; undefined while live. */
  get deathReason() {
    return this.#deathReason;
  }

  /** @returns {number|undefined} the live `guard serve` child's pid -- precise cleanup/probing
   *   (e.g. tests killing exactly this engine, never a same-named sibling from a concurrently
   *   running test file) without guessing via a process-table search. */
  get pid() {
    return this.#child.pid;
  }

  /**
   * Spawns `<repo>/bin/shepherd guard serve` and resolves once its ready line is read.
   * @param {string} shepherdBin absolute path to `bin/shepherd`.
   * @param {string} contentDir absolute path to `content/`, forwarded as `--content-dir`.
   * @returns {Promise<GuardServeEngine>}
   * @throws if the process exits, or answers anything other than the ready sentinel, before
   *   ever printing a usable first line.
   */
  static async spawn(shepherdBin, contentDir) {
    const child = spawn(shepherdBin, ["guard", "serve", "--content-dir", contentDir], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    const lines = new LineChannel(child);
    const first = await lines.next();
    if (first === undefined) {
      throw new Error(`guard serve exited before printing a ready line (spawned \`${shepherdBin} guard serve\`)`);
    }
    let parsed;
    try {
      parsed = JSON.parse(first);
    } catch (err) {
      throw new Error(`guard serve's first line was not JSON: ${first} (${String(err)})`);
    }
    if (!(typeof parsed === "object" && parsed !== null && parsed.ready === true)) {
      throw new Error(`guard serve's first line was not the ready sentinel: ${first}`);
    }
    return new GuardServeEngine(child, lines);
  }

  /**
   * Evaluates one guard request against the live engine. Requests are serialized against the
   * single child -- correct for any number of concurrent callers (multiple socket connections in
   * `guard-serve-broker.mjs` included): each request is computed fresh, from scratch, in the
   * order it was queued, and a rejected/failed request never poisons the queue for the next
   * caller. No verdict is ever cached or reused across two different requests.
   * @param {Record<string, unknown>} payload shape-(a) `{predicate, action, role, context}` or
   *   shape-(b) `{tool_name, tool_input, role}` -- `services/cli/shepherd_cli/predicates.py`'s
   *   `Engine.evaluate()` dispatches on which keys are present; this class never inspects it.
   * @returns {Promise<{ok: true, engineResult: Record<string, unknown>} | {ok: false, detail: string}>}
   */
  evaluate(payload) {
    const run = this.#pending.then(() => this.#evaluateOne(payload));
    this.#pending = run.catch(() => undefined);
    return run;
  }

  async #evaluateOne(payload) {
    if (this.#deathReason) {
      return { ok: false, detail: this.#deathReason };
    }
    try {
      this.#child.stdin.write(`${JSON.stringify(payload)}\n`);
    } catch (err) {
      this.#deathReason ??= `guard serve's stdin rejected a write: ${String(err)}`;
      return { ok: false, detail: this.#deathReason };
    }
    const line = await this.#lines.next();
    if (line === undefined) {
      this.#deathReason ??= "guard serve closed its output stream without a response";
      return { ok: false, detail: this.#deathReason };
    }
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (err) {
      return { ok: false, detail: `guard engine's response line was not JSON: ${line} (${String(err)})` };
    }
    // `guard serve`'s own `_malformed_line_response` shape for a request line it could not
    // evaluate -- the process is fine, but this ONE line failed; that is a transport/engine
    // failure for THIS request, not a real verdict, so it collapses to the same `{ok:false}`
    // envelope an unreachable engine produces rather than being handed to `interpretEngineResult`
    // as if it were a fourth decision kind.
    if (parsed && typeof parsed === "object" && typeof parsed.error === "string") {
      return { ok: false, detail: `guard engine reported an error: ${parsed.error}` };
    }
    return { ok: true, engineResult: parsed };
  }

  /** Closes stdin so `guard serve` exits on its own documented EOF contract; never orphans it. */
  close() {
    this.#child.stdin.end();
  }
}
