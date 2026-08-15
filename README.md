# Shepherd v6.4.5

[![License](https://img.shields.io/github/license/FL03/shepherd?style=for-the-badge&logo=github)](LICENSE)
[![Release](https://img.shields.io/github/v/release/FL03/shepherd?style=for-the-badge&logo=github)](https://github.com/FL03/shepherd/releases)

Shepherd is a harness-neutral execution and governance engine for long-running
agent work. The deterministic core and the canonical CLI are Rust. Claude Code,
Codex, and Pi are host adapters over the same typed WebAssembly Component Model
contract, so a new harness does not require a second policy engine or a rewrite.

The v6.4.5 component is published as `fl03:shepherd@6.4.5`. Its WIT contract,
generated bindings, native CLI, and adapter packages are versioned together.

## What is canonical

- `shepherd` is the only command-line authority. It owns configuration, layout,
  run state, dispatch identity, guard evaluation, content compilation, registry
  access, and deterministic output.
- `crates/core`, `crates/compiler`, `crates/registry`, and `crates/render` are
  reusable Rust crates. The `shepherd` SDK is the public embedding boundary.
- `crates/component` exports the typed WIT interface. It has no harness-specific
  filesystem or process policy.
- `packages/harness-claude`, `packages/harness-codex`, and `packages/harness-pi`
  only translate host events, call the component, and publish host responses.
- Python, Bash, and the retired JavaScript compiler/guard are not fallback
  implementations. An unknown legacy verb fails at the native CLI boundary.

The component has two WebAssembly roles:

| Target | Purpose |
| --- | --- |
| `wasm32-unknown-unknown` | Reachability of the pure engine without an OS or filesystem. |
| `wasm32-wasip2` | The runnable Component Model artifact consumed by Node and other hosts. |

`wasm32-unknown-unknown` is not a filesystem runtime. The Component Model
artifact is the cross-language boundary; native adapters retain only the host
operations that require a process, harness event stream, or descriptor-safe
filesystem.

## Install the one native CLI

Release installers select the host asset, verify its SHA-256 sidecar before
extraction, require the executable plus `LICENSE`, `THIRD_PARTY_NOTICES.md`,
and hash-addressed `THIRD_PARTY_LICENSES/` texts, and refuse to replace an
existing installation unless `SHEPHERD_FORCE=1` is set. GNU/Linux assets are
built and checked against a maximum `GLIBC_2.17` symbol requirement.

macOS (arm64/x86_64) and GNU-libc Linux (arm64/x86_64):

```sh
curl --fail --location \
  https://raw.githubusercontent.com/FL03/shepherd/v6.4.5/scripts/install-shepherd.sh \
  --output /tmp/install-shepherd.sh
SHEPHERD_VERSION=6.4.5 bash /tmp/install-shepherd.sh
```

Windows x86_64 PowerShell:

```powershell
$installer = Join-Path $env:TEMP 'install-shepherd.ps1'
Invoke-WebRequest `
  https://raw.githubusercontent.com/FL03/shepherd/v6.4.5/scripts/install-shepherd.ps1 `
  -OutFile $installer
$env:SHEPHERD_VERSION = '6.4.5'
& $installer
```

The default destination is `$HOME/.local/bin`; the installers do not modify
`PATH`. musl Linux and Windows ARM64 fail explicitly because this release does
not publish compatible native assets. npm packages and plugin caches are
harness adapters, not CLI installers.

To build the same native CLI from a checkout:

```sh
git clone https://github.com/FL03/shepherd.git
cd shepherd
scripts/setup.sh
cargo build --locked --release -p shepherd-cli
./target/release/shepherd --help
```

`rust-toolchain.toml` pins Rust 1.96.0 and the three WebAssembly targets. For
the full Component Model gate, install the WASI tools and SDK through the
repository setup path:

```sh
scripts/setup.sh --wasm
scripts/gate.sh wasm
```

The native executable can be placed on `PATH` by the operator. Published
adapters resolve an explicit `SHEPHERD_NATIVE_BIN` first and otherwise execute
the installed `shepherd` command from `PATH`. The checkout-only `bin/shepherd`
launcher also recognizes `target/release/shepherd` and
`target/debug/shepherd` for contributor workflows. No adapter invokes a retired
language-specific CLI.

## Initialize a project

Run the native binary from the project root:

```sh
shepherd init --confirm
shepherd doctor
shepherd home init --confirm  # optional, explicitly initializes ~/.shepherd
```

`init` creates or verifies the project-owned `.shepherd/` namespace and its
canonical configuration. `home init` owns the separately-scoped user namespace
at `~/.shepherd`. Neither command silently copies state between those roots.

For an existing pre-v6.4.5 namespace, inspect first and apply only with explicit
confirmation. Always keep the generated snapshot:

```sh
shepherd migrate --layout v5 --scope project --dry-run
shepherd migrate --layout v5 --scope project --confirm \
  --snapshot-dir /tmp/shepherd-layout-v5-project
```

The migration is bounded and descriptor-safe. It rejects collisions, symlinks,
malformed run state, and oversized inputs before mutation. Run the user scope
separately when it is intended:

```sh
shepherd migrate --layout v5 --scope user-home --dry-run
```

## Compile adapter content

Roles and skills are authored once under `content/`. The Rust compiler measures
and emits deterministic, target-specific trees. It does not write files unless
the native CLI receives an explicit absolute `--out` directory.

```sh
shepherd compile --target claude --out /absolute/path/to/claude
shepherd compile --target codex  --out /absolute/path/to/codex
shepherd compile --target pi     --out /absolute/path/to/pi
shepherd compile --target codex --out /absolute/path/to/codex --check
```

`--check` is read-only. Every emitted manifest records source provenance,
content hashes, line/word/byte/token measurements, and a whole-tree digest.
Existing generated files are changed only when the prior manifest proves
Shepherd ownership and the bytes still match that manifest.

The compiler uses a versioned UAX #29 measurement algorithm. Current hard
per-file limits are 600 words for a role, 500 for a skill, 1,500 for a
reference, and 750 for a command. Always-loaded skills are limited to 200
words; the compiled harness skill set is limited to 3,500 words. These are
upper bounds, not writing targets. Keep instructions short, load detail on
demand, and avoid repeating the same doctrine in roles, skills, and run
artifacts.

The authored flock is closed at nine roles: `shepherd`, `planter`, `engineer`,
`conductor`, `critic`, `coder`, `auditor`, `discovery`, and `worker`. A harness
may expose a different dispatch primitive, but it must preserve these role
contracts and the typed identity/write-scope facts. Adding a role is a contract
change, not an adapter-local alias.

## Native command surface

The following command families are owned by the Rust CLI in v6.4.5:

`audit`, `close-lane`, `compile`, `config`, `dispatch`, `discovery`, `doctor`,
`deliverable`, `dups`, `eval` (recorded-result inspection), `export` (stdout
views), `guard`, `graph`, `handoff`, `home`, `init`, `insights` (read-only),
`issues`, `lint`, `lock`, `mem`, `migrate`, `models`, `plan`, `query`, `render`,
`ready`, `report`, `run`, `search`, `seed`, `signal`, `sprint`, `status`, and
`teammate`.

Some names remain visible for stable refusal behavior and are not supported
workflows:

- `sync` is not wired to a native refresh pipeline.
- `worktree` is not a native git-worktree host seam.
- `eval run` does not invoke an interpreter or remote judge.
- `dups --stdin`, `insights clear`, and arbitrary `export --out` writes are
  rejected because they do not satisfy the descriptor-safe canonical boundary.
- Removed `shctx`, Python, Bash, and Node command paths are not supported.

Use `shepherd <command> --help` for the exact flags in the binary you built.

## Canonical layout-v5

The project namespace and the user namespace are separate. They must be
canonical, agree on schema/version, and contain no duplicate authority.

```text
.shepherd/
  shepherd.db       # native registry state
  shepherd.lock     # native single-writer lock
  project.json      # stable project identity
  shepherd.toml     # project configuration
  ctx/              # cross-run structured context
  docs/             # flat, cross-run human documentation
  templates/        # project template overrides
  runs/<run>/        # every run-specific artifact
    run.json
    seed.md
    mesh.md
    plan.md
    lanes/<lane>/plan.md
    dispatch/
    reports/
    audits/
    handoff.md

~/.shepherd/
  shepherd.toml             # user defaults, optional
  shepherd.<harness>.toml   # user harness defaults, optional
```

`docs/` is intentionally flat. A specification, diagram, or journal entry
that applies across runs belongs directly under `.shepherd/docs/`. A seed,
plan, report, audit, handoff, dispatch record, or lane artifact belongs under
the associated `.shepherd/runs/<run>/`. Do not create a second `memory/`,
`docs/specs/`, `docs/reports/`, or namespace-local authority.

Run ids are lower-case slugs. The run directory is the identity, so fixed
artifact names do not repeat the run or date prefix. `run.json` is written by
`shepherd run ...`, not by an adapter or hand edit.

## Harness adapters

| Harness | Package | Constraint |
| --- | --- | --- |
| Claude Code | `@fl03/harness-claude` | Hook envelopes and lifecycle events only. |
| Codex | `@fl03/harness-codex` | Hook envelopes and lifecycle events only. |
| Pi | `@fl03/harness-pi` | Requires a `SubagentProvider`-compatible extension such as `pi-subagents`; absent or unready providers fail closed. |

The npm embedding adapters load the adjacent `@fl03/component-runtime` package.
The normal Claude marketplace plugin is different: it invokes `shepherd
claude-hook` directly. Generated ESM bindings and `.wasm` files are staged for
component/npm embedding, not hand-authored or committed. `SHEPHERD_COMPONENT_MODULE`
is a controlled test/embedding override, not a production discovery mechanism.

Claude's production plugin is a normal marketplace installation through the
thin `plugins/shepherd` carrier. Its four Claude hooks use the installed native
`shepherd` executable directly. The Rust CLI owns identity normalization,
lifecycle dispatch, and fail-closed
guard evaluation. The Claude plugin has no ZIP payload, Node runtime, generated
Component Model carrier, or plugin-local compatibility launcher. Install the
native CLI first and ensure `shepherd` is on `PATH` before starting Claude.

For a persistent user installation, add the GitHub-hosted catalog and install
the thin carrier:

```sh
claude plugin marketplace add FL03/shepherd
claude plugin install shepherd@shepherd --scope user
```

The marketplace catalog uses the standard relative `./plugins/shepherd` source
entry. The carrier holds a byte-identical projection of the canonical manifest
and links to canonical hooks, agents, and skills; Claude dereferences those
within-marketplace links into its installed cache. It contains no duplicate
authored plugin content, package manifest, lockfile, or Node bootstrap. No
`--plugin-url`, `--plugin-dir`, release ZIP, or session-only loader is part of
the supported installation path.

Cross-harness resume uses the typed identity, lifecycle, dispatch, response,
and run-artifact contracts. Adapters must not infer role, policy, or run state
from another harness's private files.

## Verification

Fast checks are deterministic and local:

```sh
scripts/gate.sh fast
```

The full native suite adds locked tests, clippy, and the feature matrix:

```sh
scripts/gate.sh full
```

Component and clean-package checks are explicit:

```sh
npm ci --ignore-scripts
cargo build --locked --release -p shepherd-component --target wasm32-wasip2
bash scripts/test-component-node.sh
bash scripts/test-packed-plugin.sh
```

The packed-plugin test uses installed tarballs in a temporary directory. It is
the check that catches a package which passes from the repository but fails
after publication.

## Documentation map

- [Configuration](docs/configuration.md): project and user tiers, layout-v5,
  tracked versus local values, and secret hygiene.
- [Integration](docs/integration.md): how the three adapters and local skills
  compose without sharing harness internals.
- [Customization](docs/customization.md): project policy, skills, templates,
  and target-specific content.
- [Memory](docs/memory.md): structured Shepherd context versus harness-native
  prose memory.
- [Permissions](docs/permissions.md): safe host permissions and fail-closed
  adapter behavior.
- [Component crate](crates/component/README.md): WIT and Node Component Model
  details.

## License

Apache-2.0. See [LICENSE](LICENSE).
