#!/usr/bin/env python3
"""
启动器配置测试

测试覆盖：
1. Launcher 数据类
2. Settings 数据类
3. get_launcher 函数
4. 启动器配置的读取和保存
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import remote_claude

from utils.runtime_config import (
    Launcher,
    Settings,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestLauncherDataClass:
    """测试 Launcher 数据类"""

    def test_create_launcher(self):
        """测试创建 Launcher"""
        cmd = Launcher(
            name="claude",
            cli_type="claude",
            command="claude",
            desc="Claude Code CLI"
        )
        assert cmd.name == "claude"
        assert cmd.cli_type == "claude"
        assert cmd.command == "claude"
        assert cmd.desc == "Claude Code CLI"

    def test_launcher_to_dict(self):
        """测试 Launcher 序列化"""
        cmd = Launcher(
            name="codex",
            cli_type="codex",
            command="/usr/local/bin/codex",
            desc="OpenAI Codex CLI"
        )
        d = cmd.to_dict()
        assert d["name"] == "codex"
        assert d["cli_type"] == "codex"
        assert d["command"] == "/usr/local/bin/codex"
        assert d["desc"] == "OpenAI Codex CLI"

    def test_launcher_from_dict(self):
        """测试 Launcher 反序列化"""
        data = {
            "name": "claude",
            "cli_type": "claude",
            "command": "claude",
            "desc": "Claude Code CLI"
        }
        cmd = Launcher.from_dict(data)
        assert cmd.name == "claude"
        assert cmd.cli_type == "claude"
        assert cmd.command == "claude"
        assert cmd.desc == "Claude Code CLI"

    def test_launcher_empty_name(self):
        """测试空名称抛出异常"""
        with pytest.raises(ValueError, match="启动器名称不能为空"):
            Launcher(name="", cli_type="claude", command="test")

    def test_launcher_empty_command(self):
        """测试空命令抛出异常"""
        with pytest.raises(ValueError, match="启动器命令不能为空"):
            Launcher(name="test", cli_type="claude", command="")

    def test_launcher_requires_cli_type(self):
        """测试 Launcher 必须验证 cli_type 字段"""
        from server.biz_enum import CliType

        # 正常情况
        cmd = Launcher(name="Claude", cli_type="claude", command="claude")
        assert cmd.cli_type == "claude"

        # 缺少 cli_type
        with pytest.raises(ValueError, match="CLI 类型不能为空"):
            Launcher(name="Test", cli_type="", command="test")

        # 无效 cli_type
        with pytest.raises(ValueError, match="CLI 类型必须是"):
            Launcher(name="Test", cli_type="invalid", command="test")


class TestSettingsDataClass:
    """测试 Settings 数据类"""

    def test_create_settings(self):
        """测试创建 Settings"""
        settings = Settings(
            launchers=[
                Launcher("claude", "claude", "claude"),
                Launcher("codex", "codex", "codex"),
            ]
        )
        assert len(settings.launchers) == 2

    def test_get_launcher(self):
        """测试 get_launcher 方法"""
        settings = Settings(
            launchers=[
                Launcher("claude", "claude", "/usr/local/bin/claude"),
                Launcher("codex", "codex", "codex"),
            ]
        )
        assert settings.get_launcher("claude").command == "/usr/local/bin/claude"
        assert settings.get_launcher("codex").command == "codex"
        assert settings.get_launcher("unknown") is None

    def test_get_default_launcher(self):
        """测试 get_default_launcher 方法"""
        settings = Settings(
            launchers=[
                Launcher("claude", "claude", "/usr/local/bin/claude"),
            ]
        )
        assert settings.get_default_launcher().command == "/usr/local/bin/claude"
        # 空配置返回 None
        empty_settings = Settings()
        assert empty_settings.get_default_launcher() is None

    def test_settings_roundtrip(self):
        """测试 Settings 完整序列化/反序列化"""
        settings = Settings()
        settings.launchers = [
            Launcher("claude", "claude", "/opt/claude", "Custom Claude"),
            Launcher("codex", "codex", "/opt/codex", "Custom Codex"),
        ]
        # 序列化
        data = settings.to_dict()
        # 反序列化
        loaded = Settings.from_dict(data)
        assert len(loaded.launchers) == 2
        assert loaded.launchers[0].name == "claude"
        assert loaded.launchers[0].cli_type == "claude"
        assert loaded.launchers[0].command == "/opt/claude"


class TestGetMatchingCommands:
    """测试 _get_matching_commands 辅助函数"""

    def test_no_settings(self):
        """未配置启动器时返回默认命令"""
        from lark_client.card_builder import _get_matching_commands

        settings = None
        result = _get_matching_commands(settings)
        assert result == [
            {"name": "Claude", "command": "claude"},
            {"name": "Codex", "command": "codex"},
        ]

    def test_empty_launchers(self):
        """空启动器列表返回默认命令"""
        from lark_client.card_builder import _get_matching_commands

        settings = Settings()
        result = _get_matching_commands(settings)
        assert result == [
            {"name": "Claude", "command": "claude"},
            {"name": "Codex", "command": "codex"},
        ]

    def test_returns_all_launchers(self):
        """返回所有启动器"""
        from lark_client.card_builder import _get_matching_commands

        settings = Settings()
        settings.launchers = [
            Launcher(name="Claude", cli_type="claude", command="claude"),
            Launcher(name="Aider", cli_type="claude", command="aider --model claude-sonnet-4"),
            Launcher(name="Codex", cli_type="codex", command="codex"),
        ]
        result = _get_matching_commands(settings)
        assert len(result) == 3
        assert result[0]["name"] == "Claude"
        assert result[1]["name"] == "Aider"
        assert result[2]["name"] == "Codex"


class TestDirStartCallback:
    """测试 dir_start 回调处理"""

    def test_dir_start_callback_with_cli_command(self):
        """测试 dir_start 回调处理 cli_command 参数"""
        # 模拟回调值
        value = {
            "action": "dir_start",
            "path": "/path/to/project",
            "session_name": "myproject",
            "cli_command": "aider --model claude-sonnet-4",
        }
        # 验证回调值包含 cli_command
        assert value.get("cli_command") == "aider --model claude-sonnet-4"

    def test_dir_start_callback_without_cli_command(self):
        """测试 dir_start 回调无 cli_command 时使用默认值"""
        value = {
            "action"      : "dir_start",
            "path"        : "/path/to/project",
            "session_name": "myproject",
        }
        # 验证默认值
        cli_command = value.get("cli_command", "claude")
        assert cli_command == "claude"


def test_docker_negative_test_checks_runtime_launcher_override_in_settings_file():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert 'cp "$config_file" "$backup_file"' in content
    assert "jq '.launchers = [{\"name\": \"Invalid\", \"cli_type\": \"claude\", \"command\": \"/nonexistent/path/to/claude-invalid\"" in content
    assert 'cp "$backup_file" "$config_file"' in content
    assert 'sed -n' not in content


def test_docker_negative_test_logs_overridden_settings_for_diagnosis():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert 'log_info "=== 当前 settings.json ==="' in content
    assert 'cat "$config_file"' in content
    assert 'log_info "=== start_fail.log ==="' in content


def test_docker_negative_test_reads_hard_failure_from_current_startup_log_window():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert 'from remote_claude import _detect_hard_startup_failure, _read_recent_start_log_lines' in content
    assert 'print(_detect_hard_startup_failure(_read_recent_start_log_lines(log_path)))' in content


def test_docker_negative_test_uses_launcher_for_codex_startup():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert "uv run remote-claude start '$session' --launcher Codex" in content
    assert "start_cmd=\"uv run remote-claude start '$session' --cli codex\"" not in content


def test_docker_basic_command_check_no_longer_depends_on_help_copy():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert 'uv run remote-claude --help > "$RESULTS_DIR/cmd_help.log" 2>&1' in content
    assert 'log_success "remote-claude --help 执行成功"' in content


def test_docker_test_script_no_longer_contains_parallel_dependencies_and_keeps_serial_loops():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert "TEST_PARALLEL" not in content
    assert 'parallel --' not in content
    assert ' --jobs ' not in content
    assert 'for test in "${core_tests[@]}"; do' in content
    assert 'for test in "${non_core_tests[@]}"; do' in content


def test_docker_compose_test_does_not_enable_parallel_mode():
    content = (REPO_ROOT / "docker" / "docker-compose.test.yml").read_text(encoding="utf-8")
    assert 'TEST_PARALLEL=true' not in content
    assert 'CI=true' in content


def test_dockerfile_test_no_longer_installs_parallel_or_parallel_home_setup():
    content = (REPO_ROOT / "docker" / "Dockerfile.test").read_text(encoding="utf-8")
    assert ' parallel \\' not in content
    assert ' parallel && \\' not in content
    assert '~/.parallel' not in content
    assert ' jq \\' in content or ' jq && \\' in content


def test_docker_negative_test_uses_settings_launchers_schema():
    content = (Path(__file__).resolve().parents[1] / "docker" / "scripts" / "docker-test.sh").read_text(
        encoding="utf-8")
    assert "$HOME/.remote-claude/settings.json" in content
    assert ".launchers = [{\"name\": \"Invalid\", \"cli_type\": \"claude\", \"command\": \"/nonexistent/path/to/claude-invalid\"" in content
    assert "config.json" not in content
    assert "session.custom_commands" not in content


def test_remote_list_does_not_require_session_name():
    from remote_claude import validate_remote_args

    args = type("Args", (), {
        "host" : "example.com",
        "port" : 8765,
        "token": "secret-token",
        "name" : "",
    })()

    result = validate_remote_args(args, session_fallback="list")
    assert result == ("example.com", 8765, "list", "secret-token")


def test_docker_verify_session_startup_uses_socket_and_list_checks_not_timeout_rc():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert 'set +e' in content
    assert 'timeout "$timeout_sec" bash -c "$start_cmd" > "$log_file" 2>&1' in content
    assert 'if [[ $rc -ne 0 && $rc -ne 124 ]]; then' in content
    assert 'if [[ ! -S "$socket_path" ]]; then' in content
    assert 'if echo "$list_out" | grep -q "$session"; then' in content
    assert 'if [[ $rc -ne 124 ]]; then' not in content


def test_docker_negative_test_does_not_only_depend_on_timeout_rc():
    content = (REPO_ROOT / "docker" / "scripts" / "docker-test.sh").read_text(encoding="utf-8")
    assert 'timeout 20 uv run remote-claude start "$negative_session" > "$fail_log" 2>&1' in content
    assert 'print_session_diagnostics "$negative_session" "$fail_log"' in content
    assert '_detect_hard_startup_failure' in (REPO_ROOT / "remote_claude.py").read_text(encoding="utf-8")
    assert 'if [[ -n "$hard_failure_line" && ! -S "$negative_socket" ]]; then' in content
    assert 'elif [ $fail_rc -eq 124 ]; then' in content


def test_package_json_includes_public_docs_but_not_superpowers_docs():
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    files = package["files"]

    assert "docs/*.md" in files
    assert "docs/*.json" in files
    assert "docs/superpowers/" not in files
    assert "docs/superpowers/**" not in files


def test_cli_reference_prefers_launcher_over_cli_type_for_public_start_examples():
    content = (REPO_ROOT / "docs" / "cli-reference.md").read_text(encoding="utf-8")
    assert "--launcher <name>" in content
    assert "remote-claude start my-session --launcher Codex" in content
    assert "--cli-type <type>" not in content
    assert "remote-claude start my-session --cli-type codex" not in content


def test_public_docs_and_help_do_not_expose_cli_type_flag():
    candidates = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "cli-reference.md",
        REPO_ROOT / "docs" / "docker-test.md",
        REPO_ROOT / "docs" / "feishu-client.md",
        REPO_ROOT / "docs" / "feishu-setup.md",
        REPO_ROOT / "scripts" / "_help.sh",
    ]

    offending = []
    for path in candidates:
        content = path.read_text(encoding="utf-8")
        if "--cli_type" in content or "--cli-type" in content:
            offending.append(path.relative_to(REPO_ROOT).as_posix())

    assert offending == []


def test_readme_and_cli_reference_use_launcher_wording_only():
    files = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "cli-reference.md",
    ]

    for path in files:
        content = path.read_text(encoding="utf-8")
        if path.name == "cli-reference.md":
            assert "--launcher" in content
        assert "--cli-type" not in content
        assert "--cli_type" not in content


def test_readme_documents_uninstall_command():
    content = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "remote-claude uninstall" in content
    assert "remote-claude uninstall --yes" in content


def test_cli_reference_documents_uninstall_command_and_yes_flags():
    content = (REPO_ROOT / "docs" / "cli-reference.md").read_text(encoding="utf-8")
    assert "### uninstall - 卸载清理" in content
    assert "remote-claude uninstall [选项]" in content
    assert "--yes" in content
    assert "-y" in content


def test_supporting_docs_do_not_expose_cli_type_flag():
    files = [
        REPO_ROOT / "docs" / "docker-test.md",
        REPO_ROOT / "docs" / "feishu-client.md",
        REPO_ROOT / "docs" / "feishu-setup.md",
    ]

    for path in files:
        content = path.read_text(encoding="utf-8")
        assert "--cli-type" not in content
        assert "--cli_type" not in content


def test_local_client_uses_public_remote_claude_hints():
    content = (REPO_ROOT / "client" / "local_client.py").read_text(encoding="utf-8")
    assert "remote-claude list" in content
    assert "remote-claude kill" in content
    assert "remote-claude start" in content
    assert "python3 remote_claude.py list" not in content
    assert "python3 remote_claude.py kill" not in content
    assert "python3 remote_claude.py start" not in content


def test_cmd_uninstall_calls_uninstall_script_and_prints_followup(monkeypatch, capsys):
    called = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(remote_claude.subprocess, "run", fake_run)
    args = SimpleNamespace(yes=False)

    result = remote_claude.cmd_uninstall(args)

    assert result == 0
    assert called["cmd"][:2] == ["sh", str(remote_claude.SCRIPT_DIR / "scripts" / "uninstall.sh")]
    out = capsys.readouterr().out
    assert "npm uninstall -g remote-claude" in out
    assert "pnpm remove -g remote-claude" in out


def test_uninstall_script_accepts_yes_flags():
    content = (REPO_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
    assert "-y|--yes" in content
    assert "RC_UNINSTALL_ASSUME_YES" in content
    assert "_assume_yes()" in content


def test_cmd_uninstall_passes_yes_flag_to_shell(monkeypatch):
    called = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(remote_claude.subprocess, "run", fake_run)
    args = SimpleNamespace(yes=True)

    remote_claude.cmd_uninstall(args)

    assert called["cmd"][-1] == "--yes"


def test_completion_extracts_session_names_from_list_output():
    result = subprocess.run(
        ["bash"],
        input=f"""#!/usr/bin/env bash
set -e
PATH='/usr/bin:/bin:{REPO_ROOT}:$PATH'
function remote-claude() {{
cat <<'EOF'
活跃会话:
────────────────────────────────────────────────────────
类型     PID      tmux     名称
────────────────────────────────────────────────────────
claude   123      yes      alpha_session
codex    456      no       beta_session
共 2 个会话
EOF
}}
source '{REPO_ROOT / 'scripts' / 'completion.sh'}'
_remote_claude_get_sessions
""",
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["alpha_session", "beta_session"]


def test_completion_extracts_session_names_from_ansi_list_output():
    result = subprocess.run(
        ["bash"],
        input=f"""#!/usr/bin/env bash
set -e
PATH='/usr/bin:/bin:{REPO_ROOT}:$PATH'
function remote-claude() {{
printf '活跃会话:\n'
printf '────────────────────────────────────────────────────────\n'
printf '类型     PID      tmux     名称\n'
printf '────────────────────────────────────────────────────────\n'
printf '\033[0;32mclaude\033[0m  123      yes      ansi_alpha\n'
printf '\033[0;34mcodex\033[0m   456      no       ansi_beta\n'
printf '共 2 个会话\n'
}}
source '{REPO_ROOT / 'scripts' / 'completion.sh'}'
_remote_claude_get_sessions
""",
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["ansi_alpha", "ansi_beta"]


def test_completion_degrades_safely_when_project_dir_cannot_be_resolved():
    result = subprocess.run(
        ["bash"],
        input=f"""#!/usr/bin/env bash
set -e
PATH='/nonexistent'
source '{REPO_ROOT / 'scripts' / 'completion.sh'}'
printf 'loaded\n'
_remote_claude_get_sessions
""",
        text=True,
        capture_output=True,
        cwd='/',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["loaded"]


def test_setup_script_does_not_reference_removed_client_entry():
    content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "client/client.py" not in content


def test_setup_configure_shell_links_remote_claude_to_shell_launcher():
    setup_content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    common_content = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")

    assert 'bin/remote-claude' in setup_content
    assert 'rc_link_shortcuts_into_dir "$BIN_DIR"' in setup_content
    assert '$PROJECT_DIR/bin/$shortcut_cmd' in common_content
    assert '.venv/bin/remote-claude' not in setup_content
    assert '$PROJECT_DIR/.venv/bin/$shortcut_cmd' not in common_content


def test_pyproject_console_script_is_not_the_public_npm_entry():
    pyproject_content = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setup_content = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    common_content = (REPO_ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")

    assert 'remote-claude = "remote_claude:main"' in pyproject_content
    assert '仅供开发态/uv run' in pyproject_content
    assert 'bin/remote-claude' in setup_content
    assert '$PROJECT_DIR/bin/$shortcut_cmd' in common_content
    assert '.venv/bin/remote-claude' not in setup_content
    assert '$PROJECT_DIR/.venv/bin/$shortcut_cmd' not in common_content


if __name__ == "__main__":
    pytest.main([__file__])
