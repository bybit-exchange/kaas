#!/bin/bash
set -euo pipefail

# === Colour output ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { printf '%b[INFO]%b %s\n' "$GREEN" "$NC" "$*"; }
warn()  { printf '%b[WARN]%b %s\n' "$YELLOW" "$NC" "$*"; }
die()   { printf '%b[ERROR]%b %s\n' "$RED" "$NC" "$*" >&2; exit 1; }

# === Argument validation ===
TAG="${1:-}"
if [[ -z "$TAG" ]]; then
    echo "Usage: $0 <tag>"
    echo "Example: $0 v0.1.0"
    exit 1
fi

SEMVER_REGEX='^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$'
if [[ ! "$TAG" =~ $SEMVER_REGEX ]]; then
    die "tag format invalid: '$TAG'; expected semver like v0.1.0 or v1.0.0-rc.1"
fi

# === Locate repository root ===
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# === Environment checks ===
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    die "current directory is not a git repository"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    die "working tree has uncommitted changes; please commit or stash first"
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    die "current branch is '$CURRENT_BRANCH'; release script must run on main"
fi

git fetch origin --tags --quiet
if git rev-parse "$TAG" >/dev/null 2>&1; then
    die "tag '$TAG' already exists; use a different version number"
fi

info "Preparing release $TAG (from $CURRENT_BRANCH @ $(git rev-parse --short HEAD))"

# === Temporary worktree ===
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/kaas-release.XXXXXX")

cleanup() {
    cd "$ROOT_DIR"
    git worktree remove "$WORK_DIR" --force 2>/dev/null || rm -rf "$WORK_DIR"
}
trap cleanup EXIT

git worktree add --detach "$WORK_DIR" HEAD
cd "$WORK_DIR"

# === Create release branch ===
git checkout -B release

# === File cleanup ===
info "Cleaning up internal files..."

# Internal files/directories
git rm -rf --ignore-unmatch \
    CLAUDE.md \
    .claude/ \
    .codegraph/ \
    2>/dev/null || true

# docs/ allowlist: keep only files actually referenced from README
DOCS_KEEP="
docs/agent-quickstart.md
docs/assets/architecture.en.svg
docs/assets/architecture.zh.svg
docs/assets/distill-flow.en.svg
docs/assets/distill-flow.zh.svg
docs/assets/kaas-vs-rag.en.svg
docs/assets/kaas-vs-rag.zh.svg
"
git ls-files -- docs/ | while IFS= read -r f; do
    echo "$DOCS_KEEP" | grep -qxF "$f" || git rm -f --ignore-unmatch "$f" 2>/dev/null || true
done

info "File cleanup done"

# === Commit ===
if git diff --cached --quiet; then
    info "No file changes, skipping commit"
else
    git commit -m "release: ${TAG}

Remove internal docs and dev-only files."
    info "Commit done"
fi

# === Tag ===
git tag -a "$TAG" -m "Release $TAG"
info "tag $TAG created"

# === Push ===
info "Pushing release branch and tag to remote..."
git push origin release --force
git push origin "$TAG"

# === Done ===
cd "$ROOT_DIR"

echo ""
info "========================================="
info "Release complete!"
info "  Branch: release (pushed)"
info "  Tag:  $TAG (pushed)"
info "========================================="
