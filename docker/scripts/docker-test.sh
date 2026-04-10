#!/bin/bash
# Docker 测试主脚本
# 验证 npm 包在不同环境下的完整性和功能可用性

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 统计变量
PASSED=0
FAILED=0
WARNINGS=0
TEST_REPORT=""
TEST_INTERRUPTED=0

handle_interrupt() {
    TEST_INTERRUPTED=1
    log_warning "检测到中断信号，停止测试执行..."
}

trap 'handle_interrupt' INT TERM

# 结果目录
RESULTS_DIR="/home/testuser/test-results"
INSTALL_DIR="/home/testuser/test-npm-install"
KEEP_CONTAINER_ALIVE="${KEEP_CONTAINER_ALIVE:-1}"
mkdir -p "$RESULTS_DIR"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

check_command() {
    local display_name="$1"
    local version_cmd="$2"
    local value

    if value=$(eval "$version_cmd" 2>/dev/null | head -1); then
        log_success "$display_name: $value"
    else
        log_error "$display_name: 未找到"
        return 1
    fi
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASSED=$((PASSED + 1))
    report "✓ $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAILED=$((FAILED + 1))
    report "✗ $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    WARNINGS=$((WARNINGS + 1))
    report "⚠ $1"
}

report() {
    TEST_REPORT+="$1\n"
}

# 打印函数
print_header() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# ============== 会话测试辅助函数 ==============

# 清理会话和相关资源
# 参数: $1 = session_name
cleanup_session() {
    local session="$1"
    uv run python3 remote_claude.py kill "$session" > /dev/null 2>&1 || true
    tmux kill-session -t "rc-$session" 2>/dev/null || true
}

# 输出诊断日志
# 参数: $1 = session_name, $2 = log_file_path (可选)
print_session_diagnostics() {
    local session="$1"
    local log_file="$2"

    if [[ -n "$log_file" && -f "$log_file" ]]; then
        log_info "=== $(basename "$log_file") ==="
        cat "$log_file"
    fi

    local server_log="$HOME/.remote-claude/startup.log"
    if [[ -f "$server_log" ]]; then
        log_info "=== startup.log（最后 30 行）==="
        tail -30 "$server_log"
    fi

    log_info "=== tmux 会话状态 ==="
    tmux list-sessions 2>&1 || echo "没有活跃的 tmux 会话"

    log_info "=== socket 目录状态 ==="
    ls -la /tmp/remote-claude/ 2>&1 || echo "socket 目录不存在"

    local tmux_name="rc-${session}"
    if tmux has-session -t "$tmux_name" 2>/dev/null; then
        log_info "=== tmux 会话 $tmux_name 输出 ==="
        tmux capture-pane -t "$tmux_name" -p 2>&1 || echo "无法捕获输出"
    fi
}

# 验证会话启动成功
# 参数: $1 = session_name, $2 = timeout_seconds, $3 = cli_type (claude/codex)
verify_session_startup() {
    local session="$1"
    local timeout_sec="${2:-20}"
    local cli_type="${3:-claude}"
    local socket_path="/tmp/remote-claude/${session}.sock"
    local log_file="$RESULTS_DIR/start_${session}.log"

    cleanup_session "$session"

    local start_cmd="uv run python3 remote_claude.py start '$session'"
    if [[ "$cli_type" == "codex" ]]; then
        start_cmd="uv run python3 remote_claude.py start '$session' --launcher Codex"
    fi

    log_info "启动 $cli_type 会话 '$session'（限时 ${timeout_sec}s）..."

    set +e
    timeout "$timeout_sec" bash -c "$start_cmd" > "$log_file" 2>&1
    local rc=$?
    set -e

    if [[ $rc -ne 0 && $rc -ne 124 ]]; then
        log_info "$cli_type 会话 '$session' 启动命令退出码: $rc；继续基于 socket 与 list 状态判定"
    fi

    log_info "验证 $cli_type 会话 '$session' 的 socket 与 list 状态..."

    if [[ ! -S "$socket_path" ]]; then
        log_error "socket 文件不存在: $socket_path"
        print_session_diagnostics "$session" "$log_file"
        cleanup_session "$session"
        return 1
    fi
    log_success "socket 已创建: $socket_path"

    local list_out
    list_out=$(uv run python3 remote_claude.py list 2>&1)
    if echo "$list_out" | grep -q "$session"; then
        log_success "会话 '$session' 在 list 中可见"
        return 0
    else
        log_error "会话 '$session' 在 list 中不可见"
        log_info "list 输出：$list_out"
        print_session_diagnostics "$session" "$log_file"
        cleanup_session "$session"
        return 1
    fi
}

# 步骤 1：环境检查
check_environment() {
    print_header "步骤 1：环境检查"

    check_command "Python" "python3 --version" || return 1
    check_command "uv" "uv --version" || return 1
    check_command "tmux" "tmux -V" || return 1
    check_command "Node.js" "node --version" || return 1
    check_command "npm" "npm --version" || return 1
    check_command "Claude CLI" "claude --version" || return 1
    check_command "Codex CLI" "codex --version" || return 1
}

# 步骤 2：打包 npm 包
pack_npm_package() {
    print_header "步骤 2：打包 npm 包"

    # 复制项目到可写目录（因为 /project 是只读挂载）
    local temp_project="/tmp/project-copy"
    rm -rf "$temp_project"
    cp -r /project "$temp_project"
    cd "$temp_project"

    if npm pack > "$RESULTS_DIR/pack.log" 2>&1; then
        PACK_FILE=$(ls -t remote-claude-*.tgz 2>/dev/null | head -1)
        VERSION=$(echo "$PACK_FILE" | sed 's/remote-claude-\(.*\)\.tgz/\1/')
        log_success "npm 包打包成功: $PACK_FILE"
        log_info "版本: $VERSION"
        echo "$VERSION" > "$RESULTS_DIR/version.txt"
        cp "$PACK_FILE" "$RESULTS_DIR"
        mv "$PACK_FILE" /tmp/
    else
        log_error "npm pack 失败"
        cat "$RESULTS_DIR/pack.log"
        return 1
    fi
}

# 步骤 3：模拟用户安装
simulate_install() {
    print_header "步骤 3：模拟用户安装"

    local pack_file="$1"

    # 创建临时安装目录
    local install_dir="$INSTALL_DIR"
    rm -rf "$install_dir"
    mkdir -p "$install_dir"
    cd "$install_dir"

    log_info "在临时目录安装 npm 包..."

    if npm install "$pack_file" > "$RESULTS_DIR/npm_install.log" 2>&1; then
        log_success "npm install 成功"
        report "✓ npm install 成功"
    else
        log_error "npm install 失败"
        report "✗ npm install 失败"
        cat "$RESULTS_DIR/npm_install.log"
        return 1
    fi

    # 将安装目录路径写入文件（供后续步骤使用）
    echo "$install_dir" > "$RESULTS_DIR/install_dir.txt"
    # 导出到外部（供 main 函数使用）
    INSTALL_DIR="$install_dir"
}

# 步骤 4：验证 postinstall 执行
verify_postinstall() {
    print_header "步骤 4：验证 postinstall 执行"

    local install_dir="$1"
    cd "$install_dir/node_modules/remote-claude"

    # 验证 .venv 目录
    if [ -d ".venv" ]; then
        log_success ".venv 虚拟环境已创建"
        report "✓ .venv 虚拟环境已创建"
    else
        log_error ".venv 虚拟环境未创建"
        report "✗ .venv 虚拟环境未创建"
        return 1
    fi

    # 验证 pyproject.toml 存在
    if [ -f "pyproject.toml" ]; then
        log_success "pyproject.toml 存在"
        report "✓ pyproject.toml 存在"
    else
        log_error "pyproject.toml 不存在"
        report "✗ pyproject.toml 不存在"
        return 1
    fi

    # 检查 Python 依赖（使用 .venv 中的 Python）
    log_info "检查 Python 依赖安装..."

    if .venv/bin/python -c "import lark_oapi" 2>/dev/null; then
        log_success "lark-oapi 已安装"
        report "✓ lark-oapi 已安装"
    else
        log_error "lark-oapi 未安装"
        report "✗ lark-oapi 未安装"
        return 1
    fi

    if .venv/bin/python -c "import dotenv" 2>/dev/null; then
        log_success "python-dotenv 已安装"
        report "✓ python-dotenv 已安装"
    else
        log_error "python-dotenv 未安装"
        report "✗ python-dotenv 未安装"
        return 1
    fi

    if .venv/bin/python -c "import pyte" 2>/dev/null; then
        log_success "pyte 已安装"
        report "✓ pyte 已安装"
    else
        log_error "pyte 未安装"
        report "✗ pyte 未安装"
        return 1
    fi
}

# 步骤 5：配置 mock .env 并测试启动超时行为
test_env_and_startup() {
    print_header "步骤 5：env 配置与启动超时测试"

    local install_dir="$1"
    local env_file="$HOME/.remote-claude/.env"
    mkdir -p "$HOME/.remote-claude"

    # 5-1：写入 mock 凭证（格式合法但不能真正连接飞书）
    cat > "$env_file" << 'EOF'
FEISHU_APP_ID=cli_docker_test_mock
FEISHU_APP_SECRET=docker_test_secret_mock
EOF
    log_success "已创建 mock .env: $env_file"
    report "✓ mock .env 已创建"

    cd "$install_dir/node_modules/remote-claude"

    # 5-2：验证 check-env.sh 可在本地启动场景被显式跳过
    log_info "验证 check-env.sh 在本地启动场景可跳过飞书检查..."
    if REMOTE_CLAUDE_REQUIRE_FEISHU=0 timeout 5 sh scripts/check-env.sh > "$RESULTS_DIR/check_env_skip.log" 2>&1; then
        log_success "check-env.sh 在 REMOTE_CLAUDE_REQUIRE_FEISHU=0 下 5s 内返回成功"
        report "✓ check-env.sh 支持跳过飞书检查"
    else
        local rc=$?
        if [ $rc -eq 124 ]; then
            log_error "check-env.sh 超时（5s）—— 跳过飞书检查时仍发生阻塞"
            report "✗ check-env.sh 跳过飞书检查时仍阻塞"
        else
            log_error "check-env.sh 在跳过飞书检查时返回非零（rc=$rc）"
            cat "$RESULTS_DIR/check_env_skip.log"
            report "✗ check-env.sh 跳过飞书检查失败（rc=$rc）"
        fi
        return 1
    fi

    # 5-3：验证 lark start 不会无限卡死（凭证无效应快速报错）
    log_info "验证 lark start 不会无限卡死（限 20s）..."
    set +e
    REMOTE_CLAUDE_NONINTERACTIVE=1 timeout 20 uv run python3 remote_claude.py lark start > "$RESULTS_DIR/lark_start.log" 2>&1
    local rc=$?
    set -e
    if [ $rc -eq 124 ]; then
        log_error "lark start 超时（20s）—— 存在无限阻塞问题"
        report "✗ lark start 超时（20s）"
        return 1
    else
        # 非 124 均可接受（0=成功/已在运行，非零=凭证错误快速退出，两者都 OK）
        log_success "lark start 在 20s 内退出（rc=$rc），不存在无限卡死"
        report "✓ lark start 不阻塞（rc=$rc）"
    fi

    # 5-4：验证 remote-claude start 能成功启动 Claude 会话
    local session="docker-test-session"
    if ! verify_session_startup "$session" 20 "claude"; then
        return 1
    fi
    cleanup_session "$session"

    # 5-5：验证 remote-claude start --launcher Codex 能成功启动 Codex 会话
    local codex_session="docker-codex-session"
    if ! verify_session_startup "$codex_session" 20 "codex"; then
        return 1
    fi
    cleanup_session "$codex_session"
}

# 步骤 6：测试基本命令
test_basic_commands() {
    print_header "步骤 6：测试基本命令"

    local install_dir="$1"
    cd "$install_dir/node_modules/remote-claude"

    # 测试 remote-claude --help
    log_info "测试 remote-claude --help..."
    if uv run python3 remote_claude.py --help > "$RESULTS_DIR/cmd_help.log" 2>&1; then
        if grep -q "usage: remote-claude" "$RESULTS_DIR/cmd_help.log"; then
            log_success "remote-claude --help 输出正确"
            report "✓ remote-claude --help 输出正确"
        else
            log_error "remote-claude --help 输出异常"
            report "✗ remote-claude --help 输出异常"
            return 1
        fi
    else
        log_error "remote-claude --help 执行失败"
        report "✗ remote-claude --help 执行失败"
        return 1
    fi

    # 测试 remote-claude list
    log_info "测试 remote-claude list..."
    if uv run python3 remote_claude.py list > "$RESULTS_DIR/cmd_list.log" 2>&1; then
        log_success "remote-claude list 执行成功"
        report "✓ remote-claude list 执行成功"
    else
        log_error "remote-claude list 执行失败"
        report "✗ remote-claude list 执行失败"
        return 1
    fi

    # 检查 cla 脚本语法
    log_info "检查 cla 脚本语法..."
    if bash -n "$install_dir/../bin/cla" 2>/dev/null; then
        log_success "bin/cla 脚本语法正确"
        report "✓ bin/cla 脚本语法正确"
    else
        log_error "bin/cla 脚本语法错误"
        report "✗ bin/cla 脚本语法错误"
        return 1
    fi

    # 验证 cla 脚本中的关键逻辑
    log_info "验证 cla 脚本中的关键逻辑..."

    if grep -q "_remote_claude_shortcut_help_or_main" "$install_dir/../bin/cla"; then
        log_success "cla 脚本通过共享快捷入口分发"
        report "✓ cla 脚本通过共享快捷入口分发"
    else
        log_error "cla 脚本缺少共享快捷入口"
        report "✗ cla 脚本缺少共享快捷入口"
        return 1
    fi
}

# 步骤 7：文件完整性检查
check_file_integrity() {
    print_header "步骤 7：文件完整性检查"

    local install_dir="$1"
    cd "$install_dir/node_modules/remote-claude"

    # 关键文件列表
    local critical_files=(
        "remote_claude.py"
        "server/server.py"
        "client/base_client.py"
        "utils/protocol.py"
        "lark_client/main.py"
        "scripts/setup.sh"
        "pyproject.toml"
        "resources/defaults/env.example"
    )

    local missing_files=()
    for file in "${critical_files[@]}"; do
        if [ -f "$file" ]; then
            log_success "文件存在: $file"
            report "✓ 文件存在: $file"
        else
            log_error "文件缺失: $file"
            report "✗ 文件缺失: $file"
            missing_files+=("$file")
        fi
    done

    if [ ${#missing_files[@]} -eq 0 ]; then
        log_success "所有关键文件检查通过"
        report "✓ 所有关键文件检查通过"
        return 0
    else
        log_error "缺失 ${#missing_files[@]} 个关键文件"
        report "✗ 缺失 ${#missing_files[@]} 个关键文件"
        return 1
    fi
}

# 步骤 8：生成测试报告
generate_report() {
    print_header "步骤 8：生成测试报告"

    local report_file="$RESULTS_DIR/test_report.md"

    cat > "$report_file" << EOF
# Docker 测试报告

**生成时间**: $(date '+%Y-%m-%d %H:%M:%S')
**测试版本**: $(cat "$RESULTS_DIR/version.txt" 2>/dev/null || echo "unknown")

## 测试摘要

- 通过: $PASSED
- 失败: $FAILED
- 总计: $((PASSED + FAILED))

**总体结果**: $([ $FAILED -eq 0 ] && echo "✅ 通过" || echo "❌ 失败")

## 环境信息

- 操作系统: $(uname -a)
- Python: $(python3 --version)
- Node.js: $(node --version)
- npm: $(npm --version)
- uv: $(uv --version)
- tmux: $(tmux -V)

## 测试详情

$TEST_REPORT

## 测试日志

- npm 打包: \`pack.log\`
- npm 安装: \`npm_install.log\`

## 诊断信息

如测试失败，请运行 \`docker/scripts/docker-diagnose.sh\` 收集诊断信息。

---

*此报告由 Docker 测试脚本自动生成*
EOF

    log_success "测试报告已生成: $report_file"
    report "✓ 测试报告已生成: $report_file"
}

# 步骤 8：验证卸载钩子
verify_uninstall_hook() {
    print_header "步骤 8：验证卸载钩子"

    local install_dir="$1"
    cd "$install_dir/node_modules/remote-claude"

    log_info "验证 uninstall hook 使用非交互模式..."
    if REMOTE_CLAUDE_NONINTERACTIVE=1 sh scripts/uninstall.sh > "$RESULTS_DIR/uninstall.log" 2>&1; then
        log_success "uninstall hook 非交互执行成功"
        report "✓ uninstall hook 非交互执行成功"
    else
        log_error "uninstall hook 执行失败"
        report "✗ uninstall hook 执行失败"
        cat "$RESULTS_DIR/uninstall.log"
        return 1
    fi
}

# 步骤 9：清理
cleanup() {
    print_header "步骤 9：清理"

    local cid="$HOSTNAME"
    if [[ "$KEEP_CONTAINER_ALIVE" != "1" ]]; then
        log_info "清理完成，容器将正常退出"
        return 0
    fi

    log_info "保持容器运行状态（Docker 模式下不自动退出）"
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}容器保持运行状态（Docker 模式下不自动退出）${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${GREEN}进入容器的命令：${NC}"
    echo -e "  docker exec -it ${cid} /bin/bash"
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${YELLOW}查看测试报告：${NC}"
    echo -e "  docker exec ${cid} bash -c 'cat /home/testuser/test-results/test_report.md'"
    echo ""
    echo -e "${YELLOW}查看安装目录结构：${NC}"
    echo -e "  docker exec ${cid} bash -c 'ls -la /home/testuser/test-npm-install/node_modules/remote-claude/'"
    echo ""
    echo -e "${YELLOW}手动运行测试：${NC}"
    echo -e "  docker exec ${cid} bash -c 'cd /project && docker/scripts/docker-test.sh'"
    echo ""
    echo -e "${YELLOW}停止容器：${NC}"
    echo -e "  docker stop ${cid}"
    echo ""

    log_success "清理完成（容器保持运行状态）"
    sleep infinity
}

# 输出最终结果
print_results() {
    print_header "测试完成"
    log_info "通过: $PASSED, 失败: $FAILED"

    if [ $FAILED -eq 0 ]; then
        log_success "所有测试通过！✅"
    else
        log_error "存在 $FAILED 个失败测试 ❌"
    fi

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  登录测试容器：${NC}"
    echo -e "  docker exec -it ${HOSTNAME} /bin/bash"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 主流程
main() {
    log_info "Docker 测试开始..."

    # 步骤 1：环境检查
    if ! check_environment; then
        log_error "环境检查失败，终止测试"
        exit 1
    fi

    # 步骤 2：打包 npm 包
    if ! pack_npm_package; then
        log_error "npm 包打包失败，终止测试"
        exit 1
    fi

    # 步骤 3：模拟用户安装
    PACK_FILE_PATH=$(ls /tmp/remote-claude-*.tgz 2>/dev/null | head -1)
    if [ -z "$PACK_FILE_PATH" ]; then
        log_error "找不到打包好的 .tgz 文件"
        exit 1
    fi
    if ! simulate_install "$PACK_FILE_PATH"; then
        log_error "npm install 失败，终止测试"
        exit 1
    fi

    # 步骤 4：验证 postinstall 执行
    if ! verify_postinstall "$INSTALL_DIR"; then
        log_error "postinstall 验证失败，终止测试"
        exit 1
    fi

    # 步骤 5：env 配置与启动超时测试
    if ! test_env_and_startup "$INSTALL_DIR"; then
        log_error "env/启动超时测试失败，继续执行..."
    fi

    # 步骤 6：测试基本命令
    if ! test_basic_commands "$INSTALL_DIR"; then
        log_error "基本命令测试失败，继续执行..."
    fi

    # 步骤 7：文件完整性检查
    if ! check_file_integrity "$INSTALL_DIR"; then
        log_error "文件完整性检查失败，继续执行..."
    fi

    # 步骤 8：验证卸载钩子
    if ! verify_uninstall_hook "$INSTALL_DIR"; then
        log_error "卸载钩子验证失败，继续执行..."
    fi

    # 步骤 9：生成测试报告
    generate_report

    # 输出最终结果
    print_results

    # 步骤 10：清理（打印操作提示，并保持容器运行）
    cleanup
}

# 运行主流程
main "$@"
