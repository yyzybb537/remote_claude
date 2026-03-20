"""
测试中文字符宽度问题
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lark_client.terminal_buffer import TerminalBuffer
import unicodedata


def get_char_width(char):
    """获取字符的显示宽度"""
    if unicodedata.east_asian_width(char) in ('F', 'W'):
        return 2  # 全角字符
    return 1


def test_cjk_width():
    """测试中文字符宽度"""
    print("=" * 60)
    print("测试：中文字符宽度")
    print("=" * 60)

    # 中文字符在终端中占用2个位置
    text = "你好"
    print(f"文本: '{text}'")
    print(f"len(): {len(text)}")
    print(f"显示宽度: {sum(get_char_width(c) for c in text)}")

    # 问题场景
    buffer = TerminalBuffer()

    # 写入动画文本（假设30个字符宽度）
    buffer.write("( · Thinking)                 ")  # 30 字符
    print(f"动画后: '{buffer.get_content()}'")
    print(f"光标位置: {buffer.cursor_col}")

    # 回到行首
    buffer.write("\r")
    print(f"\\r 后光标位置: {buffer.cursor_col}")

    # 写入中文（"你好！" = 3个字符，但显示宽度是5: 2+2+1）
    buffer.write("你好！")
    print(f"写入中文后: '{buffer.get_content()}'")
    print(f"光标位置: {buffer.cursor_col}")

    print("\n问题：中文 '你好！' 只覆盖了3个字符位置，但实际显示需要5个位置")
    print("=" * 60)


def test_with_width_aware():
    """测试考虑字符宽度的情况"""
    print("\n" + "=" * 60)
    print("测试：考虑字符宽度")
    print("=" * 60)

    # 这是正确的行为：
    # "你好！" 显示宽度 = 2 + 2 + 1 = 5
    # 应该覆盖前5个字符位置

    # 原始文本：( · Thinking)
    # 位置：    0123456789...
    #
    # 覆盖后应该是：
    # 你好！inking)
    # 位置：01234567...

    print("当前行为：'你好！' 只覆盖 3 个字符位置")
    print("期望行为：'你好！' 应该覆盖 5 个字符位置（考虑显示宽度）")
    print("=" * 60)


if __name__ == "__main__":
    test_cjk_width()
    test_with_width_aware()
