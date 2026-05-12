#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

root="$(shctx_artifacts_root)"
repo="$(shctx_repo_root)"

# Conflict guard: refuse to create a NEW namespace when the OTHER is already an
# initialized shctx workspace. Without this check, a bare `shctx init` on a
# project whose shepherd.toml [paths] reference .artifacts/ would silently
# create .shepherd/ (the v5.0.0+ default), resulting in a split-brain where
# shctx data lives in one namespace while the conductor writes seeds and plans
# to the other.
#
# The check is intentionally narrow: it only fires when the TARGET directory
# does not yet exist (fresh creation) and the OTHER directory carries the shctx
# .gitignore marker written during a prior successful init.
if [[ ! -d "$root" ]]; then
  if [[ "$(basename "$root")" == ".shepherd" && -f "$repo/.artifacts/.gitignore" ]]; then
    echo "ERROR: .artifacts/ is already an initialized shctx namespace." >&2
    echo "  Creating .shepherd/ alongside it would cause a split-brain where shctx" >&2
    echo "  data and shepherd.toml [paths] entries diverge." >&2
    echo "" >&2
    echo "  To keep using .artifacts/ (recommended for existing projects):" >&2
    echo "    shctx init --artifacts" >&2
    echo "" >&2
    echo "  To migrate to .shepherd/ (new default):" >&2
    echo "    mv .artifacts .shepherd  # move your content first" >&2
    echo "    shctx init --shepherd" >&2
    exit 1
  fi
  if [[ "$(basename "$root")" == ".artifacts" && -f "$repo/.shepherd/.gitignore" ]]; then
    echo "ERROR: .shepherd/ is already an initialized shctx namespace." >&2
    echo "  Creating .artifacts/ alongside it would cause a split-brain." >&2
    echo "" >&2
    echo "  To keep using .shepherd/ (recommended):" >&2
    echo "    shctx init --shepherd" >&2
    exit 1
  fi
fi

mkdir -p "$root"/{ctx,plans,reports,docs/{handoffs,specs,diagrams,journal},logs,tmp,profiles}

# Per-project .gitignore (idempotent — only writes if absent).
gi="$root/.gitignore"
if [[ ! -f "$gi" ]]; then
  cat > "$gi" <<'EOF'
# shepherd context registry — gitignored by default.
# Remove these lines to commit the registry to the repo.
root.db
root.db-journal
root.db-wal
root.db-shm
shepherd.lock
project.json
tmp/
logs/
EOF
fi

# CONVENTIONS.md (idempotent).
conv="$root/CONVENTIONS.md"
if [[ ! -f "$conv" ]]; then
  cp "$(shctx_skill_root)/references/naming-conventions.md" "$conv"
fi
