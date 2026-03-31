#!/bin/sh
# _help.sh - 快捷命令帮助输出
# 用法: . "$PROJECT_DIR/scripts/_help.sh"

# 打印快捷命令概览表格
_print_quick_help() {
    printf '\n'
    printf '%b\n' "${GREEN}Remote Claude 快捷命令${NC}"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '%b\n' "命令   CLI      权限模式          用途"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '%b\n' "cla    Claude   正常（需确认）    启动 Claude 会话"
    printf '%b\n' "cl     Claude   跳过权限确认      快速启动 Claude 会话"
    printf '%b\n' "cx     Codex    跳过权限确认      快速启动 Codex 会话"
    printf '%b\n' "cdx    Codex    正常（需确认）    启动 Codex 会话"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '\n'
    printf '%b\n' "会话命名：当前目录路径 + 时间戳"
    printf '%b\n' "示例：/Users/foo/project_0331_142500"
    printf '\n'
    printf '%b\n' "更多信息: ${BLUE}remote-claude --help${NC}"
    printf '\n'
}
