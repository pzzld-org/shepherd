#!/usr/bin/env bash
# shctx models <resolve|show> — per-role subagent model map (v6.2.5).
#
# The single place to map each flock/meta role to the model it dispatches with,
# so ultra-parallel spawns for long durations stop relying on hand-pinned
# `model:` slugs (the v6.0.9 conductor pin was the one-off precursor). Reads the
# `[models]` block of .claude/shepherd.toml via the section-aware cfg_section_get
# precedence (local → project → XDG); falls back to the built-in defaults below
# when a role is unset.
#
# Resolution chain (forward-compatible — profiles/modes slot into 2–3 later
# with zero rework to this map; skills/shepherd/references/pipeline.md §INTRO and
# docs/configuration.md §models):
#   1. explicit [models].<role> key      ← ships now (total control)
#   2. active profile/mode preset        ← future (deferred)
#   3. root-tier-derived default         ← future (deferred)
#   4. built-in default                  ← ships now (= stated defaults)
#
#   resolve <role>       echo the resolved model slug for one role.
#   show [--md|--json]    print the full resolved 9-role table + source per row.
#
# Dispatch wiring: every dispatching tier (root/shepherd, conductor, engineer)
# calls `shctx models resolve <role>` and injects the result as the Agent-tool
# `model:` pin / teammate spawn pin. root is ADVISORY (docs/configuration.md
# §models) — a config key cannot rebind a running main-chat session, so `show`
# flags it and the 8 spawned roles are the ones actually hard-driven.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# Canonical role set + built-in defaults (bash-3.2-safe: case, not assoc array).
MODELS_ROLES="root planter engineer conductor critic discovery coder auditor worker"

_model_default() {
  case "$1" in
    root|planter|engineer)                           echo "opus[1m]" ;;
    conductor|critic|discovery|coder|auditor|worker) echo "sonnet" ;;
    *)                                               echo "" ;;
  esac
}

# Prints "<model>\t<source>" for one role; source is config|default.
_model_row() {
  local role="$1" v
  v="$(cfg_section_get models "$role" 2>/dev/null || true)"
  if [[ -n "$v" ]]; then printf '%s\tconfig' "$v"; else printf '%s\tdefault' "$(_model_default "$role")"; fi
}

usage() {
  cat <<'EOF'
shctx models <resolve|show> [args]

  resolve <role>        Echo the resolved model slug for one role
                        (explicit [models].<role> key, else built-in default).
                        Roles: root planter engineer conductor critic
                               discovery coder auditor worker
  show [--md|--json]    Print the full resolved 9-role table + source per row.

The [models] block in .claude/shepherd.toml is the single map; unset roles fall
to the built-in defaults (root/planter/engineer = opus[1m]; the rest = sonnet).
See docs/configuration.md §models.
EOF
}

sub="${1:-}"; shift || true
case "$sub" in
  resolve)
    role="${1:-}"
    [[ -n "$role" ]] || { echo "ERROR: usage: shctx models resolve <role>" >&2; exit 2; }
    case " $MODELS_ROLES " in
      *" $role "*) : ;;
      *) echo "ERROR: unknown role: $role (valid: $MODELS_ROLES)" >&2; exit 2 ;;
    esac
    row="$(_model_row "$role")"
    printf '%s\n' "${row%%$'\t'*}"
    ;;
  show|"")
    fmt="text"
    for a in "$@"; do case "$a" in --md) fmt="md" ;; --json) fmt="json" ;; -h|--help) usage; exit 0 ;; esac; done
    if [[ "$fmt" == "json" ]]; then
      printf '{\n'
      first=1
      for r in $MODELS_ROLES; do
        row="$(_model_row "$r")"; m="${row%%$'\t'*}"; src="${row##*$'\t'}"
        if [[ $first -eq 1 ]]; then first=0; else printf ',\n'; fi
        printf '  "%s": {"model": "%s", "source": "%s"}' "$r" "$m" "$src"
      done
      printf '\n}\n'
    elif [[ "$fmt" == "md" ]]; then
      printf '| role | model | source |\n|---|---|---|\n'
      for r in $MODELS_ROLES; do
        row="$(_model_row "$r")"; printf '| %s | `%s` | %s |\n' "$r" "${row%%$'\t'*}" "${row##*$'\t'}"
      done
      printf '\n_root is advisory: it names the model your live session should run; a config key cannot rebind a running main-chat session._\n'
    else
      printf 'shepherd model map (resolved)\n'
      for r in $MODELS_ROLES; do
        row="$(_model_row "$r")"; printf '  %-10s %-10s (%s)\n' "$r" "${row%%$'\t'*}" "${row##*$'\t'}"
      done
      printf '\nroot is advisory (your live session model). The 8 spawned roles are\nhard-driven: each dispatching tier injects `shctx models resolve <role>` as\nthe model pin. See docs/configuration.md §models.\n'
    fi
    ;;
  -h|--help|help) usage; exit 0 ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 2 ;;
esac
