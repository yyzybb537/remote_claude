# setup uv 多源与 trusted-host 优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 `uv` 安装与 `uv sync` 的 PyPI 源回退顺序为官方→阿里→清华，并在每次尝试中显式附加 host trust 参数，只有全部源失败时才报错。

**Architecture:** 将 PyPI 源定义集中维护在 `scripts/_common.sh`，让 `pip` 安装链路和 `scripts/setup.sh` 中的依赖同步链路共用同一套 source metadata。`uv` 安装继续保留现有官方脚本 / conda / mamba / brew 兜底逻辑；`uv sync` 改为按统一源清单顺序尝试，替代当前的预探测分支。

**Tech Stack:** POSIX shell, pip, uv, pytest

---

### Task 1: 调整共享 PyPI 源顺序与 pip 多源断言

**Files:**
- Modify: `scripts/_common.sh:189-248`
- Test: `tests/test_entry_lazy_init.py:192-352`

- [ ] **Step 1: 先写失败测试，锁定新的源顺序**

```python
def test_install_uv_multi_source_uses_official_then_aliyun_then_tuna_order():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/calls.log"

pip3() {
    echo "$*" >> "$TMPDIR_PATH/calls.log"
    return 1
}

pip() { pip3 "$@"; }
curl() { return 1; }
install_uv_multi_source || true
cat "$TMPDIR_PATH/calls.log"
''')

    assert result.returncode == 0, result.stderr
    install_lines = [l for l in result.stdout.splitlines() if "install uv" in l]
    assert len(install_lines) >= 3
    assert "-i https://pypi.org/simple" in install_lines[0]
    assert "-i https://mirrors.aliyun.com/pypi/simple/" in install_lines[1]
    assert "-i https://pypi.tuna.tsinghua.edu.cn/simple/" in install_lines[2]
```

- [ ] **Step 2: 运行单测，确认它先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "official_then_aliyun_then_tuna_order" -v`
Expected: FAIL，当前顺序仍是清华→阿里→官方。

- [ ] **Step 3: 最小实现，调整共享源定义顺序**

```sh
_install_pypi_sources() {
    cat <<'EOF'
pypi|https://pypi.org/simple|pypi.org
aliyun|https://mirrors.aliyun.com/pypi/simple/|mirrors.aliyun.com
tuna|https://pypi.tuna.tsinghua.edu.cn/simple/|pypi.tuna.tsinghua.edu.cn
EOF
}
```

- [ ] **Step 4: 运行顺序与 trusted-host 相关测试**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "official_then_aliyun_then_tuna_order or trusted_host_for_all_pip_attempts or upgrades_pip_before_uv_install" -v`
Expected: PASS，且已有 trusted-host 断言继续通过。

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/test_entry_lazy_init.py scripts/_common.sh
git commit -m "test: lock uv mirror priority order"
```

### Task 2: 抽取可复用的 uv 多源执行器

**Files:**
- Modify: `scripts/_common.sh:223-343`
- Test: `tests/test_entry_lazy_init.py:330-392`

- [ ] **Step 1: 先写失败测试，约束 uv 命令也会逐源尝试并带 trust 参数**

```python
def test_run_uv_with_pypi_sources_uses_index_and_trusted_host_for_each_attempt():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/uv.log"

uv() {
    echo "$*" >> "$TMPDIR_PATH/uv.log"
    return 1
}

_run_uv_with_pypi_sources "uv-sync" sync || true
cat "$TMPDIR_PATH/uv.log"
''')

    assert result.returncode == 0, result.stderr
    uv_lines = [l for l in result.stdout.splitlines() if l.startswith("sync")]
    assert len(uv_lines) == 3
    assert "--index-url https://pypi.org/simple" in uv_lines[0]
    assert "--allow-insecure-host pypi.org" in uv_lines[0]
    assert "--index-url https://mirrors.aliyun.com/pypi/simple/" in uv_lines[1]
    assert "--allow-insecure-host mirrors.aliyun.com" in uv_lines[1]
    assert "--index-url https://pypi.tuna.tsinghua.edu.cn/simple/" in uv_lines[2]
    assert "--allow-insecure-host pypi.tuna.tsinghua.edu.cn" in uv_lines[2]
```

- [ ] **Step 2: 运行单测，确认辅助函数尚不存在而失败**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "run_uv_with_pypi_sources_uses_index_and_trusted_host" -v`
Expected: FAIL，提示 `_run_uv_with_pypi_sources` 未定义或输出不匹配。

- [ ] **Step 3: 最小实现，新增 uv 多源执行器**

```sh
_run_uv_with_pypi_sources() {
    # $1: stage, $2...: uv 基础参数
    local STAGE LABEL INDEX_URL HOST RC CMD_SUMMARY
    STAGE="$1"
    shift

    CMD_SUMMARY="uv $* --index-url <index> --allow-insecure-host <host>"

    while IFS='|' read -r LABEL INDEX_URL HOST; do
        [ -n "$LABEL" ] || continue

        uv "$@" --index-url "$INDEX_URL" --allow-insecure-host "$HOST" 2>/dev/null
        RC=$?
        if [ "$RC" -eq 0 ]; then
            _install_log "stage=$STAGE source=$LABEL success"
            return 0
        fi

        _log_install_fail "$STAGE" "$LABEL" "$CMD_SUMMARY" "$RC"
    done <<EOF
$(_install_pypi_sources)
EOF

    return 1
}
```

- [ ] **Step 4: 运行辅助函数相关测试**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "run_uv_with_pypi_sources_uses_index_and_trusted_host or common_install_fail_summary_contains_required_fields" -v`
Expected: PASS，日志摘要格式保持不变。

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/test_entry_lazy_init.py scripts/_common.sh
git commit -m "feat: add shared uv mirror retry helper"
```

### Task 3: 用共享执行器替换 setup.sh 的 uv sync 预探测逻辑

**Files:**
- Modify: `scripts/setup.sh:297-335`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 先写失败测试，锁定 setup.sh 不再依赖 curl 探测**

```python
def test_setup_install_dependencies_uses_uv_retry_helper_instead_of_curl_probe():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "_run_uv_with_pypi_sources \"uv-sync\" sync" in content
    assert "curl -sSf --connect-timeout 3" not in content
```

- [ ] **Step 2: 运行单测，确认它先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "uses_uv_retry_helper_instead_of_curl_probe" -v`
Expected: FAIL，当前文件仍含 curl 探测分支。

- [ ] **Step 3: 最小实现，改写 install_dependencies**

```sh
install_dependencies() {
    print_header "安装 Python 依赖"

    cd "$PROJECT_DIR"

    if [ ! -f "pyproject.toml" ]; then
        print_error "未找到 pyproject.toml 文件"
        return 1
    fi

    print_info "按官方 → 阿里 → 清华顺序尝试同步依赖..."
    _run_uv_with_pypi_sources "uv-sync" sync || {
        print_error "依赖安装失败"
        return 1
    }

    print_success "依赖安装完成"
    uv run python3 scripts/report_install.py >/dev/null 2>&1 &
}
```

- [ ] **Step 4: 运行 setup 相关回归测试**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "uses_uv_retry_helper_instead_of_curl_probe or setup_runtime_creation_stays_in_success_flow or setup_completion_uses_scripts_path" -v`
Expected: PASS，且 setup 的既有顺序约束未被破坏。

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/test_entry_lazy_init.py scripts/setup.sh
git commit -m "feat: retry uv sync across shared mirrors"
```

### Task 4: 验证多源回退与安装兜底行为未回归

**Files:**
- Test: `tests/test_entry_lazy_init.py:192-392`
- Modify: `tests/test_entry_lazy_init.py`（仅在前述测试需要补充断言时）

- [ ] **Step 1: 补一个失败测试，确认 pip 全失败后仍会走后续兜底**

```python
def test_install_uv_multi_source_keeps_fallback_after_all_pypi_sources_fail():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/pip_args.log"
: > "$TMPDIR_PATH/fallback.log"

pip3() {
    echo "$*" >> "$TMPDIR_PATH/pip_args.log"
    return 1
}

pip() { pip3 "$@"; }

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

install_uv_multi_source || exit 1
cat "$TMPDIR_PATH/pip_args.log"
cat "$TMPDIR_PATH/fallback.log"
''')

    assert result.returncode == 0, result.stderr
    pip_uv_lines = [l for l in result.stdout.splitlines() if "install uv" in l]
    assert len(pip_uv_lines) == 3
    assert "curl-called" in result.stdout
```

- [ ] **Step 2: 运行单测，确认当前行为与新断言对齐**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "keeps_fallback_after_all_pypi_sources_fail or falls_back_after_pip_user_failures" -v`
Expected: 若断言还不够精确则先失败；补齐后应通过。

- [ ] **Step 3: 按需补充最小断言，不改实现语义**

```python
# 若现有 test_install_uv_multi_source_falls_back_after_pip_user_failures
# 已足够覆盖，可仅增强断言，不新增实现代码。
pip_uv_lines = [l for l in result.stdout.splitlines() if "install uv" in l]
assert len(pip_uv_lines) == 3
assert "-i https://pypi.org/simple" in pip_uv_lines[0]
assert "-i https://mirrors.aliyun.com/pypi/simple/" in pip_uv_lines[1]
assert "-i https://pypi.tuna.tsinghua.edu.cn/simple/" in pip_uv_lines[2]
```

- [ ] **Step 4: 运行完整目标测试集**

Run: `uv run pytest tests/test_entry_lazy_init.py -k "install_uv_multi_source or run_uv_with_pypi_sources or setup_" -v`
Expected: PASS，覆盖源顺序、trusted-host / allow-insecure-host、setup 回退和日志语义。

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test: cover uv mirror fallback behavior"
```

### Task 5: 完整回归并同步文档约束

**Files:**
- Modify: `CLAUDE.md`（如需更新镜像策略说明）
- Modify: `tests/TEST_PLAN.md`（补充新增回退测试场景）
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 检查文档是否需要同步当前规则变更**

```markdown
- `CLAUDE.md` 中已有“镜像策略”表述：`pip` 升级与 `uv/pip` 安装统一使用内置镜像回退策略，并附加 `--trusted-host`
- 若新增 `uv sync` 也统一走官方→阿里→清华回退，需要把该行为写入 `CLAUDE.md` 与 `tests/TEST_PLAN.md`
```

- [ ] **Step 2: 如文档缺失则补充最小内容**

```markdown
# CLAUDE.md 补充示例
- **依赖同步镜像策略：** `uv sync` 与 `pip/uv` 安装统一使用官方→阿里→清华顺序回退，并按源附加 host trust 参数

# tests/TEST_PLAN.md 补充示例
- 验证 `uv sync` 在官方失败时可依次回退到阿里、清华，全部失败后才报错
```

- [ ] **Step 3: 运行最终验证命令**

Run: `uv run pytest tests/test_entry_lazy_init.py -v`
Expected: PASS

Run: `uv run pytest tests/test_portable_python.py -k "uv_available" -v`
Expected: PASS 或在环境缺少 uv 时得到与当前基线一致的结果；若该环境不稳定，至少确认未引入新的失败。

- [ ] **Step 4: 查看工作区并准备总提交**

Run: `git status --short`
Expected: 仅包含本次计划涉及的脚本、测试和必要文档修改。

- [ ] **Step 5: 提交最终结果**

```bash
git add scripts/_common.sh scripts/setup.sh tests/test_entry_lazy_init.py CLAUDE.md tests/TEST_PLAN.md
git commit -m "feat: unify uv mirror fallback strategy"
```
