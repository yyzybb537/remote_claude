# 安装脚本重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构安装脚本，统一安装入口，确保 npm 安装执行完整初始化

**Architecture:** 将 init.sh 移动到 scripts/setup.sh，删除 postinstall.sh，install.sh 成为唯一安装入口

**Tech Stack:** POSIX shell scripts, npm lifecycle hooks

**设计文档:** `docs/superpowers/specs/2026-03-25-install-scripts-refactor-design.md`

---

## 文件变更概览

| 操作 | 原路径 | 新路径 |
|------|--------|--------|
| 移动+重命名 | `init.sh` | `scripts/setup.sh` |
| 删除 | `scripts/postinstall.sh` | - |
| 修改 | `scripts/install.sh` | - |
| 修改 | `scripts/_common.sh` | - |
| 修改 | `package.json` | - |
| 修改 | `CLAUDE.md` | - |
| 修改 | `README.md` | - |

---

### Task 1: 移动 init.sh 到 scripts/setup.sh

**Files:**
- Move: `init.sh` → `scripts/setup.sh`

- [ ] **Step 1: 使用 git mv 移动文件**

```bash
git mv init.sh scripts/setup.sh
```

- [ ] **Step 2: 修改 scripts/setup.sh 的 SCRIPT_DIR 计算**

找到文件开头（第 4-5 行）：

```sh
# 脚本目录（全局变量）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
```

修改为：

```sh
# 脚本目录（scripts/ 目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 项目根目录
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
```

- [ ] **Step 3: 更新 _common.sh 引用路径**

找到（第 9 行）：

```sh
. "$SCRIPT_DIR/scripts/_common.sh"
```

修改为：

```sh
. "$SCRIPT_DIR/_common.sh"
```

- [ ] **Step 4: 更新所有引用 $SCRIPT_DIR 为 $PROJECT_ROOT 的路径**

使用以下命令查找需要替换的位置：

```bash
grep -n '\$SCRIPT_DIR' scripts/setup.sh | head -20
```

替换规则：
- `$SCRIPT_DIR/resources/` → `$PROJECT_ROOT/resources/`
- `$SCRIPT_DIR/pyproject.toml` → `$PROJECT_ROOT/pyproject.toml`
- `$SCRIPT_DIR/remote_claude.py` → `$PROJECT_ROOT/remote_claude.py`
- `$SCRIPT_DIR/server/` → `$PROJECT_ROOT/server/`
- `$SCRIPT_DIR/client/` → `$PROJECT_ROOT/client/`
- `$SCRIPT_DIR/bin/` → `$PROJECT_ROOT/bin/`

**注意**：
- `$SCRIPT_DIR/scripts/completion.sh` → `$SCRIPT_DIR/completion.sh`（保持 $SCRIPT_DIR）

- [ ] **Step 5: 验证修改**

```bash
# 检查语法
sh -n scripts/setup.sh
```

---

### Task 2: 更新 scripts/install.sh

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: （无需操作）缓存检测函数已存在于 `_common.sh`**

`_is_in_package_manager_cache` 函数已在 `_common.sh`（第 181-193 行）定义，`install.sh` 通过 `. "$SCRIPT_DIR/_common.sh"` 自动引入。

- [ ] **Step 2: 更新 main() 函数**

找到 `main()` 函数（第 148 行开始），替换整个函数为：

```sh
main() {
    # 解析参数
    NPM_MODE=false
    LAZY_MODE=false
    for arg in "$@"; do
        [ "$arg" = "--npm" ] && NPM_MODE=true
        [ "$arg" = "--lazy" ] && LAZY_MODE=true
    done

    # 如果在包管理器缓存中，跳过初始化
    if _is_in_package_manager_cache; then
        echo "检测到缓存安装，跳过初始化"
        exit 0
    fi

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 一键安装${NC}"
    echo -e "${GREEN}   零依赖安装 - 自动配置 Python 环境${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # 延迟模式：只运行必要步骤
    if $LAZY_MODE; then
        check_and_install_uv_install
        setup_virtual_env
        print_success "Python 环境初始化完成"
        return 0
    fi

    detect_os
    check_and_install_uv_install
    setup_virtual_env
    verify_installation
    run_init_script
    show_completion
}
```

- [ ] **Step 3: 更新 run_init_script 函数**

找到 `run_init_script` 函数（第 97-116 行），替换为：

```sh
run_init_script() {
    print_header "运行初始化脚本"

    setup_script="$SCRIPT_DIR/setup.sh"

    if [ ! -f "$setup_script" ]; then
        print_error "未找到 setup.sh 脚本: $setup_script"
        exit 1
    fi

    print_info "执行 setup.sh 进行完整初始化..."

    # 根据参数调用 setup.sh
    if $NPM_MODE && $LAZY_MODE; then
        sh "$setup_script" --npm --lazy
    elif $NPM_MODE; then
        sh "$setup_script" --npm
    elif $LAZY_MODE; then
        sh "$setup_script" --lazy
    else
        sh "$setup_script"
    fi

    if [ $? -eq 0 ]; then
        print_success "setup.sh 执行完成"
    else
        print_error "setup.sh 执行失败"
        exit 1
    fi
}
```

- [ ] **Step 4: 验证语法**

```bash
sh -n scripts/install.sh
```

---

### Task 3: 删除 postinstall.sh

**Files:**
- Delete: `scripts/postinstall.sh`

- [ ] **Step 1: 使用 git rm 删除文件**

```bash
git rm scripts/postinstall.sh
```

---

### Task 4: 更新 _common.sh 延迟初始化路径

**Files:**
- Modify: `scripts/_common.sh:237-261`

- [ ] **Step 1: 更新 _lazy_init 函数中的调用路径**

找到 `_lazy_init` 函数（第 237-261 行），将：

```sh
bash init.sh --npm --lazy 2>/dev/null || true
```

修改为：

```sh
bash "$SCRIPT_DIR/scripts/setup.sh" --npm --lazy 2>/dev/null || true
```

**完整函数：**

```sh
_lazy_init() {
    # 防止重入：如果已经在初始化流程中，跳过
    case "${_LAZY_INIT_RUNNING:-}" in
        1) return 0 ;;
    esac

    # 如果在包管理器缓存中，跳过初始化
    if _is_in_package_manager_cache; then
        return 0
    fi

    # 如果需要同步（venv 不存在或依赖变更），执行初始化
    if _needs_sync; then
        echo "检测到依赖变更，正在更新 Python 环境..."
        cd "$SCRIPT_DIR"
        if command -v bash >/dev/null 2>&1; then
            # 设置标记防止重入
            _LAZY_INIT_RUNNING=1
            export _LAZY_INIT_RUNNING
            bash "$SCRIPT_DIR/scripts/setup.sh" --npm --lazy 2>/dev/null || true
            _LAZY_INIT_RUNNING=0
        fi
    fi
}
```

- [ ] **Step 2: 验证语法**

```bash
sh -n scripts/_common.sh
```

---

### Task 5: 更新 package.json

**Files:**
- Modify: `package.json`

- [ ] **Step 1: 更新 postinstall 脚本**

找到（第 14 行）：

```json
"postinstall": "sh scripts/postinstall.sh",
```

修改为：

```json
"postinstall": "sh scripts/install.sh --npm",
```

- [ ] **Step 2: 移除 files 字段中的 init.sh**

找到（第 26 行）：

```json
"files": [
  "bin/",
  "scripts/*.sh",
  "scripts/*.py",
  "init.sh",
  ...
]
```

移除 `"init.sh",` 行：

```json
"files": [
  "bin/",
  "scripts/*.sh",
  "scripts/*.py",
  "remote_claude.py",
  ...
]
```

- [ ] **Step 3: 验证 JSON 语法**

```bash
node -e "console.log(JSON.parse(require('fs').readFileSync('package.json')))"
```

---

### Task 6: 更新 CLAUDE.md 文档

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新安装流程章节**

找到 `## 安装流程` 章节，更新为：

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
2. `postinstall` 钩子自动执行 `scripts/install.sh --npm`：
   - 检查/安装 uv 包管理器
   - 创建 Python 虚拟环境（`.venv/`）
   - 使用 `uv sync --frozen` 安装依赖
   - 执行 `scripts/setup.sh` 完成初始化

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
4. 执行完整初始化（创建目录、符号链接、配置补全）

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
```

---

### Task 7: 更新 README.md 文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新第 73 行的传统安装命令**

找到：

```markdown
./init.sh
```

修改为：

```markdown
./scripts/setup.sh
```

- [ ] **Step 2: 更新第 76 行的描述**

找到：

```markdown
`init.sh` 会自动安装 uv、tmux 等依赖，配置飞书环境（可选），并写入 `cla` / `cl` / `cx` / `cdx` 快捷命令。执行完成后重启终端生效。
```

修改为：

```markdown
`scripts/setup.sh` 会自动安装 uv、tmux 等依赖，配置飞书环境（可选），并写入 `cla` / `cl` / `cx` / `cdx` 快捷命令。执行完成后重启终端生效。
```

**注意**：README.md 中第 55 行和第 60 行已经引用 `scripts/install.sh`，无需修改。

---

### Task 8: 提交变更

**Files:**
- All modified files

- [ ] **Step 1: 查看变更状态**

```bash
git status
```

- [ ] **Step 2: 提交所有变更**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor: 重构安装脚本

- init.sh 移动到 scripts/setup.sh
- 删除 postinstall.sh，功能合并到 install.sh
- 统一 npm 安装和用户安装入口
- 更新 package.json postinstall 钩子
- 更新 CLAUDE.md 和 README.md 文档

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 验证测试

**Files:**
- Test scripts

- [ ] **Step 1: 测试语法检查**

```bash
sh -n scripts/install.sh
sh -n scripts/setup.sh
sh -n scripts/_common.sh
```

- [ ] **Step 2: 测试 --npm --lazy 模式**

```bash
# 模拟延迟初始化
sh scripts/install.sh --npm --lazy
```

预期输出：
```
检测到依赖变更，正在更新 Python 环境...
...
Python 环境初始化完成
```

- [ ] **Step 3: 验证 package.json 语法**

```bash
node -e "console.log(JSON.parse(require('fs').readFileSync('package.json')))"
```

---

## 回滚方案

如果出现问题，可以通过以下命令回滚：

```bash
# 回滚最近一次提交
git revert HEAD

# 或手动恢复
git checkout HEAD~1 -- init.sh scripts/postinstall.sh scripts/_common.sh package.json CLAUDE.md README.md
# 删除新创建的文件
rm -f scripts/setup.sh
```
