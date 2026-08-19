# Shepherd Quickstart

From nothing to a running sprint. Three steps, about five minutes.

Shepherd is one native binary plus a thin adapter for whichever harness you use.
The binary is the authority; the adapter only translates host events. Install the
binary first — every harness path below assumes `shepherd` is on `PATH`.

## 1. Install the CLI

```sh
cargo binstall shepherd-cli
```

No Cargo Binstall? Use the checksum-verifying installer:

```sh
curl --fail --location \
  https://raw.githubusercontent.com/FL03/shepherd/v6.5.4/scripts/install-shepherd.sh \
  --output /tmp/install-shepherd.sh
SHEPHERD_VERSION=6.5.4 bash /tmp/install-shepherd.sh
```

Windows PowerShell, and building from source, are covered in the
[README](README.md#install-the-one-native-cli).

Confirm the install and that the harness will find it:

```sh
shepherd --version
command -v shepherd
```

Both must succeed. Adapters resolve `SHEPHERD_NATIVE_BIN` first and otherwise
run the bare `shepherd` command from `PATH` — a shell alias or a wrapper script
will not do, because the harness starts a non-interactive process that never
reads your shell profile. If `command -v shepherd` prints nothing in a login
shell, the harness will not find it either.

## 2. Initialize the project

From the project root:

```sh
shepherd init --confirm
shepherd doctor
```

`init` is mutating, so it requires `--confirm`. Running it without the flag
prints the exact command to re-run rather than doing anything.

`doctor` is the check to trust: it reports the namespace, the resolved
configuration tier, and whether the layout is canonical. A clean `doctor` is the
precondition for everything below.

The project namespace lives at `.shepherd/`. Your user-scoped defaults are a
separate root at `~/.shepherd`, created only if you ask:

```sh
shepherd home init --confirm   # optional
```

Neither command copies state between the two roots.

## 3. Install the harness adapter

Pick the one you use. Each installs the same skills over the same binary.

### Claude Code

```sh
claude plugin marketplace add FL03/shepherd
claude plugin install shepherd@shepherd --scope user
```

Restart Claude Code, then confirm the plugin is live:

```sh
claude plugin list
```

`shepherd` must appear, and its version must match `shepherd --version`. A
mismatch means the harness is running an older cached carrier against a newer
binary, or the reverse.

### Codex

```sh
codex plugin marketplace add FL03/shepherd --ref v6.5.4
codex plugin add shepherd@shepherd
```

Codex does not follow symlinks, so it installs the generated regular-file
carrier under `plugins/shepherd/codex/`. That cache is native-only: no Node, no
npm, no Wasm.

### Pi

```sh
pi install npm:pi-subagents
pi install npm:@pzzld/pi-shepherd
```

Install `pi-subagents` first. `@pzzld/pi-shepherd` is a host extension, not a
standalone runtime, and it needs a `SubagentProvider`-compatible extension to
resolve dispatch identity. If no provider is present or ready, Shepherd fails
closed rather than degrading silently.

Confirm the surface loaded:

```sh
pi config
```

Under `@pzzld/pi-shepherd` you should see one extension, nine skills, and nine
role prompts. If the package lists no resources, the install did not take —
Shepherd contributes all three or none, because Pi reads them from a single
`pi` key in the package manifest.

## Run your first sprint

A sprint moves through three skills, in order:

```
/shepherd:plant    write the seed
/shepherd:spawn    turn the seed into a gated plan
/shepherd:start    execute one lane from that plan
```

**`plant`** equips your current session with the planter profile and interviews
you until the seed is drift-resistant — the scope, the acceptance predicates,
and what is explicitly out of bounds. It writes `.shepherd/runs/<run>/seed.md`.
Nothing is dispatched; you are still the one thinking.

**`spawn`** hands that seed to an engineer, which orients through a discovery
wave and produces a plan split into file-disjoint lanes. A critic gates the plan
before it is accepted. Same session or a different one — the seed on disk is the
handoff, not the conversation.

**`start`** dispatches one conductor to execute one planned lane. Root does not
fan out; the conductor owns its lane and reports back.

If you would rather not drive it step by step, `/shepherd:shepherd` runs the
whole arc and picks up wherever the run currently is.

### Checking on a run

```sh
shepherd status              # where the run is
shepherd run list            # every run in this project
shepherd report              # what has been produced
```

These are read-only. Anything that mutates asks for `--confirm`.

## When something is wrong

Start here, in this order:

```sh
shepherd doctor              # is the layout canonical?
shepherd --version           # does it match the plugin version?
command -v shepherd          # will a non-interactive harness find it?
```

A version mismatch between the CLI and the installed plugin is the most common
failure and the least obvious: the plugin invokes whatever `shepherd` is on
`PATH`, so an old binary silently serves a new plugin. Upgrade the binary the
same way you installed it.

Every mutating command refuses without `--confirm` and prints the exact
re-runnable command. That refusal is the design, not an error.

## Where to go next

- [README](README.md) — what is canonical, the full command and skill surface.
- [Configuration](docs/configuration.md) — project versus user tiers, layout-v5.
- [Integration](docs/integration.md) — how the three adapters compose.
- [Customization](docs/customization.md) — project policy, skills, templates.
- [Permissions](docs/permissions.md) — fail-closed adapter behavior.
