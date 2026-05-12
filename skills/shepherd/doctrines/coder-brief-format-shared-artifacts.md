---
title: coder brief format for shared-context artifacts
description: |
  When multiple coder lanes write to the same shared-context file
  (`.shepherd/ctx/*.md`, `.shepherd/docs/*.md`), the brief specifies
  either a section line-range or footer-append behavior so cherry-picks
  resolve cleanly without manual conflict resolution.
---

# Doctrine — Shared-Context Artifact Brief Format

> Project-agnostic principle: cherry-picks of shared markdown files
> conflict on shared headers/footers even when the lanes don't logically
> overlap. The fix is up-front discipline in the brief — partition the
> file before dispatch, not after merge.
>
> Field origin: shepherd v5.0.3 conductor feedback (axiom v0.3.0-dev.5),
> §4. Lane 1 + Lane 3 both edited `.shepherd/ctx/feature-flag-matrix.md`
> (different sections, but same file footer note). Each cherry-pick
> needed manual conflict resolution to combine notes. v5.0.4 codifies the
> prevention.

## When this doctrine applies

- Two or more coder lanes in the SAME wave touch the SAME
  `.shepherd/ctx/*.md` (or `.shepherd/docs/*.md`, `.shepherd/reports/*.md`)
  file.
- The brief assigning each lane lists the same shared file in
  `[FILE-SCOPE]`.

## Brief patterns

### Pattern A — Section line-range partition

For files with stable section headers (e.g., `## Lane 1 audit`,
`## Lane 3 audit`), the brief states:

```
[FILE-SCOPE]
.shepherd/ctx/feature-flag-matrix.md  (lines 142..198 only — your "## Lane 1" section)
```

The coder respects the line range. Cherry-picks of two non-overlapping
ranges merge cleanly.

### Pattern B — Footer-append (additive)

For files where the contribution is a single paragraph appended to a
"Notes" section, the brief states:

```
[FILE-SCOPE]
.shepherd/ctx/feature-flag-matrix.md  (footer-append only — single bullet under "## Cross-lane notes")
```

The coder finds the trailing `## Cross-lane notes` section and appends
ONE bullet to its end. Multiple lanes appending bullets create no
conflict (each bullet is a new line at end-of-section).

### Pattern C — Single-author per file

For files where two lanes would genuinely conflict (overlap in
content, not just file), the brief assigns the file to ONE lane and
gives the other lane a `[CONTEXT-INVENTORY]` reference instead. The
non-author reads but does not write.

## Brief author responsibilities

The conductor authoring the briefs:

1. **Detects** shared `[FILE-SCOPE]` entries across waves before dispatch.
2. **Selects** Pattern A, B, or C for each shared file.
3. **States** the choice explicitly in the brief — not as a comment, but
   as part of `[FILE-SCOPE]` or a dedicated `[SHARED-FILE-RULE]` block:

   ```
   [SHARED-FILE-RULE]
   .shepherd/ctx/feature-flag-matrix.md
     pattern: footer-append
     section: "## Cross-lane notes"
     instruction: append exactly one bullet; do not touch lines above this section.
   ```

4. **Pre-runs** the conflict prediction: a `git diff` of two
   hypothetical worktree commits on the chosen pattern should resolve
   without conflict markers.

## Coder responsibilities

The coder:

1. **Reads** `[SHARED-FILE-RULE]` before any write.
2. **Refuses** to violate the pattern. If the coder believes its
   contribution doesn't fit the assigned pattern, halts with
   `BRIEF-AMENDMENT REQUEST: shared-file-rule does not fit deliverable`.
3. **Confines** writes to the section/footer specified.

## Alternative: shepherd-side helper (future)

A v5.x `shctx ctx-merge <file> <wt-1> <wt-2>` helper could automate
additive merges for `.shepherd/ctx/*.md` (treats the file as
section-partitioned by markdown headers; merges non-overlapping
sections). Not in v5.0.4. Until then: brief-side discipline.

## See also

- `worktree-confinement.md` — companion: ALL writes go to the worktree.
- `pattern-b-overlap.md` — Pattern B never crosses the same file
  unless this doctrine applies.
