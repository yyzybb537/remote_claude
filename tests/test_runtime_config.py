#!/usr/bin/env python3
"""
配置测试

测试覆盖：
1. 配置加载/保存（load_settings/save_settings, load_state/save_state）
2. 数据类序列化/反序列化
3. 边缘情况处理（文件损坏、配置缺失等）
"""

import sys
import tempfile
import shutil
import json
import os
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.runtime_config import (
    Settings,
    State,
    Launcher,
    SessionState,
    CardSettings,
    SessionSettings,
    NotifySettingsV11,
    UiSettings,
    QuickCommand,
    load_settings,
    save_settings,
    load_state,
    save_state,
    SETTINGS_CURRENT_VERSION,
    STATE_CURRENT_VERSION,
    USER_DATA_DIR,
    SETTINGS_FILE,
    STATE_FILE,
)


class TestEnv:
    """测试环境管理"""

    def __init__(self):
        self.original_dir = None
        self.temp_dir = None
        self.old_env = {}

    def setup(self):
        """设置测试环境"""
        # 创建临时目录
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_dir = USER_DATA_DIR

        # 保存原始环境
        import utils.runtime_config as config_module
        self.old_env = {
            'USER_DATA_DIR': config_module.USER_DATA_DIR,
            'SETTINGS_FILE': config_module.SETTINGS_FILE,
            'STATE_FILE': config_module.STATE_FILE,
            'SETTINGS_LOCK_FILE': config_module.SETTINGS_LOCK_FILE,
            'STATE_LOCK_FILE': config_module.STATE_LOCK_FILE,
        }

        # 临时替换路径
        config_module.USER_DATA_DIR = self.temp_dir
        config_module.SETTINGS_FILE = self.temp_dir / "settings.json"
        config_module.STATE_FILE = self.temp_dir / "state.json"
        config_module.SETTINGS_LOCK_FILE = self.temp_dir / "settings.json.lock"
        config_module.STATE_LOCK_FILE = self.temp_dir / "state.json.lock"

    def teardown(self):
        """恢复测试环境"""
        import utils.runtime_config as config_module
        for key, value in self.old_env.items():
            setattr(config_module, key, value)

        # 清理临时目录
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# ============== 数据类测试 ==============

def test_launcher():
    """测试 Launcher 数据类"""
    launcher = Launcher(name="Claude", cli_type="claude", command="claude", desc="Claude CLI")
    assert launcher.name == "Claude"
    assert launcher.cli_type == "claude"
    assert launcher.command == "claude"

    # 测试序列化
    d = launcher.to_dict()
    assert d["name"] == "Claude"

    # 测试反序列化
    launcher2 = Launcher.from_dict(d)
    assert launcher2.name == launcher.name


def test_launcher_validation():
    """测试 Launcher 验证"""
    try:
        Launcher(name="", cli_type="claude", command="claude")
        assert False, "应该抛出异常"
    except ValueError as e:
        assert "名称不能为空" in str(e)

    try:
        Launcher(name="Test", cli_type="invalid", command="test")
        assert False, "应该抛出异常"
    except ValueError as e:
        assert "CLI 类型必须是" in str(e)


def test_settings():
    """测试 Settings 数据类"""
    settings = Settings()
    assert settings.version == SETTINGS_CURRENT_VERSION
    assert settings.launchers == []
    assert settings.card.expiry_sec == 3600

    # 测试带启动器的设置
    settings_with_launchers = Settings(
        launchers=[
            Launcher(name="Claude", cli_type="claude", command="claude"),
            Launcher(name="Codex", cli_type="codex", command="codex"),
        ]
    )
    assert settings_with_launchers.get_default_launcher().name == "Claude"
    assert settings_with_launchers.get_launcher("Codex").cli_type == "codex"
    assert settings_with_launchers.get_launcher("NotExist") is None


def test_state():
    """测试 State 数据类"""
    state = State()
    assert state.version == STATE_CURRENT_VERSION
    assert state.sessions == {}

    # 测试会话路径管理
    state.set_session_path("test_session", "/path/to/session")
    assert state.get_session_path("test_session") == "/path/to/session"
    assert state.remove_session("test_session")
    assert state.get_session_path("test_session") is None


def test_session_state():
    """测试 SessionState 数据类"""
    session_state = SessionState(
        path="/test/path",
        lark_chat_id="chat_123",
        auto_answer_enabled=True,
        auto_answer_count=5
    )
    assert session_state.path == "/test/path"
    assert session_state.lark_chat_id == "chat_123"

    # 测试序列化
    d = session_state.to_dict()
    assert d["path"] == "/test/path"

    # 测试反序列化
    session_state2 = SessionState.from_dict(d)
    assert session_state2.path == session_state.path


def test_ui_settings():
    """测试 UiSettings 数据类"""
    ui = UiSettings(
        show_builtin_keys=True,
        show_launchers=["Claude", "Codex"],
        enabled_keys=["up", "down", "ctrl_o"]
    )
    assert ui.show_builtin_keys
    assert len(ui.show_launchers) == 2
    assert "up" in ui.enabled_keys


# ============== 加载/保存测试 ==============

def test_load_save_settings():
    """测试 Settings 加载/保存"""
    env = TestEnv()
    try:
        env.setup()

        # 测试默认加载
        settings = load_settings()
        assert isinstance(settings, Settings)
        assert settings.version == SETTINGS_CURRENT_VERSION

        # 测试保存
        settings.launchers = [Launcher(name="Test", cli_type="claude", command="test")]
        save_settings(settings)

        # 重新加载
        loaded = load_settings()
        assert len(loaded.launchers) == 1
        assert loaded.launchers[0].name == "Test"

    finally:
        env.teardown()


def test_load_save_state():
    """测试 State 加载/保存"""
    env = TestEnv()
    try:
        env.setup()

        # 测试默认加载
        state = load_state()
        assert isinstance(state, State)
        assert state.version == STATE_CURRENT_VERSION

        # 测试保存
        state.set_session_path("session1", "/path/1")
        state.set_lark_chat_id("session1", "chat_123")
        save_state(state)

        # 重新加载
        loaded = load_state()
        assert loaded.get_session_path("session1") == "/path/1"
        assert loaded.get_lark_chat_id("session1") == "chat_123"

    finally:
        env.teardown()


def test_corrupted_settings():
    """测试损坏的 settings.json"""
    env = TestEnv()
    try:
        env.setup()

        # 写入损坏的 JSON
        SETTINGS_FILE.write_text("{ invalid json }")

        # 应该返回默认配置而不崩溃
        settings = load_settings()
        assert isinstance(settings, Settings)
        assert settings.version == SETTINGS_CURRENT_VERSION

    finally:
        env.teardown()


def test_corrupted_state():
    """测试损坏的 state.json"""
    env = TestEnv()
    try:
        env.setup()

        # 写入损坏的 JSON
        STATE_FILE.write_text("{ invalid json }")

        # 应该返回默认配置而不崩溃
        state = load_state()
        assert isinstance(state, State)
        assert state.version == STATE_CURRENT_VERSION

    finally:
        env.teardown()


# ============== 运行测试 ==============

if __name__ == "__main__":
    # 数据类测试
    test_launcher()
    test_launcher_validation()
    test_settings()
    test_state()
    test_session_state()
    test_ui_settings()
    print("✓ 数据类测试通过")

    # 加载/保存测试
    test_load_save_settings()
    test_load_save_state()
    test_corrupted_settings()
    test_corrupted_state()
    print("✓ 加载/保存测试通过")

    print("\n所有测试通过 ✓")
