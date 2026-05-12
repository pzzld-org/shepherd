# SQL — project code style

This file is project-local at `.artifacts/styles/sql.md`. The conductor injects its content into every coder brief whose `[FILE-SCOPE]` includes SQL files (`.sql`, migrations, embedded queries). Edit freely; lives next to the project, not the user.

## Error handling & integrity
- Multi-row mutations are wrapped in an explicit transaction (`BEGIN; ... COMMIT;`) when atomicity matters. Reviewer rejects multi-row writes that rely on autocommit.
- `ON CONFLICT` clauses spell out the resolution: `ON CONFLICT (col) DO UPDATE SET ...` or `DO NOTHING`. Never omit the action — implicit failure on conflict is a bug.
- Foreign keys carry an explicit `ON DELETE` / `ON UPDATE` action. `CASCADE` requires a comment justifying the data-loss surface.
- `NOT NULL` is the default. `NULL`-able columns require a comment explaining the semantic of "missing".
- Defensive `WHERE` on every `UPDATE` / `DELETE` — no unbounded mutations. Reviewer rejects `UPDATE foo SET x = ...` without a `WHERE`.

## Ownership & state
- Explicit column lists in `INSERT` and `SELECT`. `INSERT INTO t VALUES (...)` without column names is forbidden.
- `SELECT *` is reserved for ad-hoc queries / CLI exploration. Application code and migrations enumerate columns.
- Column ordering in DDL is meaningful: primary key first, then required attributes, then optional, then timestamps (`created_at`, `updated_at`) at the end.
- Generated / computed columns are documented with a comment naming the invariant they enforce.
- Surrogate keys (UUIDv7 preferred for time-orderable IDs; serial only when ordering doesn't matter for sharding/replication).

## Layout
- One statement per logical unit. Keywords (`SELECT`, `FROM`, `WHERE`, `JOIN`, `GROUP BY`) start at column 1; columns and predicates indent one level.
- Migrations are numbered, immutable once merged, and named `NNNN_short_description.sql`. Forward-only by default; reversible migrations include a sibling `down` file when reversal is supported.
- DDL and DML are not mixed in the same migration. Schema changes ship separately from data backfills.
- Indexes are named explicitly: `idx_<table>_<col1>_<col2>` or `uq_<table>_<cols>` for unique. Auto-generated names are renamed before merge.
- Views, materialized views, and functions live in dedicated files under a `views/` or `functions/` subtree.

## Naming
- `snake_case` for tables, columns, indexes, constraints. Plural table names (`users`, `orders`); singular column names.
- Boolean columns prefix with `is_` / `has_` / `can_` so reads aren't ambiguous (`is_active`, `has_paid`).
- Timestamps use `created_at`, `updated_at`, `deleted_at` (the last for soft-delete only when the project opts in).
- Foreign keys named `<referenced_table_singular>_id` (`user_id`, `order_id`).

## Tooling
- Migrations run through the project's migration tool (sqlx, goose, dbmate, alembic, etc.) — never hand-edited against production.
- Linter (`sqlfluff` for Postgres-flavored projects) MUST pass before commit. Project-specific dialects configured in `.sqlfluff`.
- `EXPLAIN ANALYZE` results are pasted into PR descriptions for any new query touching > 1k rows or any new index.
- Schema is checked into the repo as a single canonical dump (`schema.sql`) regenerated from migrations — never hand-edited.

## Documentation
- Migration files open with a comment: purpose, ticket/issue link, rollback notes.
- Tables, columns, and indexes that aren't self-explanatory get `COMMENT ON ...` statements.
- Complex queries (window functions, CTEs > 3 levels) get an inline comment explaining the intent.

## Common patterns to AVOID (operator-flagged)
- `SELECT *` in application code or migrations — leaks schema changes into every consumer.
- `INSERT INTO t VALUES (...)` without an explicit column list — column-order drift is silent breakage.
- Implicit `ON CONFLICT` — every conflict resolution is spelled out.
- Unbounded `UPDATE` / `DELETE` (missing `WHERE`) — review-blocker.
- `IN (SELECT ...)` when an `EXISTS` subquery or `JOIN` is clearer and faster.
- Implicit type coercion in `WHERE` (`WHERE id = '123'` against an integer column) — kills index usage.
- `OR` chains across columns where `UNION` (or a composite index) would be more honest about the access pattern.
- Hand-named or auto-named constraints — every constraint and index has a deterministic, conventional name.
