#!/usr/bin/env python3
"""测试 Codex 选项交互模式解析（❯ 光标修复验证）

对应修复：codex_parser.py 中将 > (U+003E) 扩展为 [>❯]，以支持
Codex CLI 在高亮选中选项时使用的 ❯ (U+276F) 光标字符。

CLAUDE.md 示例布局：
  Implement this plan?
  1. Yes, implement this plan  Switch to Default...
  ❯ 2. No, stay in Plan mode   Continue planning...
"""

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pyte
from pyte.screens import Char

from server.parsers.codex_parser import (
    CodexParser,
    _has_numbered_options,
    _find_contiguous_options,
    _is_white_color,
    _is_light_blue_color,
    _is_pure_bg_row,
    DIVIDER_CHARS,
)


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────

def make_screen(rows=50, cols=220):
    return pyte.Screen(cols, rows)


def write_row(screen, row, text, fg='default', bg='default'):
    """将 text 从 col=0 开始写入 screen 的指定行"""
    for col, ch in enumerate(text):
        screen.buffer[row][col] = Char(data=ch, fg=fg, bg=bg)
    # 其余列填充空格
    for col in range(len(text), screen.columns):
        screen.buffer[row][col] = Char(data=' ', fg=fg, bg=bg)


def fill_row_bg(screen, row, bg_color):
    """整行填充背景色（无文字，作为背景色分割线）"""
    for col in range(screen.columns):
        screen.buffer[row][col] = Char(data=' ', bg=bg_color)


# ─── _has_numbered_options 测试 ────────────────────────────────────────────────

def test_has_numbered_options_with_gt_cursor():
    """旧 > 光标：_has_numbered_options 应返回 True（回归保证）"""
    screen = make_screen()
    # 输入区行：row 10=问题，row 11=选项1，row 12=选中选项（> 光标）
    write_row(screen, 10, 'Implement this plan?')
    write_row(screen, 11, '1. Yes, implement this plan')
    write_row(screen, 12, '> 2. No, stay in Plan mode')

    assert _has_numbered_options(screen, [10, 11, 12]), \
        "> 光标应被识别为锚点"
    print("✓ > 光标 _has_numbered_options 通过")


def test_has_numbered_options_with_heavy_cursor():
    """新 ❯ 光标（U+276F）：_has_numbered_options 应返回 True（修复验证）"""
    screen = make_screen()
    write_row(screen, 10, 'Implement this plan?')
    write_row(screen, 11, '1. Yes, implement this plan')
    write_row(screen, 12, '❯ 2. No, stay in Plan mode')

    assert _has_numbered_options(screen, [10, 11, 12]), \
        "❯ 光标应被识别为锚点（修复前此处失败）"
    print("✓ ❯ 光标 _has_numbered_options 通过")


def test_has_numbered_options_no_cursor():
    """无光标行时应返回 False"""
    screen = make_screen()
    write_row(screen, 10, 'Implement this plan?')
    write_row(screen, 11, '1. Yes, implement this plan')
    write_row(screen, 12, '2. No, stay in Plan mode')  # 无锚点

    assert not _has_numbered_options(screen, [10, 11, 12]), \
        "无锚点行时应返回 False"
    print("✓ 无光标行 _has_numbered_options 通过")


def test_has_numbered_options_only_one_option():
    """只有 1 个编号选项（含锚点），不满足 ≥2 条件，应返回 False"""
    screen = make_screen()
    write_row(screen, 10, '❯ 1. Only option')

    assert not _has_numbered_options(screen, [10]), \
        "单一选项不满足 ≥2 条件"
    print("✓ 单选项 _has_numbered_options 通过")


# ─── _find_contiguous_options 测试 ────────────────────────────────────────────

_NAV_RE = re.compile(r'(Enter to select|↑/↓|Esc to cancel|to navigate)')


def test_find_contiguous_options_gt_cursor():
    """旧 > 光标：_find_contiguous_options 正确定位锚点和范围"""
    lines = [
        'Implement this plan?',
        '1. Yes, implement this plan',
        '> 2. No, stay in Plan mode',
    ]
    cursor_idx, first_opt_idx, last_opt_idx = _find_contiguous_options(lines, _NAV_RE)
    assert cursor_idx == 2, f"锚点应在 index 2，实际 {cursor_idx}"
    assert first_opt_idx == 1, f"首选项应在 index 1，实际 {first_opt_idx}"
    assert last_opt_idx == 2, f"末选项应在 index 2，实际 {last_opt_idx}"
    print("✓ > 光标 _find_contiguous_options 通过")


def test_find_contiguous_options_heavy_cursor():
    """新 ❯ 光标：_find_contiguous_options 正确定位锚点和范围（修复验证）"""
    lines = [
        'Implement this plan?',
        '1. Yes, implement this plan',
        '❯ 2. No, stay in Plan mode',
    ]
    cursor_idx, first_opt_idx, last_opt_idx = _find_contiguous_options(lines, _NAV_RE)
    assert cursor_idx == 2, f"锚点应在 index 2，实际 {cursor_idx}（修复前此处为 -1）"
    assert first_opt_idx == 1, f"首选项应在 index 1，实际 {first_opt_idx}"
    assert last_opt_idx == 2, f"末选项应在 index 2，实际 {last_opt_idx}"
    print("✓ ❯ 光标 _find_contiguous_options 通过")


def test_find_contiguous_options_cursor_first():
    """❯ 光标在首位（第 1 个被选中），仅向后扫描"""
    lines = [
        '❯ 1. First option',
        '2. Second option',
        '3. Third option',
    ]
    cursor_idx, first_opt_idx, last_opt_idx = _find_contiguous_options(lines, _NAV_RE)
    assert cursor_idx == 0
    assert first_opt_idx == 0
    assert last_opt_idx == 2
    print("✓ ❯ 光标在首位 _find_contiguous_options 通过")


# ─── _parse_input_area 端到端测试 ──────────────────────────────────────────────

def build_plan_mode_screen():
    """构造真实 Codex Plan Mode 3-bg-divider 布局的 pyte Screen。

    布局（行号，匹配真实 screen.log）：
      row 45: bg-divider（外层顶边界，bg + 无文字）
      row 46: 'Implement this plan?'     ← 问题行（有 bg）
      row 47: bg-divider（内部空行，bg + 无文字，外观与分割线相同）
      row 48: '1. Yes, ...'              ← 未选中选项（有 bg）
      row 49: '❯ 2. No, ...'            ← 选中选项（❯ 光标，青色高亮，有 bg）
      row 50: bg-divider（外层底边界，bg + 无文字）
      row 51: 'Press enter to confirm...' ← 底部导航提示（无 bg）

    关键：row 47 与 row 45/50 外观相同（bg + 无文字），旧算法将 47 误识别为第 2 条
    分割线，导致 input_rows=[48,49]，question 被排出。新 zone 算法取最外层边界对
    (45, 50)，正确得到 input_rows=[46,47,48,49]。
    """
    BG = '2a2a2a'
    screen = make_screen(rows=60)  # 扩大到 60 行以容纳行号 51

    fill_row_bg(screen, 45, BG)   # 外层顶 bg-divider
    write_row(screen, 46, 'Implement this plan?', bg=BG)
    fill_row_bg(screen, 47, BG)   # 内部空行（外观同分割线，旧算法误判）
    write_row(screen, 48, '1. Yes, implement this plan  Switch to Default mode', bg=BG)
    # ❯ 光标行：选中状态，青色高亮
    write_row(screen, 49, '❯ 2. No, stay in Plan mode   Continue planning...', fg='cyan', bg=BG)
    fill_row_bg(screen, 50, BG)   # 外层底 bg-divider
    write_row(screen, 51, 'Press enter to confirm or esc to go back')  # 无 bg

    screen.cursor.y = 49
    screen.cursor.x = 50
    return screen


def test_parse_input_area_with_heavy_cursor():
    """新 zone 算法：3-bg-divider 布局下 input_rows 包含 question 行（修复验证）"""
    parser = CodexParser()
    screen = build_plan_mode_screen()

    # zone 算法正确找到外层边界对 (45, 50)，input_rows = [46,47,48,49]
    input_rows = [46, 47, 48, 49]
    bottom_rows = [51]
    overflow_out = []

    result = parser._parse_input_area(screen, input_rows, bottom_rows, overflow_out)

    assert result is not None, \
        "应解析出 OptionBlock（旧算法 input_rows=[48,49] 时此处返回 None）"
    assert result.sub_type == 'option', \
        f"sub_type 应为 'option'，实际 '{result.sub_type}'"
    assert result.question == 'Implement this plan?', \
        f"question 应为 'Implement this plan?'，实际 {result.question!r}"
    assert len(result.options) == 2, \
        f"应有 2 个选项，实际 {len(result.options)}"

    labels = [opt['label'] for opt in result.options]
    assert any('Yes' in lb for lb in labels), f"选项中应含 Yes，实际 {labels}"
    assert any('No' in lb for lb in labels), f"选项中应含 No，实际 {labels}"

    print(f"  question: {result.question!r}")
    print(f"  options:  {result.options}")
    print("✓ _parse_input_area ❯ 光标 3-divider 端到端测试通过")


def test_parse_input_area_with_laquo_cursor():
    """_parse_input_area 使用 › (U+203A) 光标时应成功解析（实际 screen.log 布局）"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen(rows=60)

    fill_row_bg(screen, 45, BG)   # 外层顶 bg-divider
    write_row(screen, 46, 'Implement this plan?', bg=BG)
    fill_row_bg(screen, 47, BG)   # 内部空行
    write_row(screen, 48, '1. Yes, implement this plan  Switch to Default mode', bg=BG)
    # › 光标行（U+203A，Codex 实际使用的选中光标）
    write_row(screen, 49, '› 2. No, stay in Plan mode   Continue planning...', fg='cyan', bg=BG)
    fill_row_bg(screen, 50, BG)   # 外层底 bg-divider
    write_row(screen, 51, 'Press enter to confirm or esc to go back')  # 无 bg

    screen.cursor.y = 49
    screen.cursor.x = 50

    # zone 算法找到 input_rows=[46,47,48,49]
    input_rows = [46, 47, 48, 49]
    bottom_rows = [51]
    overflow_out = []

    result = parser._parse_input_area(screen, input_rows, bottom_rows, overflow_out)

    assert result is not None, \
        "› 光标应被识别（修复前此处失败：_CURSOR_OPTION_RE 不含 ›）"
    assert result.sub_type == 'option'
    assert result.question == 'Implement this plan?', \
        f"question 应为 'Implement this plan?'，实际 {result.question!r}"
    assert len(result.options) == 2, \
        f"应有 2 个选项，实际 {len(result.options)}"

    labels = [opt['label'] for opt in result.options]
    assert any('Yes' in lb for lb in labels), f"选项中应含 Yes，实际 {labels}"
    assert any('No' in lb for lb in labels), f"选项中应含 No，实际 {labels}"

    print(f"  question: {result.question!r}")
    print(f"  options:  {result.options}")
    print("✓ _parse_input_area › 光标端到端测试通过")


def test_parse_input_area_with_gt_cursor():
    """_parse_input_area 使用 > 光标时仍能正常解析（回归保证）"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen()

    fill_row_bg(screen, 38, BG)
    write_row(screen, 39, 'Choose an option:', bg=BG)
    write_row(screen, 40, '1. Continue', bg=BG)
    write_row(screen, 41, '> 2. Abort', bg=BG)
    fill_row_bg(screen, 42, BG)

    input_rows = [39, 40, 41]
    result = parser._parse_input_area(screen, input_rows, [], [])

    assert result is not None, "> 光标回归：应解析出 OptionBlock"
    assert len(result.options) == 2
    print("✓ _parse_input_area > 光标回归测试通过")


# ─── _parse_permission_area 测试 ──────────────────────────────────────────────

def test_parse_permission_area_with_heavy_cursor():
    """_parse_permission_area 使用 ❯ 光标时正确解析（修复验证）"""
    parser = CodexParser()
    screen = make_screen()

    write_row(screen, 10, 'Bash command')
    write_row(screen, 11, 'rm -rf /tmp/test')
    write_row(screen, 12, 'Do you want to proceed?')
    write_row(screen, 13, '1. Yes, run this command')
    write_row(screen, 14, '❯ 2. No, cancel')

    bottom_rows = [10, 11, 12, 13, 14]
    result = parser._parse_permission_area(screen, bottom_rows)

    assert result is not None, \
        "_parse_permission_area 应解析出 OptionBlock（修复前此处返回 None）"
    assert result.sub_type == 'permission'
    assert len(result.options) == 2

    labels = [opt['label'] for opt in result.options]
    assert any('Yes' in lb for lb in labels), f"选项中应含 Yes，实际 {labels}"
    assert any('No' in lb for lb in labels), f"选项中应含 No，实际 {labels}"

    print(f"  title:    {result.title!r}")
    print(f"  question: {result.question!r}")
    print(f"  options:  {result.options}")
    print("✓ _parse_permission_area ❯ 光标端到端测试通过")


# ─── 辅助函数测试 ─────────────────────────────────────────────────────────────

def test_is_white_color():
    """_is_white_color 应正确识别白色"""
    assert _is_white_color('white'), "white 应为白色"
    assert _is_white_color('brightwhite'), "brightwhite 应为白色"
    assert _is_white_color('ffffff'), "hex ffffff 应为白色"
    assert not _is_white_color('default'), "default 不是白色"
    assert not _is_white_color('cyan'), "cyan 不是白色"
    assert not _is_white_color('2a2a2a'), "暗色 hex 不是白色"
    print("✓ _is_white_color 测试通过")


def test_is_light_blue_color():
    """_is_light_blue_color 应正确识别浅蓝/青色"""
    assert _is_light_blue_color('cyan'), "cyan 应为浅蓝/青色"
    assert _is_light_blue_color('brightcyan'), "brightcyan 应为浅蓝/青色"
    assert _is_light_blue_color('brightblue'), "brightblue 应为浅蓝/青色"
    assert not _is_light_blue_color('default'), "default 不是浅蓝色"
    assert not _is_light_blue_color('red'), "red 不是浅蓝色"
    print("✓ _is_light_blue_color 测试通过")


def test_is_pure_bg_row():
    """_is_pure_bg_row 应正确识别纯背景色行（无文字）"""
    BG = '2a2a2a'
    screen = make_screen()

    # 纯背景色行（bg + 无文字）
    fill_row_bg(screen, 10, BG)
    assert _is_pure_bg_row(screen, 10), "纯背景色行应返回 True"

    # 有文字的背景色行（底部栏）
    write_row(screen, 11, 'model info', bg=BG)
    assert not _is_pure_bg_row(screen, 11), "有文字的 bg 行不是纯背景色行"

    # 无背景色的空行
    assert not _is_pure_bg_row(screen, 20), "无背景色行应返回 False"

    print("✓ _is_pure_bg_row 测试通过")


# ─── _find_bg_region 测试 ──────────────────────────────────────────────────────

def test_find_bg_region_normal_mode():
    """普通模式：3 行 bg 区域（纯bg + › + 纯bg），_find_bg_region 应返回正确边界对"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen()

    fill_row_bg(screen, 45, BG)                          # 上边界（纯背景色）
    write_row(screen, 46, '› current input', bg=BG)     # 内容行（有文字）
    fill_row_bg(screen, 47, BG)                          # 下边界（纯背景色）
    write_row(screen, 48, 'model info', bg=BG)           # 底部栏（有文字，不计入区域）

    screen.cursor.y = 47

    result = parser._find_bg_region(screen, 48)
    assert result is not None, "_find_bg_region 应找到背景色区域"
    region_start, region_end = result
    assert region_start == 45, f"区域上边界应为 45，实际 {region_start}"
    assert region_end == 47, f"区域下边界应为 47，实际 {region_end}"
    print(f"  region: ({region_start}, {region_end})")
    print("✓ _find_bg_region 普通模式测试通过")


def test_find_bg_region_option_mode():
    """选项模式：6 行 bg 区域（含上方签名），_find_bg_region 应返回最外层边界对"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen(rows=60)

    fill_row_bg(screen, 45, BG)   # 外层顶边界
    write_row(screen, 46, 'Implement this plan?', bg=BG)
    fill_row_bg(screen, 47, BG)   # 内部空行（外观同边界）
    write_row(screen, 48, '1. Yes', bg=BG)
    write_row(screen, 49, '› 2. No', fg='cyan', bg=BG)
    fill_row_bg(screen, 50, BG)   # 外层底边界

    screen.cursor.y = 50

    result = parser._find_bg_region(screen, 50)
    assert result is not None, "_find_bg_region 应找到背景色区域"
    region_start, region_end = result
    assert region_start == 45, f"区域上边界应为 45，实际 {region_start}"
    assert region_end == 50, f"区域下边界应为 50，实际 {region_end}"
    print(f"  region: ({region_start}, {region_end})")
    print("✓ _find_bg_region 选项模式测试通过")


def test_bg_region_minimum_size():
    """只有 2 行纯 bg（无内容行）→ _find_bg_region 应返回 None"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen()

    fill_row_bg(screen, 45, BG)   # 纯背景色行1
    fill_row_bg(screen, 46, BG)   # 纯背景色行2（只有 2 行，无内容）

    screen.cursor.y = 46

    result = parser._find_bg_region(screen, 46)
    assert result is None, "2 行区域（无内容行）不满足最小尺寸，应返回 None"
    print("✓ _find_bg_region 最小尺寸检测通过")


# ─── _determine_input_mode 测试 ───────────────────────────────────────────────

def test_determine_input_mode_normal():
    """白色 › 在首行行首 → _determine_input_mode 应返回 'normal'"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen()

    fill_row_bg(screen, 45, BG)
    write_row(screen, 46, '› current input', fg='white', bg=BG)
    fill_row_bg(screen, 47, BG)

    content_rows = [46]
    mode = parser._determine_input_mode(screen, 45, content_rows)
    assert mode == 'normal', f"白色 › 应判定为 normal，实际 {mode!r}"
    print("✓ _determine_input_mode normal 测试通过")


def test_determine_input_mode_option_by_context():
    """上方有空行+分割线+空行 → _determine_input_mode 应返回 'option'"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen(rows=60)

    # 上方签名：空行 + 分割线 + 空行（默认背景色）
    write_row(screen, 41, '')                            # row 41：空行（默认 bg）
    write_row(screen, 42, '─' * 50)                     # row 42：分割线
    write_row(screen, 43, '')                            # row 43：空行（默认 bg）
    # 背景色区域起始
    fill_row_bg(screen, 44, BG)                          # 上边界（region_start=44）
    write_row(screen, 45, 'Implement this plan?', bg=BG)
    fill_row_bg(screen, 46, BG)
    write_row(screen, 47, '1. Yes', bg=BG)
    write_row(screen, 48, '› 2. No', fg='cyan', bg=BG)
    fill_row_bg(screen, 49, BG)

    content_rows = [45, 46, 47, 48]
    mode = parser._determine_input_mode(screen, 44, content_rows)
    assert mode == 'option', f"上方有分割线签名应判定为 option，实际 {mode!r}"
    print("✓ _determine_input_mode option（上方签名）测试通过")


def test_determine_input_mode_option_by_color():
    """浅蓝色 › + 整行同色 → _determine_input_mode 应返回 'option'"""
    BG = '2a2a2a'
    parser = CodexParser()
    screen = make_screen()

    fill_row_bg(screen, 45, BG)
    write_row(screen, 46, 'Implement this plan?', bg=BG)
    fill_row_bg(screen, 47, BG)
    write_row(screen, 48, '1. Yes', bg=BG)
    # 整行浅蓝色
    write_row(screen, 49, '› 2. No, stay in Plan mode', fg='cyan', bg=BG)
    fill_row_bg(screen, 50, BG)

    content_rows = [46, 47, 48, 49]
    mode = parser._determine_input_mode(screen, 45, content_rows)
    assert mode == 'option', f"浅蓝色 › 且整行同色应判定为 option，实际 {mode!r}"
    print("✓ _determine_input_mode option（浅蓝色）测试通过")


# ─── 主入口 ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=== _has_numbered_options 测试 ===")
    test_has_numbered_options_with_gt_cursor()
    test_has_numbered_options_with_heavy_cursor()
    test_has_numbered_options_no_cursor()
    test_has_numbered_options_only_one_option()

    print("\n=== _find_contiguous_options 测试 ===")
    test_find_contiguous_options_gt_cursor()
    test_find_contiguous_options_heavy_cursor()
    test_find_contiguous_options_cursor_first()

    print("\n=== _parse_input_area 端到端测试 ===")
    test_parse_input_area_with_heavy_cursor()
    test_parse_input_area_with_laquo_cursor()
    test_parse_input_area_with_gt_cursor()

    print("\n=== _parse_permission_area 测试 ===")
    test_parse_permission_area_with_heavy_cursor()

    print("\n=== 辅助函数测试 ===")
    test_is_white_color()
    test_is_light_blue_color()
    test_is_pure_bg_row()

    print("\n=== _find_bg_region 测试 ===")
    test_find_bg_region_normal_mode()
    test_find_bg_region_option_mode()
    test_bg_region_minimum_size()

    print("\n=== _determine_input_mode 测试 ===")
    test_determine_input_mode_normal()
    test_determine_input_mode_option_by_context()
    test_determine_input_mode_option_by_color()

    print("\n" + "=" * 50)
    print("所有 Codex 选项交互模式解析测试通过！")
    print("=" * 50)
