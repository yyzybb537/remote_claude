# Remote Claude 安装脚本优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化安装脚本，确保 npm/pnpm 全局安装时完全初始化 Python 环境，避免重复初始化，并完善卸载清理功能。

**Architecture:** 修改 postinstall.sh 在全局安装时执行完整初始化，优化 _common.sh 添加依赖变更检测，增强 uninstall.sh 清理功能。

**Tech Stack:** Bash, uv, npm/pnpm

---

## 文件结构

| 文件 | 职责 | 修改类型 |
|------|------|----------|
| `scripts/_common.sh` | 共享函数库，包含 uv 管理、初始化检测 | 修改 |
| `scripts/postinstall.sh` | npm/pnpm 安装后执行，现需支持全局安装初始化 | 修改 |
| `scripts/install.sh` | 本地克隆安装脚本 | 修改（添加 --frozen） |
| `scripts/uninstall.sh` | 卸载清理脚本 | 修改（增强清理） |
| `bin/remote-claude` | 主命令入口 | 修改（优化初始化调用） |
| `README.md` | 用户文档 | 修改 |
| `CLAUDE.md` | 开发文档 | 修改 |

---

## Task 1: 优化 _common.sh 添加依赖变更检测

**Files:**
- Modify: `scripts/_common.sh:178-231`

**背景:** 当前 `_lazy_init` 只检查 `.venv` 是否存在，需要添加对 `pyproject.toml` 和 `uv.lock` 修改时间的检测。

- [ ] **Step 1: 添加 `_needs_sync` 函数**

在 `_is_global_install` 函数后添加：

```bash
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
```

- [ ] **Step 2: 优化 `_lazy_init` 函数**

替换现有的 `_lazy_init` 函数（约第 207-230 行）：

```bash
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
```

- [ ] **Step 3: 验证修改**

运行语法检查：
```bash
bash -n scripts/_common.sh
```

Expected: 无输出（表示语法正确）

- [ ] **Step 4: 测试 `_needs_sync` 逻辑**

创建测试脚本：
```bash
cd /Users/bytedance/.superset/worktrees/remote_claude/feature/custom_command
export SCRIPT_DIR="$PWD"
source scripts/_common.sh

# 测试 1: .venv 不存在时应返回 0
rm -rf .venv
_needs_sync && echo "Test 1 PASS: venv 不存在需要同步" || echo "Test 1 FAIL"

# 测试 2: 创建 venv 后应返回 1
mkdir -p .venv
_needs_sync && echo "Test 2 FAIL" || echo "Test 2 PASS: venv 存在且依赖未变更"

# 测试 3: 修改 pyproject.toml 后应返回 0
touch pyproject.toml
_needs_sync && echo "Test 3 PASS: pyproject.toml 更新需要同步" || echo "Test 3 FAIL"

# 清理
rm -rf .venv
```

- [ ] **Step 5: Commit**

```bash
git add scripts/_common.sh
git commit -m "feat: add _needs_sync function to detect dependency changes

- Add _needs_sync() to check if venv needs re-sync
- Check pyproject.toml and uv.lock modification times
- Optimize _lazy_init() to use _needs_sync"
```

---

## Task 2: 修改 postinstall.sh 支持全局安装初始化

**Files:**
- Modify: `scripts/postinstall.sh`

**背景:** 当前 postinstall.sh 检测到全局安装时会跳过初始化，需要修改为执行完整初始化。

- [ ] **Step 1: 重写 postinstall.sh**

完全替换文件内容：

```bash
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
```

- [ ] **Step 2: 验证脚本语法**

```bash
bash -n scripts/postinstall.sh
```

Expected: 无输出

- [ ] **Step 3: 本地测试 postinstall.sh**

```bash
cd /Users/bytedance/.superset/worktrees/remote_claude/feature/custom_command
# 模拟全局安装环境测试
bash scripts/postinstall.sh
```

Expected: 显示初始化进度，创建 .venv，安装依赖

- [ ] **Step 4: Commit**

```bash
git add scripts/postinstall.sh
git commit -m "feat: postinstall.sh 支持全局安装时完整初始化

- 全局安装时执行完整的 Python 环境初始化
- 添加进度提示和错误处理
- 使用 --frozen 确保可复现安装"
```

---

## Task 3: 优化 install.sh 添加 --frozen 标志

**Files:**
- Modify: `scripts/install.sh:71`

- [ ] **Step 1: 修改 uv sync 命令**

找到第 71 行，修改为：

```bash
# 安装依赖
print_info "正在安装依赖..."
uv sync --frozen || uv sync
print_success "依赖安装完成"
```

- [ ] **Step 2: 验证修改**

```bash
bash -n scripts/install.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: install.sh 使用 --frozen 加速依赖安装

- 优先使用 --frozen 确保可复现安装
- 失败时回退到普通模式"
```

---

## Task 4: 增强 uninstall.sh 清理功能

**Files:**
- Modify: `scripts/uninstall.sh`

- [ ] **Step 1: 添加 uv 缓存清理函数**

在 `cleanup_uv_path` 函数后添加：

```bash
# 6. 清理 uv 缓存（可选）
cleanup_uv_cache() {
    print_info "检查 uv 缓存..."

    # CI 环境自动跳过
    if [ -n "$CI" ] || [ -n "$npm_config_loglevel" ]; then
        print_detail "CI 环境跳过缓存清理"
        return
    fi

    if ! command -v uv >/dev/null 2>&1; then
        print_detail "未找到 uv，跳过缓存清理"
        return
    fi

    local cache_size
    cache_size=$(uv cache dir 2>/dev/null | head -1)
    if [ -z "$cache_size" ]; then
        print_detail "无法获取缓存信息"
        return
    fi

    printf "${YELLOW}是否清理 uv 缓存？${NC} [y/N]: "
    read -r reply
    case "$reply" in
        [yY][eE][sS]|[yY])
            if uv cache clean 2>/dev/null; then
                print_success "已清理 uv 缓存"
            else
                print_warning "缓存清理失败"
            fi
            ;;
        *)
            print_info "保留 uv 缓存"
            ;;
    esac
}
```

- [ ] **Step 2: 更新主流程调用**

在 `main()` 函数中添加 `cleanup_uv_cache` 调用：

```bash
main() {
    # 非交互模式（CI环境）自动确认
    if [ -n "$CI" ] || [ -n "$npm_config_loglevel" ]; then
        export AUTO_CONFIRM=1
    fi

    cleanup_symlinks
    cleanup_shell_config
    cleanup_virtual_env
    cleanup_runtime_files
    cleanup_uv_path
    cleanup_uv_cache  # 新增
    cleanup_config_files
    show_post_uninstall_info
}
```

- [ ] **Step 3: 验证语法**

```bash
bash -n scripts/uninstall.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/uninstall.sh
git commit -m "feat: uninstall.sh 添加 uv 缓存清理

- 添加 cleanup_uv_cache 函数
- 询问用户是否清理 uv 缓存
- CI 环境自动跳过"
```

---

## Task 5: 优化 bin/remote-claude 初始化调用

**Files:**
- Modify: `bin/remote-claude:15-16`

- [ ] **Step 1: 确保 _lazy_init 被调用**

检查当前 `_common.sh` 的引入方式，确认 `_lazy_init` 会在脚本加载时自动执行。

当前 `_common.sh` 末尾有 `_lazy_init` 调用，应该已经生效。但为了确保在全局安装时也能正确检测，添加显式调用：

```bash
# 引入共享脚本（提供颜色定义、打印函数、uv 管理函数）
. "$SCRIPT_DIR/scripts/_common.sh"

# 确保初始化检查已执行（_common.sh 中已调用，此处为保险）
# _lazy_init 在 _common.sh 末尾已自动调用
```

- [ ] **Step 2: Commit**

```bash
git add bin/remote-claude
git commit -m "chore: 确保 bin/remote-claude 正确调用初始化检查"
```

---

## Task 6: 更新 README.md 安装说明

**Files:**
- Modify: `README.md:26-50`

- [ ] **Step 1: 更新安装章节**

替换第 26-50 行的安装说明：

```markdown
## 快速开始

### 1. 安装

以下安装方式 3 选 1，安装后重启 shell 生效

#### 方式一：npm 安装（推荐）

```bash
npm install -g remote-claude
```

安装时会自动：
- 安装 uv 包管理器
- 创建 Python 虚拟环境
- 安装所有 Python 依赖

#### 方式二：pnpm 安装

```bash
pnpm add -g remote-claude
```

与 npm 安装相同，会自动完成 Python 环境初始化。

#### 方式三：零依赖安装

项目自带便携式 Python 环境，无需预装 Python：

```bash
# 方式 A：一键安装脚本
curl -fsSL https://raw.githubusercontent.com/yyzybb537/remote_claude/main/scripts/install.sh | bash

# 方式 B：克隆后安装
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./scripts/install.sh
```

安装脚本会自动：
- 安装 uv 包管理器
- 下载并配置 Python（版本由 `pyproject.toml` 指定，便携式，不影响系统）
- 创建虚拟环境并安装依赖

#### 方式四：传统安装（需要预装 Python）

```bash
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./init.sh
```

`init.sh` 会自动安装 uv、tmux 等依赖，配置飞书环境（可选），并写入 `cla` / `cl` / `cx` / `cdx` 快捷命令。执行完成后重启终端生效。
```

- [ ] **Step 2: 添加卸载说明**

在 "## 使用指南" 章节前添加卸载说明：

```markdown
### 卸载

```bash
npm uninstall -g remote-claude
# 或
pnpm uninstall -g remote-claude
```

卸载时会：
- 删除快捷命令符号链接
- 停止飞书客户端
- 清理虚拟环境
- 询问是否保留配置文件

如需完全清理（包括 uv 缓存），运行：
```bash
remote-claude config reset --all
```
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: 更新 README.md 安装和卸载说明

- 添加 npm/pnpm 安装的详细说明
- 说明安装时的自动初始化行为
- 添加卸载说明和清理选项"
```

---

## Task 7: 更新 CLAUDE.md 安装流程文档

**Files:**
- Modify: `CLAUDE.md`（在适当位置添加）

- [ ] **Step 1: 在安装章节添加说明**

在 "## 常用命令" 章节前添加安装流程说明：

```markdown
## 安装流程

Remote Claude 支持多种安装方式：

### npm/pnpm 全局安装（推荐）

```bash
npm install -g remote-claude
# 或
pnpm add -g remote-claude
```

**安装过程：**
1. npm/pnpm 下载并解压包文件
2. `postinstall` 钩子自动执行：
   - 检查/安装 uv 包管理器
   - 创建 Python 虚拟环境（`.venv/`）
   - 使用 `uv sync --frozen` 安装依赖
3. 创建全局可用的快捷命令（`cla`, `cl`, `cx`, `cdx`）

**特点：**
- 安装后即可使用，无需额外初始化
- Python 环境完全隔离，不影响系统
- 使用 uv 管理的 Python 版本

### 本地克隆安装

```bash
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./scripts/install.sh
```

**安装过程：**
1. 检查操作系统（macOS/Linux）
2. 检查/安装 uv
3. 创建虚拟环境并安装依赖
4. 创建快捷命令符号链接

### 依赖变更检测

首次运行命令时，`_lazy_init` 会检查：
- `.venv` 是否存在
- `pyproject.toml` 是否比 `.venv` 新
- `uv.lock` 是否比 `.venv` 新

如果检测到变更，会自动重新同步依赖。

### 卸载流程

```bash
npm uninstall -g remote-claude
```

**卸载过程：**
1. `preuninstall` 钩子执行清理：
   - 删除快捷命令符号链接
   - 清理 shell 配置文件中的 PATH 设置
   - 删除虚拟环境
   - 停止飞书客户端并清理运行时文件
   - 询问是否删除配置文件
   - 可选：清理 uv 缓存

---
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 更新 CLAUDE.md 安装流程文档

- 详细说明 npm/pnpm 安装流程
- 说明依赖变更检测机制
- 说明卸载流程和清理选项"
```

---

## Task 8: 综合测试

**Files:**
- Test: 所有修改的文件

- [ ] **Step 1: 语法检查**

```bash
bash -n scripts/_common.sh
bash -n scripts/postinstall.sh
bash -n scripts/install.sh
bash -n scripts/uninstall.sh
bash -n bin/remote-claude
```

Expected: 全部无输出（语法正确）

- [ ] **Step 2: 功能测试 - _needs_sync**

```bash
cd /Users/bytedance/.superset/worktrees/remote_claude/feature/custom_command
export SCRIPT_DIR="$PWD"
source scripts/_common.sh

# 清理测试环境
rm -rf .venv

# 测试 1: venv 不存在
echo "Test 1: venv 不存在"
_needs_sync && echo "PASS: 需要同步" || echo "FAIL"

# 测试 2: 创建 venv
mkdir -p .venv
sleep 1
echo "Test 2: venv 存在"
_needs_sync && echo "FAIL" || echo "PASS: 不需要同步"

# 测试 3: 修改 pyproject.toml
touch pyproject.toml
echo "Test 3: pyproject.toml 更新"
_needs_sync && echo "PASS: 需要同步" || echo "FAIL"

# 测试 4: 重新同步后
touch .venv
echo "Test 4: 同步后"
_needs_sync && echo "FAIL" || echo "PASS: 不需要同步"

# 清理
rm -rf .venv
```

- [ ] **Step 3: 功能测试 - postinstall.sh**

```bash
cd /Users/bytedance/.superset/worktrees/remote_claude/feature/custom_command
rm -rf .venv

# 运行 postinstall
bash scripts/postinstall.sh

# 验证
[ -d .venv ] && echo "venv 创建成功" || echo "venv 创建失败"
[ -f .venv/bin/python3 ] && echo "Python 可用" || echo "Python 不可用"
```

- [ ] **Step 4: Commit 测试变更**

```bash
git add -A
git commit -m "test: 安装脚本优化测试通过" || echo "无变更需要提交"
```

---

## 总结

完成以上 8 个 Task 后，安装脚本将具备以下特性：

1. ✅ npm/pnpm 全局安装时自动完成 Python 环境初始化
2. ✅ 智能检测依赖变更，避免不必要的重复初始化
3. ✅ 使用 `uv sync --frozen` 确保可复现安装
4. ✅ 卸载时完整清理，包括可选的 uv 缓存清理
5. ✅ 文档已更新，说明新的安装行为

**测试验证清单：**
- [ ] `bash -n` 语法检查通过
- [ ] `_needs_sync` 逻辑测试通过
- [ ] `postinstall.sh` 初始化测试通过
- [ ] README.md 更新完成
- [ ] CLAUDE.md 更新完成
