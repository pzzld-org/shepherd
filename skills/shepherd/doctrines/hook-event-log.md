# Hook event log — operator-visible record of what hooks fire

> Origin: v5.1.1 (2026-05-15). Hooks fire silently by design; when the
> operator wants to debug "did the hook block X" or "why did my dispatch
> pause", the only signal is the additionalContext message. The event log
> persists the same data structurally so post-hoc inspection is possible.

## What it is

Every hook fire appends one line to `<ns>/logs/hooks/YYYY-MM-DD.jsonl`. One
file per day; gitignored.

`<ns>` is `.shepherd/` (default) or `.artifacts/` (legacy namespace).

## Schema

```json
{
  "ts": "2026-05-15T14:23:11.243Z",
  "hook": "bash_guard",
  "decision": "deny|warn|pass",
  "tool": "Bash|Write|Edit|Agent|Task|Session",
  "role": "discovery|worker|coder|auditor|critic|engineer|conductor|unknown",
  "session_id": "<from hook input>",
  "fields": {
    "cmd": "<truncated to 200 chars; null for non-Bash>",
    "path": "<for Write/Edit; null otherwise>",
    "reason": "<human-readable explanation of the decision>",
    "rule": "<doctrine reference, e.g. conductor-cwd.md §Ban 2>"
  }
}
```

### Field definitions

- **ts** — ISO-8601 UTC timestamp, millisecond resolution
- **hook** — basename of the hook script (without `.sh`)
- **decision** — `deny` (PreToolUse only — tool denied), `warn`
  (additionalContext emitted, tool proceeded), `pass` (silent exit 0)
- **tool** — which Claude tool fired the hook
- **role** — which flock role is acting (from
  `agent_invocation_tagger.sh` correlation); `conductor` if main chat,
  `unknown` if the tagger hasn't seen this tool_use_id
- **session_id** — the session ID Claude provides in the hook input
- **fields** — hook-specific payload

### Decision semantics

- **deny** — fires from `bash_guard.sh` and `lock_guard.sh` when they emit
  `{"permissionDecision":"deny",...}`
- **warn** — fires from any hook that emits `{"additionalContext":...}`
  (Surfaces a warning but lets the tool proceed)
- **pass** — fires from any hook that exits 0 silently (no JSON emitted)

## Operator queries

### "What did bash_guard deny today?"

```bash
jq 'select(.hook == "bash_guard" and .decision == "deny")' \
  .shepherd/logs/hooks/$(date +%Y-%m-%d).jsonl
```

### "Did any discovery agent try to write outside its sandbox?"

```bash
jq 'select(.role == "discovery" and .decision == "deny" and .hook == "lock_guard")' \
  .shepherd/logs/hooks/*.jsonl
```

### "Show all PAUSE-FOR-DEPENDENCY captures this week"

```bash
jq 'select(.hook == "agent_pause_detector" and .decision == "warn")' \
  .shepherd/logs/hooks/2026-05-*.jsonl | head -20
```

### "How many auditor cwd-drift blocks fired this sprint?"

```bash
jq -r 'select(.hook == "bash_guard" and .role == "auditor" and .decision == "deny" and .fields.rule | contains("WORKTREE-DRIFT"))' \
  .shepherd/logs/hooks/*.jsonl | wc -l
```

## Retention

No automated rotation. Operators manage manually:

```bash
# Keep last 30 days
find .shepherd/logs/hooks/ -name "*.jsonl" -mtime +30 -delete
```

The files are append-only and small (< 1 MB per active day typically), so
retention is forgiving.

## Gitignore

Add to `.gitignore` at the project root:

```
.shepherd/logs/hooks/
.artifacts/logs/hooks/   # legacy namespace
```

The framework also handles this in `examples/minimal/.gitignore` and
`examples/axiom/.gitignore`.

## Implementation

The shared hook library `hooks/scripts/_lib.sh` exports a `log_event()`
function every hook calls before its first JSON emit (or before `exit 0`
for silent passes):

```bash
log_event "$HOOK_NAME" "$DECISION" "$TOOL" "$ROLE" "$SESSION_ID" "$FIELDS_JSON"
```

The function:
1. Resolves `<ns>` (`.shepherd/` or `.artifacts/`)
2. Creates `<ns>/logs/hooks/` if absent
3. Appends the JSON entry to `YYYY-MM-DD.jsonl`
4. Errors silently (`>/dev/null 2>&1`) — log failures must NOT block hooks

## Integration with shctx

`shctx doctor` reads the log to verify hooks are firing as expected:

```
[HOOKS]
  ✓ 8 hooks active (session_open, bash_guard, ...)
  ✓ Event log: 47 entries today (15 deny, 8 warn, 24 pass)
  ⚠ session_open hook hasn't fired this session — plugin reload may be stale
```

## Anti-patterns

1. **Tailing the log live during a sprint.** Don't. The log is post-hoc
   inspection material; live monitoring belongs in operator-visible
   additionalContext (which is what the hook already emits).
2. **Logging large payloads.** Truncate `fields.cmd` to 200 chars. Long
   commands fragment the JSONL parser and bloat the file. The truncation
   is in `_lib.sh`.
3. **Logging secrets.** Hook input may include `tool_input` with env vars.
   The library MUST scrub anything that looks like a token / key / password
   pattern before logging.
4. **Logging on every Read.** PostToolUse fires on every tool. Log only
   for events that carry signal (deny + warn always; pass for tools we
   want telemetry on — Bash + Write + Edit + Agent). Other PostToolUse
   passes exit silently without logging.

## See also

- `hooks/hooks.json` — registered hooks (per-event matchers)
- `hooks/scripts/_lib.sh` — shared library exporting `log_event()`
- `skills/context/scripts/cmd_doctor.sh` — preflight that reads the log
- `doctrines/preflight-doctor.md` — when to run `shctx doctor`
