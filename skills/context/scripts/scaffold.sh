#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

root="$(shctx_artifacts_root)"
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
