# shepherd-cli

`shepherd` is the only supported Shepherd command-line authority. The engine,
guard policy, dispatch identity, configuration, registry, and content compiler
are Rust crates behind this executable. Python, shell, and Node entrypoints are
not fallback CLIs.

The binary embeds the canonical `content/` corpus when it is built, so normal
use does not depend on a source checkout:

```console
shepherd guard test
shepherd compile --target claude
shepherd compile --target codex --out ./generated/codex
shepherd compile --target codex --out ./generated/codex --check
```

`compile` supports `claude`, `codex`, and `pi`. Without `--out`, it writes one
JSON manifest to stdout and changes nothing. With `--out`, it writes a managed
tree plus `.shepherd-generated.json`. Every manifest entry records its source
path, source and output SHA-256 values, line/word/byte/token measurements, and
the whole-tree digest.

Materialization is fail-closed:

- relative emitted paths are validated before use;
- directory and file access refuses symlink targets below the selected root;
- files are synced and renamed atomically in their destination directories;
- an existing generated file is overwritten or removed only when the prior
  manifest proves ownership and its current bytes still match;
- `--check` performs no writes;
- `--content-dir` is an explicit authoring/test override. Production uses the
  corpus embedded in the executable.

An unknown legacy verb exits with a stable retirement error. It is never
forwarded to a hidden Python, Bash, or Node implementation.
