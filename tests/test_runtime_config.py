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
import importlib
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import utils.runtime_config as config_module

from utils.runtime_config import (
    Settings,
    State,
    Launcher,
    SessionState,
    CardSettings,
    SessionSettings,
    NotifySettings,
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
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_dir = USER_DATA_DIR

        import utils.runtime_config as config_module
        self.old_env = {
            'USER_DATA_DIR': config_module.USER_DATA_DIR,
            'SETTINGS_FILE': config_module.SETTINGS_FILE,
            'STATE_FILE': config_module.STATE_FILE,
            'SETTINGS_LOCK_FILE': config_module.SETTINGS_LOCK_FILE,
            'STATE_LOCK_FILE': config_module.STATE_LOCK_FILE,
        }

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

        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# ============== 数据类测试 ==============

def test_settings_roundtrip_and_lookup_behavior():
    settings = Settings(
        launchers=[
            Launcher(name="Claude", cli_type="claude", command="claude"),
            Launcher(name="Codex", cli_type="codex", command="codex"),
        ]
    )

    assert settings.version == SETTINGS_CURRENT_VERSION
    assert settings.get_default_launcher().name == "Claude"
    assert settings.get_launcher("Codex").cli_type == "codex"
    assert settings.get_launcher("NotExist") is None

    loaded = Settings.from_dict(settings.to_dict())
    assert loaded.launchers[0].name == "Claude"
    assert loaded.launchers[1].command == "codex"


def test_launcher_validation():
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


def test_state_roundtrip_and_session_lookup_behavior():
    state = State()
    assert state.version == STATE_CURRENT_VERSION
    assert state.sessions == {}

    state.set_session_path("test_session", "/path/to/session")
    state.set_lark_chat_id("test_session", "chat_123")
    assert state.get_session_path("test_session") == "/path/to/session"
    assert state.get_lark_chat_id("test_session") == "chat_123"

    session_state = SessionState(
        path="/test/path",
        lark_chat_id="chat_123",
        auto_answer_enabled=True,
        auto_answer_count=5
    )
    assert SessionState.from_dict(session_state.to_dict()).path == session_state.path

    assert state.remove_session("test_session")
    assert state.get_session_path("test_session") is None


def test_ui_settings():
    ui = UiSettings(
        show_builtin_keys=True,
        enabled_keys=["up", "down", "ctrl_o"]
    )
    assert ui.show_builtin_keys
    assert "up" in ui.enabled_keys


# ============== 加载/保存测试 ==============

def test_load_save_settings():
    env = TestEnv()
    try:
        env.setup()

        settings = load_settings()
        assert isinstance(settings, Settings)
        assert settings.version == SETTINGS_CURRENT_VERSION

        settings.launchers = [Launcher(name="Test", cli_type="claude", command="test")]
        save_settings(settings)

        loaded = load_settings()
        assert len(loaded.launchers) == 1
        assert loaded.launchers[0].name == "Test"

    finally:
        env.teardown()


def test_load_save_state():
    env = TestEnv()
    try:
        env.setup()

        state = load_state()
        assert isinstance(state, State)
        assert state.version == STATE_CURRENT_VERSION

        state.set_session_path("session1", "/path/1")
        state.set_lark_chat_id("session1", "chat_123")
        save_state(state)

        loaded = load_state()
        assert loaded.get_session_path("session1") == "/path/1"
        assert loaded.get_lark_chat_id("session1") == "chat_123"

    finally:
        env.teardown()


def test_set_session_auto_answer_enabled_uses_locked_update(monkeypatch):
    import utils.runtime_config as config_module

    env = TestEnv()
    try:
        env.setup()
        save_state(State())

        calls = []

        def fake_update(config_file, lock_path, load_func, config_class, mutator):
            calls.append((config_file, lock_path, load_func, config_class))
            state = load_func()
            result = mutator(state)
            save_state(state)
            return result

        monkeypatch.setattr(config_module, "_update_config_with_lock", fake_update)

        config_module.set_session_auto_answer_enabled("demo", True, enabled_by="tester")

        updated = load_state()
        assert updated.sessions["demo"].auto_answer_enabled is True
        assert calls == [
            (config_module.STATE_FILE, config_module.STATE_LOCK_FILE, config_module.load_state, config_module.State)
        ]
    finally:
        env.teardown()


def test_remove_session_mapping_uses_locked_update(monkeypatch):
    import utils.runtime_config as config_module

    env = TestEnv()
    try:
        env.setup()
        state = State()
        state.set_session_path("demo", "/tmp/demo")
        save_state(state)

        calls = []

        def fake_update(config_file, lock_path, load_func, config_class, mutator):
            calls.append((config_file, lock_path, load_func, config_class))
            current = load_func()
            result = mutator(current)
            save_state(current)
            return result

        monkeypatch.setattr(config_module, "_update_config_with_lock", fake_update)

        removed = config_module.remove_session_mapping("demo")

        updated = load_state()
        assert removed is True
        assert updated.get_session_path("demo") is None
        assert calls == [
            (config_module.STATE_FILE, config_module.STATE_LOCK_FILE, config_module.load_state, config_module.State)
        ]
    finally:
        env.teardown()


def test_save_state_writes_via_temp_file_replace(monkeypatch):
    import utils.runtime_config as config_module

    env = TestEnv()
    try:
        env.setup()
        state = State()
        state.set_session_path("demo", "/tmp/demo")

        replace_calls = []
        original_replace = config_module.os.replace

        def spy_replace(src, dst):
            replace_calls.append((Path(src), Path(dst)))
            return original_replace(src, dst)

        monkeypatch.setattr(config_module.os, "replace", spy_replace)

        save_state(state)

        loaded = load_state()
        assert loaded.get_session_path("demo") == "/tmp/demo"
        assert len(replace_calls) == 1
        src, dst = replace_calls[0]
        assert src.name.endswith(".tmp")
        assert dst == config_module.STATE_FILE
        assert not src.exists()
    finally:
        env.teardown()


def test_save_settings_writes_via_temp_file_replace(monkeypatch):
    import utils.runtime_config as config_module

    env = TestEnv()
    try:
        env.setup()
        settings = Settings(launchers=[Launcher(name="Claude", cli_type="claude", command="claude")])

        replace_calls = []
        original_replace = config_module.os.replace

        def spy_replace(src, dst):
            replace_calls.append((Path(src), Path(dst)))
            return original_replace(src, dst)

        monkeypatch.setattr(config_module.os, "replace", spy_replace)

        save_settings(settings)

        loaded = load_settings()
        assert loaded.get_default_launcher().name == "Claude"
        assert len(replace_calls) == 1
        src, dst = replace_calls[0]
        assert src.name.endswith(".tmp")
        assert dst == config_module.SETTINGS_FILE
        assert not src.exists()
    finally:
        env.teardown()


def test_corrupted_settings():
    env = TestEnv()
    try:
        env.setup()

        SETTINGS_FILE.write_text("{ invalid json }")

        settings = load_settings()
        assert isinstance(settings, Settings)
        assert settings.version == SETTINGS_CURRENT_VERSION

    finally:
        env.teardown()


def test_corrupted_state():
    env = TestEnv()
    try:
        env.setup()

        config_module.STATE_FILE.write_text("{ invalid json }")

        state = load_state()
        assert isinstance(state, State)
        assert state.version == STATE_CURRENT_VERSION
        backups = list(config_module.USER_DATA_DIR.glob("state.json.bak.*"))
        assert backups
        assert not config_module.STATE_FILE.exists()

    finally:
        env.teardown()


class EnvFileTestEnv:
    """测试环境变量配置的临时环境"""

    def __init__(self):
        self.temp_dir = None
        self.original_env = {}

    def setup(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_env = {key: os.environ.get(key) for key in (
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "ALLOWED_USERS",
            "ENABLE_USER_WHITELIST",
            "GROUP_NAME_PREFIX",
            "LARK_LOG_LEVEL",
            "MAX_CARD_BLOCKS",
            "STARTUP_TIMEOUT",
            "LARK_NO_PROXY",
            "USER_WHITELIST",
            "GROUP_PREFIX",
            "LOG_LEVEL",
            "NO_PROXY",
        )}

    def teardown(self):
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


def test_env_config_supports_legacy_field_names():
    from utils.env_config import EnvConfig

    env = EnvFileTestEnv()
    try:
        env.setup()
        env_file = env.temp_dir / ".env"
        env_file.write_text(
            "\n".join([
                "FEISHU_APP_ID=app_legacy",
                "FEISHU_APP_SECRET=secret_legacy",
                "USER_WHITELIST=user_a,user_b",
                "GROUP_PREFIX=Legacy-Group",
                "LOG_LEVEL=debug",
                "STARTUP_TIMEOUT=9",
                "MAX_CARD_BLOCKS=88",
                "NO_PROXY=1",
            ]) + "\n",
            encoding="utf-8",
        )

        config = EnvConfig.from_env_file(env_file)

        assert config.feishu_app_id == "app_legacy"
        assert config.feishu_app_secret == "secret_legacy"
        assert config.allowed_users == ["user_a", "user_b"]
        assert config.group_name_prefix == "Legacy-Group"
        assert config.lark_log_level == "debug"
        assert config.startup_timeout == 9
        assert config.max_card_blocks == 88
        assert config.lark_no_proxy is True
    finally:
        env.teardown()


def test_env_config_prefers_new_field_names_over_legacy():
    from utils.env_config import EnvConfig

    env = EnvFileTestEnv()
    try:
        env.setup()
        env_file = env.temp_dir / ".env"
        env_file.write_text(
            "\n".join([
                "ALLOWED_USERS=new_user",
                "USER_WHITELIST=legacy_user",
                "GROUP_NAME_PREFIX=New-Group",
                "GROUP_PREFIX=Legacy-Group",
                "LARK_LOG_LEVEL=ERROR",
                "LOG_LEVEL=DEBUG",
                "LARK_NO_PROXY=0",
                "NO_PROXY=1",
            ]) + "\n",
            encoding="utf-8",
        )

        config = EnvConfig.from_env_file(env_file)

        assert config.allowed_users == ["new_user"]
        assert config.group_name_prefix == "New-Group"
        assert config.lark_log_level == "ERROR"
        assert config.lark_no_proxy is False
    finally:
        env.teardown()


def test_lark_config_supports_legacy_and_new_env_name_precedence():
    env = EnvFileTestEnv()
    try:
        env.setup()
        os.environ["GROUP_PREFIX"] = "Legacy-Chat"
        os.environ["LOG_LEVEL"] = "INFO"
        os.environ["NO_PROXY"] = "1"
        os.environ.pop("GROUP_NAME_PREFIX", None)
        os.environ.pop("LARK_LOG_LEVEL", None)
        os.environ.pop("LARK_NO_PROXY", None)

        import lark_client.config as config_module
        importlib.reload(config_module)

        assert config_module.GROUP_NAME_PREFIX == "Legacy-Chat"
        assert config_module.LARK_LOG_LEVEL == 20
        assert config_module.LARK_NO_PROXY is True

        os.environ["GROUP_NAME_PREFIX"] = "New-Chat"
        os.environ["LARK_LOG_LEVEL"] = "ERROR"
        os.environ["LARK_NO_PROXY"] = "0"
        importlib.reload(config_module)

        assert config_module.GROUP_NAME_PREFIX == "New-Chat"
        assert config_module.LARK_LOG_LEVEL == 40
        assert config_module.LARK_NO_PROXY is False
    finally:
        env.teardown()


if __name__ == "__main__":
    test_settings_roundtrip_and_lookup_behavior()
    test_launcher_validation()
    test_state_roundtrip_and_session_lookup_behavior()
    test_ui_settings()
    test_load_save_settings()
    test_load_save_state()
    test_corrupted_settings()
    test_corrupted_state()
    print("\n所有测试通过 ✓")
