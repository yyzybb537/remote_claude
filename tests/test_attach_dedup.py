"""
tests/test_attach_dedup.py

attach 相关去重逻辑单元测试（无需运行中的 Claude 会话）

测试用例：
  1. 历史卡片过滤：■ (U+25A0) 开头的欢迎横幅行应被过滤
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lark_client.session_bridge import SessionBridge
from lark_client.component_parser import _should_skip_line


def make_bridge():
    """创建不连接 socket 的 SessionBridge（仅测试内部逻辑）"""
    outputs = []
    bridge = SessionBridge(
        session_name="test",
        on_output=lambda comps: outputs.append(comps),
    )
    return bridge, outputs


# ──────────────────────────────────────────────────────────────────────────────
# 测试 1：■ 字符（U+25A0）开头行被 _should_skip_line 过滤
# ──────────────────────────────────────────────────────────────────────────────

def test_skip_line_with_square_char():
    """■ ■ ■  ~/dev/... 应被 _should_skip_line 过滤"""
    line = "■ ■ ■  ~/dev/claude_plugins/remote_claude"
    result = _should_skip_line(line)
    assert result, f"期望 _should_skip_line 返回 True，但得到 False。line={line!r}"
    print("✅ 测试 1 通过：■ (U+25A0) 开头行被正确过滤")


def test_skip_line_with_block_element():
    """▘▝  ~/dev/... 应被 _should_skip_line 过滤（原有范围）"""
    line = "▘▝  ~/dev/remote_claude"
    result = _should_skip_line(line)
    assert result, f"期望 _should_skip_line 返回 True，但得到 False。line={line!r}"
    print("✅ 测试 1b 通过：▘▝ 开头行被正确过滤（原有范围）")


def test_format_plain_output_filters_square():
    """_format_plain_output 应过滤含 ■ 的欢迎横幅碎片行"""
    bridge, _ = make_bridge()
    text = "\n".join([
        "■ ■ ■  ~/dev/claude_plugins/remote_claude",
        "⏺ 任务完成了",
    ])
    result = bridge._format_plain_output(text)
    assert "■" not in result or "~/dev" not in result, (
        f"期望 ■ ■ ■  ~/dev/... 被过滤，但实际输出：{result!r}"
    )
    assert "任务完成了" in result, f"期望保留有效内容，实际：{result!r}"
    print("✅ 测试 1c 通过：_format_plain_output 正确过滤 ■ 行并保留有效内容")


# ──────────────────────────────────────────────────────────────────────────────
# 运行所有测试
# ──────────────────────────────────────────────────────────────────────────────

def run_all():
    tests = [
        test_skip_line_with_square_char,
        test_skip_line_with_block_element,
        test_format_plain_output_filters_square,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} 失败: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"❌ {test.__name__} 异常: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"总计: {passed} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
