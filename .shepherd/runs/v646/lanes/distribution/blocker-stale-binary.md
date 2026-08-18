# BLOCKER: the binary on PATH is stale, and it blocks every dispatched coder

Recorded by the `distribution` lane conductor. Not a lane defect; a run-wide one.
This blocked wave 1 of all four lanes, and it is the same defect class as this lane's own
deliverable 2.

## Symptom

Five coders dispatched, re-based, and resumed. 18+ tool calls between them after resuming.
ZERO files written. `git status --porcelain -- scripts/ bin/ .github/ docs/ README.md` empty.
Each returned a bare `BLOCKED.`

## Cause, measured

| Event | Time | In the installed binary? |
|---|---|---|
| `bd391e1` fix(hook): forward the host tool envelope so a root session can write | 20:31:01 | YES |
| **`~/.cargo/bin/shepherd` built** | **20:31:38** | - |
| `7e63628` fix(dispatch): resolve a subagent tool call from agent_id alone | 20:39:06 | **NO** |
| `aa6dc98` fix(hook): stop running the pre-flight guard after the tool has run | 20:41:07 | **NO** |

The reinstall captured `bd391e1`, which fixed the ROOT session's writes. That is why root's
own writes began working and the problem read as solved. It predates `7e63628` by eight
minutes, and `7e63628` is the commit that fixes SUBAGENT tool calls.

`7e63628`'s commit message states the mechanism: "Identity normalization rejected any envelope
carrying one of agent_id and agent_type without the other. A host resends agent_id on every
subagent tool call but declares agent_type only when the agent starts, so every dispatched
agent's PreToolUse failed to normalize and the guard never evaluated it at all."

Corroboration:
- Every Bash call from the conductor still prints
  `[shepherd] dispatch state unavailable, tool allowed: invalid dispatch record: native
  identity requires both agent_id and agent_type` - verbatim the error `7e63628` fixes, still
  emitted by the binary on PATH. Fails OPEN for the conductor, not for dispatched coders.
- `shepherd guard eval` on a coder write, for every path tried including in-scope ones:
  `{"decision": "unresolved", "reason": "native dispatch write-scope resolution is missing",
  "missing": ["dispatch.path_in_write_scope"]}`

## Fix

```
cargo install --path crates/cli --locked --force
```

## Why `--version` cannot detect this

The stale binary and the fixed one BOTH report `shepherd-cli 6.4.6`. Version is useless as a
probe here. Only the build timestamp compared against the commit log exposes it. This is the
second occurrence in one session; the project memory already records the first, where the
binary sat at 6.4.5 while 6.4.6 source was edited.

## Consequence for deliverable 2

This is deliverable 2's defect class taking out the sprint that fixes deliverable 2. It is the
evidence for the `shepherd doctor` check handed to the identity lane: doctor must report the
resolved path, whether it is the native binary, AND the skew between the resolved binary and
the checkout. A version-only comparison would have reported HEALTHY through both of today's
incidents.
