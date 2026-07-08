#!/usr/bin/env bash
# shepherd hook — PreToolUse(Bash): @coder git-write guard (v6.3.0, #187).
#
# ENFORCES: git custody is NEVER the coder's. The coder writes files under its
# [WORKTREE].Path and lists them in its report; STAGING, COMMITTING, rebasing,
# and pushing the coder's output are the conductor's/root's, executed only
# after the wave-review returns PASS (skills/shepherd/references/pipeline.md
# §Wave review + REDO; agents/conductor.md §Lane walk). agents/coder.md +
# skills/shepherd/references/flock.md §@coder document the contract; this hook
# is the mechanical gate.
#
# WHY (field incident, axiom dev.8): coders self-committed on first dispatch
# (lane-w B1) and ran `git commit` despite an explicit brief prohibition
# (lane-r B3). Pathspec-less self-commits in a SHARED lane worktree swept
# sibling coders' uncommitted files — two near-miss index races. The deeper
# reason the coder must own NO git: a REDO verdict re-runs the NAMED coder over
# the SAME files; if the coder had already committed, every REDO would force
# the conductor to unwind git first. Keeping coder output uncommitted until
# wave-review PASS makes a REDO a plain re-run — nothing to undo. Prompt-level
# prohibition demonstrably decays across dispatches; this is the guard.
#
# RULE: a @coder dispatch MAY run ONLY read-only git inspection
#   (status, diff, log, show, rev-parse — plus other plumbing reads).
# A @coder dispatch MUST NOT run ANY git write/mutating command
#   (add, commit, push, pull, fetch, merge, rebase, reset, checkout, switch,
#    restore, stash, clean, cherry-pick, revert, tag/branch/remote/config
#    writes, worktree *, rm, mv, …). Deny-by-default: any git subcommand not on
#    the read-only allowlist is blocked.
#
# EVENT: PreToolUse(Bash)
# STDIN: { session_id, tool_name, tool_input.command, tool_use_id, ... }
# OUTPUT:
#   {"permissionDecision":"deny","message":"..."}  — coder git-write blocked
#   silent exit 0 — not a @coder dispatch, no git in the command, or a
#                   read-only git command
#
# HALT CODE: CODER-GIT-WRITE (registered in agents/coder.md + escalation.md).
#
# ROLE DETECTION: current_role() (hooks/scripts/_lib.sh) reads the dispatch
# record agent_invocation_tagger.sh wrote — same mechanism bash_guard.sh uses
# to gate @auditor / @discovery Bash. Non-coder turns fail open (pass).
#
# CAVEAT: heuristic pass over the command string, not a fully parsed argument
# tree — the same acknowledged limitation teammate_git_guard.sh documents. The
# subcommand extraction skips git global options (-C <path>, -c <kv>,
# --git-dir=, --work-tree=, --no-pager, --paginate, …) so `git -C x commit`
# resolves to `commit`, not `-C`. python3 does the precise tokenization; if it
# is absent the fallback is a comprehensive write-verb deny-list (reads still
# pass) so protection degrades gracefully rather than failing open.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -------------------------------------------
is_shepherd_project || exit 0

# --- tool filter: only Bash ----------------------------------------------
TOOL="$(json_field "$PAYLOAD" '.tool_name' 2>/dev/null || true)"
[[ "$TOOL" == "Bash" ]] || exit 0

CMD="$(json_field "$PAYLOAD" '.tool_input.command' 2>/dev/null || true)"
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
TOOL_USE_ID="$(json_field "$PAYLOAD" '.tool_use_id' 2>/dev/null || true)"

[[ -n "$CMD" ]] || exit 0

# --- is this a @coder dispatch? ------------------------------------------
SPRINT="$(current_sprint)"
ROLE="$(current_role "$TOOL_USE_ID" "$SPRINT" 2>/dev/null || echo unknown)"
if [[ "$ROLE" != "coder" ]]; then
  pass_silent "coder_git_guard" "Bash" "$ROLE" "$SESSION"
fi

# --- fast-path: no git invocation at all ---------------------------------
printf '%s' "$CMD" | grep -qE '(^|[^[:alnum:]_.-])git([[:space:]]|$)' 2>/dev/null || \
  pass_silent "coder_git_guard" "Bash" "coder" "$SESSION"

# Read-only git subcommands a coder MAY run (deny-by-default: anything not here
# — including every write/mutating verb and the write forms of dual-mode verbs
# like branch/remote/tag/config — is blocked). All entries are unambiguously
# read-only. rev-parse is required by the coder's Step 0.5 base-commit check.
READONLY_GIT_VERBS="status diff log show rev-parse ls-files ls-tree cat-file blame show-ref rev-list merge-base describe shortlog for-each-ref name-rev diff-tree diff-index grep var whatchanged count-objects show-branch cherry version help"

BAD=""

# --- Layer 1: allowlist over extracted git subcommands (deny-by-default) ---
# python3 (shlex) walks tokens, skips git global options (git -C x commit →
# commit), and RECURSES into shell-invoking wrappers (bash/sh/zsh/eval -c
# "<string>") so a write hidden in a quoted argument is not an opaque token.
# Each extracted subcommand is cut at the first shell metacharacter so a glued
# read (git status;git log) is not mis-read as one bogus subcommand.
SUBCMDS=""
if command -v python3 >/dev/null 2>&1; then
  SUBCMDS="$(printf '%s' "$CMD" | python3 -c '
import sys, shlex, re
takes_arg = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
             "--exec-path", "--config-env", "--super-prefix"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "env", "xargs"}
def subcommands(cmd, depth=0):
    out = []
    if depth > 6:
        return out
    try:
        toks = shlex.split(cmd, posix=True)
    except ValueError:
        toks = cmd.split()
    i, n = 0, len(toks)
    while i < n:
        base = toks[i].rsplit("/", 1)[-1]
        if base == "git":
            j = i + 1
            while j < n:
                o = toks[j]
                if o in takes_arg: j += 2; continue
                if o.startswith("--") and "=" in o: j += 1; continue
                if o.startswith("-"): j += 1; continue
                sc = re.split(r"[;&|]", o.lower())[0]   # cut glued metachars
                if sc: out.append(sc)
                break
            i = j + 1
        elif base == "eval":
            for k in range(i + 1, n):
                out += subcommands(toks[k], depth + 1)   # eval <str> …
            i += 1
        elif base in SHELLS:
            k = i + 1
            while k < n:
                if toks[k] == "-c" and k + 1 < n:
                    out += subcommands(toks[k + 1], depth + 1)
                    k += 2; continue
                k += 1
            i += 1
        else:
            i += 1
    return out
print("\n".join(subcommands(sys.stdin.read())))
' 2>/dev/null || true)"
fi
if [[ -n "$SUBCMDS" ]]; then
  while IFS= read -r sc; do
    [[ -z "$sc" ]] && continue
    case " $READONLY_GIT_VERBS " in
      *" $sc "*) : ;;                       # allowed read-only verb
      *) BAD="${BAD:+$BAD, }git ${sc}" ;;   # anything else → blocked
    esac
  done <<< "$SUBCMDS"
fi

# --- Layer 2: comprehensive raw write-scan (ALWAYS runs) -------------------
# Independent of Layer 1's tokenizer: catches a git write ANYWHERE in the raw
# string — inside bash -c "…"/eval, glued to a decoy read (git status && git
# reset), or a plumbing verb the tokenizer allowlist wouldn't have to reason
# about. This is the sole check when python3 is absent. Verb list is
# exhaustive: every mutating porcelain + plumbing command, plus the write forms
# of dual-mode verbs (branch/remote/tag/config/reflog/…), which a coder never
# needs anyway.
WRITE_VERBS='add|rm|mv|commit|commit-tree|merge|merge-file|merge-index|rebase|reset|restore|checkout|checkout-index|switch|stash|clean|cherry-pick|revert|push|pull|fetch|clone|init|gc|prune|repack|apply|am|worktree|remote|tag|branch|config|notes|submodule|update-ref|update-index|update-server-info|replace|filter-branch|filter-repo|fast-import|sparse-checkout|bisect|format-patch|request-pull|write-tree|hash-object|symbolic-ref|read-tree|reflog|send-pack|receive-pack|http-push|http-fetch|credential|maintenance|mergetool|difftool|commit-graph|multi-pack-index|pack-refs|mktree|mktag|pack-objects|unpack-objects|prune-packed|fsck'
WRITE_PATTERN="(^|[^[:alnum:]_.-])git[[:space:]]+([^\"';|&]*[[:space:]])?(${WRITE_VERBS})([[:space:]\"';|&]|\$)"
if printf '%s' "$CMD" | grep -qE "$WRITE_PATTERN" 2>/dev/null; then
  BAD="${BAD:+$BAD, }git write command"
fi

[[ -z "$BAD" ]] && pass_silent "coder_git_guard" "Bash" "coder" "$SESSION"
VERBS="$BAD"

MSG="[shepherd] CODER-GIT-WRITE — @coder may not run git (read-only inspection only)."$'\n'
MSG+="  Session    : ${SESSION}"$'\n'
MSG+="  Command    : ${CMD:0:200}"$'\n'
MSG+="  Blocked    : ${VERBS}"$'\n'
MSG+="Git custody is NEVER the coder's. Write your files under [WORKTREE].Path and"$'\n'
MSG+="list them in your CODER REPORT — the conductor stages+commits your reported"$'\n'
MSG+="files after the wave-review returns PASS. This is WHY you never commit: a REDO"$'\n'
MSG+="re-runs you over the SAME files, so uncommitted output means nothing to unwind."$'\n'
MSG+="Read-only inspection (git status/diff/log/show/rev-parse) stays yours."$'\n'
MSG+="See agents/coder.md + skills/shepherd/references/flock.md §@coder / §Write boundaries."

emit_deny "$MSG" "coder_git_guard" "Bash" "coder" "$SESSION"
