"""``shepherd graph`` — Stage Graph rule-engine walker + compiler (bash: ``cmd_graph.sh``).

Native port of ``skills/context/scripts/cmd_graph.sh`` (950 LOC), the
conductor's deterministic dispatch driver over the ``state.json`` that
``shepherd plan extract`` materializes (see :mod:`shepherd_cli.commands.
plan` and the shared contract module :mod:`shepherd_cli.commands.
models_graph`). Subcommands: ``status`` / ``next`` / ``mark`` / ``trace``
/ ``reset`` / ``compile`` / ``diagram``.

**NO DATABASE.** ``cmd_graph.sh`` touches no ``shctx_sql``/
``shctx_db_path`` call — the whole surface is the state.json +
trace.jsonl pair (plus config reads for ``compile``'s ``[models]`` role
pins and ``git rev-parse`` nowhere at all: sprint comes from state.json).

SINGLE VARIADIC CALLBACK, NOT REAL ``@app.command()``s
=======================================================
Same shape (and same reasons) as :mod:`shepherd_cli.commands.plan`: bare
``shctx graph``/``-h``/``--help`` prints ``usage()`` on stdout, exit 0;
unknown subcommand prints ``ERROR: unknown subcommand: <sub>`` + usage on
STDERR, exit 1; per-subcommand flag loops are equals-form-only with
per-arm unknown-arg behavior (``mark``/``compile``/``diagram`` error exit
1; ``status``/``next``/``trace``/``reset`` silently ignore unknowns —
their bash ``case`` loops have no default arm).

GH #225 REGRESSION, STRUCTURALLY CLOSED
========================================
``graph next`` (and ``compile``/``diagram``/``plan topology``) used to
AttributeError when a node's ``agents`` entry was a bare role-name
string (or a mapping with no ``role`` key) instead of the normalized
dict. The fix is two-layered and both layers are preserved here:
``plan extract`` normalizes at the single write site, AND every reader
carries the defense-in-depth ``isinstance`` guard so a hand-edited /
pre-fix state.json degrades gracefully instead of crashing.

COMPILE CONTRACT (v6.0.1 GH #77, #178/#180 model pins)
=======================================================
``compile`` re-projects the SAME state.json (never re-parses plan.md)
into a Dynamic Workflow ``<label>.workflow.js`` + ``<label>.manifest.
json``. Emission is a PURE function of state.json + the resolved
``[models]`` role map: the script body contains NO timestamps and no
nondeterministic constructs — ``compiled_at`` lives ONLY in the
manifest, so recompiling an unchanged graph reproduces byte-identical
script bytes and the §IV faithfulness diff (soundness / completeness /
determinism / model_pin) stays meaningful. Every spawn is emitted as
``() => agent(briefs[key], { agentType: "shepherd:<role>", model: "...",
label: "..." })`` — an explicit agentType + model pin per spawn, never a
bare ``agent(prompt)``.

DOCUMENTED DEVIATIONS (additive / cosmetic only)
=================================================
1. ``--run=<name>`` on every subcommand — the run-scoped artifact shim
   (:mod:`shepherd_cli.commands.models_graph` docstring): the graph dir
   resolves to ``<workdir>/runs/<run>/graph/`` when a run is
   identifiable (``--run`` flag, ``SHEPHERD_RUN`` env,
   ``<workdir>/runs/current`` marker) AND its state.json exists, else
   ALWAYS falls back to the legacy ``<workdir>/graph/``. Derived
   artifacts (``compiled/``, ``diagrams/``, trace) follow the resolved
   dir. With no identifiable run, behavior is byte-for-byte bash.
2. The compiled script now carries the Dynamic Workflow meta contract:
   ``export const meta = { name, description, phases }`` as a PURE
   LITERAL derived deterministically from state.json (segment label,
   sprint, batch order) — no timestamp, so script-byte determinism and
   the sha256 faithfulness diff are preserved. The bash emitter predates
   the meta contract; this is the one intentional script-shape change.
3. ``graph mark --agent=<id>`` dedupes ``agent_ids`` preserving insertion
   order, where bash's ``list(set(...))`` produced unspecified order —
   a strict determinism upgrade, same membership.
4. ``graph trace --tail=<garbage>`` prints a clean ``ERROR: --tail must
   be an integer`` (exit 1) instead of bash's raw ``tail``/``int()``
   error text; a valid ``--tail=N`` is byte-for-byte.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

import typer

from shepherd_cli.commands.models_graph import (
    append_trace,
    cfg_section_get,
    load_state,
    resolve_graph_dir,
    resolve_run,
    state_path,
    trace_path,
)

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": []},
    help="Stage Graph rule-engine walker + workflow compiler (bash: cmd_graph.sh).",
)

#: Verbatim ``usage()`` heredoc from ``cmd_graph.sh``.
_USAGE = """shctx graph <status|next|mark|trace|reset> [args]

  status [--json|--md]
      Nodes by state, ready batches, completion %.

  next [--json]
      Next-eligible dispatch batch (parallel_with cliques honored).
      Conductor: read this, dispatch one Agent batch, then `mark`.

  mark <node-id> --state=<in_flight|done|skipped> [--exit=<edge>] [--agent=<id>]
      Advance state. --state=done + --exit=<edge-label> fires the named
      outgoing edge and updates downstream nodes.

  trace [--tail=N] [--json]
      Read the append-only event log.

  reset [--force]
      Drop state and trace; re-extract to rebuild.

  compile [--segment=<node-id>] [--out=<dir>] [--verify] [--list]
          [--max-concurrent=16] [--json]
      (v6.0.1, GH #77) Emit a gate-free agent-fanout segment of the Stage
      Graph as a Claude Code Dynamic Workflow script — the PRIMARY execution
      path for fanout segments. Default segment contains CLOSE-SWARM. --verify
      runs the §IV faithfulness diff (soundness / completeness / determinism);
      --list enumerates compilable segments. Seam nodes (operator gates,
      git/shell, conductor-inline) never enter the script — they run at the
      conductor (doctrine workflow-compile-down.md §III / §V / §VI).

  diagram [--segment=<node-id>] [--out=<file>] [--stdout]
      (v6.0.2, GH #77 topology utility) Emit a Mermaid execution diagram of the
      Stage Graph — nodes + edges + seam/fanout classification (seams are the
      conductor-inline gates that never compile). With --segment, overlay that
      compilable fan-out segment as a subgraph. Default writes
      {workdir}/graph/diagrams/{sprint}.mmd; --stdout prints to stdout.

See skills/shepherd/references/flock.md §Dispatch and skills/harness/references/workflow-templates.md."""

#: Seam node types (doctrine §V φ map) — operator gates + conductor-inline
#: FS/git; never compiled. Shared by ``compile`` and ``diagram`` so the
#: diagram's seam/fanout split matches exactly what compiles.
_SEAM_EXACT = frozenset(
    {
        "SEED-VERIFY",
        "CHAIN-REPAIR",
        "PLAN-GATE",
        "DEDUP-GATE",
        "LANE-CLOSE",
        "CANONICAL-TYPES-REFRESH",
        "CLOSE-FINALIZE",
        "RELEASE",
        "RESUME-LANE",
        "HARD-STOP",
        "MESH",
        "GATES-DISCOVERY",
    }
)

#: Roles whose spawns are tagged read-only in compiled scripts (§VII, #74).
_READONLY_ROLES = frozenset({"auditor", "discovery", "critic"})

#: doctrine §III: hard cap on total agents per compiled run.
_HARD_TOTAL_CAP = 1000

#: Roles the bash wrapper resolves [models] pins for before compiling.
_COMPILE_PIN_ROLES = ("coder", "auditor", "worker", "discovery", "critic", "engineer", "conductor")


def _ntype(n: dict) -> str:
    """Uppercased node type, ``UNKNOWN`` when unset (bash ``ntype``)."""
    return (n.get("type") or "UNKNOWN").upper()


def _is_compilable(n: dict) -> bool:
    """True iff the node is an agent-fanout (compilable) node (doctrine §V).

    Seam = gate / inline / operator-approval (doctrine §III/§V) — never
    compiled. Transliterated from ``cmd_graph.sh``'s ``is_compilable`` /
    ``is_fanout`` (the two bash copies are kept in sync by hand; here
    there is exactly one).

    Args:
        n: A state.json node dict.

    Returns:
        Whether the node enters compiled segments.
    """
    t = _ntype(n)
    if not n.get("agents"):
        return False  # conductor-inline → seam
    if t in _SEAM_EXACT:
        return False
    if t.startswith("PAUSE"):
        return False  # pause → segment boundary
    if t.endswith("-GATE"):
        return False  # WAVE-1-GATE etc. → seam
    if t in ("CLOSE-SWARM", "INTRO-COMBO-WAVE", "DISCOVERY-COMBO-WAVE", "DISCOVERY"):
        return True
    if "IMPL" in t or "AUDIT" in t:
        return True
    if t.startswith("HOTFIX") or t.startswith("WORKER"):
        return True
    return False


def _resolved_paths(rest: list[str]) -> tuple[str, str, str]:
    """Resolve (graph_dir, state_path, trace_path) honoring the run shim.

    Args:
        rest: The subcommand's raw args (scanned for ``--run=`` only; the
            caller does its own full flag parsing).

    Returns:
        The resolved graph dir plus its state/trace paths.
    """
    run_flag: str | None = None
    for arg in rest:
        if arg.startswith("--run="):
            run_flag = arg[len("--run=") :]
    graph_dir = resolve_graph_dir(resolve_run(run_flag))
    return graph_dir, state_path(graph_dir), trace_path(graph_dir)


def _require_state(spath: str) -> bool:
    """Print the bash ``_require_state`` error when state.json is absent.

    Args:
        spath: The resolved state.json path.

    Returns:
        True when the state file exists (caller proceeds).
    """
    if os.path.isfile(spath):
        return True
    typer.echo(f"ERROR: no graph state at {spath}. Run 'shctx plan extract <plan.md>' first.", err=True)
    return False


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
def _cmd_status(rest: list[str]) -> int:
    """``graph status [--json|--md]`` (unknown args ignored — bash parity).

    Args:
        rest: Every token after ``status``.

    Returns:
        The process exit code.
    """
    _gdir, spath, _tpath = _resolved_paths(rest)
    if not _require_state(spath):
        return 1
    fmt = "text"
    for arg in rest:
        if arg == "--json":
            fmt = "json"
        elif arg == "--md":
            fmt = "md"

    state = load_state(spath)
    nodes = state["nodes"]
    by_state = collections.Counter(n["state"] for n in nodes.values())
    total = len(nodes)
    done = by_state.get("done", 0)
    pct = (done * 100) // total if total else 0
    ready = [nid for nid, n in nodes.items() if n["state"] == "ready"]
    in_flight = [nid for nid, n in nodes.items() if n["state"] == "in_flight"]

    if fmt == "json":
        typer.echo(
            json.dumps(
                {
                    "sprint": state["sprint"],
                    "total": total,
                    "by_state": dict(by_state),
                    "completion_pct": pct,
                    "ready": ready,
                    "in_flight": in_flight,
                },
                indent=2,
            )
        )
    elif fmt == "md":
        lines = [f"## Graph status — {state['sprint']}", f"_completion: {done}/{total} ({pct}%)_", ""]
        for st in ("ready", "in_flight", "pending", "done", "skipped"):
            c = by_state.get(st, 0)
            if c:
                lines.append(f"- **{st}**: {c}")
        if ready:
            lines.append(f"\n**Ready now:** {', '.join('`' + n + '`' for n in ready)}")
        if in_flight:
            lines.append(f"\n**In flight:** {', '.join('`' + n + '`' for n in in_flight)}")
        typer.echo("\n".join(lines))
    else:
        lines = [f"Graph status — sprint: {state['sprint']}", f"  completion: {done}/{total} ({pct}%)"]
        for st in ("ready", "in_flight", "pending", "done", "skipped"):
            c = by_state.get(st, 0)
            if c:
                lines.append(f"  {st:<10}: {c}")
        if ready:
            lines.append(f"\n  Ready now:  {', '.join(ready)}")
        if in_flight:
            lines.append(f"  In flight:  {', '.join(in_flight)}")
        typer.echo("\n".join(lines))
    return 0


# --------------------------------------------------------------------------
# next — return next-eligible batch (parallel_with cliques honored)
# --------------------------------------------------------------------------
def _cmd_next(rest: list[str]) -> int:
    """``graph next [--json]`` — the #225 crash site, ported with its guard.

    Args:
        rest: Every token after ``next``.

    Returns:
        The process exit code (always 0 when state exists — bash parity).
    """
    _gdir, spath, _tpath = _resolved_paths(rest)
    if not _require_state(spath):
        return 1
    fmt = "text"
    for arg in rest:
        if arg == "--json":
            fmt = "json"

    state = load_state(spath)
    nodes = state["nodes"]
    ready = [n for n in nodes.values() if n["state"] == "ready"]

    if not ready:
        if fmt == "json":
            typer.echo(json.dumps({"batch": [], "reason": "no ready nodes"}))
        else:
            in_flight = [n["id"] for n in nodes.values() if n["state"] == "in_flight"]
            if in_flight:
                typer.echo(f"No ready nodes. In flight: {', '.join(in_flight)} — `mark` them to advance.")
            else:
                pending = [n["id"] for n in nodes.values() if n["state"] == "pending"]
                if pending:
                    typer.echo(f"No ready nodes; {len(pending)} pending with unmet in_predicates.")
                else:
                    typer.echo("Graph complete — no nodes remain.")
        return 0

    def clique_of(start_id: str) -> list[str]:
        seen = {start_id}
        stack = [start_id]
        while stack:
            cur = stack.pop()
            for peer in nodes[cur].get("parallel_with") or []:
                if peer in seen or peer not in nodes:
                    continue
                if nodes[peer]["state"] != "ready":
                    continue
                seen.add(peer)
                stack.append(peer)
        return sorted(seen)

    seed = ready[0]
    batch_ids = clique_of(seed["id"])
    batch = [nodes[i] for i in batch_ids]

    out = []
    for n in batch:
        out.append(
            {
                "id": n["id"],
                "type": n["type"],
                "agents": n.get("agents") or [],  # may be empty (conductor-inline)
                "parallel_with": [i for i in batch_ids if i != n["id"]],
            }
        )

    if fmt == "json":
        typer.echo(json.dumps({"batch": out, "count": len(out)}, indent=2))
    else:
        lines = [f"Next batch ({len(out)} node(s) — fire in ONE Agent message):"]
        for n in out:
            agents = n["agents"]
            if agents:
                for a in agents:
                    # Defense-in-depth: `agents` is normalized to dicts by
                    # `plan extract`, but guard here too in case state.json
                    # was hand-edited or pre-dates the fix (GH #225).
                    role = a.get("role") if isinstance(a, dict) else a
                    count = a.get("count", 1) if isinstance(a, dict) else 1
                    lines.append(f"  • {n['id']:<24} ({n['type']}) — @{role} ×{count}")
            else:
                lines.append(f"  • {n['id']:<24} ({n['type']}) — conductor-inline")
        lines.append("")
        lines.append("After dispatch+return:  shctx graph mark <id> --state=done --exit=<edge-label>")
        typer.echo("\n".join(lines))
    return 0


# --------------------------------------------------------------------------
# mark <node-id> --state=... [--exit=...] [--agent=...]
# --------------------------------------------------------------------------
def _cmd_mark(rest: list[str]) -> int:
    """``graph mark <node-id> --state=... [--exit=...] [--agent=...]``.

    Args:
        rest: Every token after ``mark``.

    Returns:
        The process exit code.
    """
    nid = rest[0] if rest else ""
    if not nid:
        typer.echo("ERROR: usage: shctx graph mark <node-id> --state=...", err=True)
        return 1

    target = ""
    exit_edge = ""
    agent = ""
    for arg in rest[1:]:
        if arg.startswith("--state="):
            target = arg[len("--state=") :]
        elif arg.startswith("--exit="):
            exit_edge = arg[len("--exit=") :]
        elif arg.startswith("--agent="):
            agent = arg[len("--agent=") :]
        elif arg.startswith("--run="):
            pass  # consumed by _resolved_paths (additive shim flag)
        elif arg in ("-h", "--help"):
            typer.echo(_USAGE)
            return 0
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            return 1
    if target not in ("in_flight", "done", "skipped"):
        typer.echo("ERROR: --state must be in_flight|done|skipped", err=True)
        return 1

    _gdir, spath, tpath = _resolved_paths(rest)
    if not _require_state(spath):
        return 1

    state = load_state(spath)
    nodes = state["nodes"]
    if nid not in nodes:
        typer.echo(f"ERROR: node {nid} not in graph", err=True)
        return 1
    n = nodes[nid]
    now = int(time.time())

    prev = n["state"]
    n["state"] = target
    if target == "in_flight":
        n["started_at"] = now
        if agent:
            # Deviation 3 (module docstring): insertion-order dedupe where
            # bash used list(set(...)) — same membership, stable bytes.
            ids = list(n.get("agent_ids") or [])
            if agent not in ids:
                ids.append(agent)
            n["agent_ids"] = ids
    elif target in ("done", "skipped"):
        n["exited_at"] = now
        if exit_edge:
            n["exit_edge"] = exit_edge
        if target == "done" and exit_edge:
            for downstream in nodes.values():
                for p in downstream["in_predicates"]:
                    if p["predecessor"] == nid and p["edge"] == exit_edge:
                        p["satisfied"] = True
            for d in nodes.values():
                if d["state"] != "pending":
                    continue
                if all(p["satisfied"] for p in d["in_predicates"]):
                    d["state"] = "ready"

    with open(spath, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)

    ev: dict[str, object] = {"at": now, "event": "node_mark", "node": nid, "from": prev, "to": target}
    if exit_edge:
        ev["exit_edge"] = exit_edge
    if agent:
        ev["agent_id"] = agent
    append_trace(tpath, ev)

    newly_ready = [d["id"] for d in nodes.values() if d["state"] == "ready"]
    typer.echo(f"marked: {nid}  {prev} → {target}" + (f"  exit={exit_edge}" if exit_edge else ""))
    if newly_ready:
        typer.echo(f"newly ready: {', '.join(newly_ready)}")
    return 0


# --------------------------------------------------------------------------
# trace
# --------------------------------------------------------------------------
def _cmd_trace(rest: list[str]) -> int:
    """``graph trace [--tail=N] [--json]`` (unknown args ignored).

    Args:
        rest: Every token after ``trace``.

    Returns:
        The process exit code (0 even when no trace exists — bash parity).
    """
    tail_arg = ""
    fmt = "text"
    for arg in rest:
        if arg.startswith("--tail="):
            tail_arg = arg[len("--tail=") :]
        elif arg == "--json":
            fmt = "json"
    _gdir, _spath, tpath = _resolved_paths(rest)
    if not os.path.isfile(tpath):
        typer.echo(f"(no trace yet at {tpath})")
        return 0

    tail_n = 0
    if tail_arg:
        try:
            tail_n = int(tail_arg)
        except ValueError:
            typer.echo("ERROR: --tail must be an integer", err=True)
            return 1

    with open(tpath, encoding="utf-8") as fh:
        raw = fh.read()

    if fmt == "json":
        raw_lines = raw.splitlines(keepends=True)
        if tail_n:
            raw_lines = raw_lines[-tail_n:]
        sys.stdout.write("".join(raw_lines))
        return 0

    lines = raw.splitlines()
    if tail_n > 0:
        lines = lines[-tail_n:]
    out_lines = []
    for line in lines:
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001 - bash catches bare Exception too
            out_lines.append(f"(unparseable) {line}")
            continue
        ts = datetime.fromtimestamp(ev.get("at", 0)).isoformat(timespec="seconds")
        evt = ev.pop("event", "?")
        ev.pop("at", None)
        rest_s = " ".join(f"{k}={v}" for k, v in ev.items())
        out_lines.append(f"{ts}  {evt:<16} {rest_s}")
    typer.echo("\n".join(out_lines))
    return 0


# --------------------------------------------------------------------------
# reset
# --------------------------------------------------------------------------
def _cmd_reset(rest: list[str]) -> int:
    """``graph reset [--force]`` — drop state + trace.

    Args:
        rest: Every token after ``reset``.

    Returns:
        The process exit code (always 0 — bash parity).
    """
    force = "--force" in rest
    _gdir, spath, tpath = _resolved_paths(rest)
    if not force:
        typer.echo("Will remove:")
        if os.path.isfile(spath):
            typer.echo(f"  {spath}")
        if os.path.isfile(tpath):
            typer.echo(f"  {tpath}")
        typer.echo("Re-run with --force to confirm.")
        return 0
    for path in (spath, tpath):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    typer.echo("reset: graph state and trace removed.")
    return 0


# --------------------------------------------------------------------------
# compile — emit a gate-free agent-fanout segment as a Dynamic Workflow script
# (v6.0.1, GH #77; doctrine workflow-compile-down.md §III/§IV/§V/§VI)
#
# Reuses the SAME state.json that `plan extract` materializes — the second
# projection of the one source graph (doctrine §II, anti-pattern 6); it does
# NOT parse plan.md or build a second graph reader.
# --------------------------------------------------------------------------
def _role_model(role: str, role_models: dict[str, str]) -> str:
    """Resolve one role's model pin (bash ``role_model`` + its fallback).

    Args:
        role: The flock role.
        role_models: The pre-resolved ``[models]`` map for
            :data:`_COMPILE_PIN_ROLES`.

    Returns:
        The model slug every emitted spawn for this role pins.
    """
    return role_models.get(role) or ("opus[1m]" if role in ("root", "planter", "engineer") else "sonnet")


def _graph_role_model(role: str) -> str:
    """Resolve one role from ``[models]`` config, else the built-in default.

    Mirrors ``cmd_graph.sh``'s ``_graph_role_model`` (itself mirroring
    ``cmd_models.sh``'s ``_model_default``): explicit ``[models].<role>``
    key wins; ``root``/``planter``/``engineer`` default to ``opus[1m]``;
    every other role defaults to ``sonnet``.

    Args:
        role: The flock role.

    Returns:
        The resolved model slug.
    """
    configured = cfg_section_get("models", role)
    if configured:
        return configured
    return "opus[1m]" if role in ("root", "planter", "engineer") else "sonnet"


def _cmd_compile(rest: list[str]) -> int:
    """``graph compile [--segment=N] [--out=D] [--verify] [--list] [...]``.

    Args:
        rest: Every token after ``compile``.

    Returns:
        The process exit code: 0 success, 1 usage/plan-scale/segment
        errors, 2 when ``--verify`` finds a faithfulness problem.
    """
    gdir, spath, tpath = _resolved_paths(rest)
    if not _require_state(spath):
        return 1

    seg_arg = ""
    out_dir = ""
    do_verify = False
    list_segments = False
    max_conc = 16
    fmt = "text"
    for arg in rest:
        if arg.startswith("--segment="):
            seg_arg = arg[len("--segment=") :]
        elif arg.startswith("--out="):
            out_dir = arg[len("--out=") :]
        elif arg == "--verify":
            do_verify = True
        elif arg == "--list":
            list_segments = True
        elif arg.startswith("--max-concurrent="):
            max_conc = int(arg[len("--max-concurrent=") :])
        elif arg == "--json":
            fmt = "json"
        elif arg.startswith("--run="):
            pass  # consumed by _resolved_paths (additive shim flag)
        elif arg in ("-h", "--help"):
            typer.echo(_USAGE)
            return 0
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            return 1
    if not out_dir:
        out_dir = os.path.join(gdir, "compiled")
    os.makedirs(out_dir, exist_ok=True)

    # Resolve each flock role's model from the single [models] map so every
    # emitted spawn carries an EXPLICIT pin (#180) instead of silently
    # inheriting the runtime's main-loop model (#178, one level removed).
    role_models = {role: _graph_role_model(role) for role in _COMPILE_PIN_ROLES}

    state = load_state(spath)
    nodes = state["nodes"]
    edges = state["edges"]
    sprint = state.get("sprint", "unknown")

    # adjacency over sequential edges
    succ: dict[str, list[tuple[str, str | None]]] = {nid: [] for nid in nodes}
    pred: dict[str, list[tuple[str, str | None]]] = {nid: [] for nid in nodes}
    for e in edges:
        if e["from"] in succ and e["to"] in nodes:
            succ[e["from"]].append((e["to"], e.get("label")))
            pred[e["to"]].append((e["from"], e.get("label")))

    # ---- segment detection (doctrine §III: maximal compilable subgraph) --
    def segment_of(seed_id: str) -> set[str]:
        seg = {seed_id}
        stack = [seed_id]
        while stack:
            cur = stack.pop()
            peers = list(nodes[cur].get("parallel_with") or [])
            peers += [t for (t, _l) in succ[cur]]
            peers += [f for (f, _l) in pred[cur]]
            for p in peers:
                if p in seg or p not in nodes:
                    continue
                if not _is_compilable(nodes[p]):
                    continue  # stop at seam boundary
                seg.add(p)
                stack.append(p)
        return seg

    compilable_ids = sorted(nid for nid, n in nodes.items() if _is_compilable(n))
    segments: list[list[str]] = []
    assigned: set[str] = set()
    for nid in compilable_ids:
        if nid in assigned:
            continue
        seg = segment_of(nid)
        assigned |= seg
        segments.append(sorted(seg))

    def seg_label(seg: list[str]) -> str:
        segset = set(seg)
        for nid in seg:  # CLOSE-SWARM is the canonical close label
            if _ntype(nodes[nid]) == "CLOSE-SWARM":
                return nid
        entries = [nid for nid in seg if not any(p in segset for (p, _l) in pred[nid])]
        for nid in sorted(entries):
            if "IMPL" in _ntype(nodes[nid]):
                return nid
        return sorted(entries)[0] if entries else seg[0]

    if list_segments:
        if fmt == "json":
            typer.echo(
                json.dumps(
                    [
                        {"label": seg_label(s), "nodes": s, "types": sorted({_ntype(nodes[i]) for i in s})}
                        for s in segments
                    ],
                    indent=2,
                )
            )
        else:
            if not segments:
                typer.echo("No gate-free agent-fanout segments in the graph (all nodes are seams).")
            for s in segments:
                typer.echo(f"segment {seg_label(s)}: {', '.join(s)}  [{', '.join(sorted({_ntype(nodes[i]) for i in s}))}]")
        return 0

    if not segments:
        typer.echo("ERROR: no gate-free agent-fanout segment in the graph (nothing to compile).", err=True)
        return 1

    # ---- choose the target segment ---------------------------------------
    target: list[str] | None = None
    if seg_arg:
        for s in segments:
            if seg_arg in s:
                target = s
                break
        if target is None:
            typer.echo(
                f"ERROR: no compilable segment contains node '{seg_arg}'. Run `shctx graph compile --list`.",
                err=True,
            )
            return 1
    else:
        for s in segments:  # default: CLOSE-SWARM first (§IX)
            if any(_ntype(nodes[i]) == "CLOSE-SWARM" for i in s):
                target = s
                break
        if target is None:
            target = segments[0]
    label = seg_label(target)

    # ---- order the segment into sequential batches of parallel cliques ---
    pool = set(target)

    def clique_of(nid: str) -> list[str]:
        seen = {nid}
        stack = [nid]
        while stack:
            c = stack.pop()
            for peer in nodes[c].get("parallel_with") or []:
                if peer in pool and peer not in seen:
                    seen.add(peer)
                    stack.append(peer)
        return sorted(seen)

    cliques: list[list[str]] = []
    seen_nodes: set[str] = set()
    for nid in sorted(target):
        if nid in seen_nodes:
            continue
        cl = clique_of(nid)
        seen_nodes |= set(cl)
        cliques.append(cl)

    clique_idx = {nid: i for i, cl in enumerate(cliques) for nid in cl}
    cl_succ: dict[int, set[int]] = collections.defaultdict(set)
    cl_indeg = [0] * len(cliques)
    seen_pairs: set[tuple[int, int]] = set()
    seg_orderings: list[dict] = []
    for e in edges:
        a, b = e["from"], e["to"]
        if a in clique_idx and b in clique_idx:
            seg_orderings.append({"from": a, "to": b, "edge": e.get("label")})
            ia, ib = clique_idx[a], clique_idx[b]
            if ia != ib and (ia, ib) not in seen_pairs:
                cl_succ[ia].add(ib)
                cl_indeg[ib] += 1
                seen_pairs.add((ia, ib))
    # Kahn topological order of cliques (deterministic: sorted frontier)
    indeg = cl_indeg[:]
    frontier = sorted(i for i in range(len(cliques)) if indeg[i] == 0)
    order: list[int] = []
    while frontier:
        i = frontier.pop(0)
        order.append(i)
        for j in sorted(cl_succ[i]):
            indeg[j] -= 1
            if indeg[j] == 0:
                frontier.append(j)
                frontier.sort()
    if len(order) != len(cliques):  # cycle (should not happen — DAG)
        order = list(range(len(cliques)))

    # ---- expand agents → spawns (deterministic) ---------------------------
    def spawns_for_node(nid: str) -> list[dict]:
        out = []
        for a in nodes[nid].get("agents") or []:
            # Defense-in-depth: `agents` is normalized to dicts by `plan
            # extract`, but guard here too in case state.json was
            # hand-edited or pre-dates the fix (GH #225).
            role = (a.get("role", "coder") if isinstance(a, dict) else a) or "coder"
            count = int((a.get("count", 1) if isinstance(a, dict) else 1) or 1)
            concerns = (a.get("concerns") or a.get("concern")) if isinstance(a, dict) else None
            briefs = (a.get("briefs") or a.get("brief")) if isinstance(a, dict) else None
            for k in range(count):
                tag = None
                if isinstance(concerns, list) and k < len(concerns):
                    tag = concerns[k]
                elif isinstance(concerns, str):
                    tag = concerns
                elif isinstance(briefs, list) and k < len(briefs):
                    tag = briefs[k]
                elif isinstance(briefs, str):
                    tag = briefs
                out.append(
                    {"node": nid, "role": role, "index": k, "tag": tag, "readonly": role in _READONLY_ROLES}
                )
        return out

    total_agents = sum(len(spawns_for_node(nid)) for nid in target)
    if total_agents > _HARD_TOTAL_CAP:
        typer.echo(
            f"ERROR: segment '{label}' spawns {total_agents} agents (> {_HARD_TOTAL_CAP} cap, "
            "doctrine §III). This is a plan-scale error — split the plan.",
            err=True,
        )
        return 1

    # ---- emit the workflow script -----------------------------------------
    def js(s: object) -> str:
        return json.dumps("" if s is None else s)

    def _1l(s: object) -> str:
        return str(s).replace("\n", " ").replace("\r", " ").strip()  # comment-safe

    L: list[str] = []

    def A(s: str) -> None:
        L.append(s)

    A("// ───── shepherd compiled workflow ─────")
    A(f"// segment      : {_1l(label)}")
    A("// generator    : `shctx graph compile` — compile(G_seg). DO NOT hand-edit.")
    A(f"// source plan  : {_1l(state.get('plan_path', '?'))}")
    A(f"// sprint       : {_1l(sprint)}")
    A(f"// nodes        : {', '.join(target)}")
    A(f"// agents       : {total_agents}  (≤16 concurrent, ≤1000 total — doctrine §III)")
    A(f"// faithfulness : `shctx graph compile --segment={label} --verify`  (§IV)")
    A("//")
    A("// SEAMS (doctrine §VI): git/shell, operator gates, and SQLite+git canonical")
    A("// writes run at the CONDUCTOR, never here. This workflow only coordinates")
    A("// agent fanout out-of-context; results return to the conductor in script")
    A("// variables. On runtime failure the conductor degrades to `shctx graph next`")
    A("// direct dispatch for this segment (doctrine §VI; no parallel engine).")
    A("//")
    A("// Each spawn is a thunk `() => agent(prompt, opts)` — the real Workflow")
    A("// signature (prompt STRING first, opts OBJECT second), with a LITERAL opts")
    A("// at the call site so the pin is statically visible: opts.agentType =")
    A('// "shepherd:<role>" (loads the role definition + its tool allowlist) and')
    A("// opts.model resolved from the [models] map — NEVER a bare agent(prompt),")
    A("// which would inherit the main-loop model (#178/#180). This shape is")
    A("// workflow_model_guard.sh-clean by static analysis (the guard never runs on")
    A("// this `node`-executed path, but 'would it pass the guard' is the bar).")
    A('// `briefs` is the conductor-resolved brief map keyed "<node>:<tag>" (brief')
    A("// CONTENT lives with the conductor, not in compile(G) — referenced by id).")
    A("")
    # Dynamic Workflow meta contract (documented deviation 2): a PURE
    # literal derived deterministically from state.json — name (segment
    # label), description (label + sprint), phases (batch order). NO
    # timestamp here ever; compiled_at lives ONLY in the manifest so the
    # script bytes stay deterministic and the §IV sha256 diff holds.
    meta_description = f"shepherd compiled segment '{label}' (sprint {sprint})"
    A("export const meta = {")
    A(f"  name: {js(label)},")
    A(f"  description: {js(meta_description)},")
    A(f"  phases: {json.dumps([cliques[oi] for oi in order])},")
    A("};")
    A("")
    A("export default async function ({ agent, briefs }) {")
    A(f"  const MAX_CONCURRENT = {max_conc};  // doctrine §III concurrency cap")
    A("")
    A("  // Bounded fan-out: run spawn thunks in chunks of MAX_CONCURRENT (unbounded")
    A("  // Promise.all is the §III anti-pattern). parallel_with peers share one batch.")
    A("  async function fanout(thunks) {")
    A("    const out = [];")
    A("    for (let i = 0; i < thunks.length; i += MAX_CONCURRENT) {")
    A("      const chunk = thunks.slice(i, i + MAX_CONCURRENT);")
    A("      out.push(...(await Promise.all(chunk.map((t) => t()))));")
    A("    }")
    A("    return out;")
    A("  }")
    A("")
    A("  const results = {};")
    for oi in order:
        cl = cliques[oi]
        spawns: list[dict] = []
        for nid in cl:
            spawns.extend(spawns_for_node(nid))
        bvar = f"batch_{oi}"
        types = ", ".join(sorted({_ntype(nodes[i]) for i in cl}))
        A(f"  // batch {oi}: {', '.join(cl)}  [{types}]")
        A(f"  const {bvar} = await fanout([")
        for s in spawns:
            key = f"{s['node']}:{s['tag'] if s['tag'] is not None else s['index']}"
            desc = f"@{s['role']}" + (f": {s['tag']}" if s["tag"] else f" {s['node']}#{s['index']}")
            ro = "  /* read-only: allowlist-enforced, no edit tools (§VII, #74) */" if s["readonly"] else ""
            mdl = _role_model(s["role"], role_models)
            A(
                f"    () => agent(briefs[{js(key)}], {{ agentType: \"shepherd:{s['role']}\", "
                f"model: {js(mdl)}, label: {js(desc)} }}),{ro}"
            )
        A("  ]);")
        for nid in cl:
            A(f"  results[{js(nid)}] = {bvar};")
        A("")
    A("  // Out-of-context: results live in script vars, returned to the conductor,")
    A("  // which writes canonical state (SQLite + git) and evaluates the next seam.")
    A("  return results;")
    A("}")
    script = "\n".join(L) + "\n"
    script_sha = hashlib.sha256(script.encode()).hexdigest()

    manifest = {
        "segment": label,
        "sprint": sprint,
        "nodes": target,
        "batches": [
            {
                "index": oi,
                "nodes": cliques[oi],
                "spawns": [
                    {"node": s["node"], "role": s["role"], "tag": s["tag"], "readonly": s["readonly"]}
                    for nid in cliques[oi]
                    for s in spawns_for_node(nid)
                ],
            }
            for oi in order
        ],
        "orderings": seg_orderings,
        "total_agents": total_agents,
        "max_concurrent": max_conc,
        "compiled_at": int(time.time()),
        "script_sha256": script_sha,
    }

    script_path = os.path.join(out_dir, f"{label}.workflow.js")
    manifest_path = os.path.join(out_dir, f"{label}.manifest.json")
    # Capture the prior on-disk script BEFORE overwriting — this IS the
    # "runtime's raw script" the §IV faithfulness diff compares a fresh
    # compile(G_seg) against.
    prior_script: str | None = None
    if os.path.exists(script_path):
        with open(script_path, encoding="utf-8") as fh:
            prior_script = fh.read()
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(script)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    try:
        append_trace(
            tpath,
            {
                "at": int(time.time()),
                "event": "graph_compiled",
                "segment": label,
                "agents": total_agents,
                "sha256": script_sha[:12],
            },
        )
    except Exception:  # noqa: BLE001 - bash wraps this append in try/except too
        pass

    # ---- §IV faithfulness diff -------------------------------------------
    def run_verify() -> dict[str, list[str]]:
        problems: dict[str, list[str]] = {"soundness": [], "completeness": [], "determinism": [], "model_pin": []}

        expected_nodes = set(target)
        expected_spawns: collections.Counter = collections.Counter()
        for nid in target:
            for s in spawns_for_node(nid):
                expected_spawns[(s["node"], s["role"])] += 1

        parsed_roles = collections.Counter(re.findall(r'agentType:\s*"shepherd:([a-z]+)"', script))
        parsed_nodes = {a or b for (a, b) in re.findall(r'results\[(?:"([^"]+)"|\'([^\']+)\')\]', script)}

        # SOUNDNESS — no spawned agent absent from V_seg; no ordering absent from E_seg.
        spawned_total: collections.Counter = collections.Counter()
        for (_n, role), c in expected_spawns.items():
            spawned_total[role] += c
        for role, c in parsed_roles.items():
            if spawned_total.get(role, 0) != c:
                problems["soundness"].append(
                    f"role '{role}': script spawns {c}, source graph specifies {spawned_total.get(role, 0)}"
                )
        for nid in parsed_nodes:
            if nid not in expected_nodes:
                problems["soundness"].append(f"script references node '{nid}' not in segment V_seg")
        for ia, ib in seen_pairs:
            backed = any(
                clique_idx.get(o["from"]) == ia and clique_idx.get(o["to"]) == ib for o in seg_orderings
            )
            if not backed:
                problems["soundness"].append(f"emitted ordering batch{ia}->batch{ib} has no backing edge in E_seg")

        # COMPLETENESS — every must-fire node present; every expected spawn present.
        for nid in expected_nodes:
            if nid not in parsed_nodes:
                problems["completeness"].append(f"segment node '{nid}' missing from compiled script")
        for role, c in spawned_total.items():
            if parsed_roles.get(role, 0) != c:
                problems["completeness"].append(
                    f"role '{role}': expected {c} spawns, script has {parsed_roles.get(role, 0)}"
                )

        # DETERMINISM / faithfulness diff — the script the runtime was about
        # to run (the prior on-disk artifact) must equal a fresh,
        # deterministic compile(G_seg).
        if prior_script is not None and prior_script != script:
            problems["determinism"].append(
                "prior on-disk script != fresh compile(G_seg) — hand-edited, stale, or the "
                "[models] pin resolved differently since last compile (#180) "
                "(recompiled to the canonical form now)"
            )
        for bad in ("Math.random", "Date.now", "Promise.race", "Promise.any"):
            if bad in script:
                problems["determinism"].append(f"nondeterministic construct '{bad}' in compiled script")

        # MODEL-PIN (#180) — every emitted spawn MUST carry an explicit
        # agentType + model pin.
        n_agenttype = len(re.findall(r'agentType:\s*"shepherd:[a-z]+"', script))
        n_modelpin = len(re.findall(r'\bmodel:\s*"[^"]+"', script))
        if n_agenttype != total_agents:
            problems["model_pin"].append(f"{total_agents} expected spawns but {n_agenttype} agentType pin(s)")
        if n_modelpin < total_agents:
            problems["model_pin"].append(f"{total_agents - n_modelpin} spawn(s) missing an explicit model pin")
        if re.search(r"=>\s*agent\(\s*s\s*\)", script):
            problems["model_pin"].append(
                "legacy opts-less agent(s) call shape present — must be agent(prompt, opts) with a pin"
            )

        return problems

    verify_result = run_verify() if do_verify else None
    verify_ok = (verify_result is None) or all(len(v) == 0 for v in verify_result.values())

    # ---- report -----------------------------------------------------------
    if fmt == "json":
        out: dict[str, object] = {
            "segment": label,
            "script": script_path,
            "manifest": manifest_path,
            "nodes": target,
            "total_agents": total_agents,
            "max_concurrent": max_conc,
            "script_sha256": script_sha,
        }
        if verify_result is not None:
            out["faithfulness"] = {k: ("PASS" if not v else v) for k, v in verify_result.items()}
            out["faithfulness_ok"] = verify_ok
        typer.echo(json.dumps(out, indent=2))
    else:
        typer.echo(f"compiled segment '{label}'  ({total_agents} agents, {len(cliques)} batch(es), ≤16 concurrent)")
        typer.echo(f"  script   : {script_path}")
        typer.echo(f"  manifest : {manifest_path}")
        typer.echo(f"  sha256   : {script_sha[:16]}")
        if verify_result is not None:
            typer.echo("  faithfulness diff (§IV):")
            for dim in ("soundness", "completeness", "determinism", "model_pin"):
                issues = verify_result[dim]
                if not issues:
                    typer.echo(f"    ✓ {dim}")
                else:
                    typer.echo(f"    ✗ {dim}")
                    for it in issues:
                        typer.echo(f"        - {it}")

    if do_verify and not verify_ok:
        return 2
    return 0


# --------------------------------------------------------------------------
# diagram — Mermaid execution diagram of the Stage Graph (#77 topology utility)
# --------------------------------------------------------------------------
def _cmd_diagram(rest: list[str]) -> int:
    """``graph diagram [--segment=N] [--out=F] [--stdout]``.

    Args:
        rest: Every token after ``diagram``.

    Returns:
        The process exit code.
    """
    gdir, spath, _tpath = _resolved_paths(rest)
    if not _require_state(spath):
        return 1
    seg_arg = ""
    out_file = ""
    to_stdout = False
    for arg in rest:
        if arg.startswith("--segment="):
            seg_arg = arg[len("--segment=") :]
        elif arg.startswith("--out="):
            out_file = arg[len("--out=") :]
        elif arg == "--stdout":
            to_stdout = True
        elif arg.startswith("--run="):
            pass  # consumed by _resolved_paths (additive shim flag)
        elif arg in ("-h", "--help"):
            typer.echo(_USAGE)
            return 0
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            return 1
    diag_dir = os.path.join(gdir, "diagrams")

    state = load_state(spath)
    nodes = state["nodes"]
    edges = state["edges"]
    sprint = state.get("sprint", "unknown")

    def is_fanout(n: dict) -> bool:
        return _is_compilable(n)

    def mid(nid: str) -> str:
        return "n_" + re.sub(r"[^A-Za-z0-9]", "_", nid)

    # --segment overlay: flood compilable nodes without crossing a seam.
    seg_members: set[str] = set()
    if seg_arg:
        succ: dict[str, list[str]] = {k: [] for k in nodes}
        pred: dict[str, list[str]] = {k: [] for k in nodes}
        for e in edges:
            if e["from"] in succ and e["to"] in nodes:
                succ[e["from"]].append(e["to"])
                pred[e["to"]].append(e["from"])
        if seg_arg in nodes and is_fanout(nodes[seg_arg]):
            stack = [seg_arg]
            seg_members = {seg_arg}
            while stack:
                cur = stack.pop()
                for p in list(nodes[cur].get("parallel_with") or []) + succ[cur] + pred[cur]:
                    if p in seg_members or p not in nodes or not is_fanout(nodes[p]):
                        continue
                    seg_members.add(p)
                    stack.append(p)
        elif seg_arg not in nodes:
            typer.echo(f"ERROR: node '{seg_arg}' not in graph. Run `shctx graph status`.", err=True)
            return 1

    L = [
        "%%{init: {'flowchart': {'curve':'basis'}}}%%",
        "flowchart TD",
        f"  %% shepherd Stage Graph — sprint {sprint}  (`shctx graph diagram`)",
    ]
    for nid, n in nodes.items():
        label = nid if nid == _ntype(n) else f"{nid}<br/>{_ntype(n)}"
        ag = n.get("agents") or []
        if ag:
            # Defense-in-depth: `agents` is normalized to dicts by `plan
            # extract`, but guard here too in case state.json was
            # hand-edited or pre-dates the fix (GH #225).
            label += "<br/>" + ", ".join(
                f"@{(a.get('role') if isinstance(a, dict) else a)}"
                f"×{(a.get('count', 1) if isinstance(a, dict) else 1)}"
                for a in ag
            )
        left, right = ("{{", "}}") if not is_fanout(n) else ("[", "]")  # hexagon = seam, box = fanout
        L.append(f'  {mid(nid)}{left}"{label}"{right}')
    for e in edges:
        if e["from"] in nodes and e["to"] in nodes:
            lab = (e.get("label") or "").replace("|", "/").replace('"', "'")
            L.append(
                f'  {mid(e["from"])} -->|{lab}| {mid(e["to"])}' if lab else f'  {mid(e["from"])} --> {mid(e["to"])}'
            )
    if seg_members:
        L.append(
            f'  subgraph SEG["compiled segment: {seg_arg} — Dynamic Workflow (≤16 concurrent, out-of-context)"]'
        )
        for nid in sorted(seg_members):
            L.append(f"    {mid(nid)}")
        L.append("  end")
    L.append("  classDef seam fill:#fde,stroke:#a36,stroke-width:1px;")
    L.append("  classDef fanout fill:#def,stroke:#36a,stroke-width:1px;")
    for nid, n in nodes.items():
        L.append(f"  class {mid(nid)} {'fanout' if is_fanout(n) else 'seam'};")
    mermaid = "\n".join(L) + "\n"

    if to_stdout or out_file == "-":
        sys.stdout.write(mermaid)
        return 0
    path = out_file or os.path.join(diag_dir, f"{sprint}.mmd")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(mermaid)
    png = os.path.splitext(path)[0] + ".png"
    nfan = sum(1 for n in nodes.values() if is_fanout(n))
    typer.echo(f"diagram written: {path}")
    typer.echo(
        f"  nodes: {len(nodes)} ({nfan} fanout / {len(nodes) - nfan} seam)  edges: {len(edges)}"
        + (f"  segment-overlay: {seg_arg} ({len(seg_members)} nodes)" if seg_members else "")
    )
    typer.echo(f"  render: paste into any Mermaid viewer, or `mmdc -i {path} -o {png}` (mermaid-cli).")
    return 0


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> int:
    """Reproduce ``cmd_graph.sh``'s ``case "$sub"`` dispatch byte-for-byte.

    Args:
        argv: Every raw token after ``graph`` on the command line.

    Returns:
        The process exit code.
    """
    sub = argv[0] if argv else ""
    rest = argv[1:]
    if sub in ("", "-h", "--help"):
        typer.echo(_USAGE)
        return 0
    if sub == "status":
        return _cmd_status(rest)
    if sub == "next":
        return _cmd_next(rest)
    if sub == "mark":
        return _cmd_mark(rest)
    if sub == "trace":
        return _cmd_trace(rest)
    if sub == "reset":
        return _cmd_reset(rest)
    if sub == "compile":
        return _cmd_compile(rest)
    if sub == "diagram":
        return _cmd_diagram(rest)
    typer.echo(f"ERROR: unknown subcommand: {sub}", err=True)
    typer.echo(_USAGE, err=True)
    return 1


@app.callback(invoke_without_command=True, context_settings={"ignore_unknown_options": True, "help_option_names": []})
def graph(
    args: list[str] = typer.Argument(
        None,
        help="Subcommand + args: status | next | mark | trace | reset | compile | diagram.",
    ),
) -> None:
    """Stage Graph rule-engine walker + compiler — native ``shctx graph`` port.

    See the module docstring for why this is ONE variadic callback rather
    than seven ``@app.command()``s (bash's usage-on-bare-invocation,
    stderr-usage-on-unknown-subcommand, and per-arm flag/exit-code
    contracts).

    Args:
        args: Every token after ``graph``, captured raw (``--help`` and
            unknown options land here literally — ``help_option_names``
            is emptied and ``ignore_unknown_options`` is set).

    Raises:
        typer.Exit: Always, carrying :func:`_dispatch`'s exit code.
    """
    raise typer.Exit(code=_dispatch(list(args or [])))


__all__ = ["app"]
