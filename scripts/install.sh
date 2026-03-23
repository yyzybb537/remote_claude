#!/bin/bash
#
# Remote Claude 一键安装脚本
# 自动安装 uv 并创建虚拟环境，用户无需预装 Python
#
# 用法：curl -fsSL https://raw.githubusercontent.com/.../scripts/install.sh | bash
# 或：./scripts/install.sh
#

set -e

# 颜色定义
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m' # No Color

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 打印函数
print_info() { echo -e "${GREEN}ℹ${NC} $1"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }

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

# 检查并安装 uv
check_and_install_uv() {
    print_header "检查 uv 包管理器"

    local RUNTIME_FILE="$HOME/.remote-claude/runtime.json"

    # 1. 从 runtime.json 读取 uv_path（需 jq）
    if [[ -f "$RUNTIME_FILE" ]] && command -v jq &> /dev/null; then
        local UV_PATH=$(jq -r '.uv_path // empty' "$RUNTIME_FILE" 2>/dev/null)
        if [[ -n "$UV_PATH" && -x "$UV_PATH" ]]; then
            # 配置路径有效
            print_success "uv（$UV_PATH）"
            export PATH="$(dirname "$UV_PATH"):$PATH"
            return 0
        elif [[ -n "$UV_PATH" ]]; then
            # 配置路径失效，清除并尝试系统 uv
            print_warning "配置的 uv 路径失效（$UV_PATH），尝试系统 uv..."
            # 清除失效路径
            local TMP_FILE=$(mktemp)
            jq '.uv_path = null' "$RUNTIME_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$RUNTIME_FILE"
        fi
    fi

    # 2. 检测系统 uv
    if command -v uv &> /dev/null; then
        UV_VERSION=$(uv --version)
        print_success "$UV_VERSION 已安装"
        _save_uv_path_install
        return 0
    fi

    print_warning "未找到 uv，正在安装..."

    # 3. 多来源安装
    _install_uv_multi_source_install

    # 4. 安装成功后写入路径
    if command -v uv &> /dev/null; then
        print_success "uv 安装成功"
        _save_uv_path_install
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

_install_uv_multi_source_install() {
    # 检测可用的 pip 命令
    local PIP_CMD=""
    if command -v pip3 &> /dev/null; then
        PIP_CMD="pip3"
    elif command -v pip &> /dev/null; then
        PIP_CMD="pip"
    fi

    # 方式一：官方安装脚本（推荐）
    if curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh 2>/dev/null; then
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式二：pip + PyPI
    if ! command -v uv &> /dev/null && [[ -n "$PIP_CMD" ]]; then
        print_warning "尝试 pip 安装 uv（官方 PyPI）..."
        ($PIP_CMD install uv --quiet 2>/dev/null || \
         $PIP_CMD install uv --quiet --break-system-packages 2>/dev/null) && \
            export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式三：pip + 清华镜像
    if ! command -v uv &> /dev/null && [[ -n "$PIP_CMD" ]]; then
        print_warning "尝试 pip 安装 uv（清华镜像）..."
        ($PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null || \
         $PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn \
            --break-system-packages 2>/dev/null) && \
            export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式四：conda/mamba
    if ! command -v uv &> /dev/null; then
        if command -v mamba &> /dev/null; then
            print_warning "尝试 mamba 安装 uv..."
            mamba install -c conda-forge uv -y --quiet 2>/dev/null || true
        elif command -v conda &> /dev/null; then
            print_warning "尝试 conda 安装 uv..."
            conda install -c conda-forge uv -y --quiet 2>/dev/null || true
        fi
    fi

    # 方式五：brew（macOS）
    if ! command -v uv &> /dev/null && [[ "$OS" == "Darwin" ]] && command -v brew &> /dev/null; then
        print_warning "尝试 brew install uv..."
        brew install uv 2>/dev/null || true
    fi
}

_save_uv_path_install() {
    local UV_PATH=$(command -v uv 2>/dev/null)
    if [[ -n "$UV_PATH" ]]; then
        local RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
        mkdir -p "$(dirname "$RUNTIME_FILE")"

        if [[ -f "$RUNTIME_FILE" ]] && command -v jq &> /dev/null; then
            local TMP_FILE=$(mktemp)
            jq --arg path "$UV_PATH" '.uv_path = $path' "$RUNTIME_FILE" > "$TMP_FILE" && \
                mv "$TMP_FILE" "$RUNTIME_FILE"
            print_info "已记录 uv 路径: $UV_PATH"
        elif [[ ! -f "$RUNTIME_FILE" ]]; then
            echo "{\"version\":\"1.0\",\"uv_path\":\"$UV_PATH\"}" > "$RUNTIME_FILE"
            print_info "已记录 uv 路径: $UV_PATH"
        fi
    fi
}

# 创建虚拟环境并安装依赖
setup_virtual_env() {
    print_header "创建 Python 虚拟环境"

    cd "$PROJECT_ROOT"

    # 读取 .python-version 文件（如存在）
    local PYTHON_VERSION="3.11"
    if [[ -f ".python-version" ]]; then
        PYTHON_VERSION=$(cat .python-version | tr -d '[:space:]')
        print_info "使用 Python 版本: $PYTHON_VERSION"
    fi

    # 使用 uv 创建虚拟环境
    print_info "正在创建虚拟环境..."
    if ! uv venv --python "$PYTHON_VERSION" 2>/dev/null; then
        # 如果指定版本不可用，尝试让 uv 自动安装
        print_warning "Python $PYTHON_VERSION 不可用，正在安装..."
        uv python install "$PYTHON_VERSION"
        uv venv --python "$PYTHON_VERSION"
    fi
    print_success "虚拟环境创建成功"

    # 安装依赖
    print_info "正在安装依赖..."
    uv sync
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
    check_and_install_uv
    setup_virtual_env
    verify_installation
    show_next_steps
}

# 运行主流程
main "$@"
