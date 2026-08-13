Fixture for `scripts/check-stage-graph.py --self-test`: `rule_reachability`.

`A` and `B` form a fully self-consistent two-node island (every edge is
correctly backed by a matching predicate, so stranding/unbacked/AND-join all
stay clean, and `B`'s branch into `END` means both nodes can still reach a
terminal) -- but nothing in the main `ROOT`/`END` component ever points into
the island, so neither `A` nor `B` is a root and neither is ever visited by
a walk that starts at the graph's actual roots. That isolates reachability
as the only invariant this fixture violates.

## Stage Graph

```yaml
nodes:
  - id: ROOT
    type: single-agent
    in_predicates: []
    out_edges: [{to: END, label: unconditional}]

  - id: END
    type: terminal
    in_predicates: []
    out_edges: []

  - id: A
    type: single-agent
    in_predicates: [{from: B, label: loop}]
    out_edges: [{to: B, label: fwd}]

  - id: B
    type: single-agent
    in_predicates: [{from: A, label: fwd}]
    out_edges:
      - {to: A, label: loop}
      - {to: END, label: to-terminal}
```

## End
