# 安装链路镜像与 pip 升级增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在安装 uv 前先执行 `pip --user` 升级，并让 pip/uv 安装统一走固定多镜像 + `--trusted-host` 回退，同时对安装与脚本步骤失败输出统一的分级失败日志摘要。

**Architecture:** 以 `scripts/_common.sh` 为唯一安装收敛点：新增固定镜像源枚举、通用 pip 多源执行器、pip 升级函数与失败摘要日志函数；`check_and_install_uv()` 先升级 pip 再装 uv。`scripts/install.sh` 与 `scripts/setup.sh` 保持调用公共能力并补充脚本级失败日志打点。测试采用 TDD：先补失败用例，再做最小实现，最后回归。

**Tech Stack:** POSIX sh (`/bin/sh`), Python `pytest`, 现有安装脚本与 lazy-init 测试基建

---

## 文件结构与职责

- `scripts/_common.sh`
  - 新增固定镜像源列表（tuna/aliyun/pypi）
  - 新增安装失败摘要日志函数（`[install-fail]`）
  - 新增脚本失败摘要日志函数（`[script-fail]`）
  - 新增通用 pip 多源执行器
  - 新增 pip 升级函数（`--user`）
  - 调整 uv pip 安装函数以复用多源执行器
  - 调整 `check_and_install_uv()` 顺序：先 pip 升级，再 uv 安装
- `scripts/install.sh`
  - 在主流程失败分支调用脚本失败日志函数（保持现有 `_install_fail_hint`）
- `scripts/setup.sh`
  - 在关键失败分支调用脚本失败日志函数（保持现有错误退出语义）
- `tests/test_entry_lazy_init.py`
  - 新增/更新用例：pip 升级顺序、镜像+trusted-host 参数、失败摘要日志字段
- `tests/TEST_PLAN.md`
  - 增补安装链路回归项（pip 升级、多镜像、失败摘要日志）
- `CLAUDE.md`
  - 同步安装策略约束（pip 升级前置 + 固定镜像 + 失败摘要日志）

---

### Task 1: 先补失败测试（顺序、参数、日志）

**Files:**
- Modify: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 添加“pip 升级先于 uv 安装”测试（先失败）**

```python
def test_install_uv_multi_source_upgrades_pip_before_uv_install():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$TMPDIR_PATH/bin" "$HOME/.local/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/calls.log"

pip3() {
    echo "$*" >> "$TMPDIR_PATH/calls.log"
    case " $* " in
        *" install --upgrade pip --user "*)
            return 0
            ;;
        *" install uv "*)
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

pip() { pip3 "$@"; }
curl() { return 1; }

install_uv_multi_source || exit 1
cat "$TMPDIR_PATH/calls.log"
''')

    assert result.returncode == 0, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    up_idx = next(i for i, s in enumerate(lines) if "install --upgrade pip --user" in s)
    uv_idx = next(i for i, s in enumerate(lines) if "install uv" in s)
    assert up_idx < uv_idx
```

- [ ] **Step 2: 添加“pip 升级与 uv 安装都带 trusted-host”测试（先失败）**

```python
def test_install_uv_multi_source_uses_trusted_host_for_all_pip_attempts():
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
    pip_lines = [l for l in result.stdout.splitlines() if "install" in l]
    assert pip_lines, "应至少有一次 pip install 尝试"
    assert all("--trusted-host" in l for l in pip_lines)
```

- [ ] **Step 3: 添加“失败摘要包含 stage/source/cmd/exit_code”测试（先失败）**

```python
def test_common_install_fail_summary_contains_required_fields():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
INSTALL_LOG_FILE="$TMPDIR_PATH/install.log"

_log_install_fail "pip-upgrade" "tuna" "pip install --upgrade pip --user -i <index> --trusted-host <host>" 9
cat "$INSTALL_LOG_FILE"
''')

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "[install-fail][pip-upgrade]" in out
    assert "source=tuna" in out
    assert "cmd=\"pip install --upgrade pip --user -i <index> --trusted-host <host>\"" in out
    assert "exit_code=9" in out
```

- [ ] **Step 4: 运行新增用例并确认失败**

Run:
```bash
uv run pytest \
  tests/test_entry_lazy_init.py::test_install_uv_multi_source_upgrades_pip_before_uv_install \
  tests/test_entry_lazy_init.py::test_install_uv_multi_source_uses_trusted_host_for_all_pip_attempts \
  tests/test_entry_lazy_init.py::test_common_install_fail_summary_contains_required_fields -q
```

Expected:
- FAIL（当前实现尚未满足三项新约束）

- [ ] **Step 5: 提交（仅测试）**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test(install): add failing coverage for pip-upgrade mirror flow and fail summaries"
```

---

### Task 2: 在 `_common.sh` 实现多镜像执行器与 pip 升级前置

**Files:**
- Modify: `scripts/_common.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 新增固定内置镜像源枚举函数**

```sh
_install_pypi_sources() {
    cat <<'EOF'
tuna|https://pypi.tuna.tsinghua.edu.cn/simple/|pypi.tuna.tsinghua.edu.cn
aliyun|https://mirrors.aliyun.com/pypi/simple/|mirrors.aliyun.com
pypi|https://pypi.org/simple|pypi.org
EOF
}
```

- [ ] **Step 2: 新增失败摘要日志函数（安装级）与脚本级失败日志函数**

```sh
_log_install_fail() {
    # $1: stage, $2: source, $3: cmd-summary, $4: exit-code
    local STAGE SOURCE CMD_SUMMARY EXIT_CODE
    STAGE="$1"; SOURCE="$2"; CMD_SUMMARY="$3"; EXIT_CODE="$4"
    printf '[install-fail][%s] source=%s cmd="%s" exit_code=%s\n' \
        "$STAGE" "${SOURCE:-na}" "$CMD_SUMMARY" "$EXIT_CODE" >> "$INSTALL_LOG_FILE"
}

_log_script_fail() {
    # $1: stage, $2: cmd-summary, $3: exit-code
    local STAGE CMD_SUMMARY EXIT_CODE
    STAGE="$1"; CMD_SUMMARY="$2"; EXIT_CODE="$3"
    printf '[script-fail][%s] cmd="%s" exit_code=%s\n' \
        "$STAGE" "$CMD_SUMMARY" "$EXIT_CODE" >> "$INSTALL_LOG_FILE"
}
```

- [ ] **Step 3: 新增通用 pip 多源执行器（自动附加 -i/--trusted-host）**

```sh
_run_pip_install_with_mirrors() {
    # $1: stage, $2: pip_cmd, $3...: base args
    local STAGE PIP_CMD LABEL INDEX_URL HOST RC CMD_SUMMARY
    STAGE="$1"
    PIP_CMD="$2"
    shift 2

    _install_pypi_sources | while IFS='|' read -r LABEL INDEX_URL HOST; do
        CMD_SUMMARY="$PIP_CMD $* -i <index> --trusted-host <host>"
        if "$PIP_CMD" "$@" -i "$INDEX_URL" --trusted-host "$HOST" 2>/dev/null; then
            _install_log "stage=$STAGE source=$LABEL success"
            return 0
        fi
        RC=$?
        _log_install_fail "$STAGE" "$LABEL" "$CMD_SUMMARY" "$RC"
    done
    return 1
}
```

- [ ] **Step 4: 新增 pip 升级函数并在 `install_uv_multi_source` 中前置调用**

```sh
_upgrade_pip_before_uv_install() {
    # $1: pip_cmd
    local PIP_CMD
    PIP_CMD="$1"
    [ -n "$PIP_CMD" ] || return 1
    _run_pip_install_with_mirrors "pip-upgrade" "$PIP_CMD" install --upgrade pip --user
}

install_uv_multi_source() {
    local PIP_CMD
    PIP_CMD="$(_detect_pip_cmd)"

    if ! command -v uv >/dev/null 2>&1 && [ -n "$PIP_CMD" ]; then
        _upgrade_pip_before_uv_install "$PIP_CMD" || true
    fi

    if ! command -v uv >/dev/null 2>&1 && [ -n "$PIP_CMD" ]; then
        _run_pip_install_with_mirrors "uv-install" "$PIP_CMD" install uv --quiet --user --break-system-packages && {
            _resolve_uv_path
            command -v uv >/dev/null 2>&1
            return $?
        }
    fi

    # 其余 fallback（curl/conda/mamba/brew）保持原逻辑
    # ...
}
```

- [ ] **Step 5: 运行 Task 1 用例并确认转绿**

Run:
```bash
uv run pytest \
  tests/test_entry_lazy_init.py::test_install_uv_multi_source_upgrades_pip_before_uv_install \
  tests/test_entry_lazy_init.py::test_install_uv_multi_source_uses_trusted_host_for_all_pip_attempts \
  tests/test_entry_lazy_init.py::test_common_install_fail_summary_contains_required_fields -q
```

Expected:
- PASS

- [ ] **Step 6: 提交 Task 2**

```bash
git add scripts/_common.sh tests/test_entry_lazy_init.py
git commit -m "feat(install): add mirror-based pip runner and pre-upgrade pip before uv install"
```

---

### Task 3: 接入脚本级失败摘要日志（install/setup）

**Files:**
- Modify: `scripts/install.sh`
- Modify: `scripts/setup.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 在 install 关键失败分支记录 `[script-fail]`**

```sh
# scripts/install.sh 示例（失败分支）
detect_os || { rc=$?; _log_script_fail "precheck" "detect_os" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
check_and_install_uv_install || { rc=$?; _log_script_fail "uv" "check_and_install_uv_install" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
setup_virtual_env || { rc=$?; _log_script_fail "deps" "setup_virtual_env" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
verify_installation || { rc=$?; _log_script_fail "verify" "verify_installation" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
run_init_script || { rc=$?; _log_script_fail "setup" "run_init_script" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
```

- [ ] **Step 2: 在 setup 关键失败分支记录 `[script-fail]`**

```sh
# scripts/setup.sh 示例（失败分支）
check_os || { rc=$?; _log_script_fail "setup-precheck" "check_os" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
check_uv || { rc=$?; _log_script_fail "setup-uv" "check_uv" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
install_dependencies || { rc=$?; _log_script_fail "setup-deps" "install_dependencies" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
init_config_files || { rc=$?; _log_script_fail "setup-config" "init_config_files" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }
```

- [ ] **Step 3: 添加脚本级失败日志测试**

```python
def test_install_sh_failure_logs_script_fail_summary(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    install_sh = scripts_dir / "install.sh"
    install_sh.write_text((REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8"), encoding="utf-8")
    install_sh.chmod(0o755)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    setup_sh = scripts_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 17\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    uv_stub = tmp_path / "uv"
    uv_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv_stub.chmod(0o755)

    result = subprocess.run(
        ["sh", str(install_sh)],
        text=True,
        capture_output=True,
        cwd=project_dir,
        env={**os.environ, "HOME": str(project_dir), "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    log = Path("/tmp/remote-claude-install.log").read_text(encoding="utf-8")
    assert result.returncode != 0
    assert "[script-fail]" in log
```

- [ ] **Step 4: 运行新增用例并确认通过**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_install_sh_failure_logs_script_fail_summary -q
```

Expected:
- PASS

- [ ] **Step 5: 提交 Task 3**

```bash
git add scripts/install.sh scripts/setup.sh tests/test_entry_lazy_init.py
git commit -m "feat(install): add script-fail summaries for install and setup stages"
```

---

### Task 4: 文档与测试计划同步

**Files:**
- Modify: `CLAUDE.md`
- Modify: `tests/TEST_PLAN.md`

- [ ] **Step 1: 在 CLAUDE.md 同步安装策略约束**

```markdown
- **pip 升级前置：** 在 pip 安装 uv 前，先对最终选中的 pip 执行 `install --upgrade pip --user`
- **镜像策略：** pip 升级与 uv/pip 安装统一使用固定内置镜像回退，并附加 `--trusted-host`
- **失败日志粒度：** 任一步骤失败写入 `/tmp/remote-claude-install.log`，并包含 stage/source/cmd/exit_code 摘要
```

- [ ] **Step 2: 在 TEST_PLAN.md 增加回归条目**

```markdown
- 安装链路回归：
  - pip 升级应先于 uv pip 安装触发
  - pip 升级与 uv 安装应带 `-i` 与 `--trusted-host`
  - 安装失败日志应包含 `[install-fail]` + stage/source/cmd/exit_code
  - 脚本失败日志应包含 `[script-fail]` + stage/cmd/exit_code
```

- [ ] **Step 3: 运行目标测试文件回归**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py -q
```

Expected:
- PASS

- [ ] **Step 4: 提交 Task 4**

```bash
git add CLAUDE.md tests/TEST_PLAN.md tests/test_entry_lazy_init.py
git commit -m "docs(test): sync install mirror and failure-summary requirements"
```

---

### Task 5: 全量验收与收尾

**Files:**
- Verify only: `scripts/_common.sh`, `scripts/install.sh`, `scripts/setup.sh`, `tests/test_entry_lazy_init.py`, `CLAUDE.md`, `tests/TEST_PLAN.md`

- [ ] **Step 1: 运行安装链路相关测试组合**

Run:
```bash
uv run pytest \
  tests/test_entry_lazy_init.py \
  tests/test_runtime_config.py::test_set_get_uv_path \
  tests/test_runtime_config.py::test_validate_uv_path -q
```

Expected:
- PASS

- [ ] **Step 2: 快速人工验证日志字段完整性**

Run:
```bash
sh scripts/install.sh --lazy || true
tail -n 30 /tmp/remote-claude-install.log
```

Expected:
- 日志中可见 `[install]` 阶段记录
- 失败场景可见 `[install-fail]` 或 `[script-fail]`
- 失败摘要包含 `stage`/`source(如适用)`/`cmd`/`exit_code`

- [ ] **Step 3: 最终提交**

```bash
git add scripts/_common.sh scripts/install.sh scripts/setup.sh tests/test_entry_lazy_init.py CLAUDE.md tests/TEST_PLAN.md
git commit -m "feat(install): enforce pip pre-upgrade, mirror trusted-host fallback, and unified failure summaries"
```

---

## 自检结果（plan self-review）

1. **Spec 覆盖检查**
- pip 安装 uv 前升级 pip（`--user`）：Task 1/2 覆盖。
- pip/uv 安装多镜像 + `--trusted-host`：Task 1/2 覆盖。
- 任一步骤失败记录日志且含摘要字段：Task 1/2/3 覆盖。
- 文档同步：Task 4 覆盖。

2. **占位符检查**
- 未使用 TODO/TBD/“后续补充”等占位描述。
- 每个代码步骤均给出可执行片段或明确命令。

3. **命名一致性检查**
- 统一使用 `_run_pip_install_with_mirrors`、`_upgrade_pip_before_uv_install`、`_log_install_fail`、`_log_script_fail`。
- 日志字段统一 `stage/source/cmd/exit_code`。
