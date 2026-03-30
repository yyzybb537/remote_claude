#!/bin/sh
# 检查 .env 中 FEISHU_APP_ID/APP_SECRET 是否已配置，未配置则交互引导
# 用法: . scripts/check-env.sh [项目根目录或安装目录]
# POSIX sh 兼容，不使用 sed -i

PROJECT_DIR="${PROJECT_DIR:-}"

is_valid_project_dir() {
    [ -n "$1" ] && [ -f "$1/scripts/_common.sh" ]
}

if is_valid_project_dir "${PROJECT_DIR:-}"; then
    PROJECT_DIR="$PROJECT_DIR"
elif is_valid_project_dir "${1:-}"; then
    PROJECT_DIR="$1"
else
    SOURCE="$0"
    while [ -L "$SOURCE" ]; do
        BASE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
        SOURCE="$(readlink "$SOURCE")"
        case "$SOURCE" in /*) ;; *) SOURCE="$BASE_DIR/$SOURCE" ;; esac
    done
    SELF_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    PROJECT_DIR="$(cd "$SELF_DIR/.." && pwd)"
fi

LAZY_INIT_DISABLE_AUTO_RUN=1
export LAZY_INIT_DISABLE_AUTO_RUN
if [ -f "$PROJECT_DIR/scripts/_common.sh" ]; then
    . "$PROJECT_DIR/scripts/_common.sh"
fi
unset LAZY_INIT_DISABLE_AUTO_RUN

INSTALL_DIR="${1:-$PROJECT_DIR}"
ENV_FILE="$HOME/.remote-claude/.env"
mkdir -p "$HOME/.remote-claude"
ENV_OK=false
REQUIRE_FEISHU="${REMOTE_CLAUDE_REQUIRE_FEISHU:-1}"

if [ -f "$ENV_FILE" ]; then
    APP_ID=$(grep -E '^FEISHU_APP_ID=' "$ENV_FILE" | cut -d= -f2)
    APP_SECRET=$(grep -E '^FEISHU_APP_SECRET=' "$ENV_FILE" | cut -d= -f2)
    if [ -n "$APP_ID" ] && [ "$APP_ID" != "cli_xxxxx" ] && \
       [ -n "$APP_SECRET" ] && [ "$APP_SECRET" != "xxxxx" ]; then
        ENV_OK=true
    fi
fi

if [ "$ENV_OK" = false ]; then
    if [ "$REQUIRE_FEISHU" = "0" ]; then
        echo ""
        echo "飞书客户端未配置，跳过飞书启动。"
        echo "如需启用飞书客户端，请先配置 $ENV_FILE"
        echo ""
        return 0
    fi
    echo ""
    echo "飞书客户端尚未配置，需要填写应用凭证。"
    echo "（在飞书开发者后台创建应用获取: https://open.feishu.cn/app）"
    echo ""
    printf "\033[33m飞书机器人配置文档参考：https://github.com/yyzybb537/remote_claude\033[0m\n"
    echo ""
    printf "FEISHU_APP_ID: "
    read -r INPUT_APP_ID
    printf "FEISHU_APP_SECRET: "
    read -r INPUT_APP_SECRET

    if [ -z "$INPUT_APP_ID" ] || [ -z "$INPUT_APP_SECRET" ]; then
        echo "错误: APP_ID 和 APP_SECRET 不能为空"
        exit 1
    fi

    cp "$INSTALL_DIR/resources/defaults/.env.example" "$ENV_FILE"

    # 使用临时文件替代 sed -i，跨平台兼容
    tmp_file=$(mktemp)
    sed "s/^FEISHU_APP_ID=.*/FEISHU_APP_ID=$INPUT_APP_ID/" "$ENV_FILE" > "$tmp_file" && mv "$tmp_file" "$ENV_FILE"

    tmp_file=$(mktemp)
    sed "s/^FEISHU_APP_SECRET=.*/FEISHU_APP_SECRET=$INPUT_APP_SECRET/" "$ENV_FILE" > "$tmp_file" && mv "$tmp_file" "$ENV_FILE"

    echo ""
    echo "配置已保存到 $ENV_FILE"
    echo "（可选配置, 如白名单等可稍后编辑该文件）"
    echo ""
fi
