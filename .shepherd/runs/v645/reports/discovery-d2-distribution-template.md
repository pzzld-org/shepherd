# D2 — distribution and template engine

**Reporter:** `@discovery` · **Run:** v645 · **Materialized by:** root (payload landed in root's
notification stream, not the dispatching engineer's — see `dogfood.md` DF-11) · 2026-08-12

## Current launcher defect — the brief's premise does not exist

**The mechanism the seed describes — "globs `cache/fl03/shepherd/*` only" — does not exist anywhere in
current code.** Grepped `hooks/`, `scripts/`, `.claude-plugin/plugin.json`, `README.md`: zero hits outside
comments *describing the historical bug*. It survives verbatim only in the GH issue body and in
`scripts/install-shctx-launcher.sh:5`'s own header comment recording the history.

Current code, shipped v6.4.3 in commit `d887ad4`: `scripts/install-shctx-launcher.sh:142-175` scans
`cache/*/shepherd/*` — every publisher, wildcard segment at `:147` — and picks the highest version by real
semver ordering on the version path segment (`sort -V`, with a pure-bash `version_gt()` fallback at
`:87-104`). Line `:138` explicitly refuses a silent fallback, citing "#235 bug class". 19 regression tests
at `scripts/tests/test_shctx_launcher.sh` include the exact `fl03/6.3.3` versus `pzzld/6.3.9` scenario from
the issue. `CHANGELOG.md:83` documents it as shipped.

**The residual defect is distribution, not logic: nothing auto-invokes the script.** Zero references in
`hooks/hooks.json`, `.claude-plugin/plugin.json`, `hooks/scripts/session_open.sh`, or `README.md`'s
troubleshooting table (`README.md:274` instead points users at the different, legacy
`skills/context/scripts/` bash path via `/shepherd:ctx`). An operator has to know the script exists and run
it by hand. #235's own Ask — "ship the publisher-agnostic launcher **in the plugin installer**" — is
exactly this gap and is why the issue remains open.

**This resolves seed §11 open question 1 for #235: the code fix is genuinely shipped and tested; the
auto-wiring is not.** The seed's citation of #235 as "live pain" needs restating.

## Template feature inventory

| Feature | Used in | minijinja status |
|---|---|---|
| `{{ var }}` interpolation | all 5 | present, core grammar — MATCH |
| `{% if %}…{% endif %}` | boot-prompt, lane-plan | present — MATCH |
| `{% for %}…{% endfor %}` | lane-plan, plan, seed | present — MATCH |
| `{% for %}…{% else %}…{% endfor %}` | lane-plan (x4) | present per COMPATIBILITY.md ("for loops with optional else clause"); whitespace boundary at `{% else %}` **not independently traced** |
| nested loops (`step.actions` inside `step`) | lane-plan | core grammar — MATCH |
| `is not none` | boot-prompt:108 | `none` test built in, `not` is core grammar — MATCH |
| `tojson` (custom override) | boot-prompt:112, seed:23-24 | builtin exists but **semantically diverges** — hazard 1 |
| `{# … #}` comments | all 5 (header docstrings) | present; `trim_blocks`/`lstrip_blocks` verified to apply to comment tokens identically to block tags — MATCH |
| `{% include %}` / `{% extends %}` / macros | none (grepped) | N/A — not exercised |
| `loop.*` special variable | none | N/A |
| `{% set %}` / `{% with %}` | none | N/A |
| custom Python filters besides `tojson` | none — whole `shepherd_cli` package grepped, only `render.py:160` registers a filter | N/A by construction |
| `StrictUndefined` | global env (`render.py:154`) | `UndefinedBehavior::Strict` equivalent — hard `Err` on print/iterate/attribute/coerce/truthiness — MATCH, explicit opt-in both sides |
| `autoescape=False` | global env (`render.py:158`) | default autoescape for non-HTML template names not verified; low risk, output is Markdown |
| legacy `{{BRANCH}}` bare vars, in-memory `from_string()` | handoff.md.j2 only (`commands/handoff.py:483`) | core grammar via the `from_string` equivalent, but the loader entry point differs — hazard 3 |

## Whitespace and newline defaults

Verified from source, not memory:

| Setting | Jinja2 default | minijinja default | This repo | Verdict |
|---|---|---|---|---|
| `trim_blocks` | `False` (`jinja2/defaults.py`, read from the repo's own `.venv`) | `false` (`Environment::set_trim_blocks`) | **`True`** (`render.py:155`) | MATCH |
| `lstrip_blocks` | `False` | `false` | **`True`** (`render.py:156`) | MATCH |
| `keep_trailing_newline` | `False` | `false` | **`True`** (`render.py:157`) | MATCH |

Both engines expose the identical three knobs with identical default polarity, and minijinja's setter
semantics ("remove the first newline after a block tag" / "remove leading spaces and tabs to a block") are
the same mechanic Jinja2 implements. Confirmed from `minijinja/src/compiler/lexer.rs:572-593` and
`:662-681` that `trim_blocks`/`lstrip_blocks` apply to **comment tags** exactly like block tags, via the
same `handle_tail_ws`/`skip_newline_if_trim_blocks` path every `StartMarker` variant funnels through —
which matters because all 5 templates open with a `{# … #}` header comment immediately followed by content.

**Caveat, not a divergence:** MATCH is contingent on the Rust port actually calling all three setters.
minijinja does not read a config file and does not infer these from Jinja2 semantics.

## Parity hazards

1. **HIGH — `tojson` is not a drop-in.** `render.py:129-138`'s `_sorted_tojson` is
   `json.dumps(value, sort_keys=True, separators=(", ", ": "), ensure_ascii=False)` — plain JSON, key-sorted,
   no HTML escaping. minijinja's builtin `tojson` (`minijinja/src/filters.rs:1205-1219`) **unconditionally
   HTML-escapes** `<`, `>`, `&`, `'` into `<`/`>`/`&`/`'`, and its default non-pretty
   formatter **does not sort map keys**. Threatens `boot-prompt.md.j2` (`peer_teammate_names | tojson`) and
   `seed.md.j2` (`sprint_dependencies | tojson`, `parallel_with | tojson`) — any list element containing
   `&` or `'`, plausible in a branch name, path, or URL, renders different bytes. **The Rust port must
   hand-write a byte-identical replacement filter, never reuse the builtin.**
2. **MEDIUM — the 4-knob configuration is easy to under-set.** `trim_blocks`, `lstrip_blocks`,
   `keep_trailing_newline`, and `UndefinedBehavior::Strict` all mechanically match but require four
   explicit setter calls on the Rust `Environment`. Omitting even one — `keep_trailing_newline` is the
   likeliest — silently reintroduces a trailing-newline diff across every rendered artifact, detectable
   only by the `output_sha256` gate itself, with no compile-time signal.
3. **MEDIUM — `handoff.md.j2`'s in-memory path is unverified.** `commands/handoff.py:483` renders via
   `build_env().from_string(template_text)`, not the `FileSystemLoader` path the other four use.
   minijinja's equivalent in-memory entry point (likely `Environment::template_from_str` /
   `template_from_named_str`) was not verified to produce byte-identical output to the loader path. Open
   question, not confirmed either way. Threatens `handoff.md.j2` only.
4. **LOW — `for/else` whitespace boundary unverified.** The clause's presence is confirmed; exact
   stripping right at `{% else %}` in `lane-plan.md.j2` (used 4x, always as an empty-loop "- none"
   fallback) was not traced through the lexer.
5. **LOW — `is not none`.** Core grammar, negligible risk.

## npm distribution

Root skeleton, verified against live `esbuild@0.28.2` and `@biomejs/biome@2.5.8` registry package.json via
unpkg:

```json
{
  "name": "shepherd",
  "version": "6.4.5",
  "bin": { "shepherd": "bin/shepherd" },
  "scripts": { "postinstall": "node install.js" },
  "optionalDependencies": {
    "@shepherd/darwin-arm64": "6.4.5",
    "@shepherd/darwin-x64": "6.4.5",
    "@shepherd/linux-x64-gnu": "6.4.5",
    "@shepherd/linux-x64-musl": "6.4.5",
    "@shepherd/linux-arm64-gnu": "6.4.5",
    "@shepherd/linux-arm64-musl": "6.4.5",
    "@shepherd/win32-x64": "6.4.5"
  }
}
```

One platform package, verified shape (`@biomejs/cli-linux-x64-musl`):

```json
{ "name": "@shepherd/linux-x64-musl", "version": "6.4.5",
  "os": ["linux"], "cpu": ["x64"], "libc": ["musl"] }
```

- **Use biome as the musl precedent, not esbuild.** biome splits gnu/musl by package-name suffix **and** an
  explicit `"libc": ["musl"]` field. esbuild ships **no** `-musl` variant and **no** `libc` field on
  `@esbuild/linux-x64` at all (confirmed empty on the live registry copy) — it relies on a single
  glibc-linked binary plus runtime fallback.
- **UNVERIFIED:** whether biome's glibc sibling (`@biomejs/cli-linux-x64`) carries an explicit
  `libc: ["glibc"]` or omits the field. Both are legal; omission is more common. Only the musl variant's
  fields were verified directly.
- **npm `libc` field floor is npm v10.3.0**, not "any npm 10.x" — the `--libc` install-override flag and
  the package.json field landed together in PR npm/cli#6914.
- **Install-time filtering is not runtime selection.** `libc` in package.json only controls which package
  npm *installs*. If the launcher ever needs to choose between two *installed* variants at runtime it needs
  its own `process.report.getReport().header.glibcVersionRuntime` or a `detect-libc`-style check.
- **npm/cli#8320 is CLOSED but self-resolved**, not fixed. The reporter's fresh `npm@11.4.1` install worked;
  npm triaged it as a likely duplicate of the long-standing #4828/#7961/#7543/#7750 class — "optional-dependency
  entries generated in `package-lock.json` on one platform don't cover other platforms, so `npm ci` on a
  different platform can't resolve the platform package and the `require()` throws
  `Cannot find module @scope/platform-pkg`" (exact error text confirmed in the issue body). **No structural
  fix has landed.** The seed's own locked mitigation — generate and commit `package-lock.json` from a
  Linux-glibc CI runner — is the correct workaround, and must be regenerated on every platform-package
  version bump.
- **`--no-optional` fallback, verified from esbuild's `install.js`:** `checkAndPreparePackage()` calls
  `require.resolve()` first; on failure it logs a diagnostic explicitly naming `--no-optional` as the likely
  cause, then tries in order (1) `installUsingNPM()` — pull the missing platform package directly,
  (2) `downloadDirectlyFromNPM()` — fetch the tarball straight from the registry, (3) throw
  `Failed to install package "<pkg>"`. **Name the behavior: a postinstall self-heal that re-fetches over
  the network with a clear diagnostic — never a silent no-op, never an opaque native-module stack trace.**
