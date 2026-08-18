# Content authority v6.5.0

`content/` is Shepherd's only authored prompt and policy corpus. It is
harness-neutral input to the Rust compiler, not a staging area for a later
rewrite.

## Canonical sources

- `roles/*.md` defines all nine roles, portable model hints, capabilities,
  write eligibility, dispatchability, and write scopes.
- `skills/*/SKILL.md` defines the seven portable workflow skills.
- `predicates/*.toml` defines deterministic guard-policy inputs.
- `templates/*.md` defines native artifact templates that are compiled or
  embedded by Rust.

The compiler parses these sources, validates the closed metadata grammar,
applies versioned prompt budgets, resolves each `model_hint` and capability
through a typed `HarnessProfile`, and emits target-final Claude, Codex, and Pi
trees plus machine-readable role contracts. The WebAssembly component exposes
that same compiler and guard engine to language hosts.

## Generated carriers

Root `agents/*.md` and `skills/*/SKILL.md` are generated Claude carriers. The
`.shepherd-generated.json` manifest records their source and content digests.
They are outputs, not editable doctrine. A generated skill contains exactly one
`SKILL.md`; reference, schema, query, style, example, and command subtrees are
retired because they created a second authority and inflated installed context.

Codex and Pi consume the same compiled role contracts. Adapters translate only
host events, typed component calls, and host response envelopes. They do not
parse Markdown, choose policy, maintain model/tool maps, or create run state.
Pi dispatch additionally requires a ready `SubagentProvider`; an unavailable
provider is a typed, fail-closed limitation rather than an emulated subagent.

## Enforced invariants

- `crates/compiler` owns prompt measurement, budgets, target profiles, and
  target-final emission.
- `crates/core` owns guard, identity, configuration, and portable state logic.
- `crates/registry` owns the sole embedded registry schema and migrations.
- `crates/component` owns the versioned WIT boundary used by Node hosts.
- `scripts/check-plugin.py` rejects a second root skill authority.
- compiler, component, adapter, package, and conformance gates prove the same
  corpus is accepted across all three harnesses.

Change authored behavior here, update its deterministic tests and eval case,
then regenerate carriers. Never patch an emitted harness tree by hand.
