#!/usr/bin/env python3
"""
日志级别测试

测试覆盖：
1. 默认日志级别为 WARNING
2. 环境变量覆盖日志级别
3. 无效日志级别回退到 WARNING

注意： 本测试为单元测试，不涉及实际的日志输出。
"""

import sys
import os
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def test_default_log_level():
    """测试默认日志级别为 WARNING"""
    # 保存原始环境
    original = os.environ.pop("LARK_LOG_LEVEL", None)

    try:
        # 清除环境变量
        if "LARK_LOG_LEVEL" in os.environ:
            del os.environ["LARK_LOG_LEVEL"]

        # 重新加载配置模块
        import importlib
        import lark_client.config as config_module
        importlib.reload(config_module)

        # 验证默认值为 WARNING (30)
        assert config_module.LARK_LOG_LEVEL == 30, \
            f"默认日志级别应为 30 (WARNING)，实际 {config_module.LARK_LOG_LEVEL}"
        print("✓ 默认日志级别为 WARNING (30)")

    finally:
        # 恢复原始环境
        if original is not None:
            os.environ["LARK_LOG_LEVEL"] = original


def test_env_override_debug():
    """测试环境变量覆盖为 DEBUG"""
    original = os.environ.get("LARK_LOG_LEVEL")

    try:
        os.environ["LARK_LOG_LEVEL"] = "DEBUG"

        # 重新加载配置模块
        import importlib
        import lark_client.config as config_module
        importlib.reload(config_module)

        # 验证 DEBUG = 10
        assert config_module.LARK_LOG_LEVEL == 10, \
            f"DEBUG 日志级别应为 10，实际 {config_module.LARK_LOG_LEVEL}"
        print("✓ LARK_LOG_LEVEL=DEBUG 时日志级别为 10")

    finally:
        if original is not None:
            os.environ["LARK_LOG_LEVEL"] = original
        elif "LARK_LOG_LEVEL" in os.environ:
            del os.environ["LARK_LOG_LEVEL"]


def test_env_override_info():
    """测试环境变量覆盖为 INFO"""
    original = os.environ.get("LARK_LOG_LEVEL")

    try:
        os.environ["LARK_LOG_LEVEL"] = "INFO"

        # 重新加载配置模块
        import importlib
        import lark_client.config as config_module
        importlib.reload(config_module)

        # 验证 INFO = 20
        assert config_module.LARK_LOG_LEVEL == 20, \
            f"INFO 日志级别应为 20，实际 {config_module.LARK_LOG_LEVEL}"
        print("✓ LARK_LOG_LEVEL=INFO 时日志级别为 20")

    finally:
        if original is not None:
            os.environ["LARK_LOG_LEVEL"] = original
        elif "LARK_LOG_LEVEL" in os.environ:
            del os.environ["LARK_LOG_LEVEL"]


def test_env_override_error():
    """测试环境变量覆盖为 ERROR"""
    original = os.environ.get("LARK_LOG_LEVEL")

    try:
        os.environ["LARK_LOG_LEVEL"] = "ERROR"

        # 重新加载配置模块
        import importlib
        import lark_client.config as config_module
        importlib.reload(config_module)

        # 验证 ERROR = 40
        assert config_module.LARK_LOG_LEVEL == 40, \
            f"ERROR 日志级别应为 40，实际 {config_module.LARK_LOG_LEVEL}"
        print("✓ LARK_LOG_LEVEL=ERROR 时日志级别为 40")

    finally:
        if original is not None:
            os.environ["LARK_LOG_LEVEL"] = original
        elif "LARK_LOG_LEVEL" in os.environ:
            del os.environ["LARK_LOG_LEVEL"]


def test_invalid_log_level_fallback():
    """测试无效日志级别回退到 WARNING"""
    original = os.environ.get("LARK_LOG_LEVEL")

    try:
        os.environ["LARK_LOG_LEVEL"] = "INVALID_LEVEL"

        # 重新加载配置模块
        import importlib
        import lark_client.config as config_module
        importlib.reload(config_module)

        # 验证无效级别回退到 WARNING (30)
        assert config_module.LARK_LOG_LEVEL == 30, \
            f"无效日志级别应回退到 30 (WARNING)，实际 {config_module.LARK_LOG_LEVEL}"
        print("✓ 无效日志级别回退到 WARNING (30)")

    finally:
        if original is not None:
            os.environ["LARK_LOG_LEVEL"] = original
        elif "LARK_LOG_LEVEL" in os.environ:
            del os.environ["LARK_LOG_LEVEL"]


def test_case_insensitive():
    """测试日志级别大小写不敏感"""
    original = os.environ.get("LARK_LOG_LEVEL")

    try:
        # 小写
        os.environ["LARK_LOG_LEVEL"] = "debug"
        import importlib
        import lark_client.config as config_module
        importlib.reload(config_module)
        assert config_module.LARK_LOG_LEVEL == 10, \
            f"小写 'debug' 应解析为 10，实际 {config_module.LARK_LOG_LEVEL}"
        print("✓ 小写 'debug' 正确解析为 DEBUG (10)")

        # 混合大小写
        os.environ["LARK_LOG_LEVEL"] = "WaRnInG"
        importlib.reload(config_module)
        assert config_module.LARK_LOG_LEVEL == 30, \
            f"混合大小写 'WaRnInG' 应解析为 30，实际 {config_module.LARK_LOG_LEVEL}"
        print("✓ 混合大小写 'WaRnInG' 正确解析为 WARNING (30)")

    finally:
        if original is not None:
            os.environ["LARK_LOG_LEVEL"] = original
        elif "LARK_LOG_LEVEL" in os.environ:
            del os.environ["LARK_LOG_LEVEL"]


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("日志级别测试")
    print("=" * 60)

    tests = [
        test_default_log_level,
        test_env_override_debug,
        test_env_override_info,
        test_env_override_error,
        test_invalid_log_level_fallback,
        test_case_insensitive,
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
            import traceback
            traceback.print_exc()

    # 最后重新加载配置模块以恢复原始状态
    try:
        import importlib
        import lark_client.config as config_module
        importlib.reload(config_module)
    except Exception:
        pass

    print("=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
