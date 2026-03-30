#!/bin/sh
# _common.sh - 共享的脚本初始化逻辑
# 用法: . "$PROJECT_DIR/scripts/_common.sh"

# 解析符号链接，兼容 macOS（不支持 readlink -f）
# 入口脚本可设置 PROJECT_DIR（推荐）或 SCRIPT_DIR，_common.sh 会统一补全两者
#
# 示例:
#   SOURCE="$0"
#   while [ -L "$SOURCE" ]; do
#       DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
#       SOURCE="$(readlink "$SOURCE")"
#       case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
#   done
#   PROJECT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
#   . "$PROJECT_DIR/scripts/_common.sh"

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

INSTALL_LOG_FILE="/tmp/remote-claude-install.log"

_init_install_log() {
    : > "$INSTALL_LOG_FILE"
    printf '[install] script=%s cwd=%s shell=%s\n' "${0##*/}" "$(pwd)" "${SHELL:-unknown}" >> "$INSTALL_LOG_FILE"
}

_install_log() {
    printf '[install] %s\n' "$1" >> "$INSTALL_LOG_FILE"
}

_install_stage() {
    INSTALL_STAGE="$1"
    export INSTALL_STAGE
    _install_log "stage=$INSTALL_STAGE"
}

_install_fail_hint() {
    print_error "安装失败，请查看日志: $INSTALL_LOG_FILE"
    _install_log "failed stage=${INSTALL_STAGE:-unknown} rc=${1:-1}"
}

# 统一 PROJECT_DIR / SCRIPT_DIR（兼容历史入口）
# 约定：PROJECT_DIR 为项目根目录；SCRIPT_DIR 为 $PROJECT_DIR/scripts
_normalize_project_and_script_dir() {
    if [ -n "${PROJECT_DIR:-}" ] && [ -d "$PROJECT_DIR" ]; then
        SCRIPT_DIR="$PROJECT_DIR/scripts"
        export PROJECT_DIR SCRIPT_DIR
        return 0
    fi

    if [ -n "${SCRIPT_DIR:-}" ] && [ -d "$SCRIPT_DIR" ]; then
        case "$SCRIPT_DIR" in
            */scripts)
                PROJECT_DIR="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)"
                ;;
            *)
                PROJECT_DIR="$SCRIPT_DIR"
                SCRIPT_DIR="$PROJECT_DIR/scripts"
                ;;
        esac
        export PROJECT_DIR SCRIPT_DIR
        return 0
    fi

    return 1
}

# fail-fast：校验统一入口布局，确保路径真相源存在
_require_common_layout() {
    if [ -z "${PROJECT_DIR:-}" ] || [ ! -d "$PROJECT_DIR" ]; then
        print_error "PROJECT_DIR 无效，无法继续"
        return 1
    fi
    SCRIPT_DIR="$PROJECT_DIR/scripts"
    if [ ! -d "$SCRIPT_DIR" ]; then
        print_error "scripts 目录不存在: $SCRIPT_DIR"
        return 1
    fi
    export PROJECT_DIR SCRIPT_DIR
    return 0
}

_normalize_project_and_script_dir || :
_require_common_layout || return 1

# 将目录加入 PATH（若目录存在且未包含）
_prepend_path_if_dir() {
    local DIR
    DIR="$1"
    [ -n "$DIR" ] || return 1
    [ -d "$DIR" ] || return 1

    case ":$PATH:" in
        *":$DIR:"*) ;;
        *) export PATH="$DIR:$PATH" ;;
    esac

    return 0
}

# 获取 Python user base 的 bin 路径
_get_python_user_base_bin() {
    local USER_BASE
    USER_BASE=""

    if command -v python3 >/dev/null 2>&1; then
        USER_BASE=$(python3 -m site --user-base 2>/dev/null)
    elif command -v python >/dev/null 2>&1; then
        USER_BASE=$(python -m site --user-base 2>/dev/null)
    fi

    if [ -n "$USER_BASE" ]; then
        printf '%s/bin\n' "$USER_BASE"
    fi
}

# 确保 uv 可执行在 PATH 中，并可被 command -v 发现
_resolve_uv_path() {
    local USER_BASE_BIN

    if command -v uv >/dev/null 2>&1; then
        return 0
    fi

    _prepend_path_if_dir "$HOME/.local/bin"
    if command -v uv >/dev/null 2>&1; then
        return 0
    fi

    USER_BASE_BIN=$(_get_python_user_base_bin)
    _prepend_path_if_dir "$USER_BASE_BIN"
    if command -v uv >/dev/null 2>&1; then
        return 0
    fi

    return 1
}

# uv 路径兜底
if ! _resolve_uv_path; then
    :
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

    if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
        TMP_FILE=$(mktemp)
        jq --arg path "$UV_PATH" '.uv_path = $path' "$RUNTIME_FILE" > "$TMP_FILE" && \
            mv "$TMP_FILE" "$RUNTIME_FILE"
    fi
}

# 检测可用的 pip 命令
_detect_pip_cmd() {
    if command -v pip3 >/dev/null 2>&1; then
        echo "pip3"
    elif command -v pip >/dev/null 2>&1; then
        echo "pip"
    fi
}

# 固定 PyPI 镜像源（label|index-url|trusted-host）
_install_pypi_sources() {
    cat <<'EOF'
pypi|https://pypi.org/simple|pypi.org
aliyun|https://mirrors.aliyun.com/pypi/simple/|mirrors.aliyun.com
tuna|https://pypi.tuna.tsinghua.edu.cn/simple/|pypi.tuna.tsinghua.edu.cn
EOF
}

# 安装失败摘要日志
_log_install_fail() {
    # $1: stage, $2: source, $3: cmd_summary, $4: exit_code
    local STAGE SOURCE CMD_SUMMARY EXIT_CODE
    STAGE="$1"
    SOURCE="$2"
    CMD_SUMMARY="$3"
    EXIT_CODE="$4"

    printf '[install-fail][%s] source=%s cmd="%s" exit_code=%s\n' \
        "$STAGE" "${SOURCE:-na}" "$CMD_SUMMARY" "$EXIT_CODE" >> "$INSTALL_LOG_FILE"
}

# 脚本失败摘要日志
_log_script_fail() {
    # $1: stage, $2: cmd_summary, $3: exit_code
    local STAGE CMD_SUMMARY EXIT_CODE
    STAGE="$1"
    CMD_SUMMARY="$2"
    EXIT_CODE="$3"

    printf '[script-fail][%s] source=%s cmd="%s" exit_code=%s\n' \
        "$STAGE" "na" "$CMD_SUMMARY" "$EXIT_CODE" >> "$INSTALL_LOG_FILE"
}

# 通用 pip 多源执行器（自动附加 -i + --trusted-host）
_run_pip_install_with_mirrors() {
    # $1: stage, $2: pip_cmd, $3...: pip 基础参数
    local STAGE PIP_CMD LABEL INDEX_URL HOST RC CMD_SUMMARY
    STAGE="$1"
    PIP_CMD="$2"
    shift 2

    CMD_SUMMARY="$PIP_CMD $* -i <index> --trusted-host <host>"

    while IFS='|' read -r LABEL INDEX_URL HOST; do
        [ -n "$LABEL" ] || continue

        "$PIP_CMD" "$@" -i "$INDEX_URL" --trusted-host "$HOST" 2>/dev/null
        RC=$?
        if [ "$RC" -eq 0 ]; then
            _install_log "stage=$STAGE source=$LABEL success"
            return 0
        fi

        _log_install_fail "$STAGE" "$LABEL" "$CMD_SUMMARY" "$RC"
    done <<EOF
$(_install_pypi_sources)
EOF

    return 1
}

# 通用 uv 多源执行器（自动附加 --index-url + --allow-insecure-host）
_run_uv_with_pypi_sources() {
    # $1: stage, $2...: uv 基础参数
    local STAGE LABEL INDEX_URL HOST RC CMD_SUMMARY
    STAGE="$1"
    shift

    CMD_SUMMARY="uv $* --index-url <index> --allow-insecure-host <host>"

    while IFS='|' read -r LABEL INDEX_URL HOST; do
        [ -n "$LABEL" ] || continue

        uv "$@" --index-url "$INDEX_URL" --allow-insecure-host "$HOST" 2>/dev/null
        RC=$?
        if [ "$RC" -eq 0 ]; then
            _install_log "stage=$STAGE source=$LABEL success"
            return 0
        fi

        _log_install_fail "$STAGE" "$LABEL" "$CMD_SUMMARY" "$RC"
    done <<EOF
$(_install_pypi_sources)
EOF

    return 1
}

# pip 升级前置（失败记录但不阻断）
_upgrade_pip_before_uv_install() {
    # $1: pip 命令
    local PIP_CMD
    PIP_CMD="$1"
    [ -n "$PIP_CMD" ] || return 1

    _run_pip_install_with_mirrors "pip-upgrade" "$PIP_CMD" install --upgrade pip --user
}

# 多来源安装 uv
# 返回: 0 成功, 1 失败
install_uv_multi_source() {
    local PIP_CMD RC
    PIP_CMD="$(_detect_pip_cmd)"

    # 先尝试 pip --user 升级（失败只记录，不阻断后续安装）
    if ! command -v uv >/dev/null 2>&1 && [ -n "$PIP_CMD" ]; then
        if ! _upgrade_pip_before_uv_install "$PIP_CMD"; then
            _install_log "stage=pip-upgrade all-sources-failed"
        fi
    fi

    # pip 升级后若 uv 已可用，直接成功返回
    if command -v uv >/dev/null 2>&1; then
        _resolve_uv_path
        return 0
    fi

    # 方式一：pip --user + 固定镜像回退
    if ! command -v uv >/dev/null 2>&1 && [ -n "$PIP_CMD" ]; then
        print_warning "尝试 pip 安装 uv（固定镜像回退，--user）..."
        if _run_pip_install_with_mirrors "uv-install" "$PIP_CMD" install uv --quiet --user --break-system-packages; then
            _resolve_uv_path
            command -v uv >/dev/null 2>&1
            return $?
        fi
    fi

    # 方式二：官方安装脚本（推荐，无需 Python）
    print_warning "尝试官方脚本安装"
    if curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh 2>/dev/null | sh; then
        if _resolve_uv_path && command -v uv >/dev/null 2>&1; then
            return 0
        fi
        _log_script_fail "uv-install-script" "curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh" 127
    else
        RC=$?
        _log_script_fail "uv-install-script" "curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh" "$RC"
    fi

    # 方式三：conda/mamba
    if ! command -v uv >/dev/null 2>&1; then
        if command -v mamba >/dev/null 2>&1; then
            print_warning "尝试 mamba 安装 uv..."
            if mamba install -c conda-forge uv -y --quiet 2>/dev/null; then
                if _resolve_uv_path && command -v uv >/dev/null 2>&1; then
                    return 0
                fi
                _log_script_fail "uv-install-mamba" "mamba install -c conda-forge uv -y --quiet" 127
            else
                RC=$?
                _log_script_fail "uv-install-mamba" "mamba install -c conda-forge uv -y --quiet" "$RC"
            fi
        elif command -v conda >/dev/null 2>&1; then
            print_warning "尝试 conda 安装 uv..."
            if conda install -c conda-forge uv -y --quiet 2>/dev/null; then
                if _resolve_uv_path && command -v uv >/dev/null 2>&1; then
                    return 0
                fi
                _log_script_fail "uv-install-conda" "conda install -c conda-forge uv -y --quiet" 127
            else
                RC=$?
                _log_script_fail "uv-install-conda" "conda install -c conda-forge uv -y --quiet" "$RC"
            fi
        fi
    fi

    # 方式四：brew（macOS）
    if ! command -v uv >/dev/null 2>&1 && [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        print_warning "尝试 brew install uv..."
        if brew install uv 2>/dev/null; then
            if _resolve_uv_path && command -v uv >/dev/null 2>&1; then
                return 0
            fi
            _log_script_fail "uv-install-brew" "brew install uv" 127
        else
            RC=$?
            _log_script_fail "uv-install-brew" "brew install uv" "$RC"
        fi
    fi

    return 1
}

# 检查并安装 uv（完整流程）
# 返回: 0 成功, 1 失败
check_and_install_uv() {
    local UV_PATH RUNTIME_FILE TMP_FILE

    _set_lazy_init_result_if_unset "pending"

    if _is_in_package_manager_cache && ! _is_pnpm_global_install; then
        _set_lazy_init_result "skipped-cache"
        return 0
    fi

    # 1. 从 runtime.json 读取 uv_path
    UV_PATH=$(_read_uv_path_from_runtime)
    if [ -n "$UV_PATH" ] && [ -x "$UV_PATH" ]; then
        export PATH="$(dirname "$UV_PATH"):$PATH"
        _set_lazy_init_result "ready"
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
        _set_lazy_init_result "ready"
        return 0
    fi

    # 3. 多来源安装
    if install_uv_multi_source; then
        print_success "uv 安装成功"
        _save_uv_path_to_runtime "$(command -v uv)"
        _set_lazy_init_result "installed"
        return 0
    fi

    _set_lazy_init_result "uv-install-failed"
    return 1
}

# 检查字符串是否为纯数字
_is_numeric() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

# remote-claude 初始化块标记
REMOTE_CLAUDE_INIT_BEGIN='# >>> remote-claude init >>>'
REMOTE_CLAUDE_INIT_END='# <<< remote-claude init <<<'

# 获取 shell rc 候选文件（按扫描顺序）
_get_shell_rc_candidates() {
    printf '%s\n' "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"
}

# 获取 shell 配置文件路径（POSIX 兼容）
# 基于 SHELL 与文件存在性选择写入目标，未知 shell 回退到 ~/.profile
get_shell_rc() {
    case "${SHELL:-}" in
        */zsh)
            [ -f "$HOME/.zshrc" ] && { echo "$HOME/.zshrc"; return 0; }
            echo "$HOME/.profile"
            return 0
            ;;
        */bash)
            [ -f "$HOME/.bashrc" ] && { echo "$HOME/.bashrc"; return 0; }
            [ -f "$HOME/.bash_profile" ] && { echo "$HOME/.bash_profile"; return 0; }
            echo "$HOME/.profile"
            return 0
            ;;
        *)
            echo "$HOME/.profile"
            return 0
            ;;
    esac
}

# 在候选 rc 中查找完整标记块（begin/end 成对）
_find_valid_remote_claude_init_rc() {
    local rc begin_count end_count
    for rc in $(_get_shell_rc_candidates); do
        [ -f "$rc" ] || continue
        begin_count=$(grep -cF "$REMOTE_CLAUDE_INIT_BEGIN" "$rc" 2>/dev/null || echo 0)
        end_count=$(grep -cF "$REMOTE_CLAUDE_INIT_END" "$rc" 2>/dev/null || echo 0)
        if [ "$begin_count" -gt 0 ] && [ "$begin_count" = "$end_count" ]; then
            echo "$rc"
            return 0
        fi
    done
    return 1
}

# 检查候选 rc 中是否已存在 remote-claude 初始化块（仅计完整块）
has_remote_claude_init_in_any_rc() {
    _find_valid_remote_claude_init_rc >/dev/null 2>&1
}

# 在 rc 中写入/更新 remote-claude 初始化块（全局查重 + 单文件 upsert）
upsert_remote_claude_init_block() {
    local body target rc tmp_file
    body="$1"

    rc=$(_find_valid_remote_claude_init_rc 2>/dev/null || true)
    if [ -n "$rc" ]; then
        tmp_file=$(mktemp)
        awk -v begin="$REMOTE_CLAUDE_INIT_BEGIN" -v end="$REMOTE_CLAUDE_INIT_END" -v body="$body" '
            $0==begin {print begin; print body; in_block=1; next}
            $0==end {print end; in_block=0; next}
            !in_block {print}
        ' "$rc" > "$tmp_file" && mv "$tmp_file" "$rc"
        return $?
    fi

    target=$(get_shell_rc)
    [ -f "$target" ] || : > "$target"
    {
        printf '\n%s\n' "$REMOTE_CLAUDE_INIT_BEGIN"
        printf '%s\n' "$body"
        printf '%s\n' "$REMOTE_CLAUDE_INIT_END"
    } >> "$target"
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
    printf '\n'
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '%b\n' "${GREEN}$1${NC}"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '\n'
}

# 检测是否在包管理器缓存目录中
# 缓存目录中的安装不应该执行初始化
_is_in_package_manager_cache() {
    # pnpm 缓存路径、npm 缓存路径、yarn 缓存路径、通用 node_modules 缓存标识
    case "$SCRIPT_DIR" in
        */.pnpm/*/node_modules/*|*/.pnpm-store/*|*/.store/*/node_modules/*|*/node_modules/.pnpm/*|\
        */.pnpm-global/*|\
        */_cacache/*|*/.npm/*|*/.npm-cache/*|\
        */.yarn/cache/*|*/.yarn/cache|\
        */node_modules/.cache/*|*/.cache/node_modules/*)
            return 0
            ;;
    esac
    return 1
}

# 记录惰性初始化结果，供入口脚本和测试读取
_set_lazy_init_result() {
    LAZY_INIT_RESULT="$1"
    export LAZY_INIT_RESULT
}

# 仅在结果尚未设置时写入默认惰性初始化结果
_set_lazy_init_result_if_unset() {
    if [ -z "${LAZY_INIT_RESULT:-}" ]; then
        _set_lazy_init_result "$1"
    fi
}

# 检测是否为 pnpm 全局安装
# pnpm 全局安装需要正常初始化（不同于缓存）
# 返回: 0 是 pnpm 全局安装, 1 不是
_is_pnpm_global_install() {
    case "$SCRIPT_DIR" in
        */Library/pnpm/global/*/node_modules/*|*/.local/share/pnpm/global/*/node_modules/*|*/AppData/Local/pnpm/global/*/node_modules/*)
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

# 计算文件 SHA-256 摘要
_hash_file_sha256() {
    local target_file output digest rc
    target_file="$1"

    if command -v sha256sum >/dev/null 2>&1; then
        if output=$(sha256sum "$target_file" 2>/dev/null); then
            set -- $output
            [ -n "$1" ] || return 1
            printf '%s\n' "$1"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    if command -v shasum >/dev/null 2>&1; then
        if output=$(shasum -a 256 "$target_file" 2>/dev/null); then
            set -- $output
            [ -n "$1" ] || return 1
            printf '%s\n' "$1"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    if command -v openssl >/dev/null 2>&1; then
        if output=$(openssl dgst -sha256 "$target_file" 2>/dev/null); then
            digest=${output##* }
            [ -n "$digest" ] || return 1
            printf '%s\n' "$digest"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    if command -v cksum >/dev/null 2>&1; then
        if output=$(cksum "$target_file" 2>/dev/null); then
            set -- $output
            [ -n "$1" ] || return 1
            [ -n "$2" ] || return 1
            printf 'cksum:%s:%s\n' "$1" "$2"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    return 1
}

# 计算标准输入 SHA-256 摘要
_hash_stdin_sha256() {
    local output digest rc

    if command -v sha256sum >/dev/null 2>&1; then
        if output=$(sha256sum 2>/dev/null); then
            set -- $output
            [ -n "$1" ] || return 1
            printf '%s\n' "$1"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    if command -v shasum >/dev/null 2>&1; then
        if output=$(shasum -a 256 2>/dev/null); then
            set -- $output
            [ -n "$1" ] || return 1
            printf '%s\n' "$1"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    if command -v openssl >/dev/null 2>&1; then
        if output=$(openssl dgst -sha256 2>/dev/null); then
            digest=${output##* }
            [ -n "$digest" ] || return 1
            printf '%s\n' "$digest"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    if command -v cksum >/dev/null 2>&1; then
        if output=$(cksum 2>/dev/null); then
            set -- $output
            [ -n "$1" ] || return 1
            [ -n "$2" ] || return 1
            printf 'cksum:%s:%s\n' "$1" "$2"
            return 0
        else
            rc=$?
            [ "$rc" -eq 127 ] || return 1
        fi
    fi

    return 1
}

# 获取依赖指纹文件路径
_get_dependency_fingerprint_path() {
    local project_dir
    project_dir="$1"
    printf '%s/.venv/.deps-fingerprint\n' "$project_dir"
}

# 计算依赖指纹（基于 pyproject.toml 与 uv.lock 内容）
_compute_dependency_fingerprint() {
    local project_dir pyproject_file lock_file pyproject_hash lock_hash manifest
    project_dir="$1"
    pyproject_file="$project_dir/pyproject.toml"
    lock_file="$project_dir/uv.lock"

    pyproject_hash="missing"
    lock_hash="missing"

    if [ -f "$pyproject_file" ]; then
        pyproject_hash=$(_hash_file_sha256 "$pyproject_file") || return 1
    fi

    if [ -f "$lock_file" ]; then
        lock_hash=$(_hash_file_sha256 "$lock_file") || return 1
    fi

    manifest=$(printf 'pyproject.toml=%s\nuv.lock=%s\n' "$pyproject_hash" "$lock_hash")
    printf '%s' "$manifest" | _hash_stdin_sha256
}

# 比较依赖指纹是否一致
_dependency_fingerprint_matches() {
    local project_dir fingerprint_file current_fingerprint stored_fingerprint
    project_dir="$1"
    fingerprint_file=$(_get_dependency_fingerprint_path "$project_dir")

    [ -f "$fingerprint_file" ] || return 1

    current_fingerprint=$(_compute_dependency_fingerprint "$project_dir") || return 1
    stored_fingerprint=$(tr -d '\r\n' < "$fingerprint_file" 2>/dev/null)

    [ -n "$stored_fingerprint" ] || return 1
    [ "$stored_fingerprint" = "$current_fingerprint" ]
}

# 写回依赖指纹
_write_dependency_fingerprint() {
    local project_dir venv_dir fingerprint_file current_fingerprint tmp_file
    project_dir="$1"
    venv_dir="$project_dir/.venv"
    fingerprint_file=$(_get_dependency_fingerprint_path "$project_dir")

    [ -d "$venv_dir" ] || return 1

    current_fingerprint=$(_compute_dependency_fingerprint "$project_dir") || return 1

    tmp_file=$(mktemp "$venv_dir/.deps-fingerprint.tmp.XXXXXX" 2>/dev/null || mktemp) || return 1
    if ! printf '%s\n' "$current_fingerprint" > "$tmp_file"; then
        rm -f "$tmp_file"
        return 1
    fi

    if ! mv "$tmp_file" "$fingerprint_file"; then
        rm -f "$tmp_file"
        return 1
    fi

    return 0
}

# 检查是否需要重新同步依赖
# 条件：.venv 不存在，或依赖指纹变化
# 返回: 0 需要同步, 1 不需要
_needs_sync() {
    local venv_dir project_dir

    if _is_in_package_manager_cache && ! _is_pnpm_global_install; then
        return 1
    fi

    # 使用 PROJECT_DIR（如果已设置）或从 SCRIPT_DIR 推导
    project_dir="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)}"
    [ -z "$project_dir" ] && return 1

    venv_dir="$project_dir/.venv"

    # .venv 不存在，需要同步
    [ ! -d "$venv_dir" ] && return 0

    # 指纹一致，不需要同步
    if _dependency_fingerprint_matches "$project_dir"; then
        return 1
    fi

    # 指纹不存在或变化，需要同步
    return 0
}

# 延迟初始化失败时输出统一恢复命令并保持非 0 退出
handle_lazy_init_failure() {
    local exit_code project_dir setup_script
    exit_code=${1:-$?}
    [ -z "$exit_code" ] && exit_code=1
    [ "$exit_code" -eq 0 ] && exit_code=1
    case "$exit_code" in
        126|127)
            exit_code=127
            ;;
    esac

    project_dir="${PROJECT_DIR:-}"
    if [ -z "$project_dir" ]; then
        case "$SCRIPT_DIR" in
            */scripts)
                project_dir=$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)
                ;;
            *)
                project_dir="$SCRIPT_DIR"
                ;;
        esac
    fi

    setup_script="$project_dir/scripts/setup.sh"

    print_error "Python 环境初始化失败，请执行以下命令恢复："
    printf 'sh %s --npm --lazy\n' "$setup_script" >&2
    if [ -n "${INSTALL_LOG_FILE:-}" ]; then
        printf '安装日志: %s\n' "$INSTALL_LOG_FILE" >&2
    fi
    exit "$exit_code"
}

# 延迟初始化：检测是否需要运行 setup.sh
# 条件：.venv 不存在 或依赖指纹变化 且不在缓存目录中
_lazy_init() {
    _set_lazy_init_result_if_unset "pending"

    # 防止重入：如果已经在 setup.sh 流程中，跳过
    case "${_LAZY_INIT_RUNNING:-}" in
        1)
            _set_lazy_init_result "skipped-reentrant"
            return 0
            ;;
    esac

    # 如果在包管理器缓存中，跳过初始化（但 pnpm 全局安装需要初始化）
    if _is_in_package_manager_cache && ! _is_pnpm_global_install; then
        _set_lazy_init_result "skipped-cache"
        return 0
    fi

    # 首先确保 uv 可用（设计文档要求：uv 不可用但可恢复 → 先安装/定位 uv）
    if ! command -v uv >/dev/null 2>&1; then
        print_warning "未找到 uv，正在安装..."
        if ! check_and_install_uv; then
            print_error "uv 安装失败，请手动安装后重试"
            print_info "  curl -LsSf https://astral.sh/uv/install.sh | sh"
            print_info "  或访问 https://docs.astral.sh/uv/getting-started/installation/"
            return 1
        fi
        print_success "uv 安装成功"
    fi

    # 如果需要同步（venv 不存在或依赖变更），执行初始化
    if _needs_sync; then
        local project_dir
        project_dir="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)}"
        [ -z "$project_dir" ] && return 1

        echo "检测到依赖变更，正在更新 Python 环境..."
        cd "$project_dir"
        local setup_rc shell_cmd
        shell_cmd=$(command -v sh 2>/dev/null || true)
        [ -n "$shell_cmd" ] || shell_cmd="/bin/sh"
        # 设置标记防止重入
        _LAZY_INIT_RUNNING=1
        export _LAZY_INIT_RUNNING
        _set_lazy_init_result "sync-triggered"
        if [ -x "$SCRIPT_DIR/setup.sh" ] || [ -f "$SCRIPT_DIR/setup.sh" ]; then
            "$shell_cmd" "$SCRIPT_DIR/setup.sh" --npm --lazy
            setup_rc=$?
        else
            setup_rc=127
        fi
        _LAZY_INIT_RUNNING=0
        export _LAZY_INIT_RUNNING
        if [ "$setup_rc" -ne 0 ]; then
            _set_lazy_init_result "sync-failed"
            case "$setup_rc" in
                126|127)
                    return 1
                    ;;
            esac
            return "$setup_rc"
        fi
        _set_lazy_init_result "sync-completed"
        if ! _write_dependency_fingerprint "$project_dir"; then
            print_warning "依赖指纹写入失败，后续启动可能触发重复同步"
            _install_log "stage=lazy-init fingerprint-write-failed project=$project_dir"
        fi
        return 0
    fi

    _set_lazy_init_result "no-sync-needed"
    return 0
}

if [ "${LAZY_INIT_DISABLE_AUTO_RUN:-0}" != "1" ]; then
    _lazy_init
    lazy_init_rc=$?
    if [ "$lazy_init_rc" -ne 0 ]; then
        handle_lazy_init_failure "$lazy_init_rc"
    fi
fi
