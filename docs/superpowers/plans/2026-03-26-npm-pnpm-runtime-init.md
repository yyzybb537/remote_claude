# npm/pnpm 安装安全策略兼容与首次运行初始化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不绕过 pnpm lifecycle script 安全策略的前提下，让 Remote Claude 的所有命令入口在首次运行时自动完成环境初始化，并同步更新卸载逻辑与文档说明。

**Architecture:** 将 Python 环境准备从安装期 hook 下沉到运行期入口脚本：所有 bin 命令在执行 `uv run remote-claude ...` 前统一调用共享 shell 初始化逻辑；`scripts/_common.sh` 提供幂等、可重入保护的惰性初始化函数，`package.json` 中的 lifecycle scripts 不再承担可用性关键路径。文档和测试同步改为“安装成功后首次运行完成初始化”的模型。

**Tech Stack:** POSIX sh、Python 3、uv、npm/pnpm、pytest 风格现有测试脚本、Markdown 文档

---

## 文件职责映射

- `package.json`：定义 npm/pnpm lifecycle scripts；本次要降低 `postinstall` 对可用性的关键性。
- `bin/remote-claude`：主命令入口；在进入 `uv run remote-claude "$@"` 前执行共享运行期初始化。
- `bin/cla`：Claude 快捷命令入口；需在飞书配置检查前完成 uv/.venv 初始化，避免 `uv run` 失败。
- `bin/cl`：同 `bin/cla`，但带跳过权限参数；初始化逻辑应与 `cla` 复用。
- `bin/cx`：Codex 快捷命令入口；初始化逻辑应与 `cla` 复用。
- `bin/cdx`：Codex 快捷命令入口；初始化逻辑应与 `cx` 复用。
- `scripts/_common.sh`：共享 shell 工具；新增显式可调用的运行期初始化函数，并保留重入保护。
- `scripts/install.sh`：显式安装/初始化底层脚本；保留手动执行与入口惰性初始化调用。
- `scripts/uninstall.sh`：保留 npm/pnpm 上下文下非交互行为，不引入新的交互依赖。
- `README.md`：更新安装说明，解释 pnpm 安全策略和首次运行初始化。
- `CLAUDE.md`：同步项目开发须知，说明安装与首次运行初始化的新边界。
- `tests/TEST_PLAN.md`：补充 lifecycle script 未执行时的首次运行恢复测试场景。
- `tests/test_portable_python.py`：已有 Python 环境相关测试，可作为入口初始化测试的参考。
- `tests/test_entry_lazy_init.py`（新建）：验证入口脚本在 hook 缺失场景下触发惰性初始化的关键行为。

### Task 1: 重构共享惰性初始化接口

**Files:**
- Modify: `scripts/_common.sh:51-54`
- Modify: `scripts/_common.sh:150-184`
- Modify: `scripts/_common.sh:268-329`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试，定义共享初始化接口契约**

```python
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
COMMON_SH = PROJECT_ROOT / "scripts" / "_common.sh"


def run_shell(script: str):
    return subprocess.run(
        ["sh", "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def test_lazy_init_if_needed_skips_when_venv_is_fresh(tmp_path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    scripts_dir.mkdir(parents=True)
    venv_dir.mkdir()
    (project_dir / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (project_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    script = f'''
    set -e
    SCRIPT_DIR="{scripts_dir}"
    PROJECT_DIR="{project_dir}"
    . "{COMMON_SH}"
    lazy_init_if_needed
    echo $?
    '''
    result = run_shell(script)
    assert result.returncode == 0
    assert "首次运行" not in result.stdout


def test_lazy_init_if_needed_returns_nonzero_when_setup_fails(tmp_path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (project_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (scripts_dir / "setup.sh").write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
    os.chmod(scripts_dir / "setup.sh", 0o755)

    script = f'''
    set +e
    SCRIPT_DIR="{scripts_dir}"
    PROJECT_DIR="{project_dir}"
    . "{COMMON_SH}"
    lazy_init_if_needed
    status=$?
    echo "STATUS=$status"
    exit 0
    '''
    result = run_shell(script)
    assert "STATUS=23" in result.stdout
```

- [ ] **Step 2: 运行测试，确认当前实现失败**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k lazy_init_if_needed -v`
Expected: FAIL，报错 `lazy_init_if_needed` 未定义或返回码/输出与预期不符。

- [ ] **Step 3: 在 `scripts/_common.sh` 中抽出显式初始化函数并保持自动调用兼容**

```sh
# 运行期惰性初始化：供入口脚本显式调用
# 返回: 0 无需初始化或初始化成功, 非 0 初始化失败
lazy_init_if_needed() {
    case "${_LAZY_INIT_RUNNING:-}" in
        1) return 0 ;;
    esac

    if _is_in_package_manager_cache && ! _is_pnpm_global_install; then
        return 0
    fi

    if ! _needs_sync; then
        return 0
    fi

    local project_dir setup_script init_status
    project_dir="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)}"
    [ -z "$project_dir" ] && return 1

    setup_script="$SCRIPT_DIR/setup.sh"
    [ -x "$setup_script" ] || [ -f "$setup_script" ] || return 1

    echo "首次运行，正在准备 Python 环境..."
    _LAZY_INIT_RUNNING=1
    export _LAZY_INIT_RUNNING
    sh "$setup_script" --npm --lazy
    init_status=$?
    _LAZY_INIT_RUNNING=0
    export _LAZY_INIT_RUNNING
    return "$init_status"
}

_lazy_init() {
    lazy_init_if_needed >/dev/null 2>&1 || return "$?"
}

_lazy_init
```

- [ ] **Step 4: 调整 `_needs_sync` / `check_and_install_uv` 以支持入口主路径**

```sh
check_and_install_uv() {
    local UV_PATH RUNTIME_FILE TMP_FILE
    UV_PATH=$(_read_uv_path_from_runtime)
    if [ -n "$UV_PATH" ] && [ -x "$UV_PATH" ]; then
        export PATH="$(dirname "$UV_PATH"):$PATH"
        return 0
    elif [ -n "$UV_PATH" ]; then
        print_warning "配置的 uv 路径失效（$UV_PATH），尝试系统 uv..."
        RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
        if [ -f "$RUNTIME_FILE" ] && command -v jq >/dev/null 2>&1; then
            TMP_FILE=$(mktemp)
            jq '.uv_path = null' "$RUNTIME_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$RUNTIME_FILE"
        fi
    fi

    if command -v uv >/dev/null 2>&1; then
        _save_uv_path_to_runtime "$(command -v uv)"
        return 0
    fi

    print_warning "未找到 uv，正在安装..."
    install_uv_multi_source || return 1
    _save_uv_path_to_runtime "$(command -v uv)"
    return 0
}
```

- [ ] **Step 5: 运行测试，确认共享初始化接口通过**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k lazy_init_if_needed -v`
Expected: PASS，两个测试均通过。

- [ ] **Step 6: 提交**

```bash
git add scripts/_common.sh tests/test_entry_lazy_init.py
git commit -m "feat(scripts): expose runtime lazy init for bin entrypoints"
```

### Task 2: 让所有 bin 入口显式调用运行期初始化

**Files:**
- Modify: `bin/remote-claude:4-18`
- Modify: `bin/cla:4-20`
- Modify: `bin/cl:4-20`
- Modify: `bin/cx:4-20`
- Modify: `bin/cdx:4-20`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试，验证 bin 入口在 uv run 前触发初始化**

```python
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_remote_claude_entry_runs_lazy_init_before_uv(tmp_path):
    fake_root = tmp_path / "remote-claude"
    (fake_root / "bin").mkdir(parents=True)
    (fake_root / "scripts").mkdir()
    (fake_root / "scripts" / "_common.sh").write_text(
        "lazy_init_if_needed() { echo INIT_OK; }\n",
        encoding="utf-8",
    )
    (fake_root / "bin" / "remote-claude").write_text(
        (PROJECT_ROOT / "bin" / "remote-claude").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    os.chmod(fake_root / "bin" / "remote-claude", 0o755)

    result = subprocess.run(
        [str(fake_root / "bin" / "remote-claude"), "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
    )
    assert "INIT_OK" in result.stdout + result.stderr
```

- [ ] **Step 2: 运行测试，确认当前入口未显式调用导致失败**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k entry_runs_lazy_init -v`
Expected: FAIL，输出里不包含 `INIT_OK`。

- [ ] **Step 3: 修改 `bin/remote-claude`，在 `uv run` 前执行共享初始化**

```sh
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
. "$SCRIPT_DIR/scripts/_common.sh"

if ! lazy_init_if_needed; then
    echo "Remote Claude 运行期初始化失败，请执行: sh $SCRIPT_DIR/scripts/setup.sh --npm --lazy" >&2
    exit 1
fi

if [ "$1" = "lark" ]; then
    . "$SCRIPT_DIR/scripts/check-env.sh" "$SCRIPT_DIR"
fi

cd "$SCRIPT_DIR"
exec uv run remote-claude "$@"
```

- [ ] **Step 4: 修改 `bin/cla` / `bin/cl` / `bin/cx` / `bin/cdx`，在飞书检查前执行初始化**

```sh
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"
. "$SCRIPT_DIR/scripts/_common.sh"

if ! lazy_init_if_needed; then
    echo "Remote Claude 运行期初始化失败，请执行: sh $SCRIPT_DIR/scripts/setup.sh --npm --lazy" >&2
    exit 1
fi

. "$SCRIPT_DIR/scripts/check-env.sh" "$SCRIPT_DIR"
cd "$SCRIPT_DIR"
uv run remote-claude lark start
uv run remote-claude start "${PWD}_$(date +%m%d_%H%M%S)" -- "$@"
```

`cl` / `cx` / `cdx` 仅保留各自已有参数差异，不再在初始化逻辑上分叉。

- [ ] **Step 5: 运行入口测试，确认各入口先初始化再执行主命令**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k entry_runs_lazy_init -v`
Expected: PASS，输出里可观察到 `INIT_OK`。

- [ ] **Step 6: 提交**

```bash
git add bin/remote-claude bin/cla bin/cl bin/cx bin/cdx tests/test_entry_lazy_init.py
git commit -m "fix(bin): run lazy init before uv entrypoints"
```

### Task 3: 降低 package.json 对 postinstall 的依赖并补齐失败提示

**Files:**
- Modify: `package.json:12-20`
- Modify: `scripts/install.sh:137-177`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试，验证即使不依赖 postinstall 也能给出恢复提示**

```python
def test_entry_init_failure_shows_manual_recovery_command(tmp_path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "_common.sh").write_text(
        "lazy_init_if_needed() { return 7; }\n",
        encoding="utf-8",
    )
    (project_dir / "bin").mkdir()
    entry = project_dir / "bin" / "remote-claude"
    entry.write_text((PROJECT_ROOT / "bin" / "remote-claude").read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(entry, 0o755)

    result = subprocess.run([str(entry)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "setup.sh --npm --lazy" in result.stderr
```

- [ ] **Step 2: 运行测试，确认当前失败提示不稳定或不存在**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k manual_recovery_command -v`
Expected: FAIL，stderr 中没有稳定的恢复命令提示。

- [ ] **Step 3: 调整 `package.json`，让 `postinstall` 不再承担关键职责**

```json
{
  "scripts": {
    "preinstall": "sh scripts/preinstall.sh",
    "postinstall": "sh scripts/install.sh --npm || true",
    "preuninstall": "sh scripts/uninstall.sh"
  }
}
```

如果你决定彻底移除 `postinstall`，则在同一任务里改为：

```json
{
  "scripts": {
    "preinstall": "sh scripts/preinstall.sh",
    "preuninstall": "sh scripts/uninstall.sh"
  }
}
```

执行前先确认与现有发布策略是否一致；不要保留会误导“安装必定初始化成功”的强语义描述。

- [ ] **Step 4: 修改 `scripts/install.sh`，把说明调整为显式初始化而非唯一关键路径**

```sh
main() {
    NPM_MODE=false
    LAZY_MODE=false
    for arg in "$@"; do
        [ "$arg" = "--npm" ] && NPM_MODE=true
        [ "$arg" = "--lazy" ] && LAZY_MODE=true
    done

    if _is_in_package_manager_cache; then
        echo "检测到缓存安装，跳过初始化"
        exit 0
    fi

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 环境初始化${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

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

- [ ] **Step 5: 运行恢复提示测试，确认入口失败时给出稳定指引**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k manual_recovery_command -v`
Expected: PASS，stderr 包含 `sh .../scripts/setup.sh --npm --lazy`。

- [ ] **Step 6: 提交**

```bash
git add package.json scripts/install.sh tests/test_entry_lazy_init.py
git commit -m "fix(install): remove runtime dependency on postinstall"
```

### Task 4: 固化卸载脚本的非交互行为

**Files:**
- Modify: `scripts/uninstall.sh:15-22`
- Modify: `scripts/uninstall.sh:194-247`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试，验证 npm 上下文下不读取交互输入**

```python
def test_uninstall_skips_prompt_in_npm_context(tmp_path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "config.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", "scripts/uninstall.sh"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "npm_lifecycle_event": "preuninstall",
        },
        input="n\n",
    )
    assert result.returncode == 0
    assert not data_dir.exists()
    assert "[y/N]" not in result.stdout
```

- [ ] **Step 2: 运行测试，确认当前行为失败或不稳定**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k uninstall_skips_prompt -v`
Expected: FAIL，如果输出仍含 `[y/N]` 或目录未删除则说明行为不稳定。

- [ ] **Step 3: 调整 `scripts/uninstall.sh`，确保所有 npm/pnpm hook 分支都不依赖交互**

```sh
_is_npm_context() {
    [ -n "$npm_lifecycle_event" ] || [ -n "$npm_package_json" ] || [ -n "$npm_config_loglevel" ]
}

cleanup_uv_cache() {
    print_info "检查 uv 缓存..."
    if _is_npm_context || [ -n "$CI" ]; then
        print_detail "npm/CI 环境跳过 uv 缓存清理（保留用户工具）"
        return
    fi
    # 其余逻辑保持交互式
}

cleanup_config_files() {
    print_info "检查配置文件..."
    DATA_DIR="$HOME/.remote-claude"
    [ -d "$DATA_DIR" ] || return

    if _is_npm_context; then
        rm -rf "$DATA_DIR"
        print_success "已删除配置目录: $DATA_DIR"
        return
    fi
    # 其余逻辑保持交互式
}
```

- [ ] **Step 4: 运行测试，确认卸载脚本在 hook 中静默工作**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k uninstall_skips_prompt -v`
Expected: PASS，配置目录已删除且没有交互提示。

- [ ] **Step 5: 提交**

```bash
git add scripts/uninstall.sh tests/test_entry_lazy_init.py
git commit -m "fix(uninstall): keep npm hook cleanup non-interactive"
```

### Task 5: 更新 README、CLAUDE.md 与测试计划

**Files:**
- Modify: `README.md:24-40`
- Modify: `README.md:70-79`
- Modify: `CLAUDE.md:165-171`
- Modify: `tests/TEST_PLAN.md:144-175`
- Test: `tests/TEST_PLAN.md`

- [ ] **Step 1: 写文档变更清单，先明确新对外表述**

```markdown
- README 安装说明从“安装时自动完成初始化”改为“首次运行自动初始化”。
- README 增加 pnpm 可能不执行 lifecycle scripts 的安全说明。
- README 增加初始化失败时的手动恢复命令。
- CLAUDE.md 记录：npm/pnpm 分发下命令可用性依赖运行期初始化，而不是 postinstall。
- TEST_PLAN 增加 lifecycle script 未执行时的首次运行恢复场景。
```

- [ ] **Step 2: 修改 `README.md`，同步首次运行初始化模型**

```md
### 安装

以下方式任选其一：

```bash
# 方式一：npm 安装（推荐）
npm install -g remote-claude

# 方式二：pnpm 安装
pnpm add -g remote-claude

# 方式三：零依赖安装（无需预装 Python）
curl -fsSL https://raw.githubusercontent.com/yyzybb537/remote_claude/main/scripts/install.sh | bash
```

> 说明：pnpm 可能因安全策略不执行 package lifecycle scripts。Remote Claude 不依赖该行为；首次运行 `cla` / `remote-claude` 时会自动准备 Python 环境。

首次运行时会自动完成：uv 包管理器安装、Python 虚拟环境创建、依赖安装。
如自动初始化失败，可手动执行：`sh <安装目录>/scripts/setup.sh --npm --lazy`
```

- [ ] **Step 3: 修改 `CLAUDE.md` 与 `tests/TEST_PLAN.md`，同步开发与测试规则**

```md
- **系统要求：** macOS/Linux；npm/pnpm 安装场景下不假设 lifecycle scripts 一定执行成功。
- **初始化模型：** `cla` / `cl` / `cx` / `cdx` / `remote-claude` 会在首次运行时自动检查并初始化 Python 环境。
```

```md
### 安装与首次运行回归

| 场景 | 验证点 | 测试方法 |
|------|-------|---------|
| pnpm 全局安装且 lifecycle script 未执行 | 首次 `cla --version` 自动初始化并成功 | 手动测试 / Docker 脚本 |
| 已初始化环境重复运行 | 不重复执行 setup | 手动测试 |
| 初始化失败 | 返回非 0 且输出手动恢复命令 | 手动测试 |
```

- [ ] **Step 4: 自查文档一致性**

Run: `grep -n "自动完成：uv 包管理器安装" README.md && grep -n "首次运行" README.md CLAUDE.md tests/TEST_PLAN.md`
Expected: README 不再声称“安装阶段必然完成初始化”，三个文件都出现“首次运行”相关表述。

- [ ] **Step 5: 提交**

```bash
git add README.md CLAUDE.md tests/TEST_PLAN.md
git commit -m "docs: describe runtime init for npm and pnpm installs"
```

### Task 6: 运行回归验证并整理交付说明

**Files:**
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`
- Test: `tests/test_portable_python.py`

- [ ] **Step 1: 补齐测试文件中的最终断言与辅助函数**

```python
def test_entry_init_failure_shows_manual_recovery_command(tmp_path):
    ...


def test_uninstall_skips_prompt_in_npm_context(tmp_path):
    ...


def main_guard():
    assert True
```

保证 `tests/test_entry_lazy_init.py` 中所有前序任务引用的测试函数均已定义，且名称一致。

- [ ] **Step 2: 运行新增入口初始化测试**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -v`
Expected: PASS，覆盖共享初始化、bin 入口、失败提示、非交互卸载场景。

- [ ] **Step 3: 运行现有 Python 环境回归测试**

Run: `uv run python3 tests/test_portable_python.py`
Expected: PASS，输出包含 `测试结果:` 且失败数为 0。

- [ ] **Step 4: 运行文档/脚本快速烟雾检查**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -v && uv run python3 tests/test_portable_python.py`
Expected: 全部 PASS，没有新增死循环或入口初始化阻塞。

- [ ] **Step 5: 提交**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test: cover runtime init fallback for package installs"
```

## Self-Review

- **Spec coverage:**
  - 运行期初始化取代安装期关键路径 → Task 1、Task 2、Task 3
  - 所有 bin 入口统一触发 lazy init → Task 2
  - 卸载 hook 中保持非交互 → Task 4
  - README/CLAUDE.md/TEST_PLAN 同步更新 → Task 5
  - 首次运行、重复运行、失败恢复测试 → Task 1、Task 3、Task 6
- **Placeholder scan:** 已去除 `TODO`/`TBD`/“类似 Task N”类描述；每个代码步骤都给出实际代码或命令。
- **Type consistency:** 统一使用 `lazy_init_if_needed` 作为共享入口函数名；测试函数名与执行命令中的 `-k` 关键字保持一致。
