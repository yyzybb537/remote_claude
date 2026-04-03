import importlib.util
import json
import os
import re
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

PIP_SOURCE_MARKERS = {
    "官方": "https://pypi.org/simple",
    "阿里": "https://mirrors.aliyun.com/pypi/simple/",
    "清华": "https://pypi.tuna.tsinghua.edu.cn/simple/",
}


def extract_first_pip_sources(output: str) -> list[str]:
    seen_sources: set[str] = set()
    ordered_sources: list[str] = []
    for line in output.splitlines():
        if "install uv" not in line:
            continue
        for source, marker in PIP_SOURCE_MARKERS.items():
            if marker in line and source not in seen_sources:
                seen_sources.add(source)
                ordered_sources.append(source)
                break
    return ordered_sources


def _expected_recovery_command(project_root: Path) -> str:
    return f"sh {project_root / 'scripts' / 'setup.sh'} --npm --lazy"


def run_common(script_body: str, *, env: dict[str, str] | None = None, disable_auto_lazy_init: bool = True) -> \
subprocess.CompletedProcess[str]:
    lazy_init_prefix = "LAZY_INIT_DISABLE_AUTO_RUN=1\nexport LAZY_INIT_DISABLE_AUTO_RUN\n" if disable_auto_lazy_init else ""
    shell_script = f"""#!/bin/sh
set -e
{lazy_init_prefix}SCRIPT_DIR='{REPO_ROOT}/scripts'
PROJECT_DIR='{REPO_ROOT}'
. '{COMMON_SH}'
{script_body}
"""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["sh"],
        input=shell_script,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=run_env,
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


def test_common_normalizes_project_dir_when_pointing_to_scripts_dir():
    project_dir = Path(str(REPO_ROOT))
    scripts_dir = project_dir / "scripts"

    shell_script = f"""#!/bin/sh
set -e
PROJECT_DIR='{scripts_dir}'
. '{COMMON_SH}'
printf 'project:%s\n' "$PROJECT_DIR"
printf 'script:%s\n' "$SCRIPT_DIR"
"""
    result = subprocess.run(
        ["sh"],
        input=shell_script,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert f"project:{project_dir}" in result.stdout
    assert f"script:{scripts_dir}" in result.stdout


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


def test_setup_shell_init_block_only_exports_public_bin_not_project_venv():
    setup_script = REPO_ROOT / "scripts" / "setup.sh"
    content = setup_script.read_text(encoding="utf-8")

    assert '$HOME/.local/bin' in content
    assert 'scripts/completion.sh' in content
    assert '.venv/bin/remote-claude' not in content
    assert '.venv/bin:$PATH' not in content


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


def _run_lazy_init_case(tmp_path: Path, case: dict[str, object]) -> subprocess.CompletedProcess[str]:
    project_dir = tmp_path / str(case["name"]) / "project"
    script_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    script_dir.mkdir(parents=True)
    venv_dir.mkdir()

    for rel_path, content in dict(case.get("project_files", {})).items():
        target = project_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text(str(case["setup_script"]), encoding="utf-8")
    setup_sh.chmod(0o755)

    shell_script = f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
{case.get('prepare', '')}{case['command']}{case.get('after', '')}"""
    result = run_common(shell_script)

    assert result.returncode == case["expected_returncode"], f"{case['name']}: {result.stderr}"
    for expected in case.get("expected_stdout", []):
        assert expected in result.stdout, f"{case['name']}: missing {expected!r} in {result.stdout!r}"
    for unexpected in case.get("unexpected_stdout", []):
        assert unexpected not in result.stdout, f"{case['name']}: unexpected {unexpected!r} in {result.stdout!r}"
    for rel_path in case.get("expected_paths", []):
        assert (project_dir / rel_path).exists(), str(case["name"])
    return result


def test_lazy_init_if_needed_sync_outcomes(tmp_path: Path):
    success_command = '    if _lazy_init; then\n        status=$?\n        echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"\n    else\n        status=$?\n        echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"\n        exit 1\n    fi\n'
    failure_command = '    if _lazy_init; then\n        status=$?\n        echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"\n        exit 1\n    else\n        status=$?\n        echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"\n    fi\n'
    cases = [
        {
            "name"               : "noop_when_sync_not_needed",
            "project_files"      : {
                "pyproject.toml": '[project]\nname="demo"\nversion="0.1.0"\n',
                "uv.lock"       : "version = 1\n",
            },
            "setup_script"       : "#!/bin/sh\ntouch \"$PROJECT_DIR/.sync-ran\"\nexit 0\n",
            "prepare"            : '    _write_dependency_fingerprint "$PROJECT_DIR" || exit 1\n    before_fp=$(cat "$PROJECT_DIR/.venv/.deps-fingerprint")\n',
            "command"            : success_command,
            "after"              : '    after_fp=$(cat "$PROJECT_DIR/.venv/.deps-fingerprint")\n    [ -f "$PROJECT_DIR/.sync-ran" ] && echo sync-ran\n    [ "$before_fp" = "$after_fp" ] && echo fp-stable\n',
            "expected_stdout"    : ["rc:0 result:no-sync-needed", "fp-stable"],
            "unexpected_stdout"  : ["sync-ran"],
            "expected_returncode": 0,
        },
        {
            "name"               : "trigger_sync_when_dependency_fingerprint_changes",
            "project_files"      : {
                "pyproject.toml": '[project]\nname="demo"\nversion="0.1.0"\n',
                "uv.lock"       : "version = 1\n",
            },
            "setup_script"       : "#!/bin/sh\ntouch \"$PROJECT_DIR/.sync-ran\"\nexit 0\n",
            "prepare"            : '    _write_dependency_fingerprint "$PROJECT_DIR" || exit 1\n    before_fp=$(cat "$PROJECT_DIR/.venv/.deps-fingerprint")\n    printf "\\n# changed\\n" >> "$PROJECT_DIR/uv.lock"\n',
            "command"            : success_command,
            "after"              : '    after_fp=$(cat "$PROJECT_DIR/.venv/.deps-fingerprint")\n    [ -f "$PROJECT_DIR/.sync-ran" ] && echo sync-ran\n    [ "$before_fp" != "$after_fp" ] && echo fp-updated\n',
            "expected_stdout"    : ["rc:0", "result:sync-completed", "sync-ran", "fp-updated"],
            "expected_returncode": 0,
            "expected_paths"     : [".sync-ran"],
        },
        {
            "name"               : "report_setup_success_after_trigger",
            "project_files"      : {"package-lock.json": "{}\n"},
            "setup_script"       : "#!/bin/sh\nexit 0\n",
            "command"            : success_command,
            "expected_stdout"    : ["rc:0 result:sync-completed"],
            "expected_returncode": 0,
        },
        {
            "name"               : "report_setup_failure_non_zero",
            "project_files"      : {},
            "setup_script"       : "#!/bin/sh\nexit 7\n",
            "command"            : failure_command,
            "expected_stdout"    : ["rc:7 result:sync-failed"],
            "expected_returncode": 0,
        },
    ]

    for case in cases:
        _run_lazy_init_case(tmp_path, case)


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
        assert "resources/defaults/" not in content, rel


def test_test_lark_management_uses_common_runtime_variables():
    content = (REPO_ROOT / "scripts" / "test_lark_management.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_LARK_PID_FILE" in content
    assert "REMOTE_CLAUDE_LARK_STATUS_FILE" in content
    assert "REMOTE_CLAUDE_LARK_LOG_FILE" in content
    assert "/tmp/remote-claude/lark.pid" not in content


def test_install_uv_multi_source_uses_pip_as_last_fallback():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/calls.log"

pip3() {
    echo "pip3 $*" >> "$TMPDIR_PATH/calls.log"
    cat > "$HOME/.local/bin/uv" <<'EOF'
#!/bin/sh
echo "uv 0.test"
EOF
    chmod +x "$HOME/.local/bin/uv"
    return 0
}

pip() { pip3 "$@"; }

curl() {
    echo "curl" >> "$TMPDIR_PATH/calls.log"
    return 1
}

mamba() {
    echo "mamba $*" >> "$TMPDIR_PATH/calls.log"
    return 1
}

conda() {
    echo "conda $*" >> "$TMPDIR_PATH/calls.log"
    return 1
}

uname() {
    echo Darwin
}

brew() {
    echo "brew $*" >> "$TMPDIR_PATH/calls.log"
    return 1
}

install_uv_multi_source || exit 1
cat "$TMPDIR_PATH/calls.log"
''')

    assert result.returncode == 0, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert "curl" in lines
    assert any(line.startswith("brew install uv") for line in lines)
    pip_idx = next(i for i, line in enumerate(lines) if line.startswith("pip3 install uv "))
    curl_idx = next(i for i, line in enumerate(lines) if line == "curl")
    brew_idx = next(i for i, line in enumerate(lines) if line.startswith("brew install uv"))
    assert curl_idx < brew_idx < pip_idx


def test_install_uv_multi_source_reports_manual_pip_upgrade_when_pip_is_too_old():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$TMPDIR_PATH/bin" "$HOME"
export PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"

cat > "$TMPDIR_PATH/bin/pip3" <<'EOF'
#!/bin/sh
printf 'ERROR: no such option: --break-system-packages\n' >&2
exit 2
EOF
chmod +x "$TMPDIR_PATH/bin/pip3"
ln -s "$TMPDIR_PATH/bin/pip3" "$TMPDIR_PATH/bin/pip"

cat > "$TMPDIR_PATH/bin/curl" <<'EOF'
#!/bin/sh
exit 127
EOF
chmod +x "$TMPDIR_PATH/bin/curl"

cat > "$TMPDIR_PATH/bin/uname" <<'EOF'
#!/bin/sh
echo Linux
EOF
chmod +x "$TMPDIR_PATH/bin/uname"

if install_uv_multi_source; then
    echo should-fail
    exit 1
fi
''', env={"PATH": "/usr/bin:/bin", "REMOTE_CLAUDE_STATE_FILE": "/nonexistent/state.json"}, disable_auto_lazy_init=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "当前 pip 版本过低，无法安装 uv；请先手动升级 pip 后重试" in result.stdout


def test_install_uv_multi_source_prefers_official_script_before_pip_fallback():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/calls.log"

pip3() {
    echo "pip3 $*" >> "$TMPDIR_PATH/calls.log"
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

pip() { pip3 "$@"; }

curl() {
    echo "curl-called" >> "$TMPDIR_PATH/calls.log"
    return 1
}

mamba() {
    echo "mamba-called" >> "$TMPDIR_PATH/calls.log"
    return 1
}

conda() {
    echo "conda-called" >> "$TMPDIR_PATH/calls.log"
    return 1
}

uname() {
    echo Linux
}

if install_uv_multi_source; then
    echo "ok"
else
    echo "failed"
    exit 1
fi

cat "$TMPDIR_PATH/calls.log"
''')

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    curl_idx = next(i for i, line in enumerate(lines) if line == "curl-called")
    pip_idx = next(i for i, line in enumerate(lines) if line.startswith("pip3 install uv "))
    assert curl_idx < pip_idx


def test_install_uv_multi_source_falls_back_to_pip_after_other_methods_fail():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
: > "$TMPDIR_PATH/calls.log"

pip3() {
    echo "pip3 $*" >> "$TMPDIR_PATH/calls.log"
    cat > "$HOME/.local/bin/uv" <<'EOF'
#!/bin/sh
echo "uv 0.test"
EOF
    chmod +x "$HOME/.local/bin/uv"
    return 0
}

pip() { pip3 "$@"; }

curl() {
    echo "curl-called" >> "$TMPDIR_PATH/calls.log"
    return 1
}

mamba() {
    echo "mamba-called" >> "$TMPDIR_PATH/calls.log"
    return 1
}

conda() {
    echo "conda-called" >> "$TMPDIR_PATH/calls.log"
    return 1
}

uname() {
    echo Linux
}

if install_uv_multi_source; then
    echo "ok"
else
    echo "failed"
    exit 1
fi

cat "$TMPDIR_PATH/calls.log"
''')

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert "curl-called" in lines
    assert any(line.startswith("pip3 install uv ") for line in lines)


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
    assert extract_first_pip_sources(result.stdout) == ["官方", "阿里", "清华"]


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
    return 1
}

mamba() {
    echo "mamba-called" >> "$TMPDIR_PATH/fallback.log"
    return 1
}

conda() {
    echo "conda-called" >> "$TMPDIR_PATH/fallback.log"
    return 1
}

uname() {
    echo Linux
}

install_uv_multi_source || true
cat "$TMPDIR_PATH/pip_args.log"
cat "$TMPDIR_PATH/fallback.log"
''')

    assert result.returncode == 0, result.stderr
    pip_uv_lines = [l for l in result.stdout.splitlines() if "install uv" in l]
    assert len(pip_uv_lines) >= 3
    assert "curl-called" in result.stdout


def test_check_and_install_uv_prefers_working_system_uv_over_stale_runtime_entry(tmp_path: Path):
    state_dir = tmp_path / "home" / ".remote-claude"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "state.json"
    fake_uv_dir = tmp_path / "bin"
    fake_uv_dir.mkdir()
    fake_uv = fake_uv_dir / "uv"
    fake_uv.write_text("#!/bin/sh\necho 'uv 0.recovered'\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    stale_uv = tmp_path / "missing" / "uv"
    state_file.write_text(json.dumps({"uv_path": str(stale_uv)}), encoding="utf-8")

    result = run_common(f'''
export HOME='{tmp_path / 'home'}'
PATH='{fake_uv_dir}:/usr/bin:/bin'
command() {{
    if [ "$1" = "-v" ] && [ "$2" = "uv" ]; then
        if [ -x '{fake_uv}' ]; then
            printf '%s\n' '{fake_uv}'
            return 0
        fi
        return 1
    fi
    if [ "$1" = "python3" ]; then
        shift
        python3 "$@"
        return $?
    fi
    return 127
}}
if check_and_install_uv; then
    echo "uv:$(command -v uv)"
else
    echo failed
    exit 1
fi
''', env={"PATH": f"{fake_uv_dir}:/usr/bin:/bin"})

    assert result.returncode == 0, result.stderr
    assert f"uv:{fake_uv}" in result.stdout


def test_check_and_install_uv_reinstalls_after_stale_uv_path(tmp_path: Path):
    state_dir = tmp_path / "home" / ".remote-claude"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps({"uv_path": str(tmp_path / "missing" / "uv")}), encoding="utf-8")

    result = run_common(f'''
export HOME='{tmp_path / 'home'}'
TMPDIR_PATH="$HOME/fakebin"
mkdir -p "$TMPDIR_PATH"
PATH="$TMPDIR_PATH:/usr/bin:/bin"
cat > "$TMPDIR_PATH/python3" <<'EOF'
#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "site" ] && [ "$3" = "--user-base" ]; then
    printf '%s\n' "$HOME/.local"
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "site" ] && [ "$3" = "--user-site" ]; then
    printf '%s\n' "$HOME/.local/lib/python3.12/site-packages"
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "uv" ] && [ "$3" = "--version" ]; then
    printf '%s\n' 'uv 0.reinstalled'
    exit 0
fi
exit 1
EOF
chmod +x "$TMPDIR_PATH/python3"
ln -sf "$TMPDIR_PATH/python3" "$TMPDIR_PATH/python"
pip3() {{
    mkdir -p "$HOME/.local/bin" "$HOME/.local/lib/python3.12/site-packages/uv"
    cat > "$HOME/.local/bin/uv" <<'EOF'
#!/bin/sh
exit 1
EOF
    chmod +x "$HOME/.local/bin/uv"
    touch "$HOME/.local/lib/python3.12/site-packages/uv/__init__.py"
    return 0
}}
pip() {{ pip3 "$@"; }}
curl() {{ return 1; }}
mamba() {{ return 1; }}
conda() {{ return 1; }}
uname() {{ echo Linux; }}
if check_and_install_uv; then
    echo ok
else
    echo failed
    exit 1
fi
''', env={"PATH": "/usr/bin:/bin"}, disable_auto_lazy_init=False)

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_install_uv_multi_source_exports_user_base_bin_when_pip_install_succeeds():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME/.local/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"

python3() {
    if [ "$1" = "-m" ] && [ "$2" = "site" ] && [ "$3" = "--user-base" ]; then
        printf '%s\n' "$HOME/.local"
        return 0
    fi
    command python3 "$@"
}

pip3() {
    cat > "$HOME/.local/bin/uv" <<'EOF'
#!/bin/sh
if [ "$1" = "--version" ]; then
    echo "uv 0.test"
    exit 0
fi
exit 0
EOF
    chmod +x "$HOME/.local/bin/uv"
    return 0
}

pip() { pip3 "$@"; }

curl() { return 1; }

mamba() { return 1; }
conda() { return 1; }
uname() { echo Linux; }

install_uv_multi_source || exit 1
command -v uv
uv --version
''')

    assert result.returncode == 0, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert any(line.endswith('/home/.local/bin/uv') for line in lines)
    assert 'uv 0.test' in result.stdout


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
    assert 'cmd="curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh"' in out
    assert "exit_code=127" in out


def test_shell_scripts_keep_posix_compat_static_guards():
    setup_content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    uninstall_content = (REPO_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
    completion_content = (REPO_ROOT / "scripts" / "completion.sh").read_text(encoding="utf-8")

    assert "trap cleanup_tmpdir EXIT" not in setup_content
    assert "trap 'cleanup_tmpdir' 0" in setup_content
    assert "local " not in uninstall_content

    bash_branch_match = re.search(
        r'elif \[ -n "\$\{BASH_VERSION:-}" ]; then\n(?P<body>.*?)(?=\nfi\n?)',
        completion_content,
        re.S,
    )
    assert bash_branch_match, "应能定位 completion.sh 的 bash 分支"
    bash_branch = bash_branch_match.group("body")
    assert "local " not in bash_branch


def test_dependency_fingerprint_write_fails_when_hash_command_errors(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    script_dir.mkdir(parents=True)
    venv_dir.mkdir()
    (project_dir / "pyproject.toml").write_text('[project]\nname="demo"\nversion="0.1.0"\n', encoding="utf-8")

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
sha256sum() {{ return 2; }}
if _write_dependency_fingerprint "$PROJECT_DIR"; then
    echo "unexpected-success"
    exit 1
else
    write_rc=$?
    echo "write-failed:$write_rc"
fi
if _needs_sync; then
    echo "needs-sync"
else
    echo "unexpected-no-sync"
    exit 1
fi
if [ -f "$PROJECT_DIR/.venv/.deps-fingerprint" ]; then
    echo "fingerprint-exists"
fi
""")

    assert result.returncode == 0, result.stderr
    assert "write-failed:1" in result.stdout
    assert "needs-sync" in result.stdout
    assert "unexpected-success" not in result.stdout
    assert "unexpected-no-sync" not in result.stdout
    assert "fingerprint-exists" not in result.stdout


def test_dependency_fingerprint_falls_back_when_sha_tools_unavailable(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    script_dir.mkdir(parents=True)
    venv_dir.mkdir()
    (project_dir / "pyproject.toml").write_text('[project]\nname="demo"\nversion="0.1.0"\n', encoding="utf-8")
    (project_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
sha256sum() {{ return 127; }}
shasum() {{ return 127; }}
openssl() {{ return 127; }}
_write_dependency_fingerprint "$PROJECT_DIR" || {{
    echo "write-failed"
    exit 1
}}
fp=$(cat "$PROJECT_DIR/.venv/.deps-fingerprint")
echo "fp:$fp"
if _needs_sync; then
    echo "needs-sync"
    exit 1
else
    echo "no-sync"
fi
""")

    assert result.returncode == 0, result.stderr
    assert "write-failed" not in result.stdout
    assert "no-sync" in result.stdout
    assert "fp:" in result.stdout
    assert "fp:\n" not in result.stdout


def test_lazy_init_warns_when_dependency_fingerprint_write_fails(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)

    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
_write_dependency_fingerprint() {{
    return 1
}}
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
    assert "rc:0" in result.stdout
    assert "result:sync-completed" in result.stdout
    assert "依赖指纹写入失败" in result.stdout


def test_lazy_init_if_needed_triggers_sync_when_dependency_fingerprint_changes(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    venv_dir = project_dir / ".venv"
    script_dir.mkdir(parents=True)
    venv_dir.mkdir()
    (project_dir / "pyproject.toml").write_text('[project]\nname="demo"\nversion="0.1.0"\n', encoding="utf-8")
    (project_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\ntouch \"$PROJECT_DIR/.sync-ran\"\nexit 0\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
_write_dependency_fingerprint "$PROJECT_DIR" || exit 1
before_fp=$(cat "$PROJECT_DIR/.venv/.deps-fingerprint")
printf '\n# changed\n' >> "$PROJECT_DIR/uv.lock"
if _lazy_init; then
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
else
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
    exit 1
fi
after_fp=$(cat "$PROJECT_DIR/.venv/.deps-fingerprint")
[ -f "$PROJECT_DIR/.sync-ran" ] && echo sync-ran
[ "$before_fp" != "$after_fp" ] && echo fp-updated
""")

    assert result.returncode == 0, result.stderr
    assert "rc:0" in result.stdout
    assert "result:sync-completed" in result.stdout
    assert "sync-ran" in result.stdout
    assert "fp-updated" in result.stdout
    assert (project_dir / ".sync-ran").exists()


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


def test_check_env_allows_skip_when_feishu_not_required(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    resources_dir = project_dir / "resources" / "defaults"
    script_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)

    check_env = script_dir / "check-env.sh"
    check_env.write_text((REPO_ROOT / "scripts" / "check-env.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (script_dir / "_common.sh").write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"),
                                           encoding="utf-8")
    (resources_dir / ".env.example").write_text("FEISHU_APP_ID=cli_xxxxx\nFEISHU_APP_SECRET=xxxxx\n", encoding="utf-8")

    shell_script = f"""#!/bin/sh
set -e
export HOME='{tmp_path / 'home'}'
mkdir -p "$HOME"
export REMOTE_CLAUDE_REQUIRE_FEISHU=0
PROJECT_DIR='{project_dir}'
. '{check_env}'
echo skip-ok
"""
    result = subprocess.run(["sh"], input=shell_script, text=True, capture_output=True, cwd=project_dir)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("skip-ok")


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
LAZY_INIT_DISABLE_AUTO_RUN=1
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
    assert f"env_template={project_dir / 'resources' / 'defaults' / 'env.example'}" in result.stdout
    assert f"settings_template={project_dir / 'resources' / 'defaults' / 'settings.json.example'}" in result.stdout
    assert f"state_template={project_dir / 'resources' / 'defaults' / 'state.json.example'}" in result.stdout


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
LAZY_INIT_DISABLE_AUTO_RUN=1
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
LAZY_INIT_DISABLE_AUTO_RUN=1
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


def test_lazy_init_failure_surfaces_log_hint_and_stage_details(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/bin/sh\necho 'setup stderr detail' >&2\nexit 9\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
INSTALL_LOG_FILE='{tmp_path / 'install.log'}'
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
    assert "setup stderr detail" in result.stderr
    assert str(tmp_path / 'install.log') in result.stderr


def _prepare_entry_script_project(tmp_path: Path, *entry_names: str) -> tuple[Path, Path, Path, Path]:
    project_dir = tmp_path / "project"
    bin_dir = project_dir / "bin"
    script_dir = project_dir / "scripts"
    bin_dir.mkdir(parents=True)
    script_dir.mkdir()

    for name in entry_names:
        target = bin_dir / name
        target.write_text((REPO_ROOT / "bin" / name).read_text(encoding="utf-8"), encoding="utf-8")
        target.chmod(0o755)

    (script_dir / "_common.sh").write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"),
                                           encoding="utf-8")
    (script_dir / "check-env.sh").write_text((REPO_ROOT / "scripts" / "check-env.sh").read_text(encoding="utf-8"),
                                             encoding="utf-8")
    (script_dir / "_help.sh").write_text((REPO_ROOT / "scripts" / "_help.sh").read_text(encoding="utf-8"),
                                         encoding="utf-8")
    (script_dir / "setup.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (script_dir / "setup.sh").chmod(0o755)

    # 创建资源模板目录和文件（避免 "缺少环境变量模板文件" 错误）
    resources_dir = project_dir / "resources" / "defaults"
    resources_dir.mkdir(parents=True)
    (resources_dir / "env.example").write_text("FEISHU_APP_ID=\nFEISHU_APP_SECRET=\n", encoding="utf-8")
    (resources_dir / "settings.json.example").write_text('{}\n', encoding="utf-8")
    (resources_dir / "state.json.example").write_text('{}\n', encoding="utf-8")

    home = tmp_path / "home"
    (home / ".remote-claude").mkdir(parents=True)
    (home / ".remote-claude" / "runtime.json").write_text("{}\n", encoding="utf-8")
    (project_dir / "package.json").write_text('{"name":"remote-claude","version":"0.test"}\n', encoding="utf-8")
    (project_dir / "pyproject.toml").write_text('[project]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
    python_bin_dir = project_dir / ".venv" / "bin"
    python_bin_dir.mkdir(parents=True)
    python_entry = python_bin_dir / "python3"
    python_entry.write_text(
        "#!/bin/sh\n"
        "printf 'CWD:%s\\n' \"$PWD\"\n"
        "printf 'PY:%s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    python_entry.chmod(0o755)

    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    return project_dir, bin_dir, script_dir, bindir


def test_entry_script_runtime_behaviors(tmp_path: Path):
    project_dir, bin_dir, _, bindir = _prepare_entry_script_project(tmp_path, "cla")
    uv_stub = bindir / "uv"
    uv_stub.write_text("#!/bin/sh\nprintf 'UV:%s\\n' \"$*\"\n", encoding="utf-8")
    uv_stub.chmod(0o755)

    cases = [
        {
            "name": "skip_feishu_prompt_and_executes_remote_claude_when_optional",
            "cwd": project_dir,
            "env": {"REMOTE_CLAUDE_REQUIRE_FEISHU": "0"},
            "returncode": 0,
            "contains": ["PY:", "remote_claude.py start", "--hello"],
            "not_contains": ["飞书客户端尚未配置", "remote_claude.py lark start"],
        },
        {
            "name": "use_startup_dir_not_project_dir_for_session_name",
            "cwd": tmp_path / "workspace",
            "env": {"REMOTE_CLAUDE_REQUIRE_FEISHU": "0"},
            "returncode": 0,
            "contains": [],
            "not_contains": [],
            "dynamic_contains": lambda cwd, project: [f"remote_claude.py start {cwd}_"],
            "dynamic_not_contains": lambda cwd, project: [f"remote_claude.py start {project}_"],
        },
        {
            "name": "error_when_startup_dir_is_invalid",
            "cwd": tmp_path,
            "env": {
                "REMOTE_CLAUDE_REQUIRE_FEISHU": "0",
                "STARTUP_DIR": str(tmp_path / "missing-workspace"),
            },
            "returncode_non_zero": True,
            "contains": ["启动目录"],
            "not_contains": ["UV:"],
        },
    ]

    for case in cases:
        cwd = case["cwd"]
        if not cwd.exists():
            cwd.mkdir(parents=True)

        result = subprocess.run(
            ["sh", str(bin_dir / "cla"), "--hello"],
            text=True,
            capture_output=True,
            cwd=cwd,
            env={
                **os.environ,
                "HOME": str(tmp_path / "home"),
                "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin",
                **case["env"],
            },
        )

        combined = result.stdout + result.stderr
        if case.get("returncode_non_zero"):
            assert result.returncode != 0, case["name"]
        else:
            assert result.returncode == case["returncode"], f"{case['name']}: {result.stderr}"

        expected_contains = list(case["contains"])
        expected_not_contains = list(case["not_contains"])
        if "dynamic_contains" in case:
            expected_contains.extend(case["dynamic_contains"](cwd, project_dir))
        if "dynamic_not_contains" in case:
            expected_not_contains.extend(case["dynamic_not_contains"](cwd, project_dir))

        for expected in expected_contains:
            assert expected in combined, f"{case['name']}: missing {expected!r} in {combined!r}"
        for unexpected in expected_not_contains:
            assert unexpected not in combined, f"{case['name']}: unexpected {unexpected!r} in {combined!r}"


def test_check_and_install_uv_supports_python_user_base_bin_path():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
export LAZY_INIT_DISABLE_AUTO_RUN=1
mkdir -p "$HOME/Library/Python/3.12/bin" "$TMPDIR_PATH/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"

cat > "$TMPDIR_PATH/bin/python3" <<'EOF'
#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "site" ] && [ "$3" = "--user-base" ]; then
    echo "$HOME/Library/Python/3.12"
    exit 0
fi
exit 1
EOF
chmod +x "$TMPDIR_PATH/bin/python3"
cat > "$TMPDIR_PATH/bin/pip3" <<'EOF'
#!/bin/sh
if [ "$1" = "install" ]; then
    mkdir -p "$HOME/Library/Python/3.12/bin"
    cat > "$HOME/Library/Python/3.12/bin/uv" <<'UVEOF'
#!/bin/sh
echo "uv 0.test"
UVEOF
    chmod +x "$HOME/Library/Python/3.12/bin/uv"
    exit 0
fi
exit 1
EOF
chmod +x "$TMPDIR_PATH/bin/pip3"
ln -s "$TMPDIR_PATH/bin/pip3" "$TMPDIR_PATH/bin/pip"
cat > "$TMPDIR_PATH/bin/curl" <<'EOF'
#!/bin/sh
exit 1
EOF
chmod +x "$TMPDIR_PATH/bin/curl"

_save_uv_path_to_runtime() {
    echo "saved:$1"
}

if install_uv_multi_source; then
    _save_uv_path_to_runtime "$(command -v uv)"
    echo "rc:0 uvbin:$(command -v uv)"
else
    echo "rc:$?"
    exit 1
fi
''', env={"PATH": "/usr/bin:/bin", "REMOTE_CLAUDE_STATE_FILE": "/nonexistent/state.json"})

    assert result.returncode == 0, result.stderr
    assert "saved:" in result.stdout
    assert "uvbin:" in result.stdout
    assert "/Library/Python/3.12/bin/uv" in result.stdout


def test_install_uv_multi_source_detects_uv_from_fallback_user_bin_scan_after_pip_install():
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$TMPDIR_PATH/bin" "$HOME/Library/Python/3.12/bin"
PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"
INSTALL_LOG_FILE="$TMPDIR_PATH/install.log"

cat > "$TMPDIR_PATH/bin/python3" <<'EOF'
#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "site" ] && [ "$3" = "--user-base" ]; then
    echo "$HOME/declared-user-base"
    exit 0
fi
exit 1
EOF
chmod +x "$TMPDIR_PATH/bin/python3"

cat > "$TMPDIR_PATH/bin/pip3" <<'EOF'
#!/bin/sh
if [ "$1" = "install" ]; then
    mkdir -p "$HOME/Library/Python/3.12/bin"
    cat > "$HOME/Library/Python/3.12/bin/uv" <<'UVEOF'
#!/bin/sh
if [ "$1" = "--version" ]; then
    echo "uv 0.test"
    exit 0
fi
echo "uv 0.test"
exit 0
UVEOF
    chmod +x "$HOME/Library/Python/3.12/bin/uv"
    exit 0
fi
exit 1
EOF
chmod +x "$TMPDIR_PATH/bin/pip3"
ln -s "$TMPDIR_PATH/bin/pip3" "$TMPDIR_PATH/bin/pip"
cat > "$TMPDIR_PATH/bin/curl" <<'EOF'
#!/bin/sh
exit 1
EOF
chmod +x "$TMPDIR_PATH/bin/curl"

if install_uv_multi_source; then
    echo "uvbin:$(command -v uv)"
    cat "$INSTALL_LOG_FILE"
else
    echo "rc:$?"
    exit 1
fi
''', env={"PATH": "/usr/bin:/bin", "REMOTE_CLAUDE_STATE_FILE": "/nonexistent/state.json"})

    assert result.returncode == 0, result.stderr
    assert "uvbin:" in result.stdout
    assert "/Library/Python/3.12/bin/uv" in result.stdout
    assert "[script-fail][uv-install-user-bin]" not in result.stdout


def test_common_shortcut_helper_declares_launcher_and_permission_vars():
    content = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")
    assert "_remote_claude_shortcut_main()" in content
    assert "REMOTE_CLAUDE_SHORTCUT_LAUNCHER" in content
    assert "REMOTE_CLAUDE_SHORTCUT_PERMISSION_ARGS" in content


def test_setup_runtime_creation_stays_in_success_flow():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert content.index("install_dependencies") < content.index("init_config_files")



def test_entry_scripts_define_project_dir_before_sourcing_common():
    for rel in ENTRY_SCRIPTS:
        content = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "PROJECT_DIR=" in content
        assert "scripts/_common.sh" in content
        assert content.index("PROJECT_DIR=") < content.index("scripts/_common.sh")


def test_scripts_define_project_dir_before_common_source():
    scripts = [
        "scripts/install.sh",
        "scripts/setup.sh",
        "scripts/uninstall.sh",
        "scripts/check-env.sh",
        "scripts/npm-publish.sh",
        "scripts/test_lark_management.sh",
        "scripts/preinstall.sh",
        "scripts/completion.sh",
    ]
    for rel in scripts:
        content = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "PROJECT_DIR=" in content
        assert "scripts/_common.sh" in content
        assert content.index("PROJECT_DIR=") < content.index("scripts/_common.sh")


def test_check_env_works_via_symlink_from_random_cwd(tmp_path: Path):
    project_dir = REPO_ROOT
    link_dir = tmp_path / "linkbin"
    link_dir.mkdir(parents=True)
    target = project_dir / "scripts" / "check-env.sh"
    link = link_dir / "check-env"
    link.symlink_to(target)

    shell_script = f"""#!/bin/sh
set -e
export HOME='{tmp_path / 'home'}'
mkdir -p "$HOME"
export REMOTE_CLAUDE_REQUIRE_FEISHU=0
PROJECT_DIR='{project_dir}'
. '{link}'
echo ok
"""
    result = subprocess.run(["sh"], input=shell_script, text=True, capture_output=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")


def test_check_env_rejects_legacy_directory_argument(tmp_path: Path):
    project_dir = REPO_ROOT
    script = project_dir / "scripts" / "check-env.sh"

    result = subprocess.run(
        ["sh", str(script), str(project_dir)],
        text=True,
        capture_output=True,
        cwd=project_dir,
        env={**os.environ, "REMOTE_CLAUDE_REQUIRE_FEISHU": "0"},
    )

    assert result.returncode == 2
    assert "目录参数已废弃" in (result.stderr + result.stdout)


def _load_report_install_module(entry_path: Path):
    spec = importlib.util.spec_from_file_location(f"report_install_test_{hash(entry_path)}", entry_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_install_version_resolution_not_depend_on_cwd(tmp_path: Path):
    script = REPO_ROOT / "scripts" / "report_install.py"
    expected_root = REPO_ROOT.resolve()
    expected_version = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["version"]

    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        module = _load_report_install_module(script)
        resolved_root = module._resolve_project_root().resolve()
        resolved_version = module._get_version()
    finally:
        os.chdir(original_cwd)

    assert resolved_root == expected_root
    assert resolved_version == expected_version
    assert resolved_version != "unknown"


def test_setup_lazy_mode_succeeds_after_pip_user_uv_install(tmp_path: Path):
    home_dir = tmp_path / "home"
    fake_bin = tmp_path / "fake-bin"
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    resources_dir = project_dir / "resources" / "defaults"

    script_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)
    fake_bin.mkdir(parents=True)
    (home_dir / ".local" / "bin").mkdir(parents=True)

    setup_script = script_dir / "setup.sh"
    setup_script.write_text((REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (script_dir / "_common.sh").write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"),
                                           encoding="utf-8")
    (script_dir / "_help.sh").write_text((REPO_ROOT / "scripts" / "_help.sh").read_text(encoding="utf-8"),
                                         encoding="utf-8")
    (script_dir / "completion.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (project_dir / "pyproject.toml").write_text('[project]\nname="demo"\nversion="0.1.0"\n', encoding="utf-8")
    (resources_dir / "settings.json.example").write_text("{}\n", encoding="utf-8")
    (resources_dir / "state.json.example").write_text("{}\n", encoding="utf-8")

    pip_script = fake_bin / "pip3"
    pip_script.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$HOME/.local/bin\"\n"
        "cat > \"$HOME/.local/bin/uv\" <<'EOF'\n"
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        "  echo \"uv 0.test\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"venv\" ]; then\n"
        "  mkdir -p .venv/bin\n"
        "  cat > .venv/bin/python3 <<'PYEOF'\n"
        "#!/bin/sh\n"
        "exit 0\n"
        "PYEOF\n"
        "  chmod +x .venv/bin/python3\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"sync\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
        "EOF\n"
        "chmod +x \"$HOME/.local/bin/uv\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    pip_script.chmod(0o755)
    (fake_bin / "pip").write_text("#!/bin/sh\nexec \"$(dirname \"$0\")/pip3\" \"$@\"\n", encoding="utf-8")
    (fake_bin / "pip").chmod(0o755)

    result = subprocess.run(
        ["sh", str(setup_script), "--lazy"],
        text=True,
        capture_output=True,
        cwd=project_dir,
        env={
            **os.environ,
            "HOME": str(home_dir),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        },
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "uv 安装失败，请手动安装后重试" not in combined
    assert "最小初始化完成" in combined
    assert (home_dir / ".local" / "bin" / "uv").exists()


def test_check_and_install_uv_does_not_create_runtime_when_missing():
    # 测试：当 uv 已在系统中可用但 state.json 不存在时，check_and_install_uv
    # 不会自动创建 state.json（该文件由正常的初始化流程创建，而非 uv 检测函数）
    # 注意：由于 shell 函数无法被 command -v 检测，我们需要创建一个真实的可执行文件
    result = run_common(r'''
TMPDIR_PATH="$(mktemp -d)"
export HOME="$TMPDIR_PATH/home"
mkdir -p "$HOME" "$TMPDIR_PATH/bin"

# 创建一个 mock uv 可执行文件
cat > "$TMPDIR_PATH/bin/uv" <<'EOF'
#!/bin/sh
echo "uv 1.0.0-mock"
exit 0
EOF
chmod +x "$TMPDIR_PATH/bin/uv"
export PATH="$TMPDIR_PATH/bin:/usr/bin:/bin"

if check_and_install_uv; then
    if [ -f "$HOME/.remote-claude/state.json" ]; then
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
    # state.json 不会由 check_and_install_uv 创建，需要由正常初始化流程创建
    # 因此期望 runtime:missing，与测试名称一致
    assert result.stdout.strip().endswith("runtime:missing")


def test_completion_script_can_be_sourced_from_random_cwd(tmp_path: Path):
    completion_script = REPO_ROOT / "scripts" / "completion.sh"
    result = subprocess.run(
        [
            "bash", "--noprofile", "--norc", "-c",
            f"set -e; cd '{tmp_path}'; . '{completion_script}'; type _remote_claude_get_sessions >/dev/null"
        ],
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_completion_prefers_remote_command_path_when_sourced_from_cache(tmp_path: Path):
    cache_project = tmp_path / "cache" / "remote-claude"
    cache_scripts = cache_project / "scripts"
    cache_scripts.mkdir(parents=True)

    real_project = tmp_path / "real" / "remote-claude"
    real_scripts = real_project / "scripts"
    real_bin = real_project / "bin"
    real_scripts.mkdir(parents=True)
    real_bin.mkdir(parents=True)

    (cache_scripts / "completion.sh").write_text((REPO_ROOT / "scripts" / "completion.sh").read_text(encoding="utf-8"),
                                                 encoding="utf-8")
    (real_scripts / "_common.sh").write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"),
                                             encoding="utf-8")

    remote_cmd = real_bin / "remote-claude"
    remote_cmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    remote_cmd.chmod(0o755)

    shell_cmd = (
        f"set -e; "
        f"export PATH='{real_bin}:/usr/bin:/bin:/usr/sbin:/sbin'; "
        f"cd '{tmp_path}'; "
        f". '{cache_scripts / 'completion.sh'}'; "
        "type _remote_claude_get_sessions >/dev/null"
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", shell_cmd],
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr


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
        if rel == "scripts/completion.sh":
            zsh_eval_start = text.index("eval '")
            zsh_eval_end = text.index("elif [ -n \"${BASH_VERSION:-}\" ]; then")
            text = text[:zsh_eval_start] + text[zsh_eval_end:]
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
    assert "setup.sh" in result.stdout
    assert "初始化" in result.stdout
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
    (defaults_dir / "settings.json.example").write_text(
        '{"ui_settings": {"notify": {}, "custom_commands": {"commands": [{}]}}}\n', encoding="utf-8")
    (defaults_dir / "state.json.example").write_text('{"lark_group_mappings": {}}\n', encoding="utf-8")

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
        env={
            **os.environ, "HOME": str(project_dir), "SHELL": "/bin/zsh",
            "PATH"              : f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"
        },
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


def test_install_completion_hint_uses_shared_reload_helper():
    content = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "source $shell_rc" not in content
    assert 'print_shell_reload_hint "$shell_rc"' in content


def test_check_env_escapes_sed_replacement_values():
    content = (REPO_ROOT / "scripts" / "check-env.sh").read_text(encoding="utf-8")
    assert "escape_sed_replacement()" in content
    assert 'ESCAPED_APP_ID=$(escape_sed_replacement "$INPUT_APP_ID")' in content
    assert 'ESCAPED_APP_SECRET=$(escape_sed_replacement "$INPUT_APP_SECRET")' in content
    assert 'sed "s/^FEISHU_APP_ID=.*/FEISHU_APP_ID=$ESCAPED_APP_ID/"' in content
    assert 'sed "s/^FEISHU_APP_SECRET=.*/FEISHU_APP_SECRET=$ESCAPED_APP_SECRET/"' in content


def test_npm_publish_uses_temp_npmrc_for_token():
    content = (REPO_ROOT / "scripts" / "npm-publish.sh").read_text(encoding="utf-8")
    assert "NPM_CONFIG_USERCONFIG" in content
    assert "mktemp" in content
    assert "npm config set //registry.npmjs.org/:_authToken" in content
    assert "~/.npmrc" not in content


def test_npm_publish_allows_only_package_json_changes_after_version_bump():
    content = (REPO_ROOT / "scripts" / "npm-publish.sh").read_text(encoding="utf-8")
    assert 'git diff --name-only --cached' in content
    assert 'git diff --name-only' in content
    assert 'grep -v "^package.json$"' in content


def test_uninstall_skips_project_venv_cleanup_for_repo_checkout(tmp_path: Path):
    content = (REPO_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
    assert 'case "$PROJECT_DIR" in' in content
    assert '*/node_modules/remote-claude|*/.pnpm/*/node_modules/remote-claude)' in content
    assert 'print_detail "跳过源码目录虚拟环境: $PROJECT_DIR/.venv"' in content
    assert 'rm -rf "$PROJECT_DIR/.venv"' in content


def test_uninstall_skips_prompt_and_silently_cleans_config_dir_in_pnpm_context(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "state.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME"               : str(tmp_path),
            "npm_package_json"   : str(REPO_ROOT / "package.json"),
            "npm_lifecycle_event": "preuninstall",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert not data_dir.exists()
    assert "[y/N]" not in result.stdout
    assert "是否删除" not in result.stdout


def test_uninstall_uses_centralized_current_file_names_only():
    content = (REPO_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_LARK_PID_FILE" in content
    assert "REMOTE_CLAUDE_SOCKET_DIR" in content
    assert "REMOTE_CLAUDE_STATE_FILE" in content
    assert "REMOTE_CLAUDE_SETTINGS_FILE" in content
    assert '"/tmp/remote-claude/lark.pid"' not in content
    assert 'RUNTIME_DIR="/tmp/remote-claude"' not in content
    assert 'DATA_DIR="$HOME/.remote-claude"' not in content
    assert "config.json" not in content
    assert "runtime.json" not in content


def test_uninstall_keeps_manual_prompt_when_only_generic_npm_env_present(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "settings.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            "HOME"               : str(tmp_path),
            "PATH"               : "/usr/bin:/bin:/usr/sbin:/sbin",
            "npm_config_loglevel": "notice",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert data_dir.exists()
    assert "[y/N]" in result.stdout
    assert "是否删除配置文件和数据" in result.stdout
    assert "已删除配置目录" not in result.stdout


def test_uninstall_keeps_manual_prompt_outside_npm_context(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "settings.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert data_dir.exists()
    assert "[y/N]" in result.stdout
    assert "是否删除配置文件和数据" in result.stdout
    assert "已删除配置目录" not in result.stdout


def test_uninstall_preserves_all_config_files_when_user_declines_cleanup(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "settings.json").write_text('{"settings":"keep"}\n', encoding="utf-8")
    (data_dir / "state.json").write_text('{"state":"keep"}\n', encoding="utf-8")
    (data_dir / ".env").write_text('TOKEN=keep\n', encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert (data_dir / "settings.json").read_text(encoding="utf-8") == '{"settings":"keep"}\n'
    assert (data_dir / "state.json").read_text(encoding="utf-8") == '{"state":"keep"}\n'
    assert (data_dir / ".env").read_text(encoding="utf-8") == 'TOKEN=keep\n'


def test_uninstall_scans_pnpm_library_bin_dir_for_shortcuts():
    content = (REPO_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")

    assert '"$HOME/Library/pnpm"' in content


def test_uninstall_supports_explicit_noninteractive_mode(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "state.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME"                        : str(tmp_path),
            "PATH"                        : "/usr/bin:/bin:/usr/sbin:/sbin",
            "REMOTE_CLAUDE_NONINTERACTIVE": "1",
        },
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not data_dir.exists()
    assert "[y/N]" not in result.stdout
    assert "是否删除" not in result.stdout


def test_docker_test_script_passes_noninteractive_flag_to_uninstall_hook():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_NONINTERACTIVE=1" in content


def test_uninstall_skips_prompt_and_silently_cleans_config_dir_in_pnpm_global_rm_context(tmp_path: Path):
    data_dir = tmp_path / ".remote-claude"
    data_dir.mkdir()
    (data_dir / "state.json").write_text("{}", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "uninstall.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME"                 : str(tmp_path),
            "PATH"                 : "/usr/bin:/bin:/usr/sbin:/sbin",
            "npm_config_user_agent": "pnpm/10.28.2 npm/? node/v20.0.0 darwin arm64",
            "npm_command"          : "remove",
            "npm_config_global"    : "true",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert not data_dir.exists()
    assert "[y/N]" not in result.stdout
    assert "是否删除" not in result.stdout


def test_common_reads_uv_path_from_state_json(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text('{"uv_path":"/tmp/custom-bin/uv"}\n', encoding="utf-8")

    result = run_common(f"""
    export LAZY_INIT_DISABLE_AUTO_RUN=1
    export REMOTE_CLAUDE_STATE_FILE='{state_file}'
    uv_path=$(_read_uv_path_from_runtime)
    printf 'uv:%s\\n' "$uv_path"
    """)

    assert result.returncode == 0, result.stderr
    assert "uv:/tmp/custom-bin/uv" in result.stdout


def _create_lazy_setup_project(tmp_path: Path, *, settings_default: str, state_default: str):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    defaults_dir = project_dir / "resources" / "defaults"

    scripts_dir.mkdir(parents=True)
    defaults_dir.mkdir(parents=True)

    setup_sh = scripts_dir / "setup.sh"
    setup_sh.write_text((REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8"), encoding="utf-8")
    setup_sh.chmod(0o755)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    (project_dir / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.0.0'\nrequires-python='>=3.11'\n",
        encoding="utf-8",
    )
    (defaults_dir / "settings.json.example").write_text(settings_default, encoding="utf-8")
    (defaults_dir / "state.json.example").write_text(state_default, encoding="utf-8")

    uv_stub = tmp_path / "uv"
    uv_stub.write_text(
        "#!/bin/sh\n"
        "cmd=\"$1\"\n"
        "shift || true\n"
        "case \"$cmd\" in\n"
        "  --version) echo 'uv 0.test'; exit 0 ;;\n"
        "  sync) exit 0 ;;\n"
        "  run) exit 0 ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)
    return project_dir, setup_sh, uv_stub


def test_setup_lazy_initializes_config_and_runtime_when_missing(tmp_path: Path):
    project_dir, setup_sh, _ = _create_lazy_setup_project(
        tmp_path,
        settings_default='{"version":"1.0","ui_settings":{}}\n',
        state_default='{"version":"1.0","lark_group_mappings":{}}\n',
    )

    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True)

    result = subprocess.run(
        ["sh", str(setup_sh), "--lazy"],
        capture_output=True,
        text=True,
        cwd=project_dir,
        env={**os.environ, "HOME": str(home_dir), "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 0, result.stderr
    assert (home_dir / ".remote-claude" / "settings.json").exists()
    assert (home_dir / ".remote-claude" / "state.json").exists()


def test_setup_lazy_writes_full_init_block_with_completion(tmp_path: Path):
    project_dir, setup_sh, _ = _create_lazy_setup_project(
        tmp_path,
        settings_default='{"version":"1.0","ui_settings":{}}\n',
        state_default='{"version":"1.0","lark_group_mappings":{}}\n',
    )

    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True)

    result = subprocess.run(
        ["sh", str(setup_sh), "--lazy"],
        capture_output=True,
        text=True,
        cwd=project_dir,
        env={
            **os.environ, "HOME": str(home_dir), "SHELL": "/bin/zsh",
            "PATH"              : f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"
        },
    )

    assert result.returncode == 0, result.stderr
    rc_file = home_dir / ".profile"
    content = rc_file.read_text(encoding="utf-8")
    begin = '# >>> remote-claude init >>>'
    end = '# <<< remote-claude init <<<'
    assert begin in content and end in content
    init_block = content.split(begin, 1)[1].split(end, 1)[0]
    assert 'export PATH="$HOME/.local/bin:$PATH"' in init_block
    assert f'. "{project_dir / "scripts" / "completion.sh"}"' in init_block


def test_setup_lazy_does_not_overwrite_existing_config_files(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    defaults_dir = project_dir / "resources" / "defaults"

    scripts_dir.mkdir(parents=True)
    defaults_dir.mkdir(parents=True)

    setup_sh = scripts_dir / "setup.sh"
    setup_sh.write_text((REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8"), encoding="utf-8")
    setup_sh.chmod(0o755)

    common_sh = scripts_dir / "_common.sh"
    common_sh.write_text((REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8"), encoding="utf-8")

    (project_dir / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.0.0'\nrequires-python='>=3.11'\n",
        encoding="utf-8",
    )
    (defaults_dir / "settings.json.example").write_text('{"version":"from-default"}\n', encoding="utf-8")
    (defaults_dir / "state.json.example").write_text('{"version":"from-default"}\n', encoding="utf-8")

    uv_stub = tmp_path / "uv"
    uv_stub.write_text(
        "#!/bin/sh\n"
        "cmd=\"$1\"\n"
        "shift || true\n"
        "case \"$cmd\" in\n"
        "  --version) echo 'uv 0.test'; exit 0 ;;\n"
        "  sync) exit 0 ;;\n"
        "  run) exit 0 ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)

    home_dir = tmp_path / "home"
    data_dir = home_dir / ".remote-claude"
    data_dir.mkdir(parents=True)
    (data_dir / "settings.json").write_text('{"version":"existing-config"}\n', encoding="utf-8")
    (data_dir / "state.json").write_text('{"version":"existing-runtime"}\n', encoding="utf-8")

    result = subprocess.run(
        ["sh", str(setup_sh), "--lazy"],
        capture_output=True,
        text=True,
        cwd=project_dir,
        env={**os.environ, "HOME": str(home_dir), "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 0, result.stderr
    assert (data_dir / "settings.json").read_text(encoding="utf-8").strip() == '{"version":"existing-config"}'

    runtime_data = json.loads((data_dir / "state.json").read_text(encoding="utf-8"))
    assert runtime_data.get("version") == "existing-runtime"


def test_setup_uses_centralized_path_variables_only():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "REMOTE_CLAUDE_ENV_FILE" in content
    assert "REMOTE_CLAUDE_ENV_TEMPLATE" in content
    assert "REMOTE_CLAUDE_SETTINGS_FILE" in content
    assert "REMOTE_CLAUDE_STATE_FILE" in content
    assert "REMOTE_CLAUDE_SETTINGS_TEMPLATE" in content
    assert "REMOTE_CLAUDE_STATE_TEMPLATE" in content
    assert "rc_ensure_home_dir" in content
    assert "rc_ensure_socket_dir" in content
    assert "rc_require_file" in content
    assert "rc_copy_if_missing" in content
    forbidden = [
        "config.default.json",
        "runtime.default.json",
        "lark_group_mapping.json",
        "CLAUDE_COMMAND",
        "ready_notify_enabled",
        "urgent_notify_enabled",
        "bypass_enabled",
        '$HOME/.remote-claude/.env',
        '"/tmp/remote-claude"',
    ]
    for marker in forbidden:
        assert marker not in content


def test_setup_no_longer_contains_legacy_config_migration_logic():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "migrate_legacy_notify_files()" not in content
    assert "migrate_claude_command()" not in content
    assert "migrate_legacy_notify_files" not in content
    assert "migrate_claude_command" not in content


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

    assert result.returncode == 1
    assert _expected_recovery_command(project_dir) in result.stderr
