---
title: Discovery — Render conformance suite status
date: 2026-08-13
discovery_id: conformance-render-v645
sprint: v6.4.5
sources_consulted: 4
tool_calls_used: 12
time_used_minutes: 8
---

## Sources

1. `/Users/jo3/src/fl03/shepherd/conformance/run.sh` — main runner script
2. `/Users/jo3/src/fl03/shepherd/conformance/runner.py` — Python implementation
3. `/Users/jo3/src/fl03/shepherd/conformance/lib/harness.py` — execution harness
4. `/Users/jo3/src/fl03/shepherd/conformance/cases/` directory structure

## Findings

### Q1: Does `conformance/run.sh --suite=render` exist as a valid suite?

**Status: No, the render suite does NOT exist.**

Confirmed by direct inspection of `conformance/cases/` at `/Users/jo3/src/fl03/shepherd/conformance/cases/` — only two suite directories exist:
- `conformance/cases/core/` (6 cases)
- `conformance/cases/guard-cli/` (9 cases)

Total corpus: 15 cases across 2 suites.

When `--suite=render` is passed: `conformance/run.sh --impl=python --suite=render` exits with code **1** and produces stderr: `conformance: no cases found (suite='render', cases_dir=/Users/jo3/src/fl03/shepherd/conformance/cases)` (harness.py:52).

When `--suite=render --count` is passed: exits with code **0** and prints `0` (runner.py:47-49 returns 0 before the empty-cases check).

### Q2: `--suite` argument handling and unknown-suite behavior

**Exit code and message for unknown suite (run mode):**
- Exit code: **1** (fail closed)
- Message: `conformance: no cases found (suite='<name>', cases_dir=<path>)` to stderr
- Implementation: runner.py:51-53

**Code path (run.sh:103-113, runner.py:23-54):**
1. `run.sh` parses `--suite=<name>` into variable `suite` (line 47: `--suite=*) suite="${arg#--suite=}" ;;`)
2. Passes `--suite "$suite"` to runner.py (line 110)
3. runner.py calls `harness.discover_cases(cases_dir, args.suite)` (line 45)
4. harness.discover_cases (line 169-184) applies suite filter: `if suite is not None: cases = [c for c in cases if c.suite == suite]`
5. If cases list is empty and NOT in `--count` mode, runner.py exits 1 with the error message (line 51-53)

**Fail behavior: FAIL CLOSED.** An unknown suite name produces exit code 1, not 0. The suite name is compared for exact string equality against the "suite" JSON field in each case.json.

### Q3: Flag implementation — `--impl=rust` and `--assert-reproducible`

**`--impl=rust`: IMPLEMENTED (stub)**
- Argument: Parsed by run.sh line 46 (`--impl=*) impl="${arg#--impl=}" ;;`)
- Validation: run.sh lines 67-70 check that `--impl` is either "python" or "rust"
- Behavior (run.sh:90-101): When `impl==rust`, prints `conformance --impl=rust: 0 cases implemented (Rust port not yet built -- W1-W3)` and exits 0
- In `--count` mode: prints `0` and exits 0

**`--assert-reproducible`: NOT IMPLEMENTED**
- Zero occurrences in runner.py (verified by grep -n)
- Zero occurrences in run.sh (verified by grep -n)
- Zero occurrences in harness.py (verified by grep -n)
- Not a recognized flag; would trigger run.sh's unknown-arg handler (line 54-58): exit code 2, message `run.sh: unknown arg: --assert-reproducible`

### Q4: On-disk case directory shape

**Structure per case (e.g., `conformance/cases/core/run/init-ok/`):**

```
cases/<suite>/<category>/<name>/
├── case.json                    # Metadata + invocation definition
└── expected/
    ├── exit_code                # Decimal exit code, newline-terminated
    ├── stdout.txt               # Exact normalized stdout bytes
    ├── [stderr.txt]             # Optional: normalized stderr (present only if recorded)
    ├── [files/]                 # Optional: captured file subdirectory
    │   └── <relpath__escaped>.txt  # Normalized file content (e.g., runs__v900-dev0__run.json.txt)
    └── [sqlite_master.txt]      # Optional: normalized sqlite_master dump
```

**case.json Schema** (harness.py:83-144, runner.py parser line 34-41):
```json
{
  "suite": "core|guard-cli",                      // Defaults to "core"
  "kind": "pure|mutating",                        // Required
  "description": "human summary",                 // Required
  "args": ["shepherd", "subcommand", "..."],      // Required; CLI argv tail
  "db_fixture": "none|full_schema",               // Defaults to "none"
  "seed_sql": ["INSERT ...", "..."],              // Optional; raw SQL to apply after schema
  "setup": [["arg1", "arg2"], [...], ...],        // Optional; pre-capture invocations (must exit 0)
  "stdin": "bytes",                               // NOT in JSON; use stdin_file instead
  "stdin_file": "fixture-file-name",              // Optional; relative path under case_dir
  "input_files": {                                // Optional; {relpath in scratch: fixture filename}
    "input.rs": "input.seed.md"
  },
  "capture_files": [                              // Optional; paths under SHEPHERD_WORKDIR to capture
    "runs/<id>/run.json",
    "status/log.txt"
  ],
  "capture_sqlite_master": true|false             // Defaults to false; captures sqlite_master dump
}
```

**File path escaping for capture_files:**
- Path separators `/` in `capture_files` entries are escaped to `__` when materialized in `expected/files/` (harness.py:443: `def _file_key(relpath: str)`)
- Example: `runs/v900-dev0/run.json` → `expected/files/runs__v900-dev0__run.json.txt`

### Q5: Files required for a hypothetical render suite

If a `conformance/cases/render/` suite were to exist, it would require:

**Minimum directory structure:**
```
conformance/cases/render/
├── <category1>/
│   └── <name1>/
│       ├── case.json
│       └── expected/
│           ├── exit_code
│           └── stdout.txt
└── <category2>/
    └── <name2>/
        ├── case.json
        ├── [fixture-files as needed]
        └── expected/
            └── ...
```

**Per-case files needed:**
1. **case.json** — metadata; must include `"suite": "render"`
2. **expected/exit_code** — single line with decimal exit code (typically 0 for success)
3. **expected/stdout.txt** — normalized stdout from the invocation
4. **expected/stderr.txt** — optional; normalized stderr (only if stderr was recorded)
5. **expected/files/** — optional subdirectory; one file per `capture_files` entry (escaped path)
6. **expected/sqlite_master.txt** — optional; if `capture_sqlite_master: true`
7. **Fixture files** (optional) — any input files referenced in case.json's `input_files` or `stdin_file`

**No other files or directories are required or recognized by the runner.**

## Open questions

None. The conformance system is deterministic and fully introspectable.

## Confidence

**HIGH.** All findings are backed by exact file:line citations and direct execution traces:

- Suite existence: verified by `ls -la conformance/cases/` (only `core`, `guard-cli` present)
- Suite handling: runner.py:45 `discover_cases()`, harness.py:169-184 filter logic
- Exit code behavior: run.sh:62-70 `--impl` validation; runner.py:51-53 empty-cases check
- `--impl=rust`: run.sh:90-101 (stub implementation, prints 0 cases, exits 0)
- `--assert-reproducible`: confirmed NOT present via grep across all three source files
- Case directory shape: harness.py:442-468 (record_case), 471-517 (verify_case), 259-291 (dump_sqlite_master)
- File key escaping: harness.py:441-443 (`_file_key` function)

## Suggested follow-ups

1. If a render suite is planned, create `conformance/cases/render/` and populate with test cases following the schema above.
2. To author cases: use `conformance/run.sh --impl=python --record` (harness.py:55-59) to freeze live CLI output as golden bytes.
3. To verify case integrity: `conformance/run.sh --impl=python --suite=render` (will exit 1 with "no cases found" until cases exist).
4. Note: The corpus checksum (`conformance/CHECKSUM`) will need to be regenerated after adding render cases: `conformance/scripts/checksum.sh > conformance/CHECKSUM` (run.sh:78-88).
