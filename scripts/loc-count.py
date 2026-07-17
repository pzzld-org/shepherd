#!/usr/bin/env python3
# scripts/loc-count.py — canonical deterministic wave-gate LOC counter (GH #216).
#
# WHY: the wave-gate production-LOC count was re-derived per sprint and broke
# twice before converging (v0.3.8-dev.5): (1) a single-cfg(test)-span assumption
# made a file with a helper test module *plus* a `#[cfg(test)] mod tests` read 0;
# (2) a regex that only matched `#[cfg(test)]` missed `#[cfg(all(test, ...))]`,
# over-counting a test span as production. LOC is DETERMINISTIC — same diff, same
# number — so it must never be counted in latent space again. This is the single
# source of truth the wave routine (skills/shepherd/references/wave-routine.md
# §Root gate) and pipeline.md §Gates call.
#
# WHAT IT COUNTS: net *production Rust* LOC of the working tree vs <base_ref>.
# Added-minus-removed `.rs` lines that lie OUTSIDE a brace-matched cfg(test) span,
# skipping any file under a `tests/` directory entirely. cfg(test) spans covered:
#   #[cfg(test)]                      — the classic unit-test module
#   #[cfg(all(test, feature = "x"))]  — the W2 bug: `test` inside all(...)
#   #[cfg(any(test, ...))]            — same, inside any(...)
# and NOT treated as a test span (production, correctly counted):
#   #[cfg(not(test))]                 — negated: this IS production
#   #[cfg_attr(test, ...)]            — conditional attr, not a body gate
# Multiple spans per file are all detected (the W1 bug). Brace matching is
# comment- and string/char/raw-string-literal aware so a `{`/`}`/`;` inside a
# literal never mis-bounds a span.
#
# USAGE: loc-count.py <base_ref> [repo_path]
#   Compares <base_ref> to the WORKING TREE (the wave use-case: "+N LOC since the
#   wave's base commit"). New-side content is read from the worktree; old-side
#   from `git show <base_ref>:<path>`. Ranges (A..B) are not the supported mode.
#   repo_path defaults to the current directory.
#
# OUTPUT (stdout):
#   +<added>/-<removed>  <path>     (one per changed production file, sorted)
#   TOTAL: +<A>/-<D> (net <N>)
# Exit 0 on success; exit 2 on a git/usage error.

import re
import subprocess
import sys
from pathlib import PurePosixPath

CFG_ATTR_RE = re.compile(r"^\s*#!?\[\s*cfg\s*\((?P<pred>.*)\)\s*\]\s*(//.*)?$")


def die(msg: str, code: int = 2) -> "None":
    sys.stderr.write(f"loc-count: {msg}\n")
    sys.exit(code)


def git(repo: str, *args: str, allow_fail: bool = False) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if allow_fail:
            return ""
        die(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def is_test_predicate(pred: str) -> bool:
    """True if a cfg(...) predicate gates its item to test builds.

    `test` present as a token and NOT confined to a not(...) group. Strips
    not(...) groups first so `#[cfg(not(test))]` is production, then looks for a
    bare `test` token (matches `test`, `all(test, ...)`, `any(..., test)`).
    """
    stripped = re.sub(r"not\s*\([^()]*\)", "", pred)
    return re.search(r"\btest\b", stripped) is not None


def test_span_lines(content: str) -> "set[int]":
    """Return the 1-based line numbers inside every cfg(test) span in `content`.

    A span runs from the cfg(test) attribute line through the closing `}` of the
    item it gates (or the terminating `;` for a braceless item such as
    `#[cfg(test)] use super::*;`). Brace/`;` scanning is literal-aware.
    """
    lines = content.splitlines()
    # Precompute the char offset at which each line starts, for offset->line.
    starts = []
    off = 0
    for ln in lines:
        starts.append(off)
        off += len(ln) + 1  # +1 for the stripped newline
    text = "\n".join(lines)
    n = len(text)

    def line_of(pos: int) -> int:
        # Binary-search-free: starts is small per file; linear is fine, but use
        # a manual walk with bisect for larger files.
        import bisect

        return bisect.bisect_right(starts, pos)  # 1-based

    in_span: "set[int]" = set()
    i = 0
    line_idx = 0  # 0-based index into `lines`
    while line_idx < len(lines):
        m = CFG_ATTR_RE.match(lines[line_idx])
        if not m or not is_test_predicate(m.group("pred")):
            line_idx += 1
            continue
        attr_line = line_idx + 1  # 1-based
        # Scan from just after this attribute line to find the item terminator.
        scan_pos = starts[line_idx] + len(lines[line_idx])
        end_pos = _scan_item_end(text, scan_pos, n)
        end_line = line_of(end_pos) if end_pos < n else len(lines)
        for l in range(attr_line, end_line + 1):
            in_span.add(l)
        # Continue scanning after the span's end line (handles multiple spans).
        line_idx = end_line
    return in_span


def _scan_item_end(text: str, pos: int, n: int) -> int:
    """From char offset `pos`, return the offset of the char that ends the item:
    the matching `}` of its body, or a top-level `;` for a braceless item.
    Skips // and /* */ comments and "..."/ '.' / r#"..."# literals."""
    depth = 0
    found_brace = False
    while pos < n:
        c = text[pos]
        # line comment
        if c == "/" and pos + 1 < n and text[pos + 1] == "/":
            nl = text.find("\n", pos)
            pos = n if nl == -1 else nl
            continue
        # block comment
        if c == "/" and pos + 1 < n and text[pos + 1] == "*":
            end = text.find("*/", pos + 2)
            pos = n if end == -1 else end + 2
            continue
        # raw string r"..." or r#"..."# (and br"...")
        if c in "rb" and pos + 1 < n:
            j = pos
            if text[j] == "b" and j + 1 < n and text[j + 1] == "r":
                j += 1
            if text[j] == "r":
                k = j + 1
                hashes = 0
                while k < n and text[k] == "#":
                    hashes += 1
                    k += 1
                if k < n and text[k] == '"':
                    close = '"' + "#" * hashes
                    end = text.find(close, k + 1)
                    pos = n if end == -1 else end + len(close)
                    continue
        # normal string
        if c == '"':
            pos += 1
            while pos < n:
                if text[pos] == "\\":
                    pos += 2
                    continue
                if text[pos] == '"':
                    pos += 1
                    break
                pos += 1
            continue
        # char literal '{' / '}' / '\'' — only treat as a literal when it looks
        # like one (lifetimes like 'a are not closed by a quote soon after).
        if c == "'":
            if pos + 2 < n and text[pos + 1] == "\\":
                # escaped char: '\n' '\'' '\\' etc.
                end = text.find("'", pos + 2)
                if end != -1 and end - pos <= 4:
                    pos = end + 1
                    continue
            elif pos + 2 < n and text[pos + 2] == "'":
                pos += 3
                continue
            pos += 1
            continue
        if c == "{":
            depth += 1
            found_brace = True
        elif c == "}":
            depth -= 1
            if found_brace and depth == 0:
                return pos
        elif c == ";" and depth == 0 and not found_brace:
            return pos
        pos += 1
    return n - 1 if n > 0 else 0


def parse_diff(diff: str):
    """Yield (old_path, new_path, added_new_lines:set[int], removed_old_lines:set[int]).

    Both sides are tracked so a DELETION (`+++ /dev/null` → new_path None, removed
    lines keyed to the old path) and a RENAME-with-edit (`--- a/old` ≠ `+++ b/new`,
    so the base blob is read at the OLD path) are counted correctly — dropping the
    old side silently zeroed a deleted file and mis-scoped a renamed file's spans.
    """
    files = []          # one dict per `diff --git` stanza, in order
    cur = None
    new_lineno = old_lineno = 0
    hunk_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            cur = {"old": None, "new": None, "added": set(), "removed": set()}
            files.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("--- "):
            p = line[4:]
            cur["old"] = None if p == "/dev/null" else (p[2:] if p.startswith("a/") else p)
            continue
        if line.startswith("+++ "):
            p = line[4:]
            cur["new"] = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
            continue
        if line.startswith("@@"):
            m = hunk_re.match(line)
            if m:
                old_lineno = int(m.group(1))
                new_lineno = int(m.group(2))
            continue
        if line.startswith("+"):
            cur["added"].add(new_lineno)
            new_lineno += 1
        elif line.startswith("-"):
            cur["removed"].add(old_lineno)
            old_lineno += 1
        else:  # context (shouldn't appear with -U0) advances both
            new_lineno += 1
            old_lineno += 1
    for c in files:
        yield c["old"], c["new"], c["added"], c["removed"]


def under_tests_dir(path: str) -> bool:
    return "tests" in PurePosixPath(path).parts[:-1]


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("-h", "--help")]
    if len(sys.argv) == 1 or any(a in ("-h", "--help") for a in sys.argv[1:]):
        print("Usage: loc-count.py <base_ref> [repo_path]")
        return 0 if len(sys.argv) > 1 else 2
    base_ref = args[0]
    repo = args[1] if len(args) > 1 else "."

    diff = git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", base_ref, "--", "*.rs")

    entries = list(parse_diff(diff))  # (old_path, new_path, added, removed)
    seen = {p for o, n, _, _ in entries for p in (o, n) if p}
    # loc-count runs in the root gate BEFORE the wave commit, so a coder's new
    # files are still untracked — and `git diff <base>` omits untracked files.
    # Count each untracked .rs file as wholly added, else the wave undercounts.
    untracked = git(
        repo, "ls-files", "--others", "--exclude-standard", "--", "*.rs"
    ).splitlines()
    for path in untracked:
        path = path.strip()
        if not path or path in seen:
            continue
        try:
            with open(PurePosixPath(repo) / path, "r", errors="replace") as fh:
                n_lines = len(fh.read().splitlines())
        except OSError:
            continue
        entries.append((None, path, set(range(1, n_lines + 1)), set()))

    total_add = total_del = 0
    rows = []
    for old_path, new_path, added, removed in entries:
        disp = new_path or old_path  # a deletion has no new path
        if disp is None:
            continue
        # Skip a file living under tests/ on EITHER side of a move.
        if under_tests_dir(disp) or (old_path and under_tests_dir(old_path)):
            continue
        # New content = worktree file at the NEW path (empty for a deletion);
        # old content = the base_ref blob at the OLD path (empty for an add).
        new_content = ""
        if new_path:
            try:
                with open(PurePosixPath(repo) / new_path, "r", errors="replace") as fh:
                    new_content = fh.read()
            except OSError:
                new_content = ""
        old_content = (
            git(repo, "show", f"{base_ref}:{old_path}", allow_fail=True) if old_path else ""
        )
        new_spans = test_span_lines(new_content)
        old_spans = test_span_lines(old_content)
        a = sum(1 for ln in added if ln not in new_spans)
        d = sum(1 for ln in removed if ln not in old_spans)
        if a == 0 and d == 0:
            continue
        rows.append((disp, a, d))
        total_add += a
        total_del += d

    for path, a, d in sorted(rows):
        print(f"+{a}/-{d}  {path}")
    print(f"TOTAL: +{total_add}/-{total_del} (net {total_add - total_del})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
