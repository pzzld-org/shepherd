"""``shepherd plan`` — Stage Graph extraction + critic-proof gate (bash: ``cmd_plan.sh``).

Native port of ``skills/context/scripts/cmd_plan.sh`` (483 LOC), the
bridge from the plan-as-document to the plan-as-program: parse the
engineer's plan.md ``## Stage Graph`` YAML block into the canonical
machine-readable ``<graph-dir>/state.json`` that :mod:`shepherd_cli.
commands.graph` (the rule-engine walker) consumes, plus the critic-proof
sidecar workflow (``hash`` / ``record-critique`` / ``verify``).

**NO DATABASE.** ``cmd_plan.sh`` touches no ``shctx_sql``/
``shctx_db_path`` call anywhere — the whole surface is filesystem
(plan.md in, state.json/trace.jsonl/critic-proof.json out) plus two
``_lib.sh`` helpers this port reproduces natively: ``git rev-parse
--abbrev-ref HEAD`` (sprint default) and ``cfg_get plans`` (verify's
proof-dir discovery). No ``db.lifespan``, no Tortoise models —
:mod:`shepherd_cli.commands.models`'s pure-config shape, with file I/O.

SINGLE VARIADIC CALLBACK, NOT REAL ``@app.command()``s
=======================================================
Mirrors :mod:`shepherd_cli.commands.seed`/``style``'s documented shape:
``cmd_plan.sh``'s dispatcher has bash-specific contracts a Typer
``Group`` cannot reproduce — a bare ``shctx plan`` (and ``-h``/
``--help``) prints ``usage()`` to STDOUT and exits 0; an unrecognized
subcommand prints ``ERROR: unknown subcommand: <sub>`` AND the usage
text, both to STDERR, and exits 1; per-subcommand flag loops accept
equals-form-only flags (``--sprint=X``) in some arms and both two-token
and equals forms (``--plan <p>`` / ``--plan=<p>``) in others, with a
distinct unknown-arg exit code per arm (1 for ``extract``, 2 for
``hash``/``record-critique``/``verify``). This module registers ZERO
``@app.command()``s; one callback captures the raw token list
(``ignore_unknown_options`` + empty ``help_option_names``, so ``--help``
lands here literally instead of triggering Click's generated help) and
:func:`_dispatch` reproduces bash's ``case``/loops by hand.

BASH-PARITY MAP (subcommand -> exit codes / streams)
=====================================================
- ``extract <plan.md> [--sprint=B] [--force]`` — parse + store. Usage
  error / unknown arg / overwrite-without---force / any parse failure:
  exit 1, message on stderr (the heredoc's ``sys.exit("ERROR: ...")``
  stream). Success prints the 3-line report on stdout. The GH #225
  normalization is preserved: every ``agents`` entry becomes a dict with
  a truthy ``role`` + int ``count``; a malformed entry fails extraction
  with ``malformed agents entry`` instead of AttributeError-ing later.
- ``topology [--md|--json]`` — pretty-print. Unknown args are silently
  ignored (bash's flag ``case`` has no default arm). ``--json`` emits the
  RAW state.json bytes (bash ``cat``), not a re-serialization.
- ``validate`` — structural checks; ignores all args (bash parity).
  Problems: ``VALIDATION FAILED:`` + ``  ✗ ...`` lines on stdout, exit 1.
  The problem-list order matches bash exactly (edge targets, predicate
  predecessors, parallel_with mutuality, malformed agents, then cycle).
- ``hash <plan.md>`` — ``sha256:<hex>`` of the plan bytes; usage error
  exits 2.
- ``record-critique --plan P --pre H --verdict V [--iterations N]
  [--findings N]`` — writes the critic-proof sidecar next to the plan
  (``<slug>.critic-proof.json``); missing required flag / unknown arg
  exits 2.
- ``verify [--plan P] [--quiet]`` — the acceptance gate. Named failure
  codes (``CRITIC-PROOF-MISSING`` / ``PLAN-UNEDITED`` /
  ``CRITIC-PROOF-STALE`` / ``PLAN-UNCRITIQUED``) print on STDOUT (the
  bash heredoc's ``print``) and exit 1 — EXCEPT the proof-dir-ambiguity
  ``CRITIC-PROOF-MISSING`` (no ``--plan``, != 1 proof file found), which
  bash prints on STDERR; that stream asymmetry is reproduced verbatim.

DOCUMENTED DEVIATIONS (additive / cosmetic only)
=================================================
1. ``--run=<name>`` on ``extract``/``topology``/``validate`` — the
   run-scoped artifact shim (see :mod:`shepherd_cli.commands.
   models_graph`'s module docstring): NEW state is written to
   ``<workdir>/runs/<run>/graph/`` when a run is identifiable
   (``--run`` flag, ``SHEPHERD_RUN`` env, or ``<workdir>/runs/current``
   marker); readers prefer the run-scoped state.json when present and
   ALWAYS fall back to the legacy ``<workdir>/graph/``. With no
   identifiable run, behavior is byte-for-byte bash.
2. ``record-critique`` with a non-integer ``--iterations``/``--findings``
   prints a clean ``ERROR: --iterations/--findings must be integers``
   instead of bash's raw Python ``ValueError`` traceback; the exit code
   (1) is unchanged.
3. A two-token flag (``--plan``/``--pre``/...) given as the LAST token
   with no value is treated as empty (falling into the clean
   ``required`` error, exit 2) where bash's ``shift 2`` under ``set -e``
   dies silently with exit 1.
4. PyYAML is imported lazily inside ``extract`` — exactly where bash's
   heredoc imports it — and its absence produces bash's verbatim
   ``ERROR: python3 PyYAML required (apt: python3-yaml | pip: PyYAML)``
   on stderr, exit 1.
5. ``extract`` advisorily validates the state it just built against
   :class:`shepherd_cli.commands.models_graph.GraphState` — a mismatch
   never blocks a write bash would have performed (the plain-dict
   document is what gets serialized, preserving bash's key order and
   file bytes).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import typer

from shepherd_cli.commands.models_graph import (
    GraphState,
    cfg_get,
    current_sprint,
    load_state,
    resolve_graph_dir,
    resolve_run,
    state_path,
)
from shepherd_cli.resolution import resolve_repo_root

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": []},
    help="Stage Graph extraction + critic-proof gate (bash: cmd_plan.sh).",
)

#: Verbatim ``usage()`` heredoc from ``cmd_plan.sh``.
_USAGE = """shctx plan <extract|topology|validate|hash|record-critique|verify> [args]

  extract <plan.md> [--sprint=BRANCH] [--force]
      Parse the Stage Graph YAML from plan.md and store
      <namespace>/graph/state.json. Refuses to overwrite unless --force.

  topology [--sprint=BRANCH] [--md]
      Pretty-print the extracted graph — nodes by state, edges, parallel cliques.

  validate
      Structural checks (acyclic, predicates resolve, parallel_with mutual).

  hash <plan.md>
      Echo "sha256:<hex>" of the plan bytes. The engineer captures this BEFORE
      dispatching @critic so record-critique can prove the plan was edited.

  record-critique --plan <path> --pre <hash> --verdict <v> [--iterations N] [--findings N]
      Write the critic-proof alongside the plan. Computes the post-critic hash
      from the current plan bytes; edited = (pre != post). Emitted by the
      engineer teammate after the in-session @critic pass + revision.

  verify [--plan <path>] [--quiet]
      Root's thin acceptance gate (mirrors `shctx seed verify`): the plan was
      critiqued AND edited at least once. Exit 1 with a named code on failure —
      CRITIC-PROOF-MISSING / PLAN-UNEDITED / CRITIC-PROOF-STALE / PLAN-UNCRITIQUED.
      post_critic_hash must match the ACTUAL current plan bytes, so a stale or
      hand-forged proof cannot pass.

The state file is the input to `shctx graph` (the rule-engine walker).
Critic-proof: skills/shepherd/references/pipeline.md §INTRO. See skills/shepherd/references/flock.md §Dispatch."""


def _sha256_file(path: str) -> str:
    """``sha256:<hex>`` of one file's bytes (the hash/verify primitive)."""
    with open(path, "rb") as fh:
        return "sha256:" + hashlib.sha256(fh.read()).hexdigest()


def _proof_path(plan: str) -> str:
    """Critic-proof path derived from the plan path (bash ``_proof_path``).

    ``.../plans/<slug>.plan.md`` -> ``.../plans/<slug>.critic-proof.json``
    (strip a ``.md`` suffix, then a ``.plan`` suffix).

    Args:
        plan: The plan file path as given on the command line.

    Returns:
        The sidecar proof path in the SAME directory as the plan.
    """
    directory = os.path.dirname(plan) or "."
    base = os.path.basename(plan)
    base = base[: -len(".md")] if base.endswith(".md") else base
    base = base[: -len(".plan")] if base.endswith(".plan") else base
    return os.path.join(directory, f"{base}.critic-proof.json")


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------
def _cmd_extract(rest: list[str]) -> int:
    """``plan extract <plan.md> [--sprint=B] [--force] [--run=R]``.

    Args:
        rest: Every token after ``extract``, in order.

    Returns:
        The process exit code (0 success, 1 any failure — bash parity).
    """
    plan_arg = rest[0] if rest else ""
    if not plan_arg or not os.path.isfile(plan_arg):
        typer.echo("ERROR: usage: shctx plan extract <plan.md>", err=True)
        return 1

    sprint = ""
    force = False
    run_flag: str | None = None
    for arg in rest[1:]:
        if arg.startswith("--sprint="):
            sprint = arg[len("--sprint=") :]
        elif arg == "--force":
            force = True
        elif arg.startswith("--run="):
            run_flag = arg[len("--run=") :]
        elif arg in ("-h", "--help"):
            typer.echo(_USAGE)
            return 0
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            return 1
    if not sprint:
        sprint = current_sprint()

    out_dir = resolve_graph_dir(resolve_run(run_flag), for_write=True)
    os.makedirs(out_dir, exist_ok=True)
    out_path = state_path(out_dir)
    if os.path.isfile(out_path) and not force:
        typer.echo(f"ERROR: {out_path} already exists. Pass --force to overwrite.", err=True)
        return 1

    # ---- parse (transliterated from cmd_plan.sh's extract heredoc) -------
    with open(plan_arg, encoding="utf-8") as fh:
        text = fh.read()
    section = re.search(r"^##\s+Stage Graph\s*$(.*?)(?=^##\s+|\Z)", text, re.MULTILINE | re.DOTALL)
    if not section:
        typer.echo("ERROR: no `## Stage Graph` section found in " + plan_arg, err=True)
        return 1
    body = section.group(1)
    fence = re.search(r"```(?:yaml|yml)?\s*\n(.*?)```", body, re.DOTALL)
    if not fence:
        typer.echo("ERROR: no fenced code block under `## Stage Graph`", err=True)
        return 1
    yaml_text = fence.group(1)

    # Lazy import, exactly where bash's heredoc imports it, with bash's
    # verbatim degradation message when PyYAML is absent.
    try:
        import yaml
    except ImportError:
        typer.echo("ERROR: python3 PyYAML required (apt: python3-yaml | pip: PyYAML)", err=True)
        return 1

    doc = yaml.safe_load(yaml_text)
    if not isinstance(doc, list):
        typer.echo(
            "ERROR: Stage Graph YAML must be a list of node objects (got " + type(doc).__name__ + ")",
            err=True,
        )
        return 1

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for n in doc:
        nid = n.get("id")
        if not nid:
            typer.echo(f"ERROR: node missing `id`: {n!r}", err=True)
            return 1
        if nid in nodes:
            typer.echo(f"ERROR: duplicate node id: {nid}", err=True)
            return 1
        in_preds = n.get("in_predicates") or []
        parallel_with = n.get("parallel_with") or []
        out_edges = n.get("out_edges") or []
        # GH #225: normalize agents entries HERE (the single writer of the
        # per-node `agents` field) so every downstream reader can assume a
        # dict with a `role` key.
        raw_agents = n.get("agents") or []
        if not isinstance(raw_agents, list):
            typer.echo(
                f"ERROR: node {nid} has malformed agents entry: {raw_agents!r} "
                "(expected a role-name string or a mapping with a role key)",
                err=True,
            )
            return 1
        agents: list[dict] = []
        for a in raw_agents:
            if isinstance(a, str):
                agents.append({"role": a, "count": 1})
            elif isinstance(a, dict) and a.get("role"):
                entry = dict(a)
                entry["count"] = int(a.get("count", 1) or 1)
                agents.append(entry)
            else:
                typer.echo(
                    f"ERROR: node {nid} has malformed agents entry: {a!r} "
                    "(expected a role-name string or a mapping with a role key)",
                    err=True,
                )
                return 1
        node_state = "done" if n.get("type") == "SEED-VERIFY" else "pending"
        if node_state == "pending" and not in_preds:
            node_state = "ready"

        nodes[nid] = {
            "id": nid,
            "type": n.get("type", "UNKNOWN"),
            "state": node_state,
            "parallel_with": parallel_with,
            "agents": agents,
            "in_predicates": [
                {"predecessor": p.get("predecessor"), "edge": p.get("edge"), "satisfied": False}
                for p in in_preds
            ],
            "started_at": None,
            "exited_at": None,
            "exit_edge": None,
            "agent_ids": [],
        }
        for e in out_edges:
            edges.append({"from": nid, "label": e.get("label"), "to": e.get("target")})

    state = {
        "schema_version": 1,
        "sprint": sprint,
        "plan_path": plan_arg,
        "extracted_at": int(time.time()),
        "nodes": nodes,
        "edges": edges,
        "trace_path": out_path.replace("state.json", "trace.jsonl"),
    }
    # Advisory contract check (documented deviation 5): never blocks a
    # write bash would have performed; the plain dict is what serializes.
    try:
        GraphState.model_validate(state)
    except Exception:  # noqa: BLE001 - advisory only, by contract
        pass

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    with open(state["trace_path"], "w", encoding="utf-8") as tf:
        json.dump(
            {
                "at": int(time.time()),
                "event": "graph_extracted",
                "sprint": sprint,
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
            tf,
        )
        tf.write("\n")

    typer.echo(f"extracted {len(nodes)} nodes / {len(edges)} edges from {plan_arg}")
    typer.echo(f"  state:  {out_path}")
    typer.echo(f"  trace:  {state['trace_path']}")
    return 0


# --------------------------------------------------------------------------
# topology
# --------------------------------------------------------------------------
def _cmd_topology(rest: list[str]) -> int:
    """``plan topology [--md|--json] [--run=R]`` (unknown args ignored).

    Args:
        rest: Every token after ``topology``.

    Returns:
        The process exit code.
    """
    fmt = "text"
    run_flag: str | None = None
    for arg in rest:
        if arg == "--md":
            fmt = "md"
        elif arg == "--json":
            fmt = "json"
        elif arg.startswith("--run="):
            run_flag = arg[len("--run=") :]

    s = state_path(resolve_graph_dir(resolve_run(run_flag)))
    if not os.path.isfile(s):
        typer.echo(f"ERROR: no graph state at {s} (run 'shctx plan extract <plan.md>' first)", err=True)
        return 1

    if fmt == "json":
        with open(s, encoding="utf-8") as fh:
            sys.stdout.write(fh.read())  # bash `cat` — raw bytes, no added newline
        return 0

    state = load_state(s)
    by_state: dict[str, list[dict]] = {}
    for _nid, n in state["nodes"].items():
        by_state.setdefault(n["state"], []).append(n)

    def pn(n: dict) -> str:
        pw = ", ".join(n.get("parallel_with") or []) or "—"
        # Defense-in-depth: `agents` is normalized to dicts by `plan
        # extract`, but guard here too in case state.json was hand-edited
        # or pre-dates the fix (GH #225).
        agents = ", ".join(
            f"{(a.get('role') if isinstance(a, dict) else a)}"
            f"x{(a.get('count', 1) if isinstance(a, dict) else 1)}"
            for a in (n.get("agents") or [])
        ) or "inline"
        return f"{n['id']:<24} {n['type']:<24} {agents:<24} parallel:[{pw}]"

    lines: list[str] = []
    if fmt == "md":
        lines.append(f"## Topology — {state['sprint']}")
        lines.append(
            f"_{len(state['nodes'])} nodes · {len(state['edges'])} edges · extracted at {state['extracted_at']}_"
        )
        for st in ("ready", "in_flight", "pending", "done", "skipped"):
            bucket = by_state.get(st, [])
            if not bucket:
                continue
            lines.append("")
            lines.append(f"### {st} ({len(bucket)})")
            for n in bucket:
                lines.append(f"- `{pn(n)}`")
        lines.append("")
        lines.append("### Edges")
        for e in state["edges"]:
            lines.append(f"- `{e['from']}` --{e['label']}--> `{e['to']}`")
    else:
        lines.append(f"Topology — {state['sprint']}  ({len(state['nodes'])} nodes / {len(state['edges'])} edges)")
        for st in ("ready", "in_flight", "pending", "done", "skipped"):
            bucket = by_state.get(st, [])
            if not bucket:
                continue
            lines.append("")
            lines.append(f"[{st}] ({len(bucket)})")
            for n in bucket:
                lines.append("  " + pn(n))
        lines.append("")
        lines.append("[edges]")
        for e in state["edges"]:
            lines.append(f"  {e['from']} --{e['label']}--> {e['to']}")
    typer.echo("\n".join(lines))
    return 0


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------
def _cmd_validate(rest: list[str]) -> int:
    """``plan validate [--run=R]`` (all other args ignored — bash parity).

    Args:
        rest: Every token after ``validate``.

    Returns:
        0 when structurally valid, 1 with the problem list otherwise.
    """
    run_flag: str | None = None
    for arg in rest:
        if arg.startswith("--run="):
            run_flag = arg[len("--run=") :]

    s = state_path(resolve_graph_dir(resolve_run(run_flag)))
    if not os.path.isfile(s):
        typer.echo(f"ERROR: no graph state at {s}", err=True)
        return 1

    state = load_state(s)
    nodes = state["nodes"]
    edges = state["edges"]
    problems: list[str] = []

    # 1. Every edge target must exist
    for e in edges:
        if e["to"] not in nodes:
            problems.append(f"edge {e['from']} --{e['label']}--> {e['to']} → target node missing")

    # 2. Every in_predicate's predecessor must exist
    for nid, n in nodes.items():
        for p in n["in_predicates"]:
            if p["predecessor"] not in nodes:
                problems.append(f"node {nid} in_predicate predecessor {p['predecessor']} missing")

    # 3. parallel_with must be mutual
    for nid, n in nodes.items():
        for peer in n.get("parallel_with") or []:
            if peer not in nodes:
                problems.append(f"node {nid} parallel_with {peer} missing")
            elif nid not in (nodes[peer].get("parallel_with") or []):
                problems.append(f"parallel_with not mutual: {nid} <-> {peer}")

    # 5. Malformed agents entries (defense-in-depth for hand-edited state —
    #    keeps `validate` from reporting OK for a graph that would
    #    AttributeError in `shctx graph`). Bash numbers this check 5 but
    #    runs it BEFORE the cycle check; order preserved.
    for nid, n in nodes.items():
        for a in n.get("agents") or []:
            if isinstance(a, str):
                continue
            if isinstance(a, dict) and a.get("role"):
                continue
            problems.append(f"node {nid} has malformed agents entry: {a!r}")

    # 4. Acyclic check (Kahn): topological sort by in_predicates
    remaining = {nid: {p["predecessor"] for p in n["in_predicates"]} for nid, n in nodes.items()}
    while True:
        ready = [nid for nid, preds in remaining.items() if not preds]
        if not ready:
            break
        for r in ready:
            del remaining[r]
            for preds in remaining.values():
                preds.discard(r)
    if remaining:
        problems.append(f"cycle detected involving nodes: {sorted(remaining.keys())}")

    if problems:
        typer.echo("VALIDATION FAILED:")
        for p in problems:
            typer.echo("  ✗ " + p)
        return 1
    typer.echo(f"validate: OK  ({len(nodes)} nodes, {len(edges)} edges, topological order valid)")
    return 0


# --------------------------------------------------------------------------
# hash
# --------------------------------------------------------------------------
def _cmd_hash(rest: list[str]) -> int:
    """``plan hash <plan.md>`` — echo ``sha256:<hex>`` of the plan bytes.

    Args:
        rest: Every token after ``hash``.

    Returns:
        0 on success; 2 on a usage error (bash parity).
    """
    plan = rest[0] if rest else ""
    if not plan or not os.path.isfile(plan):
        typer.echo("ERROR: usage: shctx plan hash <plan.md>", err=True)
        return 2
    typer.echo(_sha256_file(plan))
    return 0


# --------------------------------------------------------------------------
# record-critique
# --------------------------------------------------------------------------
def _parse_two_token_flags(rest: list[str], spec: dict[str, str]) -> tuple[dict[str, str], int | None]:
    """Parse bash's two-token AND equals-form flag loop.

    Args:
        rest: The raw token list.
        spec: Maps each accepted ``--flag`` to its result key. A flag
            whose result key is ``""`` is boolean (no value consumed).

    Returns:
        ``(values, early_exit)`` — ``early_exit`` is 0 when ``-h``/
        ``--help`` was hit (usage already printed), 2 on an unknown arg
        (error already printed), else None.
    """
    values: dict[str, str] = {}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in ("-h", "--help"):
            typer.echo(_USAGE)
            return values, 0
        matched = False
        for flag, key in spec.items():
            if tok == flag:
                if key == "":
                    values[flag.lstrip("-")] = "1"
                    i += 1
                else:
                    # Deviation 3 (module docstring): a dangling two-token
                    # flag takes "" and falls into the required-check.
                    values[key] = rest[i + 1] if i + 1 < len(rest) else ""
                    i += 2
                matched = True
                break
            if key != "" and tok.startswith(flag + "="):
                values[key] = tok[len(flag) + 1 :]
                i += 1
                matched = True
                break
        if not matched:
            typer.echo(f"ERROR: unknown arg: {tok}", err=True)
            return values, 2
    return values, None


def _cmd_record_critique(rest: list[str]) -> int:
    """``plan record-critique --plan P --pre H --verdict V [...]``.

    Args:
        rest: Every token after ``record-critique``.

    Returns:
        The process exit code (0 success, 2 usage error, 1 bad int —
        bash parity; see documented deviation 2).
    """
    values, early = _parse_two_token_flags(
        rest,
        {"--plan": "plan", "--pre": "pre", "--verdict": "verdict", "--iterations": "iterations", "--findings": "findings"},
    )
    if early is not None:
        return early
    plan = values.get("plan", "")
    pre = values.get("pre", "")
    verdict = values.get("verdict", "")
    iterations = values.get("iterations", "1")
    findings = values.get("findings", "0")

    if not plan or not os.path.isfile(plan):
        typer.echo("ERROR: --plan <path> required and must exist", err=True)
        return 2
    if not pre:
        typer.echo(
            "ERROR: --pre <hash> required (capture with 'shctx plan hash' BEFORE the critic pass)", err=True
        )
        return 2
    if not verdict:
        typer.echo("ERROR: --verdict <PASS|...> required", err=True)
        return 2

    try:
        iterations_i = int(iterations)
        findings_i = int(findings)
    except ValueError:
        typer.echo("ERROR: --iterations/--findings must be integers", err=True)
        return 1

    proof = _proof_path(plan)
    sprint = current_sprint()
    post = _sha256_file(plan)
    if not pre.startswith("sha256:"):
        pre = "sha256:" + pre
    edited = pre != post
    doc = {
        "schema_version": 1,
        "sprint": sprint,
        "plan_path": plan,
        "pre_critic_hash": pre,
        "post_critic_hash": post,
        "edited": edited,
        "critic": {"verdict": verdict, "iterations": iterations_i, "findings": findings_i},
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(proof, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    typer.echo(f"critic-proof written: {proof}")
    typer.echo(f"  edited={str(edited).lower()}  verdict={verdict}  iterations={iterations_i}  findings={findings_i}")
    if not edited:
        typer.echo(
            "  WARNING: pre == post — plan NOT edited after the critic pass; "
            "'shctx plan verify' will FAIL (PLAN-UNEDITED)"
        )
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------
def _cmd_verify(rest: list[str]) -> int:
    """``plan verify [--plan P] [--quiet]`` — the critic-proof gate.

    Args:
        rest: Every token after ``verify``.

    Returns:
        0 when the proof is valid; 1 with a named failure code; 2 on an
        unknown arg (bash parity).
    """
    values, early = _parse_two_token_flags(rest, {"--plan": "plan", "--quiet": ""})
    if early is not None:
        return early
    plan = values.get("plan", "")
    quiet = values.get("quiet") == "1"

    if plan:
        proof = _proof_path(plan)
    else:
        plans_dir = cfg_get("plans") or ".artifacts/docs/plans"
        if not plans_dir.startswith("/"):
            plans_dir = f"{resolve_repo_root()}/{plans_dir}"
        try:
            matches = sorted(
                os.path.join(plans_dir, name)
                for name in os.listdir(plans_dir)
                if name.endswith(".critic-proof.json")
            )
        except OSError:
            matches = []
        if len(matches) == 1:
            proof = matches[0]
        else:
            typer.echo(
                f"CRITIC-PROOF-MISSING: pass --plan <path> (found {len(matches)} proof file(s) under {plans_dir})",
                err=True,
            )
            return 1

    # ---- transliterated from cmd_plan.sh's verify heredoc (stdout) -------
    if not os.path.isfile(proof):
        typer.echo(f"CRITIC-PROOF-MISSING: {proof}")
        return 1
    try:
        with open(proof, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - bash catches bare Exception too
        typer.echo(f"CRITIC-PROOF-MISSING: unparseable proof {proof} ({exc})")
        return 1
    proved_plan = d.get("plan_path", "")
    pre = d.get("pre_critic_hash", "")
    post = d.get("post_critic_hash", "")
    crit = d.get("critic", {}) or {}
    verdict = str(crit.get("verdict", "")).upper()
    iterations = int(crit.get("iterations", 0) or 0)
    if not d.get("edited") or not pre or pre == post:
        typer.echo(f"PLAN-UNEDITED: pre==post or edited=false ({proof}) — plan not revised after the critic pass")
        return 1
    if not proved_plan or not os.path.isfile(proved_plan):
        typer.echo(f"CRITIC-PROOF-STALE: plan_path missing on disk: {proved_plan}")
        return 1
    cur = _sha256_file(proved_plan)
    if cur != post:
        typer.echo(
            f"CRITIC-PROOF-STALE: post_critic_hash != current plan bytes\n  proof: {post}\n  plan:  {cur}"
        )
        return 1
    if not verdict or verdict in ("FAIL", "RED", "REJECT", "REJECTED") or iterations < 1:
        typer.echo(f"PLAN-UNCRITIQUED: verdict={verdict or 'MISSING'} iterations={iterations}")
        return 1
    if not quiet:
        typer.echo(
            f"OK: critic-proof valid — edited=true, verdict={verdict}, iterations={iterations}, "
            f"hash-tied to {os.path.basename(proved_plan)}"
        )
    return 0


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> int:
    """Reproduce ``cmd_plan.sh``'s ``case "$sub"`` dispatch byte-for-byte.

    Args:
        argv: Every raw token after ``plan`` on the command line.

    Returns:
        The process exit code.
    """
    sub = argv[0] if argv else ""
    rest = argv[1:]
    if sub in ("", "-h", "--help"):
        typer.echo(_USAGE)
        return 0
    if sub == "extract":
        return _cmd_extract(rest)
    if sub == "topology":
        return _cmd_topology(rest)
    if sub == "validate":
        return _cmd_validate(rest)
    if sub == "hash":
        return _cmd_hash(rest)
    if sub == "record-critique":
        return _cmd_record_critique(rest)
    if sub == "verify":
        return _cmd_verify(rest)
    typer.echo(f"ERROR: unknown subcommand: {sub}", err=True)
    typer.echo(_USAGE, err=True)
    return 1


@app.callback(invoke_without_command=True, context_settings={"ignore_unknown_options": True, "help_option_names": []})
def plan(
    args: list[str] = typer.Argument(
        None,
        help="Subcommand + args: extract | topology | validate | hash | record-critique | verify.",
    ),
) -> None:
    """Stage Graph extraction + critic-proof gate — native ``shctx plan`` port.

    See the module docstring for why this is ONE variadic callback rather
    than six ``@app.command()``s (bash's usage-on-bare-invocation,
    stderr-usage-on-unknown-subcommand, and per-arm flag/exit-code
    contracts).

    Args:
        args: Every token after ``plan``, captured raw (``--help`` and
            unknown options land here literally — ``help_option_names``
            is emptied and ``ignore_unknown_options`` is set).

    Raises:
        typer.Exit: Always, carrying :func:`_dispatch`'s exit code.
    """
    raise typer.Exit(code=_dispatch(list(args or [])))


__all__ = ["app"]
