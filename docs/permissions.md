# Permissions — running shepherd in auto mode without the friction

Shepherd drives many subagent and teammate tool calls. In Claude Code's **auto
mode** (the recommended posture for a long sprint), each of those calls is
evaluated by the permission classifier. This page explains the one friction
that surfaces — the "permission laundering" callout — and the supported way to
remove it. There is no jailbreak here, and you never need
`--dangerously-skip-permissions` or `bypassPermissions`.

## What "permission laundering" is

When one agent relays an approval to another — a teammate telling a peer "the
lead already approved this" — auto mode treats that relayed approval as
**untrusted input, not consent from you**. From the
[Agent Teams docs](https://code.claude.com/docs/en/agent-teams#permissions):

> A teammate cannot approve a permission prompt or supply consent on your
> behalf, and a teammate that was denied an action cannot relay it to another
> teammate to bypass the check. In auto mode, the classifier treats an approval
> claim relayed from another agent as untrusted input rather than confirmation
> from you.

That guardrail is **working as designed** — it is what stops a subagent from
escalating its own privileges. It is not a bug, and it is not something to
route around. What it means in practice: a teammate's tool call is authorized
by *your* permission rules, never by another agent's say-so. So the fix is to
make sure the calls shepherd makes routinely are already in your allow rules —
then no relay, and no prompt, is ever needed.

## The fix: a permissions allowlist

Add shepherd's routine, read-only calls to `permissions.allow` in your
`settings.json`. Pre-approved calls run without a prompt and without ever
touching the cross-agent-relay path. Everything else still prompts (in
interactive auto mode) or follows your configured rules (in `claude -p`).

```json
{
  "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" },
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(bin/shepherd:*)",
      "Bash(shepherd:*)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(git log:*)",
      "Bash(git show:*)",
      "Bash(git rev-parse:*)",
      "Bash(git worktree list:*)",
      "Bash(git branch:*)",
      "Read(*)",
      "Grep(*)",
      "Glob(*)"
    ]
  }
}
```

Notes:

- **`bin/shepherd` / `shepherd`** cover the CLI (registry reads, dedup checks,
  liveness, dashboards). They are the read/inspect surface every brief and gate
  leans on, so pre-approving them removes the bulk of the prompts.
- **`git status`/`diff`/`log`/`show`/`rev-parse`/`worktree list`/`branch`** are
  the read-only git calls root uses to verify `WAVE-COMPLETE` and probe lane
  drift. They mutate nothing.
- **`Read`/`Grep`/`Glob`** are always safe to allow — they never write.
- **Do NOT** blanket-allow `Bash(git commit:*)`, `Bash(git push:*)`, or
  `Bash(git rebase:*)`. Git custody is deliberately gated; leave those to
  prompt so an unexpected integration always surfaces.
- MCP verbs (GitHub, Sentry, Supabase) are **not** listed here on purpose:
  shepherd discovers them at runtime and the exact tool name depends on your
  provider (native, Composio, a gateway). Add the specific read verbs your
  provider exposes — e.g. `mcp__github__list_issues` — if you want those
  pre-approved too.

## What not to do

- **Do not** set `defaultMode: "bypassPermissions"` or launch with
  `--dangerously-skip-permissions` to silence the callout. That disables the
  guardrail for *every* call, not just shepherd's, and removes the protection
  the "permission laundering" check exists to provide.
- **Do not** try to have one agent approve on another's behalf. It cannot, by
  design; the allowlist above is the supported path.

See [`docs/configuration.md`](configuration.md) for `shepherd.toml`, and the
[Install](../README.md#install) note for `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`.
