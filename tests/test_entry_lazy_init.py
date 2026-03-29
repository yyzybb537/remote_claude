import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = REPO_ROOT / "scripts" / "_common.sh"
ENTRY_SCRIPTS = [
    "bin/remote-claude",
    "bin/cla",
    "bin/cl",
    "bin/cx",
    "bin/cdx",
]


def _expected_recovery_command(project_root: Path) -> str:
    return f"sh {project_root / 'scripts' / 'setup.sh'} --npm --lazy"


def run_common(script_body: str) -> subprocess.CompletedProcess[str]:
    shell_script = f"""#!/bin/sh
set -e
SCRIPT_DIR='{REPO_ROOT}/scripts'
PROJECT_DIR='{REPO_ROOT}'
. '{COMMON_SH}'
{script_body}
"""
    return subprocess.run(
        ["sh"],
        input=shell_script,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )


def test_get_shell_rc_prefers_zsh_when_shell_is_zsh():
    result = run_common(r'''
TMP_HOME="$(mktemp -d)/home"
mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
: > "$HOME/.zshrc"
export SHELL="/bin/zsh"
rc=$(get_shell_rc)
echo "$rc"
''')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('/.zshrc')


def test_get_shell_rc_uses_profile_for_unknown_shell_even_when_other_rc_exists():
    result = run_common(r'''
TMP_HOME="$(mktemp -d)/home"
mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
: > "$HOME/.zshrc"
: > "$HOME/.bashrc"
export SHELL="/bin/fish"
rc=$(get_shell_rc)
echo "$rc"
''')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('/.profile')


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
    assert result.stdout.strip().endswith("found")


def test_upsert_rc_block_is_idempotent():
    result = run_common(r'''
TMP_HOME="$(mktemp -d)/home"
mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
export SHELL="/bin/bash"
: > "$HOME/.bashrc"
block='export PATH="$HOME/.local/bin:$PATH"'
upsert_remote_claude_init_block "$block"
upsert_remote_claude_init_block "$block"
count=$(grep -c "# >>> remote-claude init >>>" "$HOME/.bashrc")
echo "count:$count"
''')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("count:1")


def test_upsert_rc_block_handles_orphan_begin_safely():
    result = run_common(r'''
TMP_HOME="$(mktemp -d)/home"
mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
export SHELL="/bin/bash"
cat > "$HOME/.bashrc" <<'EOF'
line-before
# >>> remote-claude init >>>
orphan-body
line-after
EOF
upsert_remote_claude_init_block 'export PATH="$HOME/.local/bin:$PATH"'
printf 'contains:%s\n' "$(grep -c 'line-after' "$HOME/.bashrc")"
printf 'begin-count:%s\n' "$(grep -c '# >>> remote-claude init >>>' "$HOME/.bashrc")"
''')

    assert result.returncode == 0, result.stderr
    assert "contains:1" in result.stdout
    assert "begin-count:2" in result.stdout


def test_lazy_init_if_needed_reports_skip_in_package_cache():
    result = run_common("""
SCRIPT_DIR="$HOME/.npm/_cacache/remote-claude/scripts"
if _lazy_init; then
    status=$?
    echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"
else
    status=$?
    echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"
    exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("rc:0 result:skipped-cache")


def test_lazy_init_if_needed_reports_noop_when_sync_not_needed(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    script_dir.mkdir(parents=True)
    venv_dir.mkdir()

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
if _lazy_init; then
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
else
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
    exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("rc:0 result:no-sync-needed")


def test_needs_sync_skips_cache_without_lockfiles():
    result = run_common("""
PROJECT_DIR="$HOME/.npm/_cacache/remote-claude"
SCRIPT_DIR="$PROJECT_DIR/scripts"
mkdir -p "$PROJECT_DIR"
if _needs_sync; then
    echo needs-sync
    exit 1
else
    status=$?
    echo "rc:$status"
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("rc:1")




def test_install_uv_multi_source_prefers_pip_user_before_fallback():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/pip_args.log"
: > "$TMPDIR_PATH/fallback.log"

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

pip() {
    pip3 "$@"
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


def test_install_uv_multi_source_falls_back_after_pip_user_failures():
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

pip() {
    pip3 "$@"
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


def test_common_script_fail_summary_contains_required_fields():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
INSTALL_LOG_FILE="$TMPDIR_PATH/install.log"

_log_script_fail "uv-install-script" "curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh" 127
cat "$INSTALL_LOG_FILE"
''')

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "[script-fail][uv-install-script]" in out
    assert "source=na" in out
    assert "cmd=\"curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh\"" in out
    assert "exit_code=127" in out


def test_lazy_init_if_needed_reports_setup_success_after_trigger(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    (project_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")
    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
if _lazy_init; then
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
else
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
    exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("rc:0 result:sync-completed")


def test_lazy_init_if_needed_reports_setup_failure_non_zero(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
if _lazy_init; then
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
    exit 1
else
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("rc:7 result:sync-failed")


def test_lazy_init_reports_missing_shell_as_failure(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    (project_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
check_and_install_uv() {{
    return 0
}}
PATH=''
if _lazy_init; then
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
    exit 1
else
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("rc:1 result:sync-failed")


def test_lazy_init_failure_prints_recovery_command_and_non_zero_exit(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
_lazy_init || true
lazy_init_result=${{LAZY_INIT_RESULT:-missing}}
case "$lazy_init_result" in
    sync-failed) handle_lazy_init_failure 9 ;;
    *)
        echo "unexpected-result:$lazy_init_result"
        exit 1
        ;;
esac
""")

    assert result.returncode == 9
    assert _expected_recovery_command(project_dir) in result.stderr




def test_entry_script_preserves_lazy_init_failure_exit_code_and_reports_real_setup_path(tmp_path: Path):
    project_dir = tmp_path / "project"
    bin_dir = project_dir / "bin"
    script_dir = project_dir / "scripts"
    bin_dir.mkdir(parents=True)
    script_dir.mkdir()

    entry_script = bin_dir / "remote-claude"
    entry_script.write_text((REPO_ROOT / "bin" / "remote-claude").read_text(encoding="utf-8"), encoding="utf-8")
    entry_script.chmod(0o755)

    common_sh = script_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = subprocess.run(
        ["sh", str(entry_script)],
        text=True,
        capture_output=True,
        cwd=project_dir,
        env={**os.environ, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 23
    assert _expected_recovery_command(project_dir) in result.stderr


def test_install_sh_skips_successfully_in_package_cache():
    result = run_common("""
SCRIPT_DIR="$HOME/.npm/_cacache/remote-claude/scripts"
PROJECT_DIR="$HOME/.npm/_cacache/remote-claude"
if _is_in_package_manager_cache; then
    echo cache-detected
else
    echo cache-missed
    exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("cache-detected")


def test_check_and_install_uv_supports_python_user_base_bin_path():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/Library/Python/3.12/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"

pip3() {
    if [ "$1" = "install" ]; then
        cat > "$HOME/Library/Python/3.12/bin/uv" <<'EOF'
#!/bin/sh
echo "uv 0.test"
EOF
        chmod +x "$HOME/Library/Python/3.12/bin/uv"
        return 0
    fi
    return 1
}

pip() {
    pip3 "$@"
}

python3() {
    if [ "$1" = "-m" ] && [ "$2" = "site" ] && [ "$3" = "--user-base" ]; then
        echo "$HOME/Library/Python/3.12"
        return 0
    fi
    return 1
}

curl() {
    return 1
}

_save_uv_path_to_runtime() {
    echo "saved:$1"
}

if check_and_install_uv; then
    echo "rc:0 uvbin:$(command -v uv)"
else
    echo "rc:$?"
    exit 1
fi
''')

    assert result.returncode == 0, result.stderr
    assert "saved:" in result.stdout
    assert "uvbin:" in result.stdout
    assert "/Library/Python/3.12/bin/uv" in result.stdout


def test_install_log_path_constant_in_common_sh():
    content = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")
    assert "/tmp/remote-claude-install.log" in content


def test_setup_completion_uses_scripts_path():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "scripts/completion.sh" in content
    assert '"$PROJECT_DIR/completion.sh"' not in content


def test_setup_runtime_creation_stays_in_success_flow():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert content.index("install_dependencies") < content.index("init_config_files")


def test_common_sh_declares_install_log_helpers():
    content = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")
    assert "_init_install_log()" in content
    assert "_install_stage()" in content
    assert "_install_fail_hint()" in content


def test_install_sh_initializes_install_log_helpers():
    content = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "_init_install_log" in content
    assert "_install_stage" in content


def test_setup_still_initializes_runtime_file():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "init_config_files()" in content
    assert "runtime.default.json" in content


def test_entry_scripts_define_project_dir_before_sourcing_common():
    for rel in ENTRY_SCRIPTS:
        content = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "PROJECT_DIR=" in content
        assert "scripts/_common.sh" in content
        assert content.index("PROJECT_DIR=") < content.index("scripts/_common.sh")


def test_check_and_install_uv_does_not_create_runtime_when_missing():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME"
uv() {
    return 0
}
if check_and_install_uv; then
    if [ -f "$HOME/.remote-claude/runtime.json" ]; then
        echo "runtime:created"
    else
        echo "runtime:missing"
    fi
else
    echo "uv:failed"
    exit 1
fi
''')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("runtime:missing")


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


def test_entry_scripts_still_source_common_sh_for_uv_logic():
    for rel in ENTRY_SCRIPTS:
        content = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "scripts/_common.sh" in content
        assert "pip3 install uv" not in content
        assert "pip install uv" not in content


def test_install_sh_does_not_skip_pnpm_global_install_in_cache(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "Library" / "pnpm" / "global" / "5" / "node_modules" / "remote-claude" / "scripts"
    scripts_dir.mkdir(parents=True)

    install_log_path = Path("/tmp/remote-claude-install.log")
    if install_log_path.exists():
        install_log_path.unlink()

    install_sh = scripts_dir / "install.sh"
    install_sh.write_text((REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8"), encoding="utf-8")
    install_sh.chmod(0o755)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    pyproject = project_dir / "Library" / "pnpm" / "global" / "5" / "node_modules" / "remote-claude" / "pyproject.toml"
    pyproject.parent.mkdir(parents=True, exist_ok=True)
    pyproject.write_text(
        "[project]\nname = 'demo'\nversion = '0.0.0'\nrequires-python = '>=3.11'\n",
        encoding="utf-8",
    )

    setup_sh = scripts_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 21\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    uv_stub = tmp_path / "uv"
    uv_stub.write_text(
        "#!/bin/sh\n"
        "cmd=\"$1\"\n"
        "shift || true\n"
        "case \"$cmd\" in\n"
        "  --version)\n"
        "    echo 'uv 0.test'\n"
        "    ;;\n"
        "  venv|sync)\n"
        "    exit 0\n"
        "    ;;\n"
        "  run)\n"
        "    if [ \"$1\" = \"python3\" ] && [ \"$2\" = \"--version\" ]; then\n"
        "      echo 'Python 3.12.0'\n"
        "    elif [ \"$1\" = \"which\" ] && [ \"$2\" = \"python3\" ]; then\n"
        "      echo '/usr/bin/python3'\n"
        "    elif [ \"$1\" = \"python3\" ] && [ \"$2\" = \"-c\" ]; then\n"
        "      echo '核心模块导入成功'\n"
        "    fi\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)

    result = subprocess.run(
        ["sh", str(install_sh), "--npm"],
        text=True,
        capture_output=True,
        cwd=project_dir,
        env={**os.environ, "HOME": str(project_dir), "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 21
    assert "执行 setup.sh 进行完整初始化..." in result.stdout
    assert install_log_path.exists()
    log_content = install_log_path.read_text(encoding="utf-8")
    assert "[script-fail]" in log_content





def test_setup_configure_shell_writes_completion_via_init_block(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    setup_sh = scripts_dir / "setup.sh"
    setup_sh.write_text((REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8"), encoding="utf-8")
    setup_sh.chmod(0o755)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname='demo'\nversion='0.0.0'\nrequires-python='>=3.11'\n",
        encoding="utf-8",
    )

    defaults_dir = project_dir / "resources" / "defaults"
    defaults_dir.mkdir(parents=True)
    (defaults_dir / "config.default.json").write_text('{"ui_settings": {"notify": {}, "custom_commands": {"commands": [{}]}}}\n', encoding="utf-8")
    (defaults_dir / "runtime.default.json").write_text('{"lark_group_mappings": {}}\n', encoding="utf-8")

    (project_dir / ".venv").mkdir()
    (project_dir / "remote_claude.py").write_text("#!/bin/sh\n", encoding="utf-8")
    (project_dir / "server").mkdir(parents=True)
    (project_dir / "server" / "server.py").write_text("#!/bin/sh\n", encoding="utf-8")
    (project_dir / "client").mkdir(parents=True)
    (project_dir / "client" / "client.py").write_text("#!/bin/sh\n", encoding="utf-8")

    bin_dir = project_dir / "bin"
    bin_dir.mkdir(parents=True)
    for name in ["cla", "cl", "cx", "cdx", "remote-claude"]:
        (bin_dir / name).write_text("#!/bin/sh\n", encoding="utf-8")

    uv_stub = tmp_path / "uv"
    uv_stub.write_text(
        "#!/bin/sh\n"
        "cmd=\"$1\"\n"
        "shift || true\n"
        "case \"$cmd\" in\n"
        "  --version)\n"
        "    echo 'uv 0.test'\n"
        "    ;;\n"
        "  sync)\n"
        "    exit 0\n"
        "    ;;\n"
        "  run)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)

    tmux_stub = tmp_path / "tmux"
    tmux_stub.write_text("#!/bin/sh\nif [ \"$1\" = \"-V\" ]; then echo 'tmux 3.6'; fi\n", encoding="utf-8")
    tmux_stub.chmod(0o755)

    claude_stub = tmp_path / "claude"
    claude_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    claude_stub.chmod(0o755)

    result = subprocess.run(
        ["sh", str(setup_sh), "--npm"],
        capture_output=True,
        cwd=tmp_path,
        env={**os.environ, "HOME": str(project_dir), "SHELL": "/bin/zsh", "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="ignore")
    rc_candidates = [
        project_dir / ".zshrc",
        project_dir / ".zprofile",
        project_dir / ".profile",
        project_dir / ".bashrc",
        project_dir / ".bash_profile",
    ]
    existing_rc_contents = [p.read_text(encoding="utf-8") for p in rc_candidates if p.exists()]
    assert existing_rc_contents

    begin = '# >>> remote-claude init >>>'
    end = '# <<< remote-claude init <<<'

    init_blocks = []
    for content in existing_rc_contents:
        if begin in content and end in content:
            init_blocks.append(content.split(begin, 1)[1].split(end, 1)[0])

    assert init_blocks
    assert all('export PATH="$HOME/.local/bin:$PATH"' in block for block in init_blocks)
    assert all('$PROJECT_DIR' not in block for block in init_blocks)
    assert any(f'. "{project_dir / "scripts" / "completion.sh"}"' in block for block in init_blocks)


def test_install_completion_hint_uses_dot_not_source():
    content = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "source $shell_rc" not in content
    assert ". $shell_rc" in content


def test_uninstall_skips_prompt_and_silently_cleans_config_dir_in_pnpm_context(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "runtime.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "npm_package_json": str(REPO_ROOT / "package.json"),
            "npm_lifecycle_event": "preuninstall",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert not data_dir.exists()
    assert "[y/N]" not in result.stdout
    assert "是否删除" not in result.stdout


def test_uninstall_keeps_manual_prompt_when_only_generic_npm_env_present(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "config.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "npm_config_loglevel": "notice",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert data_dir.exists()
    assert "[y/N]" in result.stdout
    assert "是否删除配置文件和数据" in result.stdout


def test_uninstall_keeps_manual_prompt_outside_npm_context(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "config.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert data_dir.exists()
    assert "[y/N]" in result.stdout
    assert "是否删除配置文件和数据" in result.stdout
def test_entry_init_failure_shows_manual_recovery_command(tmp_path: Path):
    project_dir = tmp_path / "project"
    bin_dir = project_dir / "bin"
    scripts_dir = project_dir / "scripts"
    bin_dir.mkdir(parents=True)
    scripts_dir.mkdir()

    entry = bin_dir / "remote-claude"
    entry.write_text((REPO_ROOT / "bin" / "remote-claude").read_text(encoding="utf-8"), encoding="utf-8")
    entry.chmod(0o755)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["sh", str(entry)],
        capture_output=True,
        text=True,
        cwd=project_dir,
        env={**os.environ, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 127
    assert _expected_recovery_command(project_dir) in result.stderr


