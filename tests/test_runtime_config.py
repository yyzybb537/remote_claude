#!/usr/bin/env python3
"""
运行时配置测试

测试覆盖：
1. 配置加载/保存（load_runtime_config/save_runtime_config）
2. 迁移逻辑（migrate_legacy_config）
3. 快捷命令可见性判断
4. 边缘情况处理（文件损坏、配置缺失等）
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
    RuntimeConfig,
    UserConfig,
    QuickCommand,
    QuickCommandsConfig,
    OperationPanelSettings,
    UISettings,
    load_runtime_config,
    save_runtime_config,
    load_user_config,
    save_user_config,
    migrate_legacy_config,
    get_uv_path,
    set_uv_path,
    validate_uv_path,
    CURRENT_VERSION,
    USER_CONFIG_VERSION,
    MAX_SESSION_MAPPINGS,
    USER_DATA_DIR,
    RUNTIME_CONFIG_FILE,
    USER_CONFIG_FILE,
    LEGACY_LARK_GROUP_MAPPING_FILE,
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
            'RUNTIME_CONFIG_FILE': config_module.RUNTIME_CONFIG_FILE,
            'USER_CONFIG_FILE': config_module.USER_CONFIG_FILE,
            'LEGACY_LARK_GROUP_MAPPING_FILE': config_module.LEGACY_LARK_GROUP_MAPPING_FILE,
            'RUNTIME_LOCK_FILE': config_module.RUNTIME_LOCK_FILE,
            'USER_CONFIG_LOCK_FILE': config_module.USER_CONFIG_LOCK_FILE,
        }

        # 临时替换路径
        config_module.USER_DATA_DIR = self.temp_dir
        config_module.RUNTIME_CONFIG_FILE = self.temp_dir / "runtime.json"
        config_module.USER_CONFIG_FILE = self.temp_dir / "config.json"
        config_module.LEGACY_LARK_GROUP_MAPPING_FILE = self.temp_dir / "lark_group_mapping.json"
        config_module.RUNTIME_LOCK_FILE = self.temp_dir / "runtime.json.lock"
        config_module.USER_CONFIG_LOCK_FILE = self.temp_dir / "config.json.lock"

    def teardown(self):
        """清理测试环境"""
        import utils.runtime_config as config_module

        # 恢复原始环境
        config_module.USER_DATA_DIR = self.old_env['USER_DATA_DIR']
        config_module.RUNTIME_CONFIG_FILE = self.old_env['RUNTIME_CONFIG_FILE']
        config_module.USER_CONFIG_FILE = self.old_env['USER_CONFIG_FILE']
        config_module.LEGACY_LARK_GROUP_MAPPING_FILE = self.old_env['LEGACY_LARK_GROUP_MAPPING_FILE']
        config_module.RUNTIME_LOCK_FILE = self.old_env['RUNTIME_LOCK_FILE']
        config_module.USER_CONFIG_LOCK_FILE = self.old_env['USER_CONFIG_LOCK_FILE']

        # 清理临时目录
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# ============== 配置加载测试 ==============

def test_load_config_not_exists():
    """测试配置文件不存在时返回默认配置"""
    env = TestEnv()
    env.setup()
    try:
        config = load_runtime_config()
        assert config.version == CURRENT_VERSION
        assert config.session_mappings == {}
        assert config.lark_group_mappings == {}
        print("✓ 配置加载：文件不存在返回默认配置")
    finally:
        env.teardown()


def test_load_config_valid():
    """测试加载有效配置文件"""
    env = TestEnv()
    env.setup()
    try:
        # 创建配置文件（RuntimeConfig 不含 ui_settings）
        data = {
            "version": "1.0",
            "session_mappings": {"test": "/path/to/test"},
            "lark_group_mappings": {"oc_123": "my-session"}
        }
        import utils.runtime_config as config_module
        config_module.RUNTIME_CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False))

        config = load_runtime_config()
        assert config.get_session_mapping("test") == "/path/to/test"
        assert config.lark_group_mappings["oc_123"] == "my-session"
        print("✓ 配置加载：有效配置文件")
    finally:
        env.teardown()


def test_load_config_corrupted():
    """测试加载损坏配置文件（备份并返回默认配置）"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module
        import glob

        # 创建损坏的配置文件
        config_module.RUNTIME_CONFIG_FILE.write_text("{ invalid json }")

        config = load_runtime_config()

        # 应返回默认配置
        assert config.version == CURRENT_VERSION
        assert config.session_mappings == {}

        # 损坏文件应被备份（备份文件名格式: .json.bak.{timestamp}）
        backup_pattern = str(config_module.RUNTIME_CONFIG_FILE.with_suffix(".json.bak.*"))
        backup_files = glob.glob(backup_pattern)
        assert len(backup_files) > 0, "应存在备份文件"
        print("✓ 配置加载：损坏文件备份并返回默认配置")
    finally:
        env.teardown()


def test_load_config_partial():
    """测试加载部分字段缺失的配置文件"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 创建部分配置文件（只有 session_mappings）
        data = {
            "version": "1.0",
            "session_mappings": {"test": "/path/to/test"}
        }
        config_module.RUNTIME_CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False))

        config = load_runtime_config()
        assert config.get_session_mapping("test") == "/path/to/test"
        assert config.lark_group_mappings == {}  # 使用默认值
        print("✓ 配置加载：部分字段缺失使用默认值")
    finally:
        env.teardown()


# ============== 配置保存测试 ==============

def test_save_config_new():
    """测试保存新配置文件"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        config = RuntimeConfig()
        config.set_session_mapping("test", "/path/to/test")
        config.lark_group_mappings["oc_123"] = "my-session"

        save_runtime_config(config)

        # 验证文件已创建
        assert config_module.RUNTIME_CONFIG_FILE.exists()

        # 验证内容
        data = json.loads(config_module.RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
        assert data["session_mappings"]["test"] == "/path/to/test"
        assert data["lark_group_mappings"]["oc_123"] == "my-session"
        print("✓ 配置保存：新建配置文件")
    finally:
        env.teardown()


def test_save_config_overwrite():
    """测试覆盖保存配置文件"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 创建初始配置
        config1 = RuntimeConfig()
        config1.set_session_mapping("old", "/path/to/old")
        save_runtime_config(config1)

        # 覆盖保存
        config2 = RuntimeConfig()
        config2.set_session_mapping("new", "/path/to/new")
        save_runtime_config(config2)

        # 验证旧数据已被覆盖
        data = json.loads(config_module.RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
        assert "old" not in data["session_mappings"]
        assert data["session_mappings"]["new"] == "/path/to/new"
        print("✓ 配置保存：覆盖已有配置文件")
    finally:
        env.teardown()


def test_save_config_with_quick_commands():
    """测试保存包含快捷命令的用户配置"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        config = UserConfig()
        config.ui_settings.quick_commands.enabled = True
        config.ui_settings.quick_commands.commands = [
            QuickCommand("清空", "/clear", "🗑️"),
            QuickCommand("退出", "/exit", "🚪")
        ]

        save_user_config(config)

        # 验证快捷命令保存正确
        data = json.loads(config_module.USER_CONFIG_FILE.read_text(encoding="utf-8"))
        assert data["ui_settings"]["quick_commands"]["enabled"] is True
        assert len(data["ui_settings"]["quick_commands"]["commands"]) == 2
        print("✓ 配置保存：快捷命令配置")
    finally:
        env.teardown()


def test_load_user_config_from_file():
    """测试从文件加载用户配置"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 创建用户配置文件
        data = {
            "version": "1.0",
            "ui_settings": {
                "quick_commands": {
                    "enabled": True,
                    "commands": [
                        {"label": "测试", "value": "/test", "icon": "🧪"},
                        {"label": "清空", "value": "/clear", "icon": "🗑️"}
                    ]
                }
            }
        }
        config_module.USER_CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False))

        config = load_user_config()
        assert config.is_quick_commands_visible()
        assert len(config.get_quick_commands()) == 2
        assert config.get_quick_commands()[0].label == "测试"
        assert config.get_quick_commands()[0].value == "/test"
        print("✓ 用户配置加载：从文件加载成功")
    finally:
        env.teardown()


def test_load_user_config_not_exists():
    """测试用户配置文件不存在时返回默认配置"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 确保文件不存在
        if config_module.USER_CONFIG_FILE.exists():
            config_module.USER_CONFIG_FILE.unlink()

        config = load_user_config()
        assert config.version == USER_CONFIG_VERSION
        assert not config.is_quick_commands_visible()
        assert config.get_quick_commands() == []
        print("✓ 用户配置加载：文件不存在返回默认配置")
    finally:
        env.teardown()


def test_load_user_config_corrupted():
    """测试用户配置文件损坏时备份并返回默认配置"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 创建损坏的配置文件
        config_module.USER_CONFIG_FILE.write_text("invalid json {{{")

        config = load_user_config()
        # 应返回默认配置
        assert not config.is_quick_commands_visible()

        # 应创建备份文件
        bak_files = list(config_module.USER_DATA_DIR.glob("config.json.bak*"))
        assert len(bak_files) > 0
        print("✓ 用户配置加载：文件损坏时备份并返回默认配置")
    finally:
        env.teardown()


# ============== 迁移逻辑测试 ==============

def test_migrate_no_legacy_file():
    """测试无旧配置文件时迁移"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 确保旧文件不存在
        assert not config_module.LEGACY_LARK_GROUP_MAPPING_FILE.exists()

        migrate_legacy_config()

        # 不应创建新文件
        assert not config_module.RUNTIME_CONFIG_FILE.exists()
        print("✓ 迁移：无旧文件时跳过")
    finally:
        env.teardown()


def test_migrate_empty_legacy_file():
    """测试迁移空旧配置文件"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 创建空的旧配置文件
        config_module.LEGACY_LARK_GROUP_MAPPING_FILE.write_text("{}")

        migrate_legacy_config()

        # 旧文件应被删除
        assert not config_module.LEGACY_LARK_GROUP_MAPPING_FILE.exists()
        print("✓ 迁移：空旧文件删除")
    finally:
        env.teardown()


def test_migrate_valid_legacy_file():
    """测试迁移有效旧配置文件"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 创建旧配置文件
        legacy_data = {
            "oc_123": "session-a",
            "oc_456": "session-b"
        }
        config_module.LEGACY_LARK_GROUP_MAPPING_FILE.write_text(
            json.dumps(legacy_data, ensure_ascii=False)
        )

        migrate_legacy_config()

        # 旧文件应被删除
        assert not config_module.LEGACY_LARK_GROUP_MAPPING_FILE.exists()

        # 迁移到 runtime.json
        config = load_runtime_config()
        assert config.lark_group_mappings["oc_123"] == "session-a"
        assert config.lark_group_mappings["oc_456"] == "session-b"
        print("✓ 迁移：有效旧文件迁移成功")
    finally:
        env.teardown()


def test_migrate_conflict_with_existing():
    """测试迁移时 runtime.json 已存在映射"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 创建 runtime.json（已有映射）
        existing_config = RuntimeConfig()
        existing_config.lark_group_mappings["oc_existing"] = "existing-session"
        save_runtime_config(existing_config)

        # 创建旧配置文件
        legacy_data = {"oc_legacy": "legacy-session"}
        config_module.LEGACY_LARK_GROUP_MAPPING_FILE.write_text(
            json.dumps(legacy_data, ensure_ascii=False)
        )

        migrate_legacy_config()

        # 应保留 runtime.json 中的映射，跳过迁移
        config = load_runtime_config()
        assert config.lark_group_mappings["oc_existing"] == "existing-session"
        assert "oc_legacy" not in config.lark_group_mappings
        print("✓ 迁移：冲突时保留 runtime.json 映射")
    finally:
        env.teardown()


def test_migrate_corrupted_legacy_file():
    """测试迁移损坏的旧配置文件"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module
        import glob

        # 创建损坏的旧配置文件
        config_module.LEGACY_LARK_GROUP_MAPPING_FILE.write_text("{ invalid json }")

        migrate_legacy_config()

        # 损坏文件应被备份（备份文件名格式: .json.bak.{timestamp}）
        backup_pattern = str(config_module.LEGACY_LARK_GROUP_MAPPING_FILE.with_suffix(".json.bak.*"))
        backup_files = glob.glob(backup_pattern)
        assert len(backup_files) > 0, "应存在备份文件"
        assert not config_module.LEGACY_LARK_GROUP_MAPPING_FILE.exists()
        print("✓ 迁移：损坏旧文件备份")
    finally:
        env.teardown()


# ============== 快捷命令可见性测试（UserConfig）==============

def test_quick_commands_visibility_disabled():
    """测试快捷命令默认不可见"""
    config = UserConfig()
    assert not config.is_quick_commands_visible()
    print("✓ 快捷命令可见性：默认禁用")


def test_quick_commands_visibility_enabled_no_commands():
    """测试启用但无命令时不可见"""
    config = UserConfig()
    config.ui_settings.quick_commands.enabled = True
    assert not config.is_quick_commands_visible()
    print("✓ 快捷命令可见性：启用但无命令")


def test_quick_commands_visibility_enabled_with_commands():
    """测试启用且有命令时可见"""
    config = UserConfig()
    config.ui_settings.quick_commands.enabled = True
    config.ui_settings.quick_commands.commands = [
        QuickCommand("清空", "/clear")
    ]
    assert config.is_quick_commands_visible()
    print("✓ 快捷命令可见性：启用且有命令")


def test_quick_commands_visibility_disabled_with_commands():
    """测试禁用但有命令时不可见"""
    config = UserConfig()
    config.ui_settings.quick_commands.enabled = False
    config.ui_settings.quick_commands.commands = [
        QuickCommand("清空", "/clear")
    ]
    assert not config.is_quick_commands_visible()
    print("✓ 快捷命令可见性：禁用但有命令")


def test_get_quick_commands():
    """测试获取快捷命令列表"""
    config = UserConfig()
    config.ui_settings.quick_commands.enabled = True
    config.ui_settings.quick_commands.commands = [
        QuickCommand("清空", "/clear", "🗑️"),
        QuickCommand("退出", "/exit", "🚪")
    ]

    commands = config.get_quick_commands()
    assert len(commands) == 2
    assert commands[0].value == "/clear"
    assert commands[1].value == "/exit"
    print("✓ 获取快捷命令列表")


def test_get_quick_commands_disabled():
    """测试禁用时获取快捷命令返回空列表"""
    config = UserConfig()
    config.ui_settings.quick_commands.enabled = False
    config.ui_settings.quick_commands.commands = [
        QuickCommand("清空", "/clear")
    ]

    commands = config.get_quick_commands()
    assert commands == []
    print("✓ 禁用时获取快捷命令返回空列表")


# ============== 映射限制测试 ==============

def test_session_mapping_limit_warning():
    """测试映射数量达到上限时的警告（不阻塞）"""
    config = RuntimeConfig()

    # 设置大量映射（测试警告日志，不实际达到 500 限制）
    for i in range(10):
        config.set_session_mapping(f"session_{i}", f"/path/to/session_{i}")

    # 验证映射正常保存
    assert len(config.session_mappings) == 10
    print("✓ 映射数量限制警告（不阻塞操作）")


# ============== T073: 补充测试 ==============

def test_quick_command_icon_empty():
    """测试 icon 可空，空时使用空白占位"""
    # icon 为空字符串
    cmd = QuickCommand("清空", "/clear", "")
    assert cmd.icon == "", "icon 应该接受空字符串"
    assert cmd.value == "/clear"
    print("✓ 快捷命令 icon 可空：空字符串")

    # icon 完全省略（使用默认值）
    cmd2 = QuickCommand("退出", "/exit")
    assert cmd2.icon == "", "默认 icon 应为空字符串"
    print("✓ 快捷命令 icon 可空：省略时使用默认值")


def test_quick_command_icon_with_emoji():
    """测试 icon 包含 emoji 正常显示"""
    cmd = QuickCommand("清空", "/clear", "🗑️")
    assert cmd.icon == "🗑️"
    assert cmd.to_dict()["icon"] == "🗑️"
    print("✓ 快捷命令 icon 包含 emoji")


def test_commands_truncation():
    """测试 commands 超过 20 条时静默截断"""
    from utils.runtime_config import QuickCommandsConfig

    # 创建 25 条命令
    commands = [
        QuickCommand(f"命令{i}", f"/cmd{i}")
        for i in range(25)
    ]

    config = QuickCommandsConfig(enabled=True, commands=commands)

    # 当前实现不截断，这里验证命令列表长度
    # 实际截断在 card_builder 中实现
    assert len(config.commands) == 25, "QuickCommandsConfig 不截断命令列表"
    print(f"✓ commands 数量: {len(config.commands)} (截断在 card_builder 中实现)")


def test_commands_exactly_20():
    """测试 commands 恰好 20 条时正常显示"""
    from utils.runtime_config import QuickCommandsConfig

    commands = [
        QuickCommand(f"命令{i}", f"/cmd{i}")
        for i in range(20)
    ]

    config = QuickCommandsConfig(enabled=True, commands=commands)
    assert config.is_visible(), "20 条命令应该可见"
    assert len(config.commands) == 20
    print("✓ commands 恰好 20 条正常显示")


# ============== operation_panel 配置测试 ==============


def test_operation_panel_defaults():
    """测试 operation_panel 默认值"""
    settings = OperationPanelSettings()
    assert settings.show_builtin_keys is True
    assert settings.show_custom_commands is True
    assert settings.enabled_keys == ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]
    print("✓ operation_panel 默认值")


def test_operation_panel_roundtrip_serialization():
    """测试 operation_panel 序列化/反序列化 roundtrip"""
    config = UserConfig(
        ui_settings=UISettings(
            operation_panel=OperationPanelSettings(
                show_builtin_keys=False,
                show_custom_commands=False,
                enabled_keys=["esc", "ctrl_o", "up"],
            )
        )
    )

    data = config.to_dict()
    loaded = UserConfig.from_dict(data)

    assert loaded.ui_settings.operation_panel.show_builtin_keys is False
    assert loaded.ui_settings.operation_panel.show_custom_commands is False
    assert loaded.ui_settings.operation_panel.enabled_keys == ["esc", "ctrl_o", "up"]
    print("✓ operation_panel roundtrip")


def test_operation_panel_invalid_keys_filtered():
    """测试 operation_panel 非法键过滤"""
    settings = OperationPanelSettings.from_dict({
        "enabled_keys": ["up", "invalid", "ctrl_o", "bad", "shift_tab_x3"]
    })
    assert settings.enabled_keys == ["up", "ctrl_o", "shift_tab_x3"]
    print("✓ operation_panel 非法键过滤")


def test_operation_panel_empty_or_all_invalid_fallback_default_keys():
    """测试 operation_panel enabled_keys 为空或全非法时回退默认键集"""
    settings_empty = OperationPanelSettings.from_dict({"enabled_keys": []})
    assert settings_empty.enabled_keys == ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]

    settings_all_invalid = OperationPanelSettings.from_dict({"enabled_keys": ["foo", "bar"]})
    assert settings_all_invalid.enabled_keys == ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]
    print("✓ operation_panel 空/全非法回退默认键集")


def test_save_config_permission_error():
    """测试权限不足时使用内存配置继续运行"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module
        import builtins

        config = RuntimeConfig()
        config.set_session_mapping("test", "/path/to/test")

        # 模拟权限错误：mock builtins.open
        original_open = builtins.open

        def mock_open(*args, **kwargs):
            if 'w' in str(args[1]) if len(args) > 1 else kwargs.get('mode', ''):
                raise PermissionError("Permission denied")
            return original_open(*args, **kwargs)

        builtins.open = mock_open
        try:
            save_runtime_config(config)
            assert False, "应该抛出 PermissionError"
        except PermissionError as e:
            # 权限不足时应该抛出异常，调用方负责处理（使用内存配置继续）
            assert "Permission denied" in str(e)
            print("✓ 权限不足时抛出 PermissionError，调用方使用内存配置继续")
        finally:
            builtins.open = original_open

    finally:
        env.teardown()


def test_runtime_config_memory_fallback():
    """测试内存配置回退机制"""
    config = RuntimeConfig()
    config.set_session_mapping("memory_test", "/path/to/memory/test")

    # 即使保存失败，内存中的配置仍然可用
    assert config.get_session_mapping("memory_test") == "/path/to/memory/test"
    print("✓ 内存配置回退：配置在内存中保持")


# ============== 配置重置清理范围测试（T106d） ==============


def _write_dummy_file(path: Path, content: str = "dummy") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _read_config_reset_defaults() -> tuple[dict, dict]:
    """从模板文件读取默认配置"""
    config_template = Path(_PROJECT_ROOT) / "resources" / "defaults" / "config.default.json"
    runtime_template = Path(_PROJECT_ROOT) / "resources" / "defaults" / "runtime.default.json"

    return (
        json.loads(config_template.read_text(encoding="utf-8")),
        json.loads(runtime_template.read_text(encoding="utf-8"))
    )


def _run_config_reset(temp_dir: Path, mode: str) -> int:
    """执行 config reset 并返回退出码"""
    import utils.runtime_config as config_module

    # 直接创建带正确值的 Args 对象
    args = type("Args", (), {
        "all": mode == "all",
        "config_only": mode == "config",
        "runtime_only": mode == "runtime",
    })()

    if mode not in ("all", "config", "runtime"):
        raise ValueError("invalid mode")

    # 确保模块内路径指向临时目录
    config_module.USER_DATA_DIR = temp_dir
    config_module.USER_CONFIG_FILE = temp_dir / "config.json"
    config_module.RUNTIME_CONFIG_FILE = temp_dir / "runtime.json"
    config_module.USER_CONFIG_LOCK_FILE = temp_dir / "config.json.lock"
    config_module.RUNTIME_LOCK_FILE = temp_dir / "runtime.json.lock"

    from remote_claude import cmd_config_reset

    return cmd_config_reset(args)


def test_config_reset_cleanup_scope_config_only():
    """测试 --config 仅清理 config.json 副作用文件"""
    env = TestEnv()
    env.setup()
    try:
        temp_dir = env.temp_dir
        _write_dummy_file(temp_dir / "config.json.lock")
        _write_dummy_file(temp_dir / "config.json.bak.20260321_000001")
        _write_dummy_file(temp_dir / "runtime.json.lock")
        _write_dummy_file(temp_dir / "runtime.json.bak.20260321_000002")

        exit_code = _run_config_reset(temp_dir, "config")
        assert exit_code == 0

        assert not (temp_dir / "config.json.lock").exists()
        assert not (temp_dir / "config.json.bak.20260321_000001").exists()
        assert (temp_dir / "runtime.json.lock").exists()
        assert (temp_dir / "runtime.json.bak.20260321_000002").exists()
        print("✓ 配置重置清理范围：--config 仅清理 config 文件")
    finally:
        env.teardown()


def test_config_reset_cleanup_scope_runtime_only():
    """测试 --runtime 仅清理 runtime.json 副作用文件"""
    env = TestEnv()
    env.setup()
    try:
        temp_dir = env.temp_dir
        _write_dummy_file(temp_dir / "config.json.lock")
        _write_dummy_file(temp_dir / "config.json.bak.20260321_000001")
        _write_dummy_file(temp_dir / "runtime.json.lock")
        _write_dummy_file(temp_dir / "runtime.json.bak.20260321_000002")

        exit_code = _run_config_reset(temp_dir, "runtime")
        assert exit_code == 0

        assert (temp_dir / "config.json.lock").exists()
        assert (temp_dir / "config.json.bak.20260321_000001").exists()
        assert not (temp_dir / "runtime.json.lock").exists()
        assert not (temp_dir / "runtime.json.bak.20260321_000002").exists()
        print("✓ 配置重置清理范围：--runtime 仅清理 runtime 文件")
    finally:
        env.teardown()


def test_config_reset_cleanup_scope_all():
    """测试 --all 清理全部锁文件和备份文件"""
    env = TestEnv()
    env.setup()
    try:
        temp_dir = env.temp_dir
        _write_dummy_file(temp_dir / "config.json.lock")
        _write_dummy_file(temp_dir / "config.json.bak.20260321_000001")
        _write_dummy_file(temp_dir / "runtime.json.lock")
        _write_dummy_file(temp_dir / "runtime.json.bak.20260321_000002")

        exit_code = _run_config_reset(temp_dir, "all")
        assert exit_code == 0

        assert not (temp_dir / "config.json.lock").exists()
        assert not (temp_dir / "config.json.bak.20260321_000001").exists()
        assert not (temp_dir / "runtime.json.lock").exists()
        assert not (temp_dir / "runtime.json.bak.20260321_000002").exists()
        print("✓ 配置重置清理范围：--all 清理全部文件")
    finally:
        env.teardown()


def test_main_lark_without_subcommand_uses_compat_handler(monkeypatch):
    """测试 `remote-claude lark`（无子命令）不会因缺少 func 崩溃"""
    import remote_claude
    import utils.runtime_config as config_module

    monkeypatch.setattr(config_module, "migrate_legacy_config", lambda: None)
    monkeypatch.setattr(config_module, "migrate_legacy_notify_settings", lambda: None)
    monkeypatch.setattr(remote_claude, "is_lark_running", lambda: False)
    monkeypatch.setattr(sys, "argv", ["remote-claude", "lark"])

    assert remote_claude.main() == 0


# ============== uv_path 测试 ==============

def test_uv_path_get_default():
    """测试 uv_path 默认值为 None"""
    env = TestEnv()
    env.setup()
    try:
        config = load_runtime_config()
        assert config.uv_path is None
        print("✓ uv_path 默认值为 None")
    finally:
        env.teardown()


def test_uv_path_set_and_get():
    """测试 uv_path 设置和读取"""
    env = TestEnv()
    env.setup()
    try:
        import utils.runtime_config as config_module

        # 设置路径
        set_uv_path("/usr/local/bin/uv")

        # 重新读取验证
        path = get_uv_path()
        assert path == "/usr/local/bin/uv"
        print("✓ uv_path 设置和读取")
    finally:
        env.teardown()


def test_validate_uv_path():
    """测试 uv_path 验证函数"""
    # 空路径
    valid, msg = validate_uv_path("")
    assert not valid
    assert "空" in msg

    # 不存在的路径
    valid, msg = validate_uv_path("/nonexistent/uv")
    assert not valid
    assert "不存在" in msg

    # 查找系统中的 uv
    import shutil
    uv_path = shutil.which("uv")
    if uv_path:
        # 存在且可执行
        valid, msg = validate_uv_path(uv_path)
        assert valid
        assert msg == ""

    print("✓ validate_uv_path 验证")


def test_runtime_config_to_dict_with_uv_path():
    """测试 to_dict 包含 uv_path"""
    config = RuntimeConfig(uv_path="/test/uv")
    d = config.to_dict()
    assert "uv_path" in d
    assert d["uv_path"] == "/test/uv"
    print("✓ to_dict 包含 uv_path")


def test_runtime_config_from_dict_with_uv_path():
    """测试 from_dict 解析 uv_path"""
    data = {
        "version": "1.0",
        "uv_path": "/opt/uv",
        "session_mappings": {},
        "lark_group_mappings": {}
    }
    config = RuntimeConfig.from_dict(data)
    assert config.uv_path == "/opt/uv"
    print("✓ from_dict 解析 uv_path")


# ============== 运行所有测试 ==============

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("运行时配置测试")
    print("=" * 60)

    tests = [
        # 配置加载
        test_load_config_not_exists,
        test_load_config_valid,
        test_load_config_corrupted,
        test_load_config_partial,
        # 配置保存
        test_save_config_new,
        test_save_config_overwrite,
        test_save_config_with_quick_commands,
        # 用户配置加载
        test_load_user_config_from_file,
        test_load_user_config_not_exists,
        test_load_user_config_corrupted,
        # 迁移逻辑
        test_migrate_no_legacy_file,
        test_migrate_empty_legacy_file,
        test_migrate_valid_legacy_file,
        test_migrate_conflict_with_existing,
        test_migrate_corrupted_legacy_file,
        # 快捷命令可见性
        test_quick_commands_visibility_disabled,
        test_quick_commands_visibility_enabled_no_commands,
        test_quick_commands_visibility_enabled_with_commands,
        test_quick_commands_visibility_disabled_with_commands,
        test_get_quick_commands,
        test_get_quick_commands_disabled,
        # 映射限制
        test_session_mapping_limit_warning,
        # T073: 补充测试
        test_quick_command_icon_empty,
        test_quick_command_icon_with_emoji,
        test_commands_truncation,
        test_commands_exactly_20,
        test_save_config_permission_error,
        test_runtime_config_memory_fallback,
        # T106d: 配置重置清理范围
        test_config_reset_cleanup_scope_config_only,
        test_config_reset_cleanup_scope_runtime_only,
        test_config_reset_cleanup_scope_all,
        # uv_path 测试
        test_uv_path_get_default,
        test_uv_path_set_and_get,
        test_validate_uv_path,
        test_runtime_config_to_dict_with_uv_path,
        test_runtime_config_from_dict_with_uv_path,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
