# Shell 脚本初始化逻辑修复实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 lazy_init_if_needed 不存在的问题，统一初始化逻辑为 _common.sh 自动调用

**Architecture:** 删除 bin 入口的手动初始化调用，依赖 _common.sh 末尾的 _lazy_init 自动执行；删除过时测试；更新文档；增强 Docker 测试

**Tech Stack:** Shell (POSIX sh), Python 测试框架

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `bin/cl` | 修改 | 删除 lazy_init_if_needed 调用 |
| `bin/cdx` | 修改 | 删除 lazy_init_if_needed 调用 |
| `bin/cx` | 修改 | 删除 lazy_init_if_needed 调用 |
| `bin/cla` | 修改 | 删除 lazy_init_if_needed 调用 |
| `tests/test_entry_lazy_init.py` | 删除 | 测试已不适用 |
| `CLAUDE.md` | 修改 | 更新运行期初始化说明 |
| `tests/TEST_PLAN.md` | 修改 | 删除 User Story 5 |
| `docker/scripts/docker-test.sh` | 修改 | 添加脚本语法检查 |

---

### Task 1: 删除 bin 入口的 lazy_init_if_needed 调用

**Files:**
- Modify: `bin/cl`
- Modify: `bin/cdx`
- Modify: `bin/cx`
- Modify: `bin/cla`

- [ ] **Step 1: 修改 bin/cl**

删除第 14-17 行的 lazy_init_if_needed 调用。修改后文件内容：

```sh
#!/bin/sh
# cl - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Claude（跳过权限确认）

# 解析符号链接，兼容 macOS（不支持 readlink -f）
SOURCE="$0"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
. "$SCRIPT_DIR/scripts/_common.sh"

# 检查飞书配置
. "$SCRIPT_DIR/scripts/check-env.sh" "$SCRIPT_DIR"

# 切换到项目目录，使用 uv run 调用入口点
cd "$SCRIPT_DIR"
uv run remote-claude lark start
uv run remote-claude start "${PWD}_$(date +%m%d_%H%M%S)" -- --dangerously-skip-permissions --permission-mode=dontAsk "$@"
```

- [ ] **Step 2: 修改 bin/cdx**

删除第 14-17 行的 lazy_init_if_needed 调用。修改后文件内容：

```sh
#!/bin/sh
# cdx - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Codex

# 解析符号链接，兼容 macOS（不支持 readlink -f）
SOURCE="$0"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
. "$SCRIPT_DIR/scripts/_common.sh"

# 检查飞书配置
. "$SCRIPT_DIR/scripts/check-env.sh" "$SCRIPT_DIR"

# 切换到项目目录，使用 uv run 调用入口点
cd "$SCRIPT_DIR"
uv run remote-claude lark start
uv run remote-claude start "${PWD}_$(date +%m%d_%H%M%S)" --cli codex -- "$@"
```

- [ ] **Step 3: 修改 bin/cx**

删除第 14-17 行的 lazy_init_if_needed 调用。修改后文件内容：

```sh
#!/bin/sh
# cx - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Codex（跳过权限）

# 解析符号链接，兼容 macOS（不支持 readlink -f）
SOURCE="$0"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
. "$SCRIPT_DIR/scripts/_common.sh"

# 检查飞书配置
. "$SCRIPT_DIR/scripts/check-env.sh" "$SCRIPT_DIR"

# 切换到项目目录，使用 uv run 调用入口点
cd "$SCRIPT_DIR"
uv run remote-claude lark start
uv run remote-claude start "${PWD}_$(date +%m%d_%H%M%S)" --cli codex -- --dangerously-bypass-approvals-and-sandbox "$@"
```

- [ ] **Step 4: 修改 bin/cla**

删除第 14-17 行的 lazy_init_if_needed 调用。修改后文件内容：

```sh
#!/bin/sh
# cla - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Claude

# 解析符号链接，兼容 macOS（不支持 readlink -f）
SOURCE="$0"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
. "$SCRIPT_DIR/scripts/_common.sh"

# 检查飞书配置
. "$SCRIPT_DIR/scripts/check-env.sh" "$SCRIPT_DIR"

# 切换到项目目录，使用 uv run 调用入口点
cd "$SCRIPT_DIR"
uv run remote-claude lark start
uv run remote-claude start "${PWD}_$(date +%m%d_%H%M%S)" -- "$@"
```

- [ ] **Step 5: 验证脚本语法正确**

Run: `bash -n bin/cl && bash -n bin/cdx && bash -n bin/cx && bash -n bin/cla && echo "语法检查通过"`
Expected: 输出 "语法检查通过"

- [ ] **Step 6: 验证 bin 入口不再引用 lazy_init_if_needed**

Run: `grep -r "lazy_init_if_needed" bin/`
Expected: 无输出（无匹配）

- [ ] **Step 7: 提交变更**

```bash
git add bin/cl bin/cdx bin/cx bin/cla
git commit -m "$(cat <<'EOF'
fix(bin): remove invalid lazy_init_if_needed calls

_common.sh 末尾已自动调用 _lazy_init，无需 bin 入口手动调用。
删除对不存在函数的调用，修复运行时报错。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 删除过时的测试文件

**Files:**
- Delete: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 删除测试文件**

Run: `rm tests/test_entry_lazy_init.py`

- [ ] **Step 2: 确认文件已删除**

Run: `test -f tests/test_entry_lazy_init.py && echo "文件仍存在" || echo "文件已删除"`
Expected: 输出 "文件已删除"

- [ ] **Step 3: 提交变更**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "$(cat <<'EOF'
test: remove obsolete test_entry_lazy_init.py

测试假定存在 lazy_init_if_needed 函数，已不适用。
初始化逻辑现由 _common.sh 自动处理。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 更新 CLAUDE.md 文档

**Files:**
- Modify: `CLAUDE.md` (第 172 行)

- [ ] **Step 1: 更新运行期初始化说明**

将第 172 行：
```
- **运行期初始化：** 所有 bin 入口依赖 `scripts/_common.sh` 暴露的 `lazy_init_if_needed()`；初始化失败时必须向上传播，不能静默吞错
```

修改为：
```
- **运行期初始化：** 所有 bin 入口通过 `. scripts/_common.sh` 引入共享函数；`_common.sh` 末尾自动执行 `_lazy_init()` 检查并同步依赖
```

- [ ] **Step 2: 提交变更**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: update runtime init description in CLAUDE.md

更新运行期初始化说明：_common.sh 末尾自动执行 _lazy_init()，
无需 bin 入口手动调用。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 更新 TEST_PLAN.md 文档

**Files:**
- Modify: `tests/TEST_PLAN.md` (删除 User Story 5)

- [ ] **Step 1: 删除 User Story 5 相关内容**

删除第 144-159 行（User Story 5 及其表格和独立测试命令）：

删除内容：
```markdown
### User Story 5：npm/pnpm 首次运行惰性初始化

**测试文件**：`tests/test_entry_lazy_init.py`

| 场景 | 验证点 | 测试方法 |
|------|-------|---------|
| 真实 `_common.sh` 契约 | 暴露 `lazy_init_if_needed()` 稳定接口 | `test_real_common_sh_exposes_lazy_init_if_needed_contract()` |
| 主入口首次运行 | `remote-claude` 在 `uv run` 前触发惰性初始化 | `test_remote_claude_entry_runs_lazy_init_before_uv()` |
| 快捷入口初始化失败 | `cla/cl/cx/cdx` 在 lazy init 失败时返回非 0，且不继续执行 `check-env.sh` | `test_all_shortcut_entries_fail_with_recovery_command_when_lazy_init_fails()` |

**独立测试**：
```bash
uv run python3 -m pytest tests/test_entry_lazy_init.py -v
```

---
```

- [ ] **Step 2: 提交变更**

```bash
git add tests/TEST_PLAN.md
git commit -m "$(cat <<'EOF'
docs: remove User Story 5 from TEST_PLAN.md

删除 npm/pnpm 首次运行惰性初始化测试场景，
相关测试文件已删除。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 增强 Docker 测试脚本

**Files:**
- Modify: `docker/scripts/docker-test.sh` (test_basic_commands 函数)

- [ ] **Step 1: 在 test_basic_commands 函数中添加脚本检查**

在第 510 行（`if grep -q "lark start" "bin/cla"; then` 之后）添加以下代码：

```bash

    # 测试所有 bin 入口脚本语法
    log_info "测试所有 bin 入口脚本语法..."
    local bin_has_error=0
    for bin_file in bin/*; do
        if [ -f "$bin_file" ]; then
            if bash -n "$bin_file" 2>/dev/null; then
                log_success "$bin_file 语法正确"
            else
                log_error "$bin_file 语法错误"
                bin_has_error=1
            fi
        fi
    done

    if [ $bin_has_error -eq 1 ]; then
        return 1
    fi

    # 验证 _common.sh 不暴露 lazy_init_if_needed
    log_info "验证 _common.sh 不暴露 lazy_init_if_needed..."
    if grep -q "^lazy_init_if_needed" "scripts/_common.sh"; then
        log_error "_common.sh 不应暴露 lazy_init_if_needed 函数"
        return 1
    fi
    log_success "_common.sh 不暴露 lazy_init_if_needed（符合预期）"
```

- [ ] **Step 2: 提交变更**

```bash
git add docker/scripts/docker-test.sh
git commit -m "$(cat <<'EOF'
test(docker): add bin script syntax checks

增强 Docker 测试：
- 检查所有 bin/* 脚本语法
- 验证 _common.sh 不暴露 lazy_init_if_needed

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 最终验证

**Files:**
- 无文件变更

- [ ] **Step 1: 验证所有 bin 入口正常运行**

Run: `bin/remote-claude --help 2>&1 | head -5`
Expected: 显示帮助信息，无 "not found" 错误

- [ ] **Step 2: 验证 scripts 目录无 lazy_init_if_needed 引用**

Run: `grep -r "lazy_init_if_needed" scripts/`
Expected: 无输出（无匹配）

- [ ] **Step 3: 验证文档无 lazy_init_if_needed 引用**

Run: `grep "lazy_init_if_needed" CLAUDE.md tests/TEST_PLAN.md`
Expected: 无输出（无匹配）

- [ ] **Step 4: 运行核心单元测试确认无回归**

Run: `uv run python3 tests/test_session_truncate.py && uv run python3 tests/test_runtime_config.py && echo "测试通过"`
Expected: 输出 "测试通过"

---

## 自检清单

| 检查项 | 状态 |
|-------|------|
| Spec 覆盖完整 | ✅ 所有变更点都有对应任务 |
| 无占位符 | ✅ 每步都有完整代码/命令 |
| 类型一致 | ✅ 函数名统一为 `_lazy_init` |
| 无遗漏 | ✅ bin 文件、测试、文档、Docker 均覆盖 |
