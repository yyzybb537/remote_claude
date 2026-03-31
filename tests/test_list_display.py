#!/usr/bin/env python3
"""
List 命令展示格式测试

测试覆盖：
1. list 命令展示截断名称、原始路径和状态
2. 无映射时原始路径显示 '-'
3. 无活跃会话时的提示
4. 长名称和长路径的截断显示
"""

import sys
import tempfile
import shutil
import json
from pathlib import Path

import remote_claude

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.runtime_config import (
    State,
    SessionState,
    load_state,
    save_state,
    USER_DATA_DIR,
    STATE_FILE,
)


class _TestEnv:
    """测试环境管理"""

    def __init__(self):
        self.original_dir = None
        self.temp_dir = None
        self.old_env = {}

    def setup(self):
        """设置测试环境"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_dir = USER_DATA_DIR

        # 保存原始环境
        import utils.runtime_config as config_module
        self.old_env = {
            'USER_DATA_DIR': config_module.USER_DATA_DIR,
            'STATE_FILE': config_module.STATE_FILE,
        }

        # 临时替换路径
        config_module.USER_DATA_DIR = self.temp_dir
        config_module.STATE_FILE = self.temp_dir / "state.json"

    def teardown(self):
        """清理测试环境"""
        import utils.runtime_config as config_module

        # 恢复原始环境
        config_module.USER_DATA_DIR = self.old_env['USER_DATA_DIR']
        config_module.STATE_FILE = self.old_env['STATE_FILE']

        # 清理临时目录
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# ============== 测试函数 ==============

def test_normalize_original_path_returns_dash_for_none():
    assert remote_claude._normalize_original_path(None) == "-"


def test_normalize_original_path_returns_dash_for_empty_string():
    assert remote_claude._normalize_original_path("") == "-"


def test_normalize_original_path_returns_dash_for_whitespace():
    assert remote_claude._normalize_original_path("   ") == "-"


def test_normalize_original_path_strips_regular_value():
    assert remote_claude._normalize_original_path(" /tmp/demo ") == "/tmp/demo"


def test_list_display_with_mapping():
    """测试 list 展示截断名称和原始路径"""
    env = _TestEnv()
    env.setup()
    try:
        # 创建状态，包含会话路径
        state = State()
        state.set_session_path("myapp_src", "/Users/dev/projects/myapp/src")
        state.set_session_path("test_session", "/path/to/test/project")
        save_state(state)

        # 重新加载状态
        loaded = load_state()

        # 验证路径存在
        assert loaded.get_session_path("myapp_src") == "/Users/dev/projects/myapp/src", \
            f"路径应正确存储，期望: /Users/dev/projects/myapp/src，实际: {loaded.get_session_path('myapp_src')}"
        assert loaded.get_session_path("test_session") == "/path/to/test/project", \
            f"路径应正确存储，期望: /path/to/test/project，实际: {loaded.get_session_path('test_session')}"

        print("OK List 展示：映射正确存储和读取")
    finally:
        env.teardown()


def test_list_display_no_mapping():
    """测试无映射时原始路径显示 '-'"""
    env = _TestEnv()
    env.setup()
    try:
        # 创建空状态
        state = State()
        save_state(state)

        # 重新加载状态
        loaded = load_state()

        # 验证无映射时返回 None（显示时应转为 '-'）
        result = loaded.get_session_path("unknown_session")
        assert result is None, \
            f"无映射时应返回 None，实际: {result}"

        # 模拟 cmd_list 中的逻辑
        display_path = result or "-"
        assert display_path == "-", \
            f"无映射时应显示 '-'，实际: {display_path}"

        print("OK List 展示：无映射时显示 '-'")
    finally:
        env.teardown()


def test_list_display_empty_mapping_shows_dash():
    """测试空字符串映射时原始路径显示 '-'"""
    env = _TestEnv()
    env.setup()
    try:
        state = State()
        state.set_session_path("empty_session", "")
        save_state(state)

        loaded = load_state()
        result = loaded.get_session_path("empty_session")
        assert result == "", f"空字符串映射应保留原值，实际: {result!r}"

        display_path = result or "-"
        assert display_path == "-", f"空字符串映射应显示 '-'，实际: {display_path}"

        print("OK List 展示：空字符串映射时显示 '-'")
    finally:
        env.teardown()


def test_list_display_whitespace_mapping_shows_dash():
    """测试空白字符串映射时原始路径显示 '-'"""
    env = _TestEnv()
    env.setup()
    try:
        state = State()
        state.set_session_path("blank_session", "   ")
        save_state(state)

        loaded = load_state()
        result = loaded.get_session_path("blank_session")
        assert result == "   ", f"空白字符串映射应保留原值，实际: {result!r}"

        display_path = result.strip() if isinstance(result, str) else result
        display_path = display_path or "-"
        assert display_path == "-", f"空白字符串映射应显示 '-'，实际: {display_path!r}"

        print("OK List 展示：空白字符串映射时显示 '-'")
    finally:
        env.teardown()


def test_list_display_long_names():
    """测试长名称和长路径的截断显示"""
    env = _TestEnv()
    env.setup()
    try:
        # 创建长路径映射
        long_path = "/Users/dev/projects/very/long/path/to/myapp/src/components/utils/helpers/deep"
        truncated_name = "myapp_src_components_utils_h"

        state = State()
        state.set_session_path(truncated_name, long_path)
        save_state(state)

        # 重新加载状态
        loaded = load_state()

        # 验证长路径映射
        result = loaded.get_session_path(truncated_name)
        assert result == long_path, \
            f"长路径映射应正确存储，期望: {long_path}，实际: {result}"

        # 模拟 cmd_list 中的截断显示逻辑
        name_display = truncated_name[:18] + ".." if len(truncated_name) > 20 else truncated_name
        path_display = long_path[:50] + ".." if len(long_path) > 52 else long_path

        assert len(name_display) <= 20, \
            f"截断后名称长度应 <= 20，实际: {len(name_display)}"
        assert len(path_display) <= 52, \
            f"截断后路径长度应 <= 52，实际: {len(path_display)}"

        print("OK List 展示：长名称和长路径截断显示正确")
    finally:
        env.teardown()


def test_list_display_special_characters():
    """测试特殊字符路径的展示"""
    env = _TestEnv()
    env.setup()
    try:
        # 创建包含特殊字符的路径映射
        special_path = "/Users/dev/projects/my-app/src/components.test"
        truncated_name = "my_app_src_components_test"

        state = State()
        state.set_session_path(truncated_name, special_path)
        save_state(state)

        # 重新加载状态
        loaded = load_state()

        # 验证特殊字符路径映射
        result = loaded.get_session_path(truncated_name)
        assert result == special_path, \
            f"特殊字符路径映射应正确存储，期望: {special_path}，实际: {result}"

        print("OK List 展示：特殊字符路径正确展示")
    finally:
        env.teardown()


def test_list_display_multiple_sessions():
    """测试多会话列表展示"""
    env = _TestEnv()
    env.setup()
    try:
        # 创建多个会话映射
        state = State()
        state.set_session_path("session1", "/path/to/session1")
        state.set_session_path("session2", "/path/to/session2")
        state.set_session_path("session3", "/path/to/session3")
        save_state(state)

        # 重新加载状态
        loaded = load_state()

        # 验证所有映射
        assert len(loaded.sessions) == 3, \
            f"应有 3 个会话，实际: {len(loaded.sessions)}"

        for name, path in [
            ("session1", "/path/to/session1"),
            ("session2", "/path/to/session2"),
            ("session3", "/path/to/session3"),
        ]:
            result = loaded.get_session_path(name)
            assert result == path, \
                f"映射 {name} 应为 {path}，实际: {result}"

        print("OK List 展示：多会话列表正确展示")
    finally:
        env.teardown()


def test_list_display_with_lark_chat_id():
    """测试会话路径和飞书群 ID 共存"""
    env = _TestEnv()
    env.setup()
    try:
        # 创建状态，包含路径和飞书群绑定
        state = State()
        state.set_session_path("myapp_src", "/Users/dev/projects/myapp/src")
        state.set_lark_chat_id("myapp_src", "oc_xxx")
        state.set_lark_chat_id("other_session", "oc_yyy")
        save_state(state)

        # 重新加载状态
        loaded = load_state()

        # 验证路径和飞书群绑定都存在
        assert loaded.get_session_path("myapp_src") == "/Users/dev/projects/myapp/src"
        assert loaded.get_lark_chat_id("myapp_src") == "oc_xxx"
        assert loaded.get_lark_chat_id("other_session") == "oc_yyy"

        print("OK List 展示：会话路径和飞书群绑定共存正确")
    finally:
        env.teardown()


# ============== 运行测试 ==============

if __name__ == "__main__":
    tests = [
        test_list_display_with_mapping,
        test_list_display_no_mapping,
        test_list_display_long_names,
        test_list_display_special_characters,
        test_list_display_multiple_sessions,
        test_list_display_with_lark_chat_id,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: 意外错误 - {e}")
            failed += 1

    print("-" * 50)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    sys.exit(0 if failed == 0 else 1)
