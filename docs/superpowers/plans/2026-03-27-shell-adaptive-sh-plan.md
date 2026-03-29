# Shell-Adaptive POSIX sh Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `scripts/` 下脚本从显式 bash 依赖迁移为 POSIX `sh` 兼容，并实现 shell rc（zsh/bash/profile）读写自适应与幂等写入。

**Architecture:** 在 `scripts/_common.sh` 收敛 shell rc 选择、候选扫描与标记块 upsert 逻辑，其他脚本只调用公共函数。逐步替换 `scripts/` 中 bash-only 语法与 `bash ...` 调用为 POSIX 方案，并通过 `pytest` + shell 语法检查形成回归保护。保持现有入口行为不变，仅调整 shell 兼容路径与提示文案。

**Tech Stack:** POSIX shell (`/bin/sh`), Python `pytest`, existing Remote Claude scripts/tests

---

### Task 1: 在 `_common.sh` 实现 shrc 自适应与统一 upsert

**Files:**
- Modify: `scripts/_common.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试（rc 目标选择 + 候选扫描 + 幂等）**

```python
# tests/test_entry_lazy_init.py

def test_get_shell_rc_prefers_zsh_when_shell_is_zsh():
    result = run_common(r'''
TMP_HOME="$(mktemp -d)/home"
mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
export SHELL="/bin/zsh"
rc=$(get_shell_rc)
echo "$rc"
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('/.zshrc')


def test_rc_scan_detects_existing_block_in_profile_candidates():
    result = run_common(r'''
TMP_HOME="$(mktemp -d)/home"
mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
cat > "$HOME/.profile" <<'EOF'
# >>> remote-claude init >>>
export PATH="$HOME/.local/bin:$PATH"
# <<< remote-claude init <<<
EOF
if has_remote_claude_init_in_any_rc; then
  echo found
else
  echo missing
  exit 1
fi
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('found')


def test_upsert_rc_block_is_idempotent():
    result = run_common(r'''
TMP_HOME="$(mktemp -d)/home"
mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
export SHELL="/bin/bash"
block='export PATH="$HOME/.local/bin:$PATH"'
upsert_remote_claude_init_block "$block"
upsert_remote_claude_init_block "$block"
count=$(grep -c "# >>> remote-claude init >>>" "$HOME/.bashrc")
echo "count:$count"
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('count:1')
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_get_shell_rc_prefers_zsh_when_shell_is_zsh tests/test_entry_lazy_init.py::test_rc_scan_detects_existing_block_in_profile_candidates tests/test_entry_lazy_init.py::test_upsert_rc_block_is_idempotent -q`

Expected: FAIL（提示 `has_remote_claude_init_in_any_rc` / `upsert_remote_claude_init_block` 未定义或断言失败）

- [ ] **Step 3: 在 `_common.sh` 实现 rc 公共函数 + lazy init 改为 `sh`**

```sh
# scripts/_common.sh
REMOTE_CLAUDE_INIT_BEGIN='# >>> remote-claude init >>>'
REMOTE_CLAUDE_INIT_END='# <<< remote-claude init <<<'

_get_rc_candidates() {
    printf '%s\n' "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"
}

get_shell_rc() {
    case "${SHELL:-}" in
        */zsh)
            [ -f "$HOME/.zshrc" ] && { echo "$HOME/.zshrc"; return 0; }
            echo "$HOME/.profile"
            return 0
            ;;
        */bash)
            [ -f "$HOME/.bashrc" ] && { echo "$HOME/.bashrc"; return 0; }
            [ -f "$HOME/.bash_profile" ] && { echo "$HOME/.bash_profile"; return 0; }
            echo "$HOME/.profile"
            return 0
            ;;
    esac

    [ -f "$HOME/.zshrc" ] && { echo "$HOME/.zshrc"; return 0; }
    [ -f "$HOME/.bashrc" ] && { echo "$HOME/.bashrc"; return 0; }
    [ -f "$HOME/.bash_profile" ] && { echo "$HOME/.bash_profile"; return 0; }
    echo "$HOME/.profile"
}

has_remote_claude_init_in_any_rc() {
    local rc
    for rc in $(_get_rc_candidates); do
        [ -f "$rc" ] || continue
        if grep -qF "$REMOTE_CLAUDE_INIT_BEGIN" "$rc" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

upsert_remote_claude_init_block() {
    local body target rc tmp_file
    body="$1"

    if has_remote_claude_init_in_any_rc; then
        for rc in $(_get_rc_candidates); do
            [ -f "$rc" ] || continue
            if grep -qF "$REMOTE_CLAUDE_INIT_BEGIN" "$rc" 2>/dev/null; then
                tmp_file=$(mktemp)
                awk -v begin="$REMOTE_CLAUDE_INIT_BEGIN" -v end="$REMOTE_CLAUDE_INIT_END" -v body="$body" '
                    $0==begin {print begin; print body; in_block=1; next}
                    $0==end {print end; in_block=0; next}
                    !in_block {print}
                ' "$rc" > "$tmp_file" && mv "$tmp_file" "$rc"
                return $?
            fi
        done
    fi

    target=$(get_shell_rc)
    [ -f "$target" ] || : > "$target"
    {
        printf '\n%s\n' "$REMOTE_CLAUDE_INIT_BEGIN"
        printf '%s\n' "$body"
        printf '%s\n' "$REMOTE_CLAUDE_INIT_END"
    } >> "$target"
}

# _lazy_init 内改为 sh 调用 setup
# 原: bash "$SCRIPT_DIR/setup.sh" --npm --lazy 2>/dev/null
sh "$SCRIPT_DIR/setup.sh" --npm --lazy 2>/dev/null
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_get_shell_rc_prefers_zsh_when_shell_is_zsh tests/test_entry_lazy_init.py::test_rc_scan_detects_existing_block_in_profile_candidates tests/test_entry_lazy_init.py::test_upsert_rc_block_is_idempotent tests/test_entry_lazy_init.py::test_lazy_init_if_needed_reports_setup_success_after_trigger tests/test_entry_lazy_init.py::test_lazy_init_if_needed_reports_setup_failure_non_zero -q`

Expected: PASS

- [ ] **Step 5: 提交 Task 1**

```bash
git add scripts/_common.sh tests/test_entry_lazy_init.py
git commit -m "feat(scripts): add adaptive rc upsert and sh lazy-init path"
```

---

### Task 2: 改造 `setup.sh` / `install.sh` / `uninstall.sh` 使用统一 rc 块与 `sh` 文案

**Files:**
- Modify: `scripts/setup.sh`
- Modify: `scripts/install.sh`
- Modify: `scripts/uninstall.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试（setup/install 文案与 rc 写入路径）**

```python
# tests/test_entry_lazy_init.py

def test_setup_configure_shell_writes_completion_via_init_block(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "_common.sh").write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (script_dir / "setup.sh").write_text((REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        ["sh", str(script_dir / "setup.sh"), "--lazy"],
        env={**os.environ, "HOME": str(tmp_path / "home"), "SHELL": "/bin/zsh", "PROJECT_DIR": str(project_dir)},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    zshrc = tmp_path / "home" / ".zshrc"
    assert zshrc.exists()
    content = zshrc.read_text(encoding="utf-8")
    assert '# >>> remote-claude init >>>' in content
    assert 'completion.sh' in content


def test_install_completion_hint_uses_dot_not_source():
    content = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "source $shell_rc" not in content
    assert ". $shell_rc" in content
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_setup_configure_shell_writes_completion_via_init_block tests/test_entry_lazy_init.py::test_install_completion_hint_uses_dot_not_source -q`

Expected: FAIL（当前仍使用 `source` 或未统一 init block）

- [ ] **Step 3: 修改 setup/install/uninstall**

```sh
# scripts/setup.sh（关键改动片段）
setup_path() {
    upsert_remote_claude_init_block 'export PATH="$HOME/.local/bin:$PATH"'
    export PATH="$HOME/.local/bin:$PATH"
}

configure_shell() {
    COMPLETION_LINE='. "$PROJECT_DIR/completion.sh"'
    BLOCK_CONTENT=$(cat <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
. "$PROJECT_DIR/completion.sh"
EOF
)
    upsert_remote_claude_init_block "$BLOCK_CONTENT"
}

# 展示提示从 .bash_profile 改为动态 rc
show_usage() {
    shell_rc=$(get_shell_rc)
    cat << EOF
${YELLOW}提示：${NC}请运行以下命令使 PATH 生效，或重新打开终端：
  . $shell_rc
EOF
}
```

```sh
# scripts/install.sh（提示文案改动）
echo "${YELLOW}提示:${NC} 重新打开终端或运行 ${GREEN}. $shell_rc${NC} 生效"
```

```sh
# scripts/uninstall.sh（清理标记块）
cleanup_shell_config() {
    local cleaned=0 rc tmp_file
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.profile"; do
        [ -f "$rc" ] || continue
        tmp_file=$(mktemp)
        awk -v begin='# >>> remote-claude init >>>' -v end='# <<< remote-claude init <<<' '
            $0==begin {in_block=1; next}
            $0==end {in_block=0; next}
            !in_block {print}
        ' "$rc" > "$tmp_file" && mv "$tmp_file" "$rc"
        cleaned=$((cleaned + 1))
    done
    [ "$cleaned" -gt 0 ] && print_success "已清理 $cleaned 个 shell 配置文件"
}
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_setup_configure_shell_writes_completion_via_init_block tests/test_entry_lazy_init.py::test_install_completion_hint_uses_dot_not_source -q`

Expected: PASS

- [ ] **Step 5: 提交 Task 2**

```bash
git add scripts/setup.sh scripts/install.sh scripts/uninstall.sh tests/test_entry_lazy_init.py
git commit -m "refactor(scripts): centralize rc init block and sh-style hints"
```

---

### Task 3: 将 `completion.sh`、`npm-publish.sh`、`test_lark_management.sh` 全量 POSIX 化

**Files:**
- Modify: `scripts/completion.sh`
- Modify: `scripts/npm-publish.sh`
- Modify: `scripts/test_lark_management.sh`

- [ ] **Step 1: 写失败测试（禁止 bash-only 语法与 shebang）**

```python
# tests/test_entry_lazy_init.py

def test_scripts_use_sh_shebang_for_all_shell_scripts():
    for rel in [
        "scripts/completion.sh",
        "scripts/npm-publish.sh",
        "scripts/test_lark_management.sh",
    ]:
        first = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()[0]
        assert first.strip() == "#!/bin/sh"


def test_shell_scripts_do_not_contain_bash_only_constructs():
    for rel in [
        "scripts/completion.sh",
        "scripts/npm-publish.sh",
    ]:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "[[" not in text
        assert "#!/bin/bash" not in text
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_scripts_use_sh_shebang_for_all_shell_scripts tests/test_entry_lazy_init.py::test_shell_scripts_do_not_contain_bash_only_constructs -q`

Expected: FAIL

- [ ] **Step 3: 修改三个脚本为 POSIX 兼容实现**

```sh
# scripts/completion.sh（关键判断改造）
if [ -n "${ZSH_VERSION:-}" ]; then
    # zsh 分支
    :
elif [ -n "${BASH_VERSION:-}" ]; then
    # bash 分支
    :
else
    # sh / 其他 shell：静默退出
    return 0 2>/dev/null || exit 0
fi
```

```sh
# scripts/npm-publish.sh
#!/bin/sh
set -e

while [ "$#" -gt 0 ]; do
    case "$1" in
        --token) TOKEN="$2"; shift 2 ;;
        patch|minor|major) BUMP="$1"; shift ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

if ! npm whoami --registry=https://registry.npmjs.org/ >/dev/null 2>&1; then
    echo "❌ 未登录 npm，请通过 --token 传入 token："
    echo "   sh scripts/npm-publish.sh --token <npm-token>"
    exit 1
fi
```

```sh
# scripts/test_lark_management.sh
#!/bin/sh
set -e
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
. "$PROJECT_ROOT/scripts/_common.sh"
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_scripts_use_sh_shebang_for_all_shell_scripts tests/test_entry_lazy_init.py::test_shell_scripts_do_not_contain_bash_only_constructs -q`

Expected: PASS

- [ ] **Step 5: 提交 Task 3**

```bash
git add scripts/completion.sh scripts/npm-publish.sh scripts/test_lark_management.sh tests/test_entry_lazy_init.py
git commit -m "refactor(scripts): migrate completion and utility scripts to POSIX sh"
```

---

### Task 4: 更新测试计划并补充回归项

**Files:**
- Modify: `tests/TEST_PLAN.md`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试（静态扫描脚本中的显式 `bash` 调用）**

```python
# tests/test_entry_lazy_init.py

def test_scripts_no_explicit_bash_invocation_for_internal_calls():
    for rel in [
        "scripts/_common.sh",
        "scripts/setup.sh",
        "scripts/install.sh",
        "scripts/npm-publish.sh",
    ]:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert 'bash "$SCRIPT_DIR/setup.sh"' not in text
        assert 'bash scripts/' not in text
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_scripts_no_explicit_bash_invocation_for_internal_calls -q`

Expected: FAIL

- [ ] **Step 3: 修改 `tests/TEST_PLAN.md` 加入 shell 自适应回归章节**

```markdown
### shell 自适应与 POSIX sh 回归

| 场景 | 验证点 | 命令 |
|------|--------|------|
| rc 自适应选择 | zsh/bash/unknown shell 选择正确 rc | `uv run pytest tests/test_entry_lazy_init.py::test_get_shell_rc_prefers_zsh_when_shell_is_zsh -q` |
| init 幂等 | 重复执行不重复写块 | `uv run pytest tests/test_entry_lazy_init.py::test_upsert_rc_block_is_idempotent -q` |
| 脚本 shebang 统一 | 目标脚本均为 `#!/bin/sh` | `uv run pytest tests/test_entry_lazy_init.py::test_scripts_use_sh_shebang_for_all_shell_scripts -q` |
| 无 bash-only 语法残留 | `[[` 与 `#!/bin/bash` 被清理 | `uv run pytest tests/test_entry_lazy_init.py::test_shell_scripts_do_not_contain_bash_only_constructs -q` |
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `uv run pytest tests/test_entry_lazy_init.py::test_scripts_no_explicit_bash_invocation_for_internal_calls tests/test_entry_lazy_init.py::test_scripts_use_sh_shebang_for_all_shell_scripts tests/test_entry_lazy_init.py::test_shell_scripts_do_not_contain_bash_only_constructs -q`

Expected: PASS

- [ ] **Step 5: 提交 Task 4**

```bash
git add tests/TEST_PLAN.md tests/test_entry_lazy_init.py
git commit -m "test(scripts): add shell-adaptive regression coverage"
```

---

### Task 5: 全量验证与收尾

**Files:**
- Verify: `scripts/*.sh`
- Verify: `tests/test_entry_lazy_init.py`
- Verify: `tests/test_custom_commands.py`

- [ ] **Step 1: 执行 shell 语法检查（全脚本）**

Run: `for f in scripts/*.sh; do sh -n "$f" || exit 1; done && echo "sh syntax ok"`

Expected: 输出 `sh syntax ok`

- [ ] **Step 2: 执行核心回归测试**

Run: `uv run pytest tests/test_entry_lazy_init.py tests/test_custom_commands.py -q`

Expected: PASS

- [ ] **Step 3: 运行 repo 既有 docker 测试脚本（如环境可用）**

Run: `docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh`

Expected: 所有检查通过（若本机无 Docker，记录未执行原因）

- [ ] **Step 4: 检查改动中无 `bash` 内部调用残留**

Run: `uv run python3 - <<'PY'
from pathlib import Path
bad=[]
for p in Path('scripts').glob('*.sh'):
    t=p.read_text(encoding='utf-8')
    if 'bash "$SCRIPT_DIR/setup.sh"' in t or 'bash scripts/' in t:
        bad.append(str(p))
print('BAD' if bad else 'OK')
if bad:
    print('\n'.join(bad))
    raise SystemExit(1)
PY`

Expected: 输出 `OK`

- [ ] **Step 5: 最终提交**

```bash
git add scripts/_common.sh scripts/setup.sh scripts/install.sh scripts/uninstall.sh scripts/completion.sh scripts/npm-publish.sh scripts/test_lark_management.sh tests/test_entry_lazy_init.py tests/TEST_PLAN.md
git commit -m "feat(scripts): make shell execution POSIX and rc adaptive"
```
