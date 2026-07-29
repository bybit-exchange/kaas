#!/bin/bash
set -euo pipefail

# === 颜色输出 ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { printf '%b[INFO]%b %s\n' "$GREEN" "$NC" "$*"; }
warn()  { printf '%b[WARN]%b %s\n' "$YELLOW" "$NC" "$*"; }
die()   { printf '%b[ERROR]%b %s\n' "$RED" "$NC" "$*" >&2; exit 1; }

# === 参数校验 ===
TAG="${1:-}"
if [[ -z "$TAG" ]]; then
    echo "用法: $0 <tag>"
    echo "示例: $0 v0.1.0"
    exit 1
fi

SEMVER_REGEX='^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$'
if [[ ! "$TAG" =~ $SEMVER_REGEX ]]; then
    die "tag 格式不合法: '$TAG'，需要 semver 格式如 v0.1.0 或 v1.0.0-rc.1"
fi

# === 定位仓库根目录 ===
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# === 环境检查 ===
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    die "当前目录不是 git 仓库"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    die "工作区有未提交的变更，请先 commit 或 stash"
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    die "当前分支为 '$CURRENT_BRANCH'，发布脚本只能在 main 分支运行"
fi

git fetch origin --tags --quiet
if git rev-parse "$TAG" >/dev/null 2>&1; then
    die "tag '$TAG' 已存在，请使用不同的版本号"
fi

info "准备发布 $TAG (基于 $CURRENT_BRANCH @ $(git rev-parse --short HEAD))"

# === 临时 worktree ===
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/kaas-release.XXXXXX")

cleanup() {
    cd "$ROOT_DIR"
    git worktree remove "$WORK_DIR" --force 2>/dev/null || rm -rf "$WORK_DIR"
}
trap cleanup EXIT

git worktree add --detach "$WORK_DIR" HEAD
cd "$WORK_DIR"

# === 创建 release 分支 ===
git checkout -B release

# === 文件清理 ===
info "清理内部文件..."

# 内部文件/目录
git rm -rf --ignore-unmatch \
    CLAUDE.md \
    .claude/ \
    .codegraph/ \
    2>/dev/null || true

# docs/ 白名单保留（仅 README 实际引用的文件）
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

info "文件清理完成"

# === 提交 ===
if git diff --cached --quiet; then
    info "无文件变更，跳过提交"
else
    git commit -m "release: ${TAG}

Remove internal docs and dev-only files."
    info "提交完成"
fi

# === 打 tag ===
git tag -a "$TAG" -m "Release $TAG"
info "tag $TAG 已创建"

# === 推送 ===
info "推送 release 分支和 tag 到远端..."
git push origin release --force
git push origin "$TAG"

# === 完成 ===
cd "$ROOT_DIR"

echo ""
info "========================================="
info "发布完成!"
info "  分支: release (已推送)"
info "  Tag:  $TAG (已推送)"
info "========================================="
