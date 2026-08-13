---
kind: sprint-seed
---

# Conformance probe seed

A minimal, non-canonical seed fixture: no priority marker, no explicit
file-scope block, no "Phase 0 mesh" heading, and no GH-anchor marker, so
none of the verify gate's canonical-only WARN checks fire. No open item
markers and no prescriptive per-lane numbering either, so no HARD failure
fires. Well under the footprint cap. Exercises the universal checks
deterministically, landing on a clean 0-hard/0-warn verdict.
