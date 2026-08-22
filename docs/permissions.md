# Permissions and host boundaries

Shepherd does not broaden a harness's permissions. The native CLI and each
adapter fail closed when a required engine, identity, provider, or host bridge
is missing. Configure the host to allow the routine commands you intend to run;
do not disable its permission system globally.

## Claude Code

Claude Code's Agent Teams and hook permissions are host settings. If Agent Teams
is enabled, Shepherd can use the host's teammate primitive, but a teammate
cannot approve a permission request for another teammate. An approval claim in
agent text is not operator consent.

A narrow read-oriented allowlist can cover the canonical CLI and inspection
tools. Adjust it to the host version and project policy:

```json
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(shepherd:*)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(git log:*)",
      "Bash(git show:*)",
      "Bash(git rev-parse:*)",
      "Read(*)",
      "Grep(*)",
      "Glob(*)"
    ]
  }
}
```

Do not blanket-allow `git commit`, `git push`, `git rebase`, arbitrary shell,
or a permission-bypass mode. Run custody remains an explicit operator or root
workflow decision.

## Codex

The Codex adapter receives host hook envelopes and translates them to the typed
component boundary. The host must supply the identity and lifecycle facts that
the event claims. Missing facts produce an unresolved or blocked result; the
adapter does not infer them from an environment variable or a private Claude
directory.

The installed native `shepherd` command must be on `PATH`, or the embedding
host must provide `SHEPHERD_NATIVE_BIN`. A missing binary is an adapter error,
not a reason to invoke Python, Bash, or Node.

## Pi

Pi requires a compatible registered subagent system. At root and child
`session_start`, Shepherd uses Pi's public `pi.getAllTools()` API and requires a
configured tool named exactly `subagent`; inactive registered tools count.
Generated child carriers include that transport plus `maxSubagentDepth: 2`, but
only Component-compiled canonical roles whose capabilities contain `dispatch` may
execute it. Other managed children fail closed before provider execution. An
absent or malformed inventory leaves reads available but blocks Write, Edit,
and Bash with the exact `pi install npm:pi-subagents` and restart remediation.
`pi-subagents` is the reference provider, not a Shepherd dependency.

## Component and filesystem safety

The WebAssembly component does not receive an arbitrary filesystem writer. The
native CLI owns descriptor-safe writes and only materializes a compiler result
to an explicit absolute output root. Generated files are overwritten or
removed only when the ownership manifest proves Shepherd created them and their
bytes still match the recorded digest. `--check` performs no writes.

The component runtime's `SHEPHERD_COMPONENT_MODULE` variable is reserved for
tests and controlled embedding. It is not a production trust mechanism.

## Diagnostics

Use the native diagnostics before changing host permissions:

```sh
shepherd doctor
shepherd home show
shepherd status
```

Keep diagnostics and run reports free of credentials. A permission denial is a
host fact to record in the associated run artifact, not a prompt to turn off
the guardrail.

See [Configuration](configuration.md) for tracked/local secret hygiene and
[Integration](integration.md) for host capability limits.
