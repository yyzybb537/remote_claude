"""
终端渲染器 - 使用 pyte 正确模拟终端显示
"""

import pyte


class TerminalRenderer:
    """使用 pyte 模拟终端，获取真实的显示内容"""

    def __init__(self, columns: int = 200, lines: int = 100):
        self.screen = pyte.Screen(columns, lines)
        self.stream = pyte.Stream(self.screen)
        self.stream.use_utf8 = True

    def feed(self, data: bytes) -> None:
        """喂入原始终端数据"""
        text = data.decode('utf-8', errors='replace')
        self.stream.feed(text)

    def get_display(self) -> str:
        """获取当前终端显示内容"""
        lines = []
        for line in self.screen.display:
            stripped = line.rstrip()
            if stripped:  # 只保留非空行
                lines.append(stripped)

        return '\n'.join(lines)

    def get_full_display(self) -> str:
        """获取完整的终端显示（包括空行，用于调试）"""
        lines = []
        for i, line in enumerate(self.screen.display):
            stripped = line.rstrip()
            if stripped:
                lines.append(f"{i:3d}: {stripped}")
        return '\n'.join(lines)

    def clear(self) -> None:
        """清空终端"""
        self.screen.reset()


def test_renderer():
    """测试渲染器"""
    renderer = TerminalRenderer()

    # 使用之前捕获的真实输出
    raw_outputs = [
        b'\x1b[?2026h\x1b[2K\x1b[G\x1b[1A\r\x1b[2C\x1b[2Ahello\r\x1b[2B',
        b'\x1b]0;\xe2\x9c\xb3 Greeting\x07',
        b'\x1b[?2026h\r\x1b[3A\x1b[48;2;55;55;55m\x1b[38;2;80;80;80m\xe2\x9d\xaf \x1b[38;2;255;255;255mhello \x1b[39m\x1b[49m',
        b'\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\r\n\x1b[39m\x1b[22m  \x1b[38;2;153;153;153m? for shortcuts\x1b[39m',
        b'\x1b[?2026h\r\x1b[6A\x1b[38;2;255;255;255m\xe2\x8f\xba\x1b[1C\x1b[39m\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe6\x9c\x89\xe4\xbb\x80\xe4\xb9\x88\xe5\x8f\xaf\xe4\xbb\xa5\xe5\xb8\xae\xe4\xbd\xa0\xe7\x9a\x84\xe5\x90\x97\xef\xbc\x9f',
    ]

    for data in raw_outputs:
        renderer.feed(data)

    result = renderer.get_display()
    print("终端显示内容:")
    print("=" * 60)
    print(result)
    print("=" * 60)


if __name__ == "__main__":
    test_renderer()
