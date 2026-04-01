# Shell Path Centralization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 shell 脚本中的路径常量、目录初始化、模板校验与复制统一收敛到 `scripts/_common.sh`，并删除旧兼容逻辑。

**Architecture:** 以 `scripts/_common.sh` 作为 shell 路径真相源，新增一组 `REMOTE_CLAUDE_*` 变量和小粒度辅助函数，其他脚本只消费这些变量/函数，不再自行拼接 `$HOME/.remote-claude`、`/tmp/remote-claude` 或模板路径。实现时遵循 TDD：先更新和新增失败测试，再做最小实现，最后删掉旧兼容分支并用守卫测试防回归。

**Tech Stack:** POSIX sh、pytest、uv、jq（仅脚本现有依赖场景）

---

## File Structure

### 需要修改的文件

- `scripts/_common.sh`
  - 新增统一路径变量初始化：`REMOTE_CLAUDE_HOME_DIR`、`REMOTE_CLAUDE_SOCKET_DIR`、`REMOTE_CLAUDE_ENV_FILE`、`REMOTE_CLAUDE_SETTINGS_FILE`、`REMOTE_CLAUDE_STATE_FILE`、模板路径、lark 相关路径
  - 新增小函数：`rc_init_paths`、`rc_ensure_home_dir`、`rc_ensure_socket_dir`、`rc_require_file`、`rc_copy_if_missing`
  - 将现有 uv 路径读写从旧 `runtime.json` 切换到 `state.json`

- `scripts/setup.sh`
  - 删除旧配置迁移逻辑：`migrate_legacy_notify_files`、`migrate_claude_command`
  - 将 `configure_lark`、`create_directories`、`init_config_files` 改为只使用 `_common.sh` 统一路径 API
  - 不再出现 `config.json`、`runtime.json`、`config.default.json`、`runtime.default.json`、`lark_group_mapping.json`

- `scripts/check-env.sh`
  - 删除本地路径真相源定义，改为使用 `REMOTE_CLAUDE_ENV_FILE` / `REMOTE_CLAUDE_ENV_TEMPLATE`

- `scripts/uninstall.sh`
  - 将运行时目录、用户目录、PID/status/log 路径收口到 `_common.sh`
  - 删除对旧 `config.json` / `runtime.json` 的清理逻辑

- `scripts/install.sh`
  - 若存在用户目录、socket 目录、配置文件路径使用，统一切换到 `_common.sh`
  - 保持安装流程不变

- `scripts/test_lark_management.sh`
  - 用 `_common.sh` 统一的 lark PID/status/log 路径变量替换硬编码路径

- `tests/test_entry_lazy_init.py`
  - 新增 `_common.sh` 路径 API 测试
  - 更新 shell 脚本行为测试，使其只断言 `settings.json` / `state.json` / `env.example`
  - 增加源码守卫测试，禁止运行时 shell 脚本重新引入硬编码路径和旧兼容文件名

### 可选读取但不一定修改

- `docs/superpowers/specs/2026-04-01-shell-path-vars-centralization-design.md`
  - 作为实现对照，不需要改动

---

### Task 1: 为 `_common.sh` 路径 API 写失败测试

**Files:**
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写 `_common.sh` 统一路径变量测试**

```python
def test_common_exports_centralized_runtime_paths(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["sh"],
        input=f"""#!/bin/sh
set -e
HOME='{tmp_path / 'home'}'
mkdir -p "$HOME"
PROJECT_DIR='{project_dir}'
. '{common_sh}'
printf 'home=%s\n' "$REMOTE_CLAUDE_HOME_DIR"
printf 'socket=%s\n' "$REMOTE_CLAUDE_SOCKET_DIR"
printf 'env=%s\n' "$REMOTE_CLAUDE_ENV_FILE"
printf 'settings=%s\n' "$REMOTE_CLAUDE_SETTINGS_FILE"
printf 'state=%s\n' "$REMOTE_CLAUDE_STATE_FILE"
printf 'env_template=%s\n' "$REMOTE_CLAUDE_ENV_TEMPLATE"
printf 'settings_template=%s\n' "$REMOTE_CLAUDE_SETTINGS_TEMPLATE"
printf 'state_template=%s\n' "$REMOTE_CLAUDE_STATE_TEMPLATE"
""",
        text=True,
        capture_output=True,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert f"home={tmp_path / 'home' / '.remote-claude'}" in result.stdout
    assert "socket=/tmp/remote-claude" in result.stdout
    assert f"env={tmp_path / 'home' / '.remote-claude' / '.env'}" in result.stdout
    assert f"settings={tmp_path / 'home' / '.remote-claude' / 'settings.json'}" in result.stdout
    assert f"state={tmp_path / 'home' / '.remote-claude' / 'state.json'}" in result.stdout
```

- [ ] **Step 2: 写 `rc_copy_if_missing` 和 `rc_require_file` 的失败测试**

```python
def test_common_copy_if_missing_preserves_existing_file(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("from-template\n", encoding="utf-8")
    dst.write_text("keep-existing\n", encoding="utf-8")

    result = subprocess.run(
        ["sh"],
        input=f"""#!/bin/sh
set -e
HOME='{tmp_path / 'home'}'
mkdir -p "$HOME"
PROJECT_DIR='{project_dir}'
. '{common_sh}'
rc_copy_if_missing '{src}' '{dst}' 'dst'
cat '{dst}'
""",
        text=True,
        capture_output=True,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("keep-existing")


def test_common_require_file_returns_non_zero_for_missing_file(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    missing = tmp_path / "missing.txt"
    result = subprocess.run(
        ["sh"],
        input=f"""#!/bin/sh
set +e
HOME='{tmp_path / 'home'}'
mkdir -p "$HOME"
PROJECT_DIR='{project_dir}'
. '{common_sh}'
rc_require_file '{missing}' 'missing-file'
echo rc:$?
""",
        text=True,
        capture_output=True,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert "rc:1" in result.stdout
    assert "missing-file" in result.stderr or "missing-file" in result.stdout
```

- [ ] **Step 3: 运行定向测试，确认先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_common_exports_centralized_runtime_paths tests/test_entry_lazy_init.py::test_common_copy_if_missing_preserves_existing_file tests/test_entry_lazy_init.py::test_common_require_file_returns_non_zero_for_missing_file -q`

Expected: FAIL，提示 `_common.sh` 尚未导出 `REMOTE_CLAUDE_*` 变量或缺少 `rc_copy_if_missing` / `rc_require_file`

- [ ] **Step 4: 最小实现 `_common.sh` 路径 API**

```sh
rc_init_paths() {
    REMOTE_CLAUDE_HOME_DIR="$HOME/.remote-claude"
    REMOTE_CLAUDE_SOCKET_DIR="/tmp/remote-claude"
    REMOTE_CLAUDE_ENV_FILE="$REMOTE_CLAUDE_HOME_DIR/.env"
    REMOTE_CLAUDE_SETTINGS_FILE="$REMOTE_CLAUDE_HOME_DIR/settings.json"
    REMOTE_CLAUDE_STATE_FILE="$REMOTE_CLAUDE_HOME_DIR/state.json"
    REMOTE_CLAUDE_ENV_TEMPLATE="$PROJECT_DIR/resources/defaults/env.example"
    REMOTE_CLAUDE_SETTINGS_TEMPLATE="$PROJECT_DIR/resources/defaults/settings.json.example"
    REMOTE_CLAUDE_STATE_TEMPLATE="$PROJECT_DIR/resources/defaults/state.json.example"
    REMOTE_CLAUDE_LARK_PID_FILE="$REMOTE_CLAUDE_SOCKET_DIR/lark.pid"
    REMOTE_CLAUDE_LARK_STATUS_FILE="$REMOTE_CLAUDE_SOCKET_DIR/lark.status"
    REMOTE_CLAUDE_LARK_LOG_FILE="$REMOTE_CLAUDE_HOME_DIR/lark_client.log"
    export REMOTE_CLAUDE_HOME_DIR REMOTE_CLAUDE_SOCKET_DIR
    export REMOTE_CLAUDE_ENV_FILE REMOTE_CLAUDE_SETTINGS_FILE REMOTE_CLAUDE_STATE_FILE
    export REMOTE_CLAUDE_ENV_TEMPLATE REMOTE_CLAUDE_SETTINGS_TEMPLATE REMOTE_CLAUDE_STATE_TEMPLATE
    export REMOTE_CLAUDE_LARK_PID_FILE REMOTE_CLAUDE_LARK_STATUS_FILE REMOTE_CLAUDE_LARK_LOG_FILE
}

rc_ensure_home_dir() {
    mkdir -p "$REMOTE_CLAUDE_HOME_DIR"
}

rc_ensure_socket_dir() {
    mkdir -p "$REMOTE_CLAUDE_SOCKET_DIR"
}

rc_require_file() {
    if [ ! -f "$1" ]; then
        print_error "缺少$2: $1"
        return 1
    fi
    return 0
}

rc_copy_if_missing() {
    src="$1"
    dst="$2"
    label="$3"
    if [ -f "$dst" ]; then
        return 0
    fi
    cp "$src" "$dst"
    print_success "创建${label}: $dst"
}

rc_init_paths
```

- [ ] **Step 5: 重新运行定向测试，确认通过**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_common_exports_centralized_runtime_paths tests/test_entry_lazy_init.py::test_common_copy_if_missing_preserves_existing_file tests/test_entry_lazy_init.py::test_common_require_file_returns_non_zero_for_missing_file -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_entry_lazy_init.py scripts/_common.sh
git commit -m "refactor(shell): centralize common path helpers"
```

### Task 2: 将 `check-env.sh` 切换到统一路径 API

**Files:**
- Modify: `scripts/check-env.sh`
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写 `check-env.sh` 不再手写路径的失败测试**

```python
def test_check_env_uses_centralized_env_paths():
    content = (REPO_ROOT / "scripts" / "check-env.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_ENV_FILE" in content
    assert "REMOTE_CLAUDE_ENV_TEMPLATE" in content
    assert 'ENV_FILE="$HOME/.remote-claude/.env"' not in content
    assert 'resources/defaults/env.example' not in content
```

- [ ] **Step 2: 运行定向测试，确认先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_check_env_uses_centralized_env_paths -q`

Expected: FAIL，提示脚本仍有硬编码路径

- [ ] **Step 3: 最小修改 `scripts/check-env.sh`**

```sh
rc_ensure_home_dir || return 1
rc_require_file "$REMOTE_CLAUDE_ENV_TEMPLATE" "env 模板" || return 1

if [ "$REQUIRE_FEISHU" = "0" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ -f "$REMOTE_CLAUDE_ENV_FILE" ]; then
    APP_ID=$(grep -E '^FEISHU_APP_ID=' "$REMOTE_CLAUDE_ENV_FILE" | cut -d= -f2)
    APP_SECRET=$(grep -E '^FEISHU_APP_SECRET=' "$REMOTE_CLAUDE_ENV_FILE" | cut -d= -f2)
fi

rc_copy_if_missing "$REMOTE_CLAUDE_ENV_TEMPLATE" "$REMOTE_CLAUDE_ENV_FILE" ".env"
```

- [ ] **Step 4: 运行行为回归测试**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_check_env_allows_skip_when_feishu_not_required tests/test_entry_lazy_init.py::test_check_env_uses_centralized_env_paths -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/check-env.sh tests/test_entry_lazy_init.py
git commit -m "refactor(shell): route check-env through common paths"
```

### Task 3: 简化 `setup.sh`，删除旧兼容逻辑并切换统一路径 API

**Files:**
- Modify: `scripts/setup.sh`
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写旧兼容删除和统一路径守卫测试**

```python
def test_setup_uses_centralized_path_variables_only():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_ENV_FILE" in content
    assert "REMOTE_CLAUDE_SETTINGS_FILE" in content
    assert "REMOTE_CLAUDE_STATE_FILE" in content
    assert 'SOCKET_DIR="/tmp/remote-claude"' not in content
    assert 'USER_DATA_DIR="$HOME/.remote-claude"' not in content
    assert 'TEMPLATE_ENV="$PROJECT_DIR/resources/defaults/env.example"' not in content


def test_setup_no_longer_contains_legacy_config_migration_logic():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "migrate_legacy_notify_files" not in content
    assert "migrate_claude_command" not in content
    assert "config.default.json" not in content
    assert "runtime.default.json" not in content
    assert "lark_group_mapping.json" not in content
    assert "CLAUDE_COMMAND" not in content
    assert "ready_notify_enabled" not in content
    assert "urgent_notify_enabled" not in content
    assert "bypass_enabled" not in content
```

- [ ] **Step 2: 运行定向测试，确认先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_setup_uses_centralized_path_variables_only tests/test_entry_lazy_init.py::test_setup_no_longer_contains_legacy_config_migration_logic -q`

Expected: FAIL，提示仍存在旧路径和迁移逻辑

- [ ] **Step 3: 最小修改 `scripts/setup.sh` 的目录与模板处理**

```sh
configure_lark() {
    print_header "配置飞书客户端"
    rc_ensure_home_dir || return 1
    rc_require_file "$REMOTE_CLAUDE_ENV_TEMPLATE" ".env 模板" || return 1

    if [ -f "$REMOTE_CLAUDE_ENV_FILE" ]; then
        print_warning ".env 文件已存在（$REMOTE_CLAUDE_ENV_FILE），跳过配置"
        return
    fi

    printf "%b" "${YELLOW}是否需要配置飞书客户端？${NC} [y/N]: "
    read -r REPLY
    echo

    case "$REPLY" in
        [Yy]*)
            cp "$REMOTE_CLAUDE_ENV_TEMPLATE" "$REMOTE_CLAUDE_ENV_FILE"
            print_success ".env 文件已创建于 $REMOTE_CLAUDE_ENV_FILE"
            ;;
        *)
            print_info "跳过飞书配置（可稍后手动配置）"
            ;;
    esac
}

create_directories() {
    print_header "创建运行目录"
    rc_ensure_socket_dir
    print_success "创建目录: $REMOTE_CLAUDE_SOCKET_DIR"
    rc_ensure_home_dir
    print_success "创建目录: $REMOTE_CLAUDE_HOME_DIR"
}

init_config_files() {
    print_header "初始化配置文件"
    rc_require_file "$REMOTE_CLAUDE_SETTINGS_TEMPLATE" "settings 模板" || return 1
    rc_require_file "$REMOTE_CLAUDE_STATE_TEMPLATE" "state 模板" || return 1
    rc_ensure_home_dir || return 1
    rc_copy_if_missing "$REMOTE_CLAUDE_SETTINGS_TEMPLATE" "$REMOTE_CLAUDE_SETTINGS_FILE" "默认配置"
    rc_copy_if_missing "$REMOTE_CLAUDE_STATE_TEMPLATE" "$REMOTE_CLAUDE_STATE_FILE" "运行时配置"
}
```

- [ ] **Step 4: 删除旧迁移函数及其调用**

```sh
# 删除整个 migrate_legacy_notify_files() 函数
# 删除整个 migrate_claude_command() 函数
# 从 main/setup 流程中移除这两个函数的调用
```

- [ ] **Step 5: 运行关键回归测试**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_setup_still_initializes_runtime_file tests/test_entry_lazy_init.py::test_setup_lazy_initializes_config_and_runtime_when_missing tests/test_entry_lazy_init.py::test_setup_lazy_does_not_overwrite_existing_config_files tests/test_entry_lazy_init.py::test_setup_uses_centralized_path_variables_only tests/test_entry_lazy_init.py::test_setup_no_longer_contains_legacy_config_migration_logic -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/setup.sh tests/test_entry_lazy_init.py
git commit -m "refactor(shell): simplify setup path handling"
```

### Task 4: 将 `_common.sh` 和 `uninstall.sh` 从旧 `runtime.json` / `config.json` 切换到 `state.json` / `settings.json`

**Files:**
- Modify: `scripts/_common.sh`
- Modify: `scripts/uninstall.sh`
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写 uv 路径和卸载清理路径切换的失败测试**

```python
def test_common_reads_uv_path_from_state_json():
    content = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")
    assert 'state.json' in content
    assert 'runtime.json' not in content


def test_uninstall_uses_centralized_current_file_names_only():
    content = (REPO_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_STATE_FILE" in content
    assert "REMOTE_CLAUDE_SETTINGS_FILE" in content
    assert "REMOTE_CLAUDE_LARK_PID_FILE" in content
    assert 'runtime.json' not in content
    assert 'config.json' not in content
```

- [ ] **Step 2: 运行定向测试，确认先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_common_reads_uv_path_from_state_json tests/test_entry_lazy_init.py::test_uninstall_uses_centralized_current_file_names_only -q`

Expected: FAIL

- [ ] **Step 3: 最小修改 `_common.sh` 的 uv 路径存储文件**

```sh
_read_uv_path_from_runtime() {
    if [ -f "$REMOTE_CLAUDE_STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
        jq -r '.uv_path // empty' "$REMOTE_CLAUDE_STATE_FILE" 2>/dev/null
    fi
}

_save_uv_path_to_runtime() {
    UV_PATH="$1"
    if [ -f "$REMOTE_CLAUDE_STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
        TMP_FILE=$(mktemp)
        jq --arg path "$UV_PATH" '.uv_path = $path' "$REMOTE_CLAUDE_STATE_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$REMOTE_CLAUDE_STATE_FILE"
    fi
}
```

- [ ] **Step 4: 最小修改 `scripts/uninstall.sh`**

```sh
cleanup_runtime_files() {
    print_info "清理运行时文件..."

    if [ -f "$REMOTE_CLAUDE_LARK_PID_FILE" ]; then
        pid=$(cat "$REMOTE_CLAUDE_LARK_PID_FILE" 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
        rm -f "$REMOTE_CLAUDE_LARK_PID_FILE"
    fi

    if [ -d "$REMOTE_CLAUDE_SOCKET_DIR" ]; then
        for pattern in "*.pid" "*.status" "*.sock" "*.mq" "*.log"; do
            for file in "$REMOTE_CLAUDE_SOCKET_DIR"/$pattern; do
                [ -e "$file" ] || continue
                rm -f "$file"
            done
        done
        rmdir "$REMOTE_CLAUDE_SOCKET_DIR" 2>/dev/null || true
    fi
}

cleanup_uv_path() {
    if [ -f "$REMOTE_CLAUDE_STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
        if jq -e '.uv_path' "$REMOTE_CLAUDE_STATE_FILE" >/dev/null 2>&1; then
            tmp_file=$(mktemp)
            jq 'del(.uv_path)' "$REMOTE_CLAUDE_STATE_FILE" > "$tmp_file" && mv "$tmp_file" "$REMOTE_CLAUDE_STATE_FILE"
        fi
    fi
}
```

- [ ] **Step 5: 移除旧文件名清理列表**

```sh
# 将
# for file in config.json runtime.json .env lark_chat_bindings.json; do
# 改为只处理 settings.json state.json .env 和当前仍有效文件
```

- [ ] **Step 6: 运行回归测试**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_common_reads_uv_path_from_state_json tests/test_entry_lazy_init.py::test_uninstall_uses_centralized_current_file_names_only tests/test_entry_lazy_init.py -q`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/_common.sh scripts/uninstall.sh tests/test_entry_lazy_init.py
git commit -m "refactor(shell): drop legacy config file paths"
```

### Task 5: 统一 `install.sh` 与 `test_lark_management.sh` 的路径来源并补守卫测试

**Files:**
- Modify: `scripts/install.sh`
- Modify: `scripts/test_lark_management.sh`
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写守卫测试，禁止残留硬编码路径**

```python
def test_runtime_shell_scripts_do_not_repeat_centralized_paths():
    for rel in (
        "scripts/check-env.sh",
        "scripts/setup.sh",
        "scripts/install.sh",
        "scripts/uninstall.sh",
        "scripts/test_lark_management.sh",
    ):
        content = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert '"$HOME/.remote-claude"' not in content, rel
        assert '"/tmp/remote-claude"' not in content, rel
        assert 'resources/defaults/' not in content, rel


def test_test_lark_management_uses_common_runtime_variables():
    content = (REPO_ROOT / "scripts" / "test_lark_management.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_LARK_PID_FILE" in content
    assert "REMOTE_CLAUDE_LARK_STATUS_FILE" in content
    assert "REMOTE_CLAUDE_LARK_LOG_FILE" in content
    assert '/tmp/remote-claude/lark.pid' not in content
```

- [ ] **Step 2: 运行定向测试，确认先失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_runtime_shell_scripts_do_not_repeat_centralized_paths tests/test_entry_lazy_init.py::test_test_lark_management_uses_common_runtime_variables -q`

Expected: FAIL

- [ ] **Step 3: 最小修改 `scripts/test_lark_management.sh`**

```sh
if [ -f "$REMOTE_CLAUDE_LARK_PID_FILE" ]; then
    echo "  ✗ lark.pid 未清理"
else
    echo "  ✓ lark.pid 已清理"
fi

if [ -f "$REMOTE_CLAUDE_LARK_STATUS_FILE" ]; then
    echo "  ✗ lark.status 未清理"
else
    echo "  ✓ lark.status 已清理"
fi

if [ -f "$REMOTE_CLAUDE_LARK_LOG_FILE" ]; then
    echo "  ✓ 日志文件存在: $REMOTE_CLAUDE_LARK_LOG_FILE"
    echo "  日志大小: $(ls -lh "$REMOTE_CLAUDE_LARK_LOG_FILE" | awk '{print $5}')"
fi
```

- [ ] **Step 4: 最小修改 `scripts/install.sh`**

```sh
# 保持安装流程不变，只检查并替换残留路径字面量。
# 如果脚本需要使用用户配置目录或 socket 目录，统一改为：
#   "$REMOTE_CLAUDE_HOME_DIR"
#   "$REMOTE_CLAUDE_SOCKET_DIR"
# 不新增新的局部路径常量。
```

- [ ] **Step 5: 运行源码守卫与完整入口测试**

Run: `uv run pytest tests/test_entry_lazy_init.py -q`

Expected: PASS

- [ ] **Step 6: 运行补充回归测试**

Run: `uv run pytest tests/test_custom_commands.py -q && uv run pytest tests/test_runtime_config.py -q`

Expected: 全部 PASS；`tests/test_runtime_config.py` 如仍有既有 `PytestCollectionWarning`，允许保留但不能新增失败

- [ ] **Step 7: Commit**

```bash
git add scripts/install.sh scripts/test_lark_management.sh tests/test_entry_lazy_init.py
git commit -m "refactor(shell): enforce centralized runtime paths"
```

## Self-Review

### Spec coverage
- `_common.sh` 成为路径真相源：Task 1、Task 4
- `setup.sh` / `check-env.sh` / `install.sh` / `uninstall.sh` / `test_lark_management.sh` 不再手写路径：Task 2、Task 3、Task 4、Task 5
- 删除旧兼容逻辑：Task 3、Task 4
- 测试守卫：Task 5

无缺口。

### Placeholder scan
- 所有任务都给出了明确文件、测试命令和最小代码片段
- 没有 `TODO`、`TBD`、`similar to task` 之类占位语
- `install.sh` 的修改范围明确为“替换残留路径字面量，不改安装流程”

### Type consistency
- 统一变量名全程保持一致：
  - `REMOTE_CLAUDE_HOME_DIR`
  - `REMOTE_CLAUDE_SOCKET_DIR`
  - `REMOTE_CLAUDE_ENV_FILE`
  - `REMOTE_CLAUDE_SETTINGS_FILE`
  - `REMOTE_CLAUDE_STATE_FILE`
  - `REMOTE_CLAUDE_ENV_TEMPLATE`
  - `REMOTE_CLAUDE_SETTINGS_TEMPLATE`
  - `REMOTE_CLAUDE_STATE_TEMPLATE`
  - `REMOTE_CLAUDE_LARK_PID_FILE`
  - `REMOTE_CLAUDE_LARK_STATUS_FILE`
  - `REMOTE_CLAUDE_LARK_LOG_FILE`
- 辅助函数名全程保持一致：
  - `rc_init_paths`
  - `rc_ensure_home_dir`
  - `rc_ensure_socket_dir`
  - `rc_require_file`
  - `rc_copy_if_missing`
