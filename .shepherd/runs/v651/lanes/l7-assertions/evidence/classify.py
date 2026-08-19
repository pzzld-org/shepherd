#!/usr/bin/env python3
"""Ground-truth classifier for bare shell assertions (v651 L7-S1, #318 + #340).

A statement is BARE when it is a line-initial test/search whose exit status is
discarded into `set -e` with no diagnostic. Two things make it a defect:
  - it prints nothing, so the operator sees a dead script and no reason (#318)
  - bash 3.2 does not honour `set -e` for a failing `[[ ]]`/`(( ))` compound
    command, so on macOS it does not fail at all (#340)

CLASSIFIER RULES (why each exists):
  R1 line-initial only. `foo && [[ x ]]` is already guarded by its operator.
  R2 match the CLOSING token, then test the TAIL after it. Scanning the whole
     line for `&&`/`||` misses every `[[ -n "$a" && -f "$b" ]]` -- the operator
     lives INSIDE the brackets and is this repo's house idiom. Root's first
     survey had this bug and undercounted.
  R3 a non-empty tail (`&& ...`, `|| ...`, `; ...`) or a trailing `\` means the
     statement is guarded or continued. Not bare.
  R4 EXCLUSION -- function-return position. A test whose next non-blank,
     non-comment line is `}` is the function's RETURN VALUE, not an assertion.
     `is_shepherd_project() { ...; [[ -n "$ns" ]]; }` is a boolean predicate.
     Converting it to `|| { printf; exit 1; }` turns the false branch into a
     hard exit and breaks every caller. This rule is what keeps the three
     hooks/scripts/_lib.sh sites out of the convertible set.
"""
import re, sys, pathlib, json

OPEN = {'[[': ']]', '((': '))'}
RG = re.compile(r'^rg\s+(-[A-Za-z]+\s+)*-[A-Za-z]*q')


def strip_quotes(s):
    """Blank out quoted spans so a `]]` inside a string is not read as a close."""
    out, i, q = [], 0, None
    while i < len(s):
        c = s[i]
        if q:
            if c == '\\' and q == '"':
                out.append('  '); i += 2; continue
            out.append(' ' if c != q else c)
            if c == q:
                q = None
            i += 1
        else:
            if c in '"\'':
                q = c; out.append(c)
            elif c == '\\':
                out.append('  '); i += 2; continue
            else:
                out.append(c)
            i += 1
    return ''.join(out)


def find_close(masked, start, close):
    depth, i = 0, start
    tok = masked[start:start + 2]
    while i < len(masked) - 1:
        two = masked[i:i + 2]
        if two == tok:
            depth += 1; i += 2; continue
        if two == close:
            depth -= 1
            if depth == 0:
                return i + 2
            i += 2; continue
        i += 1
    return -1


def next_code_line(lines, idx):
    for j in range(idx + 1, len(lines)):
        t = lines[j].strip()
        if t and not t.startswith('#'):
            return t
    return ''


def classify(path):
    lines = pathlib.Path(path).read_text(errors='replace').split('\n')
    hits = []
    for n, raw in enumerate(lines):
        body = raw.strip()
        if not body or body.startswith('#'):
            continue
        masked = strip_quotes(body)
        kind = tail = None
        for op, cl in OPEN.items():
            if body.startswith(op):
                end = find_close(masked, 0, cl)
                if end < 0:
                    break
                kind, tail = op, body[end:].strip()
                break
        else:
            if RG.match(body):
                kind, tail = 'rg', ''
                m = re.search(r'(\|\||&&|\||;)', masked)
                if m:
                    tail = body[m.start():].strip()
        if kind is None:
            continue
        if tail:                                   # R3 guarded / chained
            continue
        if body.endswith('\\'):                    # R3 continued
            continue
        if next_code_line(lines, n) == '}':        # R4 function return value
            hits.append((n + 1, kind, body, 'RETURN'))
            continue
        hits.append((n + 1, kind, body, 'BARE'))
    return hits


if __name__ == '__main__':
    roots = sys.argv[1:] or ['hooks', 'scripts']
    files = sorted(p for r in roots for p in pathlib.Path(r).rglob('*.sh'))
    res = {}
    for f in files:
        h = [x for x in classify(f)]
        if h:
            res[str(f)] = h
    bare = [(f, l, k, b) for f, hs in res.items() for l, k, b, v in hs if v == 'BARE']
    ret = [(f, l, k, b) for f, hs in res.items() for l, k, b, v in hs if v == 'RETURN']
    print(json.dumps({
        'files_scanned': len(files),
        'bare_total': len(bare),
        'bare_bracket': len([x for x in bare if x[2] in ('[[', '((')]),
        'bare_rg': len([x for x in bare if x[2] == 'rg']),
        'excluded_return_position': len(ret),
    }, indent=2))
    print('\n--- BARE (convertible) ---')
    for f, l, k, b in bare:
        print(f'{f}:{l}\t{k}\t{b[:96]}')
    print('\n--- EXCLUDED: function-return position (DO NOT CONVERT) ---')
    for f, l, k, b in ret:
        print(f'{f}:{l}\t{k}\t{b[:96]}')
