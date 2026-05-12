# Use MCPs for writes; CLIs for read-only enumeration

Whenever an MCP exists for a service, use the MCP for any write operation against that service. CLIs (gh, fly, etc.) are fine for read-only enumeration when the MCP would be overkill, but writes go through the MCP.

## Why

- **Tool-call audit trail** — MCP calls are first-class tool calls in the agent's transcript. CLI calls run inside Bash and lose that structure.
- **Schema enforcement** — MCP tools have JSON schemas the agent honors. CLIs accept free-form text and silently mishandle whitespace, escaping, multiline bodies.
- **Permission model** — MCPs are bound to the user's MCP credentials. CLIs use whatever auth the host shell has, which may be a different account.
- **Idempotency** — well-built MCPs surface "already exists" / "no change" cleanly. CLI exit codes are inconsistent.

## Service-by-service

| Service | Use MCP for | CLI is OK for |
|---|---|---|
| GitHub | Issue create/update/comment, PR create/comment, label apply, milestone manage, releases | `gh issue list`, `gh pr list`, `gh repo view` (read-only enumeration when MCP is overkill) |
| Sentry | (read-only via MCP) | n/a |
| Supabase / Postgres | Schema queries, advisor checks, migration apply, table inspection | Read-only `psql` if MCP unavailable |
| Fly | Use `fly` CLI (no MCP) | All Fly ops |
| Datadog / Grafana | If MCP available, use MCP for queries | CLI for streaming logs |

## Specific to GitHub

The most common write operations agents perform:

```
# Issue creation — through MCP
mcp__plugin_github_github__issue_write({ ... })

# Label application — through MCP
mcp__plugin_github_github__issue_write({ action: "update", labels: [...] })

# PR comment — through MCP
mcp__plugin_github_github__add_issue_comment({ ... })
```

The CLI equivalents (`gh issue create`, `gh issue edit`, `gh pr comment`) work but bypass the structured-tool path. Agent transcripts become noisier and audit-finding correlation breaks.

## Read-only enumeration

For bulk read enumeration where the MCP would issue 200 round-trips, the CLI is preferred:

```bash
# Bulk-list 500 open issues for Phase 0 mesh ledger sweep
gh issue list --state open --limit 500 --json number,title,milestone,labels

# Walk recent commits
git log v0.2.9..HEAD --oneline | head -20

# Inspect Fly machine state (substitute your app)
fly status --app <your-app>
```

These don't write anything. They're cheaper as one CLI call than as 500 MCP calls.

## When neither MCP nor CLI is available

The conductor configures `[mcp]` and `[cli]` in `shepherd.toml`. If a service is `false` in both, the corresponding mesh row is downgraded ("Sentry mesh — if available, query; if neither available, mark mesh row N/A and continue").

## Anti-patterns

- **"I'll use `gh issue create` because it's faster to type"** — wrong; the MCP call IS faster (no shell overhead) and structured.
- **"The MCP doesn't have feature X yet, so I'll use the CLI"** — OK if X is genuinely missing, but file an issue to track adding X to the MCP.
- **"I'll wrap the CLI call in Bash so it counts as 'using a tool'"** — process violation; the structured-tool layer exists for a reason.

## See also

- `auditor-readonly.md` — auditors use MCP read-only queries
- `issue-ledger-awareness.md` — Phase 0 mesh ledger sweep uses CLI for the bulk enumeration
