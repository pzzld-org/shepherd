Fixture for `scripts/check-stage-graph.py --self-test`:
`rule_same_predecessor_and_joins`.

`ROOT` can fire either `branch-a` or `branch-b` toward `MID` -- exactly one,
per `_cmd_mark`'s "a node fires exactly one exit edge" -- but `MID` requires
BOTH `in_predicates` to be satisfied before it promotes. That is a permanent
stall: no single firing of `ROOT` can ever satisfy `all()`. Both predicates
are individually well-backed (each matches a real `out_edge`), so this does
not also trip stranding or unbacked-predicate.

## Stage Graph

```yaml
nodes:
  - id: ROOT
    type: single-agent
    in_predicates: []
    out_edges:
      - {to: MID, label: branch-a}
      - {to: MID, label: branch-b}

  - id: MID
    type: single-agent
    in_predicates:
      - {from: ROOT, label: branch-a}
      - {from: ROOT, label: branch-b}
    out_edges: [{to: END, label: unconditional}]

  - id: END
    type: terminal
    in_predicates: []
    out_edges: []
```

## End
