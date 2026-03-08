#!/usr/bin/env python3
"""测试终端渲染器"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lark_client.rich_text_renderer import RichTextRenderer

def test_basic():
    """测试基本渲染"""
    renderer = RichTextRenderer(80, 24)

    # 模拟 Claude CLI 的输出
    # 1. 首先是加载动画
    loading_output = b'\x1b[2J\x1b[H'  # 清屏并移动到左上角
    loading_output += b'\x1b[32m\xe2\x9c\xbb\x1b[0m Bootstrapping\xe2\x80\xa6 (\x1b[1mesc\x1b[0m to interrupt)\r\n'

    renderer.feed(loading_output)
    print("=== 加载动画后 ===")
    print(f"Plain: {repr(renderer.get_plain_display())}")
    print(f"Rich: {repr(renderer.get_rich_text())}")
    print()

    # 2. 然后是用户输入和回复
    # 模拟清屏并显示新内容
    response_output = b'\x1b[2J\x1b[H'  # 清屏
    response_output += b'\xe2\x9d\xaf \xe4\xbd\xa0\xe5\xa5\xbd\r\n'  # ❯ 你好
    response_output += b'\x1b[36m\xe2\x8f\xba\x1b[0m \xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe6\x9c\x89\xe4\xbb\x80\xe4\xb9\x88\xe5\x8f\xaf\xe4\xbb\xa5\xe5\xb8\xae\xe4\xbd\xa0\xe7\x9a\x84\xe5\x90\x97\xef\xbc\x9f\r\n'  # ⏺ 你好！有什么可以帮你的吗？

    # 不清空渲染器，模拟累积
    renderer.feed(response_output)
    print("=== 回复后（不清空）===")
    print(f"Plain: {repr(renderer.get_plain_display())}")
    print(f"Rich: {repr(renderer.get_rich_text())}")
    print()

    # 3. 测试清空后再渲染
    renderer.clear()
    renderer.feed(response_output)
    print("=== 清空后再渲染 ===")
    print(f"Plain: {repr(renderer.get_plain_display())}")
    print(f"Rich: {repr(renderer.get_rich_text())}")
    print()

def test_real_data():
    """测试真实数据格式"""
    renderer = RichTextRenderer(80, 24)

    # 模拟真实的 Claude CLI 输出序列
    # 这些是典型的 ANSI 转义序列

    # 第一帧：加载中
    frame1 = (
        b'\x1b[?25l'  # 隐藏光标
        b'\x1b[2J\x1b[H'  # 清屏
        b'\x1b[32m\xe2\x9c\xbb\x1b[0m Scurrying\xe2\x80\xa6 (\x1b[1mesc\x1b[0m to interrupt)'
    )

    renderer.feed(frame1)
    print("=== 帧1：加载中 ===")
    plain1 = renderer.get_plain_display()
    print(f"内容: {plain1}")
    print()

    # 第二帧：回复
    frame2 = (
        b'\x1b[2J\x1b[H'  # 清屏
        b'\xe2\x9d\xaf \xe4\xbd\xa0\xe5\xa5\xbd\r\n'  # ❯ 你好
        b'\r\n'
        b'\x1b[36m\xe2\x8f\xba\x1b[0m \xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe6\x9c\x89\xe4\xbb\x80\xe4\xb9\x88\xe5\x8f\xaf\xe4\xbb\xa5\xe5\xb8\xae\xe4\xbd\xa0\xe7\x9a\x84\xe5\x90\x97\xef\xbc\x9f'
    )

    renderer.feed(frame2)
    print("=== 帧2：回复（累积）===")
    plain2 = renderer.get_plain_display()
    print(f"内容: {plain2}")
    print()

    # 测试：每帧都清空
    renderer.clear()
    renderer.feed(frame2)
    print("=== 帧2：回复（清空后）===")
    plain3 = renderer.get_plain_display()
    print(f"内容: {plain3}")
    print()

def test_ansi_clear():
    """测试 ANSI 清屏命令"""
    renderer = RichTextRenderer(80, 24)

    # 先写入一些内容
    renderer.feed(b'Hello World')
    print(f"写入后: {repr(renderer.get_plain_display())}")

    # 发送清屏命令
    renderer.feed(b'\x1b[2J\x1b[H')
    print(f"清屏后: {repr(renderer.get_plain_display())}")

    # 写入新内容
    renderer.feed(b'New Content')
    print(f"新内容: {repr(renderer.get_plain_display())}")

if __name__ == '__main__':
    print("=" * 60)
    print("测试 ANSI 清屏命令")
    print("=" * 60)
    test_ansi_clear()
    print()

    print("=" * 60)
    print("测试基本渲染")
    print("=" * 60)
    test_basic()
    print()

    print("=" * 60)
    print("测试真实数据格式")
    print("=" * 60)
    test_real_data()
