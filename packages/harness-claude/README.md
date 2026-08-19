# `@pzzld/claude-shepherd`

This npm package is an optional Component Model embedding adapter. It is not
the Claude marketplace runtime. The normal Claude plugin is installed through
a thin repository carrier and calls the native `shepherd claude-hook` command
directly. That Rust command owns `RawIdentity` normalization,
`plan_lifecycle`, `DispatchService`, and `GuardEngine`; its PreToolUse failures
produce Claude's fail-closed denial envelope.

The package remains useful to an embedding that explicitly hosts the
`fl03:shepherd@6.5.5` Component Model through `@pzzld/component-runtime`. Its
generated runtime is staged during npm release and is never committed.
`SHEPHERD_COMPONENT_MODULE` is a test or embedding override only. It is not a
production discovery mechanism for the normal Claude plugin.

Hard prerequisite for the normal plugin: the native `shepherd` executable must
be on `PATH`. Node.js and a plugin ZIP are not required.

For persistent installation through Claude's marketplace catalog:

```sh
claude plugin marketplace add FL03/shepherd
claude plugin install shepherd@shepherd --scope user
```

The marketplace entry is the standard `./plugins/shepherd` carrier. It keeps a
byte-identical projection of the canonical manifest and links to the canonical
hook manifest, agents, and skills, which Claude dereferences within the
marketplace during install. It has no package manifest, lockfile, Node
bootstrap, duplicate authored content, or release archive. The deterministic
integration test is `scripts/tests/test-claude-marketplace.sh`; when Claude is available, it
strictly validates a dereferenced fixture, adds an isolated marketplace,
installs `shepherd@shepherd`, rejects escaping links and Node/npm artifacts in
the cached root, and invokes the installed native hook contract.
