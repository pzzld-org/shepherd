#!/usr/bin/env bash
# services/llm/llm.sh — the shepherd LLM service.
#
# A self-contained service that routes every model call through the LOCAL Claude
# Code in headless print mode (`claude -p`). Per CLAUDE.md: the software we build
# never calls a hosted inference API — it shells out to the local Claude Code.
# Every other service (services/eval, …) calls THIS contract, never `claude`
# directly, so there is exactly one place that owns the model invocation, the
# timeout, the model default, and the mock seam.
#
# Standalone by design (services-first / parallel-safe): it sources nothing from
# skills/context and reads only its own env vars, so a second session can work in
# services/eval/ without colliding here. Config that belongs to the caller (which
# model, which threshold) is passed in via flags/env — this service does not read
# shepherd.toml.
#
# ── Contract ────────────────────────────────────────────────────────────────
#   llm.sh complete [--prompt-file=F | --prompt=TXT | -]  \
#                   [--system-file=F | --system=TXT]      \
#                   [--model=ALIAS] [--timeout=SEC]
#       Prompt source precedence: --prompt-file > --prompt > stdin.
#       Prints the model's raw text response to stdout. Nothing else on stdout.
#   llm.sh ping            Verify the claude binary is reachable (no completion).
#   llm.sh help
#
# ── Env ─────────────────────────────────────────────────────────────────────
#   SHEPHERD_LLM_BIN        claude binary (default: claude)
#   SHEPHERD_LLM_MODEL      default model alias (default: opus — best by default,
#                           per CLAUDE.md; never silently downgrade for cost)
#   SHEPHERD_LLM_TIMEOUT    default timeout seconds (default: 120)
#   SHEPHERD_LLM_MOCK       path to a file whose contents `complete` returns
#                           verbatim, short-circuiting the claude call. The seam
#                           that makes downstream gate tests deterministic + free.
#   SHEPHERD_LLM_MOCK_TEXT  inline mock string (used when SHEPHERD_LLM_MOCK unset)
#
# ── Exit codes ──────────────────────────────────────────────────────────────
#   0 ok · 2 usage · 3 timeout · 4 llm/runtime error
#
# bash-3.2-safe (macOS default): no associative arrays, no ${var,,}, no mapfile.
set -eu -o pipefail

BIN="${SHEPHERD_LLM_BIN:-claude}"
DEFAULT_MODEL="${SHEPHERD_LLM_MODEL:-opus}"
DEFAULT_TIMEOUT="${SHEPHERD_LLM_TIMEOUT:-120}"

usage() {
  cat <<'EOF'
services/llm/llm.sh — route a model call through the LOCAL Claude Code.

Usage:
  llm.sh complete [--prompt-file=F | --prompt=TXT | -] \
                  [--system-file=F | --system=TXT]     \
                  [--model=ALIAS] [--timeout=SEC]
        Prompt source precedence: --prompt-file > --prompt > stdin.
        Prints the model's raw text response to stdout (nothing else).
  llm.sh ping     Verify the claude binary is reachable (no completion).
  llm.sh help

Env: SHEPHERD_LLM_BIN (default claude) · SHEPHERD_LLM_MODEL (default opus)
     SHEPHERD_LLM_TIMEOUT (default 120s)
     SHEPHERD_LLM_MOCK=<file> / SHEPHERD_LLM_MOCK_TEXT=<str> — return verbatim,
       short-circuiting the claude call (deterministic, free gate tests).
Exit: 0 ok · 2 usage · 3 timeout · 4 llm/runtime error
EOF
}

die() { echo "llm.sh: $1" >&2; exit "${2:-1}"; }

# ── mock seam ────────────────────────────────────────────────────────────────
# Returns 0 and prints the mock payload if a mock is configured; returns 1 if no
# mock is set (caller proceeds to a real call).
_emit_mock_if_set() {
  if [[ -n "${SHEPHERD_LLM_MOCK:-}" ]]; then
    [[ -f "$SHEPHERD_LLM_MOCK" ]] || die "SHEPHERD_LLM_MOCK file not found: $SHEPHERD_LLM_MOCK" 4
    cat "$SHEPHERD_LLM_MOCK"
    return 0
  fi
  if [[ -n "${SHEPHERD_LLM_MOCK_TEXT:-}" ]]; then
    printf '%s\n' "$SHEPHERD_LLM_MOCK_TEXT"
    return 0
  fi
  return 1
}

# ── timeout watchdog (portable: macOS has no timeout/gtimeout) ────────────────
# Runs claude in the background and polls it from this shell. Do not implement
# the deadline as a background `sleep`: that process inherits stdout when the
# service is called inside command substitution and can keep the caller blocked
# for the full timeout after claude has already exited.
_stop_process_group() {
  local pgid="$1" ticks=0
  kill -TERM -- "-$pgid" 2>/dev/null || true
  while kill -0 -- "-$pgid" 2>/dev/null && (( ticks < 60 )); do
    sleep 0.05
    ticks=$((ticks + 1))
  done
  kill -KILL -- "-$pgid" 2>/dev/null || true
}

_complete_via_claude() {
  local secs="$1" model="$2" promptfile="$3" systemfile="$4"
  command -v "$BIN" >/dev/null 2>&1 || die "claude binary not found: $BIN (set SHEPHERD_LLM_BIN)" 4

  local td; td="$(mktemp -d 2>/dev/null || mktemp -d -t shepllm)"
  local outf="$td/out" errf="$td/err"

  local args
  args=( -p --output-format text --model "$model" )
  if [[ -n "$systemfile" ]]; then
    args=( "${args[@]}" --append-system-prompt "$(cat "$systemfile")" )
  fi

  # Monitor mode gives each background job its own process group on Bash 3.2+
  # (macOS and Linux). The CLI and every descendant therefore share a group we
  # can terminate without signaling this service or its caller.
  local monitor_was_on=0
  case "$-" in *m*) monitor_was_on=1 ;; esac
  set -m
  "$BIN" "${args[@]}" < "$promptfile" >"$outf" 2>"$errf" &
  local cpid=$!
  (( monitor_was_on )) || set +m

  # Count completed 50ms polling intervals. Integer wall clocks can cross a
  # second boundary immediately after launch and fire a one-second deadline
  # early; interval counting never expires before the requested duration.
  local ticks=0 max_ticks=$((secs * 20)) timed_out=0
  while kill -0 "$cpid" 2>/dev/null; do
    if (( ticks >= max_ticks )); then
      timed_out=1
      _stop_process_group "$cpid"
      break
    fi
    sleep 0.05
    ticks=$((ticks + 1))
  done

  local rc=0
  wait "$cpid" 2>/dev/null || rc=$?

  # A wrapper may exit after spawning a worker. The invocation owns that whole
  # tree even on the success path, so never leave group descendants behind.
  if kill -0 -- "-$cpid" 2>/dev/null; then
    _stop_process_group "$cpid"
  fi

  if (( timed_out )); then
    rm -rf "$td"
    die "completion timed out after ${secs}s" 3
  fi
  if (( rc != 0 )); then
    sed 's/^/  claude: /' "$errf" >&2 2>/dev/null || true
    rm -rf "$td"
    die "claude exited $rc" 4
  fi
  cat "$outf"
  rm -rf "$td"
}

cmd_complete() {
  local promptfile="" prompt="" systemfile="" system="" model="$DEFAULT_MODEL" secs="$DEFAULT_TIMEOUT"
  local a
  for a in "$@"; do
    case "$a" in
      --prompt-file=*) promptfile="${a#--prompt-file=}" ;;
      --prompt=*)      prompt="${a#--prompt=}" ;;
      --system-file=*) systemfile="${a#--system-file=}" ;;
      --system=*)      system="${a#--system=}" ;;
      --model=*)       model="${a#--model=}" ;;
      --timeout=*)     secs="${a#--timeout=}" ;;
      -)               : ;;
      -h|--help)       usage; exit 0 ;;
      *) die "unknown arg: $a" 2 ;;
    esac
  done
  [[ "$secs" =~ ^[0-9]+$ ]] || die "--timeout must be an integer (got '$secs')" 2

  # Mock short-circuits before resolving the prompt source at all — gate tests
  # don't need a prompt to assert the harness around the call.
  if _emit_mock_if_set; then return 0; fi

  # Resolve prompt to a file (precedence: --prompt-file > --prompt > stdin).
  local td=""; local pf=""
  if [[ -n "$promptfile" ]]; then
    [[ -f "$promptfile" ]] || die "--prompt-file not found: $promptfile" 2
    pf="$promptfile"
  elif [[ -n "$prompt" ]]; then
    td="$(mktemp -d 2>/dev/null || mktemp -d -t shepllm)"; pf="$td/p"
    printf '%s' "$prompt" > "$pf"
  else
    # stdin (with or without explicit '-')
    td="$(mktemp -d 2>/dev/null || mktemp -d -t shepllm)"; pf="$td/p"
    cat > "$pf"
    [[ -s "$pf" ]] || { rm -rf "$td"; die "no prompt: pass --prompt-file, --prompt, or pipe via stdin" 2; }
  fi

  # Resolve system prompt to a file if given inline.
  local sf="$systemfile" stmp=""
  if [[ -z "$sf" && -n "$system" ]]; then
    stmp="$(mktemp 2>/dev/null || mktemp -t shepllmsys)"; printf '%s' "$system" > "$stmp"; sf="$stmp"
  fi

  local rc=0
  _complete_via_claude "$secs" "$model" "$pf" "$sf" || rc=$?
  [[ -n "$td" ]] && rm -rf "$td"
  [[ -n "$stmp" ]] && rm -f "$stmp"
  return "$rc"
}

cmd_ping() {
  if [[ -n "${SHEPHERD_LLM_MOCK:-}${SHEPHERD_LLM_MOCK_TEXT:-}" ]]; then
    echo "llm.sh: MOCK mode active (no claude call)"; return 0
  fi
  command -v "$BIN" >/dev/null 2>&1 || die "claude binary not found: $BIN" 4
  echo "llm.sh: claude reachable — $("$BIN" --version 2>/dev/null || echo '?'); default model=$DEFAULT_MODEL"
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  complete) cmd_complete "$@" ;;
  ping)     cmd_ping "$@" ;;
  help|-h|--help) usage ;;
  *) die "unknown subcommand: $cmd (try: complete | ping | help)" 2 ;;
esac
