# Directory/file content-hash watching — agent expectations about state

> Origin: v5.1.1 (2026-05-16). Operator request: "watcher that would allow us
> to create some hash of specific directories so that we can automatically
> know whenever the contents change that way an agent or session can have
> actual expectations about specific contents without having to re-read
> every time."

## What it is

`shctx watch` tracks per-path content hashes so consumers can ask "has this
changed since I last marked it?" — avoiding redundant reads when state is
stable.

Two hash sources, auto-detected:

| Source | Mechanism | Cost | Use for |
|---|---|---|---|
| `git` | `git rev-parse HEAD:<path>` (tree object hash) | O(1) | Tracked content (any file in the repo) |
| `fs`  | `find ... -type f \| sort \| shasum` | O(N files) | Untracked content (`.shepherd/runs/`, `.shepherd/discoveries/`, log files) |

## The protocol

```
shctx watch add <path> [--label=<name>]    # register; auto-detect source
shctx watch mark <path> [--by=<role>]      # record current hash as "I've seen this"
shctx watch status <path>                  # show: unchanged / CHANGED / UNMARKED
shctx watch list                           # all registered paths
shctx watch remove <path>                  # stop watching
```

## Consumer pattern (the value)

The watcher pays off when agents use it to skip re-reads. Three canonical
patterns:

### Pattern 1 — Engineer's Phase 0 mesh

The engineer reads `{paths.ctx}/canonical-types.md` at sprint open. Mark it:

```
shctx watch add .shepherd/ctx/canonical-types.md --label=canonical-types
shctx watch mark .shepherd/ctx/canonical-types.md --by=engineer
```

Next sprint, the engineer's Phase 0 mesh begins with:

```
shctx watch status .shepherd/ctx/canonical-types.md
```

If unchanged → skip the re-read. The engineer's expectation about the file
is structurally recorded; the file's mtime alone doesn't tell you whether
the file's CONTENT moved.

### Pattern 2 — Discovery cross-sprint reuse

When a discovery agent captures a report, the `discovery_capture.sh` hook
records the source-directory hash at the time of capture. If a subsequent
discovery question targets the same sources AND the hashes are unchanged,
the cached discovery is reusable.

(Not auto-wired in v5.1.1; future work in v5.1.3 or v5.2.0.)

### Pattern 3 — Conductor session orientation

At session start, the conductor checks:

```
shctx watch list
```

If watched paths show CHANGED since last mark, the conductor surfaces:

```
[orientation] sprint state has drifted since last session — review changed paths:
  - .shepherd/ctx/canonical-types.md  (CHANGED)
  - skills/shepherd/doctrines/         (CHANGED — 3 new doctrine files)
```

## Hash semantics

**git source:** `git rev-parse HEAD:<path>` returns the tree-object hash for
a directory or the blob hash for a file. Hashes change if and only if
content changes. Tracked content is always cheap to hash.

**Caveat:** the git hash is for HEAD only. Uncommitted changes in the
working tree are invisible to this command. For a working-tree-aware hash,
use `git ls-tree`-based hashing of staged content. v5.1.1 uses HEAD for
simplicity; v5.1.2+ could add `--working-tree` mode.

**fs source:** sorted SHA-256 of all regular files under the path,
hashed-of-hashes. Robust to file ordering. Slower for large directories
(O(N files)) but still subsecond for typical shepherd namespaces.

## What watching is NOT

- **Not a daemon.** Hash computation is on-demand when `status` is called.
  No background process; no inotify; no polling.
- **Not a cache invalidator.** Watching records hashes; consumers decide
  what to do with the signal. The watcher doesn't auto-refresh anything.
- **Not for security.** Hashes confirm content equality, not authenticity.
  Don't use this for tamper detection in production.

## Anti-patterns this doctrine catches

1. **Agent re-reads `canonical-types.md` every sprint without checking.**
   Wastes tokens. Use `shctx watch status` first.
2. **Operator inspects file mtime to decide if content changed.** mtime is
   set by tools that touch the file even when content doesn't change
   (linters, formatters). Hash is authoritative.
3. **Adding a path to watch and never marking it.** UNMARKED is a valid
   state; `status` shows it explicitly. But the registry isn't useful
   until consumers mark + recheck.
4. **Re-using a hash from a different `--source`.** git and fs hashes are
   not interchangeable. The registry records source per path; don't
   compare across sources.

## Future extensions (not in v5.1.1)

- `shctx watch diff <path>` — show what files changed in the path since
  last mark (useful for audit-style queries)
- Hook-level integration: PreToolUse(Read) consults the watch table; if
  the path is watched and unchanged since last mark, surface a hint
  ("this content is unchanged since you last read it")
- Auto-watching for canonical paths declared in `shepherd.toml [watch]`
  (e.g., always watch `{paths.ctx}/canonical-types.md`)

## See also

- `skills/context/scripts/cmd_watch.sh` — implementation
- `skills/context/schema/migrations/0005_watch_paths.sql` — table schema
- `doctrines/discovery-readonly.md` §"Cross-sprint reuse" — watch is the
  enabler for the cached-discovery story
- `doctrines/context-registry.md` — the broader cache-vs-canonical model
  that watching extends
