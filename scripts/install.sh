#!/bin/sh
#
# Remote Claude 一键安装脚本
# 自动安装 uv 并创建虚拟环境，用户无需预装 Python
#
# 用法：curl -fsSL https://raw.githubusercontent.com/.../scripts/install.sh | sh
# 或：./scripts/install.sh
# POSIX sh 兼容，支持 sh/bash/zsh
#

set -e

# 脚本目录（scripts/ 目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 项目根目录
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 引入共享脚本（提供颜色定义、打印函数、uv 管理函数）
# 使用 . 而非 source，兼容 POSIX sh
. "$SCRIPT_DIR/_common.sh"

# 检测操作系统
detect_os() {
    OS=$(uname -s)
    if [ "$OS" != "Darwin" ] && [ "$OS" != "Linux" ]; then
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

    cd "$PROJECT_DIR"

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

    cd "$PROJECT_DIR"

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

# 运行 setup.sh 完成初始化
run_setup_script() {
    setup_script="$SCRIPT_DIR/setup.sh"

    if [ ! -f "$setup_script" ]; then
        print_error "未找到 setup.sh 脚本: $setup_script"
        exit 1
    fi

    print_info "执行 setup.sh 进行完整初始化..."

    if $NPM_MODE && $LAZY_MODE; then
        sh "$setup_script" --npm --lazy
    elif $NPM_MODE; then
        sh "$setup_script" --npm
    elif $LAZY_MODE; then
        sh "$setup_script" --lazy
    else
        sh "$setup_script"
    fi
}

# 在 npm postinstall 场景下收敛可忽略失败范围
run_npm_postinstall() {
    if _is_in_package_manager_cache && ! _is_pnpm_global_install; then
        echo "检测到缓存安装，跳过初始化"
        return 0
    fi

    run_setup_script
}

# 运行 setup.sh 完成初始化
run_init_script() {
    print_header "运行初始化脚本"

    if $NPM_MODE; then
        run_npm_postinstall
    else
        run_setup_script
    fi

    print_success "setup.sh 执行完成"
}

# 显示完成信息
show_completion() {
    print_header "安装完成"

    shell_rc=$(get_shell_rc)

    echo "${GREEN}可用命令:${NC}"
    echo "  ${GREEN}cla${NC}  - 启动 Claude"
    echo "  ${GREEN}cl${NC}   - 启动 Claude (跳过权限)"
    echo "  ${GREEN}cx${NC}   - 启动 Codex"
    echo "  ${GREEN}cdx${NC}  - 启动 Codex (需权限)"
    echo "  ${GREEN}remote-claude${NC} - 管理工具"
    echo ""
    echo "${YELLOW}提示:${NC} 重新打开终端或运行 ${GREEN}source $shell_rc${NC} 生效"
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

    # npm postinstall 场景的缓存跳过逻辑由 run_npm_postinstall() 收敛处理
    if _is_in_package_manager_cache && ! $NPM_MODE; then
        echo "检测到缓存安装，跳过初始化"
        exit 0
    fi

    printf '\n'
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '%b\n' "${GREEN}   Remote Claude 一键安装${NC}"
    printf '%b\n' "${GREEN}   零依赖安装 - 自动配置 Python 环境${NC}"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '\n'

    # 延迟模式：只运行必要步骤
    if $LAZY_MODE; then
        check_and_install_uv_install
        setup_virtual_env
        print_success "Python 环境初始化完成"
        return 0
    fi

    detect_os
    check_and_install_uv_install
    setup_virtual_env
    verify_installation
    run_init_script
    show_completion
}

# 运行主流程
main "$@"
