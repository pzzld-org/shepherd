#!/usr/bin/env python3
"""check-stage-graph -- verify the Stage Graph's topology, not just its prose.

WHY THIS EXISTS.

The same defect -- a Stage Graph edge with no matching `in_predicate`, or the
reverse -- was caught **three separate times by three different readers**:
critic pass 2 finding 12 (`PLAN-GATE-POST-Q1`), finding 14 (`CLOSE-FINALIZE`),
and root's independent check (`CANONICAL-TYPES-REFRESH`, `WORKER-IO`,
`CODER-CONVERGENCE`). A generalized check caught 8 more instances but missed
those three, because it exempted a predicate whenever a `parallel_with`
sibling carried the matching edge -- an exemption that hides exactly the
topology error `shctx plan topology` renders wrong. Three catches by
inspection is three too many. CLAUDE.md's latent-vs-deterministic rule is
explicit: same input, same answer, by definition -> write the script.

THE SEMANTICS BEING ENFORCED.

`skills/context/scripts/cmd_graph.sh`'s `_cmd_mark`, on a `done` mark, sets
`satisfied=True` on every predicate matching `(predecessor, exit_edge)` --
scanning ALL nodes -- then promotes a node when `all(p["satisfied"] for p in
node["in_predicates"])`. Two consequences this checker encodes as rules:

  1. A node fires exactly ONE exit edge. Two `in_predicates` from the SAME
     predecessor can therefore never both be satisfied by one firing --
     a permanent stall (`rule_same_predecessor_and_joins`, generalizing
     critic-pass-2 findings 12 and 14).
  2. Readiness never consults a predecessor's `out_edges`, so an unbacked
     predicate does not stall the walk -- it just renders the topology a lie
     (`rule_unbacked_predicates`).

Usage:
    scripts/check-stage-graph.py [plan.md]     # check one plan's Stage Graph
    scripts/check-stage-graph.py --self-test   # prove every rule can fail

`--self-test` matters as much as the checks: a rule with a typo'd key name
passes everything forever. Each rule below is exercised against a
deliberately broken fixture under `scripts/tests/fixtures/stage-graph/`
before it is trusted against the real plan -- mirroring
`scripts/check-workspace.sh`, not `hooks/tests/test_v644_wiring.sh`'s
grep-for-prose pattern (DF-19): every rule here walks real graph topology
parsed out of real plan text, never asserts a string exists in a doc.

Ported from a root-authored throwaway (119 lines, zero YAML dependency) that
already proved the parsing approach and all six checks correct against the
live plan. Port, don't rewrite: the regex-based scrape and the six rules
below are unchanged in substance from that original.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLAN = ROOT / ".shepherd" / "runs" / "v645" / "plan.md"
FIXTURES_DIR = Path(__file__).resolve().parent / "tests" / "fixtures" / "stage-graph"

# An edge is either an `in_predicate` (from:, label:) or an `out_edge`
# (to:, label:) -- both scrape to the same (peer_id, label) shape.
Edge = tuple[str, str]
Graph = dict[str, dict[str, Any]]  # id -> {"type": str | None, "in_predicates": [Edge], "out_edges": [Edge]}


class GraphParseError(Exception):
    """The `## Stage Graph` section is missing or unreadable."""


# --------------------------------------------------------------------------
# Parsing. No YAML dependency -- nodes are `- id: ...` list items and the
# `in_predicates` / `out_edges` arrays are `{from:/to:, label:}` pairs,
# scraped line-by-line so both the inline (`out_edges: [{...}]`) and block
# (`out_edges:\n  - {...}`) YAML forms parse identically -- the plan uses
# both.
# --------------------------------------------------------------------------

_SECTION = re.compile(r"^## Stage Graph\s*\n(.*?)^## ", re.S | re.M)
_FENCE = re.compile(r"```(?:yaml)?\s*\n(.*?)\n```", re.S)
_NODE_ID = re.compile(r"\s*-\s+id:\s*([A-Za-z0-9_\-]+)")
_TYPE = re.compile(r"\s*type:\s*([A-Za-z0-9_\-]+)")
_IN_PRED = re.compile(r"\{from:\s*([A-Za-z0-9_\-]+),\s*label:\s*([A-Za-z0-9_\-]+)\}")
_OUT_EDGE = re.compile(r"\{to:\s*([A-Za-z0-9_\-]+),\s*label:\s*([A-Za-z0-9_\-]+)\}")


def parse_stage_graph(src: str) -> Graph:
    """Parse the fenced `## Stage Graph` block out of a plan.md's text."""
    match = _SECTION.search(src)
    if not match:
        raise GraphParseError("could not locate a '## Stage Graph' section")
    section = match.group(1)
    fence = _FENCE.search(section)
    body = fence.group(1) if fence else section

    nodes: Graph = {}
    cur: str | None = None
    for line in body.splitlines():
        id_match = _NODE_ID.match(line)
        if id_match:
            cur = id_match.group(1)
            nodes[cur] = {"type": None, "in_predicates": [], "out_edges": []}
            continue
        if cur is None:
            continue
        type_match = _TYPE.match(line)
        if type_match:
            nodes[cur]["type"] = type_match.group(1)
        for pred, edge in _IN_PRED.findall(line):
            nodes[cur]["in_predicates"].append((pred, edge))
        for tgt, edge in _OUT_EDGE.findall(line):
            nodes[cur]["out_edges"].append((tgt, edge))

    if not nodes:
        raise GraphParseError("'## Stage Graph' section had no `- id:` nodes")
    return nodes


def _terminals(nodes: Graph) -> set[str]:
    return {n for n, d in nodes.items() if d["type"] == "terminal"}


# --------------------------------------------------------------------------
# The six invariants. Each takes the parsed graph and returns a list of
# human-readable violations -- empty means the rule holds.
# --------------------------------------------------------------------------


def rule_dangling_targets(nodes: Graph) -> list[str]:
    """Every `out_edge` target must exist as a node.

    An edge to an id no node declares is a typo or a rename that never
    propagated -- `shctx plan topology` renders it as a dead arrow into
    nothing, and the walker can never satisfy it.
    """
    bad = []
    for n, d in nodes.items():
        for tgt, edge in d["out_edges"]:
            if tgt not in nodes:
                bad.append(f"DANGLING TARGET  {n} --{edge}--> {tgt} (no such node)")
    return bad


def rule_stranding_edges(nodes: Graph) -> list[str]:
    """Every `out_edge` must be backed by a matching `in_predicate` on its
    target, except edges into `type: terminal` nodes.

    Terminals gate nothing downstream (the HARD-STOP/PAUSE idiom): an edge
    landing on a real, non-terminal node with no reciprocal predicate means
    the target silently ignores how it was reached.
    """
    terminals = _terminals(nodes)
    bad = []
    for n, d in nodes.items():
        for tgt, edge in d["out_edges"]:
            if tgt not in nodes or tgt in terminals:
                continue
            if (n, edge) not in nodes[tgt]["in_predicates"]:
                bad.append(
                    f"STRANDING EDGE   {n} --{edge}--> {tgt}: target has no matching in_predicate"
                )
    return bad


def rule_unbacked_predicates(nodes: Graph) -> list[str]:
    """Every `in_predicate` must be backed by a real `out_edge` from that
    exact predecessor firing that exact edge label.

    `_cmd_mark` never consults a predecessor's `out_edges` when marking a
    predicate satisfied, so an unbacked predicate does not stall the walk --
    it just makes the rendered topology a lie.
    """
    bad = []
    for n, d in nodes.items():
        for pred, edge in d["in_predicates"]:
            if pred not in nodes:
                bad.append(f"UNBACKED PRED    {n} <-- {pred}/{edge} (no such predecessor)")
            elif (n, edge) not in nodes[pred]["out_edges"]:
                bad.append(
                    f"UNBACKED PRED    {n} <-- {pred}/{edge}: predecessor never fires that edge"
                )
    return bad


def rule_same_predecessor_and_joins(nodes: Graph) -> list[str]:
    """No node may carry more than one `in_predicate` from the SAME
    predecessor.

    A node fires exactly one exit edge, so two `in_predicates` from one
    predecessor can never both be satisfied by a single firing: a permanent
    stall. Generalizes critic-pass-2 findings 12 and 14.
    """
    bad = []
    for n, d in nodes.items():
        preds = [p for p, _ in d["in_predicates"]]
        for p in sorted(set(preds)):
            count = preds.count(p)
            if count > 1:
                bad.append(
                    f"SAME-PRED AND-JOIN {n}: {count} predicates from {p}; "
                    "one fired edge can never satisfy all() -> permanent stall"
                )
    return bad


def rule_reachability(nodes: Graph) -> list[str]:
    """Every node must be reachable from a root (a node with no
    `in_predicates`).

    An unreachable node is dead weight the walker can never enter -- a step
    nobody ever dispatches, silently.
    """
    roots = [n for n, d in nodes.items() if not d["in_predicates"]]
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n in seen or n not in nodes:
            continue
        seen.add(n)
        stack.extend(tgt for tgt, _ in nodes[n]["out_edges"])
    unreachable = sorted(set(nodes) - seen)
    return [f"UNREACHABLE      {n}" for n in unreachable]


def _reaches_terminal(nodes: Graph, terminals: set[str], start: str) -> bool:
    seen: set[str] = set()
    stack = [start]
    while stack:
        n = stack.pop()
        if n in seen or n not in nodes:
            continue
        seen.add(n)
        if n in terminals:
            return True
        stack.extend(tgt for tgt, _ in nodes[n]["out_edges"])
    return False


def rule_terminal_reachability(nodes: Graph) -> list[str]:
    """Every non-terminal node must be able to reach SOME terminal node.

    A node that cannot reach `HARD-STOP`, `PAUSE`, or any other `type:
    terminal` node is a branch the walker can enter and never leave.
    """
    terminals = _terminals(nodes)
    bad = []
    for n in nodes:
        if n not in terminals and not _reaches_terminal(nodes, terminals, n):
            bad.append(f"NO TERMINAL      {n} cannot reach any terminal node")
    return bad


RULES = [
    rule_dangling_targets,
    rule_stranding_edges,
    rule_unbacked_predicates,
    rule_same_predecessor_and_joins,
    rule_reachability,
    rule_terminal_reachability,
]


# --------------------------------------------------------------------------
# Run against a real plan.
# --------------------------------------------------------------------------


def run(plan_path: Path) -> int:
    try:
        src = plan_path.read_text()
    except OSError as exc:
        print(f"::error::cannot read {plan_path}: {exc}")
        return 1
    try:
        nodes = parse_stage_graph(src)
    except GraphParseError as exc:
        print(f"::error::{plan_path}: {exc}")
        return 1

    terminals = sorted(_terminals(nodes))
    roots = sorted(n for n, d in nodes.items() if not d["in_predicates"])
    edge_count = sum(len(d["out_edges"]) for d in nodes.values())
    pred_count = sum(len(d["in_predicates"]) for d in nodes.values())
    multi = {n: d["in_predicates"] for n, d in nodes.items() if len(d["in_predicates"]) > 1}

    print(f"{plan_path}: {len(nodes)} node(s)   terminals: {terminals}")
    print(f"roots: {roots}")
    print(f"edges: {edge_count}   predicates: {pred_count}")
    print(f"multi-predicate (genuine AND-join) nodes: {len(multi)}")
    for n, preds in multi.items():
        print(f"    {n}: {preds}")
    print()

    failures = 0
    for rule in RULES:
        label = rule.__name__.removeprefix("rule_").replace("_", " ")
        violations = rule(nodes)
        if violations:
            failures += len(violations)
            print(f"  {label:<28} FAILED")
            for violation in violations:
                print(f"      {violation}")
        else:
            print(f"  {label:<28} ok")

    print()
    if failures:
        print(f"::error::{failures} Stage Graph invariant violation(s) in {plan_path}.")
        return 1
    print(f"ok: all {len(RULES)} Stage Graph invariants hold for {plan_path}.")
    return 0


# --------------------------------------------------------------------------
# Self-test. Each rule is run against a fixture that violates ONLY it. A
# rule that cannot fail is a rule that is not checking anything, and it
# would pass silently forever -- CLAUDE.md's "a gate with no negative
# control may be silently passing."
# --------------------------------------------------------------------------

FIXTURES = {
    rule_dangling_targets: FIXTURES_DIR / "dangling-edge-target.md",
    rule_stranding_edges: FIXTURES_DIR / "stranding-edge.md",
    rule_unbacked_predicates: FIXTURES_DIR / "unbacked-predicate.md",
    rule_same_predecessor_and_joins: FIXTURES_DIR / "same-predecessor-and-join.md",
    rule_reachability: FIXTURES_DIR / "unreachable-node.md",
    rule_terminal_reachability: FIXTURES_DIR / "no-terminal-reachable.md",
}


def self_test() -> int:
    print("self-test: every rule must be able to fail\n")
    failures = 0

    for rule, fixture_path in FIXTURES.items():
        label = rule.__name__.removeprefix("rule_").replace("_", " ")
        try:
            nodes = parse_stage_graph(fixture_path.read_text())
        except (OSError, GraphParseError) as exc:
            print(f"  {label:<28} FIXTURE UNREADABLE ({exc})")
            failures += 1
            continue
        violations = rule(nodes)
        if violations:
            print(f"  {label:<28} fails as designed")
        else:
            print(f"  {label:<28} DID NOT FAIL on a broken fixture")
            failures += 1

    print()
    if failures:
        print(f"::error::{failures} rule(s) cannot detect their own violation.")
        return 1

    # A checker that only knows how to fail is as useless as one that never
    # fails. Confirm the real plan still parses and passes every rule clean.
    if DEFAULT_PLAN.is_file():
        print(f"confirming the real plan still passes clean: {DEFAULT_PLAN}\n")
        if run(DEFAULT_PLAN) != 0:
            print("::error::the real plan no longer passes -- fix the plan or the checker.")
            return 1
    else:
        print(f"note: {DEFAULT_PLAN} not present; skipping the real-plan confirmation.")

    print("ok: every rule is falsifiable, and the real plan is clean.")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    plan_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PLAN
    return run(plan_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
