/*
    Appellation: embedded <module>
    Contrib: @FL03
*/
//! Byte-identical, compile-time-embedded copies of the registry's schema SQL.
//!
//! `include_str!` reaches only into this crate's own package root -- a
//! published `rlib` cannot embed a file that lives outside it (`cargo
//! package` only bundles files under the crate directory), and a
//! self-contained crate should not need the monorepo layout on disk just to
//! build. So the 21 files at `skills/context/schema/{0001_init.sql,
//! migrations/*.sql}` are vendored verbatim under `sql/` here, staged with a
//! byte-for-byte `cp` (never hand-retyped, which is exactly how "verbatim"
//! quietly stops being true). [`crate::migrate::tests::vendored_copies_match_source`]
//! is the standing drift check: it reads the real source of truth back and
//! fails the day it and the vendored copy disagree.

/// The baseline schema (`skills/context/schema/0001_init.sql`). Applied
/// FIRST, before any migration -- it creates `schema_versions` itself and
/// self-inserts its own `(1, unixepoch(), 'baseline-v5.0.0')` row, so
/// [`super::runner::apply_all`] never records version 1 a second time.
/// `0001_init.sql` sits at the schema-dir TOP LEVEL, outside `migrations/`,
/// and is applied by a *separate* path in both existing runners (`shctx
/// init`) -- see the crate's own top-level doc comment.
pub(super) const INIT_SQL: &str = include_str!("sql/0001_init.sql");

/// One vendored migration file.
pub(super) struct Migration {
    /// The 4-digit version this migration advances `schema_versions` to.
    pub(super) version: u32,
    /// The source filename, used in error messages so a failure names the
    /// exact file, matching the existing bash/Python runners' narration
    /// (`shctx migrate: applying NNNN_*.sql`).
    pub(super) filename: &'static str,
    /// The verbatim SQL text.
    pub(super) sql: &'static str,
}

/// Every migration under `skills/context/schema/migrations/`
/// (`0002_styles.sql` .. `0021_spawn_lead.sql`), in filename (== version)
/// order -- the same order both existing runners glob
/// `migrations/[0-9][0-9][0-9][0-9]_*.sql` in. `0001_init.sql` is NOT here:
/// it sits outside `migrations/` and is [`INIT_SQL`] above.
pub(super) const MIGRATIONS: &[Migration] = &[
    Migration {
        version: 2,
        filename: "0002_styles.sql",
        sql: include_str!("sql/migrations/0002_styles.sql"),
    },
    Migration {
        version: 3,
        filename: "0003_canonical_types_filter.sql",
        sql: include_str!("sql/migrations/0003_canonical_types_filter.sql"),
    },
    Migration {
        version: 4,
        filename: "0004_fts_search.sql",
        sql: include_str!("sql/migrations/0004_fts_search.sql"),
    },
    Migration {
        version: 5,
        filename: "0005_watch_paths.sql",
        sql: include_str!("sql/migrations/0005_watch_paths.sql"),
    },
    Migration {
        version: 6,
        filename: "0006_cache_telemetry.sql",
        sql: include_str!("sql/migrations/0006_cache_telemetry.sql"),
    },
    Migration {
        version: 7,
        filename: "0007_canonical_state.sql",
        sql: include_str!("sql/migrations/0007_canonical_state.sql"),
    },
    Migration {
        version: 8,
        filename: "0008_worktrees.sql",
        sql: include_str!("sql/migrations/0008_worktrees.sql"),
    },
    Migration {
        version: 9,
        filename: "0009_locks_mode_sprint.sql",
        sql: include_str!("sql/migrations/0009_locks_mode_sprint.sql"),
    },
    Migration {
        version: 10,
        filename: "0010_sprint_metrics.sql",
        sql: include_str!("sql/migrations/0010_sprint_metrics.sql"),
    },
    Migration {
        version: 11,
        filename: "0011_mem_entries_prior_kind.sql",
        sql: include_str!("sql/migrations/0011_mem_entries_prior_kind.sql"),
    },
    Migration {
        version: 12,
        filename: "0012_loop_state.sql",
        sql: include_str!("sql/migrations/0012_loop_state.sql"),
    },
    Migration {
        version: 13,
        filename: "0013_focus.sql",
        sql: include_str!("sql/migrations/0013_focus.sql"),
    },
    Migration {
        version: 14,
        filename: "0014_compile_runs.sql",
        sql: include_str!("sql/migrations/0014_compile_runs.sql"),
    },
    Migration {
        version: 15,
        filename: "0015_struct_shapes.sql",
        sql: include_str!("sql/migrations/0015_struct_shapes.sql"),
    },
    Migration {
        version: 16,
        filename: "0016_mailbox_kind_relax.sql",
        sql: include_str!("sql/migrations/0016_mailbox_kind_relax.sql"),
    },
    Migration {
        version: 17,
        filename: "0017_focus_lane.sql",
        sql: include_str!("sql/migrations/0017_focus_lane.sql"),
    },
    Migration {
        version: 18,
        filename: "0018_eval_runs.sql",
        sql: include_str!("sql/migrations/0018_eval_runs.sql"),
    },
    Migration {
        version: 19,
        filename: "0019_teammate_declared_state.sql",
        sql: include_str!("sql/migrations/0019_teammate_declared_state.sql"),
    },
    Migration {
        version: 20,
        filename: "0020_drop_mailbox.sql",
        sql: include_str!("sql/migrations/0020_drop_mailbox.sql"),
    },
    Migration {
        version: 21,
        filename: "0021_spawn_lead.sql",
        sql: include_str!("sql/migrations/0021_spawn_lead.sql"),
    },
];
