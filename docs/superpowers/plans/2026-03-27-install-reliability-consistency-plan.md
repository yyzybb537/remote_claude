# 安装可靠性与一致性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复安装链路排障困难问题（固定日志到 `/tmp/remote-claude-install.log`），并收敛脚本变量来源到 `_common.sh`，同时保证 `runtime.json` 仅在安装成功时创建。

**Architecture:** 在 `scripts/_common.sh` 增加“安装上下文 + 阶段日志 + 失败提示”公共能力，`install.sh`/`setup.sh`/`uninstall.sh`/`bin/*` 仅复用，不再各自分散实现。测试采用 TDD：先补失败用例验证日志路径、成功/失败语义和路径一致性，再做最小实现。文档层同步 `CLAUDE.md` 与 `tests/TEST_PLAN.md` 的安装规范与回归场景。

**Tech Stack:** POSIX sh (`/bin/sh`), Python `pytest`, 现有 Remote Claude shell/python 测试体系

---

## 文件职责与改动边界

- `scripts/_common.sh`：
  - 统一 `PROJECT_DIR/SCRIPT_DIR` 归一逻辑（已有函数增强）
  - 新增安装日志能力（固定 `/tmp/remote-claude-install.log`）
  - 新增阶段打点与失败提示函数
- `scripts/install.sh`：
  - 接入公共日志能力
  - 关键阶段前后打点
  - 失败时统一提示日志路径
- `scripts/setup.sh`：
  - 修正补全路径引用一致性（`scripts/completion.sh`）
  - 保持 `runtime.json` 创建只在成功路径
  - 接入日志阶段打点
- `scripts/uninstall.sh`：
  - 统一目录变量入口，接入公共上下文（不改卸载语义）
- `bin/remote-claude`, `bin/cla`, `bin/cl`, `bin/cx`, `bin/cdx`：
  - 统一入口变量写法（最小变更）
- `tests/test_entry_lazy_init.py`：
  - 新增/调整安装日志、变量收敛、补全路径一致性测试
- `tests/TEST_PLAN.md`：
  - 增补安装失败日志、runtime 成功时创建的回归场景
- `CLAUDE.md`：
  - 同步安装日志路径与 runtime 生成时机约束

---

### Task 1: 先补失败测试（安装日志 + runtime 语义 + 补全路径）

**Files:**
- Modify: `tests/test_entry_lazy_init.py`
- Verify target: `scripts/_common.sh`, `scripts/install.sh`, `scripts/setup.sh`

- [ ] **Step 1: 新增“固定安装日志路径”失败测试**

```python
# tests/test_entry_lazy_init.py

def test_install_log_path_constant_in_common_sh():
    text = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")
    assert "/tmp/remote-claude-install.log" in text
```

- [ ] **Step 2: 新增“setup 补全路径使用 scripts/completion.sh”失败测试**

```python
def test_setup_completion_uses_scripts_path():
    text = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert 'scripts/completion.sh' in text
    assert '"$PROJECT_DIR/completion.sh"' not in text
```

- [ ] **Step 3: 新增“runtime 仅成功路径创建”的失败测试（静态顺序约束）**

```python
def test_setup_runtime_creation_stays_in_success_flow():
    text = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    # 关键流程顺序：install_dependencies 之后才 init_config_files
    assert "install_dependencies" in text
    assert "init_config_files" in text
    assert text.index("install_dependencies") < text.index("init_config_files")
```

- [ ] **Step 4: 运行测试并确认失败**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_install_log_path_constant_in_common_sh \
  tests/test_entry_lazy_init.py::test_setup_completion_uses_scripts_path \
  tests/test_entry_lazy_init.py::test_setup_runtime_creation_stays_in_success_flow -q
```

Expected:
- 至少 `test_install_log_path_constant_in_common_sh` 与 `test_setup_completion_uses_scripts_path` 失败。

- [ ] **Step 5: 提交（仅测试）**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test(install): add failing coverage for log path and setup consistency"
```

---

### Task 2: 在 `_common.sh` 实现安装日志公共能力并收敛入口变量

**Files:**
- Modify: `scripts/_common.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 在 `_common.sh` 增加日志常量与阶段函数（最小实现）**

```sh
# scripts/_common.sh
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
```

- [ ] **Step 2: 在 `_common.sh` 增强目录收敛（确保导出一致）**

```sh
# scripts/_common.sh
_normalize_project_and_script_dir() {
    if [ -n "${PROJECT_DIR:-}" ] && [ -d "$PROJECT_DIR" ]; then
        SCRIPT_DIR="${SCRIPT_DIR:-$PROJECT_DIR/scripts}"
        export PROJECT_DIR SCRIPT_DIR
        return 0
    fi

    if [ -n "${SCRIPT_DIR:-}" ] && [ -d "$SCRIPT_DIR" ]; then
        case "$SCRIPT_DIR" in
            */scripts) PROJECT_DIR="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)" ;;
            *) PROJECT_DIR="$SCRIPT_DIR"; SCRIPT_DIR="$PROJECT_DIR/scripts" ;;
        esac
        export PROJECT_DIR SCRIPT_DIR
        return 0
    fi
    return 1
}
```

- [ ] **Step 3: 运行 Task 1 的测试，确认至少日志常量用例转绿**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_install_log_path_constant_in_common_sh -q
```

Expected:
- PASS

- [ ] **Step 4: 补充一个公共函数可用性测试并运行通过**

```python
def test_common_sh_declares_install_log_helpers():
    text = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")
    assert "_init_install_log()" in text
    assert "_install_stage()" in text
    assert "_install_fail_hint()" in text
```

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_common_sh_declares_install_log_helpers -q
```

Expected:
- PASS

- [ ] **Step 5: 提交 Task 2**

```bash
git add scripts/_common.sh tests/test_entry_lazy_init.py
git commit -m "feat(install): add shared install log and stage helpers in common script"
```

---

### Task 3: 改造 `install.sh` 接入统一日志与失败提示

**Files:**
- Modify: `scripts/install.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 新增 `install.sh` 接入日志初始化测试（先失败）**

```python
def test_install_sh_initializes_install_log_helpers():
    text = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "_init_install_log" in text
    assert "_install_stage" in text
```

- [ ] **Step 2: 运行测试并确认失败**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_install_sh_initializes_install_log_helpers -q
```

Expected:
- FAIL

- [ ] **Step 3: 在 `install.sh` 关键阶段接入日志与失败提示**

```sh
# scripts/install.sh (main 入口附近)
main() {
    NPM_MODE=false
    LAZY_MODE=false
    for arg in "$@"; do
        [ "$arg" = "--npm" ] && NPM_MODE=true
        [ "$arg" = "--lazy" ] && LAZY_MODE=true
    done

    _init_install_log
    _install_stage "precheck"

    detect_os || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }

    _install_stage "uv"
    check_and_install_uv_install || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }

    _install_stage "deps"
    setup_virtual_env || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }

    _install_stage "setup"
    run_init_script || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }

    _install_stage "done"
}
```

- [ ] **Step 4: 运行测试并确认通过**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_install_sh_initializes_install_log_helpers -q
```

Expected:
- PASS

- [ ] **Step 5: 提交 Task 3**

```bash
git add scripts/install.sh tests/test_entry_lazy_init.py
git commit -m "refactor(install): wire install stages to shared log helpers"
```

---

### Task 4: 改造 `setup.sh`（补全路径修复 + 成功路径创建 runtime）

**Files:**
- Modify: `scripts/setup.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 修复补全路径到 `scripts/completion.sh`**

```sh
# scripts/setup.sh
COMPLETION_LINE='. "$PROJECT_DIR/scripts/completion.sh"'
```

- [ ] **Step 2: 在 setup 主流程打点并保留 runtime 成功路径语义**

```sh
# scripts/setup.sh main()
_init_install_log
_install_stage "setup-precheck"

check_uv || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }
install_dependencies || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }

_install_stage "setup-config"
create_directories || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }
init_config_files || { rc=$?; _install_fail_hint "$rc"; exit "$rc"; }

_install_stage "setup-done"
```

- [ ] **Step 3: 运行 Task 1 的 setup 两个测试并确认通过**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_setup_completion_uses_scripts_path \
  tests/test_entry_lazy_init.py::test_setup_runtime_creation_stays_in_success_flow -q
```

Expected:
- PASS

- [ ] **Step 4: 新增一个“runtime 初始化函数仍存在”防回归测试并运行通过**

```python
def test_setup_still_initializes_runtime_file():
    text = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "init_config_files()" in text
    assert "runtime.default.json" in text
```

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_setup_still_initializes_runtime_file -q
```

Expected:
- PASS

- [ ] **Step 5: 提交 Task 4**

```bash
git add scripts/setup.sh tests/test_entry_lazy_init.py
git commit -m "fix(setup): correct completion path and keep runtime init on success flow"
```

---

### Task 5: 统一 `uninstall.sh` 与 `bin/*` 入口变量风格

**Files:**
- Modify: `scripts/uninstall.sh`
- Modify: `bin/remote-claude`
- Modify: `bin/cla`
- Modify: `bin/cl`
- Modify: `bin/cx`
- Modify: `bin/cdx`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 增加入口一致性测试（先失败）**

```python
ENTRY_SCRIPTS = [
    "bin/remote-claude", "bin/cla", "bin/cl", "bin/cx", "bin/cdx"
]


def test_entry_scripts_define_project_dir_before_sourcing_common():
    for rel in ENTRY_SCRIPTS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "PROJECT_DIR=" in text
        assert "scripts/_common.sh" in text
        assert text.index("PROJECT_DIR=") < text.index("scripts/_common.sh")
```

- [ ] **Step 2: 运行测试并确认失败（如已通过则记录现状并继续）**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_entry_scripts_define_project_dir_before_sourcing_common -q
```

Expected:
- 初次可能 FAIL；若 PASS，记录为“基线已满足”，继续执行 Step 3 的风格收敛。

- [ ] **Step 3: 统一入口写法（最小改动）**

```sh
# bin/* 与 uninstall.sh 统一入口模式
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SELF_DIR/.." && pwd)"
. "$PROJECT_DIR/scripts/_common.sh"
```

- [ ] **Step 4: 运行入口一致性测试并确认通过**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_entry_scripts_define_project_dir_before_sourcing_common -q
```

Expected:
- PASS

- [ ] **Step 5: 提交 Task 5**

```bash
git add scripts/uninstall.sh bin/remote-claude bin/cla bin/cl bin/cx bin/cdx tests/test_entry_lazy_init.py
git commit -m "refactor(entry): align project dir bootstrap across scripts and bins"
```

---

### Task 6: 同步文档与回归计划

**Files:**
- Modify: `CLAUDE.md`
- Modify: `tests/TEST_PLAN.md`

- [ ] **Step 1: 在 `CLAUDE.md` 增加安装日志与 runtime 语义说明**

```markdown
- 安装日志固定路径：`/tmp/remote-claude-install.log`（每次安装覆盖最近一次日志）
- `runtime.json` 创建策略：仅安装成功时初始化；失败时不创建
- 目录变量约定：`PROJECT_DIR/SCRIPT_DIR` 以 `scripts/_common.sh` 为唯一收敛入口
```

- [ ] **Step 2: 在 `tests/TEST_PLAN.md` 增加安装链路回归项**

```markdown
### 安装可靠性回归

| 场景 | 验证点 | 命令 |
|------|--------|------|
| 安装失败日志落盘 | 失败后提示并可在 `/tmp/remote-claude-install.log` 定位阶段 | `uv run pytest tests/test_entry_lazy_init.py::test_install_sh_initializes_install_log_helpers -q` |
| 补全路径一致 | setup 写入补全路径为 `scripts/completion.sh` | `uv run pytest tests/test_entry_lazy_init.py::test_setup_completion_uses_scripts_path -q` |
| runtime 成功时创建 | runtime 初始化逻辑位于成功主流程 | `uv run pytest tests/test_entry_lazy_init.py::test_setup_runtime_creation_stays_in_success_flow -q` |
```

- [ ] **Step 3: 提交 Task 6**

```bash
git add CLAUDE.md tests/TEST_PLAN.md
git commit -m "docs(install): document log path and runtime creation semantics"
```

---

### Task 7: 全量验证与收尾

**Files:**
- Verify: `scripts/*.sh`
- Verify: `tests/test_entry_lazy_init.py`
- Verify: `tests/test_custom_commands.py`

- [ ] **Step 1: 运行 shell 语法检查**

Run:
```bash
for f in scripts/*.sh; do sh -n "$f" || exit 1; done && echo "sh syntax ok"
```

Expected:
- 输出 `sh syntax ok`

- [ ] **Step 2: 运行关键回归测试**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py -q
```

Expected:
- PASS

- [ ] **Step 3: 运行 custom commands 回归**

Run:
```bash
uv run pytest tests/test_custom_commands.py -q
```

Expected:
- PASS

- [ ] **Step 4: 汇总验证结果并提交最终变更**

```bash
git add scripts/_common.sh scripts/install.sh scripts/setup.sh scripts/uninstall.sh \
  bin/remote-claude bin/cla bin/cl bin/cx bin/cdx \
  tests/test_entry_lazy_init.py tests/TEST_PLAN.md CLAUDE.md
git commit -m "feat(install): improve diagnostics and unify script bootstrap semantics"
```

---

## 自检（writing-plans checklist）

1. **Spec coverage**
   - 固定 `/tmp` 安装日志：Task 2/3
   - `runtime.json` 仅成功创建：Task 1/4/6
   - 变量收敛到 `_common.sh`：Task 2/5
   - 文档同步：Task 6
2. **Placeholder scan**
   - 无 `TODO/TBD/implement later`。
3. **Type consistency**
   - 函数名统一使用 `_init_install_log/_install_stage/_install_fail_hint`。

