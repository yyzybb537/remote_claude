#!/bin/sh
# remote-claude shell 自动补全（支持 bash 和 zsh）

SOURCE=""
if [ -n "${BASH_SOURCE:-}" ]; then
    SOURCE="$BASH_SOURCE"
elif [ -n "${ZSH_VERSION:-}" ]; then
    SOURCE="$(eval 'printf %s "${(%):-%N}"')"
else
    SOURCE="$0"
fi
while [ -L "$SOURCE" ]; do
    BASE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$BASE_DIR/$SOURCE" ;; esac
done
SELF_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PROJECT_DIR="$(cd "$SELF_DIR/.." && pwd)"
LAZY_INIT_DISABLE_AUTO_RUN=1
export LAZY_INIT_DISABLE_AUTO_RUN
. "$PROJECT_DIR/scripts/_common.sh"
unset LAZY_INIT_DISABLE_AUTO_RUN

_remote_claude_get_sessions() {
    remote-claude list 2>/dev/null | awk 'NR>3 && NF>0 && !/^-/ && !/^共/ {print $1}'
}

if [ -n "${ZSH_VERSION:-}" ]; then
    # zsh 原生补全（通过 eval 延迟解析，避免 sh 解析 zsh 专有语法）
    eval '
    # compdef 依赖 compinit 初始化过的 _comps 数组，未初始化时先调用
    if ! (( ${+_comps} )); then
        autoload -Uz compinit && compinit -u 2>/dev/null
    fi

    _remote_claude_zsh() {
        local -a commands lark_cmds sessions
        commands=(
            "start:启动新会话"
            "attach:连接到已有会话"
            "list:列出所有会话"
            "kill:终止会话"
            "status:显示会话状态"
            "lark:飞书客户端管理"
            "stats:查看使用统计"
            "log:查看会话日志"
            "update:更新到最新版本"
        )
        lark_cmds=(
            "start:启动飞书客户端"
            "stop:停止飞书客户端"
            "restart:重启飞书客户端"
            "status:查看飞书客户端状态"
        )

        case $words[2] in
            attach|kill|status|log)
                sessions=( ${(f)"$(_remote_claude_get_sessions)"} )
                _describe "会话名称" sessions
                ;;
            lark)
                _describe "lark 子命令" lark_cmds
                ;;
            *)
                if [ "$CURRENT" -eq 2 ]; then
                    _describe "子命令" commands
                fi
                ;;
        esac
    }
    compdef _remote_claude_zsh remote-claude
    '
elif [ -n "${BASH_VERSION:-}" ]; then
    # bash 补全
    _remote_claude_bash() {
        _rc_bash_cur=
        _rc_bash_commands=
        _rc_bash_lark_cmds=
        _rc_bash_sessions=

        _rc_bash_cur="${COMP_WORDS[COMP_CWORD]}"
        _rc_bash_commands="start attach list kill status lark stats log update"
        _rc_bash_lark_cmds="start stop restart status"

        if [ "$COMP_CWORD" -eq 1 ]; then
            COMPREPLY=( $(compgen -W "$_rc_bash_commands" -- "$_rc_bash_cur") )
            unset _rc_bash_cur _rc_bash_commands _rc_bash_lark_cmds _rc_bash_sessions
            return
        fi

        case "${COMP_WORDS[1]}" in
            attach|kill|status|log)
                _rc_bash_sessions=$(_remote_claude_get_sessions)
                COMPREPLY=( $(compgen -W "$_rc_bash_sessions" -- "$_rc_bash_cur") )
                ;;
            lark)
                if [ "$COMP_CWORD" -eq 2 ]; then
                    COMPREPLY=( $(compgen -W "$_rc_bash_lark_cmds" -- "$_rc_bash_cur") )
                fi
                ;;
        esac

        unset _rc_bash_cur _rc_bash_commands _rc_bash_lark_cmds _rc_bash_sessions
    }
    complete -F _remote_claude_bash remote-claude
fi
