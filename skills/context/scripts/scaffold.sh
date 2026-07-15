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

mkdir -p "$root"/{archive,cache,ctx,docs/{plans,reports,handoffs,specs,diagrams,journal},logs,scripts,templates,tmp,types,profiles,styles}

# .gitkeep placeholders for new TRACKED dirs that git won't persist when empty.
for _d in archive scripts templates types docs/plans docs/reports; do
  [[ ! -f "$root/$_d/.gitkeep" ]] && touch "$root/$_d/.gitkeep"
done
# Retained dirs that already carry .gitkeep in mature trees get the same treatment.
for _d in docs/journal docs/handoffs docs/diagrams; do
  [[ ! -f "$root/$_d/.gitkeep" ]] && touch "$root/$_d/.gitkeep"
done

# Per-project .gitignore (idempotent — only writes if absent).
gi="$root/.gitignore"
if [[ ! -f "$gi" ]]; then
  cat > "$gi" <<'EOF'
# shepherd context registry — gitignored by default.
# Remove these lines to commit the registry to the repo.
#
# New standard DB name (v6.1.0+):
shepherd.db
shepherd.db-journal
shepherd.db-wal
shepherd.db-shm
# Legacy DB name (retained for back-compat — do not remove):
root.db
root.db-journal
root.db-wal
root.db-shm
shepherd.lock
project.json

# Transient runtime dirs (never tracked).
tmp/
logs/
cache/
runs/
dispatch/
discoveries/
insights/
pauses/

# Secret hygiene — never commit credentials/keys from the work dir.
*.env
.env
*.key
*.pem
*.secret
secrets/
credentials*

# Tracked subtrees stay tracked:
# docs/ styles/ profiles/ ctx/ archive/ scripts/ templates/ types/
EOF
fi

# CONVENTIONS.md (idempotent).
conv="$root/CONVENTIONS.md"
if [[ ! -f "$conv" ]]; then
  cp "$(shctx_skill_root)/references/naming-conventions.md" "$conv"
fi
