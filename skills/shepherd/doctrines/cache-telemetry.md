# Cache telemetry — measuring prompt-caching health per dispatch

> **Origin:** v5.1.3 (2026-05-19). Operator: "we simply need to ensure we are
> actually benefitting from our own plugin both in plan execution and w.r.t.
> maximizing our usage and tokens."

Brief-cache-discipline is the structural rule (stable framing first, variable
content last). Cache telemetry is the measurement layer that proves the rule
is producing cache-read wins. Without measurement, the discipline is a story
we tell ourselves; with measurement, it is a claim we can falsify.

## What it captures

For every subagent dispatch that completes, the `SubagentStop`-fired hook
`hooks/scripts/subagent_telemetry.sh` parses the subagent's transcript JSONL
(at `agent_transcript_path` in the hook payload) and aggregates the
Anthropic API per-turn `usage` records:

- `input_tokens` — non-cached input the model paid for at the standard rate
- `output_tokens` — generated tokens
- `cache_read_input_tokens` — tokens served from an existing cache breakpoint
  (the cheap signal we want maximized)
- `cache_creation_input_tokens` — tokens written into a new cache breakpoint
  (paid once, amortized across subsequent dispatches in the same TTL window)
- `cache_creation.ephemeral_5m_input_tokens` — subset of the above, written
  with a 5-minute TTL (the default)
- `cache_creation.ephemeral_1h_input_tokens` — subset of the above, written
  with a 1-hour TTL (set when `ENABLE_PROMPT_CACHING_1H=1`)

A derived `hit_rate` is computed per dispatch:

    hit_rate = cache_read / (cache_read + cache_creation + input)

`hit_rate` is `null` (not zero) when the denominator is zero — i.e. when we
could not measure. Zero means "the model paid full price for everything";
null means "we don't know what the model paid."

Counts only. No prompt content. The event log carries token totals,
identifiers, and the parse error string when aggregation fails.

## Where it lands

Two stages:

1. **Event log (raw):** one JSONL line per dispatch, appended to
   `<ns>/logs/events-YYYY-MM-DD.jsonl` (where `<ns>` is `.shepherd/` by
   default, `.artifacts/` for legacy projects). This file is gitignored per
   `doctrines/hook-event-log.md` and is the source of truth — the registry
   is downstream and rebuildable.
2. **Registry rollup (queryable):** `shctx refresh --scope=telemetry`
   shovels rows from the JSONL log into `index_cache_usage` (the table) and
   surfaces them via `v_cache_usage` (the per-sprint × role rollup view).
   The refresh is idempotent — `UNIQUE(session_id, agent_id, ts)` plus
   `INSERT OR IGNORE` makes replays a no-op.

## How it's surfaced

The completeness-concern @auditor runs `shctx query cache-usage
--sprint=<sprint_branch> --md` at sprint close and embeds the resulting
table verbatim in the close report's `## Cache telemetry` subsection. Per
`agents/auditor.md` and `skills/shepherd/agents/auditor.reference.md`, the
auditor reads the rollup, not the raw JSONL — degraded events (those with
`parse_error` populated) are excluded from `v_cache_usage` so they do not
poison the aggregate hit-rate.

If the view is empty (no telemetry collected for this sprint yet — typical
during the baseline period), the auditor writes
`telemetry view absent — establishing baseline` and moves on.

## Threshold guidance

Cache hit-rate behavior depends on agent role, sprint shape, and prefix
stability. We do not know the equilibrium yet. The doctrine ships
exploratory thresholds and refines them as data accumulates:

- **Baseline period (first 2–3 sprints after v5.1.3):** report-only. No
  grade impact. The auditor lists the table and notes "exploratory
  baseline" if patterns are not yet stable.
- **Post-baseline:** aggregate hit-rate below 40% across a sprint surfaces
  as a MEDIUM finding for the @engineer to investigate at the next intro
  wave. Do NOT grade-cap on cache telemetry alone — the metric measures
  caching health, not correctness or completeness.
- **Per-role expected ranges:** to be filled in after three sprints of
  data. Discovery and worker dispatches will trend higher (single-turn,
  small variable suffix); engineer Phase-0 mesh dispatches will trend
  lower (long, sprint-unique brief tail).

A v5.1.4+ revision of this doctrine replaces "exploratory" with the
observed per-role ranges and adjusts the 40% trigger accordingly.

## Failure modes

All hook failures are non-blocking. The hook always exits 0. Specifically:

- **Missing `agent_transcript_path` in the payload.** The hook emits a
  `cache_usage` event with all counts `null` and
  `parse_error: "missing agent_transcript_path..."`. The auditor sees a
  row marked degraded but the rest of the dispatch is unaffected.
- **Transcript file not readable** (path mistyped, permissions, race with
  cleanup). Same shape: null counts, `parse_error` populated.
- **Transcript present but no assistant `usage` records.** Indicates
  either a malformed transcript or a subagent that produced no model
  turns. Emits `parse_error: "no_assistant_usage_records_in_transcript"`.
- **Python aggregation crash** (truly unexpected). Caught at the bash
  layer; emits `parse_error: "python_aggregation_failed"`.

The discipline is loud failure, not silent success. Telemetry that looks
healthy because we suppressed bad data is worse than no telemetry at all.

## Privacy / size note

The event log captures token counts and identifiers (session id, agent id,
role, sprint branch) only. No prompt content. No tool inputs. No tool
outputs. A typical day's JSONL is well under 1 MB.

`<ns>/logs/events-*.jsonl` is gitignored per the
`doctrines/hook-event-log.md` convention. Operators rotate manually if
desired (`find <ns>/logs -name 'events-*.jsonl' -mtime +30 -delete`).

## See also

- `doctrines/brief-cache-discipline.md` — the structural rule this measures
  the impact of (stable framing first, variable content last).
- `doctrines/hook-event-log.md` — the JSONL event-log convention this
  hook writes to.
- `doctrines/context-registry.md` — the cache-vs-canonical registry model;
  `index_cache_usage` lives in the cache zone (rebuildable from the JSONL
  source) and `v_cache_usage` follows the `v_` view-prefix convention.
- `agents/auditor.md` — the completeness concern that surfaces the
  `## Cache telemetry` table at sprint close.
- `skills/context/queries/cache-usage.sql` — the canonical query the
  auditor runs.
- `skills/context/schema/migrations/0006_cache_telemetry.sql` — the
  schema for `index_cache_usage` and `v_cache_usage`.
