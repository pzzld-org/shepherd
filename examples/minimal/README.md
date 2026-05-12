# Minimal shepherd binding

The smallest viable shepherd configuration. Assumes:

- A Rust project (swap `language` and `[gates]` for other languages — see [`../../docs/integration.md`](../../docs/integration.md))
- Default mod-10 sprint convention (`v{X}.{Y}.{Z}-dev.{0..9}`)
- The three canonical Rust gates (`cargo check`, `cargo clippy`, `cargo fmt`)
- Operator-driven release pipeline (no GitHub Actions automation)
- GH MCP available; no Sentry, Supabase, Fly integration

To use:

```bash
# From your project root
mkdir -p .claude
cp /path/to/shepherd-plugin/examples/minimal/shepherd.toml .claude/shepherd.toml
# Edit .claude/shepherd.toml and customize [project].name + any specifics
```

Then in a Sonnet Claude Code session:

```
/shepherd:start
```

For more elaborate bindings (Sentry / Grafana / Supabase / Fly / per-project doctrines / GH-workflow release pipeline), see [`../axiom/`](../axiom/).
