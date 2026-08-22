# v656 planning evidence

**Role contract requested:** `shepherd:engineer`
**Actual transport identity:** `worker`
**Run:** `v656`
**Plan base:** `8d60002bd6fccc51911629526537eeda624c04d9`

## Composite orientation limitation

Pi issue #370 prevented native registration of `shepherd:engineer`, `auditor`, and
`discovery`. The child runtime exposed no subagent dispatch tool. The required composite
discovery wave was approximated with concurrent read-only repository inspection. This is
#370 evidence, not a claim that the normal spawn contract passed.

## Live #368 reproduction

Both Bash and artifact writes were blocked before execution:

```text
Pi component rejected identity or guard request (identity):
{"code":"invalid-identifier","message":"unsafe session id `call_vGjivXohXWUbpPtVtOGPtQkq|fc_0c4060b9c5de4864016a88e989d47c87d0b796feb4e46bbf8d`"}
```

The parent approved returning artifact contents for persistence through the working native
filesystem fallback. No product source was edited.

## Auditor findings

| Severity | Finding | Evidence |
|---|---|---|
| BLOCKER | Pi routes provider tool-call identifiers through a dispatch type used for session IDs. | `packages/harness-pi/src/extension.mjs:93-123`; `crates/component/src/lib.rs:132-135,388-393`; `crates/core/src/dispatch/identifier.rs:88-91,147-163`. |
| BLOCKER | Pi does not register Shepherd agent types with the provider. | `packages/harness-pi/package.json:16-27`; `packages/harness-pi/src/subagent-provider.mjs:1-115`. |
| HIGH | The seed overstated #370 as nine dispatchable roles. | `crates/core/src/dispatch/role.rs:7-28` defines nine canonical roles; `content/RECONCILIATION.md:40-47` keeps `shepherd` and `planter` top-level and non-dispatchable. Seven roles are dispatchable. |
| HIGH | Root dispatch resolution remains vacuous. | `crates/cli/src/dispatch_service.rs:285-294` emits `lane: None` and `write_scope: ["**"]`. |
| HIGH | Gate provenance is substring-derived. | `hooks/scripts/bash_post.sh:23-33`; `hooks/tests/test_bash_post_ledger.sh:31-35`. |
| HIGH | Shared Claude settings request unsafe defaults. | `.claude/settings.json` contains `Bash(*)`, `defaultMode: bypassPermissions`, and both prompt-suppression flags. |
| HIGH | Dependency updates cover GitHub Actions only. | `.github/dependabot.yml` has one `github-actions` entry. |
| HIGH | Security policy is absent. | No `SECURITY.md` exists. |
| MEDIUM | #367 appears implemented on this branch. | `crates/core/src/loader.rs:356-386`; `crates/core/tests/loader.rs:486-528`. |
| MEDIUM | #369 authored source was omitted from seed scope. | `content/skills/spawn/SKILL.md:16-27` owns the behavior; generated carriers must follow it. |
| MEDIUM | Organization migration is incomplete. | Runtime/install surfaces still contain FL03 URLs in manifests, README, QUICKSTART, plugin metadata, and integration docs. Historical records remain separate. |
| MEDIUM | Version authority scans ignored runtime state. | `scripts/version-bump.py:101-115,710-737` does not exclude `.pi`; the clean archive passes while ignored `.pi/tasks` fails in place. |
| INFO | `dep:toml` remains narrow and compliant. | Production `toml::` use is confined to typed guard predicates in `crates/core/src/guard/parser.rs`; general configuration uses `config`. |
| INFO | Artifact staging already matches policy. | `scripts/stage-pi-carrier.sh` stages generated Pi carriers; `scripts/tests/test-generated-carrier-authority.sh` rejects committed generated carriers. |
| INFO | Eval infrastructure exists. | `services/eval/evals/run_eval.sh` uses local Claude Code; deterministic tests live under `services/eval/tests/`. |

## Seed contradictions

1. Seven roles are dispatchable; `shepherd` and `planter` remain top-level identities.
2. #367 is a regression verification unless live reproduction contradicts current code/tests.
3. #369 requires `content/skills/spawn/SKILL.md` in authored scope.
4. Replace current runtime/install FL03 strings, not historical records or attribution.
5. A normal engineer/auditor/discovery wave did not run; #370 forced the worker fallback.
6. #368 blocked child planning writes; parent persistence was required.

## External discovery gap

The installed `pi-subagents` provider source and upstream role-registration API were unavailable
to the child. Pi bootstrap must first locate the provider registration contract read-only. It
may generate the seven dispatchable profiles from compiler-owned role data only after measuring
that contract. It must not guess a manifest key or commit a hand-copied agent tree.

## Validation limitation

The child could not run `shepherd plan verify --run v656` before persistence. Root owns that
gate. No product source was edited, no file was staged, and no production operation ran.
