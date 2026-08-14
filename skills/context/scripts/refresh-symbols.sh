#!/usr/bin/env bash
# Rust symbol extractor — best-effort grep-based (v5.0.0). Tree-sitter in v5.x.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

command -v cargo >/dev/null || { echo "shctx: cargo not installed; skipping rust symbols"; exit 0; }
project_id=$(shctx_project_id)
now=$(shctx_now)

# Enumerate workspace packages via `cargo metadata`.
# Portability: bash 3.2 (default macOS /bin/bash) lacks `mapfile`; fall back to read loop.
pkgs=()
if declare -F mapfile >/dev/null 2>&1 || type -t mapfile >/dev/null 2>&1; then
  mapfile -t pkgs < <(cargo metadata --format-version 1 --no-deps 2>/dev/null \
    | jq -r '.packages[] | "\(.name)\t\(.manifest_path)"')
else
  while IFS= read -r line; do pkgs+=("$line"); done < <(
    cargo metadata --format-version 1 --no-deps 2>/dev/null \
      | jq -r '.packages[] | "\(.name)\t\(.manifest_path)"'
  )
fi

(( ${#pkgs[@]} > 0 )) || { echo "shctx: no rust packages found"; exit 0; }

# Note: shctx_sql() spawns a fresh sqlite3 process per call, so BEGIN/COMMIT
# cannot wrap a multi-statement transaction here; statements auto-commit.
for row in "${pkgs[@]}"; do
  name=${row%%$'\t'*}
  manifest=${row##*$'\t'}
  pkg_dir=$(dirname "$manifest")
  rel_pkg=${pkg_dir#$(shctx_repo_root)/}
  # File-path-derived values (same class of gap as #291's dirname finding —
  # a path can legally contain an apostrophe) are escaped at each INSERT
  # below via rel_pkg_esc/rel_esc rather than here, so a fresh $rel per file
  # is always escaped alongside it.
  rel_pkg_esc=$(esc "$rel_pkg")

  while IFS= read -r -d '' f; do
    rel=${f#$(shctx_repo_root)/}
    rel_esc=$(esc "$rel")
    # v5.0.3: extended regex covers
    #   - `pub fn|struct|trait|enum|const|static|type|mod`
    #   - modifier sequences (`async`, `unsafe`, `const`, `extern "C"`)
    #   - `pub use foo::bar;` and `pub use foo::{bar, baz};` re-exports
    #   - multi-line `pub trait Foo: Bar where ...` (matches the line with the trait name)
    # Capture grep output (|| true) so files with no matches don't trip pipefail.
    matches=$(grep -nE '^[[:space:]]*(pub(\([^)]+\))?[[:space:]]+)?((async|unsafe|const|extern([[:space:]]*"[^"]*")?)[[:space:]]+)*(fn|struct|trait|enum|const|static|type|mod|use)[[:space:]]+([A-Za-z_][A-Za-z0-9_]*|\{)' "$f" 2>/dev/null || true)
    [[ -z "$matches" ]] && continue
    while IFS=: read -r line content; do
      [[ -z "$line" ]] && continue
      # Normalize: strip leading whitespace, peel off vis, then peel off modifiers,
      # then read kind + name. `const` is only treated as a modifier when followed by `fn`.
      c="${content#"${content%%[![:space:]]*}"}"
      vis="private"
      if [[ "$c" =~ ^(pub(\([^\)]+\))?)[[:space:]] ]]; then
        vis="${BASH_REMATCH[1]}"
        c="${c#${BASH_REMATCH[1]}}"
        c="${c#"${c%%[![:space:]]*}"}"
      fi
      while [[ "$c" =~ ^(async|unsafe|extern[[:space:]]*\"[^\"]*\"|extern)[[:space:]] ]]; do
        c="${c#${BASH_REMATCH[1]}}"
        c="${c#"${c%%[![:space:]]*}"}"
      done
      if [[ "$c" =~ ^const[[:space:]]+fn[[:space:]] ]]; then
        c="${c#const}"
        c="${c#"${c%%[![:space:]]*}"}"
      fi

      kind=""; sym=""
      if [[ "$c" =~ ^(fn|struct|trait|enum|const|static|type|mod)[[:space:]]+([A-Za-z_][A-Za-z0-9_]*) ]]; then
        kind="${BASH_REMATCH[1]}"
        sym="${BASH_REMATCH[2]}"
      elif [[ "$c" =~ ^use[[:space:]]+(.+)$ ]]; then
        # Re-export: `pub use foo::Bar;` (only `pub use` is interesting — private `use` is just an import).
        # Skip private `use` — we only index re-exports.
        [[ "$vis" == private ]] && continue
        path_expr="${BASH_REMATCH[1]}"
        # Strip trailing `;`, `{...}` group bodies, comments.
        path_expr="${path_expr%;*}"
        # Find names in either `path::Name` (single re-export) or `path::{A, B as C}` (group re-export).
        if [[ "$path_expr" =~ \{(.+)\} ]]; then
          # Group: split on commas, take each item (handle `as Alias`).
          group="${BASH_REMATCH[1]}"
          # bash 3.2 lacks readarray; use IFS
          IFS=',' read -ra items <<< "$group"
          for raw in "${items[@]}"; do
            item="${raw#"${raw%%[![:space:]]*}"}"
            item="${item%"${item##*[![:space:]]}"}"
            [[ -z "$item" ]] && continue
            # `Foo as Bar` ⇒ Bar; `Foo` ⇒ Foo
            if [[ "$item" =~ [[:space:]]as[[:space:]]+([A-Za-z_][A-Za-z0-9_]*) ]]; then
              sym="${BASH_REMATCH[1]}"
            elif [[ "$item" =~ ([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*$ ]]; then
              sym="${BASH_REMATCH[1]}"
            else
              continue
            fi
            kind="re-export"
            sig=$(esc "$(printf '%s' "$content" | sed -e 's/^[[:space:]]*//')")
            hash=$(printf '%s' "$rel:$line:$sym" | shasum -a 256 | awk '{print $1}')
            uid=$(shctx_uuid7)
            # $sym is regex-restricted to [A-Za-z_][A-Za-z0-9_]* (safe by
            # construction); $vis can carry arbitrary text inside `pub(...)`
            # (e.g. `pub(in some::path)`) so it is esc()'d like every other
            # free-text field here.
            shctx_sql "INSERT INTO index_symbols
              (id, project_id, name, kind, package, file_path, line, visibility, signature, doc_summary, language, hash, refreshed_at)
              VALUES ('$uid','$(esc "$project_id")','$sym','$kind','$rel_pkg_esc','$rel_esc',$line,'$(esc "$vis")','$sig',NULL,'rust','$hash',$now)
              ON CONFLICT(project_id,name,package,kind) DO UPDATE SET
                file_path=excluded.file_path, line=excluded.line,
                visibility=excluded.visibility, signature=excluded.signature,
                hash=excluded.hash, refreshed_at=excluded.refreshed_at;"
          done
          continue
        else
          # Single: take the last segment, handle `as Alias`
          if [[ "$path_expr" =~ [[:space:]]as[[:space:]]+([A-Za-z_][A-Za-z0-9_]*) ]]; then
            sym="${BASH_REMATCH[1]}"
          elif [[ "$path_expr" =~ ([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*$ ]]; then
            sym="${BASH_REMATCH[1]}"
          else
            continue
          fi
          kind="re-export"
        fi
      else
        continue
      fi

      [[ -z "$sym" || -z "$kind" ]] && continue
      sig=$(esc "$(printf '%s' "$content" | sed -e 's/^[[:space:]]*//')")
      hash=$(printf '%s' "$rel:$line:$sig" | shasum -a 256 | awk '{print $1}')
      uid=$(shctx_uuid7)
      shctx_sql "INSERT INTO index_symbols
        (id, project_id, name, kind, package, file_path, line, visibility, signature, doc_summary, language, hash, refreshed_at)
        VALUES ('$uid','$(esc "$project_id")','$sym','$kind','$rel_pkg_esc','$rel_esc',$line,'$(esc "$vis")','$sig',NULL,'rust','$hash',$now)
        ON CONFLICT(project_id,name,package,kind) DO UPDATE SET
          file_path=excluded.file_path, line=excluded.line,
          visibility=excluded.visibility, signature=excluded.signature,
          hash=excluded.hash, refreshed_at=excluded.refreshed_at;"
    done <<< "$matches"
  done < <(find "$pkg_dir/src" -type f -name '*.rs' -print0 2>/dev/null)
done

# Sweep stale rows (rust only) older than this run.
shctx_sql "DELETE FROM index_symbols WHERE project_id='$(esc "$project_id")' AND language='rust' AND refreshed_at<$now;"
echo "shctx refresh symbols: ok"
