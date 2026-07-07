#!/usr/bin/env python3
# shepherd — workflow_model_lint.py (v6.2.9, #178)
#
# Best-effort JS-lite static scan for Dynamic Workflow scripts: finds every
# top-level `agent(prompt[, opts])` call and reports one whose `opts` carries
# neither a `model:` nor an `agentType:` key — the shape that silently
# inherits the main-loop model (the platform's own stated default; shepherd's
# operator law requires an explicit pin instead, [models] table in
# .claude/shepherd.toml, docs/configuration.md §models). Invoked by
# hooks/scripts/workflow_model_guard.sh; not a general JS parser.
#
# Approach: mask every string/template literal and comment to same-length
# blanks (boundary quote chars kept) BEFORE any scanning, so a prompt that
# merely mentions "model:" in prose can never be mistaken for a real opts
# key. Paren/brace depth is then tracked on the masked text only, which
# keeps character offsets identical to the original source (needed for line
# numbers and excerpts) while making the scan string-content-blind.
#
# Usage: script text on stdin; one line of JSON on stdout:
#   {"total_agent_calls": N, "checked_calls": N, "violation_count": N,
#    "violations": [{"line": L, "reason": "...", "excerpt": "..."}],
#    "override": bool, "lines_text": "  line L: reason — excerpt\n..."}
#
# A violation fires for THREE shapes, all reported the same way (the whole
# failure mode is silent/unverified inheritance, so ambiguity is not a
# reason to pass):
#   (a) `agent(prompt)` — no second (opts) argument at all.
#   (b) `agent(prompt, {..})` — opts is a literal object, but neither
#       `model:` nor `agentType:` appears at its TOP level (a same-named
#       field nested inside e.g. an opts.schema does NOT count).
#   (c) `agent(prompt, someExpr)` — opts is not a literal object (a
#       variable, spread, or function call) — cannot be verified statically.
#
# The operator override is a `// shepherd:model-pin-override` line comment
# anywhere in the submitted script (mirrors the brief-marker idiom
# hooks/scripts/dispatch_guard.sh already uses for `mode: self-contained` /
# `dispatcher: engineer-self-contained`) — reported in `override`, acted on
# by the bash guard, never silently swallowed here.

import json
import re
import sys

CALL_RE = re.compile(r"(?<![A-Za-z0-9_$.])agent\s*\(")
KEY_RE = re.compile(r"\b(model|agentType)\s*:")
OVERRIDE_RE = re.compile(r"^[ \t]*//[ \t]*shepherd:model-pin-override\b", re.MULTILINE)
EXCERPT_CAP = 160
VIOLATIONS_CAP = 10


def _mask(src):
    """Same-length copy of src with string/template-literal interiors and
    comments blanked to spaces (newlines preserved). String delimiters are
    kept so callers can still see "this argument starts with a quote"."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:j]))
            i = j
            continue
        if c in ("'", '"', "`"):
            quote = c
            j = i + 1
            buf = [quote]
            while j < n:
                cj = src[j]
                if cj == "\\" and j + 1 < n:
                    buf.append("\n" if cj == "\n" else " ")
                    buf.append("\n" if src[j + 1] == "\n" else " ")
                    j += 2
                    continue
                if cj == quote:
                    buf.append(quote)
                    j += 1
                    break
                buf.append("\n" if cj == "\n" else " ")
                j += 1
            out.append("".join(buf))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_matching_paren(masked, open_idx):
    depth = 1
    i = open_idx + 1
    n = len(masked)
    while i < n:
        c = masked[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_top_level_args(masked_args):
    """Split an already-masked argument-list string at top-level commas,
    respecting (), [], {} depth — a comma inside prompt text or a nested
    object/call is invisible here (masked) or depth-excluded (real code)."""
    spans = []
    depth = 0
    start = 0
    for i, c in enumerate(masked_args):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            spans.append((start, i))
            start = i + 1
    if spans or masked_args[start:].strip() != "":
        spans.append((start, len(masked_args)))
    return spans


def _top_level_only(obj_literal):
    """Blank every character not at brace/paren-depth 1 — the fields
    directly inside the outer object literal — so a same-named key nested
    inside a value (e.g. a JSON schema property called "model") cannot
    masquerade as a top-level opts key."""
    out = []
    depth = 0
    for ch in obj_literal:
        if ch in "{[(":
            depth += 1
            out.append(" ")
        elif ch in "}])":
            depth -= 1
            out.append(" ")
        elif depth == 1:
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


def scan(src):
    masked = _mask(src)
    violations = []
    total = 0
    checked = 0
    for m in CALL_RE.finditer(masked):
        open_idx = m.end() - 1
        close_idx = _find_matching_paren(masked, open_idx)
        if close_idx == -1:
            continue  # unterminated call in the submitted text — skip, fail open
        total += 1
        checked += 1
        inner_masked = masked[open_idx + 1 : close_idx]
        spans = _split_top_level_args(inner_masked)
        line = src.count("\n", 0, m.start()) + 1
        excerpt = re.sub(r"\s+", " ", src[m.start() : min(close_idx + 1, m.start() + EXCERPT_CAP)]).strip()

        if len(spans) < 2:
            violations.append({"line": line, "excerpt": excerpt, "reason": "no opts argument"})
            continue

        opts_masked = inner_masked[spans[1][0] : spans[1][1]].strip()
        if not opts_masked.startswith("{"):
            violations.append({
                "line": line, "excerpt": excerpt,
                "reason": "opts argument is not a literal object — cannot verify statically",
            })
            continue

        if KEY_RE.search(_top_level_only(opts_masked)):
            continue

        violations.append({
            "line": line, "excerpt": excerpt,
            "reason": "opts object has neither model: nor agentType:",
        })
    return total, checked, violations


def main():
    src = sys.stdin.read()
    total, checked, violations = scan(src)
    override = bool(OVERRIDE_RE.search(src))
    lines = [
        "  line {line}: {reason} — {excerpt}".format(**v)
        for v in violations[:VIOLATIONS_CAP]
    ]
    if len(violations) > VIOLATIONS_CAP:
        lines.append(f"  … and {len(violations) - VIOLATIONS_CAP} more")
    print(json.dumps({
        "total_agent_calls": total,
        "checked_calls": checked,
        "violation_count": len(violations),
        "violations": violations,
        "override": override,
        "lines_text": "\n".join(lines),
    }))


if __name__ == "__main__":
    main()
