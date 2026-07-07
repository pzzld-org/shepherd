# SQL — project code style

Project-local at `.shepherd/styles/sql.md` (`.artifacts/` legacy); injected as `[CODE-STYLE]` into briefs scoping SQL files/migrations. Edit freely — lives next to the project.

## Error handling & integrity
- Multi-row mutations wrap in an explicit transaction (`BEGIN; ... COMMIT;`) when atomicity matters — never rely on autocommit. `ON CONFLICT` clauses spell out the resolution (`DO UPDATE SET ...` or `DO NOTHING`) — never omit the action.
- Foreign keys carry explicit `ON DELETE`/`ON UPDATE`; `CASCADE` requires a comment justifying data loss.
- `NOT NULL` is the default; nullable columns need a comment explaining "missing". Defensive `WHERE` on every `UPDATE`/`DELETE` — no unbounded mutations.

## Ownership & state
- Explicit column lists in `INSERT`/`SELECT`. `INSERT INTO t VALUES (...)` without column names is forbidden; `SELECT *` reserved for ad-hoc/CLI queries.
- DDL column order: primary key, required attributes, optional, timestamps (`created_at`, `updated_at`) last. Generated/computed columns get a comment naming the invariant enforced.
- Surrogate keys: UUIDv7 preferred for time-orderable IDs; serial only when ordering doesn't matter for sharding/replication.

## Layout
- One statement per logical unit; `SELECT`/`FROM`/`WHERE`/`JOIN`/`GROUP BY` start at column 1, columns/predicates indent one level.
- Migrations numbered, immutable once merged, named `NNNN_short_description.sql`; forward-only by default, reversible ones get a sibling `down` file. DDL/DML never mixed in one migration.
- Indexes named explicitly (`idx_<table>_<col1>_<col2>`, `uq_<table>_<cols>` for unique), auto-generated names renamed before merge; views/materialized views/functions live in dedicated `views/`/`functions/` files.

## Naming
- `snake_case` tables/columns/indexes/constraints; plural table names, singular columns.
- Boolean columns prefix `is_`/`has_`/`can_`; foreign keys `<referenced_table_singular>_id`; timestamps `created_at`/`updated_at`/`deleted_at` (soft-delete only when the project opts in).

## Tooling
- Migrations run through the project's migration tool (sqlx, goose, dbmate, alembic) — never hand-edited against production. `sqlfluff` (Postgres) MUST pass before commit.
- `EXPLAIN ANALYZE` results pasted into PRs for any new query touching > 1k rows or any new index. Schema checked in as a canonical `schema.sql` regenerated from migrations, never hand-edited.

## Documentation
- Migration files open with a comment: purpose, ticket link, rollback notes. Non-obvious tables/columns/indexes get `COMMENT ON ...` statements.

## Common patterns to AVOID (operator-flagged)
- `IN (SELECT ...)` when an `EXISTS` subquery or `JOIN` is clearer and faster; implicit type coercion in `WHERE` (`WHERE id = '123'` against an integer column) — kills index usage.
- `OR` chains across columns where `UNION`/a composite index is more honest about access pattern; hand-named or auto-named constraints — every constraint/index needs a deterministic name.
