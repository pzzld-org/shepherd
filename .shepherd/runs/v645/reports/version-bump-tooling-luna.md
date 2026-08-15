# Version bump tooling report

Status: DONE

## Outcome

`scripts/version-bump.py` is the only deterministic release-version updater.
It validates the complete current authority set before writing, advances only
the canonical mod-10 successor, validates the fully rendered next state in
memory, stages every changed file beside its destination, rejects concurrent
drift, and publishes each file with atomic replacement plus rollback.

The current v6.4.5 tree has 43 checked authority and inventory files. A live
v6.4.5 to v6.4.6 rehearsal changed 36 files in an isolated copy, then the
v6.4.6 check passed. The repository itself was not version-bumped.

The update set includes:

- the workspace version, six internal Cargo dependency pins, and all seven
  Shepherd entries in `Cargo.lock`;
- the root npm version, all four package versions, all three adapter dependency
  pins, and their `package-lock.json` mirrors;
- `.claude-plugin/plugin.json` and the self-contained Claude release ZIP
  references. The retired `.claude-plugin/marketplace.json` is deliberately not
  recreated;
- the versioned WIT package, Rust and JavaScript component constants, the Pi
  contract, CI/gate assertions, package tests, release tests, and direct user
  documentation;
- the wrong-version negative controls in the installer and asset tests, which
  advance one version beyond the new current value so they remain negative.

Historical strings are not rewritten. The scanner classifies conformance
authorities, migration/layout fixtures, the changelog, run artifacts, and
legacy provenance comments as history. It refuses a new unclassified version
reference in active code, docs, packages, scripts, or CI.

The canonical skill sources have no product-version frontmatter. The tool does
not invent one or churn skill prose during a release bump.

## Workflow invocation

Replace the release workflow's handwritten jq/sed bump block with:

```bash
python3 scripts/version-bump.py bump \
  --root "$GITHUB_WORKSPACE" \
  --current "$CURRENT" \
  --next "$NEXT"
python3 scripts/version-bump.py check \
  --root "$GITHUB_WORKSPACE" \
  --version "$NEXT"
```

The bump command prints the exact changed paths after its success line. The
workflow must stage those emitted paths, not a broad `git add -A`.

Wire this deterministic gate alongside the focused test:

```bash
python3 scripts/tests/test-version-bump.py
```

## Evidence

```text
$ python3 scripts/tests/test-version-bump.py
....
Ran 4 tests in 0.253s
OK

$ python3 scripts/version-bump.py check --version 6.4.5 --root .
version-bump: OK version=6.4.5 authorities=43 mode=check

$ python3 scripts/version-bump.py bump --current 6.4.5 --next 6.4.6 --root <isolated-live-copy>
version-bump: OK current=6.4.5 next=6.4.6 updated=36

$ python3 scripts/version-bump.py check --version 6.4.6 --root <isolated-live-copy>
version-bump: OK version=6.4.6 authorities=43 mode=check

$ python3 -m py_compile scripts/version-bump.py scripts/tests/test-version-bump.py
exit 0
```

The four fixture tests prove the complete update, stale-surface refusal,
missing-surface refusal, canonical-successor refusal, preservation of
historical version strings, and byte-for-byte no-write behavior on validation
failure.
