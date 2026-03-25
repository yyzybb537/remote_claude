#!/bin/bash
#
# Remote Claude 一键安装脚本
# 自动安装 uv 并创建虚拟环境，用户无需预装 Python
#
# 用法：curl -fsSL https://raw.githubusercontent.com/.../scripts/install.sh | bash
# 或：./scripts/install.sh
#

set -e

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 引入共享脚本（提供颜色定义、打印函数、uv 管理函数）
source "$SCRIPT_DIR/_common.sh"

print_header() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 检测操作系统
detect_os() {
    OS=$(uname -s)
    if [[ "$OS" != "Darwin" && "$OS" != "Linux" ]]; then
        print_error "不支持的操作系统: $OS"
        print_error "Remote Claude 仅支持 macOS 和 Linux"
        exit 1
    fi
    print_success "操作系统: $OS"
}

# 检查并安装 uv（使用 _common.sh 中的函数）
check_and_install_uv_install() {
    print_header "检查 uv 包管理器"

    if check_and_install_uv; then
        UV_VERSION=$(uv --version)
        print_success "$UV_VERSION 已安装"
        return 0
    fi

    print_error "uv 安装失败，请手动安装："
    print_info "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    print_info "  pip3 install uv"
    print_info "  pip3 install uv -i https://pypi.tuna.tsinghua.edu.cn/simple/"
    print_info "  conda install -c conda-forge uv"
    print_info "  或访问 https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
}

# 创建虚拟环境并安装依赖
setup_virtual_env() {
    print_header "创建 Python 虚拟环境"

    cd "$PROJECT_ROOT"

    # 使用 uv 创建虚拟环境
    # Python 版本由 pyproject.toml 的 requires-python 决定，uv 自动管理
    print_info "正在创建虚拟环境..."
    uv venv
    print_success "虚拟环境创建成功"

    # 安装依赖
    print_info "正在安装依赖..."
    uv sync --frozen || uv sync
    print_success "依赖安装完成"
}

# 验证安装
verify_installation() {
    print_header "验证安装"

    cd "$PROJECT_ROOT"

    print_info "Python 版本: $(uv run python3 --version)"
    print_info "安装路径: $(uv run which python3 2>/dev/null || echo 'uv 管理')"

    # 测试核心模块导入
    if uv run python3 -c "from utils.session import *; from utils.runtime_config import *; print('核心模块导入成功')" 2>/dev/null; then
        print_success "核心模块验证通过"
    else
        print_warning "核心模块导入警告（可能是路径问题）"
    fi

    print_success "安装验证完成"
}

# 显示下一步
show_next_steps() {
    print_header "安装完成！"

    cat << EOF
${YELLOW}下一步操作：${NC}

1. 初始化项目（推荐）：
   ${GREEN}./init.sh${NC}

2. 运行 Remote Claude（推荐方式）：
   ${GREEN}uv run python3 remote_claude.py --help${NC}

3. 或手动激活虚拟环境（传统方式）：
   ${GREEN}source .venv/bin/activate${NC}
   ${GREEN}python3 remote_claude.py --help${NC}

${YELLOW}提示：${NC}
- 虚拟环境位于 ${GREEN}.venv/${NC} 目录
- 推荐使用 ${GREEN}uv run python3 ...${NC} 自动激活虚拟环境执行命令
- 详细文档请阅读 README.md

EOF
}

# 主流程
main() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 一键安装${NC}"
    echo -e "${GREEN}   零依赖安装 - 自动配置 Python 环境${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    detect_os
    check_and_install_uv_install
    setup_virtual_env
    verify_installation
    show_next_steps
}

# 运行主流程
main "$@"
