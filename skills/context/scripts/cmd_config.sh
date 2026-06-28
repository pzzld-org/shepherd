#!/usr/bin/env bash
# shctx config — scaffold / inspect the project shepherd.toml binding.
#
# `config claude-md` (v6.2.0) materializes the portable operating doctrine into
# the consumer repo's CLAUDE.md as a fenced managed block (append-only, never
# clobbers operator content; --force re-syncs only the block). Companion to the
# session-surfaced doctrines/operating-philosophy.md framework binding.
#
# `config init` (v6.1.5, #15) writes a first-ever .claude/shepherd.toml from the
# bundled examples/minimal template, deriving the project `name` (git remote → cwd)
# and the `[gates]` toolchain (Cargo.toml→cargo, go.mod→go, pyproject→pytest,
# package.json→npm). It is IDEMPOTENT: an existing project/local config is never
# clobbered. The write target is cfg_get's canonical project location
# (.claude/shepherd.toml). This replaces the hard "no config" stops in
# start/spawn/plant with a scaffold→notice→proceed flow (plant adds one question).
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# Resolve the plugin install root (where examples/ lives). Prefer
# CLAUDE_PLUGIN_ROOT when it actually carries examples/; otherwise climb out of
# skills/context/scripts/ to the repo root (dev / test layout).
plugin_root() {
  if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" && -d "${CLAUDE_PLUGIN_ROOT}/examples" ]]; then
    echo "${CLAUDE_PLUGIN_ROOT}"
  else
    cd "$HERE/../../.." && pwd
  fi
}

# Derive a project name: git remote origin basename (strip .git) → repo-root basename.
derive_name() {
  local root url name
  root="$(shctx_repo_root)"
  url="$(git -C "$root" remote get-url origin 2>/dev/null || true)"
  if [[ -n "$url" ]]; then
    name="${url##*/}"; name="${name%.git}"
  else
    name="$(basename "$root")"
  fi
  echo "$name"
}

# Detect the gate toolchain from build-manifest presence at the repo root.
# Echoes a pipe-delimited tuple: "<language>|<check>|<lint>|<format>".
detect_gates() {
  local root; root="$(shctx_repo_root)"
  if   [[ -f "$root/Cargo.toml" ]]; then
    echo 'rust|cargo check --workspace|cargo clippy --workspace -- -D warnings|cargo fmt --all'
  elif [[ -f "$root/go.mod" ]]; then
    echo 'go|go build ./...|go vet ./...|gofmt -l .'
  elif [[ -f "$root/pyproject.toml" || -f "$root/setup.py" ]]; then
    echo 'python|pytest -q|ruff check .|ruff format .'
  elif [[ -f "$root/package.json" ]]; then
    echo 'typescript|npm run build --if-present|npm run lint --if-present|npm run format --if-present'
  else
    # No manifest detected — keep the template's rust defaults (operator edits later).
    echo 'rust|cargo check --workspace|cargo clippy --workspace -- -D warnings|cargo fmt --all'
  fi
}

do_init() {
  local force=0
  [[ "${1:-}" == "--force" ]] && force=1
  local repo dst src name ns gates lang check lint fmt
  repo="$(shctx_repo_root)"
  dst="$repo/.claude/shepherd.toml"

  # Idempotent: never clobber an existing project or local-override binding.
  if [[ "$force" -eq 0 ]]; then
    if [[ -f "$dst" ]]; then
      echo "shctx config: $dst already exists (preserving)"; return 0
    fi
    if [[ -f "$repo/.claude/shepherd.local.toml" || -f "$repo/.local.toml" ]]; then
      echo "shctx config: a local-override config is present (preserving; no project binding written)"; return 0
    fi
  fi

  src="$(plugin_root)/examples/minimal/shepherd.toml"
  [[ -f "$src" ]] || { echo "ERROR: bundled template missing: $src" >&2; return 1; }

  name="$(derive_name)"
  ns="$(basename "$(SHCTX_QUIET=1 resolve_workdir)")"   # .shepherd | .artifacts
  gates="$(detect_gates)"
  lang="${gates%%|*}"; gates="${gates#*|}"
  check="${gates%%|*}"; gates="${gates#*|}"
  lint="${gates%%|*}"; fmt="${gates#*|}"

  mkdir -p "$repo/.claude"
  # Patch derived values into the bundled minimal template. Only the key lines are
  # rewritten; comments and structure are preserved verbatim. The [paths] namespace
  # is realigned to the project's active shctx namespace (resolve_workdir), so a
  # project bootstrapped with `shctx init --artifacts` gets matching paths.
  awk -v name="$name" -v lang="$lang" -v ck="$check" -v lt="$lint" -v ft="$fmt" -v ns="$ns" '
    /^name[[:space:]]*=/     { print "name     = \"" name "\"";              next }
    /^language[[:space:]]*=/ { print "language = \"" lang "\""; next }
    /^check[[:space:]]*=/    { print "check  = \"" ck "\"";                  next }
    /^lint[[:space:]]*=/     { print "lint   = \"" lt "\"";                  next }
    /^format[[:space:]]*=/   { print "format = \"" ft "\"";                  next }
    /^(plans|reports|docs|ctx)[[:space:]]*=/ { gsub(/\.shepherd/, ns); print; next }
    { print }
  ' "$src" > "$dst"

  echo "shctx config: scaffolded $dst"
  echo "  name=$name  language=$lang  namespace=$ns"
  echo "  gates: check=\"$check\" lint=\"$lint\" format=\"$fmt\""
  echo "  Review [branching] + [gates] before your first sprint."
}

# Materialize the portable operating doctrine into the consumer repo's CLAUDE.md
# as a FENCED MANAGED BLOCK (v6.2.0). Mirrors do_init's bundled-template→consumer
# copy, but append-only and never-clobber: operator content OUTSIDE the markers is
# always preserved; --force re-syncs ONLY the managed block to the current plugin
# version. The block is the durable, all-sessions pin of the how-to-work doctrine
# whose framework binding lives in doctrines/operating-philosophy.md.
CLAUDEMD_BEGIN='<!-- BEGIN shepherd:operating-doctrine'
CLAUDEMD_END='<!-- END shepherd:operating-doctrine -->'

do_claude_md() {
  local force=0
  [[ "${1:-}" == "--force" ]] && force=1
  local repo dst src
  repo="$(shctx_repo_root)"
  dst="$repo/CLAUDE.md"
  src="$(plugin_root)/examples/minimal/CLAUDE.md"
  [[ -f "$src" ]] || { echo "ERROR: bundled template missing: $src" >&2; return 1; }

  # No CLAUDE.md yet → the managed block IS the file.
  if [[ ! -f "$dst" ]]; then
    cat "$src" > "$dst"
    echo "shctx config: wrote $dst (shepherd operating doctrine)"
    return 0
  fi

  # Managed block already present.
  if grep -qF "$CLAUDEMD_BEGIN" "$dst"; then
    if [[ "$force" -eq 0 ]]; then
      echo "shctx config: $dst already carries the shepherd doctrine block (preserving; --force to re-sync)"
      return 0
    fi
    # Guard: a BEGIN with no END marker means the awk would set inblock=1 and
    # never reset, silently dropping every line after BEGIN. Refuse rather than
    # swallow operator content placed after a hand-damaged block.
    if ! grep -qF "$CLAUDEMD_END" "$dst"; then
      echo "ERROR: $dst has a BEGIN marker but no '$CLAUDEMD_END' — refusing to re-sync (would drop trailing content). Repair the markers manually." >&2
      return 1
    fi
    # Re-sync: replace ONLY the BEGIN..END block, preserve everything else.
    local tmp; tmp="$(mktemp)"
    awk -v beginm="$CLAUDEMD_BEGIN" -v endm="$CLAUDEMD_END" -v src="$src" '
      index($0, beginm) > 0 {
        while ((getline line < src) > 0) print line
        close(src); inblock=1; next
      }
      inblock && index($0, endm) > 0 { inblock=0; next }
      inblock { next }
      { print }
    ' "$dst" > "$tmp"
    mv "$tmp" "$dst"
    echo "shctx config: re-synced the shepherd doctrine block in $dst"
    return 0
  fi

  # Existing CLAUDE.md, no managed block → APPEND (never clobber operator content).
  { printf '\n'; cat "$src"; } >> "$dst"
  echo "shctx config: appended the shepherd operating doctrine block to $dst (operator content preserved)"
}

sub="${1:-help}"; shift || true
case "$sub" in
  init) do_init "${1:-}" ;;
  claude-md) do_claude_md "${1:-}" ;;
  get)
    # Resolve a single key through cfg_get (local → project → XDG), optionally
    # falling back to a supplied default when unset. The one uniform read path
    # the v6.1.5 toggles (#10) and any agent/script use to get an effective value.
    key="${1:-}"; def="${2:-}"
    [[ -n "$key" ]] || { echo "ERROR: usage: shctx config get <key> [default]" >&2; exit 1; }
    v="$(cfg_get "$key")"
    [[ -n "$v" ]] && printf '%s\n' "$v" || printf '%s\n' "$def"
    ;;
  show)
    repo="$(shctx_repo_root)"; found=0
    for f in "$repo/.claude/shepherd.local.toml" "$repo/.claude/shepherd.toml"; do
      if [[ -f "$f" ]]; then echo "# $f"; cat "$f"; echo; found=1; fi
    done
    [[ "$found" -eq 1 ]] || echo "(no .claude/shepherd.toml — run 'shctx config init')"
    ;;
  path)
    echo "$(shctx_repo_root)/.claude/shepherd.toml"
    ;;
  help|-h|--help)
    cat <<'EOF'
shctx config — scaffold / inspect the project shepherd.toml binding

Usage:
  shctx config init [--force]   Scaffold .claude/shepherd.toml from the bundled
                                minimal template (idempotent). Derives [project].name
                                (git remote → cwd) + [gates] (Cargo.toml→cargo,
                                go.mod→go, pyproject→pytest, package.json→npm), and
                                realigns [paths] to the active shctx namespace.
  shctx config claude-md [--force]
                                Materialize the portable operating doctrine into the
                                repo's CLAUDE.md as a fenced managed block. Append-only
                                and never-clobber (operator content outside the markers
                                is preserved); --force re-syncs only the managed block.
  shctx config show             Print the resolved project/local config.
  shctx config path             Echo the canonical write location.
  shctx config get <key> [def]  Resolve one key via cfg_get (local→project→XDG),
                                echoing [def] when unset. The uniform read path for
                                the v6.1.5 toggles (on_grade_floor, inter_sprint_pause,
                                max_parallel, dashboard_cadence, …).
EOF
    ;;
  *) echo "ERROR: usage: shctx config <init|claude-md|show|path|get>" >&2; exit 1 ;;
esac
