#!/bin/sh
# _help.sh - 帮助输出模块
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

# 打印主命令概览
_print_main_help() {
    cat <<'EOF'
Remote Claude - 双端共享 Claude CLI 工具

命令概览：
  命令             说明                     示例
  ───────────────────────────────────────────────────────────────
  start            启动新会话               remote-claude start mywork
  attach           连接到会话               remote-claude attach mywork
  list             列出所有会话             remote-claude list
  kill             终止会话                 remote-claude kill mywork
  status           显示会话状态             remote-claude status mywork
  log              查看会话日志             remote-claude log mywork
  lark             飞书客户端管理           remote-claude lark start
  config           配置管理                 remote-claude config show
  connection       远程连接配置管理         remote-claude connection list
  token            显示会话 token           remote-claude token mywork
  regenerate-token 重新生成 token           remote-claude regenerate-token mywork
  stats            查看使用统计             remote-claude stats
  update           更新到最新版本           remote-claude update
  connect          连接到远程会话           remote-claude connect <host>
  remote           远程控制                 remote-claude remote list

选项：
  --remote    远程连接模式
  --host      远程服务器地址
  --port      远程服务器端口
  --token     认证令牌

更多信息请运行: remote-claude <command> --help
EOF
}
