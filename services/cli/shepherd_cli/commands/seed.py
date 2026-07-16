"""``shepherd seed`` — deterministic *.seed.md pre-flight gate (bash: ``cmd_seed.sh``).

Bash source of truth: ``skills/context/scripts/cmd_seed.sh`` (v6.2.1),
subcommand ``verify``. The bash file's own header is explicit about scope:
this mechanizes the planter pre-flight checklist (``planter.md`` Step 4 /
``seed-template.md`` Verification) that used to be prose-only — hallucinated
``file_scope`` paths, oversized footprints, leftover ``TODO``/``FIXME``
markers, and prescriptive ``Lane N`` numbering (the #67 firewall violation)
are caught mechanically instead of by latent self-policing.

**PURE TEXT. NO DATABASE, NO ``_lib.sh``, NO NETWORK.** ``cmd_seed.sh``
touches no ``sqlite3``/``shctx_sql`` call anywhere, resolves no project id,
and reads no config — it is a single-file text-processing gate over
whatever path is given on the command line. This module therefore imports
neither :mod:`shepherd_cli.db` nor any Tortoise model, opens no
``db.lifespan()``, and needs no ``models_seed.py`` mirror-model module (hard
rule #8/#9's "no model module needed" applies here in its pure-text form —
this is closest in shape to :mod:`shepherd_cli.commands.lint`, the other
NO-DATABASE port in this package, except ``seed`` operates on file
*content* rather than a filesystem *tree walk*). The only external process
this module ever spawns is ``git rev-parse --show-toplevel``, mirroring
bash's own ``repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"``
line verbatim — even that is optional (a non-repo invocation degrades
gracefully to resolving ``file_scope`` paths relative to the process cwd
only, exactly like bash's empty ``$repo_root``).

HARD vs WARN (bash module docstring, reproduced verbatim for reference):

- **HARD** (exit 1, blocks the SEED-GATE) — footprint over cap,
  ``TODO``/``FIXME``, ``Lane N`` numbering, a ``file_scope`` path that
  neither resolves nor carries a ``(NEW)`` marker, a canonical deliverable
  block with no ``**GH:**`` anchor.
- **WARN** (exit 0, advisory) — footprint smell, thin Phase-0 mesh, no
  CRITICAL/HIGH deliverable, missing frontmatter, ``Sequencing:``/semver
  judgments.

Exit codes: ``0`` = no hard failures (warnings allowed); ``1`` = one or
more hard failures; ``2`` = a usage error (missing/unrecognized subcommand,
unknown flag, missing/nonexistent ``<path>``).

SINGLE VARIADIC CALLBACK, NOT A REAL ``@app.command()`` FOR ``verify``
=======================================================================
Mirrors :mod:`shepherd_cli.commands.style`'s documented shape exactly, for
the same reason: ``cmd_seed.sh``'s dispatcher has THREE bash-specific
contracts that a plain ``@app.command("verify")`` cannot reproduce under
Typer/Click's own ``Group`` machinery —

1. A bare ``shctx seed`` (no subcommand) prints usage text to **stdout**
   and exits **0** — not Click's default (a missing/absent subcommand
   under ``no_args_is_help`` exits 2, or Click auto-prints its own
   generated help). ``help``/``--help``/``-h`` in the subcommand-name slot
   are bash-parity ALIASES for this same branch (``case "$sub" in
   ""|help|--help|-h) usage; exit 0;;``) — they are plain string
   comparisons against ``$1``, not Click options.
2. An unrecognized subcommand name prints ``unknown subcommand: $sub`` +
   usage to **stderr** and exits **2** (bash's own ``*)`` default arm) —
   registering ``verify`` as a real ``@app.command()`` would hand this to
   Click's ``UsageError`` machinery instead, which happens to ALSO exit 2
   (a nicer parity accident than :mod:`shepherd_cli.commands.lock`'s
   documented equivalent, where bash's own unknown-subcommand exit code is
   1, not 2) but with Click's own message text, not bash's.
3. Within ``verify`` itself, ``-*)`` (any token starting with ``-`` that
   is not literally ``--quiet``) is an ``unknown flag: $1`` error, exit 2
   — WITHOUT the usage text bash prints for cases 1/2. A formal
   ``typer.Option`` for ``--quiet`` alongside a real positional ``<path>``
   argument would hand unrecognized-flag detection to Click's own
   ``NoSuchOption`` error (different text) and would not reproduce the
   literal "last non-flag token wins" path assignment bash's
   ``*)  path="$1"`` loop performs (a caller passing two positional
   tokens has the second one win, silently — bash-parity, reproduced
   verbatim rather than "fixed").

So, exactly like ``style.py``, this module registers ZERO
``@app.command()``s. One ``@app.callback(invoke_without_command=True,
context_settings={"ignore_unknown_options": True})`` captures every token
after ``seed`` as a raw ``list[str]`` (Click's ``nargs=-1``, so a token
like ``--quiet`` or a path starting with ``-`` lands here literally instead
of raising "no such option") and :func:`_dispatch` reproduces bash's
``case``/``while`` parsing over that raw list by hand, byte-for-byte.

**ONE ACCEPTED, DOCUMENTED CLICK-VS-BASH GAP:** Click auto-registers a real
``--help`` option on every command (including this callback), and Click's
option parser recognizes KNOWN options (unlike the unknown ones
``ignore_unknown_options`` defers to us) wherever they appear on the
command line, not only in the leading position — so ``shepherd seed verify
--help`` triggers Click's own auto-generated help text and exit 0, not
bash's ``unknown flag: --help`` / exit 2. This is the same class of gap
:mod:`shepherd_cli.commands.lock`'s module docstring documents for its own
unknown-subcommand text/exit-code mismatch: a disproportionate amount of
fragile ``TyperGroup``/``_click`` subclassing to close one edge case no
other module in this package attempts either. Every other flag (including
a BARE ``-h``, which Click does NOT auto-register) reproduces bash's
``unknown flag:`` error exactly.

FILE-READING BASH QUIRK REPRODUCED ON PURPOSE
==============================================
``content="$(cat "$path")"`` — bash command substitution strips **every**
trailing newline character from the captured text (not just one), so any
number of trailing blank lines in the source file are invisible to every
check below (including ``total_lines``). :func:`_verify` reproduces this
by reading the file with ``newline=""`` (so ``\\r`` is never silently
translated the way Python's default universal-newline text mode would) and
then calling ``.rstrip("\\n")`` on the raw content before doing anything
else — matching bash's command substitution exactly. ``total_lines`` is
then ``content.count("\\n") + 1`` (via ``len(content.split("\\n"))``),
matching bash's own quirky counting method (``printf '%s\\n' "$content" |
grep -c ''`` — the ``printf`` re-adds exactly one trailing newline before
``grep -c ''`` counts lines, so an EMPTY file still counts as 1 "line").

GLOB SEMANTICS (file_scope path resolution)
============================================
:func:`_resolve_one` uses :func:`glob.glob` with ``recursive=False``
(the default) for any ``file_scope`` token containing ``*``/``?``/``[`` —
matching bash's own un-``globstar``'d pathname expansion exactly: neither
tool recurses through ``/`` on a bare ``**`` (bash without ``shopt -s
globstar`` treats consecutive ``*`` the same as one; Python's ``glob.glob``
without ``recursive=True`` does likewise), so a ``crates/**/*.rs``
``file_scope`` entry matches only one directory level deep in both tools,
not the whole subtree — an intentional, mirrored limitation, not a bug in
either the bash script or this port.
"""

from __future__ import annotations

import glob
import re
import subprocess
from pathlib import Path

import typer

app = typer.Typer(
    add_completion=False,
    help="Deterministic pre-flight gate for a *.seed.md (bash: cmd_seed.sh).",
)

# --- canonical numbers (single source of truth, matching cmd_seed.sh) ---
MIN_MESH_ROWS = 8
SPRINT_FOOTPRINT_CAP = 400
PATCH_FOOTPRINT_CAP = 200

#: Verbatim bash-parity usage text — ``usage()`` in ``cmd_seed.sh``. Printed
#: to stdout (exit 0) for a bare ``shepherd seed``/``help``/``--help``/
#: ``-h`` in the subcommand-name slot, and to stderr (exit 2) after an
#: ``unknown subcommand:`` line for anything else unrecognized.
_USAGE = (
    "shctx seed verify <path> [--quiet]\n"
    "  Deterministic pre-flight gate for a *.seed.md.\n"
    "  Exit 1 on >=1 HARD failure (blocks the SEED-GATE); 0 otherwise (warnings allowed)."
)

#: Bash's ``resolve_one()`` NEW-marker allow-list — embellishment-tolerant:
#: ``(NEW``, ``(new``, ``(New``, ``#NEW``, ``#new``, ``# NEW``, ``# new``,
#: each matched as a plain substring anywhere in the raw scope entry
#: (bash: ``case "$raw" in *'(NEW'*|*'(new'*|... ) return 0 ;; esac``).
_NEW_MARKERS = ("(NEW", "(new", "(New", "#NEW", "#new", "# NEW", "# new")


# --------------------------------------------------------------------------
# Small text/regex helpers — each mirrors one bash primitive exactly.
# --------------------------------------------------------------------------
def _first_token(s: str) -> str:
    """Return the first whitespace-delimited token of ``s``.

    Bash parity: ``${s%%[[:space:]]*}`` — the longest suffix starting at
    the FIRST whitespace character is removed, leaving everything before
    it (an empty string if ``s`` starts with whitespace or is itself
    empty).

    Args:
        s: The string to take the first token of (already stripped of
            leading/trailing whitespace by the caller in every real call
            site, but this function tolerates an unstripped ``s`` too).

    Returns:
        The substring of ``s`` up to (not including) its first whitespace
        character, or all of ``s`` if it contains no whitespace.
    """
    return re.split(r"\s", s, maxsplit=1)[0]


def _repo_root() -> str | None:
    """Resolve the git repo root the same way ``cmd_seed.sh`` does.

    Bash parity: ``repo_root="$(git rev-parse --show-toplevel 2>/dev/null
    || true)"`` — run from the process's OWN current working directory
    (never ``resolve_workdir()`` or any other shepherd-specific override;
    the bash header is explicit that this command uses none of that), with
    any failure (not a git repo, ``git`` missing, timeout) silently
    degrading to "no repo root" rather than raising.

    Returns:
        The absolute repo root path with no trailing newline, or ``None``
        if the process cwd is not inside a git repository (or ``git``
        could not be run at all).
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    root = proc.stdout.strip()
    return root or None


def _resolve_one(raw: str, repo_root: str | None) -> bool:
    """Does one ``file_scope`` entry resolve on disk, or carry a ``(NEW)`` marker?

    Bash parity: ``resolve_one()`` in ``cmd_seed.sh``.

    Args:
        raw: One raw scope entry (already comma/list-split and
            whitespace-trimmed by the caller, but may still carry a
            trailing annotation like `` — desc`` or ``(NEW - reason)``
            after the path token itself).
        repo_root: The git repo root (see :func:`_repo_root`), or ``None``
            if the entry's path should be resolved relative to the
            process cwd instead.

    Returns:
        ``True`` if ``raw`` carries a NEW-marker anywhere in it, is a
        template placeholder (``<...>``) or empty, is a glob
        (``*``/``?``/``[`` present) that matches at least one path, or is
        a literal path that exists (``os.path.exists``, matching bash's
        ``[[ -e "$cand" ]]`` — any file type). ``False`` otherwise (a
        real, non-NEW-marked path that does not resolve).
    """
    if any(marker in raw for marker in _NEW_MARKERS):
        return True
    tok = _first_token(raw)
    if tok == "" or (tok.startswith("<") and tok.endswith(">")):
        return True
    cand = tok
    if repo_root and not tok.startswith("/"):
        cand = f"{repo_root}/{tok}"
    if any(ch in tok for ch in "*?["):
        return len(glob.glob(cand)) > 0
    return Path(cand).exists()


def _extract_scope_block(lines: list[str]) -> list[str]:
    """Extract the raw ``file_scope:`` YAML block's body lines.

    Bash parity: the ``awk`` program that scans for ``^file_scope:``,
    collects every following line until a bare ``---`` separator or a
    non-indented (next top-level YAML key) line terminates the block, and
    finally has its OWN command-substitution wrapper strip every trailing
    newline — reproduced here as ``"\\n".join(...).rstrip("\\n")`` so a
    block whose only content is trailing blank lines collapses to nothing,
    exactly like bash's own ``scope_block="$(... | awk ...)"``.

    Args:
        lines: The seed file's content, already split on ``\\n`` (trailing
            newlines already stripped by the caller).

    Returns:
        The block's body lines (never includes the ``file_scope:`` header
        line itself, the terminating ``---``, or the terminating
        next-top-level-key line) — an empty list if no ``file_scope:``
        header was found, or if the block's body collapses to nothing
        after the same trailing-newline strip bash's command substitution
        performs.
    """
    scope_lines: list[str] = []
    inblk = False
    for line in lines:
        if line.startswith("file_scope:"):
            inblk = True
            continue
        if inblk and re.match(r"^---\s*$", line):
            inblk = False
        if inblk and re.match(r"^\S", line):
            inblk = False
        if inblk:
            scope_lines.append(line)
    text = "\n".join(scope_lines).rstrip("\n")
    if not text:
        return []
    return text.split("\n")


def _parse_scope_entries(scope_lines: list[str]) -> list[str]:
    """Parse individual scope-path entries out of a ``file_scope:`` block body.

    Bash parity: the ``while IFS= read -r line`` loop over ``$scope_block``
    — handles BOTH flow-style (`` exclusive: [a, b]``/`` additive: [a,
    b]``) and block-style (``  - path``) YAML list shapes, in that
    priority order per line (a line is tested for flow-style FIRST; only
    if it does not match does it fall through to the block-style check).

    Args:
        scope_lines: The block body lines from :func:`_extract_scope_block`.

    Returns:
        Every individual scope-path entry found, in file order, each
        whitespace-trimmed (flow-style) or with only its leading ``-``
        list-marker stripped (block-style, matching bash's own
        start-anchored ``sed`` substitution — trailing content is left
        alone). A header line like ``additive:`` with no inline ``[...]``
        (its entries appear on FOLLOWING block-style lines instead)
        contributes nothing, matching bash's own
        ``case "$entry" in exclusive:*|additive:*) continue;; esac`` guard.
    """
    entries: list[str] = []
    for line in scope_lines:
        if re.search(r"exclusive:.*\[.*\]", line) or re.search(r"additive:.*\[.*\]", line):
            inner = line.split("[", 1)[1].rsplit("]", 1)[0]
            for raw_entry in inner.split(","):
                stripped = raw_entry.strip()
                if stripped:
                    entries.append(stripped)
            continue
        if "- " not in line:
            continue
        entry = re.sub(r"^\s*-\s*", "", line)
        if not entry:
            continue
        if entry.startswith("exclusive:") or entry.startswith("additive:"):
            continue
        entries.append(entry)
    return entries


def _parse_deliverable_blocks(lines: list[str]) -> list[tuple[bool, bool]]:
    """Classify every ``### ...`` section as a deliverable block, tracking its GH anchor.

    Bash parity: the ``awk`` state machine — ``started``/``isdel``/
    ``hasgh`` tracked across lines, flushed (appended to the result) each
    time a NEW ``### `` heading starts (or a ``## `` heading closes the
    current one), plus once more at end-of-input (awk's ``END { flush()
    }``). Reproduces the exact one-line-early-exit (bash's ``next``) for a
    ``### `` heading line itself — such a line is NEVER also checked for
    an inline ``**Priority:**``/``**GH:**`` marker — but a ``## `` heading
    line, which bash does NOT ``next`` past, still falls through to those
    same two checks on itself.

    Args:
        lines: The seed file's content, split on ``\\n``.

    Returns:
        One ``(is_deliverable, has_gh_anchor)`` tuple per ``### ``-headed
        section that was ever ``started`` (a section that is immediately
        closed by the very next line, with zero body lines, still yields
        exactly one tuple — matching awk's own flush-on-transition
        semantics). ``is_deliverable`` is True if the heading itself
        carries a ``[CRITICAL|HIGH|MEDIUM|LOW]`` tag, or if a
        ``**Priority:**`` marker appears anywhere in the section's body.
    """
    blocks: list[tuple[bool, bool]] = []
    started = False
    isdel = False
    hasgh = False
    for line in lines:
        if re.match(r"^###[ \t]", line):
            if started:
                blocks.append((isdel, hasgh))
            started = True
            isdel = bool(re.search(r"\[(CRITICAL|HIGH|MEDIUM|LOW)\]", line))
            hasgh = False
            continue
        if re.match(r"^##[ \t]", line):
            if started:
                blocks.append((isdel, hasgh))
            started = False
        if re.search(r"\*\*Priority:\*\*", line):
            isdel = True
        if re.search(r"\*\*GH:\*\*", line):
            hasgh = True
    if started:
        blocks.append((isdel, hasgh))
    return blocks


def _extract_kind(lines: list[str]) -> str:
    """Extract the ``kind:`` frontmatter value, bash-``sed``-parity.

    Bash parity: ``grep -m1 -E '^kind:' | sed -E 's/^kind:[[:space:]]*//;
    s/[[:space:]]+#.*$//; s/[[:space:]]*$//'`` — the FIRST ``^kind:`` line
    only, with the ``kind:`` prefix and any leading whitespace stripped,
    then an inline `` # comment`` suffix (whitespace run + ``#`` to end of
    line) stripped, then trailing whitespace stripped.

    Args:
        lines: The seed file's content, split on ``\\n``.

    Returns:
        The parsed ``kind:`` value (e.g. ``"patch-seed"``), or ``""`` if
        no ``^kind:`` line exists at all.
    """
    for line in lines:
        if line.startswith("kind:"):
            value = line[len("kind:") :]
            value = re.sub(r"^\s*", "", value)
            value = re.sub(r"\s+#.*$", "", value)
            return value.rstrip()
    return ""


# --------------------------------------------------------------------------
# The gate itself.
# --------------------------------------------------------------------------
def _verify(path: Path, *, quiet: bool) -> int:
    """Run every deterministic check over one ``*.seed.md`` and print bash-parity output.

    Bash parity: the body of ``cmd_seed.sh`` from ``content="$(cat
    "$path")"`` through the final ``FAIL:``/``OK:`` verdict line, run in
    the same order, with every ``fail``/``warn``/``emit`` call reproduced
    exactly (including the ``quiet`` gate, which suppresses every line
    this function would otherwise print — the HARD/warn counts, and thus
    the return value, are unaffected by ``quiet``).

    Args:
        path: The ``*.seed.md`` file to check (already confirmed to exist
            as a regular file by the caller).
        quiet: When True, suppress every printed line (``  HARD  ...``,
            ``  warn  ...``, and the final verdict line) — the exit code
            is still computed and returned normally.

    Returns:
        ``0`` if zero HARD failures were found (any number of warnings is
        still a pass); ``1`` if one or more HARD failures were found.
    """
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        raw = fh.read()
    # Bash parity: command substitution ($(cat "$path")) strips EVERY
    # trailing newline character, not just one — see the module docstring's
    # "FILE-READING BASH QUIRK REPRODUCED ON PURPOSE" section.
    content = raw.rstrip("\n")
    lines = content.split("\n")
    total_lines = len(lines)

    hard = 0
    warns = 0

    def emit(message: str) -> None:
        if not quiet:
            typer.echo(message)

    def fail(message: str) -> None:
        nonlocal hard
        hard += 1
        emit(f"  HARD  {message}")

    def warn(message: str) -> None:
        nonlocal warns
        warns += 1
        emit(f"  warn  {message}")

    kind = _extract_kind(lines)
    cap = PATCH_FOOTPRINT_CAP if kind == "patch-seed" else SPRINT_FOOTPRINT_CAP
    warn_at = cap * 3 // 4

    is_canonical = bool(
        re.search(r"\*\*Priority:\*\*|^file_scope:|Phase 0 mesh|\*\*GH:\*\*", content, re.MULTILINE)
    )

    # --- 1. footprint (universal) ---
    if total_lines > cap:
        fail(f"footprint {total_lines} lines > cap {cap} (kind={kind or 'sprint'})")
    elif total_lines > warn_at:
        warn(f"footprint {total_lines} lines > smell threshold {warn_at}")

    # --- 2. TODO/FIXME (universal) ---
    if re.search(r"\b(TODO|FIXME):", content):
        fail("TODO:/FIXME: marker(s) present — resolve before commit")

    # --- 3. Lane-N numbering (universal — #67 firewall) ---
    if re.search(r"\bLane[ \t]+[0-9]", content):
        fail("prescriptive 'Lane N' numbering present — lane decomposition is engineer territory (#67)")

    # --- 4. Sequencing / semver judgments (universal, WARN — fuzzy) ---
    if re.search(r"^\s*\*{0,2}Sequencing:", content, re.MULTILINE):
        warn("'Sequencing:' directive present — sequencing is engineer territory (#67)")
    if re.search(
        r"too (small|big|large) for a (patch|minor|sprint)|should be a (patch|minor|major)|really a (minor|major)",
        content,
        re.IGNORECASE,
    ):
        warn("semver-content judgment present — version tier is the operator's call")

    # --- 5. file_scope paths resolve OR (NEW) (HARD, only if file_scope present) ---
    scope_lines = _extract_scope_block(lines)
    if scope_lines:
        repo_root = _repo_root()
        entries = _parse_scope_entries(scope_lines)
        for entry in entries:
            if not _resolve_one(entry, repo_root):
                fail(f"file_scope path does not resolve and is not marked (NEW): {_first_token(entry)}")
        if not entries:
            warn("file_scope present but no entries parsed — verify paths manually (unrecognized YAML shape)")

    # --- 6. canonical deliverable blocks must carry a **GH:** anchor (HARD, conditional) ---
    blocks = _parse_deliverable_blocks(lines)
    deliverable_blocks = sum(1 for is_del, _ in blocks if is_del)
    missing_gh = sum(1 for is_del, has_gh in blocks if is_del and not has_gh)
    if deliverable_blocks > 0 and missing_gh > 0:
        fail(f"{missing_gh} deliverable block(s) carry a priority but no **GH:** anchor (seed-anchored-by-issues.md)")

    # --- 7. canonical-only WARN checks ---
    if is_canonical:
        mesh_rows = sum(1 for line in lines if re.match(r"^\|\s*[0-9]+\s*\|", line))
        if mesh_rows > 0 and mesh_rows < MIN_MESH_ROWS:
            warn(f"Phase 0 mesh has {mesh_rows} row(s) (< {MIN_MESH_ROWS} recommended)")
        if re.search(r"\*\*Priority:\*\*|\[(CRITICAL|HIGH|MEDIUM|LOW)\]", content):
            if not re.search(r"\[(CRITICAL|HIGH)\]|\*\*Priority:\*\*\s*(CRITICAL|HIGH)", content):
                warn("no deliverable ranked CRITICAL or HIGH — confirm this sprint earns a slot")
        if not re.search(r"^milestone:", content, re.MULTILINE):
            warn("frontmatter missing 'milestone:' (engineer + critic parse it)")
        if not re.search(r"^kind:", content, re.MULTILINE):
            warn("frontmatter missing 'kind:' (sprint-seed | patch-seed)")

    # --- verdict ---
    if hard > 0:
        emit(f"FAIL: {hard} hard failure(s), {warns} warning(s)")
        return 1
    emit(f"OK: 0 hard failures, {warns} warning(s)")
    return 0


# --------------------------------------------------------------------------
# Dispatch + Typer wiring.
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> int:
    """Reproduce ``cmd_seed.sh``'s top-level ``case``/``while`` dispatch by hand.

    Bash parity: ``sub="${1:-}"; shift || true; case "$sub" in ...``,
    followed (only for ``sub == "verify"``) by the ``--quiet``/``<path>``
    flag loop and the two existence checks.

    Args:
        argv: Every raw token after ``seed`` on the command line, in
            order, completely unparsed by Click (see the module
            docstring's "SINGLE VARIADIC CALLBACK" section for why).

    Returns:
        The process exit code: ``2`` for any usage error (no/unrecognized
        subcommand, unknown flag, missing/nonexistent ``<path>``); ``0``
        for the bare/``help``/``--help``/``-h`` usage branch; otherwise
        whatever :func:`_verify` returns (``0`` or ``1``).
    """
    sub = argv[0] if argv else ""
    rest = argv[1:]

    if sub in ("", "help", "--help", "-h"):
        typer.echo(_USAGE)
        return 0
    if sub != "verify":
        typer.echo(f"unknown subcommand: {sub}", err=True)
        typer.echo(_USAGE, err=True)
        return 2

    quiet = False
    path_str = ""
    for token in rest:
        if token == "--quiet":
            quiet = True
        elif token.startswith("-"):
            typer.echo(f"unknown flag: {token}", err=True)
            return 2
        else:
            path_str = token  # bash parity: last non-flag token wins

    if not path_str:
        typer.echo("ERR: seed verify needs a <path>", err=True)
        return 2
    path = Path(path_str)
    if not path.is_file():
        typer.echo(f"ERR: no such file: {path_str}", err=True)
        return 2

    return _verify(path, quiet=quiet)


@app.callback(invoke_without_command=True, context_settings={"ignore_unknown_options": True, "help_option_names": []})
def seed(
    args: list[str] = typer.Argument(
        None,
        help="Subcommand + args: 'verify <path> [--quiet]'. No subcommand prints usage and exits 0.",
    ),
) -> None:
    """Deterministic pre-flight gate for a ``*.seed.md`` — native port of ``shctx seed``.

    See the module docstring for why this is ONE variadic callback rather
    than a real ``@app.command("verify")``: bash's usage-on-no-args
    (exit 0), unknown-subcommand (exit 2, custom message), and
    unknown-flag-inside-``verify`` (exit 2, no usage text) contracts don't
    match Typer/Click's own subcommand-dispatch defaults.

    Args:
        args: Every token after ``seed`` on the command line, in order,
            with NOTHING pre-parsed as flags/options by Click (see
            ``context_settings={"ignore_unknown_options": True}`` on this
            callback, which is what makes a token like ``--quiet`` land
            here as a literal string instead of being consumed as an
            option of the group itself). ``None``/empty means a bare
            ``shepherd seed`` — dispatched as the usage branch, per
            bash's ``sub="${1:-}"`` defaulting to the empty-string case.

    Raises:
        typer.Exit: With the code :func:`_dispatch` computes (``0``, ``1``,
            or ``2`` — see its own docstring).
    """
    exit_code = _dispatch(list(args or []))
    raise typer.Exit(code=exit_code)


__all__ = ["app"]
