#!/bin/sh
# uninstall.sh - npm/pnpm preuninstall 钩子
# 完全清理符号链接、shell 配置、配置文件、虚拟环境和运行时文件

set -e

SOURCE="$0"
while [ -L "$SOURCE" ]; do
    BASE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$BASE_DIR/$SOURCE" ;; esac
done
SELF_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PROJECT_DIR="$(cd "$SELF_DIR/.." && pwd)"

# 引入共享脚本（提供颜色定义、打印函数）
LAZY_INIT_DISABLE_AUTO_RUN=1
export LAZY_INIT_DISABLE_AUTO_RUN
. "$PROJECT_DIR/scripts/_common.sh"
unset LAZY_INIT_DISABLE_AUTO_RUN

# 检测是否在 npm/pnpm 的 uninstall hook 上下文中
# 判定条件：
# 1) npm 生命周期事件包含 uninstall
# 2) pnpm 全局 remove/rm/uninstall（部分场景不会注入 npm_lifecycle_event）
# 返回: 0 在 uninstall hook 上下文, 1 不在
_is_npm_context() {
    case "$npm_lifecycle_event" in
        *uninstall*)
            return 0
            ;;
    esac

    case "${npm_config_user_agent:-}" in
        pnpm/*)
            case "${npm_command:-}" in
                remove|rm|uninstall)
                    case "${npm_config_global:-}" in
                        true|1)
                            return 0
                            ;;
                    esac
                    ;;
            esac
            ;;
    esac

    return 1
}

# 1. 清理符号链接
cleanup_symlinks() {
    print_info "清理快捷命令符号链接..."

    found=0
    # 扩展的 bin 目录列表（覆盖常见安装路径）
    for dir in /usr/local/bin /usr/bin "$HOME/bin" "$HOME/.local/bin" \
               /opt/homebrew/bin /usr/local/Cellar/node/*/bin \
               "$HOME/.nvm/*/bin" "$HOME/.config/nvm/*/bin"; do
        # 如果目录存在（处理通配符）
        for bindir in $dir; do
            [ -d "$bindir" ] || continue
            for cmd in cla cl cx cdx remote-claude; do
                link_path="$bindir/$cmd"
                if [ -L "$link_path" ]; then
                    target=$(readlink "$link_path" 2>/dev/null || true)
                    # 只删除指向本项目的链接
                    case "$target" in
                        *"remote_claude"*|*"remote-claude"*)
                            rm -f "$link_path"
                            print_detail "已删除: $link_path"
                            found=$((found + 1))
                            ;;
                    esac
                fi
            done
        done
    done

    if [ $found -eq 0 ]; then
        print_detail "没有找到需要清理的符号链接"
    else
        print_success "已清理 $found 个符号链接"
    fi
}

# 2. 清理 shell 配置
cleanup_shell_config() {
    print_info "清理 shell 配置..."

    cleaned=0
    rc=
    tmp_file=
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.profile"; do
        [ -f "$rc" ] || continue

        tmp_file=$(mktemp)
        awk -v begin='# >>> remote-claude init >>>' -v end='# <<< remote-claude init <<<' '
            $0==begin {in_block=1; next}
            $0==end {in_block=0; next}
            !in_block {print}
        ' "$rc" > "$tmp_file" && mv "$tmp_file" "$rc"

        if ! grep -qF '# >>> remote-claude init >>>' "$rc" 2>/dev/null; then
            cleaned=$((cleaned + 1))
            print_detail "已清理: $rc"
        fi
    done

    if [ $cleaned -eq 0 ]; then
        print_detail "没有找到需要清理的 shell 配置"
    else
        print_success "已清理 $cleaned 个 shell 配置文件"
    fi
}

# 3. 清理虚拟环境
cleanup_virtual_env() {
    print_info "清理虚拟环境..."

    # 检查安装目录中的 .venv
    if [ -d "$PROJECT_DIR/.venv" ]; then
        rm -rf "$PROJECT_DIR/.venv"
        print_success "已删除虚拟环境: $PROJECT_DIR/.venv"
    else
        print_detail "安装目录中没有虚拟环境"
    fi

    # 检查其他可能的 venv 位置
    for venv_path in "$HOME/.remote-claude/.venv" "$HOME/.local/share/remote-claude/.venv"; do
        if [ -d "$venv_path" ]; then
            rm -rf "$venv_path"
            print_detail "已删除: $venv_path"
        fi
    done
}

# 4. 清理运行时文件和目录
cleanup_runtime_files() {
    print_info "清理运行时文件..."

    cleaned=0

    # 停止 lark 客户端
    if [ -f "$REMOTE_CLAUDE_LARK_PID_FILE" ]; then
        pid=$(cat "$REMOTE_CLAUDE_LARK_PID_FILE" 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            print_detail "停止飞书客户端 (PID: $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            # 强制终止如果还在运行
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$REMOTE_CLAUDE_LARK_PID_FILE"
        cleaned=$((cleaned + 1))
    fi

    # 删除运行时目录中的当前规范文件
    if [ -d "$REMOTE_CLAUDE_SOCKET_DIR" ]; then
        for pattern in "*.pid" "*.status" "*.sock" "*.mq"; do
            for file in "$REMOTE_CLAUDE_SOCKET_DIR"/$pattern; do
                [ -e "$file" ] || continue
                rm -f "$file"
                print_detail "已删除: $file"
                cleaned=$((cleaned + 1))
            done
        done

        rmdir "$REMOTE_CLAUDE_SOCKET_DIR" 2>/dev/null || true
    fi

    # 删除用户目录中的当前仍有效运行时文件
    for file in "$REMOTE_CLAUDE_LARK_LOG_FILE"; do
        [ -f "$file" ] || continue
        rm -f "$file"
        print_detail "已删除: $file"
        cleaned=$((cleaned + 1))
    done

    if [ $cleaned -eq 0 ]; then
        print_detail "没有找到需要清理的运行时文件"
    else
        print_success "已清理运行时文件"
    fi
}

# 5. 清理 uv 路径记录
cleanup_uv_path() {
    print_info "清理 uv 路径记录..."

    if [ -f "$REMOTE_CLAUDE_STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
        if jq -e '.uv_path' "$REMOTE_CLAUDE_STATE_FILE" >/dev/null 2>&1; then
            tmp_file=$(mktemp)
            jq 'del(.uv_path)' "$REMOTE_CLAUDE_STATE_FILE" > "$tmp_file" && mv "$tmp_file" "$REMOTE_CLAUDE_STATE_FILE"
            print_success "已清除 uv 路径记录"
        fi
    fi
}

# 6. 清理 uv 缓存（可选）
cleanup_uv_cache() {
    print_info "检查 uv 缓存..."

    # npm 环境或 CI 环境跳过交互式询问
    if _is_npm_context || [ -n "$CI" ]; then
        print_detail "npm/CI 环境跳过 uv 缓存清理（保留用户工具）"
        return
    fi

    if ! command -v uv >/dev/null 2>&1; then
        print_detail "未找到 uv，跳过缓存清理"
        return
    fi

    cache_size=
    cache_size=$(uv cache dir 2>/dev/null | head -1)
    if [ -z "$cache_size" ]; then
        print_detail "无法获取缓存信息"
        return
    fi

    printf "${YELLOW}是否清理 uv 缓存？${NC} [y/N]: "
    read -r reply
    case "$reply" in
        [yY][eE][sS]|[yY])
            if uv cache clean 2>/dev/null; then
                print_success "已清理 uv 缓存"
            else
                print_warning "缓存清理失败"
            fi
            ;;
        *)
            print_info "保留 uv 缓存"
            ;;
    esac
}

# 7. 询问删除配置文件和数据
cleanup_config_files() {
    print_info "检查配置文件..."

    if [ ! -d "$REMOTE_CLAUDE_HOME_DIR" ]; then
        print_detail "配置目录不存在，跳过"
        return
    fi

    # npm/pnpm hook 环境：静默完全删除
    if _is_npm_context; then
        rm -rf "$REMOTE_CLAUDE_HOME_DIR"
        print_success "已删除配置目录: $REMOTE_CLAUDE_HOME_DIR"
        return
    fi

    all_files=""
    for file in "$REMOTE_CLAUDE_SETTINGS_FILE" "$REMOTE_CLAUDE_STATE_FILE" "$REMOTE_CLAUDE_ENV_FILE"; do
        [ -f "$file" ] && all_files="$all_files ${file##*/}"
    done

    if [ -z "$all_files" ]; then
        printf "${YELLOW}是否删除空配置目录 $REMOTE_CLAUDE_HOME_DIR？${NC} [y/N]: "
        read -r reply
        case "$reply" in
            [yY][eE][sS]|[yY])
                rmdir "$REMOTE_CLAUDE_HOME_DIR" 2>/dev/null && print_success "已删除: $REMOTE_CLAUDE_HOME_DIR"
                ;;
        esac
        return
    fi

    printf "${YELLOW}是否删除配置文件和数据？${NC}\n"
    print_detail "将删除:$all_files"
    printf "${YELLOW}输入 y 删除，n 保留 [y/N]: ${NC}"
    read -r reply

    case "$reply" in
        [yY][eE][sS]|[yY])
            for file in "$REMOTE_CLAUDE_SETTINGS_FILE" "$REMOTE_CLAUDE_STATE_FILE" "$REMOTE_CLAUDE_ENV_FILE"; do
                if [ -f "$file" ]; then
                    rm -f "$file"
                    print_detail "已删除: $file"
                fi
            done
            if rmdir "$REMOTE_CLAUDE_HOME_DIR" 2>/dev/null; then
                print_success "已删除配置目录: $REMOTE_CLAUDE_HOME_DIR"
            else
                print_success "已删除配置文件"
            fi
            ;;
        *)
            print_info "保留配置文件"
            ;;
    esac
}

# 8. 显示卸载后信息
show_post_uninstall_info() {
    printf "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    printf "${GREEN}   Remote Claude 卸载清理完成${NC}\n"
    printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n\n"

    print_info "已清理项目:"
    print_detail "- 快捷命令符号链接 (cla, cl, cx, cdx, remote-claude)"
    print_detail "- Shell 配置文件中的 PATH 和 source 设置"
    print_detail "- Python 虚拟环境 (.venv)"
    print_detail "- 运行时文件 (PID, socket, 日志)"

    printf "\n${YELLOW}提示：${NC}\n"
    print_detail "1. 重新打开终端使 PATH 更改生效"
    print_detail "2. 如需完全清理，请手动检查 ~/.bashrc 和 ~/.zshrc"
    print_detail "3. 活跃的会话可通过 'remote-claude kill <session>' 清理"

    # 检查是否还有残留的进程
    if pgrep -f "remote_claude.py" >/dev/null 2>&1 || \
       pgrep -f "lark_client/main.py" >/dev/null 2>&1; then
        printf "\n${YELLOW}警告：检测到残留的 Remote Claude 进程${NC}\n"
        print_detail "建议运行: pkill -f 'remote_claude|lark_client'"
    fi

    printf "\n"
}

# 主流程
main() {
    # 非交互模式（CI环境）自动确认
    if [ -n "$CI" ] || [ -n "$npm_config_loglevel" ]; then
        export AUTO_CONFIRM=1
    fi

    cleanup_symlinks
    cleanup_shell_config
    cleanup_virtual_env
    cleanup_runtime_files
    cleanup_uv_path
    cleanup_uv_cache
    cleanup_config_files
    show_post_uninstall_info
}

main
