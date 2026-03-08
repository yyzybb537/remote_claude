#!/bin/bash

set -e

# 颜色定义
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m' # No Color

# 末尾汇总警告
WARNINGS=()

# 打印函数
print_info() {
    echo -e "${GREEN}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 检查操作系统
check_os() {
    print_header "检查系统环境"

    OS=$(uname -s)
    if [[ "$OS" != "Darwin" && "$OS" != "Linux" ]]; then
        print_error "不支持的操作系统: $OS"
        print_error "Remote Claude 仅支持 macOS 和 Linux"
        exit 1
    fi

    print_success "操作系统: $OS"
}

# 检查 uv
check_uv() {
    print_header "检查 uv"

    if command -v uv &> /dev/null; then
        UV_VERSION=$(uv --version)
        print_success "$UV_VERSION 已安装"
        return
    fi

    print_warning "未找到 uv，正在安装..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # 重新加载 PATH
    export PATH="$HOME/.local/bin:$PATH"

    if command -v uv &> /dev/null; then
        print_success "uv 安装成功"
    else
        print_error "uv 安装失败，请手动安装: https://docs.astral.sh/uv/"
        exit 1
    fi
}

# 检查并安装 tmux（要求 3.6+）
check_tmux() {
    print_header "检查 tmux"

    REQUIRED_MAJOR=3
    REQUIRED_MINOR=6

    install_tmux() {
        if [[ "$OS" == "Darwin" ]]; then
            if ! command -v brew &> /dev/null; then
                print_error "未找到 Homebrew，请先安装: https://brew.sh"
                exit 1
            fi
            brew install tmux
        elif [[ "$OS" == "Linux" ]]; then
            if command -v apt-get &> /dev/null; then
                sudo apt-get update && sudo apt-get install -y tmux
            elif command -v yum &> /dev/null; then
                sudo yum install -y tmux
            else
                print_error "无法自动安装 tmux，请手动安装 3.6 或更高版本"
                exit 1
            fi
        fi
        print_success "tmux 安装成功"
    }

    check_version() {
        # tmux -V 输出格式：tmux 3.6 或 tmux 3.4a
        local ver_str
        ver_str=$(tmux -V | awk '{print $2}')
        local major minor
        major=$(echo "$ver_str" | cut -d. -f1)
        minor=$(echo "$ver_str" | cut -d. -f2 | tr -dc '0-9')
        if [[ "$major" -gt "$REQUIRED_MAJOR" ]] || \
           [[ "$major" -eq "$REQUIRED_MAJOR" && "${minor:-0}" -ge "$REQUIRED_MINOR" ]]; then
            return 0
        fi
        return 1
    }

    if command -v tmux &> /dev/null; then
        TMUX_VERSION=$(tmux -V)
        if check_version; then
            print_success "$TMUX_VERSION 已安装（满足 >= ${REQUIRED_MAJOR}.${REQUIRED_MINOR}）"
            return
        else
            print_warning "$TMUX_VERSION 版本过低，需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR} 或更高，正在升级..."
            install_tmux
            # 升级后再次验证
            if ! check_version; then
                print_warning "升级后版本仍不满足要求（$(tmux -V)），请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
                WARNINGS+=("tmux 版本不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+，请手动升级")
            else
                print_success "tmux 已升级至 $(tmux -V)"
            fi
        fi
    else
        print_warning "未找到 tmux，正在安装..."
        install_tmux
        if ! check_version; then
            print_warning "安装的版本不满足要求（$(tmux -V)），请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
            WARNINGS+=("tmux 版本不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+，请手动升级")
        fi
    fi
}

# 检查 Claude CLI
check_claude() {
    print_header "检查 Claude CLI"

    if command -v claude &> /dev/null; then
        print_success "Claude CLI 已安装"
        return
    fi

    print_warning "未找到 Claude CLI"
    print_info "请访问 https://claude.ai/code 安装 Claude CLI"

    read -p "$(echo -e ${YELLOW}是否已安装 Claude CLI？${NC} [y/N]: )" -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "请先安装 Claude CLI 后再运行此脚本"
        exit 1
    fi

    if ! command -v claude &> /dev/null; then
        print_error "仍未找到 claude 命令，请检查安装或 PATH 配置"
        exit 1
    fi
}

# 安装 Python 依赖
install_dependencies() {
    print_header "安装 Python 依赖"

    if [ ! -f "pyproject.toml" ]; then
        print_error "未找到 pyproject.toml 文件"
        exit 1
    fi

    print_info "正在通过 uv 同步依赖..."
    uv sync

    print_success "依赖安装完成"
}

# 配置飞书环境
configure_lark() {
    print_header "配置飞书客户端"

    if [ -f ".env" ]; then
        print_warning ".env 文件已存在，跳过配置"
        return
    fi

    if [ ! -f ".env.example" ]; then
        print_error "未找到 .env.example 文件"
        exit 1
    fi

    read -p "$(echo -e ${YELLOW}是否需要配置飞书客户端？${NC} [y/N]: )" -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp .env.example .env
        print_success ".env 文件已创建"
        print_warning "请编辑 .env 文件，填写以下信息："
        print_info "  - FEISHU_APP_ID: 飞书应用的 App ID"
        print_info "  - FEISHU_APP_SECRET: 飞书应用的 App Secret"
        print_info ""
        print_info "获取方式: 登录飞书开放平台 -> 创建应用 -> 凭证与基础信息"
    else
        print_info "跳过飞书配置（可稍后手动配置）"
    fi
}

# 创建必要目录
create_directories() {
    print_header "创建运行目录"

    SOCKET_DIR="/tmp/remote-claude"

    if [ ! -d "$SOCKET_DIR" ]; then
        mkdir -p "$SOCKET_DIR"
        print_success "创建目录: $SOCKET_DIR"
    else
        print_info "目录已存在: $SOCKET_DIR"
    fi
}

# 设置可执行权限
set_permissions() {
    print_header "设置执行权限"

    chmod +x remote_claude.py
    chmod +x server/server.py
    chmod +x client/client.py

    print_success "已设置执行权限"
}

# 安装快捷命令（符号链接到 bin 目录）
configure_shell() {
    print_header "安装快捷命令"

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    chmod +x "$SCRIPT_DIR/bin/cla" "$SCRIPT_DIR/bin/cl"

    # 优先 /usr/local/bin，权限不够则选 ~/bin 或 ~/.local/bin 中已在 PATH 里的
    BIN_DIR="/usr/local/bin"
    if ! ln -sf "$SCRIPT_DIR/bin/cla" "$BIN_DIR/cla" 2>/dev/null; then
        if [[ ":$PATH:" == *":$HOME/bin:"* ]]; then
            BIN_DIR="$HOME/bin"
        elif [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
            BIN_DIR="$HOME/.local/bin"
        else
            BIN_DIR="$HOME/.local/bin"
            print_warning "cla/cl 将安装到 $BIN_DIR，但该目录不在 PATH 中"
            print_info "请将以下行添加到 shell 配置文件（~/.zshrc 或 ~/.bashrc）："
            echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
        mkdir -p "$BIN_DIR"
        ln -sf "$SCRIPT_DIR/bin/cla" "$BIN_DIR/cla"
        ln -sf "$SCRIPT_DIR/bin/cl"  "$BIN_DIR/cl"
    else
        ln -sf "$SCRIPT_DIR/bin/cl" "$BIN_DIR/cl"
    fi

    print_success "已安装 cla 和 cl 到 $BIN_DIR"
    print_info "  cla  - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Claude"
    print_info "  cl   - 同 cla，但跳过权限确认"
}

# 重启飞书客户端
restart_lark_client() {
    print_header "重启飞书客户端"

    LARK_PID_FILE="/tmp/remote-claude/lark.pid"

    if [ ! -f "$LARK_PID_FILE" ] && ! pgrep -f "lark_client/main.py" &>/dev/null; then
        print_info "飞书客户端未运行，跳过重启"
        return
    fi

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    print_info "正在重启飞书客户端..."
    cd "$SCRIPT_DIR"
    uv run python3 remote_claude.py lark restart
    print_success "飞书客户端已重启"
}

# 显示使用说明
show_usage() {
    print_header "安装完成！"

    cat << EOF
${YELLOW}快捷命令：${NC}

  ${GREEN}cla${NC}  - 启动飞书客户端 + 以当前目录+时间戳为会话名启动 Claude
  ${GREEN}cl${NC}   - 同 cla，但跳过权限确认

详细使用说明请阅读 README.md

EOF
}

# 主流程
main() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 初始化脚本${NC}"
    echo -e "${GREEN}   双端共享 Claude CLI 工具${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    check_os
    check_uv
    check_tmux
    check_claude
    install_dependencies
    configure_lark
    create_directories
    set_permissions
    configure_shell
    restart_lark_client
    show_usage

    if [ ${#WARNINGS[@]} -gt 0 ]; then
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}⚠ 注意事项${NC}"
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        for w in "${WARNINGS[@]}"; do
            echo -e "${YELLOW}⚠${NC} $w"
        done
        echo ""
    fi
}

# 运行主流程
main
