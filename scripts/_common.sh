#!/bin/sh
# _common.sh - 共享的脚本初始化逻辑
# 用法: . "$SCRIPT_DIR/scripts/_common.sh"

# 解析符号链接，兼容 macOS（不支持 readlink -f）
# 设置 SCRIPT_DIR 变量（项目根目录）
# 调用方式：在脚本开头定义 SOURCE 并调用此文件
#
# 示例:
#   SOURCE="$0"
#   while [ -L "$SOURCE" ]; do
#       DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
#       SOURCE="$(readlink "$SOURCE")"
#       case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
#   done
#   SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
#   . "$SCRIPT_DIR/scripts/_common.sh"

# 颜色定义（供 sourced 脚本使用）
if [ -z "$RED" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
fi

# 打印函数
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

# uv 路径兜底
if ! command -v uv >/dev/null 2>&1; then
    [ -f "$HOME/.local/bin/uv" ] && export PATH="$HOME/.local/bin:$PATH"
fi

# 从 runtime.json 读取 uv 路径
_read_uv_path_from_runtime() {
    local RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
    if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
        jq -r '.uv_path // empty' "$RUNTIME_FILE" 2>/dev/null
    fi
}

# 保存 uv 路径到 runtime.json
_save_uv_path_to_runtime() {
    local UV_PATH="$1"
    local RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
    mkdir -p "$(dirname "$RUNTIME_FILE")"

    if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
        local TMP_FILE
        TMP_FILE=$(mktemp)
        jq --arg path "$UV_PATH" '.uv_path = $path' "$RUNTIME_FILE" > "$TMP_FILE" && \
            mv "$TMP_FILE" "$RUNTIME_FILE"
    elif [ ! -f "$RUNTIME_FILE" ]; then
        printf '{"version":"1.0","uv_path":"%s"}\n' "$UV_PATH" > "$RUNTIME_FILE"
    fi
}

# 多来源安装 uv
# 返回: 0 成功, 1 失败
install_uv_multi_source() {
    # 检测可用的 pip 命令
    local PIP_CMD=""
    if command -v pip3 >/dev/null 2>&1; then
        PIP_CMD="pip3"
    elif command -v pip >/dev/null 2>&1; then
        PIP_CMD="pip"
    fi

    # 方式一：官方安装脚本（推荐，无需 Python）
    if curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh 2>/dev/null | sh; then
        export PATH="$HOME/.local/bin:$PATH"
        return 0
    fi

    # 方式二：pip + PyPI
    if ! command -v uv >/dev/null 2>&1 && [ -n "$PIP_CMD" ]; then
        print_warning "尝试 pip 安装 uv（官方 PyPI）..."
        if ($PIP_CMD install uv --quiet 2>/dev/null || \
            $PIP_CMD install uv --quiet --break-system-packages 2>/dev/null); then
            export PATH="$HOME/.local/bin:$PATH"
            return 0
        fi
    fi

    # 方式三：pip + 清华镜像
    if ! command -v uv >/dev/null 2>&1 && [ -n "$PIP_CMD" ]; then
        print_warning "尝试 pip 安装 uv（清华镜像）..."
        if ($PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null || \
         $PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn \
            --break-system-packages 2>/dev/null); then
            export PATH="$HOME/.local/bin:$PATH"
            return 0
        fi
    fi

    # 方式四：conda/mamba
    if ! command -v uv >/dev/null 2>&1; then
        if command -v mamba >/dev/null 2>&1; then
            print_warning "尝试 mamba 安装 uv..."
            if mamba install -c conda-forge uv -y --quiet 2>/dev/null; then
                return 0
            fi
        elif command -v conda >/dev/null 2>&1; then
            print_warning "尝试 conda 安装 uv..."
            if conda install -c conda-forge uv -y --quiet 2>/dev/null; then
                return 0
            fi
        fi
    fi

    # 方式五：brew（macOS）
    if ! command -v uv >/dev/null 2>&1 && [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        print_warning "尝试 brew install uv..."
        if brew install uv 2>/dev/null; then
            return 0
        fi
    fi

    return 1
}

# 检查并安装 uv（完整流程）
# 返回: 0 成功, 1 失败
check_and_install_uv() {
    # 1. 从 runtime.json 读取 uv_path
    local UV_PATH
    UV_PATH=$(_read_uv_path_from_runtime)
    if [ -n "$UV_PATH" ] && [ -x "$UV_PATH" ]; then
        export PATH="$(dirname "$UV_PATH"):$PATH"
        return 0
    elif [ -n "$UV_PATH" ]; then
        print_warning "配置的 uv 路径失效（$UV_PATH），尝试系统 uv..."
        # 清除失效路径
        local RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
        if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
            local TMP_FILE
            TMP_FILE=$(mktemp)
            jq '.uv_path = null' "$RUNTIME_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$RUNTIME_FILE"
        fi
    fi

    # 2. 检测系统 uv
    if command -v uv >/dev/null 2>&1; then
        _save_uv_path_to_runtime "$(command -v uv)"
        return 0
    fi

    # 3. 多来源安装
    print_warning "未找到 uv，正在安装..."
    if install_uv_multi_source; then
        print_success "uv 安装成功"
        _save_uv_path_to_runtime "$(command -v uv)"
        return 0
    fi

    return 1
}

# 检测是否在包管理器缓存目录中
# 缓存目录中的安装不应该执行初始化
_is_in_package_manager_cache() {
    case "$SCRIPT_DIR" in
        */.pnpm/*/node_modules/*|*/.store/*/node_modules/*|*pnpm*node_modules*|*/_cacache/*|*/.npm/*)
            return 0
            ;;
    esac
    return 1
}

# 检测是否为全局安装
# 全局安装时 .venv 应该在安装目录中创建，且不应重复初始化
_is_global_install() {
    # npm 全局安装路径、pnpm 全局安装路径、Windows npm 全局路径、nvm 路径
    case "$SCRIPT_DIR" in
        /usr/local/lib/node_modules/*|/usr/lib/node_modules/*|"$HOME"/.local/lib/node_modules/*|/opt/homebrew/lib/node_modules/*|/usr/local/Cellar/node/*/lib/node_modules/*|\
"$HOME"/Library/pnpm/global/*|"$HOME"/.local/share/pnpm/global/*|"$HOME"/AppData/Local/pnpm/global/*|\
"$PROGRAMFILES"/nodejs/node_modules/*|"$APPDATA"/npm/node_modules/*|\
"$HOME"/.nvm/*/lib/node_modules/*|"$HOME"/.config/nvm/*/lib/node_modules/*)
            return 0
            ;;
    esac
    return 1
}

# 检查是否需要重新同步依赖
# 条件：.venv 不存在，或 pyproject.toml/uv.lock 比 .venv 新
# 返回: 0 需要同步, 1 不需要
_needs_sync() {
    local venv_dir="$SCRIPT_DIR/.venv"

    # .venv 不存在，需要同步
    [ ! -d "$venv_dir" ] && return 0

    # 检查 pyproject.toml 是否比 .venv 新
    if [ -f "$SCRIPT_DIR/pyproject.toml" ] && \
       [ "$SCRIPT_DIR/pyproject.toml" -nt "$venv_dir" ]; then
        return 0
    fi

    # 检查 uv.lock 是否比 .venv 新
    if [ -f "$SCRIPT_DIR/uv.lock" ] && \
       [ "$SCRIPT_DIR/uv.lock" -nt "$venv_dir" ]; then
        return 0
    fi

    return 1
}

# 延迟初始化：检测是否需要运行 init.sh
# 条件：.venv 不存在 或依赖文件更新 且不在缓存目录中
_lazy_init() {
    # 如果在包管理器缓存中，跳过初始化
    if _is_in_package_manager_cache; then
        return 0
    fi

    # 如果需要同步（venv 不存在或依赖变更），执行初始化
    if _needs_sync; then
        echo "检测到依赖变更，正在更新 Python 环境..."
        cd "$SCRIPT_DIR"
        if command -v bash >/dev/null 2>&1; then
            bash init.sh --npm --lazy 2>/dev/null || true
        fi
    fi
}
_lazy_init
