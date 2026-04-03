#!/bin/sh
# setup.sh - 项目初始化脚本（POSIX sh 兼容，支持 sh/bash/zsh）

SOURCE="$0"
while [ -L "$SOURCE" ]; do
    BASE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$BASE_DIR/$SOURCE" ;; esac
done
SELF_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PROJECT_DIR="$(cd "$SELF_DIR/.." && pwd)"

# 引入共享脚本（提供颜色定义、打印函数、uv 管理函数）
# 使用 . 而非 source，兼容 POSIX sh
LAZY_INIT_DISABLE_AUTO_RUN=1
export LAZY_INIT_DISABLE_AUTO_RUN
. "$PROJECT_DIR/scripts/_common.sh"
if [ -f "$PROJECT_DIR/scripts/_help.sh" ]; then
    . "$PROJECT_DIR/scripts/_help.sh"
fi
unset LAZY_INIT_DISABLE_AUTO_RUN

# 末尾汇总警告（使用简单变量，POSIX sh 不支持数组）
WARNINGS_COUNT=0
add_warning() {
    WARNINGS_COUNT=$((WARNINGS_COUNT + 1))
    eval "WARNING_${WARNINGS_COUNT}=\"\$1\""
}
print_warnings() {
    if [ "$WARNINGS_COUNT" -gt 0 ]; then
        printf '%b\n' "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        printf '%b\n' "${YELLOW}⚠ 注意事项${NC}"
        printf '%b\n' "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        i=1
        while [ "$i" -le "$WARNINGS_COUNT" ]; do
            eval "w=\"\$WARNING_$i\""
            printf '%b\n' "${YELLOW}⚠${NC} $w"
            i=$((i + 1))
        done
        printf '\n'
    fi
}

# 构建完整 shell 初始化块（PATH + 自动补全）
_build_shell_init_block() {
    printf '%s' "export PATH=\"\$HOME/.local/bin:\$PATH\"; . \"$PROJECT_DIR/scripts/completion.sh\""
}

# 确保 shell 初始化块始终写入完整数据
_ensure_full_shell_init_block() {
    upsert_remote_claude_init_block "$(_build_shell_init_block)"
}

# 确保 ~/.local/bin 在 PATH 中
setup_path() {
    _ensure_full_shell_init_block
    export PATH="$HOME/.local/bin:$PATH"
}

# 检查操作系统
check_os() {
    print_header "检查系统环境"
    require_supported_os
}

# 检查 uv（使用 _common.sh 中的函数）
check_uv() {
    ensure_uv_or_hint "检查 uv"
    _ensure_full_shell_init_block
    print_success "已确保 \$HOME/.local/bin 写入 shell 初始化配置"
}

# 检查并安装 tmux（要求 3.6+）
check_tmux() {
    print_header "检查 tmux"

    # CI 模式：跳过 tmux 版本检查（Docker 环境可能没有 sudo）
    if [ "$CI_MODE" = "true" ]; then
        if command -v tmux >/dev/null 2>&1; then
            TMUX_VERSION=$(tmux -V)
            print_success "$TMUX_VERSION 已安装（CI 模式跳过版本检查）"
            return
        else
            print_error "未找到 tmux"
            add_warning "tmux 未安装，CI 模式跳过版本检查"
            return
        fi
    fi

    REQUIRED_MAJOR=3
    REQUIRED_MINOR=6

    install_tmux() {
        if [ "$OS" = "Darwin" ]; then
            if ! command -v brew >/dev/null 2>&1; then
                print_warning "未找到 Homebrew，正在自动安装..."
                sh -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                # 将 Homebrew 加入 PATH（Apple Silicon / Intel 路径不同）
                if [ -x "/opt/homebrew/bin/brew" ]; then
                    eval "$(/opt/homebrew/bin/brew shellenv)"
                elif [ -x "/usr/local/bin/brew" ]; then
                    eval "$(/usr/local/bin/brew shellenv)"
                fi
                if ! command -v brew >/dev/null 2>&1; then
                    print_error "Homebrew 安装失败，请手动安装后重试: https://brew.sh"
                    return 1
                fi
                print_success "Homebrew 安装成功"
            fi
            brew install tmux 2>/dev/null || true
        elif [ "$OS" = "Linux" ]; then
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update && sudo apt-get install -y tmux || true
            elif command -v yum >/dev/null 2>&1; then
                sudo yum install -y tmux || true
            elif command -v pacman >/dev/null 2>&1; then
                sudo pacman -Sy --noconfirm tmux || true
            elif command -v apk >/dev/null 2>&1; then
                sudo apk add --no-cache tmux || true
            elif command -v zypper >/dev/null 2>&1; then
                sudo zypper install -y tmux || true
            else
                print_warning "无法识别包管理器，尝试从源码编译 tmux..."
                install_tmux_from_source
                return
            fi
        fi
        print_success "tmux 安装成功"
    }

    install_tmux_from_source() {
        TMUX_VERSION_TAG="3.6a"
        TMUX_URL="https://github.com/tmux/tmux/releases/download/${TMUX_VERSION_TAG}/tmux-${TMUX_VERSION_TAG}.tar.gz"

        print_warning "包管理器版本不满足要求，尝试从源码编译 tmux ${TMUX_VERSION_TAG}..."

        # 安装编译依赖
        if [ "$OS" = "Darwin" ]; then
            brew install libevent ncurses pkg-config bison 2>/dev/null || true
        elif command -v apt-get >/dev/null 2>&1; then
            sudo apt-get install -y build-essential libevent-dev libncurses5-dev libncursesw5-dev bison pkg-config || true
        elif command -v yum >/dev/null 2>&1; then
            sudo yum groupinstall -y "Development Tools" || true
            sudo yum install -y libevent-devel ncurses-devel bison || true
        fi

        # 确定安装前缀
        PREFIX="/usr/local"
        if ! sudo -n true 2>/dev/null; then
            print_warning "无 sudo 权限，将安装到 \$HOME/.local"
            PREFIX="$HOME/.local"
        fi

        # 创建临时目录，编译完成后清理
        TMPDIR=$(mktemp -d)
        cleanup_tmpdir() {
            rm -rf "$TMPDIR"
        }
        trap 'cleanup_tmpdir' 0

        print_warning "下载 tmux-${TMUX_VERSION_TAG}.tar.gz..."
        if ! curl -fsSL "$TMUX_URL" -o "$TMPDIR/tmux.tar.gz"; then
            print_warning "下载失败，请检查网络或手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
            add_warning "tmux 源码下载失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
            return
        fi

        tar -xzf "$TMPDIR/tmux.tar.gz" -C "$TMPDIR"
        SRC_DIR=$(find "$TMPDIR" -maxdepth 1 -type d -name "tmux-*" | head -1)

        print_warning "编译 tmux（可能需要几分钟）..."
        NPROC=$(nproc 2>/dev/null || echo 2)
        if ! (cd "$SRC_DIR" && ./configure --prefix="$PREFIX" && make -j"$NPROC"); then
            print_warning "编译失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
            add_warning "tmux 源码编译失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
            return
        fi

        if [ "$PREFIX" = "/usr/local" ]; then
            if ! sudo make -C "$SRC_DIR" install; then
                add_warning "tmux make install 失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
                return
            fi
        else
            if ! make -C "$SRC_DIR" install; then
                add_warning "tmux make install 失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
                return
            fi
            # 若 $HOME/.local/bin 不在 PATH 中，自动写入 shell 配置
            case ":$PATH:" in
                *":$HOME/.local/bin:"*) ;;
                *)
                    export PATH="$HOME/.local/bin:$PATH"
                    _ensure_full_shell_init_block
                    print_success "已自动将 \$HOME/.local/bin 加入 PATH 并写入 shell 初始化配置"
                    ;;
            esac
        fi

        print_success "tmux ${TMUX_VERSION_TAG} 源码编译安装完成（前缀：${PREFIX}）"
    }

    check_version() {
        # tmux -V 输出格式：tmux 3.6 或 tmux 3.4a
        ver_str=$(tmux -V | awk '{print $2}')
        major=$(echo "$ver_str" | cut -d. -f1)
        minor=$(echo "$ver_str" | cut -d. -f2 | tr -dc '0-9')
        [ -z "$minor" ] && minor=0
        if [ "$major" -gt "$REQUIRED_MAJOR" ]; then
            return 0
        fi
        if [ "$major" -eq "$REQUIRED_MAJOR" ] && [ "$minor" -ge "$REQUIRED_MINOR" ]; then
            return 0
        fi
        return 1
    }

    if command -v tmux >/dev/null 2>&1; then
        TMUX_VERSION=$(tmux -V)
        if check_version; then
            print_success "$TMUX_VERSION 已安装（满足 >= ${REQUIRED_MAJOR}.${REQUIRED_MINOR}）"
            return
        else
            print_warning "$TMUX_VERSION 版本过低，需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR} 或更高，正在升级..."
            install_tmux
            # 升级后再次验证，版本仍不满足则走源码编译（跨平台）
            if ! check_version; then
                install_tmux_from_source
                if check_version; then
                    print_success "tmux 已升级至 $(tmux -V)"
                else
                    print_warning "源码编译后版本仍不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
                    add_warning "tmux 版本不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+，请手动升级"
                fi
            else
                print_success "tmux 已升级至 $(tmux -V)"
            fi
        fi
    else
        print_warning "未找到 tmux，正在安装..."
        install_tmux
        if ! check_version; then
            install_tmux_from_source
            if ! check_version; then
                print_warning "源码编译后版本仍不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
                add_warning "tmux 版本不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+，请手动升级"
            fi
        fi
    fi
}

# 检查 CLI 工具（Claude 或 Codex，至少需要一个）
check_cli_tools() {
    print_header "检查 CLI 工具"

    has_claude=false
    has_codex=false

    if command -v claude >/dev/null 2>&1; then
        has_claude=true
        print_success "Claude CLI 已安装"
    fi

    if command -v codex >/dev/null 2>&1; then
        has_codex=true
        print_success "Codex CLI 已安装"
    fi

    if $has_claude || $has_codex; then
        return
    fi

    print_warning "未找到 Claude CLI 或 Codex CLI"
    print_info "请至少安装以下其中一个："
    print_info "  Claude CLI: https://claude.ai/code"
    print_info "  Codex CLI:  npm install -g @openai/codex"

    if $NPM_MODE; then
        print_info "（npm 模式：跳过交互，请安装后重新运行）"
        return
    fi

    printf "%b" "${YELLOW}是否已安装 CLI 工具？${NC} [y/N]: "
    read -r REPLY
    echo
    case "$REPLY" in
        [Yy]*) ;;
        *)
            print_error "请先安装 Claude CLI 或 Codex CLI 后再运行此脚本"
            return 1
            ;;
    esac

    if ! command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
        print_error "仍未找到 claude 或 codex 命令，请检查安装或 PATH 配置"
        return 1
    fi
}

# 安装 Python 依赖
install_dependencies() {
    print_header "安装 Python 依赖"

    cd "$PROJECT_DIR"

    if [ ! -f "pyproject.toml" ]; then
        print_error "未找到 pyproject.toml 文件"
        return 1
    fi

    print_info "按官方 → 阿里 → 清华顺序尝试同步依赖..."
    _run_uv_with_pypi_sources "uv-sync" sync || {
        print_error "依赖安装失败"
        return 1
    }

    print_success "依赖安装完成"

    # 上报 init_install 事件（后台执行，不阻塞，失败静默）
    # 使用项目虚拟环境中的 Python，避免再次进入 uv 入口
    _run_project_python scripts/report_install.py >/dev/null 2>&1 &
}

# 配置飞书环境
configure_lark() {
    print_header "配置飞书客户端"

    rc_ensure_home_dir

    # 迁移旧 .env（项目根目录）到新位置
    if [ -f ".env" ] && [ ! -f "$REMOTE_CLAUDE_ENV_FILE" ]; then
        mv ".env" "$REMOTE_CLAUDE_ENV_FILE"
        print_success "已将 .env 迁移到 $REMOTE_CLAUDE_ENV_FILE"
    fi

    if [ -f "$REMOTE_CLAUDE_ENV_FILE" ]; then
        print_warning ".env 文件已存在（$REMOTE_CLAUDE_ENV_FILE），跳过配置"
        return
    fi

    if ! rc_require_file "$REMOTE_CLAUDE_ENV_TEMPLATE" ".env.example 模板文件"; then
        return 1
    fi

    printf "%b" "${YELLOW}是否需要配置飞书客户端？${NC} [y/N]: "
    read -r REPLY
    echo

    case "$REPLY" in
        [Yy]*)
            rc_copy_if_missing "$REMOTE_CLAUDE_ENV_TEMPLATE" "$REMOTE_CLAUDE_ENV_FILE" ".env 文件"
            print_warning "请编辑 $REMOTE_CLAUDE_ENV_FILE，填写以下信息："
            print_info "  - FEISHU_APP_ID: 飞书应用的 App ID"
            print_info "  - FEISHU_APP_SECRET: 飞书应用的 App Secret"
            print_info ""
            print_info "获取方式: 登录飞书开放平台 -> 创建应用 -> 凭证与基础信息"
            ;;
        *)
            print_info "跳过飞书配置（可稍后手动配置）"
            ;;
    esac
}

# 创建必要目录
create_directories() {
    print_header "创建运行目录"

    if [ ! -d "$REMOTE_CLAUDE_SOCKET_DIR" ]; then
        rc_ensure_socket_dir
        print_success "创建目录: $REMOTE_CLAUDE_SOCKET_DIR"
    else
        print_info "目录已存在: $REMOTE_CLAUDE_SOCKET_DIR"
    fi

    if [ ! -d "$REMOTE_CLAUDE_HOME_DIR" ]; then
        rc_ensure_home_dir
        print_success "创建目录: $REMOTE_CLAUDE_HOME_DIR"
    else
        print_info "目录已存在: $REMOTE_CLAUDE_HOME_DIR"
    fi
}

# 初始化配置文件
init_config_files() {
    print_header "初始化配置文件"

    if ! rc_require_file "$REMOTE_CLAUDE_SETTINGS_TEMPLATE" "配置模板"; then
        return 1
    fi

    if ! rc_require_file "$REMOTE_CLAUDE_STATE_TEMPLATE" "运行时模板"; then
        return 1
    fi

    rc_copy_if_missing "$REMOTE_CLAUDE_SETTINGS_TEMPLATE" "$REMOTE_CLAUDE_SETTINGS_FILE" "默认配置"
    if [ -f "$REMOTE_CLAUDE_SETTINGS_FILE" ] && [ ! -s "$REMOTE_CLAUDE_SETTINGS_FILE" ]; then
        print_info "配置文件已存在: $REMOTE_CLAUDE_SETTINGS_FILE"
    elif [ -f "$REMOTE_CLAUDE_SETTINGS_FILE" ] && [ "$(wc -c < "$REMOTE_CLAUDE_SETTINGS_FILE" 2>/dev/null)" -gt 0 ]; then
        if ! cmp -s "$REMOTE_CLAUDE_SETTINGS_TEMPLATE" "$REMOTE_CLAUDE_SETTINGS_FILE" 2>/dev/null; then
            print_info "配置文件已存在: $REMOTE_CLAUDE_SETTINGS_FILE"
        fi
    fi

    rc_copy_if_missing "$REMOTE_CLAUDE_STATE_TEMPLATE" "$REMOTE_CLAUDE_STATE_FILE" "运行时配置"
    if [ -f "$REMOTE_CLAUDE_STATE_FILE" ] && [ ! -s "$REMOTE_CLAUDE_STATE_FILE" ]; then
        print_info "运行时配置已存在: $REMOTE_CLAUDE_STATE_FILE"
    elif [ -f "$REMOTE_CLAUDE_STATE_FILE" ] && [ "$(wc -c < "$REMOTE_CLAUDE_STATE_FILE" 2>/dev/null)" -gt 0 ]; then
        if ! cmp -s "$REMOTE_CLAUDE_STATE_TEMPLATE" "$REMOTE_CLAUDE_STATE_FILE" 2>/dev/null; then
            print_info "运行时配置已存在: $REMOTE_CLAUDE_STATE_FILE"
        fi
    fi
}

# 设置可执行权限
set_permissions() {
    print_header "设置执行权限"

    chmod +x remote_claude.py
    chmod +x server/server.py
    chmod +x client/base_client.py
    chmod +x client/local_client.py
    chmod +x client/remote_client.py

    print_success "已设置执行权限"
}

# 安装快捷命令（符号链接到 bin 目录）
configure_shell() {
    print_header "安装快捷命令"

    rc_link_shortcuts_into_prepared_bins() {
        chmod +x "$PROJECT_DIR/bin/cla" "$PROJECT_DIR/bin/cl" "$PROJECT_DIR/bin/cx" "$PROJECT_DIR/bin/cdx" "$PROJECT_DIR/bin/remote-claude" 2>/dev/null || true
    }

    rc_link_shortcuts_into_prepared_bins

    # 优先 /usr/local/bin，权限不够则选 ~/bin 或 ~/.local/bin 中已在 PATH 里的
    BIN_DIR="/usr/local/bin"
    if ! ln -sf "$PROJECT_DIR/bin/cla" "$BIN_DIR/cla" 2>/dev/null; then
        if _path_contains "$HOME/bin"; then
            BIN_DIR="$HOME/bin"
        elif _path_contains "$HOME/.local/bin"; then
            BIN_DIR="$HOME/.local/bin"
        else
            BIN_DIR="$HOME/.local/bin"
            # 自动写入 PATH 到 shell 配置文件
            export PATH="$BIN_DIR:$PATH"
            _ensure_full_shell_init_block
            print_success "已自动将 \$HOME/.local/bin 加入 PATH 并写入 shell 初始化配置"
        fi
        mkdir -p "$BIN_DIR"
        rc_link_shortcuts_into_dir "$BIN_DIR"
    else
        rc_link_shortcuts_into_dir "$BIN_DIR"
    fi

    print_success "已安装 $REMOTE_CLAUDE_SHORTCUT_COMMANDS 到 $BIN_DIR"
    print_info "  cla           - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Claude"
    print_info "  cl            - 同 cla，但跳过权限确认"
    print_info "  cx            - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Codex（跳过权限）"
    print_info "  cdx           - 同 cx，但需确认权限"
    print_info "  remote-claude - Remote Claude 主命令（start/attach/list/kill/status/log/lark/config/connection/token/regenerate-token/stats/update/connect/remote）"

    # 安装 shell 自动补全（通过统一完整初始化块写入）
    _ensure_full_shell_init_block

    SHELL_RC=$(get_shell_rc)
    print_success "已更新 shell 初始化配置到 $SHELL_RC（重新打开终端后生效）"
}

# 重启飞书客户端
restart_lark_client() {
    print_header "重启飞书客户端"

    if [ ! -f "$REMOTE_CLAUDE_LARK_PID_FILE" ] && ! pgrep -f "lark_client/main.py" >/dev/null 2>&1; then
        print_info "飞书客户端未运行，跳过重启"
        return
    fi

    print_info "正在重启飞书客户端..."
    cd "$PROJECT_DIR"
    if ! _remote_claude_python lark restart; then
        add_warning "飞书客户端重启失败，请手动运行: remote-claude lark restart"
        return
    fi
    print_success "飞书客户端已重启"
}

# 显示使用说明
show_usage() {
    print_header "安装完成！"

    printf '\n'
    print_quick_commands_table
    printf '\n'
    printf '%b\n' "详细使用说明请阅读 README.md"
    printf '\n'
    print_shell_reload_hint "$(get_shell_rc)"
    printf '\n'
}

# 主流程
main() {
    # 解析参数
    NPM_MODE=false
    LAZY_MODE=false
    for arg in "$@"; do
        [ "$arg" = "--npm" ] && NPM_MODE=true
        [ "$arg" = "--lazy" ] && LAZY_MODE=true
    done

    _init_install_log

    # CI 模式：跳过 tmux 版本检查（CI 环境可能没有 sudo）
    if [ -n "$CI" ]; then
        export CI_MODE=true
    fi

    print_banner "Remote Claude 初始化脚本" "双端共享 Claude/Codex CLI 工具"

    # 延迟初始化模式：只运行必要步骤
    if $LAZY_MODE; then
        _install_stage "setup-lazy-precheck"
        setup_path || { rc=$?; _log_script_fail "setup-lazy-precheck" "setup_path" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
        check_uv || { rc=$?; _log_script_fail "setup-lazy-precheck" "check_uv" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
        _install_stage "setup-lazy-deps"
        install_dependencies || { rc=$?; _log_script_fail "setup-lazy-deps" "install_dependencies" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
        _install_stage "setup-lazy-config"
        create_directories || { rc=$?; _log_script_fail "setup-lazy-config" "create_directories" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
        init_config_files || { rc=$?; _log_script_fail "setup-lazy-config" "init_config_files" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
        _install_stage "setup-lazy-done"
        print_success "Python 环境初始化完成"
        return 0
    fi

    _install_stage "setup-precheck"
    setup_path || { rc=$?; _log_script_fail "setup-precheck" "setup_path" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    check_os || { rc=$?; _log_script_fail "setup-precheck" "check_os" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    check_uv || { rc=$?; _log_script_fail "setup-precheck" "check_uv" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    check_tmux || { rc=$?; _log_script_fail "setup-precheck" "check_tmux" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    check_cli_tools || { rc=$?; _log_script_fail "setup-precheck" "check_cli_tools" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    install_dependencies || { rc=$?; _log_script_fail "setup-precheck" "install_dependencies" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }

    _install_stage "setup-config"
    if ! $NPM_MODE; then
        configure_lark || { rc=$?; _log_script_fail "setup-config" "configure_lark" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    fi
    create_directories || { rc=$?; _log_script_fail "setup-config" "create_directories" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    init_config_files || { rc=$?; _log_script_fail "setup-config" "init_config_files" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }

    _install_stage "setup-finalize"
    set_permissions || { rc=$?; _log_script_fail "setup-finalize" "set_permissions" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    configure_shell || { rc=$?; _log_script_fail "setup-finalize" "configure_shell" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    restart_lark_client || { rc=$?; _log_script_fail "setup-finalize" "restart_lark_client" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    show_usage || { rc=$?; _log_script_fail "setup-finalize" "show_usage" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }

    _install_stage "setup-done"
    print_warnings
}

# 运行主流程
main "$@"
