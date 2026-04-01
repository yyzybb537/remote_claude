#!/bin/sh
# 检查 .env 中 FEISHU_APP_ID/APP_SECRET 是否已配置，未配置则交互引导
# 用法: . scripts/check-env.sh
# POSIX sh 兼容，不使用 sed -i

REQUIRE_FEISHU="${REMOTE_CLAUDE_REQUIRE_FEISHU:-1}"
PROJECT_DIR="${PROJECT_DIR:-}"

is_valid_project_dir() {
    [ -n "$1" ] && [ -f "$1/scripts/_common.sh" ]
}

if [ "${1:+x}" = "x" ]; then
    echo "错误: check-env.sh 目录参数已废弃，请直接调用 sh scripts/check-env.sh（或 source 时不传目录参数）" >&2
    return 2 2>/dev/null || exit 2
fi

if is_valid_project_dir "${PROJECT_DIR:-}"; then
    PROJECT_DIR="$PROJECT_DIR"
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
. "$PROJECT_DIR/scripts/_common.sh"
unset LAZY_INIT_DISABLE_AUTO_RUN

rc_ensure_home_dir
if ! rc_require_file "$REMOTE_CLAUDE_ENV_TEMPLATE" "环境变量模板文件"; then
    if [ "$REQUIRE_FEISHU" = "0" ]; then
        echo ""
        echo "飞书客户端未配置，跳过飞书启动。"
        echo "如需启用飞书客户端，请先配置 $REMOTE_CLAUDE_ENV_FILE"
        echo ""
        return 0 2>/dev/null || exit 0
    fi
    return 1 2>/dev/null || exit 1
fi

ENV_OK=false

if [ "$REQUIRE_FEISHU" = "0" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ -f "$REMOTE_CLAUDE_ENV_FILE" ]; then
    APP_ID=$(grep -E '^FEISHU_APP_ID=' "$REMOTE_CLAUDE_ENV_FILE" | cut -d= -f2)
    APP_SECRET=$(grep -E '^FEISHU_APP_SECRET=' "$REMOTE_CLAUDE_ENV_FILE" | cut -d= -f2)
    if [ -n "$APP_ID" ] && [ "$APP_ID" != "cli_xxxxx" ] && \
       [ -n "$APP_SECRET" ] && [ "$APP_SECRET" != "xxxxx" ]; then
        ENV_OK=true
    fi
fi

if [ "$ENV_OK" = false ]; then
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
        return 1 2>/dev/null || exit 1
    fi

    rc_copy_if_missing "$REMOTE_CLAUDE_ENV_TEMPLATE" "$REMOTE_CLAUDE_ENV_FILE" "环境变量配置文件"

    # 使用临时文件替代 sed -i，跨平台兼容
    tmp_file=$(mktemp)
    sed "s/^FEISHU_APP_ID=.*/FEISHU_APP_ID=$INPUT_APP_ID/" "$REMOTE_CLAUDE_ENV_FILE" > "$tmp_file" && mv "$tmp_file" "$REMOTE_CLAUDE_ENV_FILE"

    tmp_file=$(mktemp)
    sed "s/^FEISHU_APP_SECRET=.*/FEISHU_APP_SECRET=$INPUT_APP_SECRET/" "$REMOTE_CLAUDE_ENV_FILE" > "$tmp_file" && mv "$tmp_file" "$REMOTE_CLAUDE_ENV_FILE"

    echo ""
    echo "配置已保存到 $REMOTE_CLAUDE_ENV_FILE"
    echo "（可选配置, 如白名单等可稍后编辑该文件）"
    echo ""
fi
