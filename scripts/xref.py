#!/usr/bin/env python3
"""scripts/xref.py — dev-only cross-reference map of shepherd's prompt surface.

Companion to scripts/filetree.sh. NOT part of the shipped plugin; run by hand
by whoever is maintaining THIS repo: `python3 scripts/xref.py [--json]`.

Scans every file that participates in the plugin's behavior wiring (agents/,
commands/, skills/, hooks/, docs/, services/, CLAUDE.md) and extracts:

  - doctrine refs      doctrines/<slug>.md
  - reference refs     references/<slug>.md
  - agent refs         agents/<slug>.md, @<flock-name>, shepherd:<flock-name>
  - skill refs         skills/<dir>/, Skill(shepherd:<name>)
  - shctx subcommands  `shctx <cmd>` call sites
  - script refs        <name>.sh / <name>.py mentions

Prints (default) a markdown report of:
  1. shctx subcommands with ZERO call sites outside their own impl/tests (prune candidates)
  2. doctrines ranked by inbound reference count (0-inbound = fold/delete candidates)
  3. per-kind reverse-index totals
--json dumps the full graph to scripts/.xref.json (gitignored).
"""
import json
import os
import re
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

SCAN_DIRS = ["agents", "commands", "skills", "hooks", "docs", "services"]
SCAN_FILES = ["CLAUDE.md", "README.md"]
TEXT_EXT = {".md", ".sh", ".py", ".json", ".sql"}

PAT = {
    "doctrine": re.compile(r"doctrines/([a-z0-9._-]+?)\.md"),
    "reference": re.compile(r"references/([a-z0-9._-]+?)\.md"),
    "agent_path": re.compile(r"agents/([a-z0-9._-]+?)\.(?:md|reference\.md)"),
    "agent_at": re.compile(
        r"@(shepherd|planter|engineer|critic|coder|auditor|worker|discovery|conductor)\b"
    ),
    "command": re.compile(r"commands/([a-z0-9._-]+?)\.md"),
    "shctx": re.compile(r"\bshctx\s+([a-z][a-z0-9-]*)"),
    "skill_dir": re.compile(r"skills/([a-z0-9_-]+)/"),
    "script": re.compile(r"\b(cmd_[a-z0-9_-]+\.sh|[a-z0-9_-]+\.(?:sh|py))\b"),
}
SHCTX_NONCMD = {"help", "h"}  # dispatcher words, not subcommands


def files_to_scan():
    out = []
    for d in SCAN_DIRS:
        for root, dirs, names in os.walk(d):
            dirs[:] = [x for x in dirs if x not in {".git", "node_modules"}]
            for n in names:
                p = os.path.join(root, n)
                if os.path.splitext(n)[1] in TEXT_EXT:
                    out.append(p)
    out.extend(f for f in SCAN_FILES if os.path.exists(f))
    return sorted(out)


def scan():
    graph = {}
    for path in files_to_scan():
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        refs = {}
        # consumer-project extension forms are not plugin refs
        scrubbed = re.sub(r"[\w.]*\.claude/doctrines/[a-z0-9._-]+\.md", "", text)
        scrubbed = re.sub(r"project_doctrines/[a-z0-9._-]+\.md", "", scrubbed)
        for kind, pat in PAT.items():
            hits = sorted(set(pat.findall(scrubbed)))
            if kind == "shctx":
                hits = [h for h in hits if h not in SHCTX_NONCMD]
            if hits:
                refs[kind] = hits
        graph[path] = refs
    return graph


def reverse(graph, kind):
    rev = defaultdict(list)
    for path, refs in graph.items():
        for target in refs.get(kind, []):
            rev[target].append(path)
    return rev


def is_own_surface(cmd, path):
    """True when `path` is the command's own impl, its test, or the dispatcher/usage."""
    base = os.path.basename(path)
    return (
        base == f"cmd_{cmd}.sh"
        or base == f"test_cmd_{cmd}.sh"
        or base == f"test_{cmd}.sh"
        or base in {"shctx", "_lib.sh", "_assert.sh", "_setup.sh", "run.sh"}
        or path.startswith("skills/context/tests/")
    )


def main():
    graph = scan()
    if "--json" in sys.argv:
        with open("scripts/.xref.json", "w", encoding="utf-8") as fh:
            json.dump(graph, fh, indent=1, sort_keys=True)
        print("wrote scripts/.xref.json")

    # 1. shctx prune candidates
    impl_cmds = sorted(
        f[len("skills/context/scripts/cmd_") : -3]
        for f in graph
        if f.startswith("skills/context/scripts/cmd_") and f.endswith(".sh")
    )
    rev_shctx = reverse(graph, "shctx")
    print("\n## shctx subcommands by external call sites\n")
    print("| cmd | external refs | referenced by |")
    print("|---|---|---|")
    rows = []
    for cmd in impl_cmds:
        callers = [p for p in rev_shctx.get(cmd, []) if not is_own_surface(cmd, p)]
        rows.append((len(callers), cmd, callers))
    for n, cmd, callers in sorted(rows):
        sample = ", ".join(sorted({os.path.dirname(c) or c for c in callers})[:4])
        print(f"| {cmd} | {n} | {sample} |")

    # 2. dangling refs — any cited doctrine/reference/command/agent path that no
    # longer exists on disk. Primary post-restructure gate (v6.2.8+).
    print("\n## dangling refs (cited path missing on disk)\n")
    dangling = 0
    resolvers = {
        "doctrine": lambda s: [f"skills/shepherd/doctrines/{s}.md"],
        "command": lambda s: [f"commands/{s}.md"],
        "agent_path": lambda s: [f"agents/{s}.md", f"skills/shepherd/agents/{s}.reference.md"],
        "reference": lambda s: [
            f"skills/shepherd/references/{s}.md",
            f"skills/context/references/{s}.md",
            f"skills/harness/references/{s}.md",
        ],
    }
    for path, refs in sorted(graph.items()):
        if path.startswith("docs/specs/"):
            continue  # dated planning artifacts cite historical paths by design
        for kind, resolve in resolvers.items():
            for slug in refs.get(kind, []):
                if not any(os.path.exists(c) for c in resolve(slug)):
                    print(f"- {path}: {kind} `{slug}` → no candidate exists")
                    dangling += 1
    print(f"\ndangling refs: {dangling}")

    # 3. doctrines by inbound refs (skipped once the doctrine dir is dissolved)
    doc_dir = "skills/shepherd/doctrines"
    if not os.path.isdir(doc_dir):
        print("\n## doctrines: directory absent (post-v6.2.8 layout) — section skipped")
        return
    rev_doc = reverse(graph, "doctrine")
    print("\n## doctrines by inbound reference count (excluding self + doctrine dir)\n")
    print("| doctrine | inbound | from-hooks | citers |")
    print("|---|---|---|---|")
    slugs = sorted(
        os.path.splitext(n)[0]
        for n in os.listdir(doc_dir)
        if n.endswith(".md") and not n.startswith("_")
    )
    drows = []
    for slug in slugs:
        citers = [
            p
            for p in rev_doc.get(slug, [])
            if os.path.basename(p) != f"{slug}.md"
            and not p.startswith(f"{doc_dir}/_candidates")
        ]
        nonself = [c for c in citers if not c.startswith(doc_dir)]
        hooks = [c for c in citers if c.startswith("hooks/")]
        drows.append((len(nonself), slug, len(hooks), nonself))
    for n, slug, nh, citers in sorted(drows):
        kinds = ", ".join(sorted({c.split("/")[0] for c in citers})[:5])
        print(f"| {slug} | {n} | {nh} | {kinds} |")

    zero = [slug for n, slug, _, _ in drows if n == 0]
    print(f"\nzero-inbound doctrines: {len(zero)} / {len(slugs)}")


if __name__ == "__main__":
    main()
