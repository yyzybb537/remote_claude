"""
富文本渲染器 - 将终端 ANSI 样式转换为飞书卡片富文本

飞书卡片 Markdown 支持：
- **粗体**
- *斜体*
- ~~删除线~~
- `代码`
- <font color="red">颜色文本</font>
- 链接 [text](url)
"""

import codecs
import logging
import pyte
from pyte.screens import Margins
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ANSI 颜色名称到飞书颜色的映射
# 飞书 Markdown 只支持: green, red, grey 三种颜色
ANSI_TO_LARK_COLOR = {
    'black': 'grey',
    'red': 'red',
    'green': 'green',
    'yellow': None,  # 飞书不支持黄色，用默认色
    'brown': None,   # pyte 把 ANSI 33 解析为 brown
    'blue': None,    # 飞书不支持蓝色
    'magenta': 'red',  # 用红色替代
    'cyan': 'green',   # 用绿色替代
    'white': None,  # 默认颜色
    'default': None,
    # 亮色系
    'brightblack': 'grey',
    'brightred': 'red',
    'brightgreen': 'green',
    'brightyellow': None,
    'brightblue': None,
    'brightmagenta': 'red',
    'brightcyan': 'green',
    'brightwhite': None,
    # 灰色系
    'grey': 'grey',
    'gray': 'grey',
}


@dataclass
class StyledSpan:
    """带样式的文本片段"""
    text: str
    fg_color: Optional[str] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False


class _ExtendedStream(pyte.Stream):
    """pyte.Stream 子类：补充 SU（ESC[nS）和 SD（ESC[nT）支持。

    pyte 原生 CSI dispatch 不包含 'S' 和 'T'，Codex 的 ESC[2S 会被完全忽略。
    """
    csi = {**pyte.Stream.csi, 'S': 'scroll_up', 'T': 'scroll_down'}


class _DebugStream(_ExtendedStream):
    """_ExtendedStream 子类：记录被 pyte 丢弃的未识别转义序列到 DEBUG 日志。

    仅在 --debug-screen 开启时使用，替换默认 _ExtendedStream。
    """
    _undef_logger = logging.getLogger('pyte.Stream.undefined')

    def _undefined(self, *args, **kwargs):
        self._undef_logger.debug(f"pyte 未识别序列: args={args!r} kwargs={kwargs!r}")


class _DimAwareScreen(pyte.HistoryScreen):
    """pyte.HistoryScreen 子类：
    1. SGR 2 (dim/faint) 映射为灰色前景
    2. 补充 SU/SD（ESC[nS/ESC[nT）滚动支持，滚出行保存到 history.top
    """

    # dim 状态下使用的灰色（与终端 dim 效果近似）
    _DIM_FG = '808080'
    _DEFAULT_HISTORY = 800

    def __init__(self, columns, lines, **kwargs):
        kwargs.setdefault('history', self._DEFAULT_HISTORY)
        super().__init__(columns, lines, **kwargs)

    def select_graphic_rendition(self, *attrs):
        # 检查是否包含 SGR 2 (dim)
        has_dim = 2 in attrs
        # 过滤掉 2，让父类处理其余属性（父类不认识 2 会忽略）
        super().select_graphic_rendition(*attrs)
        # dim 且前景仍为 default → 映射为灰色
        if has_dim and self.cursor.attrs.fg == 'default':
            self.cursor.attrs = self.cursor.attrs._replace(fg=self._DIM_FG)

    def scroll_up(self, count=1):
        """ESC[nS — SU：上滚 n 行，滚出行保存到 history.top"""
        top, bottom = self.margins or Margins(0, self.lines - 1)
        saved_y = self.cursor.y
        self.cursor.y = bottom
        for _ in range(count):
            self.index()
        self.cursor.y = saved_y

    def scroll_down(self, count=1):
        """ESC[nT — SD：下滚 n 行"""
        top, bottom = self.margins or Margins(0, self.lines - 1)
        saved_y = self.cursor.y
        self.cursor.y = top
        for _ in range(count):
            self.reverse_index()
        self.cursor.y = saved_y


class RichTextRenderer:
    """将 pyte 屏幕内容转换为飞书富文本"""

    def __init__(self, columns: int = 200, lines: int = 500,
                 history_limit: int = _DimAwareScreen._DEFAULT_HISTORY,
                 debug_stream: bool = False):
        self.screen = _DimAwareScreen(columns, lines, history=history_limit)
        # debug_stream=True 时使用 _DebugStream，记录 pyte 未识别序列
        if debug_stream:
            self.stream = _DebugStream(self.screen)
        else:
            self.stream = _ExtendedStream(self.screen)
        self.stream.use_utf8 = True
        # 增量 UTF-8 解码器：保持跨 chunk 的解码状态，防止多字节序列被截断
        self._utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    def feed(self, data: bytes) -> None:
        """喂入原始终端数据"""
        text = self._utf8_decoder.decode(data)
        # 改动4：检测 UTF-8 解码产生的替换字符（U+FFFD），说明原始字节流有非法序列
        if '\ufffd' in text:
            # 定位替换字符位置（最多报告前 5 处）
            positions = [i for i, c in enumerate(text) if c == '\ufffd'][:5]
            contexts = []
            for pos in positions:
                ctx_start = max(0, pos - 4)
                ctx_end = min(len(text), pos + 5)
                ctx = repr(text[ctx_start:ctx_end])
                contexts.append(f"pos={pos} ctx={ctx}")
            logger.warning(f"UTF-8 解码替换字符(\\ufffd): count={text.count(chr(0xfffd))} "
                           f"positions={contexts}")
        self.stream.feed(text)

    def clear(self) -> None:
        """清空终端"""
        self.screen.reset()
        # 同时重置增量解码器状态
        self._utf8_decoder.reset()

    def get_plain_display(self) -> str:
        """获取纯文本显示（不含样式）"""
        lines = []
        for line in self.screen.display:
            stripped = line.rstrip()
            if stripped:
                lines.append(stripped)
        return '\n'.join(lines)

    def get_rich_text(self) -> str:
        """获取富文本格式的内容（飞书 Markdown）"""
        result_lines = []

        for row_idx in range(self.screen.lines):
            line_spans = self._get_line_spans(row_idx)
            if not line_spans:
                continue

            # 检查是否整行都是空白
            line_text = ''.join(span.text for span in line_spans)
            if not line_text.strip():
                continue

            # 计算缩进（前导空格数量）
            indent = 0
            for span in line_spans:
                if span.text.strip():
                    # 找到第一个非空白 span，计算其前导空格
                    indent += len(span.text) - len(span.text.lstrip())
                    break
                else:
                    # 纯空白 span，累加长度
                    indent += len(span.text)

            # 清理前导空白 span
            while line_spans and not line_spans[0].text.strip():
                line_spans.pop(0)

            # 去掉第一个 span 的前导空格（稍后统一添加缩进）
            if line_spans and line_spans[0].text:
                line_spans[0].text = line_spans[0].text.lstrip()

            # 转换为飞书 Markdown，并添加缩进
            md_line = self._spans_to_markdown(line_spans)
            if indent > 0:
                # 使用全角空格保持缩进（飞书会压缩半角空格）
                md_line = '\u3000' * (indent // 2) + ' ' * (indent % 2) + md_line
            if md_line.strip():
                # 行尾加两个空格，让 Markdown 强制换行
                result_lines.append(md_line + '  ')

        return '\n'.join(result_lines)

    def _get_line_spans(self, row_idx: int) -> List[StyledSpan]:
        """获取一行的样式片段"""
        row = self.screen.buffer[row_idx]
        spans = []
        current_span = None

        for col in range(self.screen.columns):
            char = row[col]
            char_data = char.data if hasattr(char, 'data') else ' '

            # 获取样式
            fg = getattr(char, 'fg', 'default')
            bold = getattr(char, 'bold', False)
            italic = getattr(char, 'italics', False)
            underline = getattr(char, 'underscore', False)
            strikethrough = getattr(char, 'strikethrough', False)

            # 转换颜色
            lark_color = self._convert_color(fg)

            # 检查是否需要新的 span
            if current_span is None:
                current_span = StyledSpan(
                    text=char_data,
                    fg_color=lark_color,
                    bold=bold,
                    italic=italic,
                    underline=underline,
                    strikethrough=strikethrough
                )
            elif (current_span.fg_color == lark_color and
                  current_span.bold == bold and
                  current_span.italic == italic and
                  current_span.underline == underline and
                  current_span.strikethrough == strikethrough):
                # 样式相同，追加文本
                current_span.text += char_data
            else:
                # 样式变化，保存当前 span 并开始新的
                if current_span.text:
                    spans.append(current_span)
                current_span = StyledSpan(
                    text=char_data,
                    fg_color=lark_color,
                    bold=bold,
                    italic=italic,
                    underline=underline,
                    strikethrough=strikethrough
                )

        # 添加最后一个 span
        if current_span and current_span.text:
            spans.append(current_span)

        # 清理尾部空白
        while spans and not spans[-1].text.rstrip():
            spans.pop()

        if spans:
            spans[-1].text = spans[-1].text.rstrip()

        return spans

    def _convert_color(self, ansi_color: str) -> Optional[str]:
        """将 ANSI 颜色转换为飞书颜色"""
        if not ansi_color:
            return None

        color = str(ansi_color).lower().replace('-', '')
        return ANSI_TO_LARK_COLOR.get(color)

    def _escape_markdown(self, text: str) -> str:
        """转义 markdown 特殊字符"""
        # 飞书 markdown 中需要转义的字符
        for char in ['*', '_', '~', '`']:
            text = text.replace(char, '\\' + char)
        return text

    def _spans_to_markdown(self, spans: List[StyledSpan]) -> str:
        """将样式片段转换为飞书 Markdown"""
        result = []

        for span in spans:
            text = span.text
            if not text:
                continue

            # 应用样式（从内到外）
            styled_text = text

            # 粗体
            if span.bold:
                styled_text = f'**{styled_text}**'

            # 斜体
            if span.italic:
                styled_text = f'*{styled_text}*'

            # 删除线
            if span.strikethrough:
                styled_text = f'~~{styled_text}~~'

            # 颜色：需要转义 markdown 特殊字符
            if span.fg_color:
                escaped_text = self._escape_markdown(styled_text)
                styled_text = f'<font color="{span.fg_color}">{escaped_text}</font>'

            result.append(styled_text)

        return ''.join(result)

    def get_display_for_lark(self, user_input: str = "") -> Tuple[str, str]:
        """
        获取适合飞书显示的内容

        返回: (plain_text, rich_markdown)
        """
        plain = self.get_plain_display()
        rich = self.get_rich_text()
        return plain, rich


def test_renderer():
    """测试渲染器"""
    renderer = RichTextRenderer(80, 24)

    # 模拟 Claude 的输出
    test_data = (
        # 红色错误
        b'\x1b[31mError: Something went wrong\x1b[0m\n'
        # 绿色成功
        b'\x1b[32mSuccess!\x1b[0m\n'
        # 粗体黄色警告
        b'\x1b[1;33mWarning: Be careful\x1b[0m\n'
        # 蓝色信息
        b'\x1b[34mInfo: Normal message\x1b[0m\n'
        # 代码块提示
        b'```python\n'
        b'def hello():\n'
        b'    print("Hello, World!")\n'
        b'```\n'
    )

    renderer.feed(test_data)

    print("=== 纯文本 ===")
    print(renderer.get_plain_display())
    print()
    print("=== 富文本 Markdown ===")
    print(renderer.get_rich_text())


if __name__ == "__main__":
    test_renderer()
