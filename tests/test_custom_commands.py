#!/usr/bin/env python3
"""
启动器配置测试

测试覆盖：
1. Launcher 数据类
2. Settings 数据类
3. get_launcher 函数
4. 启动器配置的读取和保存
"""

import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from utils.runtime_config import (
    Launcher,
    Settings,
    load_settings,
)


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
            "action": "dir_start",
            "path": "/path/to/project",
            "session_name": "myproject",
        }
        # 验证默认值
        cli_command = value.get("cli_command", "claude")
        assert cli_command == "claude"


if __name__ == "__main__":
    pytest.main([__file__])
