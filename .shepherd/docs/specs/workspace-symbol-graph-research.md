# Workspace symbol graph — research and design (Phase 0)

Status: research/design only. No code changes. Long-term project per Joe — not scheduled.

## Executive summary

Build the relationship layer as a SQL extension of the existing `shctx` symbol
index, not as a new subsystem. Add an `index_edges` table (caller→callee,
importer→imported, subtype→supertype, co-change) keyed on the same
`project_id`/`file_path`/`name` shape `index_symbols` and `index_struct_shapes`
already use, and answer graph questions with recursive CTEs — this is a
"graph via SQL" MVP, not a graph database. Do not adopt Glean or Kythe now:
both are real server deployments (Glean needs a persistent fact-store service
plus per-language indexers; Kythe needs a Bazel-extraction pipeline and a
GraphStore/serving stack) and both violate shepherd's per-project,
no-infra-to-run design. The right long-term upgrade path, if SQLite recursive
CTEs stop scaling, is tree-sitter-based multi-language extraction (Phase 2)
feeding the same schema, with SCIP-format export/import and an embedded graph
engine (Kùzu) evaluated only if Phase 1/2 measurably fall short (Phase 3).
LSP shell-out is rejected as the default integration path because it requires
a running, per-language server process per project — the opposite of
shctx's zero-daemon, single SQLite file model — though it remains a valid
one-off "ground truth" cross-check for Phase 2 extraction accuracy.

## Problem statement

`shctx` already solves symbol-identity dedup in two layers:

- `index_symbols` (migration `0001_init.sql`) — name-keyed symbol index.
  Backs `dedup-check.sql` (Layer 2 of `zero-duplicate-tolerance.md`) and the
  `canonical-types` catalog. Populated by `refresh-symbols.sh`, a grep/regex
  extractor for Rust (via `cargo metadata` + line-pattern matching, not a
  real parser) with tree-sitter or skip for other languages.
- `index_struct_shapes` (migration `0015_struct_shapes.sql`) — field-shape
  fingerprints. Backs `shctx dups` (Layer 4, `shape-dedup.md`), which catches
  the rename-to-evade-dedup shadow that name-matching is blind to (the FL03
  audit found 22 such clusters in one workspace: orphaned canonicals next to
  live shadows, four different `OpenPosition` shapes, etc.).

Both layers answer "does this symbol/shape already exist?" Neither answers
"what breaks if I change it?" or "what already calls the thing I'm about to
duplicate?" That's a relationship question, and shepherd has no relationship
layer today. Concretely, this gap shows up in:

- **DEDUP-GATE (`zero-duplicate-tolerance.md` Layer 2).** The conductor can
  find an existing symbol by name/shape but can't yet tell a coder "this
  symbol has 14 callers across 3 packages — converting the lane to `wire to
  existing` is safe" vs. "this symbol has 0 callers — it may already be the
  orphaned canonical the shape-gate flagged." Blast-radius is currently a
  latent-space guess made by the engineer/conductor reading grep output by
  eye.
- **`canonical-types.md` reconciliation option (b) "replace existing
  implementation."** Choosing between (a) wire-to-existing, (b) replace, (c)
  extend, (d) operator-justified divergence requires knowing the call graph
  of the existing symbol. Today that's a manual grep the conductor runs
  ad hoc, not a stored, queryable fact.
- **Auditor `dependency-topology` concern.** Currently checks the dep DAG
  at package granularity (`dep-hygiene` gate). A symbol-level call/import
  graph would let it flag a *specific* cross-tier violation (`crates/core::X`
  calling into `crates/app::Y`) instead of a package-level heuristic.
- **Phase-0 mesh fast-paths.** `canonical-types --md` and `dedup-check`
  already replace markdown reads with SQL. "What calls this" and "blast
  radius of this change" are the next fast-paths in the same lineage — SQL
  queries that replace a coder/auditor grep-and-read pass.

This doc scopes the design for that relationship layer without committing to
implementation yet, per Joe's framing ("long-term project, not needed
today").

## Survey: relationship-modeling approaches

| Tool / approach | Maturity | Embeddability (runs inside a per-project plugin, no daemon) | Relationship-modeling power | Integration cost for shepherd | Verdict |
|---|---|---|---|---|---|
| **VS Code workspace symbol provider** (`DocumentSymbolProvider` / `WorkspaceSymbolProvider`, LSP `textDocument/documentSymbol` + `workspace/symbol`) | Mature, ships in every VS Code build | No — lives inside the editor process, per-open-workspace in-memory index, not persisted or externally queryable | Flat symbol list only. No call/import graph — that's `textDocument/references` / `definition`, separate requests, resolved on demand, not stored | High — would mean embedding/driving a full editor extension host | Not viable as infra; useful only as a mental model (flat name index = what `index_symbols` already is) |
| **LSP servers directly** (rust-analyzer, gopls, pyright, tsserver) | Mature, each maintains a real in-memory symbol/type graph per project | Low — each requires a long-lived process, per-language, speaking JSON-RPC over stdio; no persisted queryable store, index dies with the process; multi-language workspace needs N servers running concurrently | Highest per-language precision (real type inference, real call hierarchy via `callHierarchy/incomingCalls`) | High — process lifecycle management, JSON-RPC client, one integration per language, no shared schema across languages, nothing persists between shctx invocations | Reject as default path. Worth a narrow one-off use: shell out to `rust-analyzer --print-config-path`-style batch commands or `gopls references` for a Phase-2 accuracy spot-check, never as the always-on index |
| **Tree-sitter (generic parsing) + ast-grep** | Mature, ast-grep is an actively maintained (2024-2025 releases, Rust-based) structural search/lint tool built on tree-sitter grammars for ~20 languages | High — tree-sitter grammars are static libraries, no daemon, parse-per-invocation, trivially shellable/embeddable exactly like `refresh-symbols.sh` already assumes ("tree-sitter in v5.x" per the script's own header comment) | Good — real AST means real call-site/import-site extraction (not the current regex heuristic), but relationship resolution (which `foo()` call binds to which `fn foo`) is still shepherd's job to write, tree-sitter gives the AST, not the resolved graph | Medium — one grammar + one extraction script per language, same shape as today's per-language `refresh-*.sh` scripts | **Adopt for Phase 2.** Matches shctx's existing per-language-script architecture; ast-grep specifically is worth vendoring/shelling-out to for the pattern-matching primitives instead of hand-rolling more regex |
| **Sourcegraph SCIP** (successor to LSIF, protobuf-based code-intel index format) + `scip-*` indexers (scip-typescript, scip-python, scip-go, rust-analyzer's `--scip` mode) | Mature format, actively used in production at Sourcegraph and GitHub-adjacent tooling; indexers are per-language, each shells out to that language's compiler/analyzer | Medium — SCIP is just a serialization format (a `.scip` protobuf file), not a server; producing one still requires the per-language indexer (often the LSP server itself in batch mode), but *consuming* one is just parsing a protobuf, embeddable | High — SCIP explicitly models symbols + occurrences + relationships (definition, reference, implementation) across files, designed for cross-repo code intel | Medium-high — no single indexer covers all languages shepherd's consumer projects use; would need to shell out to language-specific SCIP producers, then import the protobuf into SQLite | **Evaluate in Phase 3** as an import target once shctx's own edge schema is stable — SCIP as an interchange format, not as the runtime engine |
| **stack-graphs** (GitHub, used for their code navigation feature) | Mature, open-sourced by GitHub, Rust library | High — designed to be embedded, no server, builds a name-resolution graph from tree-sitter parses, incremental | Purpose-built for exactly this: cross-file, cross-scope symbol resolution as a graph, without a compiler | Medium — one stack-graph "rule file" (DSL) per language grammar; GitHub has only published rules for a handful of languages (Python, TypeScript/JS, others community-maintained) | Interesting Phase-3 candidate specifically for the *resolution* problem (binding a reference to its definition) that ast-grep extraction alone doesn't solve; not mature/broad enough in language coverage to be Phase 2 default |
| **Glean** (Meta, open-sourced) | Mature internally at Meta scale, open-sourced but documentation/adoption outside Meta is thin | Low — Glean is a fact-store *server* (its own DB, "Angle" query language, indexers that write facts via Thrift) designed for monorepo-scale, always-on service deployment | Very high — genuinely models code as a fact hypergraph (predicates relating N-ary tuples of facts), closest thing to "hypergraph of code facts" that's open source | Very high — requires running a Glean server, per-language indexers (glean-clang, glean-hs, community ones for others), a schema you author in Angle; nothing about this fits "runs inside a Claude plugin" | **Reject for now.** Right shape of idea, wrong deployment model. Revisit only if shepherd ever manages a fleet of large monorepos centrally rather than per-project |
| **Kythe** (Google, open-sourced) | Mature, but low external velocity (sparse commits/issues response outside Google-internal use per public tracking) | Low — extraction pipeline is Bazel-centric (extractors wrap the build), facts land in a GraphStore (LevelDB/etc.), served via a separate serving-table + UI stack | Very high — schema is explicitly a graph of nodes+edges over a formal "Kythe schema" (anchors, refs, defines, overrides, childof), the most complete public schema for this problem | Very high — the extraction model assumes you control the build (Bazel or a wrapped build), serving stack is multi-binary; adopting it for arbitrary consumer projects (which may not use Bazel) is a mismatch | **Reject for now**, same reasoning as Glean. Worth reading the *schema* (kythe.io/docs/schema) as a design reference for edge kinds even though the runtime isn't a fit |
| **CodeQL databases** | Mature, GitHub-maintained, widely used for security scanning | Medium — `codeql database create` produces a local, file-based database (no server), queryable offline via `codeql query run`; closer to embeddable than Glean/Kythe | High for the languages it supports, but the query language (QL) and database format are purpose-built for security/semantic queries, not general navigation, and DB creation is a full-build-required extraction (slow, needs a working build for compiled languages) | High — CLI dependency, per-language extractor, DB build time scales with project size, no incremental update story suited to per-commit refresh | Reject as the general index; not designed for the "cheap, always-fresh, refresh-on-commit" use case shctx needs. Could be a periodic *eval* input for security-doctrine work, orthogonal to this doc |
| **Property graph DBs — Neo4j** | Mature | Low — server process (JVM), not embeddable in a plugin without a daemon | High (native graph queries, Cypher) | High — a whole database server per project is the opposite of shctx's single-SQLite-file model | Reject — infra mismatch, not a capability gap |
| **Kùzu** (embedded property graph DB, Cypher-compatible, columnar, actively developed 2023-2025) | Young but real — embedded like SQLite/DuckDB, no server, single-process, has a stable enough release cadence to track | High — literally designed for "SQLite but for graphs," ships as a library, single-file storage | High — native graph storage + Cypher means multi-hop traversals (blast radius, transitive callers) are native instead of recursive-CTE-emulated | Medium — new dependency, new query language for the team to maintain alongside SQL, would run *alongside* not *instead of* the canonical SQLite store (or require migrating canonical data, which risks the "cache vs canonical" doctrine) | **Phase-3 candidate only**, gated on recursive-CTE performance actually becoming the bottleneck. Do not add a second embedded DB engine speculatively — violates "vanilla by default" until Phase 1/2 prove insufficient |
| **DuckDB + a graph extension** (e.g. community `duckpgq` property-graph extension) | DuckDB itself very mature; PGQ-style extensions are early/experimental | High in principle (DuckDB is embeddable, columnar, single-file) but the graph extension ecosystem is immature compared to Kùzu's native graph model | Medium — SQL/PGQ hybrid, still maturing | Medium — same "second engine" cost as Kùzu, less mature graph story | Reject for now — Kùzu is the more purpose-built embedded-graph option if Phase 3 ever needs one; no reason to carry two candidates |
| **SQLite + recursive CTEs** (what `shctx` already is) | Mature (SQLite is the most deployed DB engine in existence), recursive CTEs are standard SQL:1999 `WITH RECURSIVE`, well-supported since SQLite 3.8.3 (2014) | Highest — this is *already* shepherd's runtime. Zero new dependencies, zero new processes, one file, `sqlite3` binary already required by `shctx` | Medium — adjacency-list edges + `WITH RECURSIVE` handle transitive closure (callers-of-callers, blast radius) at the depth and workspace scale shepherd actually operates at (single-repo, low-thousands of symbols); breaks down only at graph-database scale (millions of nodes, deep transitive joins, ad hoc multi-predicate pattern matching) | Lowest — additive migration on an existing table family, same pattern as `0015_struct_shapes.sql` | **Adopt for Phase 1.** This is the only option that costs one migration, not a new subsystem |

## Recommended phased approach

### Phase 1 (near-term, cheap): `index_edges` — graph via SQL

Extend the existing symbol schema with an edges table. No new engine, no new
language tooling beyond what `refresh-symbols.sh` already does. This is
additive to `index_symbols`/`index_struct_shapes`, same cache-zone rules
(`context-registry.md`: rebuildable, safe to delete, refreshed on
`shctx refresh --scope=symbols`).

Concrete schema (new migration, e.g. `0019_symbol_edges.sql`):

```sql
-- 0019_symbol_edges.sql — relationship layer over index_symbols.
-- Cache zone: rebuildable via `shctx refresh --scope=edges` (or folded into
-- --scope=symbols once extraction is cheap enough to run in the same pass).
-- Edges are directed, symbol-to-symbol, resolved best-effort at index time
-- (Phase 1 extraction is regex/grep-tier, same precision ceiling as
-- refresh-symbols.sh today — an edge means "textual evidence of the
-- relationship," not "compiler-verified binding").

CREATE TABLE index_edges (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  src_symbol_id TEXT NOT NULL REFERENCES index_symbols(id) ON DELETE CASCADE,
  dst_symbol_id TEXT REFERENCES index_symbols(id) ON DELETE SET NULL,
  -- dst_symbol_id nullable: an edge whose target wasn't resolved to a known
  -- symbol (external crate, unresolved import) still records the raw name.
  dst_name      TEXT NOT NULL,      -- always populated, even when dst_symbol_id resolves
  dst_package   TEXT,               -- best-effort, NULL if unknown/external
  edge_kind     TEXT NOT NULL CHECK(edge_kind IN
                   ('calls','imports','inherits','implements','references',
                    'co-changes')),
  file_path     TEXT NOT NULL,      -- where the edge was observed (src's file, usually)
  line          INTEGER,
  weight        REAL NOT NULL DEFAULT 1.0,   -- co-change edges: normalized co-commit frequency
  confidence    TEXT NOT NULL DEFAULT 'grep' CHECK(confidence IN ('grep','ast','lsp')),
  language      TEXT NOT NULL,
  hash          TEXT NOT NULL,      -- dedup key for idempotent refresh, same pattern as index_symbols
  refreshed_at  INTEGER NOT NULL,
  UNIQUE(project_id, src_symbol_id, dst_name, edge_kind, file_path, line)
);
CREATE INDEX idx_edges_project_src  ON index_edges(project_id, src_symbol_id);
CREATE INDEX idx_edges_project_dst  ON index_edges(project_id, dst_symbol_id);
CREATE INDEX idx_edges_project_kind ON index_edges(project_id, edge_kind);

-- co-change edges are symmetric and derive from git history, not source text:
-- populated by `shctx refresh --scope=cochange` walking `git log --name-only`
-- over a rolling window, edge_kind='co-changes', weight = co-occurrence count
-- normalized by each file's total commit count (Jaccard-style).
```

Sample refresh path: extend `refresh-symbols.sh` (or add a sibling
`refresh-edges.sh` matching the existing per-language script pattern in
`skills/context/scripts/`) to, for each `fn`/`impl` body already located by
the current regex pass, grep the body for call-site patterns
(`\bIDENT\s*\(`) and import statements, resolve `IDENT` against
`index_symbols` for the same project (first same-package, then
workspace-wide), and insert one `index_edges` row per resolved or
unresolved reference. This is the same class of extraction
`refresh-symbols.sh` already does (regex over source, not a real parser) —
Phase 1 deliberately does not raise extraction precision, only adds the
relationship dimension on top of what's already extracted.

Example queries this schema enables:

**1. "What calls this function?" (direct + transitive callers, i.e. blast radius)**

```sql
WITH RECURSIVE callers(symbol_id, depth) AS (
  SELECT id, 0 FROM index_symbols
  WHERE project_id = :project_id AND name = :target_name
  UNION
  SELECT e.src_symbol_id, c.depth + 1
  FROM index_edges e
  JOIN callers c ON e.dst_symbol_id = c.symbol_id
  WHERE e.project_id = :project_id AND e.edge_kind = 'calls' AND c.depth < 5
)
SELECT DISTINCT s.name, s.package, s.file_path, s.line, c.depth
FROM callers c JOIN index_symbols s ON s.id = c.symbol_id
WHERE c.depth > 0
ORDER BY c.depth, s.package;
```

**2. "Blast radius of changing this type" (transitive dependents across calls/imports/inherits)**

```sql
WITH RECURSIVE dependents(symbol_id, depth) AS (
  SELECT id, 0 FROM index_symbols
  WHERE project_id = :project_id AND name = :target_name AND kind IN ('struct','enum','trait','class')
  UNION
  SELECT e.src_symbol_id, d.depth + 1
  FROM index_edges e
  JOIN dependents d ON e.dst_symbol_id = d.symbol_id
  WHERE e.project_id = :project_id
    AND e.edge_kind IN ('calls','imports','inherits','implements','references')
    AND d.depth < 6
)
SELECT s.package, COUNT(DISTINCT s.id) AS impacted_symbols,
       COUNT(DISTINCT s.file_path) AS impacted_files
FROM dependents d JOIN index_symbols s ON s.id = d.symbol_id
WHERE d.depth > 0
GROUP BY s.package
ORDER BY impacted_symbols DESC;
```

**3. DEDUP-GATE upgrade: "is this existing symbol an orphan (safe to replace) or load-bearing (must extend/wire-to)?"**

```sql
SELECT s.name, s.package, s.file_path, s.line,
       COUNT(e.id) AS consumer_count,
       COUNT(DISTINCT e.file_path) AS consumer_file_count
FROM index_symbols s
LEFT JOIN index_edges e
  ON e.dst_symbol_id = s.id AND e.edge_kind IN ('calls','references','imports')
WHERE s.project_id = :project_id AND s.name = :target_name
GROUP BY s.id;
-- consumer_count = 0 AND s exists in index_struct_shapes as part of a
-- foundation-blocking cluster (shape-dedup.md) => strong signal for
-- reconciliation option (b) "replace existing implementation" instead of (a)/(c).
```

This directly upgrades `zero-duplicate-tolerance.md` option selection
(a/b/c/d) from an eyeballed grep read to a deterministic query, and gives the
conductor's `DEDUP-GATE BLOCK` message a concrete `consumer_count` to cite.

**4. Co-change coupling ("what files historically change together with this one")**

```sql
SELECT dst_name AS coupled_file, weight
FROM index_edges
WHERE project_id = :project_id AND edge_kind = 'co-changes' AND file_path = :target_file
ORDER BY weight DESC LIMIT 10;
```

### Phase 2 (mid-term): tree-sitter extraction

Replace the regex-based extraction (both the existing `refresh-symbols.sh`
grep patterns and the Phase 1 edge extraction sketched above) with real
tree-sitter parses, one grammar per language, following the exact
per-language-script architecture `skills/context/scripts/` already uses
(`refresh-symbols.sh` is Rust-specific today; a Python/TS/Go sibling script
would each embed the matching tree-sitter grammar). This raises precision
(real AST nodes instead of line regex — fixes multi-line signatures, nested
scopes, macro-generated code that the current regex silently misses) without
changing the target schema — `index_edges` and `index_symbols` stay the same
shape, only `confidence='ast'` supersedes `confidence='grep'` rows.
`ast-grep` (Rust, actively maintained, ships prebuilt grammars for ~20
languages) is the concrete tool to vendor/shell out to here rather than
hand-rolling tree-sitter query bindings per language — it already exposes a
CLI (`ast-grep run --pattern ... --json`) that a shell script can consume the
same way `refresh-symbols.sh` shells out to `cargo metadata`.

Scope this phase to whatever languages the operator's actual consumer
projects use, in priority order, not all-languages-at-once.

### Phase 3 (long-term, evaluate only if 1/2 prove insufficient)

Triggers for opening this phase: recursive-CTE query latency becomes
user-visible at real workspace scale (tens of thousands of symbols/edges,
deep transitive closures), or Phase 2's binding resolution (which `IDENT`
call-site resolves to which `fn` definition across module boundaries) proves
too lossy for grep/AST-pattern matching alone.

Two independent sub-tracks, not a bundle — evaluate separately:

- **SCIP as an interchange format.** If the workspace already has a
  language-provided SCIP producer (rust-analyzer's `--scip` flag,
  `scip-typescript`, `scip-python`), import its `.scip` protobuf into
  `index_edges`/`index_symbols` as a higher-confidence overlay
  (`confidence='lsp'` — SCIP producers are typically LSP servers run in batch
  mode) rather than replacing the SQLite store. This is strictly an ingestion
  path, shctx remains the query layer.
- **Kùzu (or equivalent embedded graph DB) for query performance**, only if
  `WITH RECURSIVE` queries against `index_edges` are measured (not guessed)
  to be the bottleneck. Would run as an optional secondary index built from
  the same canonical SQLite rows (SQLite stays canonical per
  `context-registry.md`'s cache/canonical doctrine; Kùzu would be a
  cache-zone artifact, rebuildable, gitignored, exactly like `index_*` today).

Do not open Phase 3 speculatively. Both sub-tracks add a dependency; the
"vanilla by default" doctrine requires proving Phase 1/2 insufficient first,
with a number (query latency, false-negative rate on a real dedup incident),
not a feeling.

## Why not Glean/Kythe now (explicit)

Both are the closest existing open-source systems to "a real hypergraph of
code facts," and both were seriously considered per the research brief. Both
are rejected as the near-term (or even mid-term) default:

- **Deployment model mismatch.** Glean is a Thrift-based fact-store service
  (glean-server) with per-language indexers that write to it; Kythe is a
  Bazel-extraction-to-GraphStore-to-serving-table pipeline. Both assume
  "a team runs infrastructure for a monorepo," not "a plugin drops a single
  SQLite file into `.shepherd/` and works with zero setup." Adopting either
  means shepherd would need to bundle/manage a server process per consumer
  project — the exact model `shctx` was built to avoid (see
  `context-registry.md`: "per-project SQLite registry," gitignored, cache
  vs. canonical zones inside one file).
- **Build-coupling.** Kythe's extractors wrap the actual build (Bazel
  natively; other build systems need custom wrappers) to observe true
  compilation facts. Consumer projects using shepherd are not guaranteed to
  build with Bazel, or even to have a working build available at index time
  (shctx already tolerates `cargo` being absent). A build-coupled indexer is
  a strictly worse fit than the current grep-tolerant extraction.
- **Operational surface.** Both require schema authoring (Glean's Angle
  predicates, Kythe's fact/edge schema), indexer maintenance per language,
  and a serving layer to query — multiplying shepherd's maintenance surface
  far beyond "one more migration file," which is the actual cost ceiling
  `CLAUDE.md`'s "vanilla by default" and "search before building" doctrines
  set for this kind of addition. The marginal capability gain (true
  compiler-derived facts vs. grep/AST-pattern-derived facts) is real but not
  proportionate to the infra cost at shepherd's actual operating scale
  (single project, per-session, no fleet-wide index to amortize the cost
  over).
- **What's worth keeping from them.** Their *schemas* are useful design
  references even though their runtimes aren't adopted: Kythe's edge-kind
  vocabulary (`ref`, `ref/call`, `defines`, `overrides`, `childof`,
  `extends`) is a reasonable starting point for `index_edges.edge_kind`
  beyond the six kinds sketched in Phase 1, and SCIP's occurrence model
  (symbol + role: definition/reference/write-access) is worth mirroring if
  Phase 2 needs a richer confidence/role dimension than `confidence` alone
  provides.

This is the concrete application of `CLAUDE.md`'s search-before-building
ladder: Layer 1 (tried-and-true = SQLite + recursive CTEs, which is what
`shctx` already is) wins because Layer 2/3 candidates (SCIP producers,
stack-graphs, Kùzu) don't yet clear a proportionate integration cost, and the
heavyweight Layer-3-adjacent options (Glean, Kythe) fail the "genuinely
different situation" test in the wrong direction — they're built for a
different deployment shape (fleet-scale monorepo infra), not a harder
version of shepherd's actual problem.

## Open questions / non-goals

Open questions (need an operator decision before Phase 1 ships, not answered
by this doc):

- **Binding resolution ambiguity.** When a Phase 1 regex call-site `foo()`
  matches multiple `index_symbols` rows (same name, different packages),
  does the edge fan out to all candidates (`confidence='grep'`, ambiguous)
  or resolve only within the same-package/same-file scope and drop
  cross-package calls to `dst_symbol_id = NULL`? Affects false-positive rate
  on blast-radius queries. Recommend: same-package-first, NULL otherwise, in
  Phase 1; Phase 2's AST scoping resolves most of this for free.
- **Co-change edge freshness/window.** How large a git-log window
  (`--since`) balances signal vs. staleness, and does it get its own
  `--scope=cochange` refresh or fold into `--scope=symbols`? Needs a decision
  once Phase 1 is actually scheduled, not now.
- **Edge table growth vs. `index_symbols` UNIQUE constraint pattern.** Should
  edges from stale/deleted symbols be swept on every refresh (mirroring
  `refresh-symbols.sh`'s `DELETE ... WHERE refreshed_at < $now` sweep), or
  soft-expired? Recommend mirroring the existing sweep pattern for
  consistency, decide at implementation time.
- **Where the "what calls this" query surfaces.** As a new `shctx query`
  named query (`callers-of --name=X`), a new `shctx graph <blast-radius|
  callers|dependents>` verb, or folded into `dedup-check`'s output? This is
  a CLI ergonomics decision for whoever implements Phase 1, out of scope for
  this research doc.

Explicit non-goals for this doc and for Phase 1/2:

- Not proposing a general-purpose code-intelligence product (no goal to
  match Sourcegraph's cross-repo search UX or GitHub's code-nav UI).
- Not proposing real type-checking or compiler-verified bindings in Phase
  1/2 — `confidence='grep'|'ast'` explicitly signals "best-effort," and nothing
  in the dedup-gate doctrine should ever treat an edge-table miss as proof
  of absence (same "absence of evidence" caution `SKILL.md` already states
  for `shctx` path resolution).
- Not proposing multi-project/fleet-wide graph federation — this stays
  per-project, matching every other `shctx` table's `project_id` scoping.
- Not committing to a timeline. Per the brief, this is a long-term project;
  no phase here is scheduled against a sprint.

## See also

- `skills/context/SKILL.md` — CLI quick reference, cache-vs-canonical table.
- `skills/context/scripts/refresh-symbols.sh` — current regex-based Rust
  symbol extractor this doc's Phase 1/2 extend.
- `skills/context/schema/0001_init.sql` — `index_symbols` baseline schema.
- `skills/context/schema/migrations/0015_struct_shapes.sql` — the field-shape
  precedent this doc's `index_edges` follows (additive migration, cache
  zone, `shctx refresh --scope=<new>` pattern).
- `skills/shepherd/doctrines/context-registry.md` — cache vs. canonical
  doctrine `index_edges` must respect.
- `skills/shepherd/doctrines/zero-duplicate-tolerance.md` — the four-layer
  dedup stack `index_edges` upgrades (Layer 2 DEDUP-GATE reconciliation
  options a/b/c/d).
- `skills/shepherd/doctrines/shape-dedup.md` — the field-shape leg this
  relationship layer complements (shape answers "does this exist," edges
  answer "what depends on it").
