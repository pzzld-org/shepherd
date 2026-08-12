#!/usr/bin/env python3
# shepherd — workflow_model_lint.py (v6.4.2, #255 enforcement half)
#
# Best-effort JS-lite static scan for Dynamic Workflow scripts: finds every
# top-level `agent(prompt[, opts])` call and checks it against the SAME
# dispatch law `dispatch_guard.sh` enforces for `Agent()` — every flock
# dispatch pins BOTH an explicit model AND a `shepherd:<role>` type. Invoked
# by hooks/scripts/workflow_model_guard.sh; not a general JS parser.
#
# #178 shipped the weaker law: `model:` OR `agentType:` — satisfying EITHER
# passed. #255's field incident is exactly the gap that check let through: a
# Dynamic Workflow script whose agent() calls carried `agentType:
# "shepherd:<role>"` with no `model:` passed clean, and every one of 16
# deep-audit subagents it fanned out ran on the inherited main-loop model
# (opus, xhigh) instead of the mandated sonnet. `skills/shepherd/SKILL.md
# §Dispatch law` now states the two-spelling law explicitly
# (`DISPATCH-MISSING-SUBAGENT-TYPE`/`DISPATCH-MODEL-UNPINNED` either way,
# plus `WORKFLOW-OFF-FLOCK` for Workflow's own agentType check); this file is
# the mechanical half — BOTH laws are checked independently per call, so a
# call can trip either, both, or neither.
#
# Approach: mask every string/template literal and comment to same-length
# blanks (boundary quote chars kept) BEFORE any scanning, so a prompt that
# merely mentions "model:" or `agentType: "general-purpose"` in prose can
# never be mistaken for a real opts key. Paren/brace depth is then tracked on
# the masked text only, which keeps character offsets IDENTICAL to the
# original source (needed for line numbers, excerpts, AND — new in #255 —
# reading a literal agentType string's actual VALUE back out of the
# unmasked original at the same offsets; see `_extract_top_level_value`).
# This is what keeps the scan string-content-blind for detecting keys while
# still letting it read a literal's content once a real key is found.
#
# Usage: script text on stdin; one line of JSON on stdout:
#   {"total_agent_calls": N, "checked_calls": N, "violation_count": N,
#    "violations": [{"line": L, "code": "...", "reason": "...", "excerpt": "..."}],
#    "override": bool, "lines_text": "  line L: CODE — reason — excerpt\n..."}
#
# A single `agent()` call can produce MULTIPLE violation entries — the
# model law and the agentType law are independent, so a call pinning one but
# not the other trips exactly one code, and a call pinning neither trips two.
# Five distinct shapes, each its own `code` (never collapsed into one another):
#
#   DISPATCH-MODEL-UNPINNED         no top-level `model:` in a literal opts
#                                    object, or no opts argument at all.
#   DISPATCH-MISSING-SUBAGENT-TYPE  no top-level `agentType:` in a literal
#                                    opts object (or its value is the empty
#                                    string), or no opts argument at all.
#   WORKFLOW-OFF-FLOCK              `agentType:` IS a literal string but does
#                                    not start with `shepherd:` — e.g.
#                                    `agentType: "general-purpose"`. The
#                                    exact shape #255's dispatch law names.
#   WORKFLOW-AGENTTYPE-UNVERIFIABLE `agentType:` is present at the top level
#                                    but its value is NOT a literal string
#                                    (a variable, template literal, function
#                                    call, …) — cannot verify the `shepherd:`
#                                    prefix statically. Flagged, not guessed;
#                                    NEVER reported as WORKFLOW-OFF-FLOCK,
#                                    which is reserved for a verified string.
#   WORKFLOW-MODEL-PIN-UNVERIFIABLE the opts ARGUMENT ITSELF is not a literal
#                                    object (a variable, spread, function
#                                    call, …) — neither key can be checked at
#                                    all. This is #178's original shape (c),
#                                    unchanged and never collapsed into the
#                                    two split codes above.
#
# A same-named field nested inside a value (e.g. `agentType` inside
# `opts.schema`) does NOT count as top-level — see `_top_level_only`.
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
MODEL_KEY_RE = re.compile(r"\bmodel\s*:")
AGENTTYPE_KEY_RE = re.compile(r"\bagentType\s*:")
OVERRIDE_RE = re.compile(r"^[ \t]*//[ \t]*shepherd:model-pin-override\b", re.MULTILINE)
FLOCK_PREFIX = "shepherd:"
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
    masquerade as a top-level opts key. Length- and offset-preserving, same
    contract as `_mask`: output[i] describes input[i], nothing shifts."""
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


def _extract_top_level_value(top_masked, key_re, original_src, abs_base):
    """Locate `key_re` (a top-level `model:`/`agentType:`) inside
    `top_masked` — itself string/comment-masked AND depth-blanked, so the
    search that FINDS the key is fully string-content-blind — then return
    the ORIGINAL, UNMASKED source text of its value (trimmed), read out of
    `original_src` at the same character offsets.

    This is safe specifically because `_mask`/`_top_level_only` are both
    length- and offset-preserving (see their docstrings): position p in
    `top_masked` describes the exact same source character as position
    `abs_base + p` in `original_src`. The masked text is only ever used to
    decide WHERE the value starts and ends (a comma at masked-depth 1 can
    only be a real top-level comma — a comma inside a nested value or a
    string is already blanked away); the VALUE ITSELF always comes from the
    real, unmasked source, which is what lets a literal like
    `agentType: "shepherd:coder"` be read for its actual content rather than
    merely detected as "present" (#255 — #178's scan never needed to do
    this, since presence alone was the entire check).

    Returns None if the key is absent at the top level. Returns "" if the
    key is present but its value is blank (e.g. `agentType: ,` or a
    trailing `agentType:` with nothing after it) — callers treat that the
    same as "missing" (an empty pin authorizes nothing)."""
    m = key_re.search(top_masked)
    if m is None:
        return None
    val_start = m.end()
    comma_idx = top_masked.find(",", val_start)
    val_end = len(top_masked) if comma_idx == -1 else comma_idx
    segment = top_masked[val_start:val_end]
    trimmed_len = len(segment.strip())
    if trimmed_len == 0:
        return ""
    lead = len(segment) - len(segment.lstrip())
    abs_start = abs_base + val_start + lead
    abs_end = abs_start + trimmed_len
    return original_src[abs_start:abs_end]


def _is_string_literal(text):
    """True if `text` is a single '...'/"..." token (boundary quotes kept
    identical on both ends) — the same "starts with a quote" heuristic
    `_mask` already relies on elsewhere in this file. Deliberately excludes
    backtick template literals: a template CAN be fully static (no `${`),
    but proving that in a best-effort scanner isn't worth the false
    confidence — treated as unverifiable like any other non-literal, never
    guessed at."""
    return len(text) >= 2 and text[0] in ("'", '"') and text[-1] == text[0]


def _check_object_opts(opts_body_masked, abs_base, src):
    """`opts_body_masked` is the masked text of a `{...}` opts literal
    (leading whitespace before the `{` is fine — see `_top_level_only`);
    `abs_base` is its absolute offset into `src`. Returns a list of
    `(code, reason)` pairs — the model law and the agentType law are
    checked independently, so a call missing both pins produces two
    entries, not one (#255 — the old OR-check reported at most one)."""
    top = _top_level_only(opts_body_masked)
    out = []

    model_val = _extract_top_level_value(top, MODEL_KEY_RE, src, abs_base)
    if model_val is None:
        out.append((
            "DISPATCH-MODEL-UNPINNED",
            "opts has no top-level model: — Workflow agent() bypasses [models] entirely, "
            "so every call must pin one explicitly",
        ))

    at_val = _extract_top_level_value(top, AGENTTYPE_KEY_RE, src, abs_base)
    at_literal = at_val[1:-1] if at_val and _is_string_literal(at_val) else None
    if at_val is None or at_val == "" or at_literal == "":
        # Absent key, blank value (`agentType: ,`), AND an explicit empty
        # string literal (`agentType: ""`) all collapse to the same law —
        # an empty pin authorizes nothing, same as no pin at all.
        out.append((
            "DISPATCH-MISSING-SUBAGENT-TYPE",
            "opts has no top-level agentType: (or it is empty) — every flock dispatch "
            "must pin an explicit shepherd:<role>",
        ))
    elif at_literal is not None:
        if not at_literal.startswith(FLOCK_PREFIX):
            out.append((
                "WORKFLOW-OFF-FLOCK",
                'agentType: %s is not shepherd:<role> — off-flock dispatch' % at_val,
            ))
    else:
        out.append((
            "WORKFLOW-AGENTTYPE-UNVERIFIABLE",
            "agentType value is not a literal string — cannot verify the shepherd: "
            "prefix statically",
        ))
    return out


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
            call_violations = [
                ("DISPATCH-MODEL-UNPINNED", "no opts argument — agent() call has no model: pin"),
                ("DISPATCH-MISSING-SUBAGENT-TYPE", "no opts argument — agent() call has no agentType: pin"),
            ]
        else:
            arg_start, arg_end = spans[1]
            abs_base = open_idx + 1 + arg_start
            opts_masked = inner_masked[arg_start:arg_end]
            if not opts_masked.strip().startswith("{"):
                call_violations = [(
                    "WORKFLOW-MODEL-PIN-UNVERIFIABLE",
                    "opts argument is not a literal object — cannot verify statically",
                )]
            else:
                call_violations = _check_object_opts(opts_masked, abs_base, src)

        for code, reason in call_violations:
            violations.append({"line": line, "code": code, "reason": reason, "excerpt": excerpt})
    return total, checked, violations


def main():
    src = sys.stdin.read()
    total, checked, violations = scan(src)
    override = bool(OVERRIDE_RE.search(src))
    lines = [
        "  line {line}: {code} — {reason} — {excerpt}".format(**v)
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
