Fixture for `scripts/check-stage-graph.py --self-test`: `rule_dangling_targets`.

ROOT fires an extra branch into `GHOST`, a node id nothing declares. Every
other edge/predicate pair is internally consistent, so this is the only
invariant that fires: the checker must reject the dangling target without
also flagging a stranding edge, an unbacked predicate, an AND-join, an
unreachable node, or a no-terminal node.

## Stage Graph

```yaml
nodes:
  - id: ROOT
    type: single-agent
    in_predicates: []
    out_edges:
      - {to: MID, label: unconditional}
      - {to: GHOST, label: on-dangling}

  - id: MID
    type: single-agent
    in_predicates: [{from: ROOT, label: unconditional}]
    out_edges: [{to: END, label: unconditional}]

  - id: END
    type: terminal
    in_predicates: []
    out_edges: []
```

## End
