---
title: v5.1.7 — SQLite-canonical operational state
date: 2026-05-20
branch: v5.1.7
status: design (operator-approved, scope-tier patch, additive only)
scope_tier: patch  # per doctrines/version-scale-roadmap.md (≤ 10 dev sprints)
supersedes: planning portions of any prior v5.1.7 sketches (none on disk)
closes:
  - "#43 @discovery returns inline-only when brief instructs disk-write"
  - "#44 Intro-mode regression auditor should run shepherd.toml [gates] extras"
  - "#49 Teammate process crashes silently with no diagnostic trace"
  - "#50 Encode per-lane CARGO_TARGET_DIR + --frozen as default in conductor brief"
  - "#51 /shepherd:cleanup command to prune stale/crashed teammate entries"
  - "#52 Subagent stall-loop: critic/auditor announces Write without executing"
verifies-and-may-close:
  - "#45 v5.1.5 teammate-conductor dispatch overreach (resolved in v5.1.6)"
  - "#46 in-process teammates cannot dispatch flock under /shepherd:spawn (upstream)"
triages:
  - "#18..#39 — old issues, classify superseded / still-valid / close-as-stale"
defers:
  - "#47 complete --scope=minor/version semantics → v5.2.0"
  - "#53 SendMessage heartbeat_payload runtime primitive → v5.2.0+ (shctx-side prepared)"
  - "#54 per-package feature-coverage CI gate → axiom-specific, ship as doctrine guidance only"
---

# v5.1.7 — SQLite-canonical operational state

## Problem

Across the v5.1.5/v5.1.6 spawn rollout, six operator-observed defects clustered around
a single architectural pattern: the framework keeps producing new markdown files for
ephemeral operational state (discovery findings, audit findings, escalations,
heartbeats, teammate liveness, crash diagnostics, mailbox payloads) even though
shepherd ships a per-project SQLite registry (`.artifacts/root.db`, WAL mode) that
was designed to be the canonical store for exactly this kind of state.

The result: opaque "did the write happen?" failures (#43, #52), invisible silent
crashes (#49), filesystem-locked heartbeat protocols proposed as more files (#53),
markdown-paraphrase drift in audit cross-references, and operator-visible churn
from generated reports tracked in git.

SQLite-on-disk gives us atomicity, WAL concurrency, queryable structured state,
and indexable liveness — none of which file-based reports provide. The right
shift: **DB is canonical for operational state; files are views materialized on
demand**.

## North star

**Binding rule** (`doctrines/sqlite-canonical-state.md`):

- SQLite is canonical for operational/ephemeral state (teammate liveness,
  heartbeats, mailbox messages, escalations, deliverable promises, structured
  discovery findings, structured audit findings, lane status, wave-gate verdicts).
- Filesystem is canonical for human-authored durable artifacts (CLAUDE.md,
  `agents/*.md`, `commands/*.md`, `skills/**/*.md`, `doctrines/*.md`, specs under
  `.artifacts/docs/specs/`, plans under `.artifacts/docs/plans/`, seeds, CHANGELOG,
  README — anything version-controlled and human-edited).
- Markdown reports are **materialized views** of DB rows via `shctx report <kind>`.
  They are disposable artifacts of the DB, not the canonical store.

Existing markdown report flows continue to work (back-compat); new flows MUST
canonicalize. Existing tables (`mem_entries`, `logs_events`, `artifacts`,
`locks_history`, `index_*`) are unchanged.

## Non-goals (deferred to v5.2.0+)

- Full migration of every existing markdown artifact type to SQLite-canonical
  (only the bug-prone ones in this patch)
- First-class `SendMessage` `heartbeat_payload` runtime primitive (still
  upstream-dependent; we ship the DB-row infrastructure for when/if it lands)
- Cross-patch `--scope=minor` / `--scope=version` enumeration completion (#47)
- Per-package feature-coverage CI gate (#54 — project-specific; ship as
  doctrine guidance only)

## Architecture

```
.artifacts/root.db (WAL, per-project SQLite)
├── existing: projects, sessions, mem_entries, logs_events, artifacts,
│             locks_history, index_{symbols,concepts,issues,prs,releases,milestones}
└── NEW (migration 0007):
    ├── teammates          — identity + liveness + status
    ├── heartbeats         — per-tool-call updates, indexed by ts DESC
    ├── mailbox            — inter-agent messages (kinds: heartbeat_payload,
    │                        escalation, ack, status, generic)
    ├── escalations        — teammate → root surface points
    ├── deliverables       — promise/complete ledger (stall detector)
    ├── discovery_findings — structured discovery output (replaces handoff md)
    ├── audit_findings     — structured audit output (replaces report md)
    └── views: v_teammates_live, v_mailbox_unread_per_recipient,
               v_escalations_open

shctx subcommand surface (new):
    shctx teammate     {register,heartbeat,status,liveness,prune,retire}
    shctx mailbox      {send,recv,ack,stale}
    shctx escalate     {<top-level>,list,resolve}
    shctx deliverable  {promise,complete,stalled}
    shctx discovery    insert
    shctx audit        insert
    shctx report       <kind>          # markdown materializer

agent profile amendments (additive only):
    agents/discovery.md   → MUST `shctx discovery insert` (closes #43)
    agents/critic.md      → promise/complete contract (closes #52)
    agents/auditor.md     → promise/complete contract + intro-mode extras (closes #44, #52)
    agents/conductor.md   → CARGO_TARGET_DIR=target/.lanes/<slug> binding (closes #50)
    agents/shepherd.md    → TEAMMATE-CRASHED halt (closes #49)
    commands/spawn.md     → cargo discipline section
    commands/cleanup.md   → NEW slash command (closes #51)
    doctrines/sqlite-canonical-state.md — NEW

hook integration:
    PostToolUse           → shctx teammate heartbeat (extend existing telemetry)
    TeammateIdle          → status=idle, scan unresolved escalations + stalled deliverables
    deliverable_check.sh  → end-of-turn assertion: promise without completion → stalled
```

## Components

### 1. `skills/context/schema/0007_canonical_state.sql` (NEW)

Schema migration. WAL mode preserved. All new tables additive — no ALTER on
existing tables. Indexed for hot queries (`teammates.status`, `last_seen_at`,
`mailbox.recipient_name WHERE read_at IS NULL`, etc.).

Full schema verbatim:

```sql
BEGIN;

-- Teammate identity + liveness
CREATE TABLE teammates (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  team_name     TEXT NOT NULL,
  teammate_name TEXT NOT NULL,
  agent_type    TEXT NOT NULL,
  session_id    TEXT,
  tmux_pane_id  TEXT,
  spawned_at    INTEGER NOT NULL,
  last_seen_at  INTEGER NOT NULL,
  status        TEXT NOT NULL CHECK(status IN
                  ('booting','active','idle','crashed','retired')),
  metadata      TEXT CHECK(metadata IS NULL OR json_valid(metadata)),
  UNIQUE(project_id, team_name, teammate_name)
);
CREATE INDEX idx_teammates_project_status ON teammates(project_id, status);
CREATE INDEX idx_teammates_last_seen      ON teammates(last_seen_at);

-- Heartbeats
CREATE TABLE heartbeats (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  teammate_id  TEXT NOT NULL REFERENCES teammates(id) ON DELETE CASCADE,
  ts           INTEGER NOT NULL,
  phase        TEXT,
  tool_name    TEXT,
  note         TEXT
);
CREATE INDEX idx_heartbeats_teammate_ts ON heartbeats(teammate_id, ts DESC);

-- Mailbox
CREATE TABLE mailbox (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sender_id       TEXT NOT NULL,
  recipient_name  TEXT NOT NULL,
  kind            TEXT NOT NULL CHECK(kind IN
                    ('heartbeat_payload','escalation','ack','status','generic')),
  payload         TEXT NOT NULL CHECK(json_valid(payload)),
  target_file     TEXT,
  requires_ack    INTEGER NOT NULL DEFAULT 0,
  sent_at         INTEGER NOT NULL,
  read_at         INTEGER,
  acked_at        INTEGER,
  expires_at      INTEGER
);
CREATE INDEX idx_mailbox_recipient_unread ON mailbox(recipient_name, read_at)
  WHERE read_at IS NULL;
CREATE INDEX idx_mailbox_ack_pending      ON mailbox(requires_ack, acked_at)
  WHERE requires_ack = 1 AND acked_at IS NULL;

-- Escalations
CREATE TABLE escalations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  teammate_id   TEXT REFERENCES teammates(id) ON DELETE SET NULL,
  sprint_branch TEXT,
  role          TEXT NOT NULL,
  phase         TEXT,
  question      TEXT NOT NULL,
  blocking      INTEGER NOT NULL DEFAULT 1,
  context_refs  TEXT CHECK(context_refs IS NULL OR json_valid(context_refs)),
  raised_at     INTEGER NOT NULL,
  resolved_at   INTEGER,
  resolution    TEXT
);
CREATE INDEX idx_escalations_unresolved
  ON escalations(project_id, resolved_at) WHERE resolved_at IS NULL;

-- Deliverable ledger (stall detector)
CREATE TABLE deliverables (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  agent_session  TEXT NOT NULL,
  agent_role     TEXT NOT NULL,
  kind           TEXT NOT NULL,
  target_ref     TEXT NOT NULL,
  promised_at    INTEGER NOT NULL,
  delivered_at   INTEGER,
  status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK(status IN ('pending','delivered','stalled','aborted'))
);
CREATE INDEX idx_deliverables_pending
  ON deliverables(project_id, status) WHERE status = 'pending';

-- Discovery findings
CREATE TABLE discovery_findings (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sprint_branch  TEXT,
  discovery_run  TEXT NOT NULL,
  section        TEXT,
  title          TEXT NOT NULL,
  body           TEXT NOT NULL,
  sources        TEXT CHECK(sources IS NULL OR json_valid(sources)),
  created_at     INTEGER NOT NULL
);
CREATE INDEX idx_discovery_sprint_run
  ON discovery_findings(project_id, sprint_branch, discovery_run);

-- Audit findings
CREATE TABLE audit_findings (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sprint_branch  TEXT,
  concern        TEXT NOT NULL,
  severity       TEXT NOT NULL CHECK(severity IN
                   ('info','low','medium','high','critical')),
  hypothesis     TEXT NOT NULL,
  falsification  TEXT,
  confidence     TEXT CHECK(confidence IN ('low','medium','high')),
  finding        TEXT NOT NULL,
  evidence_refs  TEXT CHECK(evidence_refs IS NULL OR json_valid(evidence_refs)),
  gh_issue       INTEGER,
  created_at     INTEGER NOT NULL
);
CREATE INDEX idx_audit_sprint_severity
  ON audit_findings(project_id, sprint_branch, severity);

-- Hot-query views
CREATE VIEW v_teammates_live AS
  SELECT t.*, (strftime('%s','now')*1000 - t.last_seen_at) AS ms_since_seen
  FROM teammates t
  WHERE t.status NOT IN ('crashed','retired');

CREATE VIEW v_mailbox_unread_per_recipient AS
  SELECT recipient_name, COUNT(*) AS unread_count, MIN(sent_at) AS oldest_sent
  FROM mailbox
  WHERE read_at IS NULL
  GROUP BY recipient_name;

CREATE VIEW v_escalations_open AS
  SELECT e.*, t.teammate_name, t.team_name
  FROM escalations e
  LEFT JOIN teammates t ON t.id = e.teammate_id
  WHERE e.resolved_at IS NULL
  ORDER BY e.raised_at;

INSERT INTO schema_versions VALUES (7, strftime('%s','now')*1000, '<sha256>');

COMMIT;
```

**Storage discipline:** discovery + audit findings are intended queryable. If
`body` exceeds ~32 KB, store a pointer (path under `.artifacts/cache/`, which is
gitignored) in `sources` JSON rather than inline. DB stays compact.

### 2. `skills/shepherd/doctrines/sqlite-canonical-state.md` (NEW)

~120 lines. Sections: rule + rationale (operator-observed defect cluster);
allow-list (file-canonical vs row-canonical, both ways, explicit); materialization
contract (`shctx report` for any operator-readable view); anti-patterns (e.g.,
"agent invents new artifact path that isn't a `shctx <X> insert` call");
migration guidance (back-compat for existing markdown flows; new flows MUST
canonicalize). Field origin section cites the v5.1.5/v5.1.6 defect cluster
(#43, #49, #52).

### 3. New shctx subcommands

All under `skills/context/scripts/cmd_<sub>.sh`, dispatcher fallback in
`skills/context/scripts/shctx` makes them automatically reachable.

```
shctx teammate register <name> --team=<t> --type=<role> [--session=<uuid>] [--pane=<id>]
shctx teammate heartbeat <name> [--phase=<p>] [--tool=<t>] [--note=<n>]
shctx teammate status <name>                          # JSON row
shctx teammate liveness [--stale-mins=<n>]            # table view
shctx teammate prune --confirm [--name=<n>|--crashed] # delete dead
shctx teammate retire <name>                          # graceful

shctx mailbox send --to=<name> --kind=<k> [--target-file=<p>] [--requires-ack] <<<payload-json
shctx mailbox recv --as=<name> [--unread-only] [--mark-read]
shctx mailbox ack <id>
shctx mailbox stale [--mins=<n>]                      # awaiting-ack and aging

shctx escalate --role=<r> --question=<q> [--blocking] [--phase=<p>] [--context=<json>]
shctx escalate list [--open-only]
shctx escalate resolve <id> --reply=<text>

shctx deliverable promise --kind=<k> --target=<ref>   # returns deliverable_id
shctx deliverable complete <id>
shctx deliverable stalled [--since-mins=<n>]          # query

shctx discovery insert --run=<id> [--section=<s>] --title=<t> [--sources=<json>] <<<body
shctx audit insert --concern=<c> --severity=<s> --hypothesis=<h>
                   [--falsification=<f>] [--confidence=<c>]
                   [--evidence=<json>] [--gh-issue=<n>] <<<finding

shctx report <kind> [filters]                         # markdown materializer
                                                       # kind ∈ {discovery,audit,
                                                       #         escalation,close,teammates}
```

Each command round-trips via `sqlite3 .artifacts/root.db`, respects
`shepherd.lock`, and emits one row to `logs_events` for audit trail
(matches existing `cmd_*.sh` convention).

### 4. Hook integration

- **`PostToolUse` hook** — extends existing `skills/context/scripts/hooks/subagent_telemetry.sh`
  (v5.1.3) to also emit `shctx teammate heartbeat $TEAMMATE_NAME --tool=$TOOL_NAME`
  when running inside a teammate session (detect via `$CLAUDE_TEAMMATE_NAME`).
- **`TeammateIdle` hook (NEW)** — `skills/context/scripts/hooks/teammate_idle.sh`:
  marks `teammates.status = 'idle'`, scans unresolved escalations + stalled
  deliverables, surfaces warnings to lead via stderr.
- **`deliverable_check.sh` (NEW, PreToolUse / Stop)** — if last turn announced a
  Write/Edit/Insert without delivering the matching row/file, mark deliverable
  `stalled`, raise soft-warn. Closes **#52**.

Hooks registered in existing `hooks.json` (or `.claude-plugin/hooks.json` —
whichever shepherd uses) under appropriate event arrays.

### 5. Agent profile amendments (per-issue)

**`agents/discovery.md` — closes #43:**
- New Hard Prohibition: "Inline-only reports are CONTRACT VIOLATION. You MUST
  end your turn with one or more `shctx discovery insert --run=<RUN_ID>` calls
  per finding."
- Output contract:
  ```
  ## DISCOVERY REPORT
  - inserted: N rows under run=$RUN_ID
  - materialized view: shctx report discovery --run=$RUN_ID
  ```
- Brief from conductor passes `--run=<id>`; absence of N≥1 rows under that run
  = stall, retriable.

**`agents/critic.md` + `agents/auditor.md` — closes #52:**
- Top of brief: agent calls
  `shctx deliverable promise --kind=row --target=audit_findings:<concern>` and
  records the returned `deliverable_id`.
- End of turn: agent calls `shctx deliverable complete <id>` after writing
  rows via `shctx audit insert` (one per finding).
- `deliverable_check.sh` hook checks for orphan promise → re-dispatches with
  tightened brief.
- Markdown report materialized by `shctx report audit --sprint=<branch>`;
  agent does NOT author the report file directly.

**`agents/auditor.md` (intro mode) — closes #44:**
- New brief-template block:
  ```
  ## Canonical gates (intro-mode regression)
  1. Run the 4 check-class canonical gates (existing).
  2. For EACH `[gates].extra` entry in `.claude/shepherd.toml`:
     CARGO_TARGET_DIR=target/.lanes/intro-extra-<name> bash -c "<cmd>"
     Record ONE `audit_findings` row per extra with:
       - concern: 'regression-extras'
       - severity: 'high' on FAIL, 'info' on PASS
       - finding: first 20 lines of failure output (FAIL) or 'pass'
  3. Report MUST include 'extras run' + 'extras skipped (if any)' explicitly
     in the materialized view.
  ```

**`agents/conductor.md` + `commands/spawn.md` — closes #50:**
- New section in `agents/conductor.md` `## Cargo discipline (binding under spawn)`:
  ```
  Every cargo invocation in your flock MUST use:
    CARGO_TARGET_DIR=target/.lanes/<lane-slug> cargo <subcmd> ... --frozen
  Coder/worker briefs you emit MUST include this prefix in their cargo examples.
  Root cleanup removes target/.lanes/ at sprint close.
  ```
- Cite existing `doctrines/cargo-sequential-gates.md`.
- `commands/spawn.md` adds a `[Cargo discipline]` block to the conductor brief
  template (already-extant `cargo-sequential-gates` doctrine referenced).

**`agents/shepherd.md` — closes #49:**
- New halt-code `TEAMMATE-CRASHED`. Root's spawn loop polls
  `shctx teammate liveness --stale-mins=5`; any `presumed-crashed` teammate is
  surfaced + offered re-spawn via `shctx mailbox` of the archived initial brief.

### 6. `commands/cleanup.md` — closes #51

Five-line slash command body:
1. `shctx teammate liveness` — show table
2. Confirm with operator
3. `shctx teammate prune --confirm --crashed`
4. Materialize cleanup report via `shctx report teammates --sprint=<branch>`
5. PAUSE

Registered in `.claude-plugin/plugin.json` commands array; listed in
`skills/shepherd/SKILL.md` command table.

### 7. Version + CHANGELOG sync

Bump or confirm `v5.1.7` in all 6 version-source-of-truth files
(`.claude-plugin/plugin.json` already at 5.1.7;
`.claude-plugin/marketplace.json`, `skills/shepherd/SKILL.md`,
`skills/context/SKILL.md`, README, CHANGELOG). Add v5.1.7 CHANGELOG entry
covering canonicalization + bug-fix summary.

## Lane decomposition (file-disjoint, parallel-safe)

| Wave | Lane | Scope | Closes |
|---|---|---|---|
| W1 | **A1 Schema** | `skills/context/schema/0007_canonical_state.sql` + migration notes | foundation |
| W1 | **A2 Doctrine** | `skills/shepherd/doctrines/sqlite-canonical-state.md` (NEW) | doctrine |
| W1 | **A3 shctx core subcommands** | `cmd_{teammate,mailbox,escalate,deliverable,report}.sh` + dispatcher entries | surface |
| W1 | **A4 shctx insert subcommands** | `cmd_{discovery,audit}.sh` (new or extend) | surface |
| W1 | **W1 Old-issue triage** | `gh` worker walks #18–#39, posts summary comment per issue + triage report | #18–#39 |
| W1 | **W2 v5.1.6-fix verification** | Verify #45 + #46 resolved; comment + close as appropriate | #45, #46 |
| W2 | **B1 Agent profile amendments (D/C/A)** | `agents/{discovery,critic,auditor}.md` | #43, #52, #44 |
| W2 | **B2 Agent profile amendments (C/S/Spawn)** | `agents/{conductor,shepherd}.md`, `commands/spawn.md` cargo block | #49, #50 |
| W2 | **B3 New /shepherd:cleanup command** | `commands/cleanup.md` + plugin.json + SKILL.md command table | #51 |
| W2 | **B4 Hook integration** | `hooks/{post_tool_use,teammate_idle,deliverable_check}.sh` + hooks.json | infrastructure |
| W3 | **C1 Close audit swarm** | Concern-split via Agent dispatch: code-quality, data-flow, dependency-topology, completeness | gate |
| W3 | **C2 Version + CHANGELOG sync** | 6 version-source-of-truth files | release |

## Dispatch shape

Not via `/shepherd:*` — via `superpowers:dispatching-parallel-agents` using the
`Agent` tool. Each lane is one subagent dispatch.

- Wave 1 dispatches 6 in parallel (A1, A2, A3, A4, W1, W2) — file-disjoint.
- Wave 2 dispatches 4 in parallel (B1, B2, B3, B4) — file-disjoint.
- Wave 3 dispatches C1 (3-5 concern auditors in parallel), then C2 as a final lane.

Each lane brief follows the seven-section bracketed format (`[OBJECTIVE]`,
`[FILE-SCOPE]`, `[CONTEXT-INVENTORY]`, `[DO-NOT-DUPLICATE]`, `[ACCEPTANCE]`,
`[SKILLS]`, `[OUTPUT]`) — same shape as shepherd coder briefs.

## Acceptance gates

| Gate | Check |
|---|---|
| Schema applies | `sqlite3 .artifacts/root.db < skills/context/schema/0007_canonical_state.sql` clean; `SELECT version FROM schema_versions` returns 7 |
| shctx commands wired | `bash skills/context/scripts/shctx teammate liveness` returns empty table without error |
| Agent profile self-test | Each amended agent profile passes `grep` checks (`grep -q "shctx discovery insert" agents/discovery.md` etc.) |
| Cleanup command registered | `/shepherd:cleanup` listed in `commands/` + SKILL.md + plugin.json |
| Hook registered | `cat .claude-plugin/hooks.json \| jq '.PostToolUse'` includes new hooks |
| Doctrine referenced | Each amended agent profile cites `doctrines/sqlite-canonical-state.md` |
| Version aligned | All 6 version-source-of-truth files at 5.1.7 |
| CHANGELOG entry | `## v5.1.7` section with canonicalization + bug-fix summary |
| Old-issue triage | W1 produced summary comment per #18–#39 + triage report under `.artifacts/docs/handoffs/2026-05-20-old-issue-triage.md` |
| v5.1.6 fixes verified | W2 closed (or kept open with status note) #45 and #46 |

## Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Schema migration breaks existing `shctx` consumers | Medium | Additive only — no ALTER on existing tables; rollback = `DROP TABLE`s |
| R2 | Agent profile changes break existing `/shepherd:start` flow | Medium | Profile amendments are additive; close audit swarm includes profile smoke-load |
| R3 | Hook changes cause `Bash` permission surprises | Low | Non-blocking, warn-not-deny; mirrors existing `subagent_telemetry.sh` pattern |
| R4 | Operator workflow disruption — markdown reports replaced with DB rows | Low-Medium | `shctx report` provides equivalent markdown view; existing flows remain back-compat |
| R5 | Old-issue triage worker mis-classifies an issue (premature close) | Low | Worker writes one comment per issue + posts triage report; operator reviews before final close |
| R6 | Lane B1 + B4 conflict on agent profile if hook script paths drift | Low | B4 only edits hook scripts and `hooks.json`; B1 edits agent profile bodies. Disjoint at lane brief time |
| R7 | `shctx team prune` deletes live teammate by race | Low | `--confirm` required; `last_seen_at < (now - stale_mins)` check; operator-mediated |

## Sprint t-shirt

**M+.** Eight implementation lanes + 3-4 auditor + 1 close lane = ~13 dispatches
across 3 waves. Larger than a typical patch but still patch-tier because the
closed-flock contract is unchanged, additions are purely additive (new tables,
new commands, new doctrine), and existing surfaces (start/plant/spawn) keep
working unchanged.

## Proof of dispatch

- design authored by: main-chat @ 2026-05-20
- approach: canonical-state re-scope (architectural insight from operator)
- operator confirmation: 2026-05-20 (3 approval gates: scope=ambitious patch,
  old-issue triage=opportunistic, re-scope=canonicalization YES)
- supersedes: none (no prior v5.1.7 sketches on disk)
- next step: writing-plans skill authors implementation plan, then
  dispatching-parallel-agents skill fans out the 13-dispatch sequence
