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
    shell_script = f"""#!/usr/bin/env bash
set -e
SCRIPT_DIR='{REPO_ROOT}/scripts'
PROJECT_DIR='{REPO_ROOT}'
source '{COMMON_SH}'
{script_body}
"""
    return subprocess.run(
        ["bash"],
        input=shell_script,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )


def test_lazy_init_if_needed_exports_public_contract():
    result = run_common("""
if command -v lazy_init_if_needed >/dev/null 2>&1; then
    echo present
else
    echo missing
    exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("present")


def test_lazy_init_if_needed_does_not_auto_run_on_source():
    result = run_common("""
if [ "${_LAZY_INIT_RUNNING:-unset}" = "unset" ]; then
    echo not-run
else
    echo ran
    exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("not-run")


def test_lazy_init_if_needed_reports_skip_in_package_cache():
    result = run_common("""
SCRIPT_DIR="$HOME/.npm/_cacache/remote-claude/scripts"
if lazy_init_if_needed; then
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
if lazy_init_if_needed; then
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


def test_check_and_install_uv_skips_install_during_lazy_cache_init():
    result = run_common("""
SCRIPT_DIR="$HOME/.npm/_cacache/remote-claude/scripts"
install_uv_multi_source() {
    echo install-called
    return 0
}
if check_and_install_uv; then
    status=$?
    echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"
else
    status=$?
    echo "rc:$status result:${LAZY_INIT_RESULT:-missing}"
    exit 1
fi
""")

    assert result.returncode == 0, result.stderr
    assert "install-called" not in result.stdout
    assert result.stdout.strip().endswith("rc:0 result:skipped-cache")


def test_lazy_init_if_needed_reports_setup_success_after_trigger(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    (project_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")
    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
if lazy_init_if_needed; then
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
    setup_sh.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
if lazy_init_if_needed; then
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


def test_lazy_init_if_needed_reports_missing_shell_as_failure(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    (project_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
PATH=''
if lazy_init_if_needed; then
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
    exit 1
else
    status=$?
    echo "rc:$status result:${{LAZY_INIT_RESULT:-missing}}"
fi
""")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("rc:1 result:sync-shell-missing")


def test_lazy_init_failure_prints_recovery_command_and_non_zero_exit(tmp_path: Path):
    project_dir = tmp_path / "project"
    script_dir = project_dir / "scripts"
    script_dir.mkdir(parents=True)
    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = run_common(f"""
PROJECT_DIR='{project_dir}'
SCRIPT_DIR='{script_dir}'
lazy_init_if_needed || true
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

    wrapper_bash = tmp_path / "bash"
    wrapper_bash.write_text(
        f"#!/bin/sh\nSCRIPT_DIR='{project_dir}' exec /bin/sh '{script_dir / 'setup.sh'}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper_bash.chmod(0o755)

    setup_sh = script_dir / "setup.sh"
    setup_sh.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")
    setup_sh.chmod(0o755)

    result = subprocess.run(
        ["sh", str(entry_script)],
        text=True,
        capture_output=True,
        cwd=project_dir,
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"},
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



def test_install_sh_does_not_skip_pnpm_global_install_in_cache(tmp_path: Path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "Library" / "pnpm" / "global" / "5" / "node_modules" / "remote-claude" / "scripts"
    scripts_dir.mkdir(parents=True)

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
    setup_sh.write_text("#!/usr/bin/env bash\nexit 21\n", encoding="utf-8")
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





def test_uninstall_skips_prompt_and_silently_cleans_config_dir_in_npm_context(tmp_path: Path):
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
            "npm_lifecycle_event": "preuninstall",
        },
        input="n\n",
    )

    assert result.returncode == 0, result.stderr
    assert not data_dir.exists()
    assert "[y/N]" not in result.stdout
    assert "是否删除" not in result.stdout


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


