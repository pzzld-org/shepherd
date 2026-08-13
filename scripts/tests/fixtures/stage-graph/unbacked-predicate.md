Fixture for `scripts/check-stage-graph.py --self-test`: `rule_unbacked_predicates`.

`MID` declares two `in_predicates`: a real, correctly-backed one from `ROOT`,
plus a phantom `{from: C, label: on-fake}` that `C` never actually fires (`C`
only ever fires `unconditional` toward `END`). Because the phantom predicate
comes from a DIFFERENT predecessor than the real one, this does not also
trip the same-predecessor AND-join rule, and because `ROOT`'s real edge to
`MID` is correctly backed, it does not trip stranding either.

## Stage Graph

```yaml
nodes:
  - id: ROOT
    type: single-agent
    in_predicates: []
    out_edges: [{to: MID, label: unconditional}]

  - id: C
    type: single-agent
    in_predicates: []
    out_edges: [{to: END, label: unconditional}]

  - id: MID
    type: single-agent
    in_predicates:
      - {from: ROOT, label: unconditional}
      - {from: C, label: on-fake}
    out_edges: [{to: END, label: unconditional}]

  - id: END
    type: terminal
    in_predicates: []
    out_edges: []
```

## End
