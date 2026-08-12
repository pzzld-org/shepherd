# Contributing

We welcome contributions to pzzld! Whether you're fixing bugs, adding new features, or improving documentation, your help is appreciated. That being said, we implore all of our contributors to adhere to a standard of quality and professionalism. Please follow the guidelines below to ensure a smooth contribution process.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). We are committed to providing a welcoming and inclusive environment for all contributors.

## How to Contribute

**Note**: Every contribution should have a corresponding feature request or, for larger changes, a dedicated proposal detailing the intended changes and their rationale. This helps maintain clarity and ensures that all contributions align with the project's goals.

1. **Fork the Repository**: Start by forking the pzzld repository to your own GitHub account.
2. **Clone Your Fork**: Clone your forked repository to your local machine.
3. **Create a Branch**: Create a new branch for your feature or bug fix. Use a descriptive name for your branch.
4. **Make Changes**: Implement your changes in the new branch. Ensure your code adheres to the project's coding standards.
5. **Test Your Changes**: Thoroughly test your changes to ensure they work as expected
6. **Commit Your Changes**: Commit your changes with clear and concise commit messages.
7. **Push to Your Fork**: Push your changes to your forked repository on Git
8. **Open a Pull Request**: Navigate to the original pzzld repository and open a pull request from your forked repository. Provide a detailed description of your changes and the problem they solve.
9. **Address Feedback**: Be responsive to any feedback or requests for changes from the project maintainers.

## Rust workspace — start here

One command makes a fresh clone ready. It is idempotent and prints what it changed.

```bash
scripts/setup.sh          # toolchain, wasm targets, cargo-deny/nextest, git hooks
scripts/setup.sh --wasm   # the above, plus wasi-sdk for the WebAssembly suite
scripts/setup.sh --check  # report what is missing, change nothing
```

It exists because several things are only true if somebody remembered them, and none are discoverable by reading the code. Git hooks are inert until `core.hooksPath` is set, and that is *local* config which cannot be committed, so every clone starts with them off. The wasm targets have to be installed before the cross-target checks mean anything. The WASI suite needs a `wasi-sdk` and a `wasmtime` that nothing else in the toolchain provides.

### The gate

```bash
scripts/gate.sh fast   # formatting + workspace invariants; no compilation   (runs on commit)
scripts/gate.sh full   # the above, plus clippy, tests, feature matrix       (runs on push)
scripts/gate.sh wasm   # the WebAssembly suite, executed under wasmtime
scripts/gate.sh all    # full + wasm
```

The tiers follow the budget in `CLAUDE.md`: the per-commit gate is deterministic, local, free, and under two seconds, which rules out anything that compiles. Compilation happens at push, the last boundary that is still local and free.

Do not bypass a hook with `--no-verify` — it disables `commit-msg` and every future hook too, silently. `SHEPHERD_SKIP_GATE=1` skips the gate alone, visibly, when you genuinely need to commit a broken tree mid-rebase.

### Adding a crate

Adding a member is mechanical, and the steps are enforced rather than remembered:

```bash
scripts/check-workspace.sh --self-test   # prove the rules can fail
scripts/check-workspace.sh               # then check them
```

Nine invariants: every member inherits the workspace lints and version, carries a README and a description, builds its docs.rs page from `full`, is reachable through the `shepherd` umbrella, and appears in `scripts/check-features.sh`. Only `shepherd-cli` may ship a binary, and it must route through the umbrella rather than naming a member directly. `crates/sdk/README.md` walks the four steps.

### Feature flags

`cargo check --workspace` builds exactly **one** combination — the union of every member's defaults — so every other flag is unverified by it. `scripts/check-features.sh` checks each in isolation across both wasm targets. A new flag without a row there is a flag nothing exercises.

## Coding Standards

- Follow the existing coding style and conventions used in the project.
- Write clear, concise, and well-documented code.
- Ensure your code is efficient and avoids unnecessary complexity.
- Include unit tests for new features or bug fixes.
- Ensure all tests pass before submitting your pull request.
- Use meaningful variable and function names.
- Avoid large, monolithic commits. Break your changes into smaller, manageable commits.
- Keep your pull requests focused on a single issue or feature.
- Avoid including unrelated changes in your pull request.
- Ensure your pull request does not introduce any new warnings or errors.
- Use descriptive titles and detailed descriptions for your pull requests.
- Be respectful and professional in all communications related to your contribution.

## Reporting Issues

If you encounter any bugs or issues while using pzzld, please report them by opening an issue on the GitHub repository. Provide as much detail as possible, including steps to reproduce the issue, expected behavior, and actual behavior.
