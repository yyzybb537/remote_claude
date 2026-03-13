"""Codex CLI 输出组件解析器

独立解析器，专门处理 Codex CLI 的终端输出格式。与 ClaudeParser 的关键差异：
  - STAR_CHARS：不使用星星字符，StatusLine 改为 DOT_CHARS blink 检测
  - 用户输入指示符：`›` (U+203A) / `>` (U+003E)，与 ClaudeParser 的 `❯` 不同
  - 区域分割：无 ─━═ 字符分割线，用背景色区域（连续 bg 行 + 首尾纯背景色边界）识别输入区域
  - 欢迎框：`>_ OpenAI Codex` + `model:` + `directory:` 特征，无固定行号
  - 选项交互：编号选项 + Enter/Esc 导航提示，通过提示符颜色和上方签名区分普通/选项模式
"""

import re
import logging
import time
from collections import deque
from typing import List, Optional, Dict, Tuple, Set

import pyte

from utils.components import (
    Component, OutputBlock, UserInput, OptionBlock, StatusLine, BottomBar, AgentPanelBlock, PlanBlock, SystemBlock,
)

from .base_parser import BaseParser

logger = logging.getLogger('ComponentParser')

# 星星字符集（状态行首列）
STAR_CHARS: Set[str] = set(
    '✱✶✷✸✹✺✻✼✽✾✿✰✲✳✴✵'
    '❂❃❄❅❆❇'
    '✢✣✤✥✦✧'
    '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    '△'    # Codex 系统警告（不闪烁 → SystemBlock）
    '⚠'    # Codex 警告（不闪烁 → SystemBlock）
    '■'    # Codex 错误提示（不闪烁 → SystemBlock）
)

# 圆点字符集（OutputBlock 首列）
DOT_CHARS: Set[str] = {'●', '⏺', '⚫', '•', '◉', '◦', '⏹'}

# 分割线字符集
DIVIDER_CHARS: Set[str] = set('─━═')

# Codex 输入提示符字符集（› U+203A 是实际使用的字符，> U+003E 兼容保留）
CODEX_PROMPT_CHARS: Set[str] = {'›', '>'}

# Box-drawing 字符集（Plan Mode 使用的框线字符）
BOX_CORNER_TOP: Set[str] = {'╭', '┌'}
BOX_CORNER_BOTTOM: Set[str] = {'╰', '└'}
BOX_VERTICAL: Set[str] = {'│', '┃', '║'}

# OutputBlock 内嵌框线清理（纯文本版，用于 content 检测）
_INLINE_BOX_TOP_RE = re.compile(r'^\s*[╭┌][─━═╌]+[╮┐]\s*$')
_INLINE_BOX_BOTTOM_RE = re.compile(r'^\s*[╰└][─━═╌]+[╯┘]\s*$')
_INLINE_BOX_LEFT_RE = re.compile(r'^(\s*)[│┃║] ?')
_INLINE_BOX_RIGHT_RE = re.compile(r'\s*[│┃║]\s*$')

# ANSI 版（用于 ansi_content 清理）
_A = r'(?:\x1b\[[\d;]*m)*'
_ANSI_BOX_LEFT_RE = re.compile(rf'^({_A}\s*){_A}[│┃║]{_A} ?')
_ANSI_BOX_RIGHT_RE = re.compile(rf'\s*{_A}[│┃║]{_A}\s*$')


def _strip_inline_boxes_pair(content: str, ansi_content: str) -> tuple:
    """去除 OutputBlock 内嵌的 box-drawing 框线，同步清理 content 和 ansi_content。

    仅在检测到完整 box（顶边框 + 底边框配对）时才去除，防止误伤普通 │ 内容。
    返回 (cleaned_content, cleaned_ansi_content)。
    """
    lines = content.split('\n')
    top_stack: list = []
    box_ranges: list = []
    for i, line in enumerate(lines):
        if _INLINE_BOX_TOP_RE.match(line):
            top_stack.append(i)
        elif _INLINE_BOX_BOTTOM_RE.match(line) and top_stack:
            top_idx = top_stack.pop()
            box_ranges.append((top_idx, i))

    if not box_ranges:
        return content, ansi_content

    ansi_lines = ansi_content.split('\n')
    if len(ansi_lines) != len(lines):
        return content, ansi_content

    remove_lines: set = set()
    side_lines: set = set()
    for top_idx, bottom_idx in box_ranges:
        remove_lines.add(top_idx)
        remove_lines.add(bottom_idx)
        for j in range(top_idx + 1, bottom_idx):
            side_lines.add(j)

    result_content = []
    result_ansi = []
    for i, (line, aline) in enumerate(zip(lines, ansi_lines)):
        if i in remove_lines:
            continue
        if i in side_lines:
            line = _INLINE_BOX_LEFT_RE.sub(r'\1', line)
            line = _INLINE_BOX_RIGHT_RE.sub('', line)
            aline = _ANSI_BOX_LEFT_RE.sub(r'\1', aline)
            aline = _ANSI_BOX_RIGHT_RE.sub('', aline)
        result_content.append(line)
        result_ansi.append(aline)

    return '\n'.join(result_content), '\n'.join(result_ansi)


# 编号选项行正则（权限确认对话框特征：> 1. Yes / 2. No 等）
_NUMBERED_OPTION_RE = re.compile(r'^(?:[>❯›]\s*)?\d+[.)]\s+.+')
# 带 > / ❯ / › 光标的编号选项行正则（锚点）
_CURSOR_OPTION_RE = re.compile(r'^[>❯›]\s*(\d+)[.)]\s+.+')

# Codex 状态行检测（首列 ● blink=True + 内容含 "esc to interrupt"）


# ─── ANSI 颜色映射 ─────────────────────────────────────────────────────────────

# pyte 颜色名 → ANSI SGR 前景色代码
_FG_NAME_TO_SGR: Dict[str, int] = {
    'black': 30, 'red': 31, 'green': 32, 'brown': 33, 'yellow': 33,
    'blue': 34, 'magenta': 35, 'cyan': 36, 'white': 37,
    'brightblack': 90, 'brightred': 91, 'brightgreen': 92, 'brightyellow': 93,
    'brightblue': 94, 'brightmagenta': 95, 'brightcyan': 96, 'brightwhite': 97,
}

# pyte 颜色名 → ANSI SGR 背景色代码
_BG_NAME_TO_SGR: Dict[str, int] = {
    'black': 40, 'red': 41, 'green': 42, 'brown': 43, 'yellow': 43,
    'blue': 44, 'magenta': 45, 'cyan': 46, 'white': 47,
    'brightblack': 100, 'brightred': 101, 'brightgreen': 102, 'brightyellow': 103,
    'brightblue': 104, 'brightmagenta': 105, 'brightcyan': 106, 'brightwhite': 107,
}


def _fg_sgr(color: str) -> Optional[str]:
    """pyte 前景色 → ANSI SGR 序列片段（不含 \\x1b[...m 外壳）"""
    if not color or color == 'default':
        return None
    # 颜色名
    key = color.lower().replace(' ', '').replace('-', '')
    if key in _FG_NAME_TO_SGR:
        return str(_FG_NAME_TO_SGR[key])
    # 6 位 hex（256 色或真彩色）
    if len(color) == 6:
        try:
            r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
            return f'38;2;{r};{g};{b}'
        except ValueError:
            pass
    return None


def _bg_sgr(color: str) -> Optional[str]:
    """pyte 背景色 → ANSI SGR 序列片段"""
    if not color or color == 'default':
        return None
    key = color.lower().replace(' ', '').replace('-', '')
    if key in _BG_NAME_TO_SGR:
        return str(_BG_NAME_TO_SGR[key])
    if len(color) == 6:
        try:
            r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
            return f'48;2;{r};{g};{b}'
        except ValueError:
            pass
    return None


def _char_style_parts(char) -> List[str]:
    """提取 pyte Char 的所有样式 SGR 参数（不含 \\x1b[...m 外壳）"""
    parts: List[str] = []
    fg = _fg_sgr(char.fg)
    if fg:
        parts.append(fg)
    bg = _bg_sgr(char.bg)
    if bg:
        parts.append(bg)
    if getattr(char, 'bold', False):
        parts.append('1')
    if getattr(char, 'italics', False):
        parts.append('3')
    if getattr(char, 'underscore', False):
        parts.append('4')
    if getattr(char, 'strikethrough', False):
        parts.append('9')
    if getattr(char, 'reverse', False):
        parts.append('7')
    return parts


def _get_row_ansi_text(screen: pyte.Screen, row: int, start_col: int = 0) -> str:
    """提取指定行带 ANSI 转义码的文本。

    先确定有效列范围（与 _get_row_text 的 rstrip 等价），仅在有效范围内生成 ANSI 码。
    start_col 用于跳过首列特殊字符（圆点/星星/›）。
    """
    buf_row = screen.buffer[row]

    # 确定最右有效列（rstrip 等价）
    max_col = -1
    for col in buf_row:
        if col >= start_col and buf_row[col].data.rstrip():
            max_col = max(max_col, col)
    if max_col < start_col:
        return ''

    # 预填充空格
    result_chars = [' '] * (max_col - start_col + 1)
    prev_parts: List[str] = []
    has_style = False

    for col, char in sorted(buf_row.items()):
        if col < start_col or col > max_col:
            continue
        cur_parts = _char_style_parts(char)
        if cur_parts != prev_parts:
            if prev_parts:
                # reset 后重设新样式
                prefix = '\x1b[0;' + ';'.join(cur_parts) + 'm' if cur_parts else '\x1b[0m'
            elif cur_parts:
                prefix = '\x1b[' + ';'.join(cur_parts) + 'm'
            else:
                prefix = ''
            result_chars[col - start_col] = prefix + char.data
            prev_parts = cur_parts
            has_style = has_style or bool(cur_parts)
        else:
            result_chars[col - start_col] = char.data

    text = ''.join(result_chars)
    # 行尾 reset
    if has_style and prev_parts:
        text += '\x1b[0m'
    return text


def _get_col0_ansi(screen: pyte.Screen, row: int) -> str:
    """提取首列单个字符的 ANSI 表示（字符 + 颜色转义码）"""
    try:
        char = screen.buffer[row][0]
    except (KeyError, IndexError):
        return ''
    if not char.data.strip():
        return ''
    parts = _char_style_parts(char)
    if not parts:
        return char.data
    return '\x1b[' + ';'.join(parts) + 'm' + char.data + '\x1b[0m'


# ─── 屏幕行工具函数 ────────────────────────────────────────────────────────────

def _is_bright_color(color: str) -> bool:
    """判断 ANSI 颜色是否为亮色。

    亮色判定逻辑：
    - 标准 bright colors (ANSI 90-97)：直接判定为亮色
    - 标准 colors (ANSI 30-37)：判定为暗色
    - 颜色名含 'bright'：判定为亮色
    - 6 位 hex 颜色：通过亮度公式判断（L > 128）
    - 'default'：非亮色

    注意：暗色用于历史 InputBlock，需要排除。
    """
    if not color or color == 'default':
        return False

    # 颜色名：直接判断是否含 'bright'
    key = color.lower().replace(' ', '').replace('-', '')
    if 'bright' in key:
        return True
    # 标准 colors（ANSI 30-37）是暗色
    if key in _FG_NAME_TO_SGR:
        sgr = _FG_NAME_TO_SGR[key]
        return 90 <= sgr <= 97  # 90-97 是 bright colors

    # 6 位 hex 颜色：计算亮度
    if len(color) == 6:
        try:
            r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
            # 亮度公式：L = 0.2126*R + 0.7152*G + 0.0722*B
            brightness = 0.2126 * r + 0.7152 * g + 0.0722 * b
            return brightness > 128
        except ValueError:
            pass

    # 默认判定为亮色（非标准暗色即为亮色）
    return True


def _is_white_color(color: str) -> bool:
    """判断颜色是否为白色/亮白色"""
    if not color or color == 'default':
        return False
    key = color.lower().replace(' ', '').replace('-', '')
    if key in ('white', 'brightwhite'):
        return True
    # hex 颜色：R/G/B 都 > 200
    if len(color) == 6:
        try:
            r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
            return r > 200 and g > 200 and b > 200
        except ValueError:
            pass
    return False


def _is_light_blue_color(color: str) -> bool:
    """判断颜色是否为浅蓝色/青色"""
    if not color or color == 'default':
        return False
    key = color.lower().replace(' ', '').replace('-', '')
    if key in ('cyan', 'brightcyan', 'brightblue'):
        return True
    # hex 颜色：偏蓝（B > R 且 B > G 且整体较亮）
    if len(color) == 6:
        try:
            r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
            if b > r and b > g and (r + g + b) > 200:
                return True
            # 青色：G 和 B 都高
            if g > 150 and b > 150 and r < 150:
                return True
        except ValueError:
            pass
    return False


def _get_row_text(screen: pyte.Screen, row: int) -> str:
    """提取指定行完整文本（rstrip 去尾部空格）。
    预分配空格列表后按 dict 实际内容覆写，避免逐列触发 defaultdict。"""
    buf = [' '] * screen.columns
    for col, char in screen.buffer[row].items():
        buf[col] = char.data
    return ''.join(buf).rstrip()


def _get_col0(screen: pyte.Screen, row: int) -> str:
    """获取指定行第一列字符（col=0）"""
    try:
        return screen.buffer[row][0].data
    except (KeyError, IndexError):
        return ''


def _get_col0_blink(screen: pyte.Screen, row: int) -> bool:
    """获取指定行第一列 blink 属性"""
    try:
        char = screen.buffer[row][0]
        return bool(getattr(char, 'blink', False))
    except (KeyError, IndexError):
        return False



def _is_pure_bg_row(screen: pyte.Screen, row: int) -> bool:
    """纯背景色行：整行有非默认背景色但无文字内容（作为背景色区域的边界标记）。

    等同于 Claude Code 的 ─━═ 字符分割线，但以背景色实现。
    与底部栏区别：底部栏有文字内容，纯背景色行只有 bg 色的空格。

    注意：使用 _has_row_bg（检测所有列含空格）而非 _get_row_dominant_bg
    （只统计非空格字符），确保纯空格背景行能被正确识别。
    """
    if not _has_row_bg(screen, row):
        return False
    return _get_row_text(screen, row).strip() == ''


def _has_row_bg(screen: pyte.Screen, row: int) -> bool:
    """判断整行是否有非默认背景色（包括空格）。

    与 _get_row_dominant_bg 不同的是：
    - _get_row_dominant_bg 只统计有实际字符的背景色
    - _has_row_bg 检测整行所有列的背景色（包括空格）

    用于检测背景色分割线（只有背景色但无文字的行）。
    """
    for col in range(screen.columns):
        try:
            char = screen.buffer[row][col]
            bg = getattr(char, 'bg', 'default') or 'default'
            if bg != 'default':
                return True
        except (KeyError, IndexError):
            continue
    return False


def _has_full_row_bg(screen: pyte.Screen, row: int) -> bool:
    """判断整行是否都有非默认背景色（严格模式）。

    与 _has_row_bg 不同的是：
    - _has_row_bg：只要有一列有非默认背景色就返回 True
    - _has_full_row_bg：要求整行所有列都有非默认背景色

    用于检测输入区域的背景色分割线（整行都有背景色）。
    """
    for col in range(screen.columns):
        try:
            char = screen.buffer[row][col]
            bg = getattr(char, 'bg', 'default') or 'default'
            if bg == 'default':
                return False
        except (KeyError, IndexError):
            return False
    return True


def _get_row_dominant_bg(screen: pyte.Screen, row: int) -> str:
    """获取某行最主要的非空字符背景色；'default' 表示默认背景"""
    bg_counts: Dict[str, int] = {}
    for col in range(screen.columns):
        try:
            char = screen.buffer[row][col]
        except (KeyError, IndexError):
            continue
        if char.data.strip():
            bg = getattr(char, 'bg', 'default') or 'default'
            bg_counts[bg] = bg_counts.get(bg, 0) + 1
    return max(bg_counts, key=bg_counts.get) if bg_counts else 'default'


def _has_numbered_options(screen: pyte.Screen, rows: List[int]) -> bool:
    """检测 rows 是否含编号选项行（需 > 锚点 + ≥2 编号行）

    必须有至少一行匹配 _CURSOR_OPTION_RE（> 锚点），且总编号行 ≥2。
    """
    has_cursor = False
    option_count = 0
    for r in rows:
        text = _get_row_text(screen, r).strip()
        if _CURSOR_OPTION_RE.match(text):
            has_cursor = True
            option_count += 1
        elif _NUMBERED_OPTION_RE.match(text):
            option_count += 1
    return has_cursor and option_count >= 2


def _find_contiguous_options(lines, nav_re):
    """以 > 锚点行出发，在 lines 中找出连续编号选项的范围。

    Returns: (cursor_idx, first_option_idx, last_option_idx)
             若未找到 > 锚点，返回 (-1, -1, -1)
    """
    # 1. 找 > 锚点
    cursor_idx = -1
    cursor_num = 0
    for i, line in enumerate(lines):
        m = _CURSOR_OPTION_RE.match(line)
        if m:
            cursor_idx = i
            cursor_num = int(m.group(1))
            break
    if cursor_idx < 0:
        return (-1, -1, -1)

    # 2. 向前扫描（N-1, N-2, ...）
    first_option_idx = cursor_idx
    expected = cursor_num - 1
    for i in range(cursor_idx - 1, -1, -1):
        line = lines[i]
        if not line or nav_re.search(line):
            continue
        m = re.match(r'^(?:[>❯›]\s*)?(\d+)[.)]\s+', line)
        if m:
            if int(m.group(1)) == expected:
                first_option_idx = i
                expected -= 1
            else:
                break  # 编号不连续，停止
        # 非编号行（描述行）不打断扫描

    # 3. 向后扫描（N+1, N+2, ...）
    last_option_idx = cursor_idx
    expected = cursor_num + 1
    for i in range(cursor_idx + 1, len(lines)):
        line = lines[i]
        if not line or nav_re.search(line):
            continue
        m = re.match(r'^(?:[>❯›]\s*)?(\d+)[.)]\s+', line)
        if m:
            if int(m.group(1)) == expected:
                last_option_idx = i
                expected += 1
            else:
                break  # 编号不连续，停止
        # 非编号行（描述行）不打断扫描

    return (cursor_idx, first_option_idx, last_option_idx)


# ─── ScreenParser ─────────────────────────────────────────────────────────────

class CodexParser(BaseParser):
    """Codex CLI 终端屏幕解析器（从 ClaudeParser 复制，可按需独立修改）"""

    def __init__(self):
        # 帧间圆点缓存：布局模式切换时清空，防止残留行号产生幽灵 block
        self._dot_row_cache: Dict[int, Tuple[str, str, str, str, bool]] = {}
        # 帧间圆点属性缓存：记录上一帧的 (char, fg)，用于检测动画变化（字符/颜色变化 → StatusLine）
        self._dot_attr_cache: Dict[int, Tuple[str, str]] = {}
        # 星号滑动窗口（1.5秒）：记录每行最近 1.5 秒内出现的 (timestamp, char)，
        # 窗口内 ≥2 种不同字符 → spinner 旋转 → StatusLine；始终只有 1 种字符 → SystemBlock
        self._star_row_history: Dict[int, deque] = {}
        # 最近一次解析到的输入区 › 文本（用于 MessageQueue 追踪变更）
        self.last_input_text: str = ''
        self.last_input_ansi_text: str = ''
        # 最近一次 parse 的内部耗时（供外部写日志用）
        self.last_parse_timing: str = ''
        # 布局模式："normal" | "option" | "detail" | "agent_list" | "agent_detail"
        self.last_layout_mode: str = 'normal'
        # Pass 1 区域切分确定的布局模式（None 表示 Pass 1 未成功）
        self._pass1_mode: Optional[str] = None

    def parse(self, screen: pyte.Screen) -> List[Component]:
        """解析 pyte 屏幕，返回组件列表"""
        import time as _time
        _t0 = _time.perf_counter()

        # Step 1：区域切分
        output_rows, input_rows, bottom_rows = self._split_regions(screen)
        _t1 = _time.perf_counter()

        # 布局模式判定（优先使用 Pass 1 的结果）
        prev_mode = self.last_layout_mode
        if self._pass1_mode is not None:
            self.last_layout_mode = self._pass1_mode
        elif input_rows:
            if _has_numbered_options(screen, input_rows):
                self.last_layout_mode = 'option'    # 回退路径：编号选项检测
            else:
                self.last_layout_mode = 'normal'
        elif bottom_rows:
            bottom_text = ' '.join(
                _get_row_text(screen, r).strip() for r in bottom_rows
                if _get_row_text(screen, r).strip()
            ).lower()
            if _has_numbered_options(screen, bottom_rows):
                self.last_layout_mode = 'option'    # 1 分割线 + 编号选项（原 permission）
            elif 'ctrl+o to toggle' in bottom_text:
                self.last_layout_mode = 'detail'
            elif ('background tasks' in bottom_text
                  or ('to select' in bottom_text and 'esc to close' in bottom_text)):
                self.last_layout_mode = 'agent_list'
            elif '← to go back' in bottom_text and 'to close' in bottom_text:
                self.last_layout_mode = 'agent_detail'
            else:
                self.last_layout_mode = 'normal'
        else:
            self.last_layout_mode = 'normal'

        # 模式切换时清空缓存，防止残留行号产生幽灵 block
        if self.last_layout_mode != prev_mode:
            self._dot_row_cache.clear()
            self._dot_attr_cache.clear()
            self._star_row_history.clear()

        # 提取输入区 › 文本（用于 MessageQueue 追踪变更）
        self.last_input_text = self._extract_input_area_text(screen, input_rows)
        self.last_input_ansi_text = self._extract_input_area_ansi_text(screen, input_rows)

        # 清理已失效的 dot_row_cache 条目
        self._cleanup_cache(screen, set(output_rows))
        _t2 = _time.perf_counter()

        # Step 2+3+4：解析输出区
        components: List[Component] = self._parse_output_area(screen, output_rows)
        _t3 = _time.perf_counter()

        # 解析选项交互块（OptionBlock，状态型组件，不进 components）
        overflow_rows: List[int] = []
        option: Optional[OptionBlock] = None
        agent_panel = None

        if input_rows:
            # 2 分割线 + 编号选项 → OptionBlock(sub_type="option")
            option = self._parse_input_area(screen, input_rows, bottom_rows, overflow_rows)
        elif bottom_rows and self.last_layout_mode == 'option':
            # 1 分割线 + 编号选项 → OptionBlock(sub_type="permission")
            option = self._parse_permission_area(screen, bottom_rows)

        # Agent 面板检测（1 条分割线布局）
        if not option:
            if self.last_layout_mode == 'agent_list':
                agent_panel = self._parse_agent_list_panel(screen, bottom_rows)
                if agent_panel:
                    components.append(agent_panel)
            elif self.last_layout_mode == 'agent_detail':
                agent_panel = self._parse_agent_detail_panel(screen, bottom_rows)
                if agent_panel:
                    components.append(agent_panel)

        # OptionBlock 作为状态型组件单独存储（不进 components）
        if option:
            components.append(option)

        # 底部栏（排除被 OptionBlock 溢出占用的行；有 option/agent_panel 时跳过）
        overflow_set = set(overflow_rows)
        bottom_parts = []
        ansi_bottom_parts = []
        for r in bottom_rows:
            if r in overflow_set:
                continue
            text = _get_row_text(screen, r).strip()
            if text:
                bottom_parts.append(text)
                ansi_bottom_parts.append(_get_row_ansi_text(screen, r).strip())
        if bottom_parts and not agent_panel:
            bar_text = '\n'.join(bottom_parts)
            bar_ansi = '\n'.join(ansi_bottom_parts)
            has_agents, agent_count, agent_summary = _parse_bottom_bar_agents(bar_text)
            components.append(BottomBar(
                text=bar_text,
                ansi_text=bar_ansi,
                has_background_agents=has_agents,
                agent_count=agent_count,
                agent_summary=agent_summary,
            ))
        _t4 = _time.perf_counter()

        self.last_parse_timing = (
            f"split={1000*(_t1-_t0):.1f}ms  cleanup={1000*(_t2-_t1):.1f}ms  "
            f"output_area={1000*(_t3-_t2):.1f}ms  rest={1000*(_t4-_t3):.1f}ms  "
            f"output_rows={len(output_rows)}  cursor_y={screen.cursor.y}"
        )

        return components

    # ─── Step 1：区域切分 ──────────────────────────────────────────────────

    def _split_regions(
        self, screen: pyte.Screen
    ) -> Tuple[List[int], List[int], List[int]]:
        """Codex 无 ─━═ 分割线，用背景色区域（连续 bg 行 + 首尾纯背景色边界）定位输入区域。

        背景色区域：连续 3 行以上都有背景色，且第一行和最后一行是纯背景色（无文字），
        整个区域即为输入区域。

        优先级：
          1. 背景色区域（强）：_find_bg_region 找连续 bg zone 内首尾纯背景色边界对
          2. 宽松亮色 › 检测（回退）：只检查行首字符和前景色
          3. 位置弱信号：找最后一个其后无 block 字符的 › 行
          4. 纯背景色兜底：无 › 时用 _find_chrome_boundary
        """
        scan_limit = min(screen.cursor.y + 5, screen.lines - 1)
        _BLOCK_CHARS = DOT_CHARS | CODEX_PROMPT_CHARS | STAR_CHARS

        # Pass 1：找"背景色区域"（连续 bg zone 内首尾纯背景色边界对，区域 >= 3 行）
        self._pass1_mode = None
        bg_region = self._find_bg_region(screen, scan_limit)
        if bg_region is not None:
            region_start, region_end = bg_region
            content_rows = list(range(region_start + 1, region_end))
            # 确定布局模式
            mode = self._determine_input_mode(screen, region_start, content_rows)
            self._pass1_mode = mode
            output_rows = self._trim_welcome(screen, list(range(region_start)))
            input_rows = content_rows
            bottom_rows = list(range(region_end + 1, scan_limit + 1))
            return output_rows, input_rows, bottom_rows

        # Pass 2：宽松检测亮起的 › 行（只检查行首字符和前景色，不检查背景色）
        input_boundary = None
        for row in range(scan_limit, -1, -1):
            col0 = _get_col0(screen, row)
            if col0 in CODEX_PROMPT_CHARS:
                try:
                    char = screen.buffer[row][0]
                    fg = getattr(char, 'fg', 'default') or 'default'
                    if _is_bright_color(fg):
                        input_boundary = row
                        break
                except (KeyError, IndexError):
                    pass

        # Pass 3：位置弱信号
        if input_boundary is None:
            for row in range(scan_limit, -1, -1):
                if _get_col0(screen, row) in CODEX_PROMPT_CHARS:
                    has_block_after = any(
                        _get_col0(screen, r) in _BLOCK_CHARS
                        for r in range(row + 1, scan_limit + 1)
                    )
                    if not has_block_after:
                        input_boundary = row
                        break

        if input_boundary is not None:
            output_rows = self._trim_welcome(screen, list(range(input_boundary)))
            input_rows = [input_boundary]
            bottom_rows = list(range(input_boundary + 1, scan_limit + 1))
            return output_rows, input_rows, bottom_rows

        # Pass 4：纯背景色兜底（无 › 行时，如纯查看模式）
        chrome_start = self._find_chrome_boundary(screen, scan_limit)
        if chrome_start is not None and chrome_start > 0:
            output_rows = self._trim_welcome(screen, list(range(chrome_start)))
            bottom_rows = list(range(chrome_start, scan_limit + 1))
            return output_rows, [], bottom_rows

        # 最终兜底：全部作为输出区
        output_rows = self._trim_welcome(screen, list(range(scan_limit + 1)))
        return output_rows, [], []

    def _find_bg_region(
        self, screen: pyte.Screen, scan_limit: int
    ) -> Optional[Tuple[int, int]]:
        """在连续 bg zone 内找背景色区域（首尾纯背景色边界对，区域 >= 3 行）。

        算法：
        1. 从 scan_limit 往上扫描找连续 bg 行 zone（用 _has_row_bg）
        2. zone 内找所有纯背景色行（用 _is_pure_bg_row）
        3. 取首条和末条纯背景色行作为边界对
        4. 验证 region_end - region_start >= 2（至少 3 行：边界 + 内容行）

        Returns: (region_start, region_end) 含边界行，或 None
        """
        zone_end: Optional[int] = None
        zone_start: Optional[int] = None
        for row in range(scan_limit, -1, -1):
            if _has_row_bg(screen, row):
                if zone_end is None:
                    zone_end = row
                zone_start = row
            elif zone_end is not None:
                break  # 遇到无 bg 行，zone 边界确定

        if zone_start is None or zone_end is None:
            return None

        # 在 zone 内找所有纯背景色行（背景色区域边界候选）
        pure_bg_rows = [r for r in range(zone_start, zone_end + 1)
                        if _is_pure_bg_row(screen, r)]
        if len(pure_bg_rows) < 2:
            return None

        region_start, region_end = pure_bg_rows[0], pure_bg_rows[-1]
        # 区域至少 3 行（边界对 + 至少 1 行内容）
        if region_end - region_start < 2:
            return None

        return region_start, region_end

    def _determine_input_mode(
        self, screen: pyte.Screen, region_start: int, content_rows: List[int]
    ) -> str:
        """判断背景色区域的布局模式：'option' 或 'normal'。

        判断优先级：
        1. 条件 4b：首个内容行行首是 ›，白色/亮色 → 'normal'
        2. 条件 4a：上方依次是空行+分割线+空行 → 'option'
        3. 条件 4c：内容行中有浅蓝色 › 且整行同色 → 'option'
        4. 兜底：_has_numbered_options → 'option'，否则 'normal'
        """
        if not content_rows:
            return 'normal'

        # 条件 4b：首个内容行行首是 › + 白色/亮色 → normal
        first_content = content_rows[0]
        col0 = _get_col0(screen, first_content)
        if col0 in CODEX_PROMPT_CHARS:
            try:
                char = screen.buffer[first_content][0]
                fg = getattr(char, 'fg', 'default') or 'default'
                if _is_white_color(fg) or _is_bright_color(fg):
                    return 'normal'
            except (KeyError, IndexError):
                pass

        # 条件 4a：上方有空行+分割线+空行 → option
        if self._has_option_context_above(screen, region_start):
            return 'option'

        # 条件 4c：内容行中有浅蓝色 › 且整行同色 → option
        for row in content_rows:
            col0 = _get_col0(screen, row)
            if col0 in CODEX_PROMPT_CHARS:
                try:
                    char = screen.buffer[row][0]
                    fg = getattr(char, 'fg', 'default') or 'default'
                    if _is_light_blue_color(fg) and self._is_whole_row_same_fg(screen, row, fg):
                        return 'option'
                except (KeyError, IndexError):
                    pass

        # 兜底：编号选项检测
        if _has_numbered_options(screen, content_rows):
            return 'option'

        return 'normal'

    def _has_option_context_above(self, screen: pyte.Screen, region_start: int) -> bool:
        """检测条件 4a：背景色区域上方依次是
        默认背景色空行 → 默认背景色普通分割线（─━═）→ 默认背景色空行
        """
        if region_start < 3:
            return False

        empty_below = region_start - 1
        divider_row = region_start - 2
        empty_above = region_start - 3

        # 检查 empty_below：默认 bg + 无文字
        if _get_row_dominant_bg(screen, empty_below) != 'default':
            return False
        if _get_row_text(screen, empty_below).strip():
            return False

        # 检查 divider_row：默认 bg + 含 ─━═ 字符
        if _get_row_dominant_bg(screen, divider_row) != 'default':
            return False
        divider_text = _get_row_text(screen, divider_row).strip()
        if not divider_text or not any(c in DIVIDER_CHARS for c in divider_text):
            return False

        # 检查 empty_above：默认 bg + 无文字
        if _get_row_dominant_bg(screen, empty_above) != 'default':
            return False
        if _get_row_text(screen, empty_above).strip():
            return False

        return True

    def _is_whole_row_same_fg(self, screen: pyte.Screen, row: int, expected_fg: str) -> bool:
        """检查整行非空字符是否都有相同的前景色（条件 4c 的整行同色检测）"""
        has_chars = False
        for col in range(screen.columns):
            try:
                char = screen.buffer[row][col]
                if not char.data.strip():
                    continue
                has_chars = True
                fg = getattr(char, 'fg', 'default') or 'default'
                if fg != expected_fg:
                    return False
            except (KeyError, IndexError):
                continue
        return has_chars

    def _find_chrome_boundary(self, screen: pyte.Screen, scan_limit: int) -> Optional[int]:
        """背景色检测：从底部往上找连续的非默认背景行（UI chrome）。

        返回 chrome 区域的起始行号；若无则返回 None。
        """
        chrome_start = None
        for row in range(scan_limit, -1, -1):
            if _get_row_dominant_bg(screen, row) != 'default':
                chrome_start = row
            else:
                break
        return chrome_start

    def _trim_welcome(self, screen: pyte.Screen, rows: List[int]) -> List[int]:
        """去掉欢迎区域：跳过首列为空的前缀行和欢迎框（OpenAI Codex box）。

        注意：欢迎框顶边框行（╭────╮）本身不含工具名称，工具名在框内第一个 │ 行。
        因此需检查框内容行，而非顶边框行。
        """
        i = 0
        while i < len(rows):
            col0 = _get_col0(screen, rows[i])
            if not col0.strip():
                i += 1
                continue
            # 首个非空 col0 是 box 顶角 → 检查框内容行是否为欢迎框
            if col0 in BOX_CORNER_TOP:
                if self._is_welcome_box(screen, rows, i):
                    # 跳过整个欢迎框（到 ╰/└ 行为止）
                    i += 1
                    while i < len(rows):
                        if _get_col0(screen, rows[i]) in BOX_CORNER_BOTTOM:
                            i += 1
                            break
                        i += 1
                    continue  # 继续跳过后续空行
            # 非欢迎框，返回剩余行
            return rows[i:]
        return []

    def _is_welcome_box(self, screen: pyte.Screen, rows: List[int], top_idx: int) -> bool:
        """判断 box 是否为欢迎框。

        判断逻辑（满足任意一条即为欢迎框）：
        1. 框内行有非默认背景色（UI 主题框）
        2. 框内前几行含工具标识（>_ 提示符）或配置信息（model:、directory: 等）
        """
        for j in range(top_idx + 1, min(top_idx + 6, len(rows))):
            col0 = _get_col0(screen, rows[j])
            if col0 in BOX_CORNER_BOTTOM:
                break
            # 条件1：非默认背景色
            if _get_row_dominant_bg(screen, rows[j]) != 'default':
                return True
            # 条件2：内容行含工具配置特征
            line_text = _get_row_text(screen, rows[j])
            if any(pat in line_text for pat in ('>_ ', 'model:', 'directory:', 'workspace:')):
                return True
        return False

    # ─── Step 2+3+4：输出区解析 ────────────────────────────────────────────

    def _cleanup_cache(self, screen: pyte.Screen, output_row_set: Set[int]):
        """清理 dot_row_cache / star_row_history 中不再有效的条目"""
        for row in list(self._dot_row_cache.keys()):
            if row not in output_row_set:
                # 行已不在输出区（屏幕滚动等）
                del self._dot_row_cache[row]
                continue
            col0 = _get_col0(screen, row)
            if col0.strip() and col0 not in DOT_CHARS:
                # 首列变为其他非圆点内容，缓存失效
                del self._dot_row_cache[row]
        # 清理 star_row_history：只清理已滚出输出区的行，不根据 col0 内容变化删除
        # 原因：星星字符闪烁时会暂时变成其他字符（如·）或空白，不应因此清空历史
        # 历史记录本身有 1.5 秒过期机制，会自动清理过期数据
        for row in list(self._star_row_history.keys()):
            if row not in output_row_set:
                del self._star_row_history[row]

    def _parse_output_area(
        self, screen: pyte.Screen, rows: List[int]
    ) -> List[Component]:
        """切 Block 并分类"""
        if not rows:
            return []

        # 切 Block：首列有非空字符 OR 在 dot_row_cache 中（圆点闪烁隐去帧）→ Block 首行
        # box 区域（╭...╰）整体合并为一个 block
        blocks: List[Tuple[int, List[int]]] = []
        current_first: Optional[int] = None
        current_rows: Optional[List[int]] = None
        in_box = False

        for row in rows:
            col0 = _get_col0(screen, row)

            # Box 区域合并：╭ 开始 → │ 继续 → ╰ 结束，整个区域作为一个 block
            if in_box:
                current_rows.append(row)
                if col0 in BOX_CORNER_BOTTOM:
                    blocks.append((current_first, current_rows))
                    current_first = None
                    current_rows = None
                    in_box = False
                continue

            if col0 in BOX_CORNER_TOP:
                # 先保存当前正在构建的 block
                if current_rows is not None:
                    blocks.append((current_first, current_rows))
                current_first = row
                current_rows = [row]
                in_box = True
                continue

            is_header = bool(col0.strip()) or (row in self._dot_row_cache)

            if is_header:
                if current_rows is not None:
                    blocks.append((current_first, current_rows))
                current_first = row
                current_rows = [row]
            else:
                if current_rows is not None:
                    current_rows.append(row)
                # 欢迎区之前的行（_trim_welcome 已过滤，理论不会到这里）

        if current_rows is not None:
            blocks.append((current_first, current_rows))

        return [
            c for c in (
                self._classify_block(screen, fr, br) for fr, br in blocks
            )
            if c is not None
        ]

    def _classify_block(
        self, screen: pyte.Screen, first_row: int, block_rows: List[int]
    ) -> Optional[Component]:
        """根据首行首列字符对 Block 分类"""
        col0 = _get_col0(screen, first_row)
        is_blink = _get_col0_blink(screen, first_row)

        # 圆点闪烁隐去帧：col0 为空但 dot_row_cache 有记录
        if not col0.strip() and first_row in self._dot_row_cache:
            cached_first_line, cached_ansi_first, cached_ind, cached_ansi_ind, cached_blink = self._dot_row_cache[first_row]
            logger.debug(
                f"[cache-hit] row={first_row} cached={cached_first_line[:40]!r} blink={cached_blink}"
            )
            # 继承上次记录的 blink 状态：若上次 dot 出现时已是 False（block 已完成），
            # 则本次 dot 消失（如 ctrl+o 重绘）不应误判为 streaming
            first_content = cached_first_line[1:].strip() if cached_first_line else ''
            body_lines = [_get_row_text(screen, r) for r in block_rows[1:]]
            content = '\n'.join([first_content] + body_lines).rstrip()
            ansi_body_lines = [_get_row_ansi_text(screen, r) for r in block_rows[1:]]
            ansi_content = '\n'.join([cached_ansi_first] + ansi_body_lines).rstrip()
            content, ansi_content = _strip_inline_boxes_pair(content, ansi_content)
            return OutputBlock(
                content=content, is_streaming=cached_blink, start_row=first_row,
                ansi_content=ansi_content, indicator=cached_ind, ansi_indicator=cached_ansi_ind,
            )

        if not col0.strip():
            return None

        # PlanBlock：box-drawing 顶角字符（╭ 或 ┌）
        if col0 in BOX_CORNER_TOP:
            return self._parse_plan_block(screen, first_row, block_rows)

        lines = [_get_row_text(screen, r) for r in block_rows]

        # 星号字符：blink → StatusLine（状态行），非 blink → SystemBlock（系统提示）
        # 兜底：1.5秒滑动窗口检测（窗口内 ≥2 种不同字符 → spinner 旋转 → StatusLine）
        if col0 in STAR_CHARS:
            now = time.time()
            history = self._star_row_history.setdefault(first_row, deque())
            # 清理超过 1.5 秒的旧帧
            while history and history[0][0] < now - 1.5:
                history.popleft()
            history.append((now, col0))
            # 窗口内 ≥2 种不同字符 → spinner 旋转 → StatusLine
            unique_chars = {c for _, c in history}
            inferred_blink = is_blink or len(unique_chars) > 1
            if inferred_blink:
                return self._parse_status_block(
                    lines[0],
                    ansi_first_line=_get_row_ansi_text(screen, first_row),
                    indicator=col0,
                    ansi_indicator=_get_col0_ansi(screen, first_row),
                )
            else:
                return self._parse_system_block(screen, first_row, block_rows, lines, col0)

        # UserInput：› U+203A（Codex 实际使用字符）或 > U+003E（兼容）
        if col0 in CODEX_PROMPT_CHARS:
            first_text = lines[0][1:].strip()
            # 内容全是分割线字符（如 ›─────...─）→ 装饰性分隔符，忽略
            if not first_text or all(c in DIVIDER_CHARS for c in first_text):
                return None
            # 收集后续续行（多行输入 / 屏幕自动换行），过滤尾部空白行
            body_lines = [l for l in lines[1:] if l.strip()]
            text = '\n'.join([first_text] + body_lines)
            ind = col0
            ansi_ind = _get_col0_ansi(screen, first_row)
            ansi_first = _get_row_ansi_text(screen, first_row, start_col=1).strip()
            ansi_body = [_get_row_ansi_text(screen, r) for r in block_rows[1:]
                         if _get_row_text(screen, r).strip()]
            ansi_text = '\n'.join([ansi_first] + ansi_body)
            return UserInput(text=text, ansi_text=ansi_text, indicator=ind, ansi_indicator=ansi_ind)

        # OutputBlock：圆点字符
        if col0 in DOT_CHARS:
            # Codex：圆点 blink=True → StatusLine；blink=False → OutputBlock
            # （与 Claude Code 用星星字符区分不同，Codex 用同一圆点字符 + blink 属性区分）

            # 路径1：pyte blink 检测到 → StatusLine（原有逻辑）
            if is_blink:
                ansi_first_line = _get_row_ansi_text(screen, first_row)
                try:
                    cur_fg = str(getattr(screen.buffer[first_row].get(0), 'fg', ''))
                except Exception:
                    cur_fg = ''
                self._dot_attr_cache[first_row] = (col0, cur_fg)
                return self._parse_status_block(
                    lines[0], ansi_first_line=ansi_first_line,
                    indicator=col0, ansi_indicator=_get_col0_ansi(screen, first_row),
                )

            # 路径2：字符/颜色变化检测（pyte blink 失效时的兜底）
            try:
                cur_fg = str(getattr(screen.buffer[first_row].get(0), 'fg', ''))
            except Exception:
                cur_fg = ''
            prev_attr = self._dot_attr_cache.get(first_row)
            char_changed = prev_attr is not None and (prev_attr[0] != col0 or prev_attr[1] != cur_fg)
            self._dot_attr_cache[first_row] = (col0, cur_fg)

            # 路径3：内容含 "esc to interrupt" → Codex StatusLine 的固定特征
            first_line_text = lines[0] if lines else ''
            content_is_status = 'esc to interrupt' in first_line_text.lower()

            if char_changed or content_is_status:
                ansi_first_line = _get_row_ansi_text(screen, first_row)
                return self._parse_status_block(
                    lines[0], ansi_first_line=ansi_first_line,
                    indicator=col0, ansi_indicator=_get_col0_ansi(screen, first_row),
                )

            ind = col0
            ansi_ind = _get_col0_ansi(screen, first_row)
            ansi_first = _get_row_ansi_text(screen, first_row, start_col=1).strip()
            ansi_body = [_get_row_ansi_text(screen, r) for r in block_rows[1:]]
            # 更新帧间缓存（同时记录 blink 状态，供 dot 消失帧继承）
            self._dot_row_cache[first_row] = (lines[0], ansi_first, ind, ansi_ind, is_blink)
            if is_blink:
                logger.debug(
                    f"[blink] row={first_row} content={lines[0][:40]!r}"
                )
            first_content = lines[0][1:].strip()
            body_lines = lines[1:]
            content = '\n'.join([first_content] + body_lines).rstrip()
            ansi_content = '\n'.join([ansi_first] + ansi_body).rstrip()
            content, ansi_content = _strip_inline_boxes_pair(content, ansi_content)
            return OutputBlock(
                content=content, is_streaming=is_blink, start_row=first_row,
                ansi_content=ansi_content, indicator=ind, ansi_indicator=ansi_ind,
            )

        # 其他首列字符（装饰残留、欢迎区片段等），忽略
        return None

    def _parse_plan_block(
        self, screen: pyte.Screen, first_row: int, block_rows: List[int]
    ) -> PlanBlock:
        """解析 box-drawing 框线包裹的计划内容（Plan Mode）"""
        content_lines = []
        ansi_lines = []
        for row in block_rows:
            col0 = _get_col0(screen, row)
            if col0 in BOX_CORNER_TOP or col0 in BOX_CORNER_BOTTOM:
                continue  # 跳过顶/底边框行
            if col0 in BOX_VERTICAL:
                line = _get_row_text(screen, row)
                inner = line[1:]  # 去掉左侧 │
                # 去掉右侧 │（如有）
                stripped = inner.rstrip()
                if stripped and stripped[-1] in BOX_VERTICAL:
                    inner = stripped[:-1]
                content_lines.append(inner.rstrip())
                ansi_line = _get_row_ansi_text(screen, row, start_col=1)
                # 去掉右侧 │（可能包裹 ANSI 码，如 │\x1b[0m 或 \x1b[...m│\x1b[0m）
                ansi_line = re.sub(r'(\x1b\[[0-9;]*m)*[│┃║](\x1b\[0m)?\s*$', '', ansi_line)
                ansi_lines.append(ansi_line.rstrip())

        content = '\n'.join(content_lines).strip()
        ansi_content = '\n'.join(ansi_lines).strip()

        title = ''
        for line in content_lines:
            if line.strip():
                title = line.strip()
                break

        return PlanBlock(
            title=title,
            content=content,
            is_streaming=False,
            start_row=first_row,
            ansi_content=ansi_content,
        )

    def _parse_status_block(
        self, first_line: str,
        ansi_first_line: str = '', indicator: str = '', ansi_indicator: str = '',
    ) -> Optional[StatusLine]:
        """解析状态行：✱ Action... (Xm Ys · ↓ Nk tokens)"""
        rest = first_line[1:].strip()  # 去掉首列星星字符
        paren_match = re.search(r'\(([^)]+)\)\s*$', rest)
        if not paren_match:
            # 无统计括号（thinking 动画等），仍返回 StatusLine 保证 is_busy 可靠
            return StatusLine(
                action=rest, elapsed='', tokens='', raw=first_line,
                ansi_raw=ansi_first_line, indicator=indicator, ansi_indicator=ansi_indicator,
            )
        stats_text = paren_match.group(1)
        action = rest[:paren_match.start()].strip()
        elapsed = tokens = ''
        for part in [p.strip() for p in stats_text.split('·')]:
            if re.search(r'\d+[mhs]', part):
                elapsed = part
            elif '↓' in part or 'token' in part.lower():
                tokens = part
        return StatusLine(
            action=action, elapsed=elapsed, tokens=tokens, raw=first_line,
            ansi_raw=ansi_first_line, indicator=indicator, ansi_indicator=ansi_indicator,
        )

    def _parse_system_block(
        self, screen: pyte.Screen, first_row: int,
        block_rows: List[int], lines: List[str], col0: str,
    ) -> SystemBlock:
        """解析系统提示块：首列星号字符不闪烁（blink=False）的 block"""
        ind = col0
        ansi_ind = _get_col0_ansi(screen, first_row)
        first_content = lines[0][1:].strip()
        body_lines = lines[1:]
        content = '\n'.join([first_content] + body_lines).rstrip()
        ansi_first = _get_row_ansi_text(screen, first_row, start_col=1).strip()
        ansi_body = [_get_row_ansi_text(screen, r) for r in block_rows[1:]]
        ansi_content = '\n'.join([ansi_first] + ansi_body).rstrip()
        return SystemBlock(
            content=content,
            start_row=first_row,
            ansi_content=ansi_content,
            indicator=ind,
            ansi_indicator=ansi_ind,
        )

    # ─── 用户输入区解析 ────────────────────────────────────────────────────

    def _parse_input_area(
        self,
        screen: pyte.Screen,
        input_rows: List[int],
        bottom_rows: List[int],
        overflow_out: List[int],
    ) -> Optional[OptionBlock]:
        """解析用户输入区的 OptionBlock（编号选项检测），并检测溢出到底部栏的尾部选项"""
        if not input_rows:
            return None

        # 入口检测：是否有编号选项行（需 > 锚点）
        if not _has_numbered_options(screen, input_rows):
            return None

        # 收集行文本，用 _find_contiguous_options 定位连续选项范围
        NAV_RE = re.compile(r'(Enter to select|↑/↓|Esc to cancel|to navigate)')
        row_texts = [_get_row_text(screen, r).strip() for r in input_rows]
        cursor_idx, first_opt_idx, last_opt_idx = _find_contiguous_options(row_texts, NAV_RE)
        if cursor_idx < 0:
            return None

        # 向前收集 tag/question 行（first_opt_idx 之前）
        tag = ''
        question = ''
        pre_contents: List[str] = []
        for i in range(first_opt_idx):
            text = row_texts[i]
            if not text:
                continue
            if NAV_RE.search(text):
                continue
            pre_contents.append(text)
        if pre_contents:
            first = pre_contents[0]
            if len(pre_contents) >= 2:
                tag = first
                question = pre_contents[-1]
            else:
                if '?' in first or '？' in first:
                    question = first
                else:
                    tag = first

        # 选项范围行 + 溢出检测
        option_input_rows = input_rows[first_opt_idx:last_opt_idx + 1]
        overflow = self._detect_option_overflow(screen, option_input_rows, bottom_rows)
        overflow_out.extend(overflow)
        all_option_rows = option_input_rows + overflow

        options: List[dict] = []
        current_opt: Optional[dict] = None
        ansi_raw_lines = [_get_row_ansi_text(screen, r) for r in input_rows + overflow]

        for row in all_option_rows:
            line = _get_row_text(screen, row).strip()
            if not line:
                continue
            if NAV_RE.search(line):
                continue
            # 编号选项行
            m = re.match(r'^(?:[>❯›]\s*)?(\d+)[.)]\s*(.+)', line)
            if m:
                if current_opt is not None:
                    options.append(current_opt)
                current_opt = {
                    'label': m.group(2).strip(),
                    'value': m.group(1),
                    'description': '',
                }
            elif current_opt is not None and line:
                # 描述行
                current_opt['description'] = (
                    current_opt['description'] + ' ' + line
                ).strip()

        if current_opt is not None:
            options.append(current_opt)

        if question or options:
            return OptionBlock(
                sub_type='option', tag=tag, question=question, options=options,
                ansi_raw='\n'.join(ansi_raw_lines).rstrip(),
            )
        return None

    def _extract_input_area_text(self, screen: pyte.Screen, input_rows: List[int]) -> str:
        """提取输入区提示符后的当前输入文本（空提示符返回空字符串）。
        选项交互模式下不提取输入文本（input_rows 是选项内容，非用户输入）。
        多行输入时，收集 › 行之后首列为空的续行，合并为完整文本。
        """
        if self.last_layout_mode == 'option':
            return ''
        for i, row in enumerate(input_rows):
            if _get_col0(screen, row) in CODEX_PROMPT_CHARS:
                text = _get_row_text(screen, row)[1:].strip()
                # 排除纯分割线装饰行（如 ›─────）
                if text and not all(c in DIVIDER_CHARS for c in text):
                    # 收集续行（首列为空的非空文本行）
                    lines = [text]
                    for next_row in input_rows[i + 1:]:
                        col0 = _get_col0(screen, next_row)
                        if col0.strip():  # 首列有字符，遇到新 block 或新 › 行，停止
                            break
                        next_text = _get_row_text(screen, next_row).strip()
                        if next_text:
                            lines.append(next_text)
                    return '\n'.join(lines)
        return ''

    def _extract_input_area_ansi_text(self, screen: pyte.Screen, input_rows: List[int]) -> str:
        """提取输入区提示符后的当前输入文本（ANSI 版本）。
        多行输入时，收集 › 行之后首列为空的续行，合并为完整文本。
        """
        if self.last_layout_mode == 'option':
            return ''
        for i, row in enumerate(input_rows):
            if _get_col0(screen, row) in CODEX_PROMPT_CHARS:
                text = _get_row_text(screen, row)[1:].strip()
                if text and not all(c in DIVIDER_CHARS for c in text):
                    lines = [_get_row_ansi_text(screen, row, start_col=1).strip()]
                    for next_row in input_rows[i + 1:]:
                        col0 = _get_col0(screen, next_row)
                        if col0.strip():  # 首列有字符，停止
                            break
                        next_text = _get_row_text(screen, next_row).strip()
                        if next_text:
                            lines.append(_get_row_ansi_text(screen, next_row).strip())
                    return '\n'.join(lines)
        return ''

    def _parse_permission_area(
        self,
        screen: pyte.Screen,
        bottom_rows: List[int],
    ) -> Optional[OptionBlock]:
        """解析 1 条分割线布局下的权限确认区域，返回 OptionBlock(sub_type="permission")

        检测条件：bottom_rows 中含 > 锚点 + ≥2 个编号选项行。
        通过 _find_contiguous_options 以 > 为锚点双向扫描，只收集连续编号选项。
        """
        if not bottom_rows:
            return None

        # 收集所有非空行文本和 ANSI 文本
        lines: List[str] = []
        ansi_lines: List[str] = []
        for r in bottom_rows:
            text = _get_row_text(screen, r).strip()
            if text:
                lines.append(text)
                ansi_lines.append(_get_row_ansi_text(screen, r).rstrip())

        if not lines:
            return None

        # 用锚点 + 连续性定位选项范围
        NAV_RE = re.compile(r'(Esc to cancel|Tab to amend|to navigate|Enter to select|↑/↓)')
        cursor_idx, first_opt_idx, last_opt_idx = _find_contiguous_options(lines, NAV_RE)
        if cursor_idx < 0:
            return None

        # 至少 2 个编号行
        opt_count = 0
        for i in range(first_opt_idx, last_opt_idx + 1):
            if _NUMBERED_OPTION_RE.match(lines[i]):
                opt_count += 1
        if opt_count < 2:
            return None

        # 分类每行（仅范围内的编号行标记为 option）
        option_idx_set = set(range(first_opt_idx, last_opt_idx + 1))
        classified: List[tuple] = []
        for i, line in enumerate(lines):
            if i in option_idx_set and _NUMBERED_OPTION_RE.match(line):
                classified.append((line, 'option'))
            elif NAV_RE.search(line):
                classified.append((line, 'nav'))
            else:
                classified.append((line, 'content'))

        # title / content / question 提取逻辑不变
        title = ''
        question = ''
        options: List[dict] = []
        content_lines: List[str] = []

        # 收集第一个 option 之前的所有 content 行
        pre_option_contents: List[str] = []
        for i in range(first_opt_idx):
            line, cat = classified[i]
            if cat == 'content':
                pre_option_contents.append(line)

        if pre_option_contents:
            if len(pre_option_contents) == 1:
                question = pre_option_contents[0]
            else:
                title = pre_option_contents[0]
                question = pre_option_contents[-1]
                content_lines = pre_option_contents[1:-1]

        # 只收集范围内的 options
        for i in range(first_opt_idx, last_opt_idx + 1):
            line, cat = classified[i]
            if cat == 'option':
                m = re.match(r'^(?:[>❯›]\s*)?(\d+)[.)]\s*(.+)', line)
                if m:
                    options.append({
                        'label': m.group(2).strip(),
                        'value': m.group(1),
                    })

        return OptionBlock(
            sub_type='permission',
            title=title,
            content='\n'.join(content_lines),
            question=question,
            options=options,
            ansi_raw='\n'.join(ansi_lines).rstrip(),
        )

    def _parse_agent_list_panel(
        self,
        screen: pyte.Screen,
        bottom_rows: List[int],
    ) -> Optional[AgentPanelBlock]:
        """解析 agent 列表面板（用户按 ↓ 展开）

        特征：1 条分割线，分割线下方含 "Background tasks"、agent 列表、导航提示
        """
        if not bottom_rows:
            return None

        lines: List[str] = []
        ansi_lines: List[str] = []
        for r in bottom_rows:
            text = _get_row_text(screen, r).strip()
            if text:
                lines.append(text)
                ansi_lines.append(_get_row_ansi_text(screen, r).strip())

        if not lines:
            return None

        agents: List[dict] = []
        agent_count = 0

        for line in lines:
            # 跳过导航提示行
            if re.search(r'(↑/↓\s+to select|esc to close|to navigate)', line, re.IGNORECASE):
                continue

            # 匹配 "N active agents" 标题行
            m = re.match(r'(\d+)\s+(?:active\s+)?(?:background\s+)?(?:tasks?|agents?)', line, re.IGNORECASE)
            if m:
                agent_count = int(m.group(1))
                continue

            # 匹配 "Background tasks" 标题行
            if re.match(r'background\s+tasks?', line, re.IGNORECASE):
                continue

            # 匹配 agent 行：可选的 > 前缀 + 名称 + (status)
            m = re.match(r'^(>\s*)?(.+?)\s*\((running|completed|failed|killed)\)', line, re.IGNORECASE)
            if m:
                is_selected = bool(m.group(1))
                name = m.group(2).strip()
                status = m.group(3).lower()
                agents.append({
                    "name": name,
                    "status": status,
                    "is_selected": is_selected,
                })

        # 如果未从标题行获取 count，使用 agents 列表长度
        if not agent_count:
            agent_count = len(agents)

        return AgentPanelBlock(
            panel_type="list",
            agent_count=agent_count,
            agents=agents,
            raw_text='\n'.join(lines),
            ansi_raw='\n'.join(ansi_lines),
        )

    def _parse_agent_detail_panel(
        self,
        screen: pyte.Screen,
        bottom_rows: List[int],
    ) -> Optional[AgentPanelBlock]:
        """解析 agent 详情面板（列表中按 Enter）

        特征：1 条分割线，分割线下方含 agent 类型+名称、统计、Progress、Prompt
        """
        if not bottom_rows:
            return None

        lines: List[str] = []
        ansi_lines: List[str] = []
        for r in bottom_rows:
            text = _get_row_text(screen, r).strip()
            if text:
                lines.append(text)
                ansi_lines.append(_get_row_ansi_text(screen, r).strip())

        if not lines:
            return None

        agent_type = ''
        agent_name = ''
        stats = ''
        progress_lines: List[str] = []
        prompt_lines: List[str] = []
        current_section = None  # 'progress' | 'prompt' | None

        for line in lines:
            # 跳过导航提示行
            if re.search(r'(← to go back|esc to close)', line, re.IGNORECASE):
                continue

            # 匹配首行 "type › name" 格式
            if not agent_type:
                m = re.match(r'^(.+?)\s*›\s*(.+)', line)
                if m:
                    agent_type = m.group(1).strip()
                    agent_name = m.group(2).strip()
                    continue

            # 统计行：包含时间和 token 信息
            if re.search(r'\d+[ms]\s*·.*token', line, re.IGNORECASE):
                stats = line
                continue

            # Section 标题
            if re.match(r'^progress$', line, re.IGNORECASE):
                current_section = 'progress'
                continue
            if re.match(r'^prompt$', line, re.IGNORECASE):
                current_section = 'prompt'
                continue

            # Section 内容
            if current_section == 'progress':
                progress_lines.append(line)
            elif current_section == 'prompt':
                prompt_lines.append(line)

        return AgentPanelBlock(
            panel_type="detail",
            agent_name=agent_name,
            agent_type=agent_type,
            stats=stats,
            progress='\n'.join(progress_lines).strip(),
            prompt='\n'.join(prompt_lines).strip(),
            raw_text='\n'.join(lines),
            ansi_raw='\n'.join(ansi_lines),
        )

    def _detect_option_overflow(
        self,
        screen: pyte.Screen,
        option_rows: List[int],
        bottom_rows: List[int],
    ) -> List[int]:
        """检测溢出到底部栏区域的选项行（最多 2 行）

        识别依据：缩进一致性 + 数字编号连续性
        """
        if not bottom_rows or not option_rows:
            return []

        # 找输入区中最后一个数字编号
        last_num = 0
        for row in reversed(option_rows):
            line = _get_row_text(screen, row).strip()
            m = re.match(r'^(?:>\s*)?(\d+)[.)]\s+', line)
            if m:
                last_num = int(m.group(1))
                break

        if last_num == 0:
            return []

        overflow: List[int] = []
        expected = last_num + 1
        for row in bottom_rows[:2]:
            line = _get_row_text(screen, row).strip()
            m = re.match(r'^(?:>\s*)?(\d+)[.)]\s+', line)
            if m and int(m.group(1)) == expected:
                overflow.append(row)
                expected += 1
            else:
                break

        return overflow



# ─── 底部栏 Agent 信息解析 ─────────────────────────────────────────────────────

def _parse_bottom_bar_agents(text: str) -> tuple:
    """Codex 底部栏不包含 agent 管理信息"""
    return (False, 0, '')


# ─── 公共接口 ──────────────────────────────────────────────────────────────────

def components_content_key(components: List[Component]) -> str:
    """生成组件列表内容指纹，用于去重"""
    parts = []
    for c in components:
        if isinstance(c, OutputBlock):
            first = c.content.split('\n')[0][:100]
            parts.append(f"OB:{first}:{c.is_streaming}")
        elif isinstance(c, UserInput):
            parts.append(f"U:{c.text}")
        elif isinstance(c, OptionBlock):
            if c.sub_type == 'permission':
                parts.append(f"Perm:{c.question[:50]}:{len(c.options)}")
            else:
                parts.append(f"Opt:{c.question[:50]}:{len(c.options)}")
        elif isinstance(c, AgentPanelBlock):
            if c.panel_type == 'detail':
                parts.append(f"AP:{c.agent_name[:50]}")
            elif c.panel_type == 'summary':
                parts.append(f"AP:summary:{c.agent_count}")
            else:
                parts.append(f"AP:list:{c.agent_count}")
        elif isinstance(c, PlanBlock):
            parts.append(f"PL:{c.title[:50]}")
        elif isinstance(c, StatusLine):
            parts.append(f"S:{c.action}:{c.elapsed}")
        elif isinstance(c, BottomBar):
            parts.append(f"BB:{c.text[:100]}")
    return '|'.join(parts)


