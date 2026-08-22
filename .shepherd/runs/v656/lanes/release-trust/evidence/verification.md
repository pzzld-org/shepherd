# Wave 2 verification

## Reviewer REDO reproduced

Independent review `c726e2db-fc9f-4a75-b7fb-ea98337f3af1` returned REDO. Root reproduced each BLOCKER/HIGH: the schema-1 findings were declarative, Cargo closure was absent, npm closure collapsed duplicate paths, the release check did not execute Cargo deny, workflow reachability used substring presence, and the eval contract did not verify recorded scores.

The replacement mutation suite was run before implementation: the initial `18` tests produced `23` failures and `1` error; reviewer-directed controls expanded the suite to `20` tests and reproduced four additional workflow/root-identity failures. The controls include omitted/fabricated npm and Cargo findings, duplicate npm versions, optional/dev edges, exact Cargo package IDs, corrupted fixes, fabricated paths/artifacts, incomplete/expired waivers, tool failure, commented/other-job/disabled workflow commands, URL scheme/case variants, and active-surface identity preservation.

## GREEN implementation

- `node scripts/check-deps.mjs` now runs `npm audit --json`, full `cargo deny --workspace --all-features check`, JSON Cargo advisories, and locked all-feature Cargo metadata by default.
- Exact normalized measured findings must equal `package.json.shepherdReleaseTrust.observedFindings`; missing, fabricated, or changed fix data fails.
- npm closure follows exact lock paths and audit nodes through production/optional edges while excluding dev edges. Duplicate package names never merge.
- Cargo closure follows exact metadata package IDs and non-dev resolve edges. Paths and shipped artifacts are derived, not asserted.
- Raw npm/Cargo reports and a hashed Cargo metadata summary are captured under `evidence/measurements/`; full metadata is intentionally not tracked.
- The release workflow exposes three separate conditional single-line verification steps under `release-metadata`; its validator binds their exact `run` fields, rejects heredoc/fixture substitution, relocation, and `if: false`, and requires a conditional `taiki-e/install-action@v2` cargo-deny installation before the live checker.
- `scripts/release-trust-surfaces.json` inventories every extended active surface while preserving historical prefixes and contributor identities.
- Current FL03 URLs are rejected case-insensitively for HTTP and HTTPS; historical attribution stays allowed.

## Focused verification

- dependency policy mutation suite: `20/20`, exit `0`;
- version authority fixtures: `9/9`, exit `0`;
- live default dependency checker: exit `0`, `findings=4`, `npm-production-findings=0`, `cargo-production-findings=0`, `reachable-high-critical=0`, `waivers=0`;
- deterministic eval contracts: `9/9`, exit `0`;
- release-trust live score contract: `good=100`, `bad=20`, threshold `80`, margin `80`;
- installer contract: exit `0`;
- GitHub Actions policy: exit `0`, `10` workflows, `64` external uses, `12` repositories;
- primary LSP diagnostics for checker and mutation tests: `0`;
- `git diff --check`: exit `0`.

The live score evidence is bound to SHA-256 hashes of the good case, bad case, and rubric in `release-trust-live-scores.json`. The judge was local Claude Code `opus`; good exited `0`, bad exited `1`.

## Package and gate acceptance

Two monitor attempts reached the Rust build after every preceding command passed, then failed because a persistent `sccache` daemon retained a deleted context-mode temporary directory. Re-running with `RUSTC_WRAPPER=` and `TMPDIR=/tmp` isolated the runner defect:

- locked release `wasm32-wasip2` component build: exit `0`;
- packed-plugin installation and active Claude/Codex/Pi adapter test: exit `0`;
- fast gate: exit `0`;
- `git diff --check`: exit `0`;
- LSP and project scanner findings over the three edited executable test/checker files: `0`.

The packed-plugin run exposed three stale assertions from the accepted least-authority change. They now prove the actual policy: no-scope Claude/Codex Bash requests fail closed, root identity alone does not authorize opaque Bash mutation, and the PATH-resolution check uses a bounded Write request. Product behavior was not weakened.

## Independent hostile follow-up

The re-review identified and root reproduced three further gaps before verdict:

- command strings hidden in a heredoc while a fixture-backed checker actually ran;
- a dev-only duplicate lock entry using a shipped package name being seeded as a production root;
- duplicate classification IDs overwriting one another;
- release workflow use of `cargo deny` without installing it.

All failed before repair. Exact workspace lock paths now define npm roots, duplicate IDs fail before insertion, release checks are separate YAML `run` fields, and cargo-deny installation/action/tool/order are gated. The expanded `20/20` mutation suite, default live checker, deterministic eval contracts, GitHub Actions checker (`64` external uses), release-workflow test, fast gate, diff check, and zero-diagnostic LSP run all passed after these final edits.

## Remaining acceptance

Independent reviewer run `cba5a76b-4e39-48f2-bf9a-1e63c36d9148` returned **PASS** with `BLOCKER/HIGH: 0` after source inspection and reviewer-directed hostile mutations. The lane is accepted for commit and root integration. PR #372 remains draft. No release, publish, tag, or merge action is authorized.
