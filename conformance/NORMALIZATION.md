# conformance/NORMALIZATION.md — pinned non-determinism sources

Every source of non-determinism a contract-authority implementation can emit, and the
EXPLICIT rule that pins it before a case's bytes are captured or compared.
Implementation: `conformance/lib/harness.py`'s `normalize()` (post-capture substitution)
and `_build_env()` (pinned at the source, where that is stronger). Freeze
locale, timezone, user-home, and host overrides at the process boundary rather
than trying to scrub their effects after the fact.

An unpinned source is a flaky case, and a flaky oracle is worse than none. Every
rule below exists because a real field in the native CLI's output depends on it.

## Recording authority

Every case is owned by the canonical Rust CLI and declares
`authority: native-v6.4.5` (omitting it is equivalent). The runner rejects legacy
authority values and has no Python recording or replay path. This prevents a retired
implementation from restoring unsafe failure behavior.

| Source | Where it appears | Rule |
|---|---|---|
| **Timestamps** | `run.json`'s `updated_at`; `teammates.spawned_at`/`last_seen_at`; `deliverables.promised_at`; any JSON field named `created_at`/`refreshed_at`/`applied_at`/`ts` | `harness.normalize()`'s `_TS_FIELD_RE`: matched **by JSON key name** (an explicit allow-list), substituted with the literal token `<TS>`. Never a bare digit-run regex — that would also scrub row counts, ports, and other legitimate integers. |
| **UUIDs** | Not currently emitted by any case in this corpus, but several `index_*`/`mem_entries` rows carry UUID primary keys the CLI could echo back | `harness.normalize()`'s `_UUID_RE`: RFC-4122 textual shape (`8-4-4-4-12` hex), case-insensitive, substituted with `<UUID>`. |
| **Handoff calendar date** | The exact `| Date | YYYY-MM-DD |` row in a generated `handoff.md` | `harness.normalize()`'s `_HANDOFF_DATE_RE` matches that complete Markdown row and substitutes `| Date | <DATE> |`. Other date-shaped strings remain byte-significant. `TZ=UTC` still pins the source boundary. |
| **Absolute paths** | Any `--json`/text output that embeds a scratch cwd or repo path (e.g. an error message naming a file) | `harness.normalize()`: the case's own scratch root and `REPO_ROOT` are replaced with `<SCRATCH>`/`<REPO_ROOT>` before comparison — the scratch root is unique per invocation (`tempfile.TemporaryDirectory`) by construction, so this substitution can never collide with real captured content. |
| **Hostname** | Not currently emitted by any case, but `socket.gethostname()` could leak into a future case's output (e.g. a lock-file owner field) | `harness.normalize()`: `socket.gethostname()` is looked up once and, if present in the text, replaced with `<HOSTNAME>`. |
| **Locale** | Numeric alignment, sorting, and any locale-aware native or subprocess output | Pinned at the source, not scrubbed after: `harness._build_env()` sets `LC_ALL=C` for every invocation. |
| **Timezone** | Any wall-clock-derived rendering | Pinned at the source: `harness._build_env()` sets `TZ=UTC`. Date and timestamp fields that remain nondeterministic are normalized only by the narrow rules above. |
| **Env leakage** | Current or retired Shepherd overrides inherited from the operator or CI runner could redirect a case at real project or user state | `_build_env()` strips `SHCTX_DB`, `SHEPHERD_WORKDIR`, `SHEPHERD_HOME`, `SHCTX_ROOT_OVERRIDE`, `SHEPHERD_SESSION_ID`, `CLAUDE_SESSION_ID`, `CLAUDE_PLUGIN_ROOT`, `SHCTX_SKILL_ROOT`, and `SHCTX_QUIET`; it then sets `SHEPHERD_HOME` to `<scratch>/cwd/.shepherd-user` and `CLAUDE_PLUGIN_ROOT` to the checkout. Retired `SHCTX_*` and `SHEPHERD_WORKDIR` values are never rebuilt. |
| **JSON key order** | Native `--json` output and captured state documents | Not scrubbed. Field order is part of the byte-exact Rust contract, so the corpus captures it as emitted. Where the CLI does not control ordering (the SQLite catalog), the harness normalizes explicitly; see `sqlite_master ordering` below. |
| **sqlite_master ordering** | SQLite's own `sqlite_master` catalog has no guaranteed row order across writes | `harness.dump_sqlite_master()`: `ORDER BY type, name` explicitly — the query does the normalizing, not a post-hoc sort of captured text. |
| **Repo/worktree identity** | The native CLI discovers project state from its process cwd and primary git root | Every case runs under `<scratch>/cwd`; cases that declare `requires_git: true` get a fresh `git init`, while the rest remain non-git fixtures. Project state is always `<scratch>/cwd/.shepherd`, user state is always `<scratch>/cwd/.shepherd-user`, and no retired workdir/database override is set. |

## What is deliberately NOT normalized

- **Exit codes** — always exact; an exit code is never a source of drift worth pinning
  around, it IS the signal.
- **A command's own field order in a table render** — this is CLI behavior,
  not incidental noise; the native implementation must reproduce it exactly.
- **Trailing newline count** — captured and asserted verbatim.
