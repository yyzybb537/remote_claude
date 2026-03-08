"""Claude CLI 输出组件解析器（重构版）

基于 CLAUDE.md 中定义的 4 步解析规则：
  1. 区域切分：从底部向上找最后 2 条分割线，切出欢迎区/输出区/用户输入区/底部栏
  2. 输出区切 Block：首列（col=0）有非空字符的行是 Block 首行
  3. Block 分类：星星字符→StatusLine，圆点字符→OutputBlock，❯→UserInput
  4. 执行状态判断：首列字符 blink 属性 + dot_row_cache 帧间持久化

OptionBlock（AskUserQuestion 选项交互块）出现在用户输入区，不在输出区。
"""

import re
import logging
from typing import List, Optional, Dict, Tuple, Set

import pyte

from utils.components import (
    Component, OutputBlock, UserInput, OptionBlock, StatusLine, BottomBar, AgentPanelBlock,
)

logger = logging.getLogger('ComponentParser')

# 星星字符集（状态行首列）
STAR_CHARS: Set[str] = set(
    '✱✶✷✸✹✺✻✼✽✾✿✰✲✳✴✵'
    '❂❃❄❅❆❇'
    '✢✣✤✥✦✧'
    '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
)

# 圆点字符集（OutputBlock 首列）
DOT_CHARS: Set[str] = {'●', '⏺', '⚫', '•', '◉', '◦', '⏹'}

# 分割线字符集
DIVIDER_CHARS: Set[str] = set('─━═')

# 编号选项行正则（权限确认对话框特征：❯ 1. Yes / 2. No 等）
_NUMBERED_OPTION_RE = re.compile(r'^(?:❯\s*)?\d+[.)]\s+.+')
# 带 ❯ 光标的编号选项行正则（锚点）
_CURSOR_OPTION_RE = re.compile(r'^❯\s*(\d+)[.)]\s+.+')


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
    start_col 用于跳过首列特殊字符（圆点/星星/❯）。
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


def _is_divider_row(screen: pyte.Screen, row: int) -> bool:
    """判断整行是否为分割线：所有非空字符均为分割线字符，不限制行长度"""
    found = False
    for col in range(screen.columns):
        c = screen.buffer[row][col].data
        if not c.strip():
            continue
        if c not in DIVIDER_CHARS:
            return False  # 发现非分割线字符，立即短路
        found = True
    return found


def _has_numbered_options(screen: pyte.Screen, rows: List[int]) -> bool:
    """检测 rows 是否含编号选项行（需 ❯ 锚点 + ≥2 编号行）

    必须有至少一行匹配 _CURSOR_OPTION_RE（❯ 锚点），且总编号行 ≥2。
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
    """以 ❯ 锚点行出发，在 lines 中找出连续编号选项的范围。

    Returns: (cursor_idx, first_option_idx, last_option_idx)
             若未找到 ❯ 锚点，返回 (-1, -1, -1)
    """
    # 1. 找 ❯ 锚点
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
        m = re.match(r'^(?:❯\s*)?(\d+)[.)]\s+', line)
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
        m = re.match(r'^(?:❯\s*)?(\d+)[.)]\s+', line)
        if m:
            if int(m.group(1)) == expected:
                last_option_idx = i
                expected += 1
            else:
                break  # 编号不连续，停止
        # 非编号行（描述行）不打断扫描

    return (cursor_idx, first_option_idx, last_option_idx)


# ─── ScreenParser ─────────────────────────────────────────────────────────────

class ScreenParser:
    """终端屏幕解析器（会话级别持久化，跨帧保留 dot_row_cache）"""

    def __init__(self):
        # 帧间圆点缓存：布局模式切换时清空，防止残留行号产生幽灵 block
        self._dot_row_cache: Dict[int, Tuple[str, str, str, str, bool]] = {}
        # 最近一次解析到的输入区 ❯ 文本（用于 MessageQueue 追踪变更）
        self.last_input_text: str = ''
        self.last_input_ansi_text: str = ''
        # 最近一次 parse 的内部耗时（供外部写日志用）
        self.last_parse_timing: str = ''
        # 布局模式："normal" | "option" | "detail" | "agent_list" | "agent_detail"
        self.last_layout_mode: str = 'normal'

    def parse(self, screen: pyte.Screen) -> List[Component]:
        """解析 pyte 屏幕，返回组件列表"""
        import time as _time
        _t0 = _time.perf_counter()

        # Step 1：区域切分
        output_rows, input_rows, bottom_rows = self._split_regions(screen)
        _t1 = _time.perf_counter()

        # 布局模式判定
        prev_mode = self.last_layout_mode
        if input_rows:
            if _has_numbered_options(screen, input_rows):
                self.last_layout_mode = 'option'    # 2 分割线 + 编号选项
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

        # 模式切换时清空 dot_row_cache，防止残留行号产生幽灵 block
        if self.last_layout_mode != prev_mode:
            self._dot_row_cache.clear()

        # 提取输入区 ❯ 文本（用于 MessageQueue 追踪变更）
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
        if bottom_parts and not option and not agent_panel:
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
        """从底部向上找最后 2 条分割线，返回 (output_rows, input_rows, bottom_rows)"""
        # cursor_y 是当前光标所在行，内容不会超过此行。
        # 加 5 行余量应对光标尚未移动到最末行的情况，避免扫描 2000 行空行。
        scan_limit = min(screen.cursor.y + 5, screen.lines - 1)

        dividers: List[int] = []
        for row in range(scan_limit, -1, -1):
            if _is_divider_row(screen, row):
                dividers.append(row)
                if len(dividers) == 2:
                    break
        dividers.sort()

        if len(dividers) >= 2:
            div1, div2 = dividers[-2], dividers[-1]
            output_rows = self._trim_welcome(screen, list(range(div1)))
            input_rows = list(range(div1 + 1, div2))
            bottom_rows = list(range(div2 + 1, scan_limit + 1))
        elif len(dividers) == 1:
            div1 = dividers[0]
            output_rows = self._trim_welcome(screen, list(range(div1)))
            input_rows = []
            bottom_rows = list(range(div1 + 1, scan_limit + 1))
        else:
            output_rows = self._trim_welcome(screen, list(range(scan_limit + 1)))
            input_rows = []
            bottom_rows = []

        return output_rows, input_rows, bottom_rows

    def _trim_welcome(self, screen: pyte.Screen, rows: List[int]) -> List[int]:
        """去掉欢迎区域：跳过首列为空的前缀行，从第一个首列有内容的行开始"""
        for i, row in enumerate(rows):
            if _get_col0(screen, row).strip():
                return rows[i:]
        return []

    # ─── Step 2+3+4：输出区解析 ────────────────────────────────────────────

    def _cleanup_cache(self, screen: pyte.Screen, output_row_set: Set[int]):
        """清理 dot_row_cache 中不再有效的条目"""
        for row in list(self._dot_row_cache.keys()):
            if row not in output_row_set:
                # 行已不在输出区（屏幕滚动等）
                del self._dot_row_cache[row]
                continue
            col0 = _get_col0(screen, row)
            if col0.strip() and col0 not in DOT_CHARS:
                # 首列变为其他非圆点内容，缓存失效
                del self._dot_row_cache[row]

    def _parse_output_area(
        self, screen: pyte.Screen, rows: List[int]
    ) -> List[Component]:
        """切 Block 并分类"""
        if not rows:
            return []

        # 切 Block：首列有非空字符 OR 在 dot_row_cache 中（圆点闪烁隐去帧）→ Block 首行
        blocks: List[Tuple[int, List[int]]] = []
        current_first: Optional[int] = None
        current_rows: Optional[List[int]] = None

        for row in rows:
            col0 = _get_col0(screen, row)
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
            return OutputBlock(
                content=content, is_streaming=cached_blink, start_row=first_row,
                ansi_content=ansi_content, indicator=cached_ind, ansi_indicator=cached_ansi_ind,
            )

        if not col0.strip():
            return None

        lines = [_get_row_text(screen, r) for r in block_rows]

        # StatusLine：星星字符
        if col0 in STAR_CHARS:
            return self._parse_status_block(
                lines[0],
                ansi_first_line=_get_row_ansi_text(screen, first_row),
                indicator=col0,
                ansi_indicator=_get_col0_ansi(screen, first_row),
            )

        # UserInput：❯
        if col0 == '❯':
            text = lines[0][1:].strip()
            # 内容全是分割线字符（如 ❯─────...─）→ 装饰性分隔符，忽略
            if not text or all(c in DIVIDER_CHARS for c in text):
                return None
            ind = col0
            ansi_ind = _get_col0_ansi(screen, first_row)
            ansi_text = _get_row_ansi_text(screen, first_row, start_col=1).strip()
            return UserInput(text=text, ansi_text=ansi_text, indicator=ind, ansi_indicator=ansi_ind)

        # OutputBlock：圆点字符
        if col0 in DOT_CHARS:
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
            return OutputBlock(
                content=content, is_streaming=is_blink, start_row=first_row,
                ansi_content=ansi_content, indicator=ind, ansi_indicator=ansi_ind,
            )

        # 其他首列字符（装饰残留、欢迎区片段等），忽略
        return None

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

        # 入口检测：是否有编号选项行（需 ❯ 锚点）
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
            m = re.match(r'^(?:❯\s*)?(\d+)[.)]\s*(.+)', line)
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
        """提取输入区 ❯ 提示符后的当前输入文本（空提示符返回空字符串）"""
        for row in input_rows:
            if _get_col0(screen, row) == '❯':
                text = _get_row_text(screen, row)[1:].strip()
                # 排除纯分割线装饰行（如 ❯─────）
                if text and not all(c in DIVIDER_CHARS for c in text):
                    return text
        return ''

    def _extract_input_area_ansi_text(self, screen: pyte.Screen, input_rows: List[int]) -> str:
        """提取输入区 ❯ 提示符后的当前输入文本（ANSI 版本）"""
        for row in input_rows:
            if _get_col0(screen, row) == '❯':
                text = _get_row_text(screen, row)[1:].strip()
                if text and not all(c in DIVIDER_CHARS for c in text):
                    return _get_row_ansi_text(screen, row, start_col=1).strip()
        return ''

    def _parse_permission_area(
        self,
        screen: pyte.Screen,
        bottom_rows: List[int],
    ) -> Optional[OptionBlock]:
        """解析 1 条分割线布局下的权限确认区域，返回 OptionBlock(sub_type="permission")

        检测条件：bottom_rows 中含 ❯ 锚点 + ≥2 个编号选项行。
        通过 _find_contiguous_options 以 ❯ 为锚点双向扫描，只收集连续编号选项。
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
                m = re.match(r'^(?:❯\s*)?(\d+)[.)]\s*(.+)', line)
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

            # 匹配 agent 行：可选的 ❯ 前缀 + 名称 + (status)
            m = re.match(r'^(❯\s*)?(.+?)\s*\((running|completed|failed|killed)\)', line, re.IGNORECASE)
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
            m = re.match(r'^(?:❯\s*)?(\d+)[.)]\s+', line)
            if m:
                last_num = int(m.group(1))
                break

        if last_num == 0:
            return []

        overflow: List[int] = []
        expected = last_num + 1
        for row in bottom_rows[:2]:
            line = _get_row_text(screen, row).strip()
            m = re.match(r'^(?:❯\s*)?(\d+)[.)]\s+', line)
            if m and int(m.group(1)) == expected:
                overflow.append(row)
                expected += 1
            else:
                break

        return overflow



# ─── 底部栏 Agent 信息解析 ─────────────────────────────────────────────────────

def _parse_bottom_bar_agents(text: str) -> tuple:
    """解析底部栏中的后台 agent 信息

    返回 (has_background_agents, agent_count, agent_summary)
    """
    lower = text.lower()
    # 检测 "↓ to manage" 关键词（agent 模式的标志）
    if '↓ to manage' not in lower:
        return (False, 0, '')

    # 匹配 "N local agents" 或 "N agents"
    m = re.search(r'(\d+)\s+(local\s+)?agents?', lower)
    if m:
        count = int(m.group(1))
        # 提取原始摘要文本（保留原始大小写）
        summary_match = re.search(r'(\d+\s+(?:local\s+)?agents?)', text, re.IGNORECASE)
        summary = summary_match.group(1) if summary_match else f"{count} agents"
        return (True, count, summary)

    # 匹配 "(running)" 关键词（单个 agent 运行时的格式）
    if '(running)' in lower:
        # 提取 agent 名称：分割线前的部分
        parts = text.split('·')
        summary = parts[0].strip() if parts else text.strip()
        return (True, 1, summary)

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
        elif isinstance(c, StatusLine):
            parts.append(f"S:{c.action}:{c.elapsed}")
        elif isinstance(c, BottomBar):
            parts.append(f"BB:{c.text[:100]}")
    return '|'.join(parts)
