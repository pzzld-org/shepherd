---
title: Discovery — v5.1.0 internal consistency audit
date: 2026-05-15
discovery_id: v51-readiness
sprint: v5.1.0
sources_consulted: 15
tool_calls_used: 8
time_used_minutes: 11
---

# Discovery — v5.1.0 Framework Consistency Audit

## Sources

- `agents/discovery.md` — agent frontmatter + system prompt for @discovery
- `agents/auditor.md` — agent frontmatter + system prompt for @auditor (v5.1.0 rewrite)
- `skills/shepherd/SKILL.md` — conductor quick reference (v5.1.0)
- `skills/shepherd/flock.md` — per-agent dispatch reference
- `skills/shepherd/pipeline.md` — Stage Graph + node taxonomy
- `skills/shepherd/planter.md` — planter behavioral contract
- `skills/shepherd/references/agent-briefs.md` — copy-paste brief templates
- `skills/shepherd/doctrines/discovery-readonly.md` — discovery contract doctrine
- `skills/shepherd/doctrines/intro-combo-wave.md` — INTRO-COMBO-WAVE doctrine
- `skills/shepherd/doctrines/auditor-hypothesis-driven.md` — hypothesis-driven auditor doctrine
- `skills/shepherd/doctrines/sprint-as-patch.md` — sprint-as-patch doctrine
- `skills/shepherd/doctrines/hook-event-log.md` — hook event log doctrine
- `skills/shepherd/doctrines/preflight-doctor.md` — preflight-doctor doctrine
- `skills/shepherd/doctrines/README.md` — doctrine index
- `CHANGELOG.md` — v5.1.0 changelog entries

---

## Findings

### (a) Flock size: is "six agents" consistent everywhere?

| File | Claim | Consistent? | Notes |
|---|---|---|---|
| `agents/discovery.md` frontmatter | "Sixth lane in the shepherd flock." [line 7] | ✅ |  |
| `agents/auditor.md` frontmatter | No explicit count; lists "flock" without number [line 9] | ⚠ | References "closed at six" only implicitly via behavior |
| `SKILL.md` frontmatter description | "Six-agent flock (engineer, critic, coder, auditor, worker, discovery)" [line 6] | ✅ |  |
| `SKILL.md` §I table | Six rows enumerated explicitly [lines 82–87] | ✅ |  |
| `SKILL.md` §I text | "The flock is **closed**. Never dispatch outside these five" [line 112] | ❌ **CONTRADICTION** | Still says "five" — holdover from pre-v5.1.0 text; should say "six" |
| `SKILL.md` anti-pattern #23 | "discovery is read-only-comprehension" — implies sixth lane without explicit count [line 337] | ✅ |  |
| `flock.md` §I | Lists six agents with paths [lines 17–22]; preamble says "closed at six" [line 41] | ✅ |  |
| `planter.md` §I Identity paragraph | "The flock is closed at six lanes (v5.1.0+: engineer, critic, coder, auditor, worker, discovery)" [line 8] | ✅ |  |
| `planter.md` §XIV Inheritance | "The flock is closed (planter is not a sixth agent — it's a mode)" [line 417] | ⚠ | Says "not a sixth agent" in context of describing planter's inheritance — slightly ambiguous phrasing (planter is not the sixth agent; discovery is), but the parenthetical clarifies correctly |
| `pipeline.md` §II DISCOVERY node | New DISCOVERY and INTRO-COMBO-WAVE node types added [lines 69–70] | ✅ |  |
| `doctrines/discovery-readonly.md` | "sixth lane in the shepherd flock (v5.1.0+)" [line 3] | ✅ |  |
| `doctrines/README.md` doctrine index | Lists `discovery-readonly.md` as new v5.1.0 doctrine [line 83] | ✅ |  |
| `CHANGELOG.md` | "sixth lane in the flock" [line 17] | ✅ |  |

**Primary contradiction found:** `SKILL.md` line 112 reads "Never dispatch outside these **five** — no `general-purpose`, `Explore`, `Plan`..." — this "five" is a stale holdover from the pre-discovery flock. All other files correctly use "six". [source: `SKILL.md:112`]

---

### (b) Discovery's tool boundary and report shape: is it consistent?

| Dimension | agents/discovery.md | doctrines/discovery-readonly.md | flock.md §@discovery | references/agent-briefs.md | Consistent? |
|---|---|---|---|---|---|
| **Write tool restriction** | "Write is path-restricted to `{paths.reports}/<date>-discovery-<id>.md`" [line 70–71] | "Write to `{paths.reports}/<date>-discovery-<id>.md`" [line 35] | "structured DISCOVERY REPORT written to `{paths.reports}/<date>-discovery-<id>.md`" [line 307] | `[OUTPUT-PATH] {paths.reports}/{date}-discovery-{id}.md` [line 410] | ✅ |
| **Edit tool** | "NEVER `Edit`" [line 73] | "Edit any file → ❌" [line 37] | implied by "Read-only" language | Not mentioned | ✅ |
| **Agent dispatch** | "NEVER dispatch other agents" [line 75] | "Dispatch other agents → ❌" [line 39] | "NEVER mutates state. No Edit, no MCP write, no dispatch" [line 308–309] | `[NON-GOALS] Do NOT dispatch other agents` [line 421] | ✅ |
| **State-modifying Bash** | Forbidden list with examples [lines 79–85] | "Run state-modifying Bash → ❌" [line 38] | Read-only language | "[NON-GOALS] Do NOT run state-modifying Bash (rm, mv, >, >>, tee, gh issue create, etc.)" [line 422] | ✅ |
| **Grading / severity** | "NEVER grade" [line 57] | "Grade / score / assign severity → ❌" [line 42] | "Never grades (auditor's lane)" [line 309] | Not mentioned | ✅ |
| **Report shape: frontmatter** | YAML block with `title`, `date`, `discovery_id`, `sprint`, `sources_consulted`, `tool_calls_used`, `time_used_minutes` [lines 209–216] | Same YAML block, same fields [lines 84–91] | Not specified | Not specified | ✅ — two files agree exactly |
| **Report shape: required sections** | `## Sources`, `## Findings`, `## Open questions`, `## Confidence`, `## Suggested follow-ups (optional)` [lines 218–238] | Same five sections (optional last) [lines 94–110] | "Findings + Open questions + Confidence minimum" [line 321] | "Required sections: ## Sources, ## Findings, ## Open questions, ## Confidence" [line 416] | ✅ — minor phrasing variation but no contradiction |
| **Return message shape (DISCOVERY REPORT block)** | Nine-field block defined [lines 259–271] | Not defined (points to agents/discovery.md) | Not defined | Not defined | ✅ — single source of truth in agents/discovery.md |
| **Parallel cap** | Not stated explicitly in system prompt body | "Cap: **5 concurrent discoveries per Agent batch**" [lines 71–72] | "Cap: 5 concurrent" [line 295] | Not stated | ⚠ — `agents/discovery.md` does not mention the cap in the Parallel-safety section [lines 323–330] despite the doctrine and flock.md both specifying 5; the agent system prompt omits this constraint |
| **MCP write tools blocked** | Blocked by naming forbidden patterns [lines 86–90] | "MCP write (issue_write, apply_migration, ...) → ❌" [line 40] | Read-only language | Not mentioned | ✅ |

**One gap found:** The 5-concurrent-discoveries cap appears in `doctrines/discovery-readonly.md` [line 71] and `flock.md` [line 295] but is absent from the `agents/discovery.md` body's parallel-safety section [lines 323–330]. The agent's own system prompt does not know the cap. [source: `agents/discovery.md:323–330`, `doctrines/discovery-readonly.md:71`, `flock.md:295`]

---

### (c) Intro-wave default composition: is it consistent?

| File | Stated default composition | Consistent? |
|---|---|---|
| `doctrines/intro-combo-wave.md` §Default composition | 3 discoveries (prior-close-audit-summary, canonical-types-freshness, gh-state-inventory) + 2 intro auditors (regression, carry-forward-disposition) = **5 lanes total** [lines 44–49] | ✅ Baseline |
| `planter.md` §IV INTRO-COMBO-WAVE planning | "Default composition: 3 discoveries (prior-close-audit-summary, canonical-types-freshness, gh-state-inventory) + 2 intro auditors (regression, carry-forward-disposition)" [lines 114–118] | ✅ |
| `SKILL.md` §III §1 INTRODUCTION | "dispatch discoveries + intro-mode auditors in parallel BEFORE the engineer's MESH... discoveries absorb prior-state ingestion... intro auditors surface regressions and carry-forward drift" [lines 170–174] | ✅ — consistent in substance, doesn't restate exact count |
| `SKILL.md` checklist item | "**INTRO-COMBO-WAVE dispatched (M+ sprints)** — discoveries + intro auditors in ONE Agent batch BEFORE @engineer. Reports written to `{paths.reports}/<date>-discovery-*.md` and `{paths.reports}/<date>-intro-audit-*.md`." [line 184] | ✅ |
| `flock.md` §@auditor | "SWARM — minimum 3, maximum 5. Always parallel. Split by concern, never by file" [line 51] — describes close-time; intro mentioned in `@auditor` section as "OR 1–2 lane intro" [line 85 SKILL.md] | ✅ |
| `agents/auditor.md` §Modes table | `regression` and `carry-forward-disposition` are both intro-mode concerns [lines 113–114] | ✅ |
| `references/agent-briefs.md` INTRO-COMBO-WAVE dispatch block | Lists 5 Agent calls: 3 @discovery + 2 @auditor intro-mode [lines 638–648] | ✅ |
| `pipeline.md` §II INTRO-COMBO-WAVE node | "Parallel batch of `@discovery` + `@auditor` (intro-mode)" [line 70] | ✅ |
| `doctrines/intro-combo-wave.md` §Configuration toml | `default_discoveries = ["prior-close-audit-summary", "canonical-types-freshness", "gh-state-inventory"]` and `default_intro_auditors = ["regression", "carry-forward-disposition"]` and `parallel_max = 5` [lines 57–65] | ✅ |
| `agents/auditor.md` example block | Conductor says "Dispatching the INTRO-COMBO-WAVE in one Agent batch: 3 @discovery agents ... + 2 @auditor agents in intro mode" [lines 29–33] | ✅ |
| `SKILL.md` §I `@auditor` row | "SWARM of 3–5 (close) OR 1–2 (intro)" [line 85] | ✅ |

**Wave composition: fully consistent across all sources.** No contradictions found.

One terminological note: `doctrines/intro-combo-wave.md` states the wave fires for M+, skipping XS (`disable_for_tshirt = ["XS"]`) [line 63]. `SKILL.md` says "Skip the wave for XS sprints" [line 176]. Both agree. `planter.md` says "Sprint seeds with size M+ MUST include an `intro_wave:` section" [line 112], which is consistent (XS is excluded, S is optional). No contradiction. [source: `doctrines/intro-combo-wave.md:63`, `SKILL.md:176`, `planter.md:112`]

---

### (d) Auditor's hypothesis-driven contract: is it consistent?

| Dimension | agents/auditor.md | doctrines/auditor-hypothesis-driven.md | Other files | Consistent? |
|---|---|---|---|---|
| **Step 1: load systematic-debugging** | "Before reading the brief, invoke: `Skill(skill="superpowers:systematic-debugging")`" [lines 58–62] | "Step 1 — Load systematic-debugging discipline. Invoke: `Skill(skill="superpowers:systematic-debugging")`" [lines 186–188] | `SKILL.md` anti-pattern #26: "Auditor files finding without Hypothesis + Falsification + Confidence → conjecture, not finding" [line 340]; `references/agent-briefs.md` auditor brief: "Read your full system prompt at `${CLAUDE_PLUGIN_ROOT}/agents/auditor.md`" | ✅ |
| **Three required finding fields** | "Hypothesis + Falsification attempt + Confidence" required on every finding [lines 143–172] | Same three-field contract [lines 35–74] | `SKILL.md` anti-pattern #26 [line 340] | ✅ |
| **Per-finding shape** | Full shape given with all sub-fields [lines 147–171] | Same shape with same sub-fields [lines 35–74] | `references/agent-briefs.md` does not reproduce the shape (just says "per v5.1.0 hypothesis-driven shape") — acceptable, defers to agent file | ✅ |
| **LOW confidence → Open questions** | "LOW-confidence findings DO NOT GET FILED as GH issues. They land in `## Open questions`" [lines 176–177] | "LOW-confidence findings SHOULD NOT be filed as findings — they belong in the report's `## Open questions` section" [lines 80–82] | Consistent in substance | ⚠ — minor wording discrepancy: `agents/auditor.md` says "DO NOT GET FILED as GH issues" (but still appear as findings), while `auditor-hypothesis-driven.md` says "SHOULD NOT be filed as findings" (i.e., don't appear as findings at all). These are subtly different instructions about where LOW findings land. |
| **Verifications section** | "## Verifications (positive findings worth noting)" section required for disproved hypotheses [lines 179–194] | Same `## Verifications` section with same purpose [lines 153–166] | ✅ | ✅ |
| **Bayesian weighting from sprint-patterns** | "Read `<ns>/sprint-patterns.md` at dispatch time" [lines 199–211] | "The auditor reads `<ns>/sprint-patterns.md` at dispatch time" [lines 125–149] | ✅ | ✅ |
| **Three auditor modes** | `close`, `regression`, `carry-forward-disposition` [lines 106–115] | Not enumerated in this doctrine (defers to `agents/auditor.md` + `intro-combo-wave.md`) | `intro-combo-wave.md` enumerates same three [lines 72–115] | ✅ |
| **Intro modes: no grade** | "No grade emitted. Findings list only." for both `regression` [line 379] and `carry-forward-disposition` [line 395] intro modes | Anti-pattern #5: "Auditor in intro mode grading. Intro mode ... surfaces findings, NEVER grade." [lines 221–222] | `intro-combo-wave.md`: "Grade: none — intro-mode auditors don't grade" [lines 94, 111] and anti-pattern #2 [lines 171–173] | ✅ |
| **Grade rubric: sprint-as-patch calibration** | "per `doctrines/sprint-as-patch.md`, each sprint is patch-equivalent in scope" [lines 290–295] | Not in this doctrine (cross-reference in `See also`) | `doctrines/sprint-as-patch.md` §For the auditor gives matching rubric anchors [lines 89–102] | ✅ |
| **Report shape frontmatter additions** | Three new frontmatter fields: `mode`, `methodology`, `prior_class_priors` [lines 219–226] | Same three fields [lines 200–206] | ✅ | ✅ |
| **`flock.md` anti-patterns** | Not covered | Not covered | `flock.md` does not list hypothesis-driven as an anti-pattern (it defers to agents/auditor.md) | ✅ — acceptable |

**Minor wording discrepancy on LOW findings:** `agents/auditor.md` lines 176–177 says LOW-confidence findings "DO NOT GET FILED as GH issues" (implying they still appear as findings in the report body, just without GH tickets). `auditor-hypothesis-driven.md` lines 80–82 says they "SHOULD NOT be filed as **findings**" (implying they should be in `## Open questions` instead, not even as findings). [source: `agents/auditor.md:176–177`, `doctrines/auditor-hypothesis-driven.md:80–82`]

---

### (e) Cross-cutting: undefined terms and missing cross-references

| Item | Location | Description |
|---|---|---|
| `{paths.reports}` format discrepancy | `doctrines/discovery-readonly.md` [line 35] uses `{paths.reports}/<date>-discovery-<id>.md`; `flock.md` [line 307] uses the same; `references/agent-briefs.md` [line 410] uses `{paths.reports}/{date}-discovery-{id}.md` — note `<date>` vs `{date}` and `<id>` vs `{id}` | Minor: two path placeholder styles (`<x>` vs `{x}`) coexist across files; not a contradiction, both refer to the same token |
| `RESEARCH-SUMMARY-DISCOVERY` pattern | Listed in `agents/discovery.md` §Use-case catalog [line 306–308] as "Pattern F" and in `flock.md` [line 302] as `RESEARCH-SUMMARY-DISCOVERY`, but `references/agent-briefs.md` only provides templates D-A through D-F where D-F is `DOCTRINE-RECONCILIATION-DISCOVERY` not `RESEARCH-SUMMARY-DISCOVERY` | The agent-briefs.md defines D-A (prior-close-audit-summary), D-B (canonical-types-freshness), D-C (gh-state-inventory), D-D (pre-hotfix error-cluster), D-E (architecture-discovery), D-F (doctrine-reconciliation). Neither D-E nor D-F maps to `RESEARCH-SUMMARY-DISCOVERY` (Pattern F). The Pattern F / RESEARCH-SUMMARY-DISCOVERY brief template is **absent** from `references/agent-briefs.md`. [source: `agents/discovery.md:306–308`, `references/agent-briefs.md:426–585`] |
| `MCP-STATE-DISCOVERY` brief template | Listed in `agents/discovery.md` as "Pattern E" [lines 302–305] and `flock.md` [line 301] but no corresponding brief template appears in `references/agent-briefs.md` | Similar to above — only six templates defined (D-A through D-F) and none maps to MCP-STATE-DISCOVERY (Pattern E). [source: `agents/discovery.md:302–305`, `flock.md:301`] |
| `ARCHITECTURE-DISCOVERY` naming | `agents/discovery.md` calls it "Pattern C — ARCHITECTURE-DISCOVERY" [line 298]; `flock.md` calls it `ARCHITECTURE-DISCOVERY` [line 299]; `references/agent-briefs.md` calls it `D-E — ARCHITECTURE-DISCOVERY` [line 534] | All three point to the same use-case; naming is consistent |
| `sprint_branch` variable in discovery context | `doctrines/discovery-readonly.md` report shape shows `sprint: {sprint_branch}` in frontmatter [line 90]; `agents/discovery.md` [line 211] shows the same — consistent | ✅ |
| `INTRO-COMBO-WAVE` vs `PRE-MESH-DISCOVERY` anti-pattern | `doctrines/intro-combo-wave.md` anti-pattern #4 [lines 176–178]: "PRE-MESH-DISCOVERY duplicate to intro wave. Pick one." `agents/discovery.md` §Pattern A names "PRE-MESH-DISCOVERY (most common)" [line 285]; `flock.md` @discovery section lists "PRE-MESH-DISCOVERY (in INTRO-COMBO-WAVE)" [line 297] | Consistent — `flock.md` clarifies PRE-MESH-DISCOVERY fires *within* the INTRO-COMBO-WAVE, not separately |
| `discovery_capture.sh` hook reference | `agents/discovery.md` mentions "The conductor's `discovery_capture.sh` hook" [line 274]; `doctrines/discovery-readonly.md` references `shctx discovery search` [line 146]; `CHANGELOG.md` defers `discovery_capture.sh` to v5.1.1 [lines 39–46] | The hook is referenced as operational in `agents/discovery.md` but deferred to v5.1.1 per CHANGELOG. No contradiction in doctrine (agents/discovery.md does not claim the hook exists *now*), but a future sprint must deliver it. |
| `doctrines/auditor-readonly.md` cross-reference | `agents/auditor.md` [line 71] references "per `doctrines/auditor-readonly.md`"; `doctrines/README.md` lists `auditor-readonly.md` [line 85] — but this source list (from the brief) does not include `auditor-readonly.md`. This is not a contradiction — the file exists and is referenced by name; we simply did not read it in this discovery. | Not a finding — source not in brief scope |
| `PAUSE-FOR-DEPENDENCY` doctrine | Referenced in `SKILL.md` [line 414] and `pipeline.md` as an entry in §XI See also; in scope as context but not a new v5.1.0 doctrine per se (it was v5.0.9) | ✅ — correct version attribution in CHANGELOG |

---

## Open questions

- Should `agents/discovery.md`'s parallel-safety section [lines 323–330] explicitly state the "Cap: 5 concurrent" rule, since the agent's own prompt currently omits it? The agent would be unable to self-enforce the cap without seeing it in its own system prompt.

- The LOW-confidence findings wording discrepancy (findings vs GH issues): does the intended behavior allow LOW findings to appear in the report body under a `### Finding ... (LOW)` heading without a GH issue, or should they be moved entirely to `## Open questions`? `agents/auditor.md` implies the former; `doctrines/auditor-hypothesis-driven.md` implies the latter.

- Are `RESEARCH-SUMMARY-DISCOVERY` (Pattern F / Pattern E) brief templates intentionally omitted from `references/agent-briefs.md`, or is this a gap to fill in a follow-up sprint?

- `SKILL.md` line 112 ("never dispatch outside these **five**") — is this a known leftover from v5.0.x or was it missed during the v5.1.0 update sweep?

- The `discovery_capture.sh` hook (and related hooks) are deferred to v5.1.1 per CHANGELOG. How does the conductor index DISCOVERY REPORT returns between v5.1.0 and v5.1.1 without the hook? Is the cross-sprint reuse (`shctx discovery search`) expected to be manual in this window?

---

## Confidence

**HIGH** — All 15 source files were fully read. The sources are authoritative (these are the canonical framework files for v5.1.0). Four findings are well-evidenced by specific line citations. No sources conflicted in any way that required inference rather than direct reading. The one ambiguity (LOW-confidence finding placement) exists as two slightly different phrasings in two authoritative files; it is a real discrepancy, not an inferential one.

---

## Suggested follow-ups

- A follow-up discovery reading `agents/discovery.md` §Parallel-safety against the shepherd plugin's hooks.json and bash_guard.sh (once v5.1.1 ships) to verify the cap enforcement is actually wired at the hook layer.
- A follow-up to determine whether the missing D-E (MCP-STATE) and Pattern F (RESEARCH-SUMMARY) brief templates belong in `references/agent-briefs.md`.
- No code changes are proposed here — the above are framed as research questions for the operator or conductor to prioritize.
