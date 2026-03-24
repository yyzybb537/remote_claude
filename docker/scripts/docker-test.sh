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

# 结果目录
RESULTS_DIR="/home/testuser/test-results"

mkdir -p "$RESULTS_DIR"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
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

# 从项目 .python-version 读取 Python 版本
PYTHON_VERSION_FILE="/project/.python-version"
if [ ! -f "$PYTHON_VERSION_FILE" ]; then
    echo -e "${RED}[ERROR]${NC} 未找到 .python-version 文件: $PYTHON_VERSION_FILE"
    exit 1
fi
PYTHON_VERSION=$(cat "$PYTHON_VERSION_FILE")
if [ -z "$PYTHON_VERSION" ]; then
    echo -e "${RED}[ERROR]${NC} .python-version 文件为空"
    exit 1
fi

# 步骤 1：环境检查
check_environment() {
    print_header "步骤 1：环境检查"

    # uv 版本
    if uv --version &> /dev/null; then
        UV_VERSION=$(uv --version)
        log_success "uv: $UV_VERSION"
    else
        log_error "未找到 uv"
        return 1
    fi

    # Python 版本
    if uv run --python "$PYTHON_VERSION" python3 --version &> /dev/null; then
        PYTHON_VER=$(uv run --python "$PYTHON_VERSION" python3 --version)
        log_success "Python: $PYTHON_VER"
    else
        log_error "未找到 Python, 输出为：$(uv run --python "$PYTHON_VERSION" python3 --version)"
        return 1
    fi

    # tmux 版本
    if tmux -V &> /dev/null; then
        TMUX_VERSION=$(tmux -V)
        log_success "tmux: $TMUX_VERSION"
    else
        log_error "未找到 tmux"
        return 1
    fi

    # Node.js 版本
    if node --version &> /dev/null; then
        NODE_VERSION=$(node --version)
        log_success "Node.js: $NODE_VERSION"
    else
        log_error "未找到 Node.js"
        return 1
    fi

    # npm 版本
    if npm --version &> /dev/null; then
        NPM_VERSION=$(npm --version)
        log_success "npm: $NPM_VERSION"
    else
        log_error "未找到 npm"
        return 1
    fi

    # Claude CLI（必需）
    if claude --version &> /dev/null; then
        log_success "Claude CLI: $(claude --version 2>&1 | head -1)"
    else
        log_error "未找到 Claude CLI"
        return 1
    fi

    # Codex CLI（必需）
    if codex --version &> /dev/null; then
        log_success "Codex CLI: $(codex --version 2>&1 | head -1)"
    else
        log_error "未找到 Codex CLI"
        return 1
    fi
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
        log_success "npm 包打包成功: $PACK_FILE,  $VERSION"
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

    # 在 test-results 目录下创建安装目录（产物持久化到外部）
    local install_dir="$RESULTS_DIR/npm-install"
    rm -rf "$install_dir"
    mkdir -p "$install_dir"
    cd "$install_dir"

    log_info "在临时目录安装 npm 包..."

    # 使用 CN 镜像地址，可选
    if npm install "$pack_file" --registry=https://registry.npmmirror.com  > "$RESULTS_DIR/npm_install.log" 2>&1; then
        log_success "npm install 成功"
    else
        log_error "npm install 失败"
        cat "$RESULTS_DIR/npm_install.log"
        return 1
    fi

    # 将安装目录路径写入文件（供后续步骤使用）
    echo "$install_dir" > "$RESULTS_DIR/install_dir.txt"

    # 设置全局变量（供后续步骤使用）
    INSTALL_DIR="$install_dir"
}

# 步骤 4：验证 postinstall 执行
verify_postinstall() {
    print_header "步骤 4：验证 postinstall 执行"

    local install_dir="$1"
    local package_dir="$install_dir/node_modules/remote-claude"
    cd "$package_dir"

    # 验证 .venv 目录（在 node_modules/remote-claude/ 下，而非 npm-install/ 下）
    if [ -d "$package_dir/.venv" ]; then
        log_success ".venv 虚拟环境已创建"
    else
        log_error ".venv 虚拟环境未创建"
        return 1
    fi

    # 验证 pyproject.toml 存在
    if [ -f "pyproject.toml" ]; then
        log_success "pyproject.toml 存在"
    else
        log_error "pyproject.toml 不存在"
        return 1
    fi

    # 检查 Python 依赖
    log_info "检查 Python 依赖安装..."

    if uv run --python "$PYTHON_VERSION" python3 -c "import lark_oapi" 2>/dev/null; then
        log_success "lark-oapi 已安装"
    else
        log_error "lark-oapi 未安装"
        return 1
    fi

    if uv run --python "$PYTHON_VERSION" python3 -c "import dotenv" 2>/dev/null; then
        log_success "python-dotenv 已安装"
    else
        log_error "python-dotenv 未安装"
        return 1
    fi

    if uv run --python "$PYTHON_VERSION" python3 -c "import pyte" 2>/dev/null; then
        log_success "pyte 已安装"
    else
        log_error "pyte 未安装"
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

    # 5-2：验证 check-env.sh 不再交互阻塞
    log_info "验证 check-env.sh 不阻塞..."
    if timeout 5 bash scripts/check-env.sh . > "$RESULTS_DIR/check_env.log" 2>&1; then
        log_success "check-env.sh 在 5s 内正常返回（不阻塞）"
        report "✓ check-env.sh 不阻塞"
    else
        local rc=$?
        if [ $rc -eq 124 ]; then
            log_error "check-env.sh 超时（5s）—— 仍在等待交互输入"
            report "✗ check-env.sh 超时阻塞"
            return 1
        else
            log_error "check-env.sh 返回非零（rc=$rc）"
            return 1
        fi
    fi

    # 5-3：验证 lark start 不会无限卡死（凭证无效应快速报错）
    log_info "验证 lark start 不会无限卡死（限 20s）..."
    timeout 20 uv run remote-claude lark start > "$RESULTS_DIR/lark_start.log" 2>&1
    local rc=$?
    if [ $rc -eq 124 ]; then
        log_error "lark start 超时（20s）—— 存在无限阻塞问题"
        return 1
    else
        # 非 124 均可接受（0=成功/已在运行，非零=凭证错误快速退出，两者都 OK）
        log_success "lark start 在 20s 内退出（rc=$rc），不存在无限卡死"
    fi

    # 5-4：验证 remote-claude start 能成功启动会话
    # 判断逻辑：
    #   - start = 启动 server（tmux）+ attach client，正常运行时会阻塞等待 Claude 交互
    #   - 若 20s 内自然退出 → 说明启动失败，捕获日志报错
    #   - 若 20s 超时仍在运行 → 再检查 socket 和 remote-claude list，均正常才算成功
    log_info "验证 remote-claude start 能成功启动会话（预期 20s 内不退出）..."

    local session="docker-test-session"
    local socket_path="/tmp/remote-claude/${session}.sock"
    # 清理可能残留的同名会话
    uv run remote-claude kill "$session" > /dev/null 2>&1 || true
    tmux kill-session -t "rc-$session" 2>/dev/null || true

    # 启动会话，限时 20s；正常情况下 Claude 运行中，timeout 会触发（rc=124）
    timeout 20 uv run remote-claude start "$session" \
        > "$RESULTS_DIR/start_session.log" 2>&1
    local rc=$?

    if [ $rc -ne 124 ]; then
        # 20s 内自然退出 → 启动失败，输出日志诊断
        log_error "start 命令在 20s 内意外退出（rc=$rc），启动失败"
        report "✗ start 命令意外退出（rc=$rc）"
        log_info "=== start_session.log ==="
        cat "$RESULTS_DIR/start_session.log"
        # 打印 server 日志辅助诊断
        local server_log="$HOME/.remote-claude/startup.log"
        if [ -f "$server_log" ]; then
            log_info "=== startup.log（最后 20 行）==="
            tail -20 "$server_log"
        fi
        tmux kill-session -t "rc-$session" 2>/dev/null || true
        return 1
    fi

    # timeout 触发（rc=124）→ 命令仍在运行，检查 socket 和会话列表
    log_info "start 命令 20s 后仍在运行（符合预期），检查 socket 和会话列表..."

    if [ ! -S "$socket_path" ]; then
        log_error "socket 文件不存在: $socket_path"
        report "✗ start 命令：socket 未创建"
        tmux kill-session -t "rc-$session" 2>/dev/null || true
        return 1
    fi
    log_success "socket 文件已存在: $socket_path"

    local list_out
    list_out=$(uv run remote-claude list 2>&1)
    if echo "$list_out" | grep -q "$session"; then
        log_success "remote-claude list 中可见会话: $session"
        report "✓ start 命令成功：socket 就绪，会话可见"
    else
        log_error "remote-claude list 中未找到会话: $session"
        log_info "list 输出：$list_out"
        report "✗ start 命令：会话在 list 中不可见"
        tmux kill-session -t "rc-$session" 2>/dev/null || true
        return 1
    fi

    # 清理测试会话
    uv run remote-claude kill "$session" > /dev/null 2>&1 || true

    # 5-5：负面测试——自定义命令配置为不存在的命令，验证测试能检测到启动失败
    log_info "负面测试：配置不存在的命令应导致 start 在 20s 内失败退出..."

    # 在 config.json 中设置无效命令
    local config_file="$HOME/.remote-claude/config.json"
    if command -v jq &> /dev/null && [[ -f "$config_file" ]]; then
        local tmp_file=$(mktemp)
        jq '.ui_settings.custom_commands.enabled = true | .ui_settings.custom_commands.commands[0].command = "claudeyy"' \
            "$config_file" > "$tmp_file" && mv "$tmp_file" "$config_file"
    fi

    # 使用不同的会话名，避免与正常测试冲突
    local negative_session="docker-negative-test"
    # 清理同名残留会话
    uv run remote-claude kill "$negative_session" > /dev/null 2>&1 || true
    tmux kill-session -t "rc-$negative_session" 2>/dev/null || true

    timeout 20 uv run remote-claude start "$negative_session" \
        > "$RESULTS_DIR/start_fail.log" 2>&1
    local fail_rc=$?

    # 还原 config.json（恢复默认命令）
    if command -v jq &> /dev/null && [[ -f "$config_file" ]]; then
        local tmp_file=$(mktemp)
        jq '.ui_settings.custom_commands.enabled = false | .ui_settings.custom_commands.commands[0].command = "claude"' \
            "$config_file" > "$tmp_file" && mv "$tmp_file" "$config_file"
    fi

    # 清理负面测试会话
    uv run remote-claude kill "$negative_session" > /dev/null 2>&1 || true
    tmux kill-session -t "rc-$negative_session" 2>/dev/null || true

    if [ $fail_rc -eq 124 ]; then
        log_error "负面测试失败：无效命令配置时 start 未在 20s 内退出"
        log_info "=== start_fail.log ==="
        cat "$RESULTS_DIR/start_fail.log"
        report "✗ 负面测试：无效命令未被检测到"
        return 1
    elif [ $fail_rc -eq 0 ]; then
        log_error "负面测试失败：无效命令配置时 start 返回 rc=0（不应成功）"
        report "✗ 负面测试：无效命令返回成功"
        return 1
    else
        log_success "负面测试通过：无效命令导致 start 在 20s 内以 rc=$fail_rc 退出"
        report "✓ 负面测试：启动失败被正确检测（rc=$fail_rc）"
    fi

    # 5-6：验证 remote-claude start --cli codex 能成功启动 Codex 会话
    log_info "验证 remote-claude start --cli codex 能成功启动会话（预期 20s 内不退出）..."

    local codex_session="docker-codex-session"
    local codex_socket="/tmp/remote-claude/${codex_session}.sock"
    uv run remote-claude kill "$codex_session" > /dev/null 2>&1 || true
    tmux kill-session -t "rc-$codex_session" 2>/dev/null || true

    timeout 20 uv run remote-claude start "$codex_session" --cli codex \
        > "$RESULTS_DIR/start_codex.log" 2>&1
    local codex_rc=$?

    if [ $codex_rc -ne 124 ]; then
        log_error "Codex start 在 20s 内意外退出（rc=$codex_rc），启动失败"
        report "✗ Codex start 意外退出（rc=$codex_rc）"
        log_info "=== start_codex.log ==="
        cat "$RESULTS_DIR/start_codex.log"
        local server_log="$HOME/.remote-claude/startup.log"
        if [ -f "$server_log" ]; then
            log_info "=== startup.log（最后 20 行）==="
            tail -20 "$server_log"
        fi
        tmux kill-session -t "rc-$codex_session" 2>/dev/null || true
        return 1
    fi

    log_info "Codex start 20s 后仍在运行（符合预期），检查 socket 和会话列表..."

    if [ ! -S "$codex_socket" ]; then
        log_error "Codex socket 不存在: $codex_socket"
        report "✗ Codex start：socket 未创建"
        tmux kill-session -t "rc-$codex_session" 2>/dev/null || true
        return 1
    fi
    log_success "Codex socket 已存在: $codex_socket"

    local codex_list_out
    codex_list_out=$(uv run remote-claude list 2>&1)
    if echo "$codex_list_out" | grep -q "$codex_session"; then
        log_success "remote-claude list 中可见 Codex 会话: $codex_session"
        report "✓ Codex start 成功：socket 就绪，会话可见"
    else
        log_error "remote-claude list 中未找到 Codex 会话: $codex_session"
        log_info "list 输出：$codex_list_out"
        report "✗ Codex start：会话在 list 中不可见"
        tmux kill-session -t "rc-$codex_session" 2>/dev/null || true
        return 1
    fi

    uv run remote-claude kill "$codex_session" > /dev/null 2>&1 || true
}

# 步骤 6：测试基本命令
test_basic_commands() {
    print_header "步骤 6：测试基本命令"

    local install_dir="$1"
    cd "$install_dir/node_modules/remote-claude"

    # 测试 remote-claude --help
    log_info "测试 remote-claude --help..."
    if uv run remote-claude --help > "$RESULTS_DIR/cmd_help.log" 2>&1; then
        if grep -q "双端共享 Claude CLI 工具" "$RESULTS_DIR/cmd_help.log"; then
            log_success "remote-claude --help 输出正确"
        else
            log_error "remote-claude --help 输出异常"
            return 1
        fi
    else
        log_error "remote-claude --help 执行失败"
        return 1
    fi

    # 测试 remote-claude list
    log_info "测试 remote-claude list..."
    if uv run remote-claude list > "$RESULTS_DIR/cmd_list.log" 2>&1; then
        log_success "remote-claude list 执行成功"
    else
        log_error "remote-claude list 执行失败"
        return 1
    fi

    # 检查 cla 脚本语法
    log_info "检查 cla 脚本语法..."
    if bash -n "bin/cla" 2>/dev/null; then
        log_success "bin/cla 脚本语法正确"
    else
        log_error "bin/cla 脚本语法错误"
        return 1
    fi

    # 验证 cla 脚本中的关键逻辑
    log_info "验证 cla 脚本中的关键逻辑..."

    if grep -q "uv run" "bin/cla"; then
        log_success "cla 脚本包含 uv run"
    else
        log_error "cla 脚本缺少 uv run"
        return 1
    fi

    if grep -q "remote-claude" "bin/cla"; then
        log_success "cla 脚本包含 remote-claude"
    else
        log_error "cla 脚本缺少 remote-claude"
        return 1
    fi

    if grep -q "lark start" "bin/cla"; then
        log_success "cla 脚本包含 lark start"
    else
        log_error "cla 脚本缺少 lark start"
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
        "client/client.py"
        "utils/protocol.py"
        "lark_client/main.py"
        "init.sh"
        "pyproject.toml"
        "resources/defaults/.env.example"
        "resources/defaults/config.default.json"
        "resources/defaults/runtime.default.json"
    )

    local missing_files=()
    for file in "${critical_files[@]}"; do
        if [ -f "$file" ]; then
            log_success "文件存在: $file"
        else
            log_error "文件缺失: $file"
            missing_files+=("$file")
        fi
    done

    if [ ${#missing_files[@]} -eq 0 ]; then
        log_success "所有关键文件检查通过"
        return 0
    else
        log_error "缺失 ${#missing_files[@]} 个关键文件"
        return 1
    fi
}

# 步骤 8：执行独立单元测试
run_unit_tests() {
    print_header "步骤 8：执行独立单元测试"

    local install_dir="$1"
    cd "$install_dir/node_modules/remote-claude"

    # 核心测试列表（失败终止）
    local core_tests=(
        "tests/test_session_truncate.py"
        "tests/test_runtime_config.py"
        "tests/test_biz_enum.py"
        "tests/test_custom_commands.py"
    )

    # 非核心测试列表（失败继续）
    local non_core_tests=(
        "tests/test_stream_poller.py"
        "tests/test_card_interaction.py"
        "tests/test_list_display.py"
        "tests/test_log_level.py"
        "tests/test_disconnected_state.py"
        "tests/test_renderer.py"
        "tests/lark_client/test_mock_output.py"
        "tests/lark_client/test_cjk_width.py"
        "tests/lark_client/test_full_simulation.py"
    )

    local core_failed=0
    local non_core_failed=0
    local unit_passed=0
    local unit_total=0

    # 执行核心测试
    log_info "执行核心测试（失败将终止）..."
    for test in "${core_tests[@]}"; do
        if [ -f "$test" ]; then
            unit_total=$((unit_total + 1))
            log_info "运行核心测试: $test"
            if uv run python3 "$test" > "$RESULTS_DIR/$(basename "$test" .py).log" 2>&1; then
                log_success "核心测试通过: $test"
                unit_passed=$((unit_passed + 1))
            else
                log_error "核心测试失败: $test"
                core_failed=$((core_failed + 1))
            fi
        else
            log_error "核心测试文件不存在: $test"
            core_failed=$((core_failed + 1))
        fi
    done

    # 核心测试失败则终止
    if [ $core_failed -gt 0 ]; then
        log_error "$core_failed 个核心测试失败，终止测试流程"
        return 1
    fi

    # 执行非核心测试
    log_info "执行非核心测试（失败继续）..."
    for test in "${non_core_tests[@]}"; do
        if [ -f "$test" ]; then
            unit_total=$((unit_total + 1))
            log_info "运行非核心测试: $test"
            if uv run python3 "$test" > "$RESULTS_DIR/$(basename "$test" .py).log" 2>&1; then
                log_success "非核心测试通过: $test"
                unit_passed=$((unit_passed + 1))
            else
                log_warning "非核心测试失败: $test（继续执行）"
                non_core_failed=$((non_core_failed + 1))
            fi
        else
            log_error "非核心测试文件不存在: $test"
            non_core_failed=$((non_core_failed + 1))
        fi
    done

    # 汇总单元测试结果
    log_info "单元测试汇总: 通过 $unit_passed/$unit_total"
    report "📊 单元测试汇总: 通过 $unit_passed/$unit_total（核心失败: $core_failed，非核心失败: $non_core_failed）"

    if [ $non_core_failed -gt 0 ]; then
        log_warning "$non_core_failed 个非核心测试失败"
        return 0  # 非核心测试失败不终止
    fi

    return 0
}

# 步骤 9：生成测试报告
generate_report() {
    print_header "步骤 9：生成测试报告"

    local report_file="$RESULTS_DIR/test_report.md"

    cat > "$report_file" << EOF
# Docker 测试报告

**生成时间**: $(date '+%Y-%m-%d %H:%M:%S')
**测试版本**: $(cat "$RESULTS_DIR/version.txt" 2>/dev/null || echo "unknown")

## 测试摘要

- 通过: $PASSED
- 失败: $FAILED
- 警告: $WARNINGS
- 总计: $((PASSED + FAILED))

**总体结果**: $([ $FAILED -eq 0 ] && echo "✅ 通过" || echo "❌ 失败")

## 测试详情

$TEST_REPORT

## 测试日志

详细日志位于 \`$RESULTS_DIR/\` 目录：
- \`pack.log\` — npm 打包日志
- \`npm_install.log\` — npm 安装日志
- \`test_*.log\` — 单元测试日志

## 诊断信息

如测试失败，请运行 \`docker/scripts/docker-diagnose.sh\` 收集诊断信息。

---

*此报告由 Docker 测试脚本自动生成*
EOF

    log_success "测试报告已生成: $report_file"
}

# 步骤 10：清理
cleanup() {
    print_header "步骤 10：清理"

    log_info "保持容器运行状态"

    local cid="$HOSTNAME"
    echo ""
    echo -e "${GREEN}容器保持运行，操作命令：${NC}"
    echo -e "  进入容器: docker exec -it ${cid} /bin/bash"
    echo -e "  查看报告: docker exec ${cid} cat /home/testuser/test-results/test_report.md"
    echo -e "  停止容器: docker stop ${cid}"
    echo ""

    log_success "清理完成"

    # 保持容器运行，直到手动 docker stop
    sleep infinity
}

# 输出最终结果
print_results() {
    print_header "测试完成"
    log_info "通过: $PASSED, 失败: $FAILED, 警告: $WARNINGS"

    if [ $FAILED -eq 0 ]; then
        log_success "所有测试通过！✅"
    else
        log_error "存在 $FAILED 个失败测试 ❌"
    fi

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
    PACK_FILE_PATH=$(ls -t /tmp/remote-claude-*.tgz 2>/dev/null | head -1)
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
        log_warning "env/启动超时测试失败，继续执行..."
    fi

    # 步骤 6：测试基本命令
    if ! test_basic_commands "$INSTALL_DIR"; then
        log_warning "基本命令测试失败，继续执行..."
    fi

    # 步骤 7：文件完整性检查
    if ! check_file_integrity "$INSTALL_DIR"; then
        log_warning "文件完整性检查失败，继续执行..."
    fi

    # 步骤 8：执行独立单元测试
    if ! run_unit_tests "$INSTALL_DIR"; then
        log_warning "核心单元测试失败，终止测试"
        exit 1
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