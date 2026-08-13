# conformance/NORMALIZATION.md — pinned non-determinism sources

Every source of non-determinism the Python CLI (`services/cli/shepherd_cli`) can emit,
and the EXPLICIT rule that pins it before a case's bytes are captured or compared.
Implementation: `conformance/lib/harness.py`'s `normalize()` (post-capture substitution)
and `_build_env()` (pinned at the source, where that is stronger — code-style/python.md's
"Byte-exact output parity" section: freeze the clock/UUID/locale at the boundary rather
than scrub after the fact, wherever pinning is possible).

An unpinned source is a flaky case, and a flaky oracle is worse than none (plan.md
W0-S9, action 2) — every rule below exists because a real field in this CLI's real
output depends on it.

| Source | Where it appears | Rule |
|---|---|---|
| **Timestamps** | `run.json`'s `updated_at`; `teammates.spawned_at`/`last_seen_at`; `deliverables.promised_at`; any JSON field named `created_at`/`refreshed_at`/`applied_at`/`ts` | `harness.normalize()`'s `_TS_FIELD_RE`: matched **by JSON key name** (an explicit allow-list), substituted with the literal token `<TS>`. Never a bare digit-run regex — that would also scrub row counts, ports, and other legitimate integers. |
| **UUIDs** | Not currently emitted by any case in this corpus, but several `index_*`/`mem_entries` rows carry UUID primary keys the CLI could echo back | `harness.normalize()`'s `_UUID_RE`: RFC-4122 textual shape (`8-4-4-4-12` hex), case-insensitive, substituted with `<UUID>`. |
| **Absolute paths** | Any `--json`/text output that embeds a scratch cwd or repo path (e.g. an error message naming a file) | `harness.normalize()`: the case's own scratch root and `REPO_ROOT` are replaced with `<SCRATCH>`/`<REPO_ROOT>` before comparison — the scratch root is unique per invocation (`tempfile.TemporaryDirectory`) by construction, so this substitution can never collide with real captured content. |
| **Hostname** | Not currently emitted by any case, but `socket.gethostname()` could leak into a future case's output (e.g. a lock-file owner field) | `harness.normalize()`: `socket.gethostname()` is looked up once and, if present in the text, replaced with `<HOSTNAME>`. |
| **Locale** | `printf`/`str.format` numeric alignment in table-rendered output (`teammate.py`'s `_render_liveness_table`, `deliverable.py`'s stalled table) | Pinned at the source, not scrubbed after: `harness._build_env()` sets `LC_ALL=C` for every invocation (code-style/python.md: "pin `LC_ALL=C`"). |
| **Timezone** | Any wall-clock-derived rendering (none of this corpus's cases render a timezone-formatted timestamp today, but the CLI's `time.time()` calls are wall-clock, not UTC-pinned, at the call site) | Pinned at the source: `harness._build_env()` sets `TZ=UTC`. |
| **Env leakage** | `SHCTX_DB`, `SHEPHERD_WORKDIR`, `SHEPHERD_HOME`, `SHCTX_ROOT_OVERRIDE`, `SHEPHERD_SESSION_ID`, `CLAUDE_SESSION_ID`, `CLAUDE_PLUGIN_ROOT`, `SHCTX_SKILL_ROOT`, `SHCTX_QUIET` — any of these inherited from the host process (this very Claude Code session, or a CI runner) would silently redirect a case at real state instead of its scratch fixture | `harness._build_env()` strips all nine (mirrors `services/cli/tests/conftest.py`'s `_STRIP_ENV_KEYS` verbatim) before rebuilding the environment explicitly for every invocation. |
| **Dict/JSON key order** | Every `--json` output in this package is produced by `json.dumps(..., indent=2)` (or, in `models.py`'s `_render_json`, an equivalent hand-built one-role-per-line shape) over a `dict`/`pydantic` model whose field order is the MODEL's declaration order, not alphabetical | Not scrubbed — the CLI's own field order is itself part of the byte-exact contract a port must reproduce, so this corpus captures it as-is. Where the CLI does NOT control its own ordering (SQL result rows), the harness normalizes explicitly — see "sqlite_master ordering" below. |
| **sqlite_master ordering** | SQLite's own `sqlite_master` catalog has no guaranteed row order across writes | `harness.dump_sqlite_master()`: `ORDER BY type, name` explicitly — the query does the normalizing, not a post-hoc sort of captured text. |
| **Repo/worktree identity** | `resolve_repo_root()` (`services/cli/shepherd_cli/resolution.py`) walks `git rev-parse --git-common-dir` from the process cwd | Every case's scratch cwd is a plain `tempfile.TemporaryDirectory`, never a git repository — `git rev-parse` fails inside it, so `resolve_repo_root()` degrades to `os.getcwd()` (the scratch dir itself), never the real shepherd repo. `SHEPHERD_WORKDIR`/`SHCTX_DB` are set explicitly regardless, so this degradation is belt-and-suspenders, not the only guard. |

## What is deliberately NOT normalized

- **Exit codes** — always exact; an exit code is never a source of drift worth pinning
  around, it IS the signal.
- **A command's own field order in a table render** — e.g. `teammate.py`'s
  `_LIVENESS_COLUMNS` — this is CLI behavior, not incidental noise; a port must
  reproduce it exactly.
- **Trailing newline count** — `typer.echo()` appends exactly one; captured verbatim,
  asserted verbatim (code-style/python.md: "Trailing newlines — decide once, assert it
  in a test").
