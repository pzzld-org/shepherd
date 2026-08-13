Fixture for `scripts/check-stage-graph.py --self-test`: `rule_stranding_edges`.

`ROOT` fires a real edge into the real, non-terminal node `MID2`, but `MID2`
never declares the matching `in_predicate` -- it declares no predicates at
all, which also makes it a root, so it stays reachable and can still reach a
terminal on its own. That keeps every other invariant clean and isolates the
one this fixture exists to exercise.

## Stage Graph

```yaml
nodes:
  - id: ROOT
    type: single-agent
    in_predicates: []
    out_edges:
      - {to: MID, label: unconditional}
      - {to: MID2, label: on-branch}

  - id: MID
    type: single-agent
    in_predicates: [{from: ROOT, label: unconditional}]
    out_edges: [{to: END, label: unconditional}]

  - id: MID2
    type: single-agent
    in_predicates: []
    out_edges: [{to: END, label: unconditional}]

  - id: END
    type: terminal
    in_predicates: []
    out_edges: []
```

## End
