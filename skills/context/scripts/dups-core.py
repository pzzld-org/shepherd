#!/usr/bin/env python3
"""dups-core.py — field-shape similar-struct engine for `shctx dups` (v6.1.8, #157).

Pure stdlib. Invoked by cmd_dups.sh; never run directly by operators.

Subcommands:
  extract   --files-stdin                    parse source files -> JSONL of shapes (debug/tests)
  scan      --files-stdin [opts]             parse workspace, cluster similar shapes, report
  check     --as PATH --stdin   [opts]       parse a candidate's new shapes, match vs corpus

The "Rust + syn" parse from the proposal is realized here as a brace/generic/
attribute-aware scanner over Rust source — no build step, deterministic, and
testable without a toolchain. Multi-language (tree-sitter) is a later extension;
the shape model + similarity + clustering are language-agnostic.

Similarity: weighted Jaccard over (field_name, normalized_type) pairs, blended
with a field-NAME Jaccard so a shadow that restated Uuid->String / DateTime->
String / f64 field-for-field under different type names still surfaces.

    sim(a, b) = name_weight * jaccard(names) + (1 - name_weight) * jaccard(typed)

Field-less shapes (unit / marker structs) and shapes below --min-fields are
excluded from clustering/matching — a marker type has no shape to compare.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

# ---------------------------------------------------------------------------
# Rust source parsing
# ---------------------------------------------------------------------------

_DEF_RE = re.compile(
    r'(?P<vis>pub(?:\s*\([^)]*\))?\s+)?(?P<kind>struct|enum)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)'
)
_DOC_RE = re.compile(r'^\s*///\s?(.*)$')


def _strip_block_comments(src):
    """Remove /* ... */ comments (greedy-safe, nesting-tolerant) but keep newlines
    so reported line numbers stay accurate."""
    out = []
    i, n = 0, len(src)
    depth = 0
    while i < n:
        two = src[i:i + 2]
        if depth == 0 and two == '/*':
            depth = 1
            i += 2
            continue
        if depth > 0:
            if two == '/*':
                depth += 1
                i += 2
                continue
            if two == '*/':
                depth -= 1
                i += 2
                continue
            out.append('\n' if src[i] == '\n' else ' ')
            i += 1
            continue
        # depth == 0, not entering a comment
        if two == '//':
            # line comment — keep to newline
            j = src.find('\n', i)
            if j == -1:
                break
            i = j
            continue
        out.append(src[i])
        i += 1
    return ''.join(out)


def _line_at(src, pos):
    return src.count('\n', 0, pos) + 1


def _skip_ws_and_attrs(src, i):
    """Advance past whitespace and #[...] / #![...] attribute spans."""
    n = len(src)
    while i < n:
        if src[i].isspace():
            i += 1
            continue
        if src[i] == '#' and i + 1 < n and src[i + 1] in '![':
            # attribute — skip to the matching ] of the leading [
            k = src.find('[', i)
            if k == -1:
                break
            depth = 0
            while k < n:
                if src[k] == '[':
                    depth += 1
                elif src[k] == ']':
                    depth -= 1
                    if depth == 0:
                        k += 1
                        break
                k += 1
            i = k
            continue
        break
    return i


_OPEN = {'(': ')', '[': ']', '{': '}', '<': '>'}
_CLOSE = {')': '(', ']': '[', '}': '{', '>': '<'}


def _match_delim(src, i):
    """src[i] is an opening delimiter; return index just past its match."""
    open_ch = src[i]
    close_ch = _OPEN[open_ch]
    depth = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _skip_generics(src, i):
    """If src[i] is '<', skip the balanced generic params (handles nested <>)."""
    n = len(src)
    i = _skip_ws(src, i)
    if i < n and src[i] == '<':
        depth = 0
        while i < n:
            if src[i] == '<':
                depth += 1
            elif src[i] == '>':
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
    return i


def _skip_ws(src, i):
    n = len(src)
    while i < n and src[i].isspace():
        i += 1
    return i


def _split_top_level(body, seps=(',',)):
    """Split body on top-level separators, respecting () [] {} <> nesting."""
    parts = []
    depth = 0
    cur = []
    for c in body:
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1 if depth > 0 else 0
        if depth == 0 and c in seps:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
    if cur:
        parts.append(''.join(cur))
    return [p.strip() for p in parts if p.strip()]


def normalize_type(t):
    """Normalize a Rust type to a comparable token.

    Strips references, mut, lifetimes, surrounding whitespace, and the module
    path of the OUTER base type (uuid::Uuid -> Uuid; std::vec::Vec<u8> ->
    Vec<u8>). Deliberately does NOT alias Uuid->String etc. — that pattern is
    caught by the field-NAME Jaccard bonus, not by over-normalizing types.
    """
    t = t.strip()
    # peel attributes already removed upstream; peel leading vis on tuple fields
    t = re.sub(r'^pub(\s*\([^)]*\))?\s+', '', t)
    # drop references and mut
    t = re.sub(r'^&\s*', '', t)
    t = re.sub(r"^'[A-Za-z_][A-Za-z0-9_]*\s+", '', t)  # leading lifetime after &
    t = re.sub(r'^mut\s+', '', t)
    t = re.sub(r'^dyn\s+', '', t)
    # collapse whitespace
    t = re.sub(r'\s+', '', t)
    # strip lifetimes inside generics
    t = re.sub(r"'[A-Za-z_][A-Za-z0-9_]*,?", '', t)
    if not t:
        return ''
    # split base<generics>
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_:]*)(<.*>)?$', t)
    if m:
        base = m.group(1)
        generics = m.group(2) or ''
        base = base.split('::')[-1]  # strip module path of outer base
        return base + generics
    return t


def _parse_struct_fields(body):
    """body is the inner text of a named struct's { ... }. Returns [(name, type)]."""
    fields = []
    for item in _split_top_level(body):
        item = item.strip()
        if not item or item.startswith('#') or item.startswith('//'):
            continue
        item = re.sub(r'^pub(\s*\([^)]*\))?\s+', '', item)
        # name : type
        idx = _top_level_colon(item)
        if idx == -1:
            continue
        name = item[:idx].strip()
        typ = item[idx + 1:].strip()
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name):
            continue
        fields.append((name, normalize_type(typ)))
    return fields


def _top_level_colon(s):
    """Index of the first ':' not inside <> () [] {} and not part of '::'."""
    depth = 0
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1 if depth > 0 else 0
        elif c == ':' and depth == 0:
            if i + 1 < n and s[i + 1] == ':':
                i += 2
                continue
            return i
        i += 1
    return -1


def _parse_tuple_fields(body):
    """body is the inner text of a tuple struct's ( ... ). Returns positional fields."""
    fields = []
    for idx, item in enumerate(_split_top_level(body)):
        typ = normalize_type(item)
        if typ:
            fields.append(('', typ))  # positional: no field name (name-Jaccard ignores)
    return fields


def _parse_enum_variants(body):
    """body is the inner text of an enum's { ... }. Variant name = field name,
    variant payload signature = type."""
    fields = []
    for item in _split_top_level(body):
        item = item.strip()
        if not item or item.startswith('#') or item.startswith('//'):
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$', item, re.S)
        if not m:
            continue
        vname = m.group(1)
        rest = m.group(2).strip()
        if rest.startswith('('):
            payload = 'tuple(' + ','.join(
                normalize_type(x) for x in _split_top_level(rest[1:rest.rfind(')')])
            ) + ')'
        elif rest.startswith('{'):
            inner = rest[1:rest.rfind('}')]
            payload = 'struct{' + ','.join(
                sorted(n for n, _ in _parse_struct_fields(inner))
            ) + '}'
        else:
            payload = ''  # unit variant or discriminant
        fields.append((vname, payload))
    return fields


def parse_rust_source(src, rel_path, package):
    """Parse one Rust source string -> list of shape dicts (public struct/enum)."""
    src = _strip_block_comments(src)
    shapes = []
    n = len(src)
    for m in _DEF_RE.finditer(src):
        vis_raw = (m.group('vis') or '').strip()
        if not vis_raw.startswith('pub'):
            continue  # only public types participate
        # guard against matching inside an identifier (e.g. `my_struct`)
        start = m.start('kind')
        if start > 0 and (src[start - 1].isalnum() or src[start - 1] == '_'):
            continue
        kind = m.group('kind')
        name = m.group('name')
        line = _line_at(src, m.start())
        vis = re.sub(r'\s+', '', vis_raw)

        i = _skip_generics(src, m.end('name'))
        # skip an optional where-clause / generic bounds up to the body delimiter
        i = _skip_ws(src, i)
        # find the next significant delimiter: ; ( {
        j = i
        while j < n and src[j] not in ';({':
            j += 1
        if j >= n:
            continue
        delim = src[j]
        if delim == ';':
            fields = []  # unit struct
        elif delim == '(':
            end = _match_delim(src, j)
            fields = _parse_tuple_fields(src[j + 1:end - 1])
        else:  # '{'
            end = _match_delim(src, j)
            inner = src[j + 1:end - 1]
            fields = _parse_enum_variants(inner) if kind == 'enum' else _parse_struct_fields(inner)

        # doc summary: nearest preceding /// line
        doc = _doc_above(src, m.start())
        shapes.append(_mk_shape(name, kind, package, rel_path, line, vis, doc, fields))
    return shapes


def _doc_above(src, pos):
    head = src.rfind('\n', 0, pos)
    if head == -1:
        return ''
    # walk back over attribute/doc lines
    lines = src[:head].splitlines()
    for ln in reversed(lines):
        s = ln.strip()
        if not s:
            break
        dm = _DOC_RE.match(ln)
        if dm:
            return dm.group(1).strip()[:200]
        if s.startswith('#'):
            continue
        break
    return ''


def _mk_shape(name, kind, package, rel_path, line, vis, doc, fields):
    field_names = sorted({n for n, _ in fields if n})
    typed = sorted(f"{n}:{t}" for n, t in fields)
    shape_hash = hashlib.sha256('|'.join(typed).encode('utf-8')).hexdigest()
    return {
        "name": name,
        "kind": kind,
        "package": package,
        "file": rel_path,
        "line": line,
        "visibility": vis,
        "doc": doc,
        "fields": [{"n": n, "t": t} for n, t in fields],
        "field_names": field_names,
        "field_count": len(fields),
        "shape_hash": shape_hash,
        "lang": "rust",
    }


def _package_for(rel_path):
    """Heuristic package label from a path: the segment after crates/ | bin/ |
    packages/, else the top dir, else '(root)'."""
    parts = rel_path.replace('\\', '/').split('/')
    for anchor in ('crates', 'packages', 'libs', 'bin'):
        if anchor in parts:
            k = parts.index(anchor)
            if k + 1 < len(parts):
                return parts[k + 1]
    return parts[0] if len(parts) > 1 else '(root)'


def parse_files(paths):
    shapes = []
    file_text = {}
    for p in paths:
        p = p.strip()
        if not p or not p.endswith('.rs'):
            continue
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as fh:
                src = fh.read()
        except OSError:
            continue
        file_text[p] = src
        shapes.extend(parse_rust_source(src, p, _package_for(p)))
    return shapes, file_text


# ---------------------------------------------------------------------------
# Similarity + clustering
# ---------------------------------------------------------------------------

def _typed_set(shape):
    return {f"{f['n']}:{f['t']}" for f in shape['fields']}


def _name_set(shape):
    return set(shape['field_names'])


def jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(s1, s2, name_weight):
    j_typed = jaccard(_typed_set(s1), _typed_set(s2))
    n1, n2 = _name_set(s1), _name_set(s2)
    # name-Jaccard only contributes when both shapes carry named fields
    if not n1 or not n2:
        return j_typed
    j_names = jaccard(n1, n2)
    return name_weight * j_names + (1.0 - name_weight) * j_typed


def _key(shape):
    return f"{shape['package']}::{shape['name']}"


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _build_consumers(shapes, file_text):
    """consumers[key] = # of files that REFERENCE the type name as a real usage.

    Comments are stripped (a doc/comment mention is not a consumer), and any file
    that DEFINES a struct/enum of the same name is excluded (a second definition
    is a duplicate, not a consumer — this keeps the orphan-canonical signal clean
    when a concept is defined twice under the same name)."""
    tok_re = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
    # identifier sets from comment-stripped source
    file_idents = {p: set(tok_re.findall(_strip_block_comments(src)))
                   for p, src in file_text.items()}
    # files that define each type name
    def_files = {}
    for s in shapes:
        def_files.setdefault(s['name'], set()).add(s['file'])
    consumers = {}
    for s in shapes:
        name = s['name']
        skip = def_files.get(name, set())
        c = 0
        for p, idents in file_idents.items():
            if p in skip:
                continue
            if name in idents:
                c += 1
        consumers[_key(s)] = c
    return consumers


_FOUNDATION_RE = re.compile(r'(types?|core|model|domain|primitives?|common|base|proto|schema|entit)', re.I)


def _pick_canonical(members, consumers, registry):
    # 1) registry pin
    canon_vals = set((registry or {}).get('canonical', {}).values())
    for mi, m in members:
        if _key(m) in canon_vals:
            return mi, "registry-pinned"
    # 2) foundation-tier package name
    found = [(mi, m) for mi, m in members if _FOUNDATION_RE.search(m['package'] or '')]
    if found:
        # among foundation members, prefer most consumers then most fields
        best = max(found, key=lambda im: (consumers.get(_key(im[1]), 0), im[1]['field_count']))
        return best[0], "foundation-tier package"
    # 3) most consumers (de-facto canonical = carries the traffic)
    best = max(members, key=lambda im: (consumers.get(_key(im[1]), 0), im[1]['field_count']))
    if consumers.get(_key(best[1]), 0) > 0:
        return best[0], "most consumers"
    # 4) most complete shape, then lexicographic path
    best = min(members, key=lambda im: (-im[1]['field_count'], im[1]['file'], im[1]['line']))
    return best[0], "most fields"


def _allow_listed(registry, ka, kb):
    for pair in (registry or {}).get('allow', []):
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        if {ka, kb} == {pair[0], pair[1]}:
            return True
    return False


def _concept_guess(canonical_name):
    # strip common shadow suffixes to name the concept
    base = re.sub(
        r'(Snapshot|Dto|DTO|Info|Data|Event|Record|Entry|Model|State|Repr|Raw|Msg|Message|Payload|Row|View|Inner|Impl)$',
        '', canonical_name)
    return base or canonical_name


def cluster(shapes, threshold, name_weight, min_fields, registry, consumers):
    elig = [s for s in shapes if s['field_count'] >= min_fields]
    n = len(elig)
    uf = _UF(n)
    sims = {}
    for i in range(n):
        si = elig[i]
        ki = _key(si)
        for j in range(i + 1, n):
            sj = elig[j]
            kj = _key(sj)
            if ki == kj:
                continue
            if _allow_listed(registry, ki, kj):
                continue
            s = similarity(si, sj, name_weight)
            if s >= threshold:
                uf.union(i, j)
                sims[(i, j)] = s
    # group
    groups = {}
    for idx in range(n):
        groups.setdefault(uf.find(idx), []).append(idx)
    clusters = []
    for root, idxs in groups.items():
        if len(idxs) < 2:
            continue
        members = [(ix, elig[ix]) for ix in idxs]
        ci, reason = _pick_canonical(members, consumers, registry)
        canon = elig[ci]
        pairs = []
        max_sim = 0.0
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ia, ib = sorted((idxs[a], idxs[b]))
                s = sims.get((ia, ib))
                if s is None:
                    s = similarity(elig[ia], elig[ib], name_weight)
                max_sim = max(max_sim, s)
                pairs.append({
                    "a": _key(elig[ia]), "b": _key(elig[ib]), "similarity": round(s, 3)
                })
        # severity
        cons_vals = [consumers.get(_key(m), 0) for _, m in members]
        orphan_shadow = (min(cons_vals) == 0 and max(cons_vals) > 0)
        if orphan_shadow:
            severity = "foundation-blocking"
        elif max_sim >= 0.90:
            severity = "high"
        else:
            severity = "medium"
        mem_out = []
        for ix, m in sorted(members, key=lambda im: (-consumers.get(_key(im[1]), 0), im[1]['file'])):
            mem_out.append({
                "name": m['name'], "kind": m['kind'], "package": m['package'],
                "file": m['file'], "line": m['line'], "field_count": m['field_count'],
                "consumers": consumers.get(_key(m), 0),
                "is_canonical": (ix == ci),
                "field_names": m['field_names'],
            })
        clusters.append({
            "concept": _concept_guess(canon['name']),
            "severity": severity,
            "max_similarity": round(max_sim, 3),
            "suggested_canonical": _key(canon),
            "canonical_reason": reason,
            "members": mem_out,
            "pairs": sorted(pairs, key=lambda p: -p['similarity']),
        })
    # rank: foundation-blocking first, then by max_similarity
    rank = {"foundation-blocking": 3, "high": 2, "medium": 1}
    clusters.sort(key=lambda c: (-rank[c['severity']], -c['max_similarity']))
    return clusters


# ---------------------------------------------------------------------------
# DB corpus (python sqlite3 module — no sqlite3 binary dependency)
# ---------------------------------------------------------------------------

_SHAPES_DDL = """
CREATE TABLE IF NOT EXISTS index_struct_shapes (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  package TEXT NOT NULL, file_path TEXT NOT NULL, line INTEGER, visibility TEXT,
  language TEXT NOT NULL DEFAULT 'rust', fields TEXT NOT NULL DEFAULT '[]',
  field_names TEXT NOT NULL DEFAULT '[]', field_count INTEGER NOT NULL DEFAULT 0,
  shape_hash TEXT NOT NULL, doc_summary TEXT, refreshed_at INTEGER NOT NULL,
  UNIQUE(project_id, name, package, kind)
);
"""


def _uuid7_like():
    ts = int(time.time() * 1000)
    rnd = os.urandom(10).hex()
    hi = f"{ts:012x}"
    return f"{hi[0:8]}-{hi[8:12]}-7{rnd[0:3]}-8{rnd[3:6]}-{rnd[6:18]}"


def persist_shapes(db_path, project_id, shapes):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(_SHAPES_DDL)
        now = int(time.time())
        for s in shapes:
            conn.execute(
                """INSERT INTO index_struct_shapes
                   (id, project_id, name, kind, package, file_path, line, visibility,
                    language, fields, field_names, field_count, shape_hash, doc_summary, refreshed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(project_id, name, package, kind) DO UPDATE SET
                     file_path=excluded.file_path, line=excluded.line, visibility=excluded.visibility,
                     fields=excluded.fields, field_names=excluded.field_names,
                     field_count=excluded.field_count, shape_hash=excluded.shape_hash,
                     doc_summary=excluded.doc_summary, refreshed_at=excluded.refreshed_at""",
                (_uuid7_like(), project_id, s['name'], s['kind'], s['package'], s['file'],
                 s['line'], s['visibility'], s['lang'], json.dumps(s['fields']),
                 json.dumps(s['field_names']), s['field_count'], s['shape_hash'],
                 s['doc'], now))
        # sweep rows not seen this run
        conn.execute(
            "DELETE FROM index_struct_shapes WHERE project_id=? AND refreshed_at<?",
            (project_id, now))
        conn.commit()
        return conn.total_changes
    finally:
        conn.close()


def load_corpus(db_path, project_id):
    if not db_path or not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT name, kind, package, file_path, line, visibility, fields,
                          field_names, field_count, shape_hash
                   FROM index_struct_shapes WHERE project_id=?""", (project_id,)).fetchall()
        except sqlite3.OperationalError:
            return []  # table absent — fail open
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        out.append({
            "name": r["name"], "kind": r["kind"], "package": r["package"],
            "file": r["file_path"], "line": r["line"], "visibility": r["visibility"],
            "doc": "", "fields": json.loads(r["fields"]),
            "field_names": json.loads(r["field_names"]),
            "field_count": r["field_count"], "shape_hash": r["shape_hash"], "lang": "rust",
        })
    return out


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _read_registry(path):
    if not path or not os.path.exists(path):
        return {"version": 1, "canonical": {}, "allow": []}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        data.setdefault('canonical', {})
        data.setdefault('allow', [])
        return data
    except (OSError, ValueError):
        return {"version": 1, "canonical": {}, "allow": []}


def _stdin_paths():
    return [ln for ln in sys.stdin.read().splitlines() if ln.strip()]


def cmd_extract(args):
    paths = _stdin_paths() if args.files_stdin else (args.file or [])
    shapes, _ = parse_files(paths)
    for s in shapes:
        print(json.dumps(s, sort_keys=True))
    return 0


def cmd_scan(args):
    paths = _stdin_paths() if args.files_stdin else (args.file or [])
    shapes, file_text = parse_files(paths)
    registry = _read_registry(args.registry)
    consumers = _build_consumers(shapes, file_text)
    clusters = cluster(shapes, args.threshold, args.name_weight, args.min_fields, registry, consumers)

    if args.update and args.db and args.project_id:
        try:
            persist_shapes(args.db, args.project_id, shapes)
        except sqlite3.Error as e:
            sys.stderr.write(f"dups: persist failed: {e}\n")

    rank = {"foundation-blocking": 3, "high": 2, "medium": 1}
    fail_rank = rank.get(args.fail_on, 0) if args.fail_on else 0
    worst = max((rank[c['severity']] for c in clusters), default=0)
    gate_fail = bool(fail_rank) and worst >= fail_rank

    result = {
        "schema": "dups-scan/1",
        "threshold": args.threshold,
        "name_weight": args.name_weight,
        "min_fields": args.min_fields,
        "stats": {
            "files": len(file_text),
            "types": len(shapes),
            "clusters": len(clusters),
            "clustered_types": sum(len(c['members']) for c in clusters),
        },
        "gate": {"fail_on": args.fail_on, "failed": gate_fail},
        "clusters": clusters,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _render_scan(result)
    return 3 if gate_fail else 0


def cmd_check(args):
    content = sys.stdin.read() if args.stdin else _read_file(args.file_arg)
    if content is None:
        return 0
    as_path = args.as_path or (args.file_arg or "candidate.rs")
    if not as_path.endswith('.rs'):
        return 0  # only rust supported today — fail open
    new_shapes = parse_rust_source(content, as_path, _package_for(as_path))
    registry = _read_registry(args.registry)
    corpus = load_corpus(args.db, args.project_id) if args.db and args.project_id else []
    # exclude same-file defs from the corpus (re-edits of the same type)
    corpus = [c for c in corpus if c['file'] != as_path]

    candidates = []
    block = False
    for ns in new_shapes:
        if ns['field_count'] < args.min_fields:
            continue
        kns = _key(ns)
        hits = []
        for c in corpus:
            if _key(c) == kns:
                continue
            if _allow_listed(registry, kns, _key(c)):
                continue
            s = similarity(ns, c, args.name_weight)
            if s >= args.threshold:
                hits.append({
                    "name": c['name'], "package": c['package'], "kind": c['kind'],
                    "file": c['file'], "line": c['line'], "similarity": round(s, 3),
                    "shared_field_names": sorted(set(ns['field_names']) & set(c['field_names'])),
                })
                if s >= args.block_threshold:
                    block = True
        if hits:
            hits.sort(key=lambda h: -h['similarity'])
            candidates.append({
                "name": ns['name'], "kind": ns['kind'], "field_count": ns['field_count'],
                "field_names": ns['field_names'], "hits": hits,
            })

    result = {
        "schema": "dups-check/1",
        "threshold": args.threshold,
        "block_threshold": args.block_threshold,
        "block": block,
        "candidates": candidates,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _render_check(result, as_path)
    return 5 if block else 0


def _read_file(path):
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Human rendering
# ---------------------------------------------------------------------------

def _render_scan(r):
    s = r['stats']
    print(f"shctx dups scan — {s['types']} public struct/enum defs in {s['files']} files; "
          f"{s['clusters']} similar-shape cluster(s) (threshold {r['threshold']}).")
    if not r['clusters']:
        print("  ✓ no duplicate-shape clusters above threshold.")
        return
    badge = {"foundation-blocking": "‼ FOUNDATION-BLOCKING", "high": "▲ HIGH", "medium": "△ MEDIUM"}
    for i, c in enumerate(r['clusters'], 1):
        print()
        print(f"[{i}] {badge[c['severity']]}  concept≈{c['concept']}  "
              f"(max similarity {c['max_similarity']})")
        print(f"    suggested canonical: {c['suggested_canonical']}  "
              f"[{c['canonical_reason']}]")
        for m in c['members']:
            mark = "★ canonical" if m['is_canonical'] else f"{m['consumers']} consumer(s)"
            print(f"      - {m['package']}::{m['name']} ({m['kind']}, {m['field_count']} fields) "
                  f"{m['file']}:{m['line']}  [{mark}]")
    if r['gate']['failed']:
        print()
        print(f"  ✗ GATE FAILED (--fail-on {r['gate']['fail_on']}).")


def _render_check(r, as_path):
    if not r['candidates']:
        return
    verb = "BLOCKED" if r['block'] else "similar-shape match(es)"
    print(f"shctx dups check — {as_path}: {verb}")
    for cand in r['candidates']:
        print(f"  {cand['name']} {{ {', '.join(cand['field_names'])} }}")
        for h in cand['hits']:
            print(f"    is {h['similarity']}-similar to {h['package']}::{h['name']} "
                  f"({h['file']}:{h['line']}) — reuse it?")
            if h['shared_field_names']:
                print(f"        shared fields: {', '.join(h['shared_field_names'])}")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

def main(argv):
    p = argparse.ArgumentParser(prog="dups-core.py", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--threshold", type=float, default=0.7)
        sp.add_argument("--name-weight", dest="name_weight", type=float, default=0.5)
        sp.add_argument("--min-fields", dest="min_fields", type=int, default=2)
        sp.add_argument("--registry", default="")
        sp.add_argument("--db", default="")
        sp.add_argument("--project-id", dest="project_id", default="")
        sp.add_argument("--json", action="store_true")

    pe = sub.add_parser("extract")
    pe.add_argument("--files-stdin", dest="files_stdin", action="store_true")
    pe.add_argument("file", nargs="*")

    ps = sub.add_parser("scan")
    common(ps)
    ps.add_argument("--files-stdin", dest="files_stdin", action="store_true")
    ps.add_argument("--update", action="store_true")
    ps.add_argument("--fail-on", dest="fail_on", default="",
                    choices=["", "medium", "high", "foundation-blocking", "any"])
    ps.add_argument("file", nargs="*")

    pc = sub.add_parser("check")
    common(pc)
    pc.add_argument("--block-threshold", dest="block_threshold", type=float, default=0.85)
    pc.add_argument("--as", dest="as_path", default="")
    pc.add_argument("--stdin", action="store_true")
    pc.add_argument("file_arg", nargs="?")

    args = p.parse_args(argv)
    if getattr(args, "fail_on", "") == "any":
        args.fail_on = "medium"

    if args.cmd == "extract":
        return cmd_extract(args)
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "check":
        return cmd_check(args)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:
        sys.exit(0)
