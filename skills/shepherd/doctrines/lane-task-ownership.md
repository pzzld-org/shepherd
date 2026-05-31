# Lane-task ownership (v6.0.3 — #102)

> Framework-intrinsic. Applies under `/shepherd:spawn` (Agent Teams), TEAMMATE mode.

## Problem

All teammate-conductors in a spawn share ONE team task list. The platform broadcasts
`TaskCreated`/`TaskCompleted` to every team session, so a task created by lane L2 is
visible — and claimable — by L4. Without a partition, lanes confuse ownership and root
cannot route a `TaskCompleted` to the correct lane's context.

## Rule

1. **Title prefix.** Every `TaskCreate` from a teammate-conductor MUST prefix its title
   with its lane id: `"{lane_id}: <description>"` (e.g. `"L4: W2-impl-obs-init"`).
2. **Ownership.** Immediately after creating a task, `TaskUpdate(owner: <your-teammate-name>)`.
   (The `TaskCreated`/`TaskCompleted` hook surfaces this as `assignee`. `TaskCreate` has
   no owner argument.)
3. **Claim discipline.** Only claim/work/complete tasks whose title prefix matches YOUR
   `lane_id`. A different prefix belongs to a sibling lane — leave it.
4. **Terminal tasks.** Root-owned terminal tasks (e.g. `shepherd-{sprint_slug}-close`)
   carry NO lane prefix. Root uses that ABSENCE to distinguish them from wave-scope tasks.

## Halt code

`TASK-LANE-MISMATCH` — a teammate created a task without its lane prefix/owner, or claimed
a task outside its lane. Re-title, set owner, release the sibling task.

## See also

- `agents/conductor.md §Hard prohibitions #20`, `§Halt codes`
- `commands/spawn.md §Build the teammate prompt`
- `skills/shepherd/doctrines/spawn-escalation.md §VI`
