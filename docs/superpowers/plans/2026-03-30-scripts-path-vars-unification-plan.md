# Scripts 路径变量收敛与目录传参移除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有 `scripts/*.sh` 统一通过 `_common.sh` 收敛 `PROJECT_DIR/SCRIPT_DIR`，并彻底移除“目录参数传入脚本”语义，修复 `lark/resources/defaults/.env.example` 误路径问题。

**Architecture:** 所有 shell 脚本入口统一为“解析脚本真实路径 → 设置 `PROJECT_DIR` → source `_common.sh`”。`check-env.sh` 只接受无目录参数调用，若收到目录参数立即报错退出。所有调用点（`bin/*`、docker 脚本、测试）同步改为无目录参数，并以测试覆盖 `source/直接执行/软链` 三类入口。

**Tech Stack:** POSIX sh, Python/pytest, uv

---

## 文件结构与职责

- 修改：`scripts/check-env.sh`
  - 目录参数废弃策略（显式报错退出）与模板路径固定到 `$PROJECT_DIR`。
- 修改：`scripts/install.sh`
- 修改：`scripts/setup.sh`
- 修改：`scripts/uninstall.sh`
- 修改：`scripts/preinstall.sh`
- 修改：`scripts/npm-publish.sh`
- 修改：`scripts/test_lark_management.sh`
  - 统一入口骨架并保证均 source `_common.sh`。
- 修改：`scripts/_common.sh`
  - 保持路径收敛唯一真相源与入口约束注释/断言（若需微调）。
- 修改：`bin/cla`
- 修改：`bin/cl`
- 修改：`bin/cx`
- 修改：`bin/cdx`
- 修改：`bin/remote-claude`
  - 去除 `. scripts/check-env.sh "$PROJECT_DIR"` 目录传参调用。
- 修改：`docker/scripts/docker-test.sh`
  - 去除 `bash scripts/check-env.sh .` 目录传参调用。
- 修改：`tests/test_entry_lazy_init.py`
  - 新增“目录参数应失败”与“无参数入口稳定”回归。
- 修改：`tests/TEST_PLAN.md`
  - 同步新增/更新回归命令。
- 修改：`CLAUDE.md`
  - 同步脚本入口与“禁止目录参数传入”约定。

---

### Task 1: 先写失败测试，锁定新约束

**Files:**
- Modify: `tests/test_entry_lazy_init.py`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 新增 check-env 目录参数废弃测试（先失败）**

```python
def test_check_env_rejects_legacy_directory_argument(tmp_path: Path):
    project_dir = REPO_ROOT
    script = project_dir / "scripts" / "check-env.sh"

    result = subprocess.run(
        ["sh", str(script), str(project_dir)],
        text=True,
        capture_output=True,
        env={**os.environ, "REMOTE_CLAUDE_REQUIRE_FEISHU": "0"},
    )

    assert result.returncode != 0
    assert "目录参数已废弃" in (result.stderr or result.stdout)
```

- [ ] **Step 2: 更新现有 source 测试为“无目录参数”调用（先失败）**

```python
shell_script = f"""#!/bin/sh
set -e
export HOME='{tmp_path / 'home'}'
mkdir -p "$HOME"
export REMOTE_CLAUDE_REQUIRE_FEISHU=0
. '{check_env}'
echo skip-ok
"""
```

- [ ] **Step 3: 运行定向测试确认失败**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_check_env_rejects_legacy_directory_argument -q
uv run pytest tests/test_entry_lazy_init.py::test_check_env_allows_skip_when_feishu_not_required -q
```

Expected: 至少一项 FAIL（实现尚未完成）。

- [ ] **Step 4: 提交失败测试基线**

```bash
git add tests/test_entry_lazy_init.py
git commit -m "test: add failing checks for deprecated check-env dir argument"
```

---

### Task 2: 实现 check-env 目录传参移除与报错退出

**Files:**
- Modify: `scripts/check-env.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 在 check-env 开头增加目录参数拒绝分支**

```sh
if [ "${1:+x}" = "x" ]; then
    echo "错误: check-env.sh 目录参数已废弃，请直接调用 . scripts/check-env.sh" >&2
    return 2 2>/dev/null || exit 2
fi
```

- [ ] **Step 2: 固定模板路径只使用 PROJECT_DIR**

```sh
INSTALL_DIR="$PROJECT_DIR"
if [ ! -f "$INSTALL_DIR/resources/defaults/.env.example" ]; then
    echo "错误: 无法定位安装目录模板文件: $INSTALL_DIR/resources/defaults/.env.example" >&2
    return 1 2>/dev/null || exit 1
fi
```

- [ ] **Step 3: 运行定向测试验证通过**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_check_env_rejects_legacy_directory_argument -q
uv run pytest tests/test_entry_lazy_init.py::test_check_env_allows_skip_when_feishu_not_required -q
uv run pytest tests/test_entry_lazy_init.py::test_check_env_works_via_symlink_from_random_cwd -q
```

Expected: PASS。

- [ ] **Step 4: 提交 check-env 实现**

```bash
git add scripts/check-env.sh tests/test_entry_lazy_init.py
git commit -m "fix(scripts): reject deprecated check-env directory argument"
```

---

### Task 3: 同步所有调用点，去除目录参数传入

**Files:**
- Modify: `bin/cla`
- Modify: `bin/cl`
- Modify: `bin/cx`
- Modify: `bin/cdx`
- Modify: `bin/remote-claude`
- Modify: `docker/scripts/docker-test.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 修改 bin 入口脚本调用方式（去参）**

```sh
# before
. "$PROJECT_DIR/scripts/check-env.sh" "$PROJECT_DIR"

# after
. "$PROJECT_DIR/scripts/check-env.sh"
```

- [ ] **Step 2: 修改 remote-claude lark 分支调用方式（去参）**

```sh
# before
. "${PROJECT_DIR}/scripts/check-env.sh" "${PROJECT_DIR}"

# after
. "${PROJECT_DIR}/scripts/check-env.sh"
```

- [ ] **Step 3: 修改 docker 回归命令（去参）**

```bash
# before
timeout 5 bash scripts/check-env.sh .

# after
timeout 5 bash scripts/check-env.sh
```

- [ ] **Step 4: 运行调用点回归测试**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_entry_script_skips_feishu_prompt_and_executes_remote_claude_when_optional -q
uv run pytest tests/test_entry_lazy_init.py::test_entry_scripts_define_project_dir_before_sourcing_common -q
```

Expected: PASS。

- [ ] **Step 5: 提交调用点同步变更**

```bash
git add bin/cla bin/cl bin/cx bin/cdx bin/remote-claude docker/scripts/docker-test.sh
git commit -m "refactor(entry): remove deprecated check-env directory argument passing"
```

---

### Task 4: 统一 scripts 入口骨架并保持 `_common.sh` 单一真相源

**Files:**
- Modify: `scripts/install.sh`
- Modify: `scripts/setup.sh`
- Modify: `scripts/uninstall.sh`
- Modify: `scripts/preinstall.sh`
- Modify: `scripts/npm-publish.sh`
- Modify: `scripts/test_lark_management.sh`
- Modify: `scripts/_common.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 对全部目标脚本核对并统一入口骨架**

```sh
SOURCE="$0"
while [ -L "$SOURCE" ]; do
    BASE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    case "$SOURCE" in /*) ;; *) SOURCE="$BASE_DIR/$SOURCE" ;; esac
done
SELF_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PROJECT_DIR="$(cd "$SELF_DIR/.." && pwd)"
. "$PROJECT_DIR/scripts/_common.sh"
```

- [ ] **Step 2: 确认 `_common.sh` 的收敛断言仍生效**

```sh
_normalize_project_and_script_dir || :
_require_common_layout || return 1
```

- [ ] **Step 3: 运行脚本入口一致性测试**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_scripts_define_project_dir_before_common_source -q
uv run pytest tests/test_entry_lazy_init.py::test_check_env_works_via_symlink_from_random_cwd -q
```

Expected: PASS。

- [ ] **Step 4: 提交入口统一变更**

```bash
git add scripts/install.sh scripts/setup.sh scripts/uninstall.sh scripts/preinstall.sh scripts/npm-publish.sh scripts/test_lark_management.sh scripts/_common.sh
git commit -m "refactor(scripts): unify entry template and path source via _common.sh"
```

---

### Task 5: 文档与测试计划同步

**Files:**
- Modify: `tests/TEST_PLAN.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新 TEST_PLAN 的目录参数废弃回归项**

```markdown
| check-env 目录参数废弃 | 传目录参数时显式失败 | `uv run pytest tests/test_entry_lazy_init.py::test_check_env_rejects_legacy_directory_argument -q` |
| check-env 无参兼容 | source/直接执行/symlink 无参数均稳定 | `uv run pytest tests/test_entry_lazy_init.py::test_check_env_works_via_symlink_from_random_cwd -q` |
```

- [ ] **Step 2: 更新 CLAUDE.md 入口约定**

```markdown
- **脚本入口约定：** `scripts/*.sh` 必须使用统一入口模板（先解析真实路径并定义 `PROJECT_DIR`，再 source `scripts/_common.sh`）
- **调用约定：** 禁止向 `scripts/check-env.sh` 传目录参数；历史传参视为错误并立即退出
```

- [ ] **Step 3: 运行文档关联快速回归**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_scripts_define_project_dir_before_common_source -q
```

Expected: PASS。

- [ ] **Step 4: 提交文档同步**

```bash
git add tests/TEST_PLAN.md CLAUDE.md
git commit -m "docs: codify check-env no-dir-arg rule and script entry contract"
```

---

### Task 6: 全量验证与收尾

**Files:**
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 运行本次改动相关测试集**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py -q
```

Expected: PASS。

- [ ] **Step 2: 回归 docker 脚本中的 check-env 非阻塞行为**

Run:
```bash
uv run pytest tests/test_entry_lazy_init.py::test_docker_test_script_runs_startup_regression_cases -q
```

Expected: PASS（脚本中不再使用目录参数调用）。

- [ ] **Step 3: 手工烟测（无参数 + symlink）**

Run:
```bash
tmpdir=$(mktemp -d)
ln -s "$PWD/scripts/check-env.sh" "$tmpdir/check-env-link.sh"
REMOTE_CLAUDE_REQUIRE_FEISHU=0 sh "$tmpdir/check-env-link.sh"
```

Expected: 退出码 0，且不出现 `lark/resources/defaults/.env.example` 路径错误。

- [ ] **Step 4: 确认工作区状态**

Run:
```bash
git status
```

Expected: 仅保留本次预期改动，或 `working tree clean`（若已完成全部提交）。

---

## 自检（写计划后）

1. **Spec coverage：** 已覆盖 `_common.sh` 单一真相源、全脚本统一入口、目录参数移除并显式失败、source/直接执行/symlink 回归。
2. **Placeholder scan：** 无 TBD/TODO/“后续实现”等占位表述。
3. **Type consistency：** 全文统一使用 `PROJECT_DIR/SCRIPT_DIR`；`check-env.sh` 目录参数策略前后一致为“显式报错退出”。
