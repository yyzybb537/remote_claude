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

# 颜色常量（BLUE 仅用于 print_detail）
BLUE='\033[0;34m'

print_detail() {
    printf "${BLUE}  %s${NC}\n" "$1"
}

# uv 路径兜底
if ! command -v uv >/dev/null 2>&1; then
    [ -f "$HOME/.local/bin/uv" ] && export PATH="$HOME/.local/bin:$PATH"
fi

# 从 runtime.json 读取 uv 路径
_read_uv_path_from_runtime() {
    local RUNTIME_FILE
    RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
    if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
        jq -r '.uv_path // empty' "$RUNTIME_FILE" 2>/dev/null
    fi
}

# 保存 uv 路径到 runtime.json
_save_uv_path_to_runtime() {
    local UV_PATH RUNTIME_FILE TMP_FILE
    UV_PATH="$1"
    RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
    mkdir -p "$(dirname "$RUNTIME_FILE")"

    if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
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
    local PIP_CMD
    PIP_CMD=""
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
    local UV_PATH RUNTIME_FILE TMP_FILE
    # 1. 从 runtime.json 读取 uv_path
    UV_PATH=$(_read_uv_path_from_runtime)
    if [ -n "$UV_PATH" ] && [ -x "$UV_PATH" ]; then
        export PATH="$(dirname "$UV_PATH"):$PATH"
        return 0
    elif [ -n "$UV_PATH" ]; then
        print_warning "配置的 uv 路径失效（$UV_PATH），尝试系统 uv..."
        # 清除失效路径
        RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
        if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
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

# 检查字符串是否为纯数字
_is_numeric() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

# 获取 shell 配置文件路径（POSIX 兼容）
# 优先使用当前运行的 shell 类型，而非 $SHELL 环境变量
get_shell_rc() {
    if [ -n "$ZSH_VERSION" ]; then
        echo "$HOME/.zshrc"
    elif [ -n "$BASH_VERSION" ]; then
        echo "$HOME/.bashrc"
    elif [ -f "$HOME/.zshrc" ]; then
        echo "$HOME/.zshrc"
    else
        echo "$HOME/.bashrc"
    fi
}

# 检查 PATH 是否包含指定目录
_path_contains() {
    case ":$PATH:" in
        *":$1:"*) return 0 ;;
        *) return 1 ;;
    esac
}

# 打印带颜色的标题头
print_header() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 检测是否在包管理器缓存目录中
# 缓存目录中的安装不应该执行初始化
_is_in_package_manager_cache() {
    # pnpm 缓存路径、npm 缓存路径、yarn 缓存路径、通用 node_modules 缓存标识
    case "$SCRIPT_DIR" in
        */.pnpm/*/node_modules/*|*/.pnpm-store/*|*/.store/*/node_modules/*|*/node_modules/.pnpm/*|\
        *pnpm*node_modules*|*pnpm-global*|\
        */_cacache/*|*/.npm/*|*/.npm-cache/*|\
        */.yarn/cache/*|*/.yarn/cache|\
        */node_modules/.cache/*|*/.cache/node_modules/*)
            return 0
            ;;
    esac
    return 1
}

# 检测是否为 pnpm 全局安装
# pnpm 全局安装需要正常初始化（不同于缓存）
# 返回: 0 是 pnpm 全局安装, 1 不是
_is_pnpm_global_install() {
    case "$SCRIPT_DIR" in
        "$HOME"/Library/pnpm/global/*|"$HOME"/.local/share/pnpm/global/*|"$HOME"/AppData/Local/pnpm/global/*)
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
    local venv_dir project_dir

    # 使用 PROJECT_DIR（如果已设置）或从 SCRIPT_DIR 推导
    project_dir="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)}"
    [ -z "$project_dir" ] && return 1

    venv_dir="$project_dir/.venv"

    # .venv 不存在，需要同步
    [ ! -d "$venv_dir" ] && return 0

    # 检查 pyproject.toml 是否比 .venv 新
    if [ -f "$project_dir/pyproject.toml" ] && \
       [ "$project_dir/pyproject.toml" -nt "$venv_dir" ]; then
        return 0
    fi

    # 检查 uv.lock 是否比 .venv 新
    if [ -f "$project_dir/uv.lock" ] && \
       [ "$project_dir/uv.lock" -nt "$venv_dir" ]; then
        return 0
    fi

    return 1
}

# 延迟初始化：检测是否需要运行 init.sh
# 条件：.venv 不存在 或依赖文件更新 且不在缓存目录中
_lazy_init() {
    # 防止重入：如果已经在 init.sh 流程中，跳过
    case "${_LAZY_INIT_RUNNING:-}" in
        1) return 0 ;;
    esac

    # 如果在包管理器缓存中，跳过初始化
    if _is_in_package_manager_cache; then
        return 0
    fi

    # 如果需要同步（venv 不存在或依赖变更），执行初始化
    if _needs_sync; then
        local project_dir
        project_dir="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)}"
        [ -z "$project_dir" ] && return 1

        echo "检测到依赖变更，正在更新 Python 环境..."
        cd "$project_dir"
        if command -v bash >/dev/null 2>&1; then
            # 设置标记防止重入
            _LAZY_INIT_RUNNING=1
            export _LAZY_INIT_RUNNING
            bash "$SCRIPT_DIR/setup.sh" --npm --lazy 2>/dev/null || true
            _LAZY_INIT_RUNNING=0
        fi
    fi
}
_lazy_init
