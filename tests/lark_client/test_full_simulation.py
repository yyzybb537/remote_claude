"""
完整模拟测试 - 使用真实捕获的 Claude CLI 输出
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lark_client.terminal_renderer import TerminalRenderer


def test_with_real_captured_output():
    """使用之前捕获的真实输出测试"""
    print("=" * 60)
    print("测试：使用真实捕获的 Claude CLI 输出")
    print("=" * 60)

    renderer = TerminalRenderer()

    # 这是从 capture_output.py 捕获的真实输出序列
    raw_outputs = [
        b'\x1b[?2026h\x1b[2K\x1b[G\x1b[1A\r\x1b[2C\x1b[2Ahello\r\x1b[2B                                                              ',
        b'\x1b]0;\xe2\x9c\xb3 Greeting\x07',
        b'\x1b[?2026h\r\x1b[3A\x1b[48;2;55;55;55m\x1b[38;2;80;80;80m\xe2\x9d\xaf \x1b[38;2;255;255;255mhello \x1b[39m\x1b[49m                ',
        b'\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\r\n\x1b[39m\x1b[22m  \x1b[38;2;153;153;153m? for shortcuts\x1b[39m                       ',
        # 动画帧
        b'\x1b[?2026h\r\x1b[11C\x1b[6A\x1b[38;2;215;119;87mg\xe2\x80\xa6\x1b[39m\r\r\n\r\n\r\n\r\n\r\n\r\n\x1b[?2026l',
        b'\x1b[?2026h\r\x1b[6A\x1b[38;2;215;119;87m\xe2\x9c\xbb\x1b[39m\r\r\n\r\n\r\n\r\n\r\n\r\n\x1b[?2026l',
        b'\x1b[?2026h\r\x1b[2C\x1b[6A\x1b[38;2;235;159;127mSy\x1b[39m\r\r\n\r\n\r\n\r\n\r\n\r\n\x1b[?2026l',
        b'\x1b[?2026h\r\x1b[2C\x1b[6A\x1b[38;2;215;119;87mS\x1b[1C\x1b[38;2;235;159;127mmb\x1b[39m\r\r\n\r\n\r\n\r\n\r\n\r\n\x1b[?2026l',
        # 更多动画帧...
        b'\x1b[?2026h\r\x1b[31C\x1b[6A\x1b[38;2;153;153;153m \xc2\xb7 thinking)\x1b[39m\r\r\n\r\n\r\n\r\n\r\n\r\n\x1b[?2026l',
        # 最终响应
        b'\x1b[?2026h\r\x1b[6A\x1b[38;2;255;255;255m\xe2\x8f\xba\x1b[1C\x1b[39m\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe6\x9c\x89\xe4\xbb\x80\xe4\xb9\x88\xe5\x8f\xaf\xe4\xbb\xa5\xe5\xb8\xae\xe4\xbd\xa0\xe7\x9a\x84\xe5\x90\x97\xef\xbc\x9f               \r\x1b',
    ]

    for i, data in enumerate(raw_outputs):
        renderer.feed(data)
        print(f"步骤 {i+1}: 喂入 {len(data)} 字节")

    print("\n最终终端显示:")
    print("-" * 60)
    display = renderer.get_display()
    print(display)
    print("-" * 60)

    # 简单清理
    def clean_display(text):
        lines = text.split('\n')
        clean = []
        for line in lines:
            if '? for shortcuts' in line:
                continue
            if 'esc to' in line.lower():
                continue
            clean.append(line)
        return '\n'.join(clean).strip()

    cleaned = clean_display(display)
    print("\n清理后:")
    print("-" * 60)
    print(cleaned)
    print("-" * 60)

    # 验证
    if "你好！有什么可以帮你的吗？" in cleaned:
        print("\n✓ 包含正确的回复")
    else:
        print("\n✗ 未找到回复")

    print("=" * 60)


def test_multiple_rounds():
    """测试多轮对话"""
    print("\n" + "=" * 60)
    print("测试：模拟多轮对话")
    print("=" * 60)

    renderer = TerminalRenderer()

    # 第一轮
    print("\n--- 第一轮：用户输入 'hello' ---")
    first_round = [
        b'\x1b[?2026h\x1b[2K\x1b[G\x1b[1A\r\x1b[2C\x1b[2Ahello\r\x1b[2B',
        b'\x1b[?2026h\r\x1b[6A\x1b[38;2;255;255;255m\xe2\x8f\xba\x1b[1C\x1b[39m\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81',
    ]
    for data in first_round:
        renderer.feed(data)

    print(f"显示: {renderer.get_display()}")

    # 清空准备第二轮
    renderer.clear()

    # 第二轮
    print("\n--- 第二轮：用户输入 '1+1=?' ---")
    second_round = [
        b'\x1b[?2026h\x1b[2K\x1b[G\x1b[1A\r\x1b[2C\x1b[2A1+1=?\r\x1b[2B',
        b'\x1b[?2026h\r\x1b[6A\x1b[38;2;255;255;255m\xe2\x8f\xba\x1b[1C\x1b[39m1+1=2',
    ]
    for data in second_round:
        renderer.feed(data)

    print(f"显示: {renderer.get_display()}")

    print("\n✓ 多轮对话测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_with_real_captured_output()
    test_multiple_rounds()
