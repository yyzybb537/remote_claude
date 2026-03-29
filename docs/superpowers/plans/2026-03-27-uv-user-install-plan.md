# UV 用户态优先安装策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 uv 安装策略改为“优先 `pip --user`，失败后 fallback”，并在 install/setup/bin 懒初始化全入口保持一致行为。
**Architecture:** 仅修改 `scripts/_common.sh` 中 `install_uv_multi_source()` 与相关小型辅助函数，实现 pip 段配置归拢与重复逻辑收敛；入口脚本继续统一调用 `check_and_install_uv()`，不新增分散实现。通过 `tests/test_entry_lazy_init.py` 增加行为测试，验证 user-first、fallback 与入口一致性。
**Tech Stack:** POSIX shell (`sh`/`bash` 兼容片段)、pytest、现有脚本测试基建（`run_common`）。

---

## Scope Check

该 spec 只覆盖一个子系统：`scripts/_common.sh` 中 uv 安装路径与其测试回归；无需拆分为多个实现计划。

## File Structure

- Modify: `scripts/_common.sh`
  - 责任：统一 uv 检测/安装流程，收敛 pip 尝试配置，保证 user-first + fallback。
- Modify: `tests/test_entry_lazy_init.py`
  - 责任：新增 `install_uv_multi_source()` 行为测试，覆盖 `pip --user` 优先、pip 失败 fallback、成功后 PATH/uv 可发现。
- Modify: `tests/TEST_PLAN.md`
  - 责任：补充 uv user-first 与 fallback 的回归测试场景。
- Modify: `CLAUDE.md`
  - 责任：同步“uv 安装策略优先 `pip --user`”开发须知，满足仓库变更同步规则。

### Task 1: 先写失败测试（TDD）验证 user-first 与 fallback

**Files:**
- Modify: `tests/test_entry_lazy_init.py:125-220`（在现有 lazy init 相关测试后追加新用例）
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 新增“pip 必须带 --user”失败测试**

```python
def test_install_uv_multi_source_prefers_pip_user_before_fallback():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin"

pip3() {
    echo "$*" >> "$TMPDIR_PATH/pip_args.log"
    case " $* " in
        *" --user "*)
            cat > "$HOME/.local/bin/uv" <<'EOF'
#!/bin/sh
echo "uv 0.test"
EOF
            chmod +x "$HOME/.local/bin/uv"
            return 0
            ;;
    esac
    return 1
}

curl() {
    echo "curl-called" >> "$TMPDIR_PATH/fallback.log"
    return 1
}

if install_uv_multi_source; then
    echo "ok"
else
    echo "failed"
    exit 1
fi

cat "$TMPDIR_PATH/pip_args.log"
[ -f "$TMPDIR_PATH/fallback.log" ] && cat "$TMPDIR_PATH/fallback.log"
''')

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert "--user" in result.stdout
    assert "curl-called" not in result.stdout
```

- [ ] **Step 2: 运行单测确认当前实现先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_install_uv_multi_source_prefers_pip_user_before_fallback -q`
Expected: `FAIL`（当前 pip 分支未强制 `--user`，断言不满足）

- [ ] **Step 3: 新增“pip 失败后必须 fallback”失败测试**

```python
def test_install_uv_multi_source_falls_back_after_pip_user_failures():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin"

pip3() {
    echo "$*" >> "$TMPDIR_PATH/pip_args.log"
    return 1
}

curl() {
    echo "curl-called" >> "$TMPDIR_PATH/fallback.log"
    cat <<'EOF'
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/uv" <<'UVEOF'
#!/bin/sh
echo "uv 0.test"
UVEOF
chmod +x "$HOME/.local/bin/uv"
EOF
    return 0
}

if install_uv_multi_source; then
    echo "ok"
else
    echo "failed"
    exit 1
fi

cat "$TMPDIR_PATH/pip_args.log"
cat "$TMPDIR_PATH/fallback.log"
''')

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert "--user" in result.stdout
    assert "curl-called" in result.stdout
```

- [ ] **Step 4: 运行新增测试确认失败基线**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_install_uv_multi_source_falls_back_after_pip_user_failures -q`
Expected: `FAIL`（改造前行为与断言不完全一致）

- [ ] **Step 5: 提交测试基线**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test(uv): add failing coverage for pip --user priority"
```

### Task 2: 最小实现改造 `_common.sh`（归拢配置，减少重复）

**Files:**
- Modify: `scripts/_common.sh:81-149`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 提取 pip 命令检测与安装尝试辅助函数**

```sh
_detect_pip_cmd() {
    if command -v pip3 >/dev/null 2>&1; then
        echo "pip3"
    elif command -v pip >/dev/null 2>&1; then
        echo "pip"
    fi
}

_try_install_uv_with_pip() {
    # $1: pip command, $2: label, $3..: extra pip args
    local pip_cmd label
    pip_cmd="$1"
    label="$2"
    shift 2

    print_warning "尝试 pip 安装 uv（${label}，--user）..."
    if "$pip_cmd" install uv --quiet --user "$@" 2>/dev/null; then
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv >/dev/null 2>&1
        return $?
    fi
    return 1
}
```

- [ ] **Step 2: 用配置化循环替换重复 pip 分支**

```sh
install_uv_multi_source() {
    local PIP_CMD
    PIP_CMD="$(_detect_pip_cmd)"

    if ! command -v uv >/dev/null 2>&1 && [ -n "$PIP_CMD" ]; then
        if _try_install_uv_with_pip "$PIP_CMD" "清华镜像" \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn; then
            return 0
        fi

        if _try_install_uv_with_pip "$PIP_CMD" "官方 PyPI"; then
            return 0
        fi
    fi

    # 保留原有 fallback：官方脚本 -> mamba/conda -> brew
    # （此处沿用现有分支，不改变顺序）
    ...
}
```

- [ ] **Step 3: 统一失败提示文案（避免多处分叉）**

```sh
print_uv_manual_install_hint() {
    print_info "  pip3 install --user uv"
    print_info "  pip3 install --user uv -i https://pypi.tuna.tsinghua.edu.cn/simple/"
    print_info "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    print_info "  详见: https://docs.astral.sh/uv/getting-started/installation/"
}
```

并在 `scripts/install.sh` / `scripts/setup.sh` 现有错误分支中通过 source 后调用该函数（不复制文案）。

- [ ] **Step 4: 运行两条定向测试确认转绿**

Run:
- `uv run pytest tests/test_entry_lazy_init.py::test_install_uv_multi_source_prefers_pip_user_before_fallback -q`
- `uv run pytest tests/test_entry_lazy_init.py::test_install_uv_multi_source_falls_back_after_pip_user_failures -q`

Expected: 两条都 `PASS`

- [ ] **Step 5: 提交实现**

```bash
git add scripts/_common.sh tests/test_entry_lazy_init.py scripts/install.sh scripts/setup.sh
git commit -m "refactor(uv): prefer pip --user and deduplicate install flow"
```

### Task 3: 入口一致性与回归验证

**Files:**
- Modify: `tests/test_entry_lazy_init.py`（若需补 1 条入口一致性用例）
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 新增入口一致性测试（install/setup/bin 仍通过 `check_and_install_uv`）**

```python
def test_entry_scripts_still_source_common_sh_for_uv_logic():
    for rel in ENTRY_SCRIPTS:
        content = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert 'scripts/_common.sh' in content
        assert 'check_and_install_uv' in content or '_lazy_init' in content
```

- [ ] **Step 2: 运行入口相关测试子集**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "install_uv_multi_source or entry_scripts_still_source_common_sh_for_uv_logic" -q`
Expected: `PASS`

- [ ] **Step 3: 提交入口一致性回归**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test(entry): verify uv install flow remains centralized"
```

### Task 4: 同步文档规则并做最终验证

**Files:**
- Modify: `tests/TEST_PLAN.md`
- Modify: `CLAUDE.md`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 更新测试计划文档**

在 `tests/TEST_PLAN.md` 新增场景：

```markdown
### uv 安装策略回归
- pip 可用时优先 `pip --user` 安装 uv
- pip 失败后继续 fallback（官方脚本/conda/mamba/brew）
- install/setup/bin 懒初始化入口均复用 `_common.sh` 策略
```

- [ ] **Step 2: 更新 CLAUDE.md 开发须知**

在安装相关说明中补充：

```markdown
- uv 安装策略：优先 `pip --user`，失败后按多来源 fallback 自动恢复
```

- [ ] **Step 3: 运行最终回归命令**

Run:
- `uv run pytest tests/test_entry_lazy_init.py -q`
- `uv run python3 tests/test_runtime_config.py`

Expected:
- `test_entry_lazy_init.py` 全量通过
- `test_runtime_config.py` 保持通过（`uv_path` 行为无回归）

- [ ] **Step 4: 最终提交**

```bash
git add tests/TEST_PLAN.md CLAUDE.md
git commit -m "docs: sync uv user-first install strategy and test plan"
```

- [ ] **Step 5: 手工验收命令（记录在 PR 描述）**

Run:
- `sh scripts/install.sh --help`
- `sh scripts/setup.sh --help`

Expected: 命令可执行，未引入 shell 语法错误。

## Self-Review

1. **Spec coverage:**
   - user-first pip 策略：Task 1/2 覆盖
   - pip 失败 fallback：Task 1/2 覆盖
   - 配置归拢、减少重复：Task 2 覆盖
   - 全入口一致性：Task 3 覆盖
   - 测试与文档同步：Task 4 覆盖
2. **Placeholder scan:** 未包含 TBD/TODO/“类似 Task N”等占位内容。
3. **Type consistency:** 函数名与路径均与现有代码一致（`install_uv_multi_source` / `check_and_install_uv` / `tests/test_entry_lazy_init.py`）。
