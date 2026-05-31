# Scope-scale workload (`/shepherd:spawn --scope`) (v5.1.6+)

The `--scope` flag on `/shepherd:spawn` declares the **workload scale** for
a spawn session. It composes orthogonally with `--parallel <N>` (how-many)
and supersedes `--auto` (which becomes an alias for `--scope patch`).

This doctrine defines the four scope values, their sprint enumeration, the
preflight gating (especially for the resource-heavy options), and how scope
composes with parallel fanout.

The 4-tier roadmap in `doctrines/version-scale-roadmap.md` is the scale
source-of-truth. `--scope` operationalizes those tiers as concrete dispatch
shapes.

> **Scope is workload-scale, NEVER a quality bar (binding, v6.0.0).** A
> `--scope` value declares HOW MANY sprints a spawn session walks; it does
> NOT permit a planter to defer or downscope seed content, and it does NOT
> permit a conductor to come up short on lane delivery, gate honesty, or
> close-grade thresholds. "It's just a patch" is not a valid excuse to
> deliver less than what the seed promises. The seed is ground truth; the
> scope flag is a scale label only. See `version-scale-roadmap.md` opening
> note for the canonical statement.

---

## I. The four scope values

```
sprint  → 1 sprint                        (default)
patch   → ~sprints_per_patch (default 10)
minor   → ~patches_per_minor × sprints_per_patch (default ~100)
version → ~minors_per_major × patches_per_minor × sprints_per_patch (default ~1000)
```

### `--scope sprint` (default)

- One `dev.N` sprint. Current `/shepherd:spawn` base behavior.
- No special preflight beyond Checks 1–5.
- Composes with `--parallel <N>` only if N seeds exist within the same
  patch (current behavior).

### `--scope patch`

- Full patch from `dev.0` (or current `dev.N`) through `dev.LAST`.
- Equivalent to the retired `--auto` flag in v5.1.5 and earlier (auto
  remains as an alias — see §V).
- Preflight: identify dev.LAST per `shepherd.toml [version].dev_total` or
  by seed count or by operator prompt (current `--auto` Check 5).
- Composes with `--parallel <N>` to fan out across the patch's disjoint
  sprints (current `--parallel` semantics, dev-order merge gate enforced).

### `--scope minor`

- Multiple patches under the current minor version (e.g., v5.1.6 → v5.1.7
  → v5.1.8 → … → v5.1.LAST_PATCH).
- **Experimental.** Preflight requires operator to type the literal string
  `confirm minor` before any spawn fires.
- Spawn fires one patch at a time; rollover to the next patch follows the
  patch-rollover cascade (per `references/branching-model.md §IV`).
- Composes with `--parallel <N>` BUT capped at N ≤ 2 — cross-patch
  parallel work is high-conflict. v5.1.6 ships with sequential-only
  enforcement; parallel deferred.

### `--scope version`

- Multiple minors under a major version (e.g., v5.* → v6 boundary).
- **Highly experimental.** Preflight requires operator to type the literal
  string `confirm version` AND surfaces a hard-pause warning block:
  ```
  /shepherd:spawn --scope version: ESTIMATED 1000-sprint walk.
  This will consume:
    - Token budget: ~$N estimated
    - Wall time: ~M days estimated
    - GitHub API rate budget: ~K calls
  Confirm by typing the exact phrase: confirm version
  ```
- Sequential-only in v5.1.6. Parallel-fan minor walks deferred.

---

## II. Scope × parallel composition matrix

| `--scope` | `--parallel 1` | `--parallel 2` | `--parallel 3-4` |
|---|---|---|---|
| `sprint` | Single sprint (base) | Two sprints from current patch (file-disjoint) | Three-four sprints, dev-order merge gate |
| `patch` | Sequential autopilot | Fanout 2 from current patch | Fanout 3-4 from current patch |
| `minor` | Patch-by-patch sequential | Refused (v5.1.6) | Refused (v5.1.6) |
| `version` | Minor-by-minor sequential | Refused (v5.1.6) | Refused (v5.1.6) |

The current patch is the unit of concurrent fanout. Cross-patch fanout
(scope=minor + parallel>1) is deferred — the merge gate across patches has
not been validated.

---

## III. Preflight gates

`/shepherd:spawn` preflight adds the following checks specific to `--scope`:

### Check 6 — Scope sprint enumeration

For every scope value, enumerate the concrete sprint list before any spawn:

```
[SCOPE ENUMERATION]
Scope: {scope}
Patch boundary: dev.0..dev.{LAST}
Concrete sprint list:
  - v{X}.{Y}.{Z}-dev.0  → {paths.plans}/v{XYZ}-dev0.seed.md       [seed: present]
  - v{X}.{Y}.{Z}-dev.1  → {paths.plans}/v{XYZ}-dev1.seed.md       [seed: present]
  - ...
  - v{X}.{Y}.{Z}-dev.{LAST}  → ...                                [seed: MISSING]

Total sprints: {N}
Missing seeds: {M}
```

If any required seed is missing, refuse the spawn and direct the operator
to `/shepherd:plant {sprint_slug}` for each gap.

### Check 7 — Scope confirmation (for minor/version)

- `--scope minor` → require operator to type `confirm minor`
- `--scope version` → require operator to type `confirm version` AND
  display the resource-estimate block (per §I `--scope version`).
- Confirmation phrase is case-insensitive but must be exact (no
  punctuation, no extra words).

### Check 8 — Resource estimate (info-only)

Always surface an info block before spawning:

```
[RESOURCE ESTIMATE]
Sprints: {N}
Estimated wall time: ~{N × avg_sprint_minutes} minutes
Estimated GitHub API calls: ~{N × avg_api_per_sprint}
Worktree count peak: {parallel_N} concurrent worktrees
```

Numbers are based on the project's prior-sprint averages (from
`shctx adapt priors --metrics` when n>0, else conservative defaults).

---

## IV. Sprint enumeration algorithm

Given `--scope <value>` and the current branch context, the planter (root
shepherd in spawn mode) enumerates the concrete sprint list:

```python
def enumerate_sprints(scope, current_branch, shepherd_toml):
    X, Y, Z, N = parse_current_branch(current_branch)
    sprints_per_patch = shepherd_toml["branching"]["sprints_per_patch"]  # default 10
    if scope == "sprint":
        return [current_sprint(X, Y, Z, N)]
    if scope == "patch":
        last_n = resolve_dev_last(shepherd_toml, X, Y, Z)
        return [sprint(X, Y, Z, i) for i in range(N, last_n + 1)]
    if scope == "minor":
        last_patch_z = resolve_last_patch_in_minor(X, Y)
        results = []
        for z in range(Z, last_patch_z + 1):
            last_n = resolve_dev_last(shepherd_toml, X, Y, z)
            start_n = N if z == Z else 0
            for i in range(start_n, last_n + 1):
                results.append(sprint(X, Y, z, i))
        return results
    if scope == "version":
        # similar, walking minors then patches then dev.N
        ...
```

`resolve_dev_last` precedence (existing `--auto` Check 5 logic):
1. `shepherd.toml [version].dev_total` if present
2. Seed count in `{paths.plans}/` matching the patch pattern
3. Operator prompt

`resolve_last_patch_in_minor` requires either explicit config
(`[version].patch_total`) or operator prompt. v5.1.6 defaults to "prompt
operator if config absent".

---

## V. Migration from `--auto`

`--auto` is preserved as an alias for `--scope patch` to avoid breaking
operator muscle memory:

```
/shepherd:spawn --auto              ≡  /shepherd:spawn --scope patch
/shepherd:spawn --auto --parallel 4 ≡  /shepherd:spawn --scope patch --parallel 4
```

Internal logic is identical. The command file recognizes both flag forms
and normalizes to `--scope patch` for downstream processing.

`--auto` is a **preserved alias for `--scope patch`** — the previously documented
deprecation (v5.2.0) and removal (v6.0.0) timeline is **rescinded**. The alias
remains live indefinitely to avoid breaking operator muscle memory.

---

## VI. Failure modes specific to scope

| Code | Trigger | Recovery |
|---|---|---|
| `SCOPE-SEED-GAP` | Required seed missing for an enumerated sprint | Operator runs `/shepherd:plant` for each gap |
| `SCOPE-CONFIRMATION-MISSING` | minor/version scope without confirmation phrase | Re-invoke with confirmation |
| `SCOPE-VERSION-OVER-BUDGET` | Resource estimate exceeds `[autorun].max_token_budget` if configured | Operator opts in OR narrows scope |
| `SCOPE-PARALLEL-OVERREACH` | `--scope minor/version` combined with `--parallel >1` in v5.1.6 | Refuse; re-invoke without `--parallel` |
| `SCOPE-DEV-LAST-UNKNOWN` | Cannot resolve dev.LAST and operator declines to prompt | Refuse; operator configures `[version].dev_total` |

---

## VII. Composition with root-shepherd modes

When `--scope > sprint`, the root shepherd cycles through its three modes
(idle / dispatch / coordinate per `root-shepherd-orchestration.md §II`)
multiple times — once per sprint in the enumerated list:

```
[ROOT IDLE] → enumerate sprint K
  [DISPATCH] spawn teammate for sprint K
  [COORDINATE] babysit; wave-complete; materialize artifacts
  [DISPATCH] (if applicable) re-spawn for hot-fix wave
  [COORDINATE] close-swarm
[ROOT IDLE] → inter-sprint cleanup (planter delegation)
[ROOT IDLE] → enumerate sprint K+1
...
```

The cleanup between sprints is the planter's responsibility (per
`agents/planter.md §Sprint rollover --auto mode`). The shepherd profile
delegates to planter via inline mode-switch when seed work is needed.

---

## VIII. See also

- `doctrines/root-shepherd-orchestration.md` — root-tier responsibilities + modes
- `doctrines/dispatch-tier-separation.md` — who-can-dispatch-whom matrix
- `doctrines/version-scale-roadmap.md` — 4-tier scale (dev/patch/minor/major)
- `references/branching-model.md` — patch + sprint rollover cascade
- `commands/spawn.md §--scope flag` — invocation entry point
- `agents/planter.md §Sprint rollover --auto mode` — inter-sprint cleanup
