Fixture for `scripts/check-stage-graph.py --self-test`: `rule_terminal_reachability`.

`LOOP-A` and `LOOP-B` cycle between themselves forever with no edge out of
the pair, even though both are reachable from the real root `ROOT` (which
also branches straight to `END`, so overall reachability stays clean). Every
edge/predicate pair inside the loop is correctly backed, so this fixture
isolates terminal-reachability: neither `LOOP-A` nor `LOOP-B` can ever reach
`END`, or any other terminal, once inside the cycle.

## Stage Graph

```yaml
nodes:
  - id: ROOT
    type: single-agent
    in_predicates: []
    out_edges:
      - {to: LOOP-A, label: enter}
      - {to: END, label: unconditional}

  - id: END
    type: terminal
    in_predicates: []
    out_edges: []

  - id: LOOP-A
    type: single-agent
    in_predicates:
      - {from: ROOT, label: enter}
      - {from: LOOP-B, label: to-a}
    out_edges: [{to: LOOP-B, label: to-b}]

  - id: LOOP-B
    type: single-agent
    in_predicates: [{from: LOOP-A, label: to-b}]
    out_edges: [{to: LOOP-A, label: to-a}]
```

## End
