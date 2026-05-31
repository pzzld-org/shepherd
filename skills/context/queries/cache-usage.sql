-- usage: shctx query cache-usage [--sprint=<branch>] [--md|--json]
--
-- Per-sprint × role rollup of prompt-caching health, sourced from
-- index_cache_usage (rows landed by `shctx refresh --scope=telemetry` from
-- the JSONL event log emitted by hooks/scripts/subagent_telemetry.sh).
--
-- The view filters parse_error IS NULL — degraded dispatches do not
-- contribute to the aggregate hit-rate. To inspect parse-error events
-- directly, query index_cache_usage with `WHERE parse_error IS NOT NULL`.
--
-- The --sprint binding is optional: leave it empty (no flag) to roll up
-- every sprint in the project.
SELECT sprint,
       role,
       dispatches,
       avg_hit_rate,
       total_input,
       total_cache_read,
       total_cache_creation,
       avg_first_turn_creation
FROM v_cache_usage
WHERE project_id = :project_id
  AND (:sprint IS NULL OR sprint = :sprint)
ORDER BY sprint DESC, role;
