#!/usr/bin/env bash
# hooks/scripts/generate_harness_parity.sh — GENERATED event x harness x
# implementation-state table for the three shepherd harnesses (Claude, Codex,
# Pi). Never hand-write the table this script produces; regenerate it here.
#
# GROUND TRUTH (three JSON manifests, read directly, no JavaScript grepped):
#   Claude: hooks/hooks.json
#   Codex:  plugins/shepherd/codex/hooks/hooks.json
#   Pi:     packages/harness-pi/shepherd.pi.json (its "hooks" block; Pi
#           dispatches in-process through src/extension.mjs rather than
#           spawning a binary per event, so each entry carries a
#           "canonicalEvent" field this script maps onto the same event axis
#           Claude/Codex use — see hooks/tests/test_pi_manifest_drift.sh for
#           the tripwire that keeps that block honest against extension.mjs).
#
# THREE STATES, always exactly one per cell, never blank:
#   1. implemented and effective
#   2. registered but inert         (reason + file:line citation required)
#   3. unsupported harness limitation (reason + file:line citation required)
#
# Every row of the table corresponds to a canonical event name (the same
# vocabulary crates/core/src/dispatch/portable.rs::NativeEvent uses, plus the
# two Claude-only shell-telemetry events CwdChanged/PreCompact, plus Pi's
# lifecycle-parity SessionShutdown), EXCEPT one synthetic row,
# "SubagentStart — write-scope narrowing": write-scope accuracy is a
# *property of* the SubagentStart binding, not a separate manifest key, and
# it disagrees with SubagentStart's own state (SubagentStart is state 1 on
# Claude; its write-scope narrowing is state 3 on every harness) — a single
# table cell cannot hold two states at once, so it gets its own row rather
# than silently overriding or being merged into SubagentStart's cell.
#
# Three facts are NOT mechanically derivable from the JSON manifests alone
# (a manifest can say an event is registered; it cannot say *why* a Rust
# refusal path exists, or that a no-op is intentional, or that a native
# registration site would be a silent no-op). Those three facts live in the
# LIMITATIONS lookup below, hand-curated but VERSIONED WITH THIS SCRIPT (not
# with the generated artifact), so the artifact itself stays fully
# regenerated:
#   (a) Codex SubagentStart/SubagentStop: no trusted spawn-to-child
#       correlation exists; building one would mint shadow identities.
#   (b) Claude SubagentStart write-scope: recorded "**" because no host ever
#       declares a narrower one.
#   (c) Claude CwdChanged/PreCompact: shell telemetry does real work (state
#       1), but no NATIVE handler exists for either — portable.rs maps every
#       untyped event to DispatchPlan::Ignored, so a native registration
#       there would be a silent no-op.
#
# All three source-line citations below are found by grep AT GENERATION TIME
# (find_line), not hardcoded, and hard-fail loudly if the anchor text ever
# moves or disappears. This is deliberate: the lane brief that specified this
# script cited portable.rs:794 for fact (c); the actual current line is 810
# (16 lines of drift from intervening edits in the same run). A hardcoded
# number would have shipped that exact staleness into a "generated, always
# correct" artifact. A grep anchor self-heals across everything except an
# actual rewrite of the cited logic, which is exactly when a human should be
# forced to look again — hence the hard failure instead of a silent stale
# citation.
#
# PI SESSION_SHUTDOWN — state 2, not state 1 (defended, not just declared):
# the manifest's own "behavior" text says "no-op". "Implemented and
# effective" requires the handler to DO something; a no-op does not become
# effective merely because it was deliberately written that way. It is
# "registered but inert" in the most literal sense: pi.on("session_shutdown")
# is registered, and it is inert. Intentional inertness is still inertness —
# the state describes runtime effect, not authorial intent. (Compare: Claude
# SubagentStart *is* state 1 because it demonstrably writes a dispatch record
# — see commit 7d5492e below.)
#
# Bash 3.2 safe throughout: no ${var,,}, no mapfile, no declare -A. Verified
# against the operator's actual default `bash` (GNU bash 3.2.57, macOS).
#
# Usage:
#   generate_harness_parity.sh [OUTPUT_PATH] [--check]
#     OUTPUT_PATH   where to write the table (default: env override below,
#                   else .shepherd/runs/v646/harness-parity.md). Passing an
#                   explicit path is how a test runs this without ever
#                   writing the tracked artifact.
#     --check       do not write OUTPUT_PATH; regenerate to a scratch file
#                   and diff it against the file already at OUTPUT_PATH,
#                   exiting 1 on any difference (or if OUTPUT_PATH does not
#                   exist yet). This is the regenerate-and-diff drift check.
#
# Env overrides (manifest ground truth only — never the Rust citations,
# which always read the real tree so a falsification test cannot corrupt a
# citation that has nothing to do with the manifest being falsified):
#   SHEPHERD_PARITY_CLAUDE_MANIFEST
#   SHEPHERD_PARITY_CODEX_MANIFEST
#   SHEPHERD_PARITY_PI_MANIFEST
#   SHEPHERD_HARNESS_PARITY_OUTPUT

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

CLAUDE_MANIFEST="${SHEPHERD_PARITY_CLAUDE_MANIFEST:-$REPO_ROOT/hooks/hooks.json}"
CODEX_MANIFEST="${SHEPHERD_PARITY_CODEX_MANIFEST:-$REPO_ROOT/plugins/shepherd/codex/hooks/hooks.json}"
PI_MANIFEST="${SHEPHERD_PARITY_PI_MANIFEST:-$REPO_ROOT/packages/harness-pi/shepherd.pi.json}"

NATIVE_HOOK_RS="$REPO_ROOT/crates/cli/src/cmd/native_hook.rs"
CLAUDE_HOOK_RS="$REPO_ROOT/crates/cli/src/cmd/claude_hook.rs"
PORTABLE_RS="$REPO_ROOT/crates/core/src/dispatch/portable.rs"
CODEX_HOOK_CLI_TEST="$REPO_ROOT/crates/cli/tests/codex_hook_cli.rs"
PI_EXTENSION="$REPO_ROOT/packages/harness-pi/src/extension.mjs"

# --- output/mode argument parsing -------------------------------------------
# Parsed BEFORE any file I/O (including the jq availability check) so that
# --help and a rejected bad flag both exit cleanly without creating anything
# — in particular, without creating a file literally named after a typo'd
# flag. Any argument beginning with "-" that is not a recognized flag is a
# hard error, never silently reinterpreted as an output path: a mistyped
# `--chekc` must fail loudly, not write a file called `--chekc` and report
# success.

print_usage() {
  cat <<'USAGE_EOF'
Usage: generate_harness_parity.sh [OUTPUT_PATH] [--check]
       generate_harness_parity.sh --help

  OUTPUT_PATH   where to write the table (default: $SHEPHERD_HARNESS_PARITY_OUTPUT,
                else .shepherd/runs/v646/harness-parity.md)
  --check       do not write OUTPUT_PATH; regenerate to a scratch file and
                diff it against the file already at OUTPUT_PATH, exiting 1 on
                any difference or if OUTPUT_PATH does not exist yet
  --help        print this message and exit 0
USAGE_EOF
}

OUTPUT="${SHEPHERD_HARNESS_PARITY_OUTPUT:-$REPO_ROOT/.shepherd/runs/v646/harness-parity.md}"
CHECK_MODE=0
OUTPUT_SET=0
for arg in "$@"; do
  case "$arg" in
    --help | -h)
      print_usage
      exit 0
      ;;
    --check)
      CHECK_MODE=1
      ;;
    -*)
      printf 'generate_harness_parity: unrecognized flag: %s\n' "$arg" >&2
      print_usage >&2
      exit 1
      ;;
    *)
      if [[ "$OUTPUT_SET" -eq 1 ]]; then
        printf 'generate_harness_parity: unexpected extra argument: %s\n' "$arg" >&2
        print_usage >&2
        exit 1
      fi
      OUTPUT="$arg"
      OUTPUT_SET=1
      ;;
  esac
done

if ! command -v jq >/dev/null 2>&1; then
  printf 'generate_harness_parity: jq is required\n' >&2
  exit 1
fi

WORKDIR="$(mktemp -d -t shep-harness-parity.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

# --- dynamic citation anchors ------------------------------------------------
# find_line FILE PATTERN — fixed-string grep, returns comma-joined 1-based
# line numbers. Hard-fails rather than silently returning an empty/stale
# citation (see header comment on the portable.rs:794-vs-810 drift already
# caught by doing it this way instead of hardcoding).
find_line() {
  local file="$1" pattern="$2" lines
  lines="$(grep -nF -- "$pattern" "$file" 2>/dev/null | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')"
  if [[ -z "$lines" ]]; then
    printf 'generate_harness_parity: citation anchor not found: %s in %s\n' "$pattern" "$file" >&2
    exit 1
  fi
  printf '%s' "$lines"
}

# find_line_optional — same, but returns empty instead of hard-failing; used
# only for supplementary (non-mandatory) corroborating citations.
find_line_optional() {
  local file="$1" pattern="$2"
  grep -nF -- "$pattern" "$file" 2>/dev/null | cut -d: -f1 | tr '\n' ',' | sed 's/,$//'
}

CODEX_SUBAGENT_LINE="$(find_line "$NATIVE_HOOK_RS" 'no trusted lifecycle correlation for subagents')"
CODEX_SUBAGENT_CITE="crates/cli/src/cmd/native_hook.rs:${CODEX_SUBAGENT_LINE}"
CODEX_SUBAGENT_TEST_LINE="$(find_line_optional "$CODEX_HOOK_CLI_TEST" 'no trusted lifecycle correlation')"

WRITE_SCOPE_LINES="$(find_line "$NATIVE_HOOK_RS" 'vec!["**".into()]')"
WRITE_SCOPE_CLAUDE_CITE="crates/cli/src/cmd/native_hook.rs:${WRITE_SCOPE_LINES}"
WRITE_SCOPE_CODEX_CITE="crates/cli/src/cmd/native_hook.rs:${CODEX_SUBAGENT_LINE}"

PORTABLE_LINE="$(find_line "$PORTABLE_RS" 'NativeEvent::Other(_) => DispatchPlan::Ignored')"
PORTABLE_CITE="crates/core/src/dispatch/portable.rs:${PORTABLE_LINE}"

# --- reason prose (the three hand-curated, versioned-with-this-script facts) -

CODEX_SUBAGENT_REASON="Codex exposes no trusted spawn-to-child correlation; binding an identity here would mint a shadow identity for a call the host never actually attributes to a subagent. This is a correctness decision, not a gap to fill."
if [[ -n "$CODEX_SUBAGENT_TEST_LINE" ]]; then
  CODEX_SUBAGENT_REASON="$CODEX_SUBAGENT_REASON Pinned by crates/cli/tests/codex_hook_cli.rs:${CODEX_SUBAGENT_TEST_LINE}."
fi

WRITE_SCOPE_CLAUDE_REASON="Identity binding and role enforcement work for a dispatched subagent on Claude, but the write scope is always recorded as \`**\` because no host ever declares a narrower one; narrowing still requires a declared scope the host does not send."
WRITE_SCOPE_CODEX_REASON="SubagentStart is refused outright on Codex (see the SubagentStart/SubagentStop row above), so no dispatch binding — and therefore no write scope — is ever constructed to narrow."
WRITE_SCOPE_PI_REASON="The Pi manifest's hooks block declares no SubagentStart-equivalent event (only session_start, tool_call, session_shutdown), so there is no dispatch binding to narrow a write scope for."

CLAUDE_SUBAGENT_START_REASON="native adapter (\`shepherd claude-hook\`) binds subagent dispatch identity and role, and WRITES a dispatch record via \`DispatchRequest::Start\` as of commit 7d5492e — do not read this as inert, that was true earlier and is now stale."

CWD_PRECOMPACT_NOTE="no native handler exists for this event: portable.rs types every unlisted event as \`NativeEvent::Other\`, which maps to \`DispatchPlan::Ignored\` — a native registration here would be a silent no-op, so the shell registration is the only place this behavior can live"

# --- state labels -------------------------------------------------------------

ST_OK="Implemented and effective"
ST_INERT="Registered but inert"
ST_UNSUP="Unsupported (harness limitation)"

# --- canonical event rows (fixed order; the table's row axis) ----------------

ROW_KEYS=(SessionStart PreToolUse PostToolUse SubagentStart WriteScopeNarrowing SubagentStop CwdChanged PreCompact SessionShutdown)
ROW_LABELS=(
  "SessionStart"
  "PreToolUse"
  "PostToolUse"
  "SubagentStart"
  "SubagentStart — write-scope narrowing"
  "SubagentStop"
  "CwdChanged"
  "PreCompact"
  "SessionShutdown"
)

# --- helpers -------------------------------------------------------------------

rel() {
  # rel PATH — print PATH relative to REPO_ROOT when it is under REPO_ROOT,
  # else print it unchanged (falsification tests point manifests at scratch
  # paths outside the repo; those should still cite something real).
  local path="$1"
  case "$path" in
    "$REPO_ROOT"/*) printf '%s' "${path#"$REPO_ROOT"/}" ;;
    *) printf '%s' "$path" ;;
  esac
}

emit_cell() {
  # emit_cell STATE REASON CITATION — prints one markdown table cell's text
  # (no leading/trailing pipe). CITATION may be empty for a state-1 cell that
  # has no natural single citation.
  local state="$1" reason="$2" citation="${3:-}" text
  text="**${state}**"
  if [[ -n "$reason" ]]; then
    text="$text — $reason"
  fi
  if [[ -n "$citation" ]]; then
    text="$text (see \`$citation\`)"
  fi
  printf '%s' "$text" | sed 's/|/\\|/g'
}

emit_missing_hooks_cell() {
  local manifest="$1"
  emit_cell "$ST_UNSUP" "manifest missing hooks data" "$(rel "$manifest")"
}

# manifest_missing_hooks MANIFEST — exit 0 (true, shell sense) if the
# manifest is absent, or valid JSON with no non-null top-level "hooks" key.
# Hard-exits the whole script if the manifest exists but is not valid JSON at
# all (nothing honest can be said about an unparsable manifest; every other
# case degrades gracefully to a state-3 cell instead of aborting, per the
# brief: "either errors out or marks every event ... unsupported").
manifest_missing_hooks() {
  local manifest="$1"
  if [[ ! -f "$manifest" ]]; then
    return 0
  fi
  if ! jq -e '.' "$manifest" >/dev/null 2>&1; then
    printf 'generate_harness_parity: %s is not valid JSON\n' "$manifest" >&2
    exit 1
  fi
  if jq -e '(has("hooks")) and (.hooks != null)' "$manifest" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

CLAUDE_DEGRADED=0
if manifest_missing_hooks "$CLAUDE_MANIFEST"; then
  CLAUDE_DEGRADED=1
fi
CODEX_DEGRADED=0
if manifest_missing_hooks "$CODEX_MANIFEST"; then
  CODEX_DEGRADED=1
fi
PI_DEGRADED=0
if manifest_missing_hooks "$PI_MANIFEST"; then
  PI_DEGRADED=1
fi

# --- per-harness registration readers (ground truth, three JSON sources) -----

claude_commands_for_event() {
  local event="$1"
  jq -r --arg ev "$event" '
    (.hooks[$ev] // [])[]
    | ((.matcher // "*")) as $m
    | (.hooks // [])[]?
    | select(.type == "command")
    | [(.command // ""), ((.args // []) | join(" ")), $m]
    | @tsv
  ' "$CLAUDE_MANIFEST" 2>/dev/null || true
}

codex_commands_for_event() {
  local event="$1"
  jq -r --arg ev "$event" '
    (.hooks[$ev] // [])[]
    | ((.matcher // "*")) as $m
    | (.hooks // [])[]?
    | select(.type == "command")
    | [(.command // ""), $m]
    | @tsv
  ' "$CODEX_MANIFEST" 2>/dev/null || true
}

pi_entries_for_canonical_event() {
  local event="$1"
  jq -r --arg ev "$event" '
    (.hooks // {}) | to_entries[]
    | select(.value.canonicalEvent == $ev)
    | [.key, (.value.handler // ""), (.value.behavior // "")]
    | @tsv
  ' "$PI_MANIFEST" 2>/dev/null || true
}

# --- generic mechanical renderers (no hand-curated fact involved) ------------

render_claude_generic() {
  local event="$1" rows native cmd args matcher target shell_sorted
  rows="$(claude_commands_for_event "$event")"
  if [[ -z "$rows" ]]; then
    emit_cell "$ST_UNSUP" "manifest declares no hook for this event" "$(rel "$CLAUDE_MANIFEST")"
    return
  fi
  native=0
  : > "$WORKDIR/claude_shell.txt"
  while IFS=$'\t' read -r cmd args matcher; do
    [[ -z "$cmd" ]] && continue
    if [[ "$cmd" == "shepherd" || "$cmd" == '${CLAUDE_PLUGIN_ROOT}/hooks/scripts/shepherd_native.sh' ]] && printf '%s' "$args" | grep -qF 'claude-hook'; then
      native=1
    else
      target="$(printf '%s' "$cmd" | sed -E 's#.*\$\{CLAUDE_PLUGIN_ROOT\}/##')"
      printf '%s\n' "$target" >> "$WORKDIR/claude_shell.txt"
    fi
  done <<< "$rows"
  # NOTE: not `paste -sd', ' -` — BSD paste treats a multi-char -d argument
  # as a *cycling* one-char-per-gap delimiter list (comma, then space, then
  # back to comma...), which silently produces "a.sh,b.sh c.sh" instead of
  # "a.sh, b.sh, c.sh" for 3+ items. awk join is portable and correct.
  shell_sorted="$(sort -u "$WORKDIR/claude_shell.txt" | awk 'NR>1{printf ", "} {printf "%s", $0} END{print ""}')"
  if [[ "$native" -eq 1 && -n "$shell_sorted" ]]; then
    emit_cell "$ST_OK" "native adapter (\`shepherd claude-hook\`) plus shell telemetry: $shell_sorted" "crates/cli/src/cmd/claude_hook.rs; $shell_sorted"
  elif [[ "$native" -eq 1 ]]; then
    emit_cell "$ST_OK" "native adapter (\`shepherd claude-hook\`) resolves this event directly" "crates/cli/src/cmd/claude_hook.rs"
  else
    emit_cell "$ST_OK" "shell telemetry: $shell_sorted (no native \`shepherd claude-hook\` registration for this event)" "$shell_sorted"
  fi
}

render_codex_generic() {
  local event="$1" rows native cmd matcher
  rows="$(codex_commands_for_event "$event")"
  if [[ -z "$rows" ]]; then
    emit_cell "$ST_UNSUP" "manifest declares no hook for this event" "$(rel "$CODEX_MANIFEST")"
    return
  fi
  native=0
  while IFS=$'\t' read -r cmd matcher; do
    [[ -z "$cmd" ]] && continue
    case "$cmd" in
      *codex-hook*) native=1 ;;
    esac
  done <<< "$rows"
  if [[ "$native" -eq 1 ]]; then
    emit_cell "$ST_OK" "native adapter (\`shepherd codex-hook\`) resolves this event directly" "crates/cli/src/cmd/native_hook.rs"
  else
    emit_cell "$ST_OK" "registered via a non-native command (no \`shepherd codex-hook\` adapter matched)" "$(rel "$CODEX_MANIFEST")"
  fi
}

render_pi_generic() {
  local event="$1" rows key handler behavior
  rows="$(pi_entries_for_canonical_event "$event")"
  if [[ -z "$rows" ]]; then
    emit_cell "$ST_UNSUP" "manifest declares no hook for this canonical event" "$(rel "$PI_MANIFEST")"
    return
  fi
  key="" handler="" behavior=""
  while IFS=$'\t' read -r key handler behavior; do
    break
  done <<< "$rows"
  if [[ "$key" == "session_shutdown" ]]; then
    emit_cell "$ST_INERT" "declared for lifecycle parity across the three harnesses; the handler performs no action (\`$handler\`: $behavior) — see this script's header comment for why intentional inertness is still state 2, not state 1" "$(rel "$PI_MANIFEST")"
  else
    emit_cell "$ST_OK" "in-process handler \`$handler\`: $behavior" "packages/harness-pi/src/extension.mjs"
  fi
}

# --- LIMITATIONS lookup (the three hand-curated, non-mechanical facts) -------
# Returns 0 and prints the cell if an override applies to (ROW_KEY, HARNESS);
# returns 1 (prints nothing) otherwise, so the caller falls through to the
# mechanical renderer.

lookup_limitation() {
  local row_key="$1" harness="$2"
  case "${row_key}:${harness}" in
    "SubagentStart:Codex" | "SubagentStop:Codex")
      emit_cell "$ST_UNSUP" "$CODEX_SUBAGENT_REASON" "$CODEX_SUBAGENT_CITE"
      return 0
      ;;
    "SubagentStart:Claude")
      emit_cell "$ST_OK" "$CLAUDE_SUBAGENT_START_REASON" "crates/cli/src/cmd/native_hook.rs"
      return 0
      ;;
    "WriteScopeNarrowing:Claude")
      emit_cell "$ST_UNSUP" "$WRITE_SCOPE_CLAUDE_REASON" "$WRITE_SCOPE_CLAUDE_CITE"
      return 0
      ;;
    "WriteScopeNarrowing:Codex")
      emit_cell "$ST_UNSUP" "$WRITE_SCOPE_CODEX_REASON" "$WRITE_SCOPE_CODEX_CITE"
      return 0
      ;;
    "WriteScopeNarrowing:Pi")
      emit_cell "$ST_UNSUP" "$WRITE_SCOPE_PI_REASON" "$(rel "$PI_MANIFEST")"
      return 0
      ;;
    "CwdChanged:Claude")
      emit_cell "$ST_OK" "shell telemetry (\`hooks/scripts/cwd_changed.sh\`) performs real work; $CWD_PRECOMPACT_NOTE" "$PORTABLE_CITE"
      return 0
      ;;
    "PreCompact:Claude")
      emit_cell "$ST_OK" "shell telemetry (\`hooks/scripts/precompact_snapshot.sh\`) performs real work; $CWD_PRECOMPACT_NOTE" "$PORTABLE_CITE"
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# --- cell dispatch -------------------------------------------------------------

render_cell() {
  local row_key="$1" harness="$2"

  case "$harness" in
    Claude)
      if [[ "$CLAUDE_DEGRADED" -eq 1 ]]; then
        emit_missing_hooks_cell "$CLAUDE_MANIFEST"
        return
      fi
      ;;
    Codex)
      if [[ "$CODEX_DEGRADED" -eq 1 ]]; then
        emit_missing_hooks_cell "$CODEX_MANIFEST"
        return
      fi
      ;;
    Pi)
      if [[ "$PI_DEGRADED" -eq 1 ]]; then
        emit_missing_hooks_cell "$PI_MANIFEST"
        return
      fi
      ;;
  esac

  if lookup_limitation "$row_key" "$harness"; then
    return
  fi

  case "$row_key" in
    WriteScopeNarrowing)
      # Every (row, harness) pair for this synthetic row is covered above;
      # this is an unreachable fail-safe, not a real path — if it ever
      # triggers, a harness was added without updating lookup_limitation, and
      # the honest answer is still "no data", never a fabricated state.
      emit_cell "$ST_UNSUP" "no write-scope narrowing data recorded for this harness (lookup_limitation gap — update this script)" "hooks/scripts/generate_harness_parity.sh"
      ;;
    *)
      case "$harness" in
        Claude) render_claude_generic "$row_key" ;;
        Codex) render_codex_generic "$row_key" ;;
        Pi) render_pi_generic "$row_key" ;;
      esac
      ;;
  esac
}

record_appendix() {
  local label="$1" harness="$2" cell="$3"
  case "$cell" in
    "**${ST_INERT}"* | "**${ST_UNSUP}"*)
      printf -- '- **%s / %s** — %s\n' "$label" "$harness" "$cell" >> "$WORKDIR/appendix.txt"
      ;;
  esac
}

# --- assembly --------------------------------------------------------------

print_header() {
  cat <<HEADER
# Harness parity — event x harness x implementation

GENERATED FILE. Do not hand-edit. Regenerate with:

    bash hooks/scripts/generate_harness_parity.sh

Ground truth: \`hooks/hooks.json\` (Claude), \`plugins/shepherd/codex/hooks/hooks.json\`
(Codex), \`packages/harness-pi/shepherd.pi.json\` (Pi). Pi dispatches in-process
through \`packages/harness-pi/src/extension.mjs\` rather than spawning a binary
per event; its manifest's \`canonicalEvent\` field is what maps it onto the
same event axis Claude and Codex use.

Three states, one per cell, never blank:

1. **Implemented and effective** — the event is handled and does real work.
2. **Registered but inert** — the event is registered but the handler has no
   observable effect; reason and citation given.
3. **Unsupported (harness limitation)** — the harness or host provides no
   support for this event/behavior; reason and citation given.

HEADER
}

build_table() {
  print_header
  printf '| Event | Claude | Codex | Pi |\n'
  printf '|---|---|---|---|\n'
  : > "$WORKDIR/appendix.txt"
  local i=0 row_key label claude_cell codex_cell pi_cell
  while [[ $i -lt ${#ROW_KEYS[@]} ]]; do
    row_key="${ROW_KEYS[$i]}"
    label="${ROW_LABELS[$i]}"
    claude_cell="$(render_cell "$row_key" Claude)"
    codex_cell="$(render_cell "$row_key" Codex)"
    pi_cell="$(render_cell "$row_key" Pi)"
    printf '| %s | %s | %s | %s |\n' "$label" "$claude_cell" "$codex_cell" "$pi_cell"
    record_appendix "$label" "Claude" "$claude_cell"
    record_appendix "$label" "Codex" "$codex_cell"
    record_appendix "$label" "Pi" "$pi_cell"
    i=$((i + 1))
  done
  printf '\n## Every non-"Implemented and effective" cell, with its citation\n\n'
  if [[ -s "$WORKDIR/appendix.txt" ]]; then
    cat "$WORKDIR/appendix.txt"
  else
    printf '(none — every cell in this table is state 1)\n'
  fi
}

# --- entry point -------------------------------------------------------------

if [[ "$CHECK_MODE" -eq 1 ]]; then
  build_table > "$WORKDIR/check_output.md"
  if [[ ! -f "$OUTPUT" ]]; then
    printf 'generate_harness_parity --check: no committed artifact at %s\n' "$OUTPUT" >&2
    exit 1
  fi
  if diff -u "$OUTPUT" "$WORKDIR/check_output.md"; then
    printf 'generate_harness_parity --check: %s matches a fresh regeneration\n' "$OUTPUT"
    exit 0
  else
    printf 'generate_harness_parity --check: %s is stale (see diff above)\n' "$OUTPUT" >&2
    exit 1
  fi
fi

mkdir -p "$(dirname "$OUTPUT")"
build_table > "$OUTPUT"
printf 'generate_harness_parity: wrote %s\n' "$OUTPUT"
