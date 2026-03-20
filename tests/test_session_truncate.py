#!/usr/bin/env python3
"""
会话名称截断测试

测试覆盖：
1. 截断策略（从右向左保留路径后缀）
2. 冲突检测（不同路径产生相同截断名称）
3. 映射存储（RuntimeConfig 存储）
4. 平台检测（macOS/Linux socket 路径限制）
"""

import sys
import tempfile
import shutil
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.session import _safe_filename, _MAX_FILENAME
from utils.runtime_config import RuntimeConfig, QuickCommand


def test_safe_filename_normal():
    """测试正常长度会话名（不截断）"""
    name = "my-session"
    result = _safe_filename(name)
    assert result == name, f"预期 '{name}'，实际 '{result}'"
    print(f"✓ 正常会话名: {name} -> {result}")


def test_safe_filename_with_slash():
    """测试包含路径分隔符的会话名"""
    name = "/Users/dev/projects/myapp"
    result = _safe_filename(name)
    # 路径开头的 / 被替换为 _，然后首尾下划线被去除
    expected = "Users_dev_projects_myapp"
    assert result == expected, f"预期 '{expected}'，实际 '{result}'"
    print(f"✓ 路径分隔符替换: {name} -> {result}")


def test_safe_filename_truncate():
    """测试超长会话名截断（保留后缀）"""
    # 创建一个超长路径
    parts = ["part" + str(i) for i in range(30)]
    name = "/".join(parts)
    result = _safe_filename(name)

    # 验证长度不超过限制
    assert len(result) <= _MAX_FILENAME, f"截断后长度 {len(result)} 超过限制 {_MAX_FILENAME}"

    # 验证保留后缀（最后一个部分应该存在）
    assert "part29" in result, f"截断后应包含 'part29'，实际 '{result}'"
    print(f"✓ 超长截断（{_MAX_FILENAME}字符限制）: 长度 {len(name)} -> {len(result)}")


def test_safe_filename_md5_fallback():
    """测试单个部分超长时回退到 MD5"""
    # 创建一个单独的超长部分（无法保留任何完整部分）
    long_part = "a" * 200
    name = f"/{long_part}"
    result = _safe_filename(name)

    # 验证长度不超过限制
    assert len(result) <= _MAX_FILENAME, f"MD5 回退后长度 {len(result)} 超过限制 {_MAX_FILENAME}"

    # 验证是 MD5 哈希（32 字符十六进制）
    assert len(result) == 32 or len(result) == _MAX_FILENAME, f"预期 MD5 哈希长度，实际 {len(result)}"
    print(f"✓ MD5 回退: 长度 200 单部分 -> {result[:20]}...")


def test_safe_filename_consecutive_underscores():
    """测试连续下划线合并（如 a__b → a_b）"""
    # 测试连续下划线
    name = "a__b___c"
    result = _safe_filename(name)
    expected = "a_b_c"
    assert result == expected, f"预期 '{expected}'，实际 '{result}'"
    print(f"✓ 连续下划线合并: {name} -> {result}")

    # 测试路径中的连续斜杠（首尾下划线会被去除）
    name = "/path//to///project"
    result = _safe_filename(name)
    expected = "path_to_project"
    assert result == expected, f"预期 '{expected}'，实际 '{result}'"
    print(f"✓ 路径连续分隔符合并: {name} -> {result}")

    # 测试路径和点号混合产生的连续下划线
    name = "/path/./to//project"
    result = _safe_filename(name)
    expected = "path_to_project"
    assert result == expected, f"预期 '{expected}'，实际 '{result}'"
    print(f"✓ 混合分隔符合并: {name} -> {result}")


def test_safe_filename_empty_name():
    """测试空会话名拒绝"""
    # 测试空字符串
    try:
        _safe_filename("")
        assert False, "预期 ValueError: 会话名不能为空"
    except ValueError as e:
        assert "会话名不能为空" in str(e), f"预期错误信息包含 '会话名不能为空'，实际: {e}"
        print("✓ 空会话名拒绝: 空字符串")

    # 测试只有空格
    try:
        _safe_filename("   ")
        assert False, "预期 ValueError: 会话名不能为空"
    except ValueError as e:
        assert "会话名不能为空" in str(e), f"预期错误信息包含 '会话名不能为空'，实际: {e}"
        print("✓ 空会话名拒绝: 只有空格")

    # 测试只有特殊字符（转换后为空）
    try:
        _safe_filename("///...")
        assert False, "预期 ValueError: 无效"
    except ValueError as e:
        assert "无效" in str(e) or "空" in str(e), f"预期错误信息包含 '无效' 或 '空'，实际: {e}"
        print("✓ 空会话名拒绝: 只有特殊字符")


def test_safe_filename_strip_underscores():
    """测试首尾下划线去除"""
    # 测试首尾下划线
    name = "_test_session_"
    result = _safe_filename(name)
    expected = "test_session"
    assert result == expected, f"预期 '{expected}'，实际 '{result}'"
    print(f"✓ 首尾下划线去除: {name} -> {result}")

    # 测试路径开头斜杠产生的首下划线
    name = "/test/session"
    result = _safe_filename(name)
    expected = "test_session"
    assert result == expected, f"预期 '{expected}'，实际 '{result}'"
    print(f"✓ 路径开头斜杠处理: {name} -> {result}")


def test_runtime_config_session_mapping():
    """测试会话映射存储"""
    config = RuntimeConfig()

    # 设置映射
    config.set_session_mapping("myapp_src", "/Users/dev/projects/myapp/src")

    # 获取映射
    result = config.get_session_mapping("myapp_src")
    assert result == "/Users/dev/projects/myapp/src", f"预期 '/Users/dev/projects/myapp/src'，实际 '{result}'"

    # 不存在的映射
    result = config.get_session_mapping("nonexistent")
    assert result is None, f"预期 None，实际 '{result}'"

    print("✓ 会话映射存储和获取")


def test_runtime_config_mapping_limit():
    """测试映射数量限制警告（不阻塞）"""
    config = RuntimeConfig()

    # 设置大量映射（超过限制会输出警告但不阻塞）
    for i in range(10):
        config.set_session_mapping(f"session_{i}", f"/path/to/session_{i}")

    # 验证映射已保存
    assert len(config.session_mappings) == 10, f"预期 10 条映射，实际 {len(config.session_mappings)}"
    print(f"✓ 映射数量限制处理: {len(config.session_mappings)} 条映射")


def test_quick_command_validation():
    """测试快捷命令验证"""
    # 正常命令
    cmd = QuickCommand("清空对话", "/clear", "🗑️")
    assert cmd.value == "/clear", f"预期 '/clear'，实际 '{cmd.value}'"
    print("✓ 快捷命令验证：正常命令")

    # 测试无效命令（不以 / 开头）
    try:
        QuickCommand("无效命令", "clear")
        assert False, "预期 ValueError"
    except ValueError as e:
        assert "必须以 / 开头" in str(e)
        print("✓ 快捷命令验证：无效命令（不以 / 开头）")

    # 测试带空格的命令
    try:
        QuickCommand("带参数命令", "/attach session")
        assert False, "预期 ValueError"
    except ValueError as e:
        assert "不能包含空格" in str(e)
        print("✓ 快捷命令验证：无效命令（包含空格）")


def test_quick_commands_config_visibility():
    """测试快捷命令可见性判断"""
    from utils.runtime_config import QuickCommandsConfig

    # 默认配置：不显示
    config = QuickCommandsConfig()
    assert not config.is_visible(), "默认配置应不显示"
    print("✓ 快捷命令可见性：默认不显示")

    # 启用但无命令：不显示
    config = QuickCommandsConfig(enabled=True)
    assert not config.is_visible(), "启用但无命令应不显示"
    print("✓ 快捷命令可见性：启用但无命令不显示")

    # 启用且有命令：显示
    config = QuickCommandsConfig(
        enabled=True,
        commands=[QuickCommand("清空", "/clear")]
    )
    assert config.is_visible(), "启用且有命令应显示"
    print("✓ 快捷命令可见性：启用且有命令显示")


def test_runtime_config_json_roundtrip():
    """测试 RuntimeConfig 序列化/反序列化"""
    import json

    # 创建配置（RuntimeConfig 不含 ui_settings）
    config = RuntimeConfig()
    config.set_session_mapping("test_session", "/path/to/test")
    config.lark_group_mappings["oc_123"] = "my-session"

    # 序列化
    data = config.to_dict()
    json_str = json.dumps(data, ensure_ascii=False)

    # 反序列化
    data2 = json.loads(json_str)
    config2 = RuntimeConfig.from_dict(data2)

    # 验证
    assert config2.get_session_mapping("test_session") == "/path/to/test"
    assert config2.lark_group_mappings["oc_123"] == "my-session"

    print("✓ 配置序列化/反序列化")


def test_max_filename_platform():
    """测试平台特定的文件名长度限制"""
    import platform

    system = platform.system()
    print(f"✓ 当前平台: {system}, _MAX_FILENAME: {_MAX_FILENAME}")

    # macOS 限制更严格（104 - 19 - 5 = 80）
    if system == "Darwin":
        assert _MAX_FILENAME == 80, f"macOS _MAX_FILENAME 应为 80，实际 {_MAX_FILENAME}"
    # Linux 限制稍宽松（108 - 19 - 5 = 84）
    elif system == "Linux":
        assert _MAX_FILENAME == 84, f"Linux _MAX_FILENAME 应为 84，实际 {_MAX_FILENAME}"


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("会话名称截断测试")
    print("=" * 60)

    tests = [
        test_safe_filename_normal,
        test_safe_filename_with_slash,
        test_safe_filename_truncate,
        test_safe_filename_md5_fallback,
        test_safe_filename_consecutive_underscores,
        test_safe_filename_empty_name,
        test_safe_filename_strip_underscores,
        test_runtime_config_session_mapping,
        test_runtime_config_mapping_limit,
        test_quick_command_validation,
        test_quick_commands_config_visibility,
        test_runtime_config_json_roundtrip,
        test_max_filename_platform,
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
