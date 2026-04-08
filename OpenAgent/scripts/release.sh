#!/usr/bin/env bash
# =============================================================
#  Somnia — 发版脚本
# =============================================================
#  用法:
#    bash scripts/release.sh 0.2.0              # 正式发布
#    bash scripts/release.sh 0.2.0 --dry        # 预览，不实际发布
#    bash scripts/release.sh 0.2.0 --skip-push  # 本地打 tag，不推送
#
#  流程:
#    1. 检查工作区干净
#    2. 更新 VERSION 文件
#    3. 同步版本号到 __init__.py / package.json
#    4. 更新 CHANGELOG.md
#    5. 提交 git + 打 tag
#    6. 构建 PyPI 包
#    7. 发布到 PyPI
#    8. 推送 tag 到 GitHub (触发 CI 自动发布 npm)
# =============================================================

set -euo pipefail
cd "$(dirname "$0")/.."

# ─── 参数解析 ─────────────────────────────────────────────────
if [ $# -lt 1 ]; then
  echo "用法: bash scripts/release.sh <version> [--dry|--skip-push]"
  echo "示例: bash scripts/release.sh 0.2.0"
  exit 1
fi

NEW_VERSION="$1"
DRY_RUN=false
SKIP_PUSH=false

for arg in "${@:2}"; do
  case "$arg" in
    --dry)        DRY_RUN=true ;;
    --skip-push)  SKIP_PUSH=true ;;
  esac
done

BOLD='\033[1m'
GREEN='\033[32m'
RED='\033[31m'
CYAN='\033[36m'
YELLOW='\033[33m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}${CYAN}🚀 Somnia Release${RESET}"
echo ""

# ─── 1. 检查工作区干净 ──────────────────────────────────────
if [ -n "$(git status --porcelain)" ]; then
  echo -e "${RED}✗ 工作区有未提交的更改，请先 commit 或 stash${RESET}"
  git status --short
  exit 1
fi
echo -e "${GREEN}✓${RESET} 工作区干净"

# ─── 2. 验证版本号格式 ──────────────────────────────────────
if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo -e "${RED}✗ 版本号格式错误: $NEW_VERSION (需要 semver 格式: x.y.z)${RESET}"
  exit 1
fi

CURRENT_VERSION=$(cat VERSION | tr -d '[:space:]')
echo -e "  当前版本: ${YELLOW}$CURRENT_VERSION${RESET}"
echo -e "  目标版本: ${GREEN}$NEW_VERSION${RESET}"
echo ""

if [ "$DRY_RUN" = true ]; then
  echo -e "${YELLOW}👀 DRY RUN — 不会实际修改任何内容${RESET}"
  echo ""
fi

# ─── 3. 更新 VERSION 文件 ────────────────────────────────────
if [ "$DRY_RUN" = false ]; then
  echo "$NEW_VERSION" > VERSION
  echo -e "${GREEN}✓${RESET} VERSION → $NEW_VERSION"
fi

# ─── 4. 同步版本号 ───────────────────────────────────────────
if [ "$DRY_RUN" = false ]; then
  bash scripts/sync-version.sh
fi

# ─── 5. 更新 CHANGELOG.md ────────────────────────────────────
TODAY=$(date +%Y-%m-%d)
CHANGELOG_ENTRY="## $NEW_VERSION ($TODAY)\n\n(请手动补充 changelog)\n"

if [ "$DRY_RUN" = false ]; then
  # 在文件开头的 "# Changelog" 后插入新版本
  sed -i.bak "s|# Changelog|# Changelog\n\n${CHANGELOG_ENTRY}|" CHANGELOG.md
  rm -f CHANGELOG.md.bak
  echo -e "${GREEN}✓${RESET} CHANGELOG.md 已添加 $NEW_VERSION 条目"
fi

# ─── 6. Git commit + tag ─────────────────────────────────────
if [ "$DRY_RUN" = false ]; then
  git add VERSION openagent/__init__.py npm/package.json CHANGELOG.md
  git commit -m "release: v$NEW_VERSION"
  git tag "v$NEW_VERSION"
  echo -e "${GREEN}✓${RESET} git commit + tag v$NEW_VERSION"
fi

# ─── 7. 构建 PyPI 包 ─────────────────────────────────────────
if [ "$DRY_RUN" = false ]; then
  rm -rf dist/
  python -m build
  echo -e "${GREEN}✓${RESET} 构建完成"
fi

# ─── 8. 发布到 PyPI ──────────────────────────────────────────
if [ "$DRY_RUN" = false ]; then
  echo ""
  echo -e "${CYAN}📦 发布到 PyPI ...${RESET}"
  twine upload dist/*
  echo -e "${GREEN}✓${RESET} PyPI 发布完成"
fi

# ─── 9. 推送到 GitHub ────────────────────────────────────────
if [ "$DRY_RUN" = false ] && [ "$SKIP_PUSH" = false ]; then
  echo ""
  echo -e "${CYAN}📤 推送到 GitHub ...${RESET}"
  git push origin main
  git push origin "v$NEW_VERSION"
  echo -e "${GREEN}✓${RESET} 推送完成 (CI 将自动发布 npm)"
fi

# ─── 完成 ─────────────────────────────────────────────────────
echo ""
if [ "$DRY_RUN" = true ]; then
  echo -e "${YELLOW}👀 DRY RUN 完成 — 以上为将要执行的操作${RESET}"
  echo "  去掉 --dry 参数即可实际执行"
else
  echo -e "${GREEN}${BOLD}✅ Somnia v$NEW_VERSION 发布成功！${RESET}"
  echo ""
  echo "  PyPI:  https://pypi.org/project/somnia/$NEW_VERSION/"
  echo "  安装:  pip install somnia"
  echo "  升级:  pip install --upgrade somnia"
  echo ""
  if [ "$SKIP_PUSH" = true ]; then
    echo "  ⚠️  未推送到远程，手动推送:"
    echo "    git push origin main"
    echo "    git push origin v$NEW_VERSION"
  fi
fi
