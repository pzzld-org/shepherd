# Minimal Shepherd project

This is the smallest useful layout-v5 project binding. It has one native
configuration and no harness-specific policy. Claude, Codex, and Pi may all
coordinate through the same `.shepherd/runs/<run>/` state.

From a Git repository root:

```bash
shepherd init --confirm
cp /path/to/shepherd/examples/minimal/shepherd.toml .shepherd/shepherd.toml
shepherd doctor --json
shepherd compile --target claude
shepherd compile --target codex
shepherd compile --target pi
```

Install only the carrier for the harnesses you use. The carriers do not own
configuration, guard policy, identity, run state, or authored role and skill
logic. Those remain in the Rust CLI and Component Model.

See [`../../docs/configuration.md`](../../docs/configuration.md) for every typed
configuration field and [`../rust-service/`](../rust-service/) for a workspace
with extra gates.
