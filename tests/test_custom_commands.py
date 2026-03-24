#!/usr/bin/env python3
"""
自定义命令配置测试

测试覆盖：
1. CustomCommand 数据类
2. CustomCommandsConfig 数据类
3. get_cli_command 函数
4. 自定义命令配置的读取和保存
"""

import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.runtime_config import (
    CustomCommand,
    CustomCommandsConfig,
    UserConfig,
    UISettings,
    get_custom_commands,
    get_cli_command,
    load_user_config,
)


class TestCustomCommandDataClass:
    """测试 CustomCommand 数据类"""

    def test_create_custom_command(self):
        """测试创建 CustomCommand"""
        cmd = CustomCommand(
            name="claude",
            cli_type="claude",
            command="claude",
            description="Claude Code CLI"
        )
        assert cmd.name == "claude"
        assert cmd.cli_type == "claude"
        assert cmd.command == "claude"
        assert cmd.description == "Claude Code CLI"

    def test_custom_command_to_dict(self):
        """测试 CustomCommand 序列化"""
        cmd = CustomCommand(
            name="codex",
            cli_type="codex",
            command="/usr/local/bin/codex",
            description="OpenAI Codex CLI"
        )
        d = cmd.to_dict()
        assert d["name"] == "codex"
        assert d["cli_type"] == "codex"
        assert d["command"] == "/usr/local/bin/codex"
        assert d["description"] == "OpenAI Codex CLI"

    def test_custom_command_from_dict(self):
        """测试 CustomCommand 反序列化"""
        data = {
            "name": "claude",
            "cli_type": "claude",
            "command": "claude",
            "description": "Claude Code CLI"
        }
        cmd = CustomCommand.from_dict(data)
        assert cmd.name == "claude"
        assert cmd.cli_type == "claude"
        assert cmd.command == "claude"
        assert cmd.description == "Claude Code CLI"

    def test_custom_command_empty_name(self):
        """测试空名称抛出异常"""
        with pytest.raises(ValueError, match="命令名称不能为空"):
            CustomCommand(name="", cli_type="claude", command="test")

    def test_custom_command_empty_command(self):
        """测试空命令抛出异常"""
        with pytest.raises(ValueError, match="命令值不能为空"):
            CustomCommand(name="test", cli_type="claude", command="")

    def test_custom_command_long_name(self):
        """测试超长名称抛出异常"""
        with pytest.raises(ValueError, match="命令名称最大长度 20"):
            CustomCommand(name="a" * 21, cli_type="claude", command="test")

    def test_custom_command_requires_cli_type(self):
        """测试 CustomCommand 必须验证 cli_type 字段"""
        from server.biz_enum import CliType

        # 正常情况
        cmd = CustomCommand(name="Claude", cli_type="claude", command="claude")
        assert cmd.cli_type == "claude"

        # 缺少 cli_type
        with pytest.raises(ValueError, match="CLI 类型不能为空"):
            CustomCommand(name="Test", cli_type="", command="test")

        # 无效 cli_type
        with pytest.raises(ValueError, match="CLI 类型必须是"):
            CustomCommand(name="Test", cli_type="invalid", command="test")


class TestCustomCommandsConfigDataClass:
    """测试 CustomCommandsConfig 数据类"""

    def test_create_config(self):
        """测试创建 CustomCommandsConfig"""
        config = CustomCommandsConfig(
            enabled=True,
            commands=[
                CustomCommand("claude", "claude", "claude"),
                CustomCommand("codex", "codex", "codex"),
            ]
        )
        assert config.enabled is True
        assert len(config.commands) == 2

    def test_get_command(self):
        """测试 get_command 方法"""
        config = CustomCommandsConfig(
            enabled=True,
            commands=[
                CustomCommand("claude", "claude", "/usr/local/bin/claude"),
                CustomCommand("codex", "codex", "codex"),
            ]
        )
        assert config.get_command("claude") == "/usr/local/bin/claude"
        assert config.get_command("codex") == "codex"
        assert config.get_command("unknown") is None

    def test_get_default_command(self):
        """测试 get_default_command 方法"""
        config = CustomCommandsConfig(
            enabled=True,
            commands=[
                CustomCommand("claude", "claude", "/usr/local/bin/claude"),
            ]
        )
        assert config.get_default_command() == "/usr/local/bin/claude"
        # 空配置返回默认值
        empty_config = CustomCommandsConfig()
        assert empty_config.get_default_command() == "claude"

    def test_is_visible(self):
        """测试 is_visible 方法"""
        enabled_config = CustomCommandsConfig(
            enabled=True,
            commands=[CustomCommand("claude", "claude", "claude")]
        )
        assert enabled_config.is_visible() is True
        disabled_config = CustomCommandsConfig(
            enabled=False,
            commands=[CustomCommand("claude", "claude", "claude")]
        )
        assert disabled_config.is_visible() is False
        empty_config = CustomCommandsConfig(enabled=True)
        assert empty_config.is_visible() is False


class TestCustomCommandsIntegration:
    """测试自定义命令与 UI 配置集成"""

    def test_uisettings_contains_custom_commands(self):
        """测试 UISettings 包含 custom_commands"""
        ui = UISettings()
        assert hasattr(ui, "custom_commands")
        assert isinstance(ui.custom_commands, CustomCommandsConfig)
        assert ui.custom_commands.enabled is False

    def test_user_config_roundtrip(self):
        """测试 UserConfig 完整序列化/反序列化"""
        # 使用临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config = Path(temp_dir) / "test_config.json"

            config = UserConfig()
            config.ui_settings.custom_commands.enabled = True
            config.ui_settings.custom_commands.commands = [
                CustomCommand("claude", "claude", "/opt/claude", "Custom Claude"),
                CustomCommand("codex", "codex", "/opt/codex", "Custom Codex"),
            ]
            # 保存
            temp_config.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2))
            # 加载
            with patch("utils.runtime_config.USER_CONFIG_FILE", temp_config):
                loaded = load_user_config()
                assert loaded.ui_settings.custom_commands.enabled is True
                assert len(loaded.ui_settings.custom_commands.commands) == 2
                assert loaded.ui_settings.custom_commands.commands[0].name == "claude"
                assert loaded.ui_settings.custom_commands.commands[0].cli_type == "claude"
                assert loaded.ui_settings.custom_commands.commands[0].command == "/opt/claude"


class TestGetCliCommand:
    """测试 get_cli_command 函数"""

    def test_get_cli_command_from_config(self):
        """测试从配置获取命令"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config = Path(temp_dir) / "test_config.json"

            # 创建配置文件
            config_data = {
                "version": "1.0",
                "ui_settings": {
                    "custom_commands": {
                        "enabled": True,
                        "commands": [
                            {"name": "claude", "cli_type": "claude", "command": "/opt/claude", "description": "Custom Claude"},
                            {"name": "codex", "cli_type": "codex", "command": "/opt/codex", "description": "Custom Codex"},
                        ]
                    }
                }
            }
            temp_config.write_text(json.dumps(config_data, ensure_ascii=False))
            # Mock 配置文件路径
            with patch("utils.runtime_config.USER_CONFIG_FILE", temp_config):
                cmd = get_cli_command("claude")
                assert cmd == "/opt/claude"
                cmd = get_cli_command("codex")
                assert cmd == "/opt/codex"

    def test_get_cli_command_unknown_type(self):
        """测试未知 CLI 类型回退到原名称"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config = Path(temp_dir) / "test_config.json"

            config_data = {
                "version": "1.0",
                "ui_settings": {
                    "custom_commands": {
                        "enabled": True,
                        "commands": []
                    }
                }
            }
            temp_config.write_text(json.dumps(config_data, ensure_ascii=False))
            with patch("utils.runtime_config.USER_CONFIG_FILE", temp_config):
                cmd = get_cli_command("unknown")
                assert cmd == "unknown"


if __name__ == "__main__":
    pytest.main([__file__])
