# Rust service Shepherd project

This example adds workspace tests, a `wasm32-wasip2` Component build, and the
three adapter checks to the minimal layout-v5 configuration.

```bash
shepherd init --confirm
cp /path/to/shepherd/examples/rust-service/shepherd.toml .shepherd/shepherd.toml
shepherd doctor --json
```

The example intentionally contains no `CLAUDE.md`, slash command, Python
launcher, shell dispatcher, or project copy of Shepherd doctrine. Project
decisions belong in flat `.shepherd/docs/`; run decisions and evidence belong
under `.shepherd/runs/<run>/`.
