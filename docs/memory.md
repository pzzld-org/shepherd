# Memory — the registry vs. Claude Code's native memory

Two questions this sprint asked: is `/shepherd:context` a naming conflict, and do
Claude Code's newer native-memory features make shepherd's own memory layer
unnecessary? Short answers: the rename already shipped, and no — the registry
stays, because the two systems cover different work.

## Naming: resolved

- The command is **`/shepherd:ctx`** (`commands/ctx.md`), not `/shepherd:context`.
- The skill is **`shepherd-context`** (`skills/context/SKILL.md` frontmatter `name:`).
- Claude Code's `/context` is a **slash command**, not a tool name, and plugin
  commands are namespaced under `shepherd:` — so there is no hard collision.
  Reserved tool names (Agent, Workflow, Read, …) are all avoided.

## What native memory covers

Claude Code now ships native memory (docs: `code.claude.com/docs/en/memory`):

- **`CLAUDE.md`** hierarchy (`~/.claude/CLAUDE.md` user, project, local) — always
  loaded, human-authored instructions.
- **Auto memory** at `~/.claude/projects/<project>/memory/` (`MEMORY.md` index +
  topic files, `/memory` to toggle) — Claude's own learnings across sessions.
- **Per-subagent memory** via the `memory: user|project|local` frontmatter field.

This is best-effort prose notes for future sessions: build commands, debugging
insights, preferences. It persists across `/clear` and `/resume`.

## Why the SQLite registry stays

`/shepherd:ctx` (`.shepherd/shepherd.db`) is a **queryable relational store**, not
notes. It does what native memory structurally cannot:

| Registry (`shctx`) | Native memory |
| :--- | :--- |
| FTS5 symbol + artifact search, dedup by name/shape | Prose recall |
| GitHub issue/PR/release cache, event log | — |
| Teammate liveness, locks, focus record, Stage-Graph state | — |
| Adaptation priors as typed rows (`adapt roll`/`priors`) | Freeform learnings |
| Read/written by hooks and the CLI, outside a model turn | Model-authored only |

The DEDUP-GATE, the carry-forward ledger, liveness, and the Stage-Graph walk all
need structured queries and out-of-turn writes. Native memory cannot back any of
them. So the registry is retained.

## Where they compose

Native memory is the better home for the **lesson/doctrine layer** that is prose
by nature. Shepherd's adaptation loop (`skills/adaptation/SKILL.md`) already keeps
typed priors in the DB for sizing and dedup; a project's user-wide doctrines and
durable learnings can additionally live in `~/.claude/CLAUDE.md` or native auto
memory so they ride along in every session without a registry read. The two are
complementary: structured state in the registry, prose context in native memory.
