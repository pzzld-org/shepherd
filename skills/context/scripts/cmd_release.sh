#!/usr/bin/env bash
# shctx release — algorithmic gear-cascade release pipeline.
#
# Two operational modes (auto-detected from current branch shape):
#
#   sprint-end mode:
#     - current branch matches sprint pattern  (e.g. v0.2.9-dev.5).
#     - if sprint N == sprints_per_patch - 1: full cascade (rebase → squash → tag → release → cut next).
#     - else: rebase the dev branch into the patch branch, delete it, cut the next dev.
#
#   lighter-pattern mode:
#     - current branch matches the patch pattern directly (e.g. v5.0.0).
#     - skip the rebase step; jump to squash → tag → release → cascade.
#
# Cascade per major X (unbounded). Each patch X.Y.Z has 10 sprints (mod 10 by default).
#   Z < 9          → cut X.Y.{Z+1} from main
#   Z == 9, Y < 9  → cut X.{Y+1}.0 from main
#   Z == 9, Y == 9 → cut {X+1}.0.0 from main
#
# Flags:
#   --dry-run             Print the plan without executing any git/gh action.
#   --skip=tag,gh,bump    Comma-separated list of steps to skip (tag, gh, bump, push).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

DRY_RUN=0
SKIP_TAG=0
SKIP_GH=0
SKIP_BUMP=0
SKIP_PUSH=0

usage() {
  cat <<'EOF'
shctx release [--dry-run] [--skip=tag,gh,bump,push]

Run the algorithmic gear-cascade release pipeline. Mode is auto-detected from
the current git branch:

  sprint-end mode  — branch like v0.2.9-dev.5 (rebase → patch close → cascade)
  lighter-pattern  — branch like v5.0.0      (squash → tag → release → cascade)

Defaults (TOML overrides not yet wired):
  patch_branch_pattern  = v{X}.{Y}.{Z}
  sprint_branch_pattern = v{X}.{Y}.{Z}-dev.{N}
  sprints_per_patch     = 10
  main_branch           = main

Use --dry-run to print the plan without executing.
EOF
}

for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    --skip=*)
      IFS=, read -r -a parts <<< "${a#--skip=}"
      for p in "${parts[@]}"; do
        case "$p" in
          tag)  SKIP_TAG=1 ;;
          gh)   SKIP_GH=1 ;;
          bump) SKIP_BUMP=1 ;;
          push) SKIP_PUSH=1 ;;
          *)    echo "ERROR: unknown skip step: $p" >&2; exit 1 ;;
        esac
      done
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown flag: $a" >&2; usage >&2; exit 1 ;;
  esac
done

# ---- config (read from .claude/shepherd.toml; defaults when file/key absent) ----
# sprints_per_patch is the mod-N cascade base: it sets LAST_SPRINT below (the
# release-vs-next-sprint trigger) and is the floor every consumer reasons about.
# Hardcoding it — the prior "TOML wiring deferred" state — silently gave projects
# on sprints_per_patch != 10 (the shipped examples use 5 and 7) the WRONG release
# trigger: dev.4 of a 5-sprint patch would be treated as mid-patch and cut dev.5.
# Lightweight grep — bash-3.2-safe, no TOML parser; last match wins; section-agnostic
# (the key is unique under [branching]).
SPRINTS_PER_PATCH="$(cfg_get sprints_per_patch | grep -oE '[0-9]+' | tail -1 || true)"
[[ "$SPRINTS_PER_PATCH" =~ ^[0-9]+$ ]] || SPRINTS_PER_PATCH=10
# NOTE: next_version() below still hardcodes the `< 9` rollover for the
# patch→minor→major gears. That is correct for the default mod-10 convention but
# not for projects overriding [branching].mod_base per level (branching-model.md
# §IV note). Wiring those three bases is a separate follow-up; the sprint-level
# trigger (the dev.{last} bug) is fixed here.
MAIN_BRANCH="main"

# Default version-file list (path:format).
#   json:  patches the "version" key in a JSON file.
#   yaml:  patches a YAML `version:` key (skill manifest).
#   readme:patches the literal `Current version: **X.Y.Z**` line.
VERSION_FILES=(
  ".claude-plugin/plugin.json:json"
  "skills/shepherd/SKILL.md:yaml"
  "skills/context/SKILL.md:yaml"
  ".claude-plugin/marketplace.json:json"
  "README.md:readme"
)

CHANGELOG_PATH="CHANGELOG.md"

# ---- helpers ----
log()  { echo "shctx release: $*"; }
plan() { echo "  PLAN: $*"; }
run() {
  if (( DRY_RUN )); then
    plan "$*"
  else
    log "exec: $*"
    eval "$@"
  fi
}

current_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || echo ""
}

# Parse a branch name into mode + components.
# Sets globals: BRANCH_MODE (sprint|patch|none), VER_X, VER_Y, VER_Z, SPRINT_N (sprint mode).
parse_branch() {
  local b="$1"
  BRANCH_MODE=none; VER_X=""; VER_Y=""; VER_Z=""; SPRINT_N=""
  # sprint pattern: v<X>.<Y>.<Z>-dev.<N>
  if [[ "$b" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)-dev\.([0-9]+)$ ]]; then
    BRANCH_MODE=sprint
    VER_X="${BASH_REMATCH[1]}"
    VER_Y="${BASH_REMATCH[2]}"
    VER_Z="${BASH_REMATCH[3]}"
    SPRINT_N="${BASH_REMATCH[4]}"
    return 0
  fi
  # patch pattern: v<X>.<Y>.<Z>
  if [[ "$b" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    BRANCH_MODE=patch
    VER_X="${BASH_REMATCH[1]}"
    VER_Y="${BASH_REMATCH[2]}"
    VER_Z="${BASH_REMATCH[3]}"
    return 0
  fi
  return 0
}

# Compute the next version per cascade. Sets NEXT_X/NEXT_Y/NEXT_Z.
next_version() {
  local x="$1" y="$2" z="$3"
  if   (( z < 9 )); then NEXT_X="$x"; NEXT_Y="$y"; NEXT_Z=$((z + 1))
  elif (( y < 9 )); then NEXT_X="$x"; NEXT_Y=$((y + 1)); NEXT_Z=0
  else                   NEXT_X=$((x + 1)); NEXT_Y=0; NEXT_Z=0
  fi
}

# Tag exists locally?
tag_exists() {
  git rev-parse --verify --quiet "refs/tags/$1" >/dev/null
}

# Branch already squash-merged into main? (Rough heuristic — looks for the patch tag pointing into main.)
already_merged_into_main() {
  local branch="$1"
  git merge-base --is-ancestor "$branch" "$MAIN_BRANCH" 2>/dev/null
}

# Extract release notes from CHANGELOG.md for a given vX.Y.Z section.
# Looks for a heading line that contains the version and emits everything until the next `## ` heading.
extract_release_notes() {
  local version="$1" file="$2"
  [[ -f "$file" ]] || { echo "(no CHANGELOG.md found at $file)"; return 0; }
  awk -v ver="$version" '
    BEGIN { capture=0 }
    /^## / {
      if (capture) exit
      if (index($0, ver) > 0) { capture=1; next }
    }
    capture { print }
  ' "$file"
}

# Bump a single file per format. Operates in dry-run-safe manner: uses temp file + mv.
bump_file() {
  local entry="$1" new_version="$2"
  local path="${entry%%:*}"
  local fmt="${entry##*:}"
  local repo; repo="$(shctx_repo_root)"
  local full="$repo/$path"
  if [[ ! -f "$full" ]]; then
    plan "skip bump (not found): $path"
    return 0
  fi
  if (( DRY_RUN )); then
    plan "bump ($fmt) $path → $new_version"
    return 0
  fi
  local tmp="$full.shctx-bump.$$"
  case "$fmt" in
    json)
      # Patch top-level "version" key, plus any nested plugins[].version
      # (marketplace.json carries both — the nested block drifted before #130).
      # plugin.json has no `plugins` key, so the guarded branch is a no-op there.
      jq --arg v "$new_version" '
        .version = $v
        | (if has("plugins") then .plugins |= map(.version = $v) else . end)
      ' "$full" > "$tmp"
      mv "$tmp" "$full"
      ;;
    yaml)
      # Patch YAML `version:` key (replace value to the right of the colon on the first match).
      awk -v v="$new_version" '
        BEGIN { done=0 }
        /^version:/ && !done { print "version: " v; done=1; next }
        { print }
      ' "$full" > "$tmp"
      mv "$tmp" "$full"
      ;;
    readme)
      # Replace the literal `Current version: **X.Y.Z**` line.
      awk -v v="$new_version" '
        /^Current version: \*\*[0-9]+\.[0-9]+\.[0-9]+\*\*/ { print "Current version: **" v "**"; next }
        { print }
      ' "$full" > "$tmp"
      mv "$tmp" "$full"
      ;;
    *)
      rm -f "$tmp"
      echo "ERROR: unknown bump format: $fmt" >&2; return 1 ;;
  esac
  log "bumped $path → $new_version"
}

# ---- mode dispatch ----
BRANCH="$(current_branch)"
parse_branch "$BRANCH"

log "current branch: ${BRANCH:-<unknown>} (mode: $BRANCH_MODE)"
if [[ "$BRANCH_MODE" == "none" ]]; then
  echo "ERROR: current branch '$BRANCH' does not match a known release pattern" >&2
  echo "       expected v<X>.<Y>.<Z> or v<X>.<Y>.<Z>-dev.<N>" >&2
  exit 1
fi

PATCH_VERSION="${VER_X}.${VER_Y}.${VER_Z}"
PATCH_BRANCH="v${PATCH_VERSION}"
TAG_PATCH="v${PATCH_VERSION}"
TAG_MINOR="v${VER_X}.${VER_Y}"
TAG_MAJOR="v${VER_X}"

# Decide the work plan.
case "$BRANCH_MODE" in
  sprint)
    log "sprint-end mode: dev.${SPRINT_N} of patch ${PATCH_VERSION}"
    LAST_SPRINT=$((SPRINTS_PER_PATCH - 1))
    if (( SPRINT_N < LAST_SPRINT )); then
      # Mid-patch: rebase dev into patch, delete dev, cut next dev.
      NEXT_SPRINT=$((SPRINT_N + 1))
      NEXT_DEV_BRANCH="v${PATCH_VERSION}-dev.${NEXT_SPRINT}"
      log "mid-patch sprint close: rebase dev.${SPRINT_N} → ${PATCH_BRANCH}, then cut dev.${NEXT_SPRINT}"
      run "git checkout ${PATCH_BRANCH}"
      run "git rebase ${BRANCH}"
      (( SKIP_PUSH )) || run "git push origin ${PATCH_BRANCH}"
      run "git branch -D ${BRANCH}"
      (( SKIP_PUSH )) || run "git push origin --delete ${BRANCH}"
      run "git checkout -b ${NEXT_DEV_BRANCH} ${PATCH_BRANCH}"
      (( SKIP_PUSH )) || run "git push -u origin ${NEXT_DEV_BRANCH}"
      log "done. now on ${NEXT_DEV_BRANCH}."
      exit 0
    fi
    log "patch-end sprint: rebase dev.${SPRINT_N} → ${PATCH_BRANCH}, then run full cascade"
    run "git checkout ${PATCH_BRANCH}"
    run "git rebase ${BRANCH}"
    (( SKIP_PUSH )) || run "git push origin ${PATCH_BRANCH}"
    run "git branch -D ${BRANCH}"
    (( SKIP_PUSH )) || run "git push origin --delete ${BRANCH}"
    # Fall through to the cascade below (now on ${PATCH_BRANCH}).
    BRANCH="${PATCH_BRANCH}"
    BRANCH_MODE=patch
    ;;
  patch)
    log "lighter-pattern mode: patch ${PATCH_VERSION} ready for release"
    ;;
esac

# ---- cascade: squash → tag → release → bump → cut next ----

# 1. squash patch branch into main.
if already_merged_into_main "$PATCH_BRANCH" 2>/dev/null && (( ! DRY_RUN )); then
  log "skip squash: ${PATCH_BRANCH} already an ancestor of ${MAIN_BRANCH}"
else
  run "git checkout ${MAIN_BRANCH}"
  (( SKIP_PUSH )) || run "git pull --ff-only origin ${MAIN_BRANCH}"
  run "git merge --squash ${PATCH_BRANCH}"
  run "git commit -m 'release: shepherd ${TAG_PATCH}'"
  (( SKIP_PUSH )) || run "git push origin ${MAIN_BRANCH}"
fi

# 2. tag immutable patch tag (skip if exists).
if (( SKIP_TAG )); then
  plan "skip tag (--skip=tag): ${TAG_PATCH}"
elif tag_exists "$TAG_PATCH" && (( ! DRY_RUN )); then
  log "skip tag: ${TAG_PATCH} already exists"
else
  run "git tag -a ${TAG_PATCH} -m 'shepherd ${TAG_PATCH}'"
  # `git push origin <name>` is ambiguous when a branch and tag share <name>
  # (we routinely have v5.0.1 as both branch and tag mid-cascade). Use the
  # explicit refs/tags/ refspec to disambiguate.
  (( SKIP_PUSH )) || run "git push origin refs/tags/${TAG_PATCH}"
fi

# 3. force-update mutable tags vX and vX.Y.
if (( SKIP_TAG )); then
  plan "skip mutable tags (--skip=tag): ${TAG_MINOR}, ${TAG_MAJOR}"
else
  run "git tag -f ${TAG_MINOR}"
  (( SKIP_PUSH )) || run "git push -f origin refs/tags/${TAG_MINOR}"
  run "git tag -f ${TAG_MAJOR}"
  (( SKIP_PUSH )) || run "git push -f origin refs/tags/${TAG_MAJOR}"
fi

# 4. gh release create with notes extracted from CHANGELOG.
if (( SKIP_GH )); then
  plan "skip gh release (--skip=gh): ${TAG_PATCH}"
else
  notes_file="$(shctx_artifacts_root)/tmp/release-notes-${TAG_PATCH}.md"
  if (( DRY_RUN )); then
    plan "extract release notes for ${TAG_PATCH} from ${CHANGELOG_PATH} → ${notes_file}"
    plan "gh release create ${TAG_PATCH} --notes-file=${notes_file}"
  else
    mkdir -p "$(dirname "$notes_file")"
    extract_release_notes "$TAG_PATCH" "$(shctx_repo_root)/$CHANGELOG_PATH" > "$notes_file"
    if [[ ! -s "$notes_file" ]]; then
      echo "shepherd ${TAG_PATCH}" > "$notes_file"
    fi
    if command -v gh >/dev/null 2>&1; then
      run "gh release create ${TAG_PATCH} --notes-file='${notes_file}' --title='shepherd ${TAG_PATCH}'"
    else
      log "gh missing; skipped gh release (notes at ${notes_file})"
    fi
  fi
fi

# 5. compute next version, cut new patch + dev.0, bump version files.
next_version "$VER_X" "$VER_Y" "$VER_Z"
NEXT_PATCH_VERSION="${NEXT_X}.${NEXT_Y}.${NEXT_Z}"
NEXT_PATCH_BRANCH="v${NEXT_PATCH_VERSION}"
NEXT_DEV_BRANCH="v${NEXT_PATCH_VERSION}-dev.0"

log "cascade: next patch ${NEXT_PATCH_VERSION}"
run "git checkout ${MAIN_BRANCH}"
run "git checkout -b ${NEXT_PATCH_BRANCH} ${MAIN_BRANCH}"
(( SKIP_PUSH )) || run "git push -u origin ${NEXT_PATCH_BRANCH}"
run "git checkout -b ${NEXT_DEV_BRANCH} ${NEXT_PATCH_BRANCH}"
(( SKIP_PUSH )) || run "git push -u origin ${NEXT_DEV_BRANCH}"

# 6. bump versions in workspace files.
if (( SKIP_BUMP )); then
  plan "skip version bump (--skip=bump)"
else
  log "bumping version files to ${NEXT_PATCH_VERSION}"
  for entry in "${VERSION_FILES[@]}"; do
    bump_file "$entry" "${NEXT_PATCH_VERSION}"
  done
  if (( ! DRY_RUN )); then
    # Stage just the files we touched.
    for entry in "${VERSION_FILES[@]}"; do
      path="${entry%%:*}"
      [[ -f "$(shctx_repo_root)/$path" ]] && run "git add '${path}'"
    done
    run "git commit -m 'chore: bump shepherd to v${NEXT_PATCH_VERSION} (next patch working branch)'"
    (( SKIP_PUSH )) || run "git push origin ${NEXT_DEV_BRANCH}"
  else
    plan "git add + commit version bumps"
    plan "git push origin ${NEXT_DEV_BRANCH}"
  fi
fi

log "release pipeline complete: ${TAG_PATCH} released; now on ${NEXT_DEV_BRANCH}"
