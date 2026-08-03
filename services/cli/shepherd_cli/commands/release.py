"""``shepherd release`` — algorithmic gear-cascade release pipeline (bash: ``cmd_release.sh``).

Native port of ``skills/context/scripts/cmd_release.sh`` (377 LOC): NO
DATABASE — every piece of state this command reads or writes lives in git
itself (branches, tags, commits), in the workspace version files it bumps,
and in one release-notes file under the shepherd workdir. Per hard rule #7,
a command with no DB access needs no ``db.lifespan()``; this module
imports neither :mod:`shepherd_cli.db` nor any Tortoise model.

Two operational modes, auto-detected from the current git branch (bash's
``parse_branch``):

``sprint-end mode``
    Current branch matches the sprint pattern ``v<X>.<Y>.<Z>-dev.<N>``.
    When ``N == sprints_per_patch - 1``: rebase the dev branch into the
    patch branch, then run the full cascade (squash → tag → release → cut
    next). Otherwise (mid-patch): rebase dev into patch, delete the dev
    branch, cut ``dev.{N+1}``, exit 0 — NO cascade.

``lighter-pattern mode``
    Current branch matches the patch pattern ``v<X>.<Y>.<Z>`` directly.
    Skip the rebase step; jump straight to squash → tag → release →
    cascade.

Cascade per major X (unbounded), 10 sprints per patch by default (the
``sprints_per_patch`` config key is wired; the per-level ``mod_base``
overrides for the patch→minor→major ``< 9`` rollover gears are NOT — same
follow-up bash's own header comment defers)::

    Z < 9          → cut X.Y.{Z+1} from main
    Z == 9, Y < 9  → cut X.{Y+1}.0 from main
    Z == 9, Y == 9 → cut {X+1}.0.0 from main

Flag surface (parsed by a manual token loop mirroring bash's ``for a in
"$@"`` — Click's own option machinery is bypassed entirely, exactly like
``commands/worktree.py``/``close_lane.py``, so every error message, help
text, and exit code below is byte-identical to bash):

- ``--dry-run`` — print the plan (``  PLAN: ...`` lines) without executing
  any git/gh action. The default-safe read-only mode.
- ``--skip=tag,gh,bump,push`` — comma-separated steps to skip. An unknown
  step is ``ERROR: unknown skip step: <p>`` on stderr, exit 1. Splitting
  mirrors bash's ``IFS=, read -r -a`` exactly: one trailing empty field is
  dropped (``--skip=tag,`` ≡ ``--skip=tag``), an INTERIOR empty field
  (``--skip=tag,,gh``) errors with an empty step name, and ``--skip=`` is
  a no-op. The space-separated form ``--skip tag`` is NOT recognized
  (bash's ``--skip=*`` glob doesn't match it) — it errors as
  ``ERROR: unknown flag: --skip``.
- ``-h``/``--help`` — verbatim ``usage()`` heredoc to STDOUT, exit 0. The
  bare word ``help`` is NOT special (bash parity: it hits the unknown-flag
  arm).
- Any other token — ``ERROR: unknown flag: <a>`` on stderr, then the usage
  text ALSO on stderr, exit 1.

Bash-parity output shape: every informational line is
``shctx release: ...`` on stdout; every planned/skipped step is
``  PLAN: ...`` on stdout (bash's ``log()``/``plan()``); executed commands
log ``shctx release: exec: <display>`` first, where ``<display>`` is the
EXACT string bash would eval — including the single quotes bash's source
embeds (``git commit -m 'release: shepherd v5.0.0'``). Real git
invocations inherit stdout/stderr (bash's un-redirected ``eval``); a
failing git command aborts the pipeline with that command's own exit code
(bash's ``set -e``).

Config: ``sprints_per_patch`` is read via a line-oriented,
SECTION-AGNOSTIC scan of ``.claude/shepherd.local.toml`` →
``.claude/shepherd.toml`` → ``$XDG_CONFIG_HOME/shepherd.toml`` (falling
back to ``$HOME/.config``), last match wins within a file, first file with
a non-empty value wins — a faithful port of ``_lib.sh``'s ``cfg_get``
grep/sed pipeline, NOT a TOML parse (the key lives under ``[branching]``
and bash's grep deliberately ignores section headers; a real TOML lookup
would miss it). The last digit-run of the value is used
(``grep -oE '[0-9]+' | tail -1``); anything without digits falls back
to 10.

Run-scoped artifact shim (``<workdir>/runs/{run}/`` migration) — the ONE
workdir artifact this command writes is the gh release-notes file, bash:
``$(shctx_artifacts_root)/tmp/release-notes-<tag>.md``. When a run is
identifiable — the ADDITIVE ``--run=<name>`` flag, the ``SHEPHERD_RUN``
env var, or a ``<workdir>/runs/current`` marker, the exact
:func:`shepherd_cli.commands.models_graph.resolve_run` precedence — the
notes file is written to ``<workdir>/runs/<run>/tmp/release-notes-<tag>.md``
instead; with no identifiable run the legacy ``<workdir>/tmp/`` path is
used, reproducing bash byte-for-byte. No legacy READ fallback is needed:
the notes file is created and consumed within the same invocation.

Documented deviations (additive/robustness only — zero change to any
bash-reachable success path):

1. ``--run=<name>`` is an ADDITIVE flag ``cmd_release.sh`` does not have
   (the run-scoped shim above). Only the ``--run=NAME`` form is accepted,
   matching the single-token loop shape of every other flag here.
2. The ``gh release create`` execution goes through :func:`_gh_retry`, a
   faithful port of ``_lib.sh``'s ``shctx_gh_retry`` (same
   ``SHCTX_GH_RETRY_MAX``/``SHCTX_GH_RETRY_BACKOFF`` env knobs, same
   transient markers — HTTP 502/503/504, timeout/timed out/connection
   reset — same exponential ``backoff_base ** attempt`` sleep, same
   ``shctx_gh_retry: ...`` stderr diagnostics). ``cmd_release.sh`` itself
   eval'd ``gh`` directly with no retry; routing through the ported helper
   is the mandated hardening. Observable difference: gh's combined
   stdout+stderr is captured and re-emitted (success → stdout, terminal
   failure → stderr) with trailing newlines stripped, instead of streaming
   — identical to how ``shctx_gh_retry`` itself behaves in bash.
3. Version-file bumping uses stdlib ``json`` instead of shelling to
   ``jq``: key order is preserved and the output shape (2-space indent,
   raw UTF-8, trailing newline) matches jq's default rendering; the
   nested ``plugins[].version`` patch only touches list entries that are
   objects (jq would hard-error on a non-object entry — a shape no
   shipped marketplace.json has ever had).
4. A malformed version file (unparseable JSON) produces a clean
   ``ERROR: bump (json) failed for <path>: ...`` on stderr, exit 1,
   instead of jq's raw parse error — same failure class and exit
   behavior, better message.
5. A non-numeric ``SHCTX_GH_RETRY_MAX``/``SHCTX_GH_RETRY_BACKOFF``
   degrades to the default (3 / 2) instead of bash's arithmetic-context
   abort — mirroring the same documented choice in
   ``commands/close_lane.py``'s ``_int_env``.

No ``--json`` flag: hard rule #7's "--json on every read command" targets
read commands; ``release`` is a pipeline mutator whose read-only face is
``--dry-run``, which must stay byte-identical to bash's plan output.

No ``models_release.py`` is written — the one structured shape here (a
parsed branch name) is the single small :class:`ReleaseBranch` pydantic
model below.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Literal

import typer
from pydantic import BaseModel, ConfigDict

from shepherd_cli.commands.models_graph import resolve_run
from shepherd_cli.resolution import resolve_repo_root, resolve_workdir

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    # help_option_names=[] disables Click's own --help so -h/--help reach
    # this module's own token loop and print the verbatim bash usage text;
    # allow_extra_args + ignore_unknown_options let every raw token
    # (including --flags) land in the callback's args list untouched —
    # matching commands/worktree.py / close_lane.py / prune.py.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    help="Algorithmic gear-cascade release pipeline (rebase → squash → tag → gh release → cut next).",
)

#: Hardcoded main branch — bash: ``MAIN_BRANCH="main"`` (TOML override not
#: yet wired there either; the usage text below says so verbatim).
MAIN_BRANCH = "main"

#: Repo-root-relative changelog path — bash: ``CHANGELOG_PATH``.
CHANGELOG_PATH = "CHANGELOG.md"

#: Default version-file list, in bash's exact ``VERSION_FILES`` order.
#: ``json``: patches the top-level ``"version"`` key (plus any nested
#: ``plugins[].version`` — marketplace.json carries both); ``yaml``:
#: patches the first ``version:`` line; ``readme``: patches the literal
#: ``Current version: **X.Y.Z**`` line.
VERSION_FILES: tuple[tuple[str, str], ...] = (
    (".claude-plugin/plugin.json", "json"),
    ("skills/shepherd/SKILL.md", "yaml"),
    ("skills/context/SKILL.md", "yaml"),
    (".claude-plugin/marketplace.json", "json"),
    ("README.md", "readme"),
)

#: Verbatim bash-parity usage text — ``usage()``'s heredoc in
#: ``cmd_release.sh`` (including the now-stale "TOML overrides not yet
#: wired" line: ``sprints_per_patch`` IS wired, but the text is kept
#: byte-identical to bash's).
_USAGE = (
    "shctx release [--dry-run] [--skip=tag,gh,bump,push]\n"
    "\n"
    "Run the algorithmic gear-cascade release pipeline. Mode is auto-detected from\n"
    "the current git branch:\n"
    "\n"
    "  sprint-end mode  — branch like v0.2.9-dev.5 (rebase → patch close → cascade)\n"
    "  lighter-pattern  — branch like v5.0.0      (squash → tag → release → cascade)\n"
    "\n"
    "Defaults (TOML overrides not yet wired):\n"
    "  patch_branch_pattern  = v{X}.{Y}.{Z}\n"
    "  sprint_branch_pattern = v{X}.{Y}.{Z}-dev.{N}\n"
    "  sprints_per_patch     = 10\n"
    "  main_branch           = main\n"
    "\n"
    "Use --dry-run to print the plan without executing."
)

#: Branch-shape patterns — bash ``parse_branch``'s two ``[[ =~ ]]`` regexes.
_SPRINT_RE = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)-dev\.([0-9]+)$")
_PATCH_RE = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")

#: ``shctx_gh_retry``'s transient-failure substring markers (``_lib.sh``).
_TRANSIENT_MARKERS = ("HTTP 504", "HTTP 502", "HTTP 503", "timeout", "timed out", "connection reset")

#: ``shctx_gh_retry``'s default max attempts / backoff base (``_lib.sh``).
_DEFAULT_GH_RETRY_MAX = 3
_DEFAULT_GH_RETRY_BACKOFF = 2


class ReleaseBranch(BaseModel):
    """One parsed branch name — bash ``parse_branch``'s globals as a model.

    Attributes:
        mode: ``"sprint"`` for ``v<X>.<Y>.<Z>-dev.<N>``, ``"patch"`` for
            ``v<X>.<Y>.<Z>``, ``"none"`` for anything else (including an
            empty/undeterminable branch).
        x: Major component, as the ORIGINAL matched substring (bash keeps
            the string, so a hypothetical leading zero survives into every
            composed branch/tag name). Empty when ``mode == "none"``.
        y: Minor component (same string semantics).
        z: Patch component (same string semantics).
        sprint_n: Sprint number ``N`` (sprint mode only; empty otherwise).
    """

    model_config = ConfigDict(from_attributes=True)

    mode: Literal["sprint", "patch", "none"]
    x: str = ""
    y: str = ""
    z: str = ""
    sprint_n: str = ""


# --------------------------------------------------------------------------
# Output + execution helpers — bash's log() / plan() / run().
# --------------------------------------------------------------------------
def _log(msg: str) -> None:
    """``log()``: ``shctx release: <msg>`` on stdout, flushed immediately.

    The explicit flush keeps Python-buffered lines ordered ahead of any
    child git process writing straight to the inherited fd (bash has no
    such buffering seam).
    """
    typer.echo(f"shctx release: {msg}")
    sys.stdout.flush()


def _plan(msg: str) -> None:
    """``plan()``: ``  PLAN: <msg>`` on stdout, flushed immediately."""
    typer.echo(f"  PLAN: {msg}")
    sys.stdout.flush()


def _run(dry_run: bool, display: str, argv: list[str]) -> None:
    """Bash's ``run()``: plan in dry-run mode, else log ``exec:`` and execute.

    Args:
        display: The EXACT string bash would print/eval (quotes included
            where bash's source embeds them) — parity for both the
            ``  PLAN:`` and ``exec:`` renderings.
        argv: The real argument vector to execute (shell-quoting already
            resolved, as bash's ``eval`` would resolve it).

    Raises:
        typer.Exit: with the child's own exit code when it fails — bash's
            ``set -e`` abort semantics, same code, same streamed stderr
            (the child inherits stdout/stderr, like bash's un-redirected
            ``eval``).
    """
    if dry_run:
        _plan(display)
        return
    _log(f"exec: {display}")
    proc = subprocess.run(argv, check=False)
    if proc.returncode != 0:
        raise typer.Exit(code=proc.returncode)


def _git_capture(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` capturing output (for the read-only probes)."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


# --------------------------------------------------------------------------
# Read-only git probes — current_branch / tag_exists / already_merged.
# --------------------------------------------------------------------------
def _current_branch() -> str:
    """``current_branch()``: ``git rev-parse --abbrev-ref HEAD`` or ``""``."""
    proc = _git_capture("rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode == 0:
        return proc.stdout.strip()
    return ""


def _tag_exists(tag: str) -> bool:
    """``tag_exists()``: ``git rev-parse --verify --quiet refs/tags/<tag>``."""
    return _git_capture("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0


def _already_merged_into_main(branch: str) -> bool:
    """``already_merged_into_main()``: is ``branch`` an ancestor of main?

    Bash suppresses stderr (``2>/dev/null``); capture does the same.
    """
    return _git_capture("merge-base", "--is-ancestor", branch, MAIN_BRANCH).returncode == 0


# --------------------------------------------------------------------------
# Branch parsing + version cascade.
# --------------------------------------------------------------------------
def _parse_branch(branch: str) -> ReleaseBranch:
    """``parse_branch()``: classify one branch name into mode + components."""
    m = _SPRINT_RE.match(branch)
    if m:
        return ReleaseBranch(mode="sprint", x=m.group(1), y=m.group(2), z=m.group(3), sprint_n=m.group(4))
    m = _PATCH_RE.match(branch)
    if m:
        return ReleaseBranch(mode="patch", x=m.group(1), y=m.group(2), z=m.group(3))
    return ReleaseBranch(mode="none")


def _next_version(x: int, y: int, z: int) -> tuple[int, int, int]:
    """``next_version()``: the mod-10 patch→minor→major gear cascade.

    The ``< 9`` rollover bases are hardcoded exactly as bash's are (its own
    header comment defers wiring ``[branching].mod_base`` per level).
    """
    if z < 9:
        return x, y, z + 1
    if y < 9:
        return x, y + 1, 0
    return x + 1, 0, 0


# --------------------------------------------------------------------------
# Config — cfg_get port (line-oriented, section-agnostic; see module doc).
# --------------------------------------------------------------------------
def _config_search_paths(repo_root: str) -> tuple[str, str, str]:
    """The three config files ``cfg_get`` checks, in precedence order.

    Same local → project → XDG chain as ``commands/models.py``'s
    ``_config_search_paths`` (``${XDG_CONFIG_HOME:-$HOME/.config}``
    semantics: an EMPTY env var falls back too, like bash's ``:-``).
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or ""
    if not xdg_config_home:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        xdg_config_home = os.path.join(home, ".config")
    return (
        os.path.join(repo_root, ".claude", "shepherd.local.toml"),
        os.path.join(repo_root, ".claude", "shepherd.toml"),
        os.path.join(xdg_config_home, "shepherd.toml"),
    )


def _cfg_get(key: str, repo_root: str) -> str:
    """Port of ``_lib.sh``'s ``cfg_get`` grep/sed pipeline (NOT a TOML parse).

    Line-oriented and section-AGNOSTIC: matches ``^\\s*<key>\\s*=`` under
    any ``[section]`` (bash's grep never looks at headers — that is load-
    bearing here, since ``sprints_per_patch`` lives under ``[branching]``).
    Last match wins within a file; the first file whose stripped value is
    non-empty wins overall. Stripping mirrors bash's sed: drop everything
    through the first ``=`` plus following whitespace, drop a trailing
    ``<whitespace>#...`` inline comment, strip ONE surrounding double-quote
    pair.

    Returns:
        The stripped value, or ``""`` when unset everywhere (bash echoes
        ``""`` and never returns non-zero).
    """
    key_re = re.compile(r"^[ \t]*" + re.escape(key) + r"[ \t]*=")
    for path in _config_search_paths(repo_root):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        value = ""
        for line in lines:
            if not key_re.match(line):
                continue
            v = re.sub(r"^[^=]*=[ \t]*", "", line)
            v = re.sub(r"[ \t]+#.*$", "", v)
            v = re.sub(r'^"', "", v)
            v = re.sub(r'"$', "", v)
            value = v  # last match wins, even if it strips to empty
        if value:
            return value
    return ""


def _sprints_per_patch(repo_root: str) -> int:
    """The mod-N cascade base — bash's ``SPRINTS_PER_PATCH`` block.

    ``cfg_get sprints_per_patch | grep -oE '[0-9]+' | tail -1``: the LAST
    digit-run of the configured value; anything without digits (including
    an unset key) falls back to 10.
    """
    raw = _cfg_get("sprints_per_patch", repo_root)
    digit_runs = re.findall(r"[0-9]+", raw)
    if not digit_runs:
        return 10
    return int(digit_runs[-1])


# --------------------------------------------------------------------------
# Release notes extraction + notes-file path (run-scoped shim).
# --------------------------------------------------------------------------
def _extract_release_notes(version: str, changelog_path: str) -> str:
    """``extract_release_notes()``: the vX.Y.Z section body from CHANGELOG.md.

    awk parity: find the first ``## `` heading line CONTAINING ``version``
    (substring, anywhere in the line), emit every following line until the
    next ``## `` heading. A missing changelog yields the literal
    ``(no CHANGELOG.md found at <path>)`` line (which — bash parity — makes
    the notes file non-empty, so the ``shepherd <tag>`` fallback does NOT
    fire in that case).

    Returns:
        The captured lines, each newline-terminated (awk's ``print``), or
        ``""`` when no matching section exists.
    """
    if not os.path.isfile(changelog_path):
        return f"(no CHANGELOG.md found at {changelog_path})\n"
    captured: list[str] = []
    capture = False
    with open(changelog_path, encoding="utf-8") as fh:
        for line in fh.read().splitlines():
            if line.startswith("## "):
                if capture:
                    break
                if version in line:
                    capture = True
                continue
            if capture:
                captured.append(line)
    return "".join(line + "\n" for line in captured)


def _notes_file_path(tag_patch: str, run_name: str | None) -> str:
    """The release-notes file path, honoring the run-scoped artifact shim.

    Bash: ``$(shctx_artifacts_root)/tmp/release-notes-<tag>.md``. When a
    run is identifiable (``--run`` flag → ``SHEPHERD_RUN`` env →
    ``<workdir>/runs/current`` marker, via
    :func:`shepherd_cli.commands.models_graph.resolve_run`), the NEW
    run-scoped location ``<workdir>/runs/<run>/tmp/`` is used instead. No
    read-side legacy fallback is needed: the file is written and consumed
    within this same invocation.
    """
    workdir = resolve_workdir()
    run = resolve_run(run_name)
    if run:
        return f"{workdir}/runs/{run}/tmp/release-notes-{tag_patch}.md"
    return f"{workdir}/tmp/release-notes-{tag_patch}.md"


# --------------------------------------------------------------------------
# gh retry — port of _lib.sh's shctx_gh_retry (see documented deviation 2).
# --------------------------------------------------------------------------
def _int_env(name: str, default: int) -> int:
    """Read a ``${VAR:-default}`` int env knob; non-numeric degrades to default."""
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _is_transient_gh_failure(combined_output: str) -> bool:
    """``shctx_gh_retry``'s transient ``case`` glob, as a substring test."""
    return any(marker in combined_output for marker in _TRANSIENT_MARKERS)


def _gh_retry(args: list[str]) -> int:
    """Run ``gh <args>``, retrying transient failures — ``shctx_gh_retry`` port.

    Semantics, all bash-verbatim: combined stdout+stderr capture
    (``2>&1``) with trailing newlines stripped (command-substitution
    parity); success re-emits the output to stdout and returns 0; a
    NON-transient failure re-emits it to stderr and fails fast with gh's
    exit code; a transient failure (any :data:`_TRANSIENT_MARKERS`
    substring) sleeps ``backoff_base ** attempt`` seconds and retries, up
    to ``SHCTX_GH_RETRY_MAX`` attempts, emitting the same
    ``shctx_gh_retry: ...`` stderr diagnostics ``_lib.sh`` does.

    Args:
        args: gh subcommand + arguments (WITHOUT the leading ``gh``).

    Returns:
        0 on success; gh's exit code on terminal failure (127 if the gh
        binary vanished between the ``command -v``-equivalent check and
        the exec — bash's own shell-level not-found code).
    """
    max_attempts = _int_env("SHCTX_GH_RETRY_MAX", _DEFAULT_GH_RETRY_MAX)
    backoff_base = _int_env("SHCTX_GH_RETRY_BACKOFF", _DEFAULT_GH_RETRY_BACKOFF)
    attempt = 1
    rc = 0
    out = ""
    while attempt <= max_attempts:
        try:
            proc = subprocess.run(
                ["gh", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except OSError as exc:
            sys.stderr.write(f"{exc}\n")
            sys.stderr.flush()
            return 127
        out = (proc.stdout or "").rstrip("\n")
        if proc.returncode == 0:
            sys.stdout.write(out)
            sys.stdout.flush()
            return 0
        rc = proc.returncode
        if _is_transient_gh_failure(out):
            if attempt < max_attempts:
                sleep_for = backoff_base**attempt
                typer.echo(
                    f"shctx_gh_retry: transient failure (attempt {attempt}/{max_attempts}); "
                    f"retrying in {sleep_for}s...",
                    err=True,
                )
                time.sleep(sleep_for)
                attempt += 1
                continue
        else:
            sys.stderr.write(out)
            sys.stderr.flush()
            return rc
        attempt += 1
    typer.echo(f"shctx_gh_retry: exhausted {max_attempts} attempts; last output:", err=True)
    typer.echo(out, err=True)
    return rc


# --------------------------------------------------------------------------
# Version-file bumping — bash's bump_file().
# --------------------------------------------------------------------------
def _bump_json(full: str, tmp: str, new_version: str) -> None:
    """jq parity: ``.version = $v`` plus guarded ``.plugins[].version``.

    Key order preserved (both jq and Python dicts keep insertion order);
    output is jq's default shape — 2-space indent, raw UTF-8, one trailing
    newline. See documented deviation 3 for the non-object-plugin-entry
    edge.
    """
    with open(full, encoding="utf-8") as fh:
        data = json.load(fh)
    data["version"] = new_version
    plugins = data.get("plugins")
    if isinstance(plugins, list):
        for plugin in plugins:
            if isinstance(plugin, dict):
                plugin["version"] = new_version
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, full)


def _bump_yaml(full: str, tmp: str, new_version: str) -> None:
    """awk parity: replace the FIRST ``^version:`` line, pass the rest through."""
    with open(full, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    done = False
    out: list[str] = []
    for line in lines:
        if not done and line.startswith("version:"):
            out.append(f"version: {new_version}")
            done = True
        else:
            out.append(line)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("".join(line + "\n" for line in out))
    os.replace(tmp, full)


_README_VERSION_RE = re.compile(r"^Current version: \*\*[0-9]+\.[0-9]+\.[0-9]+\*\*")


def _bump_readme(full: str, tmp: str, new_version: str) -> None:
    """awk parity: replace EVERY ``Current version: **X.Y.Z**`` line."""
    with open(full, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out: list[str] = []
    for line in lines:
        if _README_VERSION_RE.match(line):
            out.append(f"Current version: **{new_version}**")
        else:
            out.append(line)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("".join(line + "\n" for line in out))
    os.replace(tmp, full)


def _bump_file(path: str, fmt: str, new_version: str, dry_run: bool, repo_root: str) -> None:
    """``bump_file()``: patch one version file per format, temp-file + replace.

    Order of operations is bash-exact: the existence check happens FIRST
    (a missing file plans ``skip bump (not found)`` even in real mode),
    then the dry-run plan short-circuit, then the actual patch + the
    ``bumped <path> → <v>`` log line.

    Raises:
        typer.Exit: code 1 on an unknown format (unreachable from the
            fixed :data:`VERSION_FILES` list — bash's ``*)`` arm kept for
            parity) or an unreadable/malformed file (documented
            deviation 4).
    """
    full = os.path.join(repo_root, path)
    if not os.path.isfile(full):
        _plan(f"skip bump (not found): {path}")
        return
    if dry_run:
        _plan(f"bump ({fmt}) {path} → {new_version}")
        return
    tmp = f"{full}.shctx-bump.{os.getpid()}"
    try:
        if fmt == "json":
            _bump_json(full, tmp, new_version)
        elif fmt == "yaml":
            _bump_yaml(full, tmp, new_version)
        elif fmt == "readme":
            _bump_readme(full, tmp, new_version)
        else:
            typer.echo(f"ERROR: unknown bump format: {fmt}", err=True)
            raise typer.Exit(code=1)
    except (OSError, ValueError) as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        typer.echo(f"ERROR: bump ({fmt}) failed for {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _log(f"bumped {path} → {new_version}")


# --------------------------------------------------------------------------
# The pipeline itself — cmd_release.sh's mode dispatch + cascade, in order.
# --------------------------------------------------------------------------
def _pipeline(
    *,
    dry_run: bool,
    skip_tag: bool,
    skip_gh: bool,
    skip_bump: bool,
    skip_push: bool,
    run_name: str | None,
) -> None:
    """Run the full release pipeline (see the module docstring for the map).

    Raises:
        typer.Exit: code 0 after a mid-patch sprint close (bash's early
            ``exit 0``); code 1 on an unrecognized branch shape; a failing
            git/gh command's own exit code anywhere in the cascade.
    """
    branch = _current_branch()
    parsed = _parse_branch(branch)

    _log(f"current branch: {branch or '<unknown>'} (mode: {parsed.mode})")
    if parsed.mode == "none":
        typer.echo(f"ERROR: current branch '{branch}' does not match a known release pattern", err=True)
        typer.echo("       expected v<X>.<Y>.<Z> or v<X>.<Y>.<Z>-dev.<N>", err=True)
        raise typer.Exit(code=1)

    patch_version = f"{parsed.x}.{parsed.y}.{parsed.z}"
    patch_branch = f"v{patch_version}"
    tag_patch = f"v{patch_version}"
    tag_minor = f"v{parsed.x}.{parsed.y}"
    tag_major = f"v{parsed.x}"

    if parsed.mode == "sprint":
        _log(f"sprint-end mode: dev.{parsed.sprint_n} of patch {patch_version}")
        last_sprint = _sprints_per_patch(resolve_repo_root()) - 1
        sprint_n = int(parsed.sprint_n)
        if sprint_n < last_sprint:
            # Mid-patch: rebase dev into patch, delete dev, cut next dev.
            next_sprint = sprint_n + 1
            next_dev_branch = f"v{patch_version}-dev.{next_sprint}"
            _log(f"mid-patch sprint close: rebase dev.{parsed.sprint_n} → {patch_branch}, then cut dev.{next_sprint}")
            _run(dry_run, f"git checkout {patch_branch}", ["git", "checkout", patch_branch])
            _run(dry_run, f"git rebase {branch}", ["git", "rebase", branch])
            if not skip_push:
                _run(dry_run, f"git push origin {patch_branch}", ["git", "push", "origin", patch_branch])
            _run(dry_run, f"git branch -D {branch}", ["git", "branch", "-D", branch])
            if not skip_push:
                _run(dry_run, f"git push origin --delete {branch}", ["git", "push", "origin", "--delete", branch])
            _run(
                dry_run,
                f"git checkout -b {next_dev_branch} {patch_branch}",
                ["git", "checkout", "-b", next_dev_branch, patch_branch],
            )
            if not skip_push:
                _run(dry_run, f"git push -u origin {next_dev_branch}", ["git", "push", "-u", "origin", next_dev_branch])
            _log(f"done. now on {next_dev_branch}.")
            raise typer.Exit(code=0)
        _log(f"patch-end sprint: rebase dev.{parsed.sprint_n} → {patch_branch}, then run full cascade")
        _run(dry_run, f"git checkout {patch_branch}", ["git", "checkout", patch_branch])
        _run(dry_run, f"git rebase {branch}", ["git", "rebase", branch])
        if not skip_push:
            _run(dry_run, f"git push origin {patch_branch}", ["git", "push", "origin", patch_branch])
        _run(dry_run, f"git branch -D {branch}", ["git", "branch", "-D", branch])
        if not skip_push:
            _run(dry_run, f"git push origin --delete {branch}", ["git", "push", "origin", "--delete", branch])
        # Fall through to the cascade below (now on the patch branch).
        branch = patch_branch
    else:
        _log(f"lighter-pattern mode: patch {patch_version} ready for release")

    # ---- cascade: squash → tag → release → bump → cut next ----

    # 1. squash patch branch into main.
    if not dry_run and _already_merged_into_main(patch_branch):
        _log(f"skip squash: {patch_branch} already an ancestor of {MAIN_BRANCH}")
    else:
        _run(dry_run, f"git checkout {MAIN_BRANCH}", ["git", "checkout", MAIN_BRANCH])
        if not skip_push:
            _run(
                dry_run,
                f"git pull --ff-only origin {MAIN_BRANCH}",
                ["git", "pull", "--ff-only", "origin", MAIN_BRANCH],
            )
        _run(dry_run, f"git merge --squash {patch_branch}", ["git", "merge", "--squash", patch_branch])
        _run(
            dry_run,
            f"git commit -m 'release: shepherd {tag_patch}'",
            ["git", "commit", "-m", f"release: shepherd {tag_patch}"],
        )
        if not skip_push:
            _run(dry_run, f"git push origin {MAIN_BRANCH}", ["git", "push", "origin", MAIN_BRANCH])

    # 2. tag immutable patch tag (skip if exists).
    if skip_tag:
        _plan(f"skip tag (--skip=tag): {tag_patch}")
    elif not dry_run and _tag_exists(tag_patch):
        _log(f"skip tag: {tag_patch} already exists")
    else:
        _run(
            dry_run,
            f"git tag -a {tag_patch} -m 'shepherd {tag_patch}'",
            ["git", "tag", "-a", tag_patch, "-m", f"shepherd {tag_patch}"],
        )
        # `git push origin <name>` is ambiguous when a branch and tag share
        # <name> (v5.0.1 is routinely both mid-cascade) — explicit
        # refs/tags/ refspec, bash-verbatim.
        if not skip_push:
            _run(
                dry_run,
                f"git push origin refs/tags/{tag_patch}",
                ["git", "push", "origin", f"refs/tags/{tag_patch}"],
            )

    # 3. force-update mutable tags vX and vX.Y.
    if skip_tag:
        _plan(f"skip mutable tags (--skip=tag): {tag_minor}, {tag_major}")
    else:
        _run(dry_run, f"git tag -f {tag_minor}", ["git", "tag", "-f", tag_minor])
        if not skip_push:
            _run(
                dry_run,
                f"git push -f origin refs/tags/{tag_minor}",
                ["git", "push", "-f", "origin", f"refs/tags/{tag_minor}"],
            )
        _run(dry_run, f"git tag -f {tag_major}", ["git", "tag", "-f", tag_major])
        if not skip_push:
            _run(
                dry_run,
                f"git push -f origin refs/tags/{tag_major}",
                ["git", "push", "-f", "origin", f"refs/tags/{tag_major}"],
            )

    # 4. gh release create with notes extracted from CHANGELOG.
    if skip_gh:
        _plan(f"skip gh release (--skip=gh): {tag_patch}")
    else:
        notes_file = _notes_file_path(tag_patch, run_name)
        if dry_run:
            _plan(f"extract release notes for {tag_patch} from {CHANGELOG_PATH} → {notes_file}")
            _plan(f"gh release create {tag_patch} --notes-file={notes_file}")
        else:
            os.makedirs(os.path.dirname(notes_file), exist_ok=True)
            notes = _extract_release_notes(tag_patch, os.path.join(resolve_repo_root(), CHANGELOG_PATH))
            with open(notes_file, "w", encoding="utf-8") as fh:
                fh.write(notes)
            if os.path.getsize(notes_file) == 0:
                with open(notes_file, "w", encoding="utf-8") as fh:
                    fh.write(f"shepherd {tag_patch}\n")
            if shutil.which("gh"):
                _log(
                    f"exec: gh release create {tag_patch} "
                    f"--notes-file='{notes_file}' --title='shepherd {tag_patch}'"
                )
                rc = _gh_retry(
                    ["release", "create", tag_patch, f"--notes-file={notes_file}", f"--title=shepherd {tag_patch}"]
                )
                if rc != 0:
                    raise typer.Exit(code=rc)
            else:
                _log(f"gh missing; skipped gh release (notes at {notes_file})")

    # 5. compute next version, cut new patch + dev.0.
    next_x, next_y, next_z = _next_version(int(parsed.x), int(parsed.y), int(parsed.z))
    next_patch_version = f"{next_x}.{next_y}.{next_z}"
    next_patch_branch = f"v{next_patch_version}"
    next_dev_branch = f"v{next_patch_version}-dev.0"

    _log(f"cascade: next patch {next_patch_version}")
    _run(dry_run, f"git checkout {MAIN_BRANCH}", ["git", "checkout", MAIN_BRANCH])
    _run(
        dry_run,
        f"git checkout -b {next_patch_branch} {MAIN_BRANCH}",
        ["git", "checkout", "-b", next_patch_branch, MAIN_BRANCH],
    )
    if not skip_push:
        _run(dry_run, f"git push -u origin {next_patch_branch}", ["git", "push", "-u", "origin", next_patch_branch])
    _run(
        dry_run,
        f"git checkout -b {next_dev_branch} {next_patch_branch}",
        ["git", "checkout", "-b", next_dev_branch, next_patch_branch],
    )
    if not skip_push:
        _run(dry_run, f"git push -u origin {next_dev_branch}", ["git", "push", "-u", "origin", next_dev_branch])

    # 6. bump versions in workspace files.
    if skip_bump:
        _plan("skip version bump (--skip=bump)")
    else:
        _log(f"bumping version files to {next_patch_version}")
        repo_root = resolve_repo_root()
        for path, fmt in VERSION_FILES:
            _bump_file(path, fmt, next_patch_version, dry_run, repo_root)
        if not dry_run:
            # Stage just the files we touched.
            for path, _fmt in VERSION_FILES:
                if os.path.isfile(os.path.join(repo_root, path)):
                    _run(False, f"git add '{path}'", ["git", "add", path])
            _run(
                False,
                f"git commit -m 'chore: bump shepherd to v{next_patch_version} (next patch working branch)'",
                ["git", "commit", "-m", f"chore: bump shepherd to v{next_patch_version} (next patch working branch)"],
            )
            if not skip_push:
                _run(False, f"git push origin {next_dev_branch}", ["git", "push", "origin", next_dev_branch])
        else:
            # Bash quirk preserved: in dry-run these two plan lines print
            # even under --skip=push (the else-arm has no SKIP_PUSH guard).
            _plan("git add + commit version bumps")
            _plan(f"git push origin {next_dev_branch}")

    _log(f"release pipeline complete: {tag_patch} released; now on {next_dev_branch}")


# --------------------------------------------------------------------------
# Entry point — bash's `for a in "$@"` flag loop.
# --------------------------------------------------------------------------
@app.callback(invoke_without_command=True)
def release(
    args: list[str] = typer.Argument(
        None,
        metavar="[--dry-run] [--skip=tag,gh,bump,push] [--run=<name>] [-h|--help]",
        hidden=True,
        help="Raw flag tokens, parsed by the bash-parity loop (see the module docstring).",
    ),
) -> None:
    """Run the gear-cascade release pipeline (rebase → squash → tag → gh → cut next).

    Native port of ``shctx release`` (``cmd_release.sh``). Flags are parsed
    by a manual in-order token loop exactly mirroring bash's ``for a in
    "$@"`` — an unknown flag errors the moment it is reached, and ``-h``
    reached AFTER valid flags still prints usage and exits 0, both as bash
    does.

    Args:
        args: Every token after ``release`` on the command line.

    Raises:
        typer.Exit: code 0 on ``-h``/``--help``; code 1 on an unknown flag
            or unknown ``--skip=`` step. See :func:`_pipeline` for every
            downstream exit path.
    """
    argv = list(args) if args else []
    dry_run = False
    skip_tag = False
    skip_gh = False
    skip_bump = False
    skip_push = False
    run_name: str | None = None

    for a in argv:
        if a == "--dry-run":
            dry_run = True
        elif a.startswith("--skip="):
            raw = a[len("--skip=") :]
            parts = raw.split(",") if raw else []
            if parts and parts[-1] == "":
                # bash `IFS=, read -r -a` drops exactly one trailing empty
                # field (`--skip=tag,` ≡ `--skip=tag`); interior empties
                # survive and hit the unknown-step arm below.
                parts.pop()
            for p in parts:
                if p == "tag":
                    skip_tag = True
                elif p == "gh":
                    skip_gh = True
                elif p == "bump":
                    skip_bump = True
                elif p == "push":
                    skip_push = True
                else:
                    typer.echo(f"ERROR: unknown skip step: {p}", err=True)
                    raise typer.Exit(code=1)
        elif a.startswith("--run="):
            # ADDITIVE (documented deviation 1): run-scoped notes-file shim.
            run_name = a[len("--run=") :] or None
        elif a in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown flag: {a}", err=True)
            typer.echo(_USAGE, err=True)
            raise typer.Exit(code=1)

    _pipeline(
        dry_run=dry_run,
        skip_tag=skip_tag,
        skip_gh=skip_gh,
        skip_bump=skip_bump,
        skip_push=skip_push,
        run_name=run_name,
    )


__all__ = ["app", "ReleaseBranch", "VERSION_FILES", "MAIN_BRANCH", "CHANGELOG_PATH"]
