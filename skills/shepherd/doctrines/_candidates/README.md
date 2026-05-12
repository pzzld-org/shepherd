# Doctrine Candidates — Promotion Pipeline

This directory holds **candidate doctrines**: rules that emerged as project-specific memory and have proven general enough to become framework-intrinsic.

The typical path:

```
Project discovers a pattern
  → operator saves it as ~/.claude/projects/<proj>/memory/feedback_<topic>.md
  → pattern recurs across 3+ sprints, or across 2+ projects
  → conductor or maintainer files it here as a candidate
  → next framework maintenance session promotes it to doctrines/<rule>.md
  → project memory pointer updated: "promoted to shepherd doctrines/; no longer local"
```

---

## What belongs here

A candidate doctrine:
- Is **language-agnostic** (or can be stated as a principle with language-specific examples)
- Has been observed in **field use** (not theoretical)
- Solves a **recurrent problem** (not a one-off)
- Does NOT duplicate an existing doctrine
- Is **under 200 lines** when fully stated (if longer, it's probably two doctrines)

What does NOT belong here:
- Project-specific rules that only apply to one project (those stay in `[memory].project_doctrines/`)
- Rules already covered by existing doctrines (even if the field observation uses different language)
- Premature generalization of a single observation

---

## Candidate template

Create `_candidates/<slug>.md` with this frontmatter:

```yaml
---
title: <slug>
status: candidate
observed-in: <project/sprint reference>
observed-date: <YYYY-MM-DD>
promoted-to: null  # set to "doctrines/<slug>.md" when promoted
---
```

Then write the doctrine body per `doctrines/README.md §How to add new doctrines`:
1. Principle first, language-agnostic
2. No language syntax in the rule statement
3. Per-language examples in a §Examples section
4. Cross-references to related doctrines

---

## Current candidates

*(empty — file candidates here as they emerge from field use)*

---

## Promotion checklist

When promoting a candidate to `doctrines/`:

- [ ] Move file to `doctrines/<slug>.md`
- [ ] Add `introduced: v{X}.{Y}.{Z}` frontmatter
- [ ] Remove `status: candidate` frontmatter
- [ ] Set `promoted-to` in the candidate's original location (leave the candidate file as a pointer)
- [ ] Add entry to `doctrines/README.md` doctrine index table
- [ ] Update any project memory files that reference the candidate: replace with "promoted to shepherd `doctrines/<slug>.md`"
- [ ] Add cross-references from related doctrines
- [ ] Bump shepherd version (MINOR for new doctrine, PATCH for clarification)
