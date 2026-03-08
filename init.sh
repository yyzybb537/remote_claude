#!/bin/bash

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
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
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
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

# 检查并安装 tmux
check_tmux() {
    print_header "检查 tmux"

    if command -v tmux &> /dev/null; then
        TMUX_VERSION=$(tmux -V)
        print_success "$TMUX_VERSION 已安装"
        return
    fi

    print_warning "未找到 tmux，正在安装..."

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
            print_error "无法自动安装 tmux，请手动安装"
            exit 1
        fi
    fi

    print_success "tmux 安装成功"
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

# 运行测试
run_tests() {
    print_header "运行测试"

    read -p "$(echo -e ${YELLOW}是否运行单元测试？${NC} [y/N]: )" -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if [ -f "tests/test_format_unit.py" ]; then
            print_info "运行格式化单元测试..."
            uv run python3 tests/test_format_unit.py
            print_success "测试通过"
        else
            print_warning "未找到测试文件，跳过"
        fi
    fi
}

# 配置 shell 快捷命令
configure_shell() {
    print_header "配置 Shell 快捷命令"

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    SHELL_RC=""

    # 检测当前 shell
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_RC="$HOME/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        SHELL_RC="$HOME/.bashrc"
    fi

    if [ -z "$SHELL_RC" ]; then
        print_warning "未检测到 bash/zsh，请手动配置快捷命令"
        return
    fi

    # 检查是否已配置
    if grep -q "remote_claude.py" "$SHELL_RC" 2>/dev/null; then
        print_info "快捷命令已配置在 $SHELL_RC 中"
        return
    fi

    read -p "$(echo -e ${YELLOW}是否添加快捷命令到 ${SHELL_RC}？${NC} [y/N]: )" -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cat >> "$SHELL_RC" << RCEOF

# Remote Claude 快捷命令
cla() { uv run --project ${SCRIPT_DIR} python3 ${SCRIPT_DIR}/remote_claude.py lark start; uv run --project ${SCRIPT_DIR} python3 ${SCRIPT_DIR}/remote_claude.py start "\${PWD}_\$(date +%m%d_%H%M%S)"; }
cl() { uv run --project ${SCRIPT_DIR} python3 ${SCRIPT_DIR}/remote_claude.py lark start; uv run --project ${SCRIPT_DIR} python3 ${SCRIPT_DIR}/remote_claude.py start "\${PWD}_\$(date +%m%d_%H%M%S)" -- --dangerously-skip-permissions --permission-mode=dontAsk; }
RCEOF
        print_success "已添加快捷命令到 $SHELL_RC"
        print_info "  cla  - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Claude"
        print_info "  cl   - 同 cla，但跳过权限确认"
        print_warning "请运行 source $SHELL_RC 或重新打开终端生效"
    else
        print_info "跳过快捷命令配置"
    fi
}

# 显示使用说明
show_usage() {
    print_header "安装完成！"

    cat << EOF
Remote Claude 已成功初始化！🎉

${GREEN}快速开始：${NC}

  1. 启动一个新会话：
     ${BLUE}uv run python3 remote_claude.py start <会话名>${NC}

     示例：
     uv run python3 remote_claude.py start mywork

  2. 从其他终端连接会话：
     ${BLUE}uv run python3 remote_claude.py attach <会话名>${NC}

  3. 查看所有会话：
     ${BLUE}uv run python3 remote_claude.py list${NC}

  4. 关闭会话：
     ${BLUE}uv run python3 remote_claude.py kill <会话名>${NC}

${YELLOW}快捷命令：${NC}

  ${BLUE}cla${NC}  - 启动飞书客户端 + 以当前目录+时间戳为会话名启动 Claude
  ${BLUE}cl${NC}   - 同 cla，但跳过权限确认

${YELLOW}飞书客户端（可选）：${NC}

  1. 编辑 .env 文件，填写飞书应用凭证
  2. 启动飞书客户端：
     ${BLUE}uv run python3 remote_claude.py lark start${NC}
  3. 管理飞书客户端：
     ${BLUE}uv run python3 remote_claude.py lark stop/restart/status${NC}
  4. 在飞书中与机器人对话，使用命令：
     /attach <会话名>  - 连接会话
     /detach          - 断开会话
     /list            - 查看所有会话

${YELLOW}测试：${NC}

  单元测试（无需会话）：
  ${BLUE}uv run python3 tests/test_format_unit.py${NC}

  集成测试（需先启动会话）：
  ${BLUE}uv run python3 remote_claude.py start test${NC}
  ${BLUE}uv run python3 tests/test_integration.py${NC}

${YELLOW}文档：${NC}

  - CLAUDE.md         - 项目架构和开发说明
  - QUICKSTART.md     - 快速上手指南
  - TEST_PLAN.md      - 测试计划和场景

${GREEN}祝使用愉快！${NC}

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
    run_tests
    show_usage
}

# 运行主流程
main
