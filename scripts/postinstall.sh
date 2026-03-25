#!/bin/bash
# postinstall.sh - npm/pnpm 安装后执行
# 全局安装时也执行完整 Python 环境初始化

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    printf "${GREEN}ℹ${NC} %s\n" "$1"
}

print_success() {
    printf "${GREEN}✓${NC} %s\n" "$1"
}

print_warning() {
    printf "${YELLOW}⚠${NC} %s\n" "$1"
}

print_error() {
    printf "${RED}✗${NC} %s\n" "$1"
}

print_detail() {
    printf "${BLUE}  %s${NC}\n" "$1"
}

# 解析安装目录（符号链接解析）
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in
        /*) ;;
        *) SOURCE="$DIR/$SOURCE" ;;
    esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 检测是否在包管理器缓存目录中
_is_in_package_manager_cache() {
    case "$INSTALL_DIR" in
        */.pnpm/*/node_modules/*|*/.store/*/node_modules/*|*pnpm*node_modules*|*/_cacache/*|*/.npm/*)
            return 0
            ;;
    esac
    return 1
}

# 引入共享脚本
source "$SCRIPT_DIR/_common.sh"

# 初始化 Python 环境
init_python_env() {
    print_info "正在初始化 Python 环境..."

    cd "$INSTALL_DIR"

    # 检查/安装 uv
    if ! check_and_install_uv; then
        print_error "uv 安装失败，请手动安装:"
        print_detail "curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    local uv_version
    uv_version=$(uv --version)
    print_success "uv 已安装: $uv_version"

    # 创建虚拟环境
    if [ ! -d "$INSTALL_DIR/.venv" ]; then
        print_info "创建虚拟环境..."
        uv venv
        print_success "虚拟环境创建完成"
    else
        print_info "虚拟环境已存在"
    fi

    # 安装依赖
    print_info "安装 Python 依赖..."
    if uv sync --frozen; then
        print_success "依赖安装完成"
    else
        print_warning "依赖安装失败，尝试非冻结模式..."
        if uv sync; then
            print_success "依赖安装完成"
        else
            print_error "依赖安装失败"
            exit 1
        fi
    fi

    # 验证安装
    print_info "验证安装..."
    if "$INSTALL_DIR/.venv/bin/python3" -c "import remote_claude" 2>/dev/null; then
        print_success "安装验证通过"
    else
        print_warning "模块验证跳过（不影响使用）"
    fi
}

# 显示完成信息
show_completion() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 安装完成${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    print_info "可用命令:"
    print_detail "cla  - 启动 Claude (当前目录为会话名)"
    print_detail "cl   - 同 cla，跳过权限确认"
    print_detail "cx   - 启动 Codex (跳过权限确认)"
    print_detail "cdx  - 同 cx，需要权限确认"
    print_detail "remote-claude - 管理工具"
    echo ""
    print_info "提示: 重新打开终端或运行 'source ~/.bashrc' 使命令生效"
    echo ""
}

# 主流程
main() {
    # 如果在包管理器缓存中，跳过初始化
    if _is_in_package_manager_cache; then
        echo "检测到缓存安装，跳过初始化"
        exit 0
    fi

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 初始化${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    init_python_env
    show_completion
}

main "$@"
