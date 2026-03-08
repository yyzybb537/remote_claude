"""
终端输出缓冲器 - 正确处理回退和覆盖
"""

import re
from typing import List


class TerminalBuffer:
    """
    模拟终端缓冲区，正确处理回退字符和覆盖

    终端动画原理：
    - \r (carriage return) 回到行首
    - \x1b[K 清除到行尾
    - \x1b[2K 清除整行
    - 动画通过重复 \r + 新内容 实现
    """

    def __init__(self):
        self.lines: List[str] = [""]  # 当前屏幕内容（按行存储）
        self.cursor_line = 0  # 光标所在行
        self.cursor_col = 0   # 光标所在列

    def write(self, data: str) -> None:
        """写入数据到缓冲区"""
        # 先移除 ANSI 转义码（颜色等）但保留控制字符
        data = self._strip_ansi_colors(data)

        i = 0
        while i < len(data):
            char = data[i]

            if char == '\r':
                # 回车：回到行首
                self.cursor_col = 0
            elif char == '\n':
                # 换行：移动到下一行
                self._new_line()
            elif char == '\x1b':
                # 转义序列
                seq_len = self._handle_escape_sequence(data[i:])
                i += seq_len - 1  # -1 因为循环会 +1
            elif ord(char) >= 32 or char == '\t':
                # 可打印字符或制表符
                self._write_char(char)

            i += 1

    def _strip_ansi_colors(self, data: str) -> str:
        """移除 ANSI 颜色码，但保留控制序列"""
        # 移除颜色码 (SGR)
        data = re.sub(r'\x1b\[[0-9;]*m', '', data)
        # 移除私有模式设置
        data = re.sub(r'\x1b\[\?[0-9]+[hl]', '', data)
        return data

    def _handle_escape_sequence(self, data: str) -> int:
        """处理转义序列，返回序列长度"""
        if len(data) < 2:
            return 1

        if data[1] == '[':
            # CSI 序列
            match = re.match(r'\x1b\[([0-9;]*)([A-Za-z])', data)
            if match:
                params = match.group(1)
                cmd = match.group(2)
                self._handle_csi(params, cmd)
                return len(match.group(0))

        return 1

    def _handle_csi(self, params: str, cmd: str) -> None:
        """处理 CSI 命令"""
        n = int(params) if params.isdigit() else 1

        if cmd == 'A':  # 光标上移
            self.cursor_line = max(0, self.cursor_line - n)
        elif cmd == 'B':  # 光标下移
            self.cursor_line = min(len(self.lines) - 1, self.cursor_line + n)
        elif cmd == 'C':  # 光标右移
            self.cursor_col += n
        elif cmd == 'D':  # 光标左移
            self.cursor_col = max(0, self.cursor_col - n)
        elif cmd == 'K':  # 清除行
            if params == '' or params == '0':
                # 清除光标到行尾
                if self.cursor_line < len(self.lines):
                    self.lines[self.cursor_line] = self.lines[self.cursor_line][:self.cursor_col]
            elif params == '1':
                # 清除行首到光标
                if self.cursor_line < len(self.lines):
                    line = self.lines[self.cursor_line]
                    self.lines[self.cursor_line] = ' ' * self.cursor_col + line[self.cursor_col:]
            elif params == '2':
                # 清除整行
                if self.cursor_line < len(self.lines):
                    self.lines[self.cursor_line] = ''
        elif cmd == 'J':  # 清除屏幕
            if params == '2':
                self.lines = [""]
                self.cursor_line = 0
                self.cursor_col = 0
        elif cmd == 'G':  # 光标移动到列
            self.cursor_col = max(0, n - 1)

    def _new_line(self) -> None:
        """换行"""
        self.cursor_line += 1
        self.cursor_col = 0
        while len(self.lines) <= self.cursor_line:
            self.lines.append("")

    def _write_char(self, char: str) -> None:
        """写入一个字符"""
        # 确保行存在
        while len(self.lines) <= self.cursor_line:
            self.lines.append("")

        line = self.lines[self.cursor_line]

        # 如果光标位置超出当前行长度，用空格填充
        if self.cursor_col >= len(line):
            line = line + ' ' * (self.cursor_col - len(line)) + char
        else:
            # 覆盖现有字符
            line = line[:self.cursor_col] + char + line[self.cursor_col + 1:]

        self.lines[self.cursor_line] = line
        self.cursor_col += 1

    def get_content(self) -> str:
        """获取当前缓冲区内容"""
        # 合并所有行，移除尾部空行
        result = []
        for line in self.lines:
            # 移除行尾空格
            result.append(line.rstrip())

        # 移除尾部空行
        while result and not result[-1]:
            result.pop()

        return '\n'.join(result)

    def clear(self) -> None:
        """清空缓冲区"""
        self.lines = [""]
        self.cursor_line = 0
        self.cursor_col = 0


def clean_terminal_output(raw_data: bytes, user_input: str = "") -> str:
    """
    清理终端输出，正确处理回退和覆盖

    Args:
        raw_data: 原始终端输出
        user_input: 用户输入（用于过滤回显）

    Returns:
        清理后的文本
    """
    text = raw_data.decode('utf-8', errors='replace')

    # 使用终端缓冲器处理
    buffer = TerminalBuffer()
    buffer.write(text)
    content = buffer.get_content()

    # 后处理：移除 Claude CLI 界面元素
    lines = content.split('\n')
    clean_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 跳过边框和分隔线
        if all(c in '─━═-–—│╭╮╰╯┌┐└┘├┤┬┴┼ ' for c in stripped):
            continue
        if stripped.startswith(('╭', '╰', '│', '┌', '└', '├')):
            continue

        # 跳过界面元素
        if any(x in stripped for x in ['Welcome to', 'Welcome back']):
            continue
        if re.match(r'^Try\s*"', stripped):
            continue

        # 跳过动画文本
        if any(x in stripped.lower() for x in ['evaporating', 'seasoning', 'fiddling', 'thinking']):
            continue

        # 跳过特殊符号行
        if stripped in ['❯', '>', '$', '⏺', '·', '( )', ';', '()']:
            continue

        # 跳过状态标签
        if stripped in ['问候', 'Basic Math', 'Greeting', 'Code', 'Analysis']:
            continue

        # 跳过用户输入回显
        if user_input and stripped == user_input:
            continue

        # 跳过 esc 提示
        if 'esc to' in stripped.lower():
            continue

        clean_lines.append(stripped)

    return '\n'.join(clean_lines).strip()
