# Lazy Init 指纹判定与 POSIX sh 兼容优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 lazy init 仅在真实依赖变化时触发并打印提示，同时将相关 shell 脚本修正为稳定 POSIX `sh` 兼容。

**Architecture:** 在 `scripts/_common.sh` 中引入“依赖指纹”机制替代目录时间戳判定，并在 `scripts/setup.sh --lazy` 成功后写回指纹；`_lazy_init` 的提示仅在 `_needs_sync` 为真时打印。同步清理 `local` 与 `trap ... EXIT` 等非 POSIX 用法，保持现有安装/初始化语义不变。

**Tech Stack:** POSIX sh, pytest, uv

---

## 文件结构与职责

- Modify: `scripts/_common.sh`
  - 新增/调整依赖指纹函数与 `_needs_sync` 判定逻辑。
  - 清理 `local` 等非 POSIX 写法（本文件内）。
- Modify: `scripts/setup.sh`
  - `--lazy` 成功路径写回依赖指纹。
  - `trap cleanup_tmpdir EXIT` 改为 POSIX 兼容写法。
- Modify: `scripts/uninstall.sh`
  - 清理 `local` 关键字（函数内部变量命名改为普通变量）。
- Modify: `scripts/completion.sh`
  - 保证 `sh` 可达路径无非 POSIX 语法问题（不破坏 zsh/bash 补全分支）。
- Modify: `tests/test_entry_lazy_init.py`
  - 增加“依赖未变不触发/依赖变更触发”与指纹回写测试。
  - 增加关键脚本无 `local`/`trap ... EXIT` 的静态断言测试。
- Modify: `tests/TEST_PLAN.md`
  - 同步新增回归命令。
- Modify: `CLAUDE.md`
  - 同步脚本规范：lazy init 触发依据与 sh 兼容约束。

---

### Task 1: 先写失败测试锁定新行为（TDD）

**Files:**
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 新增“依赖未变不触发同步且不打印提示”的测试（先失败）**

```python
def test_lazy_init_no_sync_when_fingerprint_unchanged(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    scripts_dir.mkdir(parents=True)
    venv_dir.mkdir(parents=True)

    (project_dir / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.0'\n", encoding="utf-8")
    (project_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{scripts_dir}'
fp=$(_compute_dep_fingerprint)
printf '%s\n' "$fp" > "$PROJECT_DIR/.venv/.remote_claude_dep_fingerprint"
if _lazy_init; then
  echo "rc:$? result:${{LAZY_INIT_RESULT:-missing}}"
else
  echo "rc:$? result:${{LAZY_INIT_RESULT:-missing}}"
  exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert "result:no-sync-needed" in result.stdout
    assert "检测到依赖变更" not in (result.stdout + result.stderr)
```

- [ ] **Step 2: 新增“依赖变更触发同步并打印提示”的测试（先失败）**

```python
def test_lazy_init_sync_when_fingerprint_changed(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    scripts_dir.mkdir(parents=True)
    venv_dir.mkdir(parents=True)

    (project_dir / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.0'\n", encoding="utf-8")
    (project_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (venv_dir / ".remote_claude_dep_fingerprint").write_text("stale\n", encoding="utf-8")

    setup_sh = scripts_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{scripts_dir}'
if _lazy_init; then
  echo "rc:$? result:${{LAZY_INIT_RESULT:-missing}}"
else
  echo "rc:$? result:${{LAZY_INIT_RESULT:-missing}}"
  exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert "result:sync-completed" in result.stdout
    assert "检测到依赖变更，正在更新 Python 环境" in (result.stdout + result.stderr)
```

- [ ] **Step 3: 新增“setup --lazy 成功后写回指纹文件”的测试（先失败）**

```python
def test_setup_lazy_writes_dependency_fingerprint(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    setup_sh = scripts_dir / "setup.sh"
    setup_sh.write_text((REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8"), encoding="utf-8")
    setup_sh.chmod(0o755)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    (project_dir / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.0'\n", encoding="utf-8")
    (project_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    uv_stub = tmp_path / "uv"
    uv_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv_stub.chmod(0o755)

    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ.get('PATH','')}"}
    result = subprocess.run(["sh", str(setup_sh), "--lazy"], text=True, capture_output=True, cwd=project_dir, env=env)

    assert result.returncode == 0, result.stderr
    fp_file = project_dir / ".venv" / ".remote_claude_dep_fingerprint"
    assert fp_file.exists()
    assert fp_file.read_text(encoding="utf-8").strip() != ""
```

- [ ] **Step 4: 新增静态断言测试（先失败）**

```python
def test_shell_scripts_avoid_non_posix_local_and_exit_trap():
    for rel in ["scripts/_common.sh", "scripts/uninstall.sh"]:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "local " not in text

    setup_text = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "trap cleanup_tmpdir EXIT" not in setup_text
```

- [ ] **Step 5: 运行定向测试确认失败**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_no_sync_when_fingerprint_unchanged -q
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_sync_when_fingerprint_changed -q
uv run pytest tests/test_entry_lazy_init.py::test_setup_lazy_writes_dependency_fingerprint -q
uv run pytest tests/test_entry_lazy_init.py::test_shell_scripts_avoid_non_posix_local_and_exit_trap -q
```

Expected: 至少一项 FAIL（实现尚未完成）。

- [ ] **Step 6: 提交失败测试基线**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test(lazy-init): add failing fingerprint and sh-compat regression cases"
```

---

### Task 2: 在 `_common.sh` 实现依赖指纹判定并替换 `_needs_sync`

**Files:**
- Modify: `scripts/_common.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 新增指纹路径与计算函数（最小实现）**

```sh
_dep_fingerprint_file() {
    printf '%s/.venv/.remote_claude_dep_fingerprint\n' "$PROJECT_DIR"
}

_compute_dep_fingerprint() {
    dep_files=""
    [ -f "$PROJECT_DIR/pyproject.toml" ] && dep_files="$dep_files $PROJECT_DIR/pyproject.toml"
    [ -f "$PROJECT_DIR/uv.lock" ] && dep_files="$dep_files $PROJECT_DIR/uv.lock"

    if [ -z "$dep_files" ]; then
        printf 'no-dep-files\n'
        return 0
    fi

    # shellcheck disable=SC2086
    cksum $dep_files 2>/dev/null | awk '{print $1":"$2":"$3}' | cksum | awk '{print $1":"$2}'
}
```

- [ ] **Step 2: 新增变更判断与写回函数**

```sh
_has_dep_changed() {
    fp_file="$(_dep_fingerprint_file)"
    current_fp="$(_compute_dep_fingerprint)"

    [ -n "$current_fp" ] || return 0
    [ -f "$fp_file" ] || return 0

    saved_fp=$(cat "$fp_file" 2>/dev/null)
    [ -n "$saved_fp" ] || return 0

    [ "$current_fp" = "$saved_fp" ] && return 1
    return 0
}

_write_dep_fingerprint() {
    fp_file="$(_dep_fingerprint_file)"
    fp_dir=$(dirname "$fp_file")
    current_fp="$(_compute_dep_fingerprint)"

    [ -n "$current_fp" ] || return 1
    mkdir -p "$fp_dir" || return 1

    tmp_fp=$(mktemp)
    printf '%s\n' "$current_fp" > "$tmp_fp" && mv "$tmp_fp" "$fp_file"
}
```

- [ ] **Step 3: 替换 `_needs_sync` 判定逻辑**

```sh
_needs_sync() {
    project_dir="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)}"
    [ -z "$project_dir" ] && return 1

    venv_dir="$project_dir/.venv"
    [ ! -d "$venv_dir" ] && return 0

    if _has_dep_changed; then
        return 0
    fi

    return 1
}
```

- [ ] **Step 4: 清理 `_common.sh` 中 `local` 声明**

```sh
# before
_example() {
    local VALUE
    VALUE="$1"
}

# after
_example() {
    example_value="$1"
}
```

- [ ] **Step 5: 运行定向测试验证通过**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_no_sync_when_fingerprint_unchanged -q
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_sync_when_fingerprint_changed -q
```

Expected: PASS。

- [ ] **Step 6: 提交 `_common.sh` 变更**

```bash
git add scripts/_common.sh tests/test_entry_lazy_init.py
git commit -m "feat(scripts): use dependency fingerprint for lazy init sync detection"
```

---

### Task 3: 在 `setup.sh --lazy` 成功后写回指纹

**Files:**
- Modify: `scripts/setup.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 在 lazy 成功路径调用 `_write_dep_fingerprint`**

```sh
if $LAZY_MODE; then
    _install_stage "setup-lazy-precheck"
    setup_path || { ... }
    check_uv || { ... }
    _install_stage "setup-lazy-deps"
    install_dependencies || { ... }

    if ! _write_dep_fingerprint; then
        _install_log "stage=setup-lazy-done fingerprint-write-failed"
    fi

    _install_stage "setup-lazy-done"
    print_success "Python 环境初始化完成"
    return 0
fi
```

- [ ] **Step 2: 运行指纹写回测试**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_setup_lazy_writes_dependency_fingerprint -q
```

Expected: PASS。

- [ ] **Step 3: 提交 setup lazy 写回实现**

```bash
git add scripts/setup.sh tests/test_entry_lazy_init.py
git commit -m "feat(setup): persist dependency fingerprint after lazy sync success"
```

---

### Task 4: 修正 sh 兼容问题（`trap` 与 `local`）

**Files:**
- Modify: `scripts/setup.sh`
- Modify: `scripts/uninstall.sh`
- Modify: `scripts/completion.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 将 setup 的 EXIT trap 改为 POSIX 写法**

```sh
# before
trap cleanup_tmpdir EXIT

# after
trap cleanup_tmpdir 0
```

- [ ] **Step 2: 清理 uninstall/completion 中 `local`（仅 `sh` 可达路径）**

```sh
# before
func() {
    local cleaned=0
}

# after
func() {
    cleaned=0
}
```

- [ ] **Step 3: 运行静态断言测试**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_shell_scripts_avoid_non_posix_local_and_exit_trap -q
```

Expected: PASS。

- [ ] **Step 4: 提交 sh 兼容修正**

```bash
git add scripts/setup.sh scripts/uninstall.sh scripts/completion.sh tests/test_entry_lazy_init.py
git commit -m "fix(shell): remove non-posix local usage and use trap 0"
```

---

### Task 5: 验证提示打印时机与回归

**Files:**
- Modify: `scripts/_common.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 确认 `_lazy_init` 提示仅在 `_needs_sync` 为真时输出**

```sh
if _needs_sync; then
    echo "检测到依赖变更，正在更新 Python 环境..."
    ...
fi
```

- [ ] **Step 2: 运行行为回归测试**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_if_needed_reports_noop_when_sync_not_needed -q
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_if_needed_reports_setup_success_after_trigger -q
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_no_sync_when_fingerprint_unchanged -q
uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_sync_when_fingerprint_changed -q
```

Expected: PASS。

- [ ] **Step 3: 提交提示时机回归确认**

```bash
git add scripts/_common.sh tests/test_entry_lazy_init.py
git commit -m "fix(lazy-init): print sync notice only when real dependency sync is triggered"
```

---

### Task 6: 同步文档与测试计划

**Files:**
- Modify: `tests/TEST_PLAN.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: 在 TEST_PLAN 增加新回归用例命令**

```markdown
| lazy 指纹判定（无变化） | 指纹一致时不触发同步且不打印提示 | `uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_no_sync_when_fingerprint_unchanged -q` |
| lazy 指纹判定（有变化） | 指纹变更时触发同步并打印提示 | `uv run pytest tests/test_entry_lazy_init.py::test_lazy_init_sync_when_fingerprint_changed -q` |
| lazy 成功写回指纹 | `setup.sh --lazy` 成功后落盘指纹文件 | `uv run pytest tests/test_entry_lazy_init.py::test_setup_lazy_writes_dependency_fingerprint -q` |
| sh 兼容静态约束 | 禁止 `local` 与 `trap ... EXIT` | `uv run pytest tests/test_entry_lazy_init.py::test_shell_scripts_avoid_non_posix_local_and_exit_trap -q` |
```

- [ ] **Step 2: 在 CLAUDE.md 同步脚本约束**

```markdown
- **lazy init 触发约定：** 依赖同步由 `pyproject.toml/uv.lock` 指纹比较决定；仅真实触发同步时打印“检测到依赖变更...”。
- **shell 兼容约定：** `scripts/*.sh` 需保持 POSIX `sh` 兼容，避免 `local`、`trap ... EXIT` 等非可移植写法。
```

- [ ] **Step 3: 提交文档同步**

```bash
git add tests/TEST_PLAN.md CLAUDE.md
git commit -m "docs: codify lazy-init fingerprint trigger and posix sh compatibility rules"
```

---

### Task 7: 全量验证与收尾

**Files:**
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 跑本次改动完整相关测试集**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py -q
```

Expected: PASS。

- [ ] **Step 2: 补充脚本层语法烟测（sh）**

Run:
```bash
sh -n scripts/_common.sh
sh -n scripts/setup.sh
sh -n scripts/install.sh
sh -n scripts/uninstall.sh
sh -n scripts/check-env.sh
```

Expected: 全部退出码 0。

- [ ] **Step 3: 检查工作区状态**

Run:
```bash
git status
```

Expected: 仅保留本次预期变更，或 `working tree clean`（若已完成全部提交）。

---

## 自检（写计划后）

1. **Spec coverage：** 已覆盖“真实触发才打印”“指纹判定替代时间戳”“_common.sh/setup.sh/uninstall.sh/completion.sh 关键改动”“回归验证与文档同步”。
2. **Placeholder scan：** 无 TBD/TODO/“后续补充”类占位描述。
3. **Type consistency：** 统一使用 `PROJECT_DIR/SCRIPT_DIR`，统一指纹文件名 `.remote_claude_dep_fingerprint`，测试与实现命名一致。
