// packages/harness-pi/src/guard-client.ts -- spawns `bin/shepherd guard serve` ONCE and
// relays every guard check to it over line-delimited JSON on stdio (S2-guard-serve, DF-76).
// Replaces src/guard.ts's local predicate interpreter (C1-pi-collapse): the local port is
// gone, this is the one interpreter of content/predicates/*.toml Pi's guard layer defers to
// now, the same engine Claude/Codex's adapters already relay to
// (services/cli/shepherd_cli/predicates.py, via services/cli/shepherd_cli/commands/guard.py).
//
// W10-B2-pi HALTED on this collapse measuring `bin/shepherd guard eval` (one subprocess per
// call) at 150-600ms/call against a handler it believed had to run synchronously, in-process.
// Both premises no longer hold: `guard serve` loads the engine once and answers a warmed
// request in ~0.03-0.1ms (measured live, this repo -- see this step's CODER REPORT), and
// src/pi-types.ts's header shows the `tool_call` handler was never actually synchronous-only
// -- Pi's real installed 0.84.1 types/runtime support and genuinely await an async handler.
// One consequence of that second fact drives this file's design: `docs/extensions.md`
// guarantees "sibling tool calls from the same assistant message are preflighted
// sequentially, then executed concurrently", so exactly one guard request is ever in flight
// per session -- a serialized request queue against one child process is correct by
// construction, never a race, and needs no per-request correlation id.
//
// Fails CLOSED, matching every other guard decision in this package: a `guard serve` that
// never starts, dies mid-session, or answers with anything other than a clean allow/deny
// verdict produces `{allow: false, ...}`, never a silent allow (content/RECONCILIATION.md's
// "an unenforceable-by-omission guard is exactly the silent-non-enforcement defect" bar).

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

export type PredicateId = "dedup-gate" | "dispatch-scope" | "git-custody" | "write-boundary";

export interface GuardCheck {
  predicateId: PredicateId;
  role: string;
  action: string;
  context: Record<string, unknown>;
}

export interface GuardVerdict {
  allow: boolean;
  haltCode?: string;
  reason: string;
}

/** `guard serve`'s per-line JSON response shape (services/cli/shepherd_cli/predicates.py `Verdict.to_json`), plus the `{error}` shape a malformed request line gets. */
interface ServeResponse {
  decision?: "allow" | "deny" | "unresolved";
  predicate?: string;
  rule?: string;
  halt_code?: string;
  reason?: string;
  missing?: string[];
  error?: string;
}

function toVerdict(response: ServeResponse): GuardVerdict {
  if (response.decision === "allow") return { allow: true, reason: "guard engine allowed" };
  if (response.decision === "deny") {
    return { allow: false, haltCode: response.halt_code, reason: response.reason ?? "guard engine denied with no reason given" };
  }
  // "unresolved" (missing role/predicate/context) and a malformed-line `{error}` both fail
  // closed here -- neither is a real allow, and treating either as one would be exactly the
  // silent-non-enforcement defect this guard layer exists to prevent.
  return {
    allow: false,
    reason: response.error ?? response.reason ?? `guard engine returned an unrecognized verdict: ${JSON.stringify(response)}`,
  };
}

/** A minimal async line channel over a child's stdout -- buffers eagerly so no `line` event can arrive before a reader is waiting for it. */
class LineChannel {
  #buffered: string[] = [];
  #waiters: Array<(line: string | undefined) => void> = [];
  #closed = false;

  constructor(child: ChildProcessWithoutNullStreams) {
    createInterface({ input: child.stdout }).on("line", (line: string) => this.#push(line));
    child.once("close", () => this.#end());
  }

  #push(line: string): void {
    const waiter = this.#waiters.shift();
    if (waiter) waiter(line);
    else this.#buffered.push(line);
  }

  #end(): void {
    this.#closed = true;
    while (this.#waiters.length > 0) this.#waiters.shift()?.(undefined);
  }

  next(): Promise<string | undefined> {
    if (this.#buffered.length > 0) return Promise.resolve(this.#buffered.shift());
    if (this.#closed) return Promise.resolve(undefined);
    return new Promise((resolve) => this.#waiters.push(resolve));
  }
}

/** One live `shepherd guard serve` child process, plus a serialized request queue against it. */
export class GuardClient {
  readonly #child: ChildProcessWithoutNullStreams;
  readonly #lines: LineChannel;
  #pending: Promise<unknown> = Promise.resolve();
  #deathReason: string | undefined;

  private constructor(child: ChildProcessWithoutNullStreams, lines: LineChannel) {
    this.#child = child;
    this.#lines = lines;
    child.once("exit", (code, signal) => {
      this.#deathReason ??= `guard serve exited (code=${code ?? "null"}, signal=${signal ?? "null"})`;
    });
    // Never let an unconsumed stderr pipe block the child, and never swallow a real crash
    // reason -- surfacing it is strictly better than the silence a synchronous local
    // interpreter never had to account for.
    child.stderr.on("data", (chunk: Buffer) => process.stderr.write(`[guard serve] ${chunk}`));
  }

  /**
   * Spawns `<repo>/bin/shepherd guard serve` and resolves once its ready line is read, so no
   * `tool_call` can race an engine that has not finished loading `content/predicates/`.
   *
   * @param shepherdBin absolute path to `bin/shepherd`.
   * @param contentDir absolute path to `content/`, forwarded as `--content-dir`.
   * @throws if the process exits, or answers anything other than the ready sentinel, before
   *   ever printing a usable first line.
   */
  static async spawn(shepherdBin: string, contentDir: string): Promise<GuardClient> {
    const child = spawn(shepherdBin, ["guard", "serve", "--content-dir", contentDir], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    const lines = new LineChannel(child);
    const first = await lines.next();
    if (first === undefined) {
      throw new Error(`guard serve exited before printing a ready line (spawned \`${shepherdBin} guard serve\`)`);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(first);
    } catch (err) {
      throw new Error(`guard serve's first line was not JSON: ${first} (${String(err)})`);
    }
    if (!(typeof parsed === "object" && parsed !== null && (parsed as { ready?: unknown }).ready === true)) {
      throw new Error(`guard serve's first line was not the ready sentinel: ${first}`);
    }
    return new GuardClient(child, lines);
  }

  /** Evaluates one check against the live engine. Requests are serialized -- see module header for why that is always sufficient for this event, never a bottleneck. */
  evaluate(check: GuardCheck): Promise<GuardVerdict> {
    const run = this.#pending.then(() => this.#evaluateOne(check));
    // A rejected request must never poison the queue for the next caller.
    this.#pending = run.catch(() => undefined);
    return run;
  }

  async #evaluateOne(check: GuardCheck): Promise<GuardVerdict> {
    if (this.#deathReason) {
      return { allow: false, reason: `guard engine unavailable, failing closed: ${this.#deathReason}` };
    }
    const request = { harness: "pi", predicate: check.predicateId, action: check.action, role: check.role, context: check.context };
    this.#child.stdin.write(`${JSON.stringify(request)}\n`);
    const line = await this.#lines.next();
    if (line === undefined) {
      this.#deathReason ??= "guard serve closed its output stream without a response";
      return { allow: false, reason: `guard engine unavailable, failing closed: ${this.#deathReason}` };
    }
    try {
      return toVerdict(JSON.parse(line));
    } catch (err) {
      return { allow: false, reason: `guard engine's response line was not JSON: ${line} (${String(err)})` };
    }
  }

  /** Closes stdin so `guard serve` exits on its own documented EOF contract; never orphans it. */
  close(): void {
    this.#child.stdin.end();
  }
}
