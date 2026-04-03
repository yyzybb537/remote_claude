#!/bin/bash
# Docker 测试诊断脚本
# 测试失败时自动收集诊断信息

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 结果目录
RESULTS_DIR="/home/testuser/test-results"

# 诊断目录
DIAG_DIR="$RESULTS_DIR/diagnosis"
mkdir -p "$DIAG_DIR"

log_info() {
    echo -e "${BLUE}[DIAG]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[DIAG]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 收集会话与启动诊断信息
collect_session_diagnostics() {
    print_header "收集会话与启动诊断"

    local session_log="$DIAG_DIR/session.txt"
    echo "=== remote-claude list ===" > "$session_log"

    if uv run remote-claude list >> "$session_log" 2>&1; then
        echo "" >> "$session_log"
    else
        echo "remote-claude list 执行失败" >> "$session_log"
        echo "" >> "$session_log"
    fi

    echo "=== /tmp/remote-claude ===" >> "$session_log"
    ls -la /tmp/remote-claude >> "$session_log" 2>&1 || echo "/tmp/remote-claude 不存在" >> "$session_log"
    echo "" >> "$session_log"

    echo "=== tmux list-sessions ===" >> "$session_log"
    tmux list-sessions >> "$session_log" 2>&1 || echo "没有活跃的 tmux 会话" >> "$session_log"
    echo "" >> "$session_log"

    echo "=== startup.log (tail -100) ===" >> "$session_log"
    if [ -f "$HOME/.remote-claude/startup.log" ]; then
        tail -100 "$HOME/.remote-claude/startup.log" >> "$session_log" 2>&1
    else
        echo "startup.log 不存在" >> "$session_log"
    fi

    log_success "会话与启动诊断已收集"
}

# 收集系统信息
collect_system_info() {
    print_header "收集系统信息"

    echo "=== 系统信息 ===" > "$DIAG_DIR/system.txt"
    uname -a >> "$DIAG_DIR/system.txt"
    echo "" >> "$DIAG_DIR/system.txt"

    echo "=== OS Release ===" >> "$DIAG_DIR/system.txt"
    cat /etc/os-release >> "$DIAG_DIR/system.txt"
    echo "" >> "$DIAG_DIR/system.txt"

    echo "=== 环境变量 ===" >> "$DIAG_DIR/system.txt"
    env | grep -E '(PATH|NODE|NPM|PYTHON|UV|HOME)' | sort >> "$DIAG_DIR/system.txt"

    log_success "系统信息已收集"
}

# 收集依赖版本
collect_dependency_versions() {
    print_header "收集依赖版本"

    echo "=== 依赖版本 ===" > "$DIAG_DIR/dependencies.txt"

    echo "Python:" >> "$DIAG_DIR/dependencies.txt"
    uv run python3 --version 2>&1 >> "$DIAG_DIR/dependencies.txt"
    echo "" >> "$DIAG_DIR/dependencies.txt"

    echo "Node.js:" >> "$DIAG_DIR/dependencies.txt"
    node --version 2>&1 >> "$DIAG_DIR/dependencies.txt"
    echo "" >> "$DIAG_DIR/dependencies.txt"

    echo "npm:" >> "$DIAG_DIR/dependencies.txt"
    npm --version 2>&1 >> "$DIAG_DIR/dependencies.txt"
    echo "" >> "$DIAG_DIR/dependencies.txt"

    echo "uv:" >> "$DIAG_DIR/dependencies.txt"
    uv --version 2>&1 >> "$DIAG_DIR/dependencies.txt"
    echo "" >> "$DIAG_DIR/dependencies.txt"

    echo "tmux:" >> "$DIAG_DIR/dependencies.txt"
    tmux -V 2>&1 >> "$DIAG_DIR/dependencies.txt"
    echo "" >> "$DIAG_DIR/dependencies.txt"

    if command -v claude &> /dev/null; then
        echo "Claude CLI:" >> "$DIAG_DIR/dependencies.txt"
        claude --version 2>&1 >> "$DIAG_DIR/dependencies.txt"
        echo "" >> "$DIAG_DIR/dependencies.txt"
    fi

    log_success "依赖版本已收集"
}

# 收集 npm 包信息
collect_npm_info() {
    print_header "收集 npm 包信息"

    echo "=== npm 全局包列表 ===" > "$DIAG_DIR/npm.txt"
    npm list -g --depth=0 2>&1 >> "$DIAG_DIR/npm.txt"
    echo "" >> "$DIAG_DIR/npm.txt"

    if [ -d "$RESULTS_DIR/npm-install" ]; then
        echo "=== 本地安装包列表 ===" >> "$DIAG_DIR/npm.txt"
        cd "$RESULTS_DIR/npm-install"
        npm list --depth=0 2>&1 >> "$DIAG_DIR/npm.txt"
    fi

    log_success "npm 包信息已收集"
}

# 收集 Python 包信息
collect_python_info() {
    print_header "收集 Python 包信息"

    echo "=== Python 包列表 ===" > "$DIAG_DIR/python.txt"

    # 项目虚拟环境包（uv 管理）
    echo "--- 项目依赖 ---" >> "$DIAG_DIR/python.txt"
    uv pip list 2>&1 >> "$DIAG_DIR/python.txt"
    echo "" >> "$DIAG_DIR/python.txt"

    log_success "Python 包信息已收集"
}

# 收集文件结构
collect_file_structure() {
    print_header "收集文件结构"

    if [ -d "$RESULTS_DIR/npm-install/node_modules/remote-claude" ]; then
        cd "$RESULTS_DIR/npm-install/node_modules/remote-claude"

        echo "=== 目录结构 ===" > "$DIAG_DIR/structure.txt"
        find . -type f -o -type d | sort >> "$DIAG_DIR/structure.txt"
        echo "" >> "$DIAG_DIR/structure.txt"

        echo "=== 关键目录列表 ===" >> "$DIAG_DIR/structure.txt"
        ls -la >> "$DIAG_DIR/structure.txt"
        echo "" >> "$DIAG_DIR/structure.txt"

        echo "=== server/ 目录 ===" >> "$DIAG_DIR/structure.txt"
        ls -la server/ 2>&1 >> "$DIAG_DIR/structure.txt"
        echo "" >> "$DIAG_DIR/structure.txt"

        echo "=== lark_client/ 目录 ===" >> "$DIAG_DIR/structure.txt"
        ls -la lark_client/ 2>&1 >> "$DIAG_DIR/structure.txt"
        echo "" >> "$DIAG_DIR/structure.txt"

        echo "=== bin/ 目录 ===" >> "$DIAG_DIR/structure.txt"
        ls -la bin/ 2>&1 >> "$DIAG_DIR/structure.txt"
    fi

    log_success "文件结构已收集"
}

# 复制测试日志
collect_test_logs() {
    print_header "复制测试日志"

    local results_dir="/home/testuser/test-results"

    if [ -d "$results_dir" ]; then
        # 复制所有日志文件（排除 diagnosis 目录）
        find "$results_dir" -maxdepth 1 -type f -name "*.log" -o -name "*.txt" | while read -r log; do
            if [ "$(basename "$log")" != "test_report.md" ]; then
                cp -v "$log" "$DIAG_DIR/"
            fi
        done
    fi

    log_success "测试日志已复制"
}

# 收集错误信息
collect_errors() {
    print_header "收集错误信息"

    local error_log="$DIAG_DIR/errors.txt"
    echo "=== 错误汇总 ===" > "$error_log"

    # 从测试日志中提取错误
    if [ -f "/home/testuser/test-results/npm_install.log" ]; then
        echo "--- npm_install.log ---" >> "$error_log"
        grep -i error /home/testuser/test-results/npm_install.log >> "$error_log" || true
        echo "" >> "$error_log"
    fi

    if [ -f "/home/testuser/test-results/pack.log" ]; then
        echo "--- pack.log ---" >> "$error_log"
        grep -i error /home/testuser/test-results/pack.log >> "$error_log" || true
        echo "" >> "$error_log"
    fi

    # 从单元测试日志中提取错误
    local results_dir="/home/testuser/test-results"
    if [ -d "$results_dir" ]; then
        echo "--- 单元测试失败汇总 ---" >> "$error_log"
        local test_logs=$(find "$results_dir" -maxdepth 1 -name "test_*.log" -o -name "test_*.txt" 2>/dev/null)
        if [ -n "$test_logs" ]; then
            for test_log in $test_logs; do
                local matches
                matches=$(grep -i "fail\|error\|traceback\|assertion" "$test_log" 2>/dev/null) || true
                if [ -n "$matches" ]; then
                    echo ">>> $(basename "$test_log") <<<" >> "$error_log"
                    echo "$matches" >> "$error_log"
                    echo "" >> "$error_log"
                fi
            done
        else
            echo "未找到单元测试日志文件" >> "$error_log"
        fi
        echo "" >> "$error_log"
    fi

    # 检查缺失的依赖
    echo "--- 依赖检查 ---" >> "$error_log"
    echo "检查关键依赖..." >> "$error_log"

    if ! uv run python3 -c "import lark_oapi" 2>&1; then
        echo "✗ lark_oapi 未安装" >> "$error_log"
    fi

    if ! uv run python3 -c "import dotenv" 2>&1; then
        echo "✗ python-dotenv 未安装" >> "$error_log"
    fi

    if ! uv run python3 -c "import pyte" 2>&1; then
        echo "✗ pyte 未安装" >> "$error_log"
    fi

    log_success "错误信息已收集"
}

# 生成诊断报告
generate_diagnosis_report() {
    print_header "生成诊断报告"

    local report="$DIAG_DIR/diagnosis_report.md"

    cat > "$report" << EOF
# Docker 测试诊断报告

**生成时间**: $(date '+%Y-%m-%d %H:%M:%S')

## 系统信息

\`\`\`
$(cat "$DIAG_DIR/system.txt")
\`\`\`

## 依赖版本

\`\`\`
$(cat "$DIAG_DIR/dependencies.txt")
\`\`\`

## npm 包信息

\`\`\`
$(cat "$DIAG_DIR/npm.txt")
\`\`\`

## Python 包信息

\`\`\`
$(cat "$DIAG_DIR/python.txt")
\`\`\`

## 文件结构

\`\`\`
$(cat "$DIAG_DIR/structure.txt")
\`\`\`

## 会话与启动诊断

```\n$(cat "$DIAG_DIR/session.txt")\n```

## 错误汇总

\`\`\`
$(cat "$DIAG_DIR/errors.txt")
\`\`\`

## 测试日志

- npm_install.log
- pack.log
- commands.txt
- *.log (单元测试日志)

## 建议

根据上述信息，请检查：

1. **依赖安装**: Python 和 Node.js 版本是否满足要求
2. **npm 包**: npm install 是否成功，关键文件是否存在
3. **Python 环境**: .venv 虚拟环境是否正确创建
4. **测试失败**: 查看具体的单元测试日志

## 联系支持

如无法自行解决，请将 \`$DIAG_DIR\` 目录打包并发送给开发者。

---

*此报告由 Docker 诊断脚本自动生成*
EOF

    log_success "诊断报告已生成: $report"
}

# 打包诊断信息
pack_diagnosis() {
    print_header "打包诊断信息"

    local tarball="/home/testuser/test-results/diagnosis.tar.gz"

    cd /home/testuser/test-results
    tar -czf "$tarball" diagnosis/

    local size=$(du -h "$tarball" | cut -f1)
    log_success "诊断信息已打包: $tarball ($size)"
}

# 主流程
main() {
    log_info "开始收集诊断信息..."

    collect_system_info
    collect_dependency_versions
    collect_npm_info
    collect_python_info
    collect_file_structure
    collect_session_diagnostics
    collect_test_logs
    collect_errors
    generate_diagnosis_report
    pack_diagnosis

    print_header "诊断完成"
    log_info "诊断信息已保存到: $DIAG_DIR"
    log_info "打包文件: /home/testuser/test-results/diagnosis.tar.gz"
    log_info "请将此文件发送给开发者进行进一步分析"
}

# 运行主流程
main "$@"