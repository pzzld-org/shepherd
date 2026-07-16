"""``shepherd worktree`` — git worktree hygiene helpers (bash: ``cmd_worktree.sh``).

Native port of ``skills/context/scripts/cmd_worktree.sh`` (v5.0.4): four
subcommands that operate directly on ``git worktree`` state — this module
NEVER touches the shepherd registry database at all (unlike
``commands/sprint.py``'s ``close``, which reads ``lane_closures``). Every
piece of state this command reads or writes lives in git itself (worktree
list, branches, commits); the ``worktrees`` table added by
``skills/context/schema/migrations/0008_worktrees.sql`` is written by a
COMPLETELY SEPARATE component (``hooks/scripts/worktree_lifecycle.sh``, a
Claude Code ``WorktreeCreate``/``WorktreeRemove`` hook) and is never read or
written by ``cmd_worktree.sh`` or this port — confirmed by grepping
``cmd_worktree.sh`` for ``shctx_sql``/``sqlite3`` (zero hits). Per hard rule
#7, a command with no DB access needs no ``db.lifespan()`` and no mirror
model module; this module accordingly imports neither
:mod:`shepherd_cli.db` nor any Tortoise model, and no ``models_worktree.py``
is written (see the ``new_model_module``/``new_model_classes`` fields of
this port's return value).

Subcommands (bash-parity, in ``cmd_worktree.sh``'s own doc-comment order)::

    list
        Print all known worktrees with branch + last-commit HEAD + age.

    create-batch <lane-id…> [--from=<branch>] [--prefix=agent-]
        Pre-create one worktree per lane-id at
        ``.claude/worktrees/<prefix><id>``, checked out at the HEAD of
        ``--from`` (default: current branch).

    gc [--older-than=<hours>] [--dry-run] [--all]
        Prune ``.claude/worktrees/agent-*`` entries whose last-commit
        timestamp is older than ``--older-than`` (default 24h). ``--all``
        is an alias for ``--older-than=0``.

    merge <agent-id> [--strategy=theirs|prompt] [--no-cleanup]
        Cherry-pick the worktree's HEAD onto the current branch, then
        (unless ``--no-cleanup``) remove the worktree.

Every git-mutating operation below shells out to the EXACT same ``git``
argv bash invokes (``git -C <path> worktree add ...``, ``git -C <path>
cherry-pick ...``, etc.) — per hard rule #9, this module drives real ``git``
subprocesses rather than reimplementing any worktree/cherry-pick semantics
natively, and streams/suppresses each command's stdout/stderr exactly where
bash's own (un-)redirected invocation does.

**Top-level dispatch mirrors bash's own ``sub="${1:-list}"; shift || true``
exactly**: a bare ``shepherd worktree`` (no subcommand at all) DEFAULTS TO
``list`` — NOT a usage screen (unlike ``commands/sprint.py``'s
no-subcommand branch, which prints usage and exits 0). Only the LITERAL
first token ``-h``/``--help``/``help`` (i.e. when it lands in the
subcommand-name slot, exactly as bash's ``sub`` case-matches it) prints the
full top-level usage block — to STDOUT, exit 0 (bash: an unredirected
``cat <<'EOF'`` heredoc). Any other unrecognized first token is
``"ERROR: unknown subcommand: <token>" `` on stderr, exit 1 (bash's
``case``'s catch-all ``*)`` arm).

**A critical, easy-to-miss asymmetry preserved exactly**: each of
``create-batch``/``gc``/``merge``'s OWN ``-h``/``--help`` arm writes its
one-or-few-line usage summary to STDERR (bash: ``echo "..." >&2; exit 0``)
— stderr, yet still EXIT 0 — a different stream than the top-level help
(stdout). ``list`` has NO ``-h``/``--help`` handling of its own at all:
bash's ``list)`` case body never references ``"$@"``, so any trailing
tokens after ``list`` (including ``-h``) are silently ignored and a normal
listing still runs; this port's :func:`_cmd_list` takes no ``argv`` at all,
reproducing that exact silence.

Argument-parsing shape differs per subcommand, all bash-verbatim:

- ``create-batch``: ``--from=*``/``--from <val>``/``--prefix=*``/
  ``--prefix <val>`` are recognized flags; any OTHER token starting with
  ``--`` is an unknown-flag error, but a bare (non-``--``) token is
  APPENDED to the lane-id list (``lanes+=("$1")``) — multiple positional
  tokens accumulate, they do not overwrite each other.
- ``merge``: ``--strategy=*``/``--no-cleanup`` are recognized; any other
  ``--``-prefixed token is an unknown-flag error, but a bare token
  OVERWRITES ``agent`` (plain reassignment — last bare token wins, unlike
  ``create-batch``'s accumulating list).
- ``gc``: ``--older-than=*``/``--all``/``--dry-run`` are recognized; its
  catch-all arm is a bare ``*)`` (not ``--*)``), so ANY unrecognized
  token — flag-shaped or not — is an unknown-flag error. ``gc`` accepts no
  positional arguments at all.

Two documented, deliberate simplifications where bash relies on a broader
mechanism than this port reproduces bit-for-bit (both concern only
degenerate/adversarial inputs that never arise from this command's own
``create-batch``-generated branch names):

- ``gc``'s "no other worktree still references this branch" check
  (``git worktree list | grep -q "$br"``) is a basic-regex SUBSTRING/
  pattern match in bash; this port does a plain Python substring
  containment check instead of treating ``br`` as a regex. For every
  branch name this command itself ever generates (``<prefix><lane-id>``,
  alphanumerics/dashes only) the two are equivalent — only a branch name
  containing regex metacharacters could observably differ, which is not a
  scenario ``cmd_worktree.sh`` or its callers (``cmd_sprint.sh close``)
  ever produce.
- An invalid (non-integer) ``--older-than`` value is UNGUARDED in bash —
  ``$(( older * 3600 ))`` with a non-numeric ``older`` is a bash arithmetic
  syntax error that aborts the script (exit status 1, bash's own
  diagnostic on stderr, no clean message). This port catches that case
  explicitly with a clear ``"ERROR: --older-than must be an integer, got:
  <value>"`` message on stderr, exit 1 — strictly friendlier than bash's
  raw arithmetic-error crash, at the same exit code, for an input bash
  itself never validates or documents.

No ``models_worktree.py`` is written — see the module docstring's opening
paragraph.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import typer

from shepherd_cli.resolution import resolve_repo_root

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    # help_option_names=[] disables Click's own --help so -h/--help reach
    # this module's own token-loop dispatch and print the verbatim bash
    # usage text (parity) — matching commands/sync.py / audit.py / search.py.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    help="Worktree hygiene: list, create-batch, gc, merge.",
)

#: Verbatim bash-parity TOP-LEVEL usage text — the ``-h|--help|help``
#: heredoc in ``cmd_worktree.sh``. Printed to STDOUT (bash: an unredirected
#: ``cat`` heredoc), exit 0. Reached only when the literal FIRST token is
#: ``-h``/``--help``/``help`` (bash's ``sub`` case match) — never when one
#: of those strings appears as a later argument to a real subcommand.
_TOP_HELP_TEXT = (
    "shctx worktree <subcommand>\n"
    "\n"
    "  list                                                   list worktrees with branch + age\n"
    "  create-batch <lane-id…> [--from=<branch>] [--prefix=]  pre-create per-lane worktrees from sprint HEAD\n"
    "  gc   [--older-than=<hours> | --all] [--dry-run]        prune stale agent worktrees (default 24h)\n"
    "  merge <agent-id> [--strategy=...] [--no-cleanup]       cherry-pick + cleanup\n"
    "\n"
    "Per skills/shepherd/references/flock.md §@conductor the conductor never `cd`'s into a worktree —\n"
    "this command uses `git -C <path>` and stays at sprint root."
)

#: Verbatim bash-parity ``create-batch -h|--help`` text — THREE separate
#: ``echo ... >&2`` lines in ``cmd_worktree.sh``, joined here by ``\n`` for
#: a single :func:`typer.echo` call. Printed to STDERR, exit 0.
_CREATE_BATCH_HELP = (
    "shctx worktree create-batch <lane-id…> [--from=<branch>] [--prefix=agent-]\n"
    "  Pre-creates one worktree per lane-id at .claude/worktrees/<prefix><id>\n"
    "  rooted at the HEAD of --from (default: current branch)."
)

#: Verbatim bash-parity ``gc -h|--help`` text. Printed to STDERR, exit 0.
_GC_HELP = "shctx worktree gc [--older-than=<hours> | --all] [--dry-run]"

#: Verbatim bash-parity ``merge -h|--help`` text. Printed to STDERR, exit 0.
_MERGE_HELP = "shctx worktree merge <agent-id> [--strategy=theirs|prompt] [--no-cleanup]"


# --------------------------------------------------------------------------
# Shared: list_worktrees() / age_hours() (bash: cmd_worktree.sh's own
# helpers of the same name, used by `list`, `gc`, and `merge` alike).
# --------------------------------------------------------------------------
def _age_hours(then: int) -> int:
    """Integer hours elapsed since ``then`` (epoch seconds), truncated toward zero.

    Bash::

        age_hours() {
          local then="$1" now
          now=$(shctx_now)
          echo $(( (now - then) / 3600 ))
        }

    ``shctx_now()`` (``date +%s``) is called fresh on every invocation, not
    memoized across rows — reproduced here via a fresh ``time.time()`` call
    each time this is invoked, matching bash's own (mildly) non-deterministic
    per-row timing. Bash's ``$(( ))`` integer division truncates toward
    zero, not Python's floor-toward-negative-infinity ``//`` — reproduced
    via ``int(x / y)`` (float division then truncation) rather than ``//``,
    since a worktree's last-commit timestamp can in principle be in the
    future (clock skew, injected test fixtures), which would make ``now -
    then`` negative.

    Args:
        then: The worktree's last-commit epoch-seconds timestamp (0 if it
            could not be determined — see :func:`_list_worktrees`).

    Returns:
        Whole hours elapsed, truncated toward zero.
    """
    now = int(time.time())
    return int((now - then) / 3600)


def _list_worktrees(repo: str) -> list[tuple[str, str, str, int]]:
    """Enumerate every non-main worktree: ``(abs_path, branch, head_sha, last_commit_epoch)``.

    Bash::

        list_worktrees() {
          git -C "$repo" worktree list --porcelain | awk '
            /^worktree / { wt=$2 }
            /^branch /   { br=$2 }
            /^HEAD /     { sha=$2 }
            /^$/ {
              if (wt && wt != "" && wt != ENVIRON["REPO"]) {
                print wt"|"br"|"sha
              }
              wt=""; br=""; sha=""
            }
          ' REPO="$repo" | while IFS='|' read -r wt br sha; do
            [[ -n "$wt" ]] || continue
            if [[ -d "$wt" ]]; then
              ts=$(git -C "$wt" log -1 --format=%ct 2>/dev/null || echo 0)
            else
              ts=0
            fi
            echo "$wt|${br#refs/heads/}|$sha|$ts"
          done
        }

    ``git worktree list --porcelain`` emits one record per worktree,
    fields on their own lines, records separated by a blank line (verified:
    every record — including the last — is blank-line-terminated, so no
    "flush the final pending block" special case is needed here, matching
    the awk pattern's own ``/^$/``-triggered emit). The MAIN worktree (the
    one matching ``repo`` exactly) is excluded, exactly like the awk guard
    ``wt != ENVIRON["REPO"]`` — every OTHER field (``branch``/``HEAD``)
    line inside a block simply overwrites the running ``wt``/``br``/``sha``
    locals, matching the awk script's own field-by-field accumulation.

    For each surviving worktree, ``refs/heads/`` is stripped from the
    branch ref (a detached worktree's ``branch`` line is absent entirely,
    leaving ``br`` as the empty string, matching bash's uninitialized-var
    default). The last-commit timestamp is 0 when the worktree directory no
    longer exists on disk (a stale/removed worktree git still lists) OR
    when ``git log`` fails/returns empty output for it (bash: ``|| echo
    0``, reproduced by defaulting ``ts`` to 0 on any non-zero exit or blank
    stdout).

    Args:
        repo: The absolute repo root (``git -C`` target for both the
            ``worktree list`` call and validating each worktree's own
            ``git log``).

    Returns:
        One 4-tuple per non-main worktree, in the SAME order
        ``git worktree list --porcelain`` emits them (main worktree first
        in git's own output, but excluded here — so this is typically
        creation/registration order for the rest).
    """
    listing = subprocess.run(
        ["git", "-C", repo, "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )

    raw_entries: list[tuple[str, str, str]] = []
    wt = br = sha = ""
    for line in listing.stdout.splitlines():
        if line.startswith("worktree "):
            wt = line[len("worktree ") :]
        elif line.startswith("branch "):
            br = line[len("branch ") :]
        elif line.startswith("HEAD "):
            sha = line[len("HEAD ") :]
        elif line == "":
            if wt and wt != repo:
                raw_entries.append((wt, br, sha))
            wt = br = sha = ""

    entries: list[tuple[str, str, str, int]] = []
    for path, branch_ref, head_sha in raw_entries:
        branch = branch_ref[len("refs/heads/") :] if branch_ref.startswith("refs/heads/") else branch_ref
        ts = 0
        if os.path.isdir(path):
            log = subprocess.run(
                ["git", "-C", path, "log", "-1", "--format=%ct"],
                capture_output=True,
                text=True,
                check=False,
            )
            if log.returncode == 0:
                stripped = log.stdout.strip()
                if stripped:
                    try:
                        ts = int(stripped)
                    except ValueError:
                        ts = 0
        entries.append((path, branch, head_sha, ts))
    return entries


# --------------------------------------------------------------------------
# `list`
# --------------------------------------------------------------------------
def _cmd_list(repo: str) -> None:
    """Print every worktree as a fixed-width table: PATH BRANCH HEAD AGE.

    Bash::

        printf '%-60s %-30s %-12s %s\\n' PATH BRANCH HEAD AGE
        while IFS='|' read -r wt br sha ts; do
          [[ -n "$wt" ]] || continue
          ah=$(age_hours "$ts")
          printf '%-60s %-30s %-12s %sh\\n' "${wt#$repo/}" "$br" "${sha:0:10}" "$ah"
        done < <(list_worktrees)

    ``${wt#$repo/}`` strips the ``<repo>/`` prefix from the absolute
    worktree path when present, leaving a repo-relative display path
    (reproduced via a plain ``str.startswith``/slice check, not
    ``os.path.relpath``, since bash's ``#`` prefix-strip only fires on an
    EXACT literal prefix match — a worktree path that is not actually
    rooted under ``repo`` is left fully absolute, unchanged). ``${sha:0:10}``
    takes the first 10 characters of the full 40-character commit SHA.

    Takes no ``argv`` at all — bash's ``list)`` case body never references
    ``"$@"``, so any trailing tokens the caller passed after ``list``
    (including ``-h``/``--help``) are silently ignored; this signature
    enforces that by construction.

    Args:
        repo: The absolute repo root, as resolved by
            :func:`shepherd_cli.resolution.resolve_repo_root`.
    """
    typer.echo(f"{'PATH':<60} {'BRANCH':<30} {'HEAD':<12} AGE")
    for wt, br, sha, ts in _list_worktrees(repo):
        if not wt:
            continue
        display_path = wt[len(repo) + 1 :] if wt.startswith(repo + "/") else wt
        typer.echo(f"{display_path:<60} {br:<30} {sha[:10]:<12} {_age_hours(ts)}h")


# --------------------------------------------------------------------------
# `create-batch`
# --------------------------------------------------------------------------
def _parse_create_batch_args(argv: list[str]) -> tuple[str, str, list[str]]:
    """Parse ``create-batch``'s flags, mirroring bash's ``while ... case`` loop.

    Bash::

        while (( $# > 0 )); do
          case "$1" in
            --from=*)   from_branch="${1#*=}" ;;
            --from)     shift; from_branch="${1:-}" ;;
            --prefix=*) prefix="${1#*=}" ;;
            --prefix)   shift; prefix="${1:-}" ;;
            -h|--help)  echo "..." >&2; ...; exit 0 ;;
            --*) echo "ERROR: unknown flag: $1" >&2; exit 1 ;;
            *)   lanes+=("$1") ;;
          esac
          shift
        done

    The bare (no ``=``) ``--from``/``--prefix`` forms consume the NEXT
    token as their value: bash's own ``shift`` inside the case arm PLUS the
    loop's own trailing ``shift`` together advance past both the flag and
    its value token — reproduced here by advancing the index by 2 total for
    those two arms (one inside the branch, one via the loop's own
    increment). A bare token that is the LAST argument (nothing left to
    consume as the value) yields an empty-string value, matching bash's
    ``"${1:-}"`` default.

    Args:
        argv: Every token given after ``create-batch`` on the command line.

    Returns:
        ``(from_branch, prefix, lanes)`` — ``from_branch`` empty string if
        never given (resolved later against the current branch);
        ``prefix`` defaults to ``"agent-"``; ``lanes`` is every bare
        (non-``--``-prefixed) token, in the order given, possibly empty.

    Raises:
        typer.Exit: code 0, after printing :data:`_CREATE_BATCH_HELP` to
            STDERR, on ``-h``/``--help``. Code 1, after printing
            ``"ERROR: unknown flag: <token>"`` to stderr, on any other
            ``--``-prefixed token.
    """
    from_branch = ""
    prefix = "agent-"
    lanes: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]
        if tok.startswith("--from="):
            from_branch = tok[len("--from=") :]
        elif tok == "--from":
            i += 1
            from_branch = argv[i] if i < n else ""
        elif tok.startswith("--prefix="):
            prefix = tok[len("--prefix=") :]
        elif tok == "--prefix":
            i += 1
            prefix = argv[i] if i < n else ""
        elif tok in ("-h", "--help"):
            typer.echo(_CREATE_BATCH_HELP, err=True)
            raise typer.Exit(code=0)
        elif tok.startswith("--"):
            typer.echo(f"ERROR: unknown flag: {tok}", err=True)
            raise typer.Exit(code=1)
        else:
            lanes.append(tok)
        i += 1
    return from_branch, prefix, lanes


def _cmd_create_batch(repo: str, argv: list[str]) -> None:
    """Pre-create one worktree per lane-id at ``.claude/worktrees/<prefix><id>``.

    Bash parity, in order: parse flags -> require >=1 lane-id (exit 1) ->
    resolve ``from_branch`` to the current branch if unset (``git
    symbolic-ref --short HEAD``; exit 1 on detached HEAD) -> verify
    ``from_branch`` exists (``git rev-parse --verify``; exit 1 if not) ->
    resolve ``base_sha`` (``git rev-parse <from_branch>``) -> ``mkdir -p``
    the worktrees dir -> for each lane: skip if the target dir already
    exists; reuse an existing same-named branch (warning if it points
    somewhere other than ``base_sha``) via ``git worktree add <path>
    <branch>``, else create a fresh branch via ``git worktree add -b
    <branch> <path> <from_branch>`` -> print a per-lane "created" line and
    the final summary + ``[BASE-COMMIT-EXPECTED]`` line.

    Every ``git worktree add`` invocation is UNCAPTURED (bash: no
    redirection at all on those calls) — its own stdout/stderr stream
    straight through to this process's, exactly like bash's own
    unredirected invocation. None of those calls has a bash ``||`` guard
    either: a non-zero exit from ANY of them aborts immediately under
    bash's ``set -e`` with that exact exit code and whatever git already
    printed to stderr — reproduced here by propagating the child's
    ``returncode`` via ``typer.Exit`` the instant it is non-zero, with NO
    additional message of this port's own (git's own diagnostic, already
    streamed, is the only error output — matching bash exactly).

    Args:
        repo: The absolute repo root.
        argv: Every token given after ``create-batch``.

    Raises:
        typer.Exit: code 1 if no lane-id was given, HEAD is detached with
            no ``--from``, or ``--from=<branch>`` does not exist. The exact
            non-zero return code of the first failing ``git`` subprocess
            (``rev-parse``/``worktree add``) if one fails outright. See
            :func:`_parse_create_batch_args` for flag-parsing exits.
    """
    from_branch, prefix, lanes = _parse_create_batch_args(argv)
    if not lanes:
        typer.echo("ERROR: at least one lane-id required", err=True)
        raise typer.Exit(code=1)

    if not from_branch:
        symbolic = subprocess.run(
            ["git", "-C", repo, "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        from_branch = symbolic.stdout.strip() if symbolic.returncode == 0 else ""
        if not from_branch:
            typer.echo("ERROR: detached HEAD; pass --from=<branch>", err=True)
            raise typer.Exit(code=1)

    verify = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--verify", from_branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if verify.returncode != 0:
        typer.echo(f"ERROR: --from={from_branch} does not exist", err=True)
        raise typer.Exit(code=1)

    base_sha_result = subprocess.run(
        ["git", "-C", repo, "rev-parse", from_branch],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if base_sha_result.returncode != 0:
        raise typer.Exit(code=base_sha_result.returncode)
    base_sha = base_sha_result.stdout.strip()

    os.makedirs(os.path.join(repo, ".claude", "worktrees"), exist_ok=True)
    created = 0
    for lane in lanes:
        wt_path = os.path.join(repo, ".claude", "worktrees", f"{prefix}{lane}")
        wt_branch = f"{prefix}{lane}"
        if os.path.isdir(wt_path):
            typer.echo(f"skip {prefix}{lane}: {wt_path} already exists")
            continue

        branch_exists = (
            subprocess.run(
                ["git", "-C", repo, "rev-parse", "--verify", wt_branch],
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            == 0
        )
        if branch_exists:
            existing_sha_result = subprocess.run(
                ["git", "-C", repo, "rev-parse", wt_branch],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
            )
            if existing_sha_result.returncode != 0:
                raise typer.Exit(code=existing_sha_result.returncode)
            existing_sha = existing_sha_result.stdout.strip()
            if existing_sha != base_sha:
                typer.echo(f"WARN {prefix}{lane}: branch exists at {existing_sha} (expected {base_sha})")
            add_result = subprocess.run(["git", "-C", repo, "worktree", "add", wt_path, wt_branch], check=False)
        else:
            add_result = subprocess.run(
                ["git", "-C", repo, "worktree", "add", "-b", wt_branch, wt_path, from_branch], check=False
            )
        if add_result.returncode != 0:
            raise typer.Exit(code=add_result.returncode)

        typer.echo(f"created {prefix}{lane}: {wt_path} (base={base_sha[:10]})")
        created += 1

    typer.echo(f"shctx worktree create-batch: created {created} worktrees from {from_branch} ({base_sha[:10]})")
    typer.echo(f"[BASE-COMMIT-EXPECTED] for coder briefs: {base_sha}")


# --------------------------------------------------------------------------
# `gc`
# --------------------------------------------------------------------------
def _parse_gc_args(argv: list[str]) -> tuple[str, bool]:
    """Parse ``gc``'s flags, mirroring bash's ``for arg in "$@"`` loop.

    Bash::

        older=24
        dry=0
        for arg in "$@"; do
          case "$arg" in
            --older-than=*) older="${arg#*=}" ;;
            --all)          older=0 ;;
            --dry-run)      dry=1 ;;
            -h|--help) echo "..." >&2; exit 0 ;;
            *) echo "ERROR: unknown flag: $arg" >&2; exit 1 ;;
          esac
        done

    Note the catch-all arm is a bare ``*)`` (NOT ``--*)`` as in
    ``create-batch``/``merge``) — ``gc`` accepts no positional arguments
    at all; any token that is not one of the four recognized shapes is an
    unknown-flag error, flag-shaped or not.

    ``older`` is kept as the RAW string bash would hold (the literal
    ``--older-than=<value>`` text, or ``"24"``/``"0"`` for the untouched-
    default/``--all`` cases) rather than pre-parsed to an int — bash's own
    ``${older}h`` in the final summary line echoes whatever string form was
    given verbatim (e.g. a leading-zero value like ``"048"``), and the
    caller (:func:`_cmd_gc`) is responsible for both that verbatim echo and
    the int conversion used in the threshold arithmetic.

    Args:
        argv: Every token given after ``gc`` on the command line.

    Returns:
        ``(older, dry)`` — ``older`` as the raw string form (default
        ``"24"``), ``dry`` True if ``--dry-run`` was given.

    Raises:
        typer.Exit: code 0, after printing :data:`_GC_HELP` to stderr, on
            ``-h``/``--help``. Code 1, after printing ``"ERROR: unknown
            flag: <token>"`` to stderr, on any other unrecognized token.
    """
    older = "24"
    dry = False
    for arg in argv:
        if arg.startswith("--older-than="):
            older = arg[len("--older-than=") :]
        elif arg == "--all":
            older = "0"
        elif arg == "--dry-run":
            dry = True
        elif arg in ("-h", "--help"):
            typer.echo(_GC_HELP, err=True)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown flag: {arg}", err=True)
            raise typer.Exit(code=1)
    return older, dry


def _cmd_gc(repo: str, argv: list[str]) -> None:
    """Prune stale ``.claude/worktrees/agent-*`` entries.

    Bash parity, in order: parse flags -> compute ``threshold = shctx_now()
    - older*3600`` -> for each worktree from :func:`_list_worktrees` whose
    path contains ``/.claude/worktrees/agent-`` AND whose last-commit
    timestamp is strictly older than ``threshold``: either print a
    ``[dry-run] would prune ...`` line (``--dry-run``) or actually remove it
    (``git worktree remove --force``, falling back to a plain recursive
    delete if that fails — matching bash's own ``|| rm -rf "$wt"``) and,
    when the worktree HAD a branch name and no other worktree still
    references it, best-effort delete that branch too (``git branch -D``,
    errors swallowed) -> always run ``git worktree prune`` at the end,
    unconditionally, regardless of ``--dry-run`` -> print the final summary
    line.

    Args:
        repo: The absolute repo root.
        argv: Every token given after ``gc``.

    Raises:
        typer.Exit: code 1, after printing ``"ERROR: --older-than must be
            an integer, got: <value>"`` to stderr, if ``--older-than``'s
            value is not a base-10 integer — a friendlier, same-exit-code
            substitute for bash's own unguarded arithmetic-syntax crash on
            the same input (see the module docstring's deviations list).
            See :func:`_parse_gc_args` for flag-parsing exits.
    """
    older, dry = _parse_gc_args(argv)
    try:
        older_int = int(older)
    except ValueError:
        typer.echo(f"ERROR: --older-than must be an integer, got: {older}", err=True)
        raise typer.Exit(code=1) from None

    threshold = int(time.time()) - older_int * 3600
    pruned = 0
    for wt, br, _sha, ts in _list_worktrees(repo):
        if not wt:
            continue
        if "/.claude/worktrees/agent-" not in wt:
            continue
        if not (ts < threshold):
            continue

        if dry:
            typer.echo(f"[dry-run] would prune {wt} (branch={br}, age={_age_hours(ts)}h)")
        else:
            typer.echo(f"pruning {wt} (branch={br}, age={_age_hours(ts)}h)")
            remove = subprocess.run(
                ["git", "-C", repo, "worktree", "remove", "--force", wt],
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if remove.returncode != 0:
                shutil.rmtree(wt, ignore_errors=True)
            if br:
                still_listed = subprocess.run(
                    ["git", "-C", repo, "worktree", "list"],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout
                # bash: `grep -q "$br"` (basic-regex substring match). A
                # plain substring check is equivalent for every branch name
                # this command itself ever generates — see the module
                # docstring's deviations list.
                if br not in still_listed:
                    subprocess.run(
                        ["git", "-C", repo, "branch", "-D", br],
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
        pruned += 1

    subprocess.run(["git", "-C", repo, "worktree", "prune"], check=False)
    typer.echo(f"shctx worktree gc: pruned {pruned} (threshold {older}h)")


# --------------------------------------------------------------------------
# `merge`
# --------------------------------------------------------------------------
def _parse_merge_args(argv: list[str]) -> tuple[str, str, bool]:
    """Parse ``merge``'s flags, mirroring bash's ``while ... case`` loop.

    Bash::

        while (( $# > 0 )); do
          case "$1" in
            --strategy=*) strategy="${1#*=}" ;;
            --no-cleanup) cleanup=0 ;;
            -h|--help) echo "..." >&2; exit 0 ;;
            --*) echo "ERROR: unknown flag: $1" >&2; exit 1 ;;
            *)   agent="$1" ;;
          esac
          shift
        done

    A bare (non-``--``-prefixed) token OVERWRITES ``agent`` via plain
    variable reassignment — unlike ``create-batch``'s lane-id list, the
    LAST bare token given wins if more than one is passed, not an
    accumulating collection.

    Args:
        argv: Every token given after ``merge`` on the command line.

    Returns:
        ``(agent, strategy, cleanup)`` — ``agent`` empty string if no bare
        token was given; ``strategy`` defaults to ``"prompt"``; ``cleanup``
        defaults to True (``--no-cleanup`` clears it).

    Raises:
        typer.Exit: code 0, after printing :data:`_MERGE_HELP` to stderr,
            on ``-h``/``--help``. Code 1, after printing ``"ERROR: unknown
            flag: <token>"`` to stderr, on any other ``--``-prefixed token.
    """
    agent = ""
    strategy = "prompt"
    cleanup = True
    for tok in argv:
        if tok.startswith("--strategy="):
            strategy = tok[len("--strategy=") :]
        elif tok == "--no-cleanup":
            cleanup = False
        elif tok in ("-h", "--help"):
            typer.echo(_MERGE_HELP, err=True)
            raise typer.Exit(code=0)
        elif tok.startswith("--"):
            typer.echo(f"ERROR: unknown flag: {tok}", err=True)
            raise typer.Exit(code=1)
        else:
            agent = tok
    return agent, strategy, cleanup


def _cmd_merge(repo: str, argv: list[str]) -> None:
    """Cherry-pick a worktree's HEAD onto the current branch, then clean it up.

    Bash parity, in order: parse flags -> require ``agent`` non-empty (exit
    1) -> validate ``--strategy`` is ``theirs``/``prompt`` (exit 1
    otherwise) -> find the FIRST worktree from :func:`_list_worktrees`
    whose path contains the substring ``agent-<agent>`` (bash: ``[[ "$path"
    == *"agent-${agent}"* ]]`` — a fixed ``"agent-"`` prefix, independent of
    whatever ``--prefix`` a ``create-batch`` call may have used; exit 1 if
    none matches or the matched path no longer exists on disk) -> resolve
    its HEAD sha -> cherry-pick that sha onto ``repo`` (``-X theirs`` when
    ``strategy == "theirs"``, plain otherwise) -> on conflict (non-zero
    exit): print the two-line conflict message to stderr and exit with
    that SAME return code, WITHOUT cleaning up the worktree -> on success:
    remove the worktree (unless ``--no-cleanup``) and print the final "ok"
    line.

    The cherry-pick subprocess itself is UNCAPTURED (bash: ``set +e; git
    -C "$repo" cherry-pick ...; rc=$?; set -e`` — no redirection at all) so
    its own conflict/success output streams straight through, exactly
    matching bash.

    Args:
        repo: The absolute repo root (the cherry-pick TARGET).
        argv: Every token given after ``merge``.

    Raises:
        typer.Exit: code 1 if ``agent`` is missing, ``--strategy`` is
            invalid, no matching worktree is found, or the matched
            worktree's directory is missing. The cherry-pick's own
            non-zero exit code, verbatim, on a conflict. See
            :func:`_parse_merge_args` for flag-parsing exits.
    """
    agent, strategy, cleanup = _parse_merge_args(argv)
    if not agent:
        typer.echo("ERROR: agent-id required", err=True)
        raise typer.Exit(code=1)
    if strategy not in ("theirs", "prompt"):
        typer.echo("ERROR: --strategy must be theirs|prompt", err=True)
        raise typer.Exit(code=1)

    needle = f"agent-{agent}"
    wt = ""
    for path, _br, _sha, _ts in _list_worktrees(repo):
        if needle in path:
            wt = path
            break
    if not wt:
        typer.echo(f"ERROR: no worktree matching agent-id '{agent}'", err=True)
        raise typer.Exit(code=1)
    if not os.path.isdir(wt):
        typer.echo(f"ERROR: worktree path missing: {wt}", err=True)
        raise typer.Exit(code=1)

    head_sha_result = subprocess.run(
        ["git", "-C", wt, "rev-parse", "HEAD"],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if head_sha_result.returncode != 0:
        raise typer.Exit(code=head_sha_result.returncode)
    head_sha = head_sha_result.stdout.strip()
    typer.echo(f"shctx worktree merge: cherry-picking {head_sha} from {wt}")

    if strategy == "theirs":
        cherry_argv = ["git", "-C", repo, "cherry-pick", "-X", "theirs", head_sha]
    else:
        cherry_argv = ["git", "-C", repo, "cherry-pick", head_sha]
    rc = subprocess.run(cherry_argv, check=False).returncode

    if rc != 0:
        typer.echo(
            f"shctx worktree merge: cherry-pick had conflicts (rc={rc}). "
            "Resolve, then run `git cherry-pick --continue`.",
            err=True,
        )
        typer.echo(
            "                       Worktree NOT cleaned up; re-run "
            f"`shctx worktree merge {agent} --no-cleanup` after resolution if needed.",
            err=True,
        )
        raise typer.Exit(code=rc)

    if cleanup:
        typer.echo(f"shctx worktree merge: cleanup — removing {wt}")
        remove = subprocess.run(
            ["git", "-C", repo, "worktree", "remove", "--force", wt],
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if remove.returncode != 0:
            shutil.rmtree(wt, ignore_errors=True)
    typer.echo("shctx worktree merge: ok")


# --------------------------------------------------------------------------
# Top-level dispatch — bash: `sub="${1:-list}"; shift || true; case "$sub" in ...`
# --------------------------------------------------------------------------
@app.callback(invoke_without_command=True)
def worktree(
    args: list[str] = typer.Argument(
        None,
        metavar="[list|create-batch <lane-id…>|gc|merge <agent-id>] [args] [-h|--help]",
        hidden=True,
        help=(
            "Bare invocation defaults to 'list' (bash parity) — see "
            "cmd_worktree.sh's usage text (-h/--help) for every subcommand."
        ),
    ),
) -> None:
    """Git worktree hygiene: list, create-batch, gc, merge.

    Native port of ``shctx worktree`` (``cmd_worktree.sh``). Bash resolves
    ``sub="${1:-list}"`` BEFORE any other dispatch — a bare ``shepherd
    worktree`` therefore runs ``list``, NOT a usage screen (unlike
    ``commands/sprint.py``'s no-subcommand branch). Only when the LITERAL
    first token is ``-h``/``--help``/``help`` does the top-level usage
    block print (to stdout, exit 0); any other unrecognized first token is
    ``"ERROR: unknown subcommand: <token>"`` on stderr, exit 1.

    Args:
        args: Every token given after ``worktree`` on the command line, or
            None/empty for a bare ``shepherd worktree`` (bash parity: runs
            ``list`` with no further arguments).

    Raises:
        typer.Exit: code 0 with the top-level usage text on
            ``-h``/``--help``/``help``; code 1 with
            ``"ERROR: unknown subcommand: <token>"`` for anything else
            unrecognized. See :func:`_cmd_create_batch`, :func:`_cmd_list`,
            :func:`_cmd_gc`, and :func:`_cmd_merge` for every other exit
            path, per subcommand.
    """
    argv = list(args) if args else []
    sub = argv[0] if argv else "list"
    rest = argv[1:] if argv else []
    repo = resolve_repo_root()

    if sub in ("-h", "--help", "help"):
        typer.echo(_TOP_HELP_TEXT)
        raise typer.Exit(code=0)
    if sub == "create-batch":
        _cmd_create_batch(repo, rest)
        return
    if sub == "list":
        _cmd_list(repo)
        return
    if sub == "gc":
        _cmd_gc(repo, rest)
        return
    if sub == "merge":
        _cmd_merge(repo, rest)
        return

    typer.echo(f"ERROR: unknown subcommand: {sub}", err=True)
    raise typer.Exit(code=1)


__all__ = ["app"]
