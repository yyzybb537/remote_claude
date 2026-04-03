#!/bin/sh
#
# Remote Claude 安装引导脚本
# 负责准备 uv / Python 运行时，并调用 scripts/setup.sh 完成完整初始化
# 用户无需预装 Python
#
# 用法：curl -fsSL https://raw.githubusercontent.com/.../scripts/install.sh | sh
# 或：./scripts/install.sh
# POSIX sh 兼容，支持 sh/bash/zsh
#

set -e

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

# 检查并安装 uv（使用 _common.sh 中的函数）
check_and_install_uv_install() {
    ensure_uv_or_hint "检查 uv 包管理器"
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
    setup_script="$PROJECT_DIR/scripts/setup.sh"

    if [ ! -f "$setup_script" ]; then
        print_error "未找到 setup.sh 脚本: $setup_script"
        return 1
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
        run_npm_postinstall || return $?
    else
        run_setup_script || return $?
    fi

    print_success "setup.sh 执行完成"
}

# 显示完成信息
show_completion() {
    print_header "安装完成"

    shell_rc=$(get_shell_rc)

    printf '\n'
    print_quick_commands_table
    printf '%b\n' "  ${GREEN}remote-claude${NC} - 管理工具"
    print_info "公开入口统一为 shell launcher（如 /usr/local/bin/remote-claude 或 ~/.local/bin/remote-claude）；项目 .venv 仅作内部运行时，不会加入用户 PATH"
    printf '\n'
    print_shell_reload_hint "$shell_rc"
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

    # npm postinstall 场景的缓存跳过逻辑由 run_npm_postinstall() 收敛处理
    if _is_in_package_manager_cache && ! $NPM_MODE; then
        echo "检测到缓存安装，跳过初始化"
        _install_stage "cache-skip"
        exit 0
    fi

    print_banner "Remote Claude 安装引导" "准备运行时并调用 setup.sh 完成初始化"

    # 延迟模式：只运行必要步骤
    if $LAZY_MODE; then
        _install_stage "uv"
        check_and_install_uv_install || { rc=$?; _log_script_fail "uv" "check_and_install_uv_install" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
        _install_stage "deps"
        setup_virtual_env || { rc=$?; _log_script_fail "deps" "setup_virtual_env" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
        _install_stage "lazy-done"
        print_success "Python 环境初始化完成"
        return 0
    fi

    _install_stage "precheck"
    require_supported_os || { rc=$?; _log_script_fail "precheck" "require_supported_os" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    _install_stage "uv"
    check_and_install_uv_install || { rc=$?; _log_script_fail "uv" "check_and_install_uv_install" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    _install_stage "deps"
    setup_virtual_env || { rc=$?; _log_script_fail "deps" "setup_virtual_env" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    _install_stage "verify"
    verify_installation || { rc=$?; _log_script_fail "verify" "verify_installation" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    _install_stage "setup"
    run_init_script || { rc=$?; _log_script_fail "setup" "run_init_script" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
    _install_stage "done"
    show_completion
}

# 运行主流程
main "$@"
