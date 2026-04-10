"""
Claude CLI 输出清理器

策略：不模拟终端，直接从原始输出中提取有意义的文本
"""

import re
from typing import List


class OutputCleaner:
    """Claude CLI 输出清理器"""

    def __init__(self):
        self._buffer = b""
        self._last_meaningful_content = ""
        self._user_input = ""

    def feed(self, data: bytes) -> None:
        """喂入原始输出数据"""
        self._buffer += data

    def set_user_input(self, text: str) -> None:
        """设置用户输入（用于过滤回显）"""
        self._user_input = text.strip()

    def get_response(self) -> str:
        """获取清理后的响应内容"""
        text = self._buffer.decode('utf-8', errors='replace')
        return self._extract_response(text)

    def clear(self) -> None:
        """清空缓冲区"""
        self._buffer = b""
        self._last_meaningful_content = ""

    def _extract_response(self, text: str) -> str:
        """从原始输出中提取 Claude 的回复"""
        # 1. 移除所有 ANSI 转义序列
        text = self._strip_ansi(text)

        # 2. 移除所有控制字符（保留换行和空格）
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

        # 3. 处理换行
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # 4. 提取有意义的内容
        lines = text.split('\n')
        meaningful_lines = []

        for line in lines:
            cleaned = self._clean_line(line)
            if cleaned:
                meaningful_lines.append(cleaned)

        # 5. 去重并合并
        result = self._deduplicate_lines(meaningful_lines)

        return result

    def _strip_ansi(self, text: str) -> str:
        """移除所有 ANSI 转义序列"""
        # CSI 序列: ESC [ ... 字母
        text = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', text)
        # OSC 序列: ESC ] ... BEL 或 ST (ESC \)
        text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
        # 其他转义序列
        text = re.sub(r'\x1b[^[\]a-zA-Z]*[a-zA-Z]', '', text)
        return text

    def _clean_line(self, line: str) -> str:
        """清理单行内容"""
        stripped = line.strip()

        if not stripped:
            return ""

        # 跳过边框和分隔线
        if all(c in '─━═-–—│╭╮╰╯┌┐└┘├┤┬┴┼ ' for c in stripped):
            return ""
        if stripped.startswith(('╭', '╰', '│', '┌', '└', '├')):
            return ""

        # 跳过界面元素
        skip_patterns = [
            r'^Welcome to',
            r'^Welcome back',
            r'^Try\s*"',
            r'esc to',
            r'for shortcuts',
            r'^\?.*shortcuts',
            r'· thinking',
            r'· Thinking',
        ]
        for pattern in skip_patterns:
            if re.search(pattern, stripped, re.IGNORECASE):
                return ""

        # 跳过动画文本
        animation_words = ['evaporating', 'seasoning', 'fiddling', 'symbioting', 'thinking']
        stripped_lower = stripped.lower()
        for word in animation_words:
            # 只跳过完整包含动画词的行
            if word in stripped_lower and len(stripped) < 50:
                return ""

        # 跳过特殊符号行
        if stripped in ['❯', '>', '$', '⏺', '·', '( )', ';', '()', '( · )', '( ·', '✻', '✳']:
            return ""
        if all(c in '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠐⠂✻✳ ' for c in stripped):
            return ""

        # 跳过状态标签
        if stripped in ['问候', 'Basic Math', 'Greeting', 'Code', 'Analysis', 'Initial Greeting']:
            return ""

        # 跳过命令提示符行
        if stripped.startswith('❯') or stripped.startswith('>'):
            return ""

        # 跳过包含大量 ─ 的行（分隔线）
        if '─' in stripped and stripped.count('─') > 3:
            return ""

        # 跳过短的无意义行（动画碎片）
        if len(stripped) <= 3 and not self._has_cjk(stripped):
            return ""

        # 跳过只有 ... 或省略号的行
        if stripped in ['…', '...', '..', '.']:
            return ""

        # 跳过用户输入回显
        if self._user_input and stripped == self._user_input:
            return ""

        # 提取⏺符号后的内容（这通常是 Claude 的实际回复）
        if '⏺' in stripped:
            parts = stripped.split('⏺', 1)
            if len(parts) > 1:
                return parts[1].strip()

        return stripped

    def _has_cjk(self, text: str) -> bool:
        """检查是否包含中日韩字符"""
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return True
            if '\u3040' <= char <= '\u30ff':
                return True
            if '\uac00' <= char <= '\ud7a3':
                return True
        return False

    def _deduplicate_lines(self, lines: List[str]) -> str:
        """去除重复行"""
        if not lines:
            return ""

        # 去除连续重复
        deduped = [lines[0]]
        for line in lines[1:]:
            if line != deduped[-1]:
                deduped.append(line)

        # 合并结果
        result = '\n'.join(deduped)

        # 清理多余空白
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = re.sub(r' {2,}', ' ', result)

        return result.strip()


def test_cleaner():
    """测试清理器"""
    cleaner = OutputCleaner()
    cleaner.set_user_input("hello")

    # 模拟真实捕获的输出
    raw_outputs = [
        b'\x1b[?2026h\x1b[2K\x1b[G\x1b[1A\r\x1b[2C\x1b[2Ahello\r\x1b[2B',
        b'\x1b]0;\xe2\x9c\xb3 Greeting\x07',
        b'\x1b[?2026h\r\x1b[3A\x1b[48;2;55;55;55m\x1b[38;2;80;80;80m\xe2\x9d\xaf \x1b[38;2;255;255;255mhello \x1b[39m\x1b[49m',
        b'\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\r\n\x1b[39m\x1b[22m  \x1b[38;2;153;153;153m? for shortcuts\x1b[39m',
        b'\x1b[?2026h\r\x1b[6A\x1b[38;2;255;255;255m\xe2\x8f\xba\x1b[1C\x1b[39m\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe6\x9c\x89\xe4\xbb\x80\xe4\xb9\x88\xe5\x8f\xaf\xe4\xbb\xa5\xe5\xb8\xae\xe4\xbd\xa0\xe7\x9a\x84\xe5\x90\x97\xef\xbc\x9f',
    ]

    for data in raw_outputs:
        cleaner.feed(data)

    result = cleaner.get_response()
    print(f"清理后的响应:\n'{result}'")
    print()

    # 验证
    errors = []
    if "你好！有什么可以帮你的吗？" not in result:
        errors.append(f"期望包含回复")
    if "shortcuts" in result:
        errors.append(f"不应包含 'shortcuts'")
    if "hello" in result.lower():
        errors.append(f"不应包含用户输入 'hello'")
    if "❯" in result:
        errors.append(f"不应包含命令提示符 '❯'")
    if "─" in result:
        errors.append(f"不应包含分隔线")

    if errors:
        print("✗ 测试失败:")
        for e in errors:
            print(f"  - {e}")
        print(f"实际结果: '{result}'")
    else:
        print("✓ 测试通过")


if __name__ == "__main__":
    test_cleaner()
