<!-- Mirrored as the bundled Jinja template services/cli/shepherd_cli/templates/handoff.md.j2 (rendered via `shepherd render handoff.md.j2`); project overrides live in .shepherd/templates/. -->
# Sprint handoff — {{BRANCH}}

| Field | Value |
|---|---|
| Branch | `{{BRANCH}}` |
| Date | {{DATE}} |
| Session | {{SESSION}} |

## North star

> {{NORTH_STAR}}

## What landed

Last commits on `{{BRANCH}}`:

```
{{COMMITS}}
```

## Sprint metrics

| Metric | Value |
|---|---|
| Artifacts (created/modified) | {{ARTIFACTS_COUNT}} |
| Memory entries written | {{MEM_COUNT}} |
| Lock acquisitions | {{LOCK_COUNT}} |
| Open issues (registry view) | {{OPEN_ISSUES_COUNT}} |
| Drift-risk items (registry view) | {{DRIFT_RISK_COUNT}} |

## Carry-forwards

{{CARRY_FORWARDS}}

## Recommended next sprint focus

{{NEXT_FOCUS}}

## Files of interest

{{FILES_OF_INTEREST}}
