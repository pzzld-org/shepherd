---
title: v6.4.5 CLOSE audit — dependency-topology
date: 2026-08-14
auditor: shepherd:auditor
sprint: v6.4.5
concern: dependency-topology
mode: close
methodology: hypothesis-driven falsification (superpowers:systematic-debugging); every
  claim below is grounded in a command run in this session against
  /Users/jo3/src/fl03/shepherd @ b57d495, not in another agent's report
prior_class_priors: adaptation registry empty at this sprint's close
  (`shctx adapt priors --lessons` / `shctx adapt report` both returned no prior
  metrics) — framework priors used, no adjustment applied
---

## Scope reviewed

- `Cargo.toml` (workspace) + `crates/{cli,core,registry,render,sdk}/Cargo.toml`
- `package.json` (workspace root) + `packages/{compiler,harness-claude,harness-codex,harness-pi}/package.json`
- `packages/scripts/check-deps.mjs` (the npm-side dependency gate)
- `scripts/gate.sh`, `scripts/check-workspace.sh`, `.githooks/pre-commit`,
  `.github/workflows/{boundaries,rust,rust-wasm,release}.yml` (what actually wires which
  gate to which trigger)
- Live guard wiring: `packages/harness-codex/hooks/hooks.json`,
  `packages/harness-codex/hooks/scripts/shepherd_guard.mjs`,
  `packages/harness-claude/src/guard-serve-{broker,client,engine}.mjs`,
  `packages/harness-pi/src/extension.ts`, `bin/shepherd`
- `crates/core/src/run.rs` vs `services/cli/shepherd_cli/models_run.py` (the "behavioral
  oracle" relationship), `crates/cli/src/cmd.rs`, `services/cli/shepherd_cli/commands/guard.py`
- `.shepherd/runs/v645/seed.md` decision 9 + the conformance-oracle deliverable; GH #280,
  #281, #284; `conformance/run.sh`
- 5 wave reports under `.shepherd/runs/v645/reports/` read only to locate git commit
  boundaries and confirm no prior agent already flagged what follows (all findings below
  are independently re-derived from commands, not taken on report authority)

15 files/scripts read directly; ~25 commands run, plus a re-verification pass at report
finalization time (same HEAD, all reproduced identically — see each finding's
falsification block). No `cargo build`/`cargo test` workspace-wide, no full pytest run —
`cargo tree -p shepherd-cli --depth 1` and targeted `node`/`bash` invocations only, per
the dispatch brief's concurrency constraint.

## Findings summary

| Severity | Count |
|---|---|
| CRITICAL | 1 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 0 |

Both findings filed as `audit_findings` rows (ids 69, 72; project registry,
`concern=dependency-topology`), confirmed present via direct sqlite3 query against
`.shepherd/shepherd.db` at report-finalization time. GH #290 filed for the CRITICAL
finding, confirmed OPEN.

## Findings

### FINDING 1 — CRITICAL — `harness-codex` depends on `harness-claude` at runtime; its own gate says so and is wired into nothing

**Hypothesis:** the seed's own decision 9 and GH #280's acceptance item 6 ("no `harness-*`
package imports a sibling harness") hold at HEAD, and `check-deps.mjs` — built in W0
specifically to enforce this — passes clean.

**Falsification:**

```
$ node packages/scripts/check-deps.mjs
checking 4 package(s): @fl03/compiler, @fl03/harness-claude, @fl03/harness-codex, @fl03/harness-pi

  no adapter depends on another adapter        FAILED
      @fl03/harness-codex: depends on adapter package `@fl03/harness-claude` -- adapters must not depend on each other
  adapter scoped deps are allowlisted          FAILED
      @fl03/harness-codex: depends on `@fl03/harness-claude`, which is neither `@fl03/compiler` nor a `@fl03/cli-*` platform package
  compiler does not depend on adapters         ok

::error::2 dependency-rule violation(s).
```
Exit code 1. The hypothesis is falsified: the gate is RED at HEAD, not clean. Reproduced
a second time at report-finalization, byte-identical output.

**Root-cause trace, four independent facts, each verified by a command:**

1. **Introduced in the sprint's own final commit.** `git log -p -- packages/harness-codex/package.json | awk '/^commit/{c=$2} /harness-claude/{print c}'` names only `b57d495` — HEAD itself, titled "W12 — close the loop, and one gate that could never pass." `git diff b57d495~1 b57d495 -- packages/harness-codex/package.json` shows the exact addition: `+ "@fl03/harness-claude": "6.4.5"`. No later commit exists to re-check it against. The only recorded run of `check-deps.mjs` anywhere in `.shepherd/runs/v645/reports/` is `coder-W0-S7.md`, which predates this dependency and shows 0 violations — the coder who built the gate never saw it fail because the violating code didn't exist yet.

2. **The coupling is not a manifest artifact — it's live, `$PLUGIN_ROOT`-relative, production code.** `packages/harness-codex/hooks/hooks.json` wires `command: node "$PLUGIN_ROOT/hooks/scripts/shepherd_guard.mjs"` as the real `PreToolUse`/`PostToolUse` hook (both files are `git ls-files`-tracked, not generated-only). That script does:
   ```js
   import { defaultSocketPath } from "../../../harness-claude/src/guard-serve-broker.mjs";
   import { requestGuardVerdict } from "../../../harness-claude/src/guard-serve-client.mjs";
   ```
   a static ES import resolved by hardcoded relative path (three directories up from `hooks/scripts/`), never the `@fl03/harness-claude` package specifier. Two test files under `packages/harness-codex/test/` do the same. `packages/harness-codex/README.md` names an already-installed `codex-shepherd@1.0.2` sibling bundle as the deployment target this package models itself on, and GH #280's own spec says `codex-shepherd` is meant to become a build output of this package — i.e., eventually shipped standalone, without `packages/harness-claude` present. The relative import walks outside `$PLUGIN_ROOT` looking for a `harness-claude/` sibling that will not exist in that deployment. Confirmed this is a real design choice, not an oversight: `guard-serve-broker.mjs`'s own header states it is "SHARED between packages/harness-claude and packages/harness-codex ... cross-imported rather than copied" and cites `materialize.mjs`'s existing `../../compiler/...` import as precedent — but `@fl03/compiler` is allowlisted by rule 2 and `@fl03/harness-claude` is not; the precedent argument doesn't hold under the gate's own rules, and nobody ran the gate to notice.

3. **The gate is wired into nothing.** `grep -rln check-deps` across every `*.sh`/`*.yml`/`*.json`/`*.mjs` in the repo returns only the script itself. Not `scripts/gate.sh` (`gate_fast`/`gate_full` are exclusively Rust — rustfmt, `check-workspace.sh`, `check-plugin.py`, clippy, `cargo test`, `check-features.sh`). Not `.githooks/pre-commit` (its path filter is `\.rs$|Cargo\.(toml|lock)$|^scripts/check-|^(agents|commands|skills|hooks)/|^\.claude-plugin/` — `packages/scripts/check-deps.mjs` matches none of it). Not any `.github/workflows/*.yml` (`boundaries.yml` is Rust-only wasm/delivery-dependency checks; no workflow references `packages/` at all). Not any `package.json` `scripts` block — root `package.json` has no `scripts` field, and none of the 4 workspace members declare `check`/`lint`/`predeploy`. The intro's "`gate (full) green`" claim is true and orthogonal: `gate.sh` never touches this gate. Re-confirmed at finalization time: the same grep still returns only the script itself.

4. **Even wired in, the gate cannot see the real coupling.** `check-deps.mjs`'s three rules parse only `package.json` dependency fields (`dependencies`/`devDependencies`/`peerDependencies`/`optionalDependencies`) — confirmed by reading the script (`allDeps()`, `ruleNoAdapterToAdapter`, `ruleAdapterScopedDepsAllowlisted`) and independently corroborated by `auditor-W4-central-verify.md:454-467`, which found the identical gap re `@fl03/compiler` at W4 ("check-deps.mjs still passes because its 3 rules ... reason over the manifest graph, not real module resolution"). Deleting `"@fl03/harness-claude": "6.4.5"` from `harness-codex/package.json` — the obvious minimal fix — would turn the gate green while the relative-path runtime import stays exactly as coupled as before. The gate would then be checking the wrong signal, permanently, and reporting success while doing so.

**Why this is a distinct class from this sprint's nine other "gate that cannot fail" instances** (DF-17/19/59/62/63/71/72/75/77, GH #284): `check-deps.mjs` genuinely *is* falsifiable — `--self-test` builds three synthetic broken fixtures and all three correctly fail, proven by running it (`node packages/scripts/check-deps.mjs --self-test`, all three "fails as designed", then the real tree re-check inside the same invocation reproduces the same 2 violations). And it correctly detects the live violation the moment someone runs it by hand. The defect is not a manufactured precondition or a vacuous pass — it is that **nothing in the pipeline ever runs it**, so a correct, working, currently-failing gate produced zero protection at exactly the moment its rule was broken. If the brief's "tenth instance" is being counted, this is closer to an inverse case worth naming precisely rather than folding into the same bucket: a gate that lies (cannot fail) is bad; a gate that tells the truth to nobody is functionally identical in outcome and arguably easier to miss, because every report of "the gate passes" is technically accurate — it was just never asked the question.

**Confidence:** HIGH — every claim above is a direct command output or a `git diff`/`git log` against the actual commit, not an inference from another report. Re-verified a second time at report-finalization (same HEAD `b57d495`): `check-deps.mjs` still exits 1 with the identical two violations, and the wiring grep still finds nothing.

**Filed:** GH #290 (OPEN, confirmed) — full evidence + 3-part fix: resolve the coupling architecturally — extract the broker into `@fl03/compiler` or a new allowlisted package, or extend the allowlist and document the exception; wire `check-deps.mjs` into `scripts/gate.sh` or a CI workflow; extend the gate to resolve real import specifiers, not just manifest fields). Cross-referenced against open GH #280 (acceptance item 6, still OPEN, confirmed — correctly, this is why).

### FINDING 2 — MEDIUM — the four `packages/*/package.json` version fields have no bump mechanism and no parity check against the Cargo workspace version

**Hypothesis:** the four new npm packages' hardcoded `"version": "6.4.5"` fields, and root `package.json`'s claim that "the Rust workspace ... is the single source of truth every package.json version here tracks," are backed by some mechanical check or bump step, the way the Rust side is.

**Falsification:**
```
$ grep -n version packages/*/package.json | grep -v engines
compiler/package.json:3:      "version": "6.4.5",
harness-claude/package.json:3: "version": "6.4.5",
harness-codex/package.json:3:  "version": "6.4.5",
harness-pi/package.json:3:     "version": "6.4.5",

$ grep -n "Cargo.toml" .github/workflows/release.yml   # 0 hits
$ grep -n "package.json" .github/workflows/release.yml # 0 hits — the bump step
  explicitly touches .claude-plugin/plugin.json, marketplace.json, SKILL.md
  frontmatters, and README only
$ grep -n "package.json\|Cargo.toml" skills/context/scripts/cmd_release.sh  # 0 hits
```
Re-run at finalization time: both greps against `release.yml` and `cmd_release.sh` again
returned 0 hits, confirming no drift since the first pass.

None of the four `packages/*/package.json` files carry a `[package.metadata.release]`-class
config (every `crates/*/Cargo.toml` does, feeding `cargo-release`'s `no-dev-version`/
`tag-name`), and `crates/*` additionally inherit `version.workspace = true`, checked by
`check-workspace.sh`'s "version inherited" rule (wired into `gate.sh`, currently `ok`). The
npm side has no analogous inheritance or gate.

**Root cause:** these four `package.json` files are new this sprint (W0-S7). The parity
they currently show is a one-time human/agent act, not a maintained invariant. The
automated release pipeline (`release.yml`) has a fixed, explicit file list it bumps and
that list does not include these; nothing else in the toolchain checks version fields at
all (`check-deps.mjs`'s three rules never look at `version`; `check-workspace.sh` only
walks Cargo workspace members).

**Why this matters:** it will not manifest until the next version cut — which is exactly
why it's easy to miss at a close audit and exactly why it needs to be on record now rather
than discovered as a surprise drift in v6.4.6. Lower severity than Finding 1 because
nothing is broken today and all four packages are `"private": true` (never published,
limiting blast radius to internal tooling/documentation-accuracy rather than a public
version-resolution failure).

**Confidence:** HIGH — direct greps against the actual release workflow and the actual
package.json files; no inference.

## Verifications (hypotheses disproved)

1. **Hypothesis:** `crates/cli` reaches directly into `shepherd-core`/`shepherd-registry`/`shepherd-render`, bypassing the `sdk` umbrella (a decision-9 violation). **Falsification:** `cargo tree -p shepherd-cli --depth 1` shows exactly one first-party dependency, `shepherd v6.4.5 (crates/sdk)` (all other deps — `anyhow`, `clap`, `config`, `serde`, `serde_json`, `thiserror`, `tracing`, `tracing-subscriber` — are third-party); `grep -rn shepherd_core\|shepherd_registry\|shepherd_render crates/cli/src crates/cli/bin` → 0 hits. Re-run at finalization: identical tree output. **Disproved** — decision 9 holds cleanly on the Rust side.

2. **Hypothesis:** `crates/cli`'s binary name `shepherd` (from `[[bin]] name = "shepherd"`) collides with `bin/shepherd` (the bash wrapper) if the Rust binary is ever installed via `cargo install`, silently shadowing the Python-backed CLI on `PATH`. **Falsification:** every runtime caller of the CLI (`packages/harness-claude/src/guard-serve-engine.mjs:129`, `packages/harness-pi/src/extension.ts:155`, `packages/harness-pi/src/guard-client.ts:120`) spawns the CLI by absolute path to `bin/shepherd`, never a bare `shepherd` relying on `PATH` resolution; same confirmed across `hooks/scripts/*.sh` and `skills/context/scripts/*.sh`. **Disproved as a live risk** — the two binaries can coexist because nothing resolves the name via `PATH`.

3. **Hypothesis:** `crates/core/src/run.rs` naming `services/cli/shepherd_cli/models_run.py` as its "behavioral oracle" is a circular authority — the Rust engine depends on the Python CLI's behavior, which might in turn depend on Rust. **Falsification:** the doc comment (`crates/core/src/run.rs:6-36`) is explicit that this is a one-directional, documentation-level fidelity relationship (byte-for-byte canonical JSON, `extra=allow` round-trip) with a stated, narrower scope than the Python module (the legacy-shape migration layer is explicitly NOT ported here). `grep -rn "packages/harness\|crates/" services/cli/shepherd_cli/*.py` shows only comments citing the Rust/npm side for historical traceability (e.g. `predicates.py` documents it was ported FROM `packages/harness-codex/src/predicates.mjs`, which is now confirmed deleted — `ls packages/harness-codex/src/predicates.mjs` → No such file or directory, reconfirmed at finalization). Seed §113-123 names this a CRITICAL, explicitly time-boxed deliverable ("Conformance oracle frozen from the Python CLI") with a stated acceptance/exit (`conformance/run.sh --impl=rust --suite=run-state` byte-clean against the python oracle). **Disproved as circular** — this is a sound, precedented "golden master" port pattern with a documented exit, not a finding.

4. **Hypothesis:** `conformance/run.sh --impl=rust` reporting "0 cases, exit 1" is itself a tenth "gate that cannot fail." **Falsification:** ran it directly — `conformance --impl=rust: FAIL -- 0 cases implemented (Rust port not yet built -- W1-W3)`, exit 1. This is the correct counter-example to the sprint's dominant defect class: it fails LOUDLY and names why, rather than passing vacuously on an empty case count. **Disproved** — this is the pattern working as intended, not a defect.

5. **Hypothesis:** `crates/cli`'s single `Init` subcommand means every harness's guard decision genuinely has nowhere to route in Rust, so the "count the layers" question in the brief has a real, mappable answer worth stating precisely (not itself a defect — the seed says the Rust port is explicitly incomplete). **Confirmed, not a finding:** `crates/cli/src/cmd.rs` — `pub enum ShepherdCommand { Init(InitCmd) }`, one variant (reconfirmed by direct read at finalization). `services/cli/shepherd_cli/commands/guard.py` has both `eval` and `serve` app commands. For one Codex tool-call guard decision at HEAD, warm-broker path: Codex host → spawns `node hooks/scripts/shepherd_guard.mjs` (per-call, per `hooks.json`) → connects via Unix socket (cross-package import) to `packages/harness-claude/hooks/guard-broker-main.mjs` (a detached, long-lived Node process, spawned once and shared across both harnesses by a deterministic socket path keyed off `content/`'s absolute path) → that broker's `GuardServeEngine` holds one persistent `bin/shepherd guard serve` child → `bin/shepherd` (bash) resolves the Python venv interpreter (cached `stat`, or `poetry env info --executable` on a cache miss) and `exec`s into `python3 -m shepherd_cli guard serve` → `services/cli/shepherd_cli/predicates.py` interprets `content/predicates/*.toml` and returns a JSON line. Two language boundaries (Node→bash→Python, collapsed to one process via `exec`) plus one IPC hop (hook→broker), stress-tested for resilience by the W12 central auditor's independent `kill -9` on the live engine PID (4ms fail-closed deny, no orphans) — noted here as descriptive context for Finding 1, not a separate finding: the depth of the stack is a known, accepted, and tested consequence of the Rust guard port not existing yet, which the brief explicitly rules out of scope.

## Open questions

- None rise to a finding-worthy ambiguity. The one soft item: `packages/harness-pi/package.json`'s description text ("a genuine second guard interpreter, not a file copy") reads as slightly stale against `extension.ts`'s actual wiring (`pi.on('tool_call', ...)` relays through the same `GuardClient`/`bin/shepherd guard serve` path Claude and Codex use) — this is a documentation-accuracy question for `code-quality`, not a dependency-topology defect, and is noted here only so it isn't silently dropped between concerns.

## Pattern delta

N/A — pattern-delta tracking (severity vs prior, 3-sprint trend) is scoped to the
`completeness`/`close`-mode auditor per the audit contract; not duplicated here.

## Grade

D

## Grade rationale

One CRITICAL, unaddressed finding: a live runtime dependency edge (`harness-codex` →
`harness-claude`) that the sprint's own gate (`check-deps.mjs`, a genuinely well-built,
falsifiable checker) correctly flags as forbidden, introduced in the sprint's own closing
commit, never re-checked, and wired into no pipeline that would have caught it. Per the
rubric this is exactly "D — CRITICAL findings unaddressed," not a proportional average
against the concern's real strengths. And there are real strengths worth stating plainly
so the D isn't misread as "the sprint's dependency work is bad": decision 9 holds cleanly
and is well-gated on the Rust side (`crates/cli` → `shepherd` sdk only, confirmed by
`cargo tree` and `check-workspace.sh`, both wired into `gate.sh` and CI); `packages/compiler`
and `packages/harness-pi` are clean; the Python "behavioral oracle" relationship is a sound,
time-boxed port pattern with a stated exit, not a circular dependency; and
`conformance/run.sh --impl=rust` is the sprint's own best example of a gate failing
honestly instead of vacuously. The one CRITICAL finding is narrow in scope (one edge, one
package pair) but structurally serious (it breaks the exact thing GH #280's acceptance
item 6 and the seed's decision 9 promise, in the one place — a live security-relevant
PreToolUse guard hook — where a silent break has the highest cost), and it shipped without
detection because the gate purpose-built to catch it was never connected to anything that
runs automatically. Fix is scoped and named (GH #290); this is not a theme-abandoned F,
and it is not a gates-broken-at-HEAD F either — the gates that exist and run are green;
the gate that would have caught this simply never runs.

## Cache telemetry

N/A — this section is scoped to the `completeness` concern in the audit contract; not
duplicated here to avoid a second, redundant `shctx query cache-usage` run against the
same registry mid-swarm.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 18 (status: delivered)
- Concern: dependency-topology
- Mode: close
- Files reviewed: 15 (+ ~25 commands run, plus a finalization re-verification pass)
- Findings: CRITICAL=1, HIGH=0, MEDIUM=1, LOW=0
- Verifications (disproved): 5
- Open questions: 1 (documentation-accuracy nit, not a topology finding)
- GH issues filed: #290
- Grade: D
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/close-dependency-topology.md
- Hot-fix-lane recommendations: 1 (Finding 1 — resolve the harness-codex/harness-claude
  coupling and wire check-deps.mjs into scripts/gate.sh before the next patch cut; not a
  same-day blocker since nothing public consumes the Codex adapter standalone yet, but it
  should not survive to a second sprint unaddressed)
- Sprint-pattern entry: skipped (dependency-topology concern; pattern-delta tracking is
  scoped to the completeness auditor per the audit contract)
- Agent ID + timestamp: shepherd:auditor (dependency-topology) @ 2026-08-14T09:25:00Z
```
