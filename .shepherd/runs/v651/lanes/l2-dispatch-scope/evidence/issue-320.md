# L2 / D6 (#320) — Write-versus-Bash asymmetry, measured before disposition

Same tree, same binary as `issue-323.md` (`shepherd-cli 6.5.1` from `target/debug`, G3).

## Measurement 1 — the plan's two payloads, verbatim

```
$ printf '{"tool_name":"Write","role":"auditor","tool_input":{"file_path":"/tmp/x/out.md"}}' | shepherd guard eval
{"decision": "unresolved", "reason": "native dispatch write-scope resolution is missing", "missing": ["dispatch.path_in_write_scope"]}

$ printf '{"tool_name":"Bash","role":"auditor","tool_input":{"command":"echo hi > /tmp/x/out.md"}}' | shepherd guard eval
{"decision": "allow"}
```

The plan's L2-S2 acceptance implies this pair yields a deny-versus-allow diff. It does not:
the `Write` payload is `unresolved`, because `evaluate_write_tool` requires a native
dispatch resolution block that a bare payload does not carry. The Claude adapter translates
`unresolved` to a fail-closed denial, so the operator-visible behaviour is still
deny-versus-allow — but the recorded verdict is `unresolved`, and this artifact records what
was actually printed. **Plan claim contradicted; see the lane report.**

## Measurement 2 — the same two payloads with a real dispatch resolution attached

This is the apples-to-apples comparison: same role, same destination path, same dispatch
block, same declared write scope.

```
$ printf '{"tool_name":"Write","role":"auditor","tool_input":{"file_path":"/tmp/x/out.md"},"dispatch":{"schema":"shepherd.identity-resolution/1","role":"auditor","write_paths":[".shepherd/runs/v651/reports/a.md"],"path_in_write_scope":false}}' | shepherd guard eval
{"decision": "deny", "predicate": "write-boundary", "rule": "role-write-eligibility,path-in-declared-scope", "halt_code": "DISCOVERY-WRITE-PATH", "reason": "fs.write is denied outright when the role's content/roles/<role>.md declares write_eligible: false. / Even a write_eligible = true role's write is denied when the target path falls outside the write_scope this specific dispatch's brief declares (a general write grant is not a blanket grant — the brief's file scope narrows it per dispatch)."}

$ printf '{"tool_name":"Bash","role":"auditor","tool_input":{"command":"echo hi > /tmp/x/out.md"},"dispatch":{"schema":"shepherd.identity-resolution/1","role":"auditor","write_paths":[".shepherd/runs/v651/reports/a.md"],"path_in_write_scope":false}}' | shepherd guard eval
{"decision": "allow"}
```

**REPRODUCED, and unambiguously.** Identical role, identical destination, identical
dispatch-scope facts. `Write` denies. `Bash` performing the same write allows.

The `dispatch` block is ignored entirely on the `Bash` path — supplying it changes nothing.

## Measurement 3 — it is not redirect-specific

```
  tee /tmp/x/out.md                 -> {"decision": "allow"}
  cp /etc/hosts /tmp/x/out.md       -> {"decision": "allow"}
  git commit -am x                  -> {"decision": "deny", "predicate": "git-custody", "rule": "implementer-never-writes-git", "halt_code": "CODER-GIT-WRITE", …}
```

Every non-git filesystem write through `Bash` allows. A git verb denies.

## Root cause — the predicate is not asymmetric; the router never reaches it

`crates/core/src/guard/engine.rs:209-234`, `evaluate_tool_call`:

- `WRITE_TOOL_NAMES = ["Write", "Edit", "apply_patch"]` (`:22`) route to
  `evaluate_write_tool`, which evaluates the `write-boundary` predicate under the `fs.write`
  action.
- `tool_name == "Bash"` routes to `evaluate_bash_tool` (`:335-382`), which inspects the
  command **only** for git subcommands via `extract_git_subcommands`, maps them to
  `vcs.integrate` / `vcs.write`, and returns a bare `Verdict::allow()` at `:360-361` for
  everything else.

`write-boundary` is therefore **never consulted for `Bash`, under any command**. There is
one `path_in_dispatch_write_scope` fact and one predicate that reads it (verified:
`grep -rn "path_in_dispatch_write_scope" crates/ content/` — one producer at `:334`, one
consumer pair at `:644` and `:648`); the `Bash` path simply never produces it. #320 is a
tool-router gap, not a predicate conflict.

## Disposition

The asymmetry is **intended at this boundary and out of this lane's reach to remove.**

Closing it would mean statically parsing arbitrary shell for filesystem effects — inferring
a write target from redirects, `tee`, `cp`, `dd`, `install`, `sed -i`, `python3 -c`, and
every other spelling — and then denying on the inference. That is a new subsystem, which
global constraint G2 makes a critic-RED escalation, and it is a static-analysis arms race
the v6.4.5 note at `hooks/tests/test_native_cli_contract.sh:77-81` already declines for the
same reason on the `Workflow`-script side. The honest boundary is the one that exists: the
typed tool surface carries a typed target and is governed; an opaque shell string is not
statically governable and is governed by role tier instead.

Widening `Write` to permit out-of-repo absolute paths is refused outright by the step's
NON-GOALS and is the wrong direction regardless.

So: the asymmetry stands, and it is pinned by a test so a future author cannot "fix" it by
accident and cannot narrow `Bash` without deliberately deleting an assertion that says why.
#320 closes citing this file.
