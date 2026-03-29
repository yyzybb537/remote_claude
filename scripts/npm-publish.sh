#!/bin/sh
# 发布 remote-claude 到 npm
# 用法：sh scripts/npm-publish.sh [patch|minor|major] [--token <npm-token>]
#       默认 patch（0.0.x）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# 解析参数
BUMP="patch"
TOKEN=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --token)
            TOKEN="$2"
            shift 2
            ;;
        patch|minor|major)
            BUMP="$1"
            shift
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# 写入 token（如果提供）
if [ -n "$TOKEN" ]; then
    npm config set //registry.npmjs.org/:_authToken "$TOKEN"
    echo "🔑 npm token 已写入 ~/.npmrc"
fi

# 检查 npm 登录状态
if ! npm whoami --registry=https://registry.npmjs.org/ >/dev/null 2>&1; then
    echo "❌ 未登录 npm，请通过 --token 传入 token："
    echo "   sh scripts/npm-publish.sh --token <npm-token>"
    exit 1
fi

# 检查 git 工作区干净（package.json 之外）
DIRTY=$(git status --porcelain | grep -v "^.M package.json" || true)
if [ -n "$DIRTY" ]; then
    echo "❌ 工作区有未提交的改动，请先 commit："
    echo "$DIRTY"
    exit 1
fi

# 获取旧版本
OLD_VERSION=$(node -e "console.log(require('./package.json').version)")

# bump 版本号（不创建 git tag）
npm version "$BUMP" --no-git-tag-version

NEW_VERSION=$(node -e "console.log(require('./package.json').version)")

echo "版本: $OLD_VERSION → $NEW_VERSION"

# 提交 package.json
git add package.json
git commit -m "chore: 发布 $NEW_VERSION"

# 发布到 npm
echo "📦 发布中..."
npm publish --registry=https://registry.npmjs.org/

echo "✅ remote-claude@$NEW_VERSION 发布成功"
