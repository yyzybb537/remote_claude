#!/usr/bin/env python3
"""PTY raw log 重放脚本

从 _pty_raw.log 逐帧喂入 pyte，每帧输出指定行范围的屏幕内容，
用于逐帧定位 pyte 与真实终端的差异。

用法：
    uv run python3 tools/replay_pty.py /tmp/remote-claude/cx_pty_raw.log --rows 54-62
    uv run python3 tools/replay_pty.py /tmp/remote-claude/cx_pty_raw.log --rows 54-62 --cols 231 --lines 2000
    uv run python3 tools/replay_pty.py /tmp/remote-claude/cx_pty_raw.log --rows 54-62 --search hello
"""

import argparse
import json
import sys
import unicodedata

try:
    import pyte
except ImportError:
    print("需要安装 pyte：pip install pyte", file=sys.stderr)
    sys.exit(1)


def get_char_width(ch: str) -> int:
    """返回字符显示宽度（CJK 全角 = 2，其余 = 1）"""
    if not ch:
        return 0
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ('W', 'F') else 1


def render_row(screen, row: int) -> tuple[str, str]:
    """渲染指定行，返回 (plain_text, bg_info)"""
    plain_parts = []
    row_bgs = set()

    for col in range(screen.columns):
        char = screen.buffer[row].get(col)
        if char is None:
            plain_parts.append(' ')
            continue
        data = char.data if char.data else ''
        if data:
            plain_parts.append(data)
        else:
            plain_parts.append('')
        bg = getattr(char, 'bg', 'default')
        if bg and bg != 'default':
            row_bgs.add(str(bg))

    plain = ''.join(plain_parts).rstrip()
    bg_info = ','.join(sorted(row_bgs)) if row_bgs else ''
    return plain, bg_info


def load_frames(path: str) -> list[dict]:
    """加载 _pty_raw.log 中的帧列表"""
    frames = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    frames.append(obj)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        print(f"文件不存在：{path}", file=sys.stderr)
        sys.exit(1)
    return frames


def main():
    parser = argparse.ArgumentParser(description='PTY raw log 逐帧重放工具')
    parser.add_argument('log_file', help='_pty_raw.log 文件路径')
    parser.add_argument('--rows', default='0-80',
                        help='要显示的行范围，格式 start-end（默认 0-80）')
    parser.add_argument('--cols', type=int, default=220,
                        help='终端列数（默认 220）')
    parser.add_argument('--lines', type=int, default=2000,
                        help='终端行数（默认 2000）')
    parser.add_argument('--search', default='',
                        help='在行内容中搜索的文本，只显示包含该文本的帧')
    parser.add_argument('--from-frame', type=int, default=0,
                        help='从第 N 帧开始（默认 0）')
    parser.add_argument('--max-frames', type=int, default=0,
                        help='最多处理 N 帧（默认 0=全部）')
    args = parser.parse_args()

    # 解析行范围
    try:
        row_parts = args.rows.split('-')
        row_start = int(row_parts[0])
        row_end = int(row_parts[1]) if len(row_parts) > 1 else row_start + 20
    except (ValueError, IndexError):
        print(f"无效的行范围格式：{args.rows}，应为 start-end", file=sys.stderr)
        sys.exit(1)

    # 加载帧
    frames = load_frames(args.log_file)
    if not frames:
        print("未找到任何帧数据", file=sys.stderr)
        sys.exit(1)

    print(f"共加载 {len(frames)} 帧，终端尺寸 {args.cols}×{args.lines}")
    print(f"显示行范围：{row_start}-{row_end}")
    if args.search:
        print(f"搜索关键词：'{args.search}'")
    print()

    # 初始化 pyte screen
    screen = pyte.Screen(args.cols, args.lines)
    stream = pyte.Stream(screen)

    processed = 0
    for i, frame in enumerate(frames):
        if i < args.from_frame:
            continue
        if args.max_frames > 0 and processed >= args.max_frames:
            break

        # 解析帧数据
        ts = frame.get('ts', '')
        data_hex = frame.get('data', '')
        if isinstance(data_hex, str):
            try:
                data = bytes.fromhex(data_hex)
            except ValueError:
                data = data_hex.encode('utf-8', errors='replace')
        elif isinstance(data_hex, bytes):
            data = data_hex
        else:
            continue

        # 喂入 pyte
        stream.feed(data.decode('utf-8', errors='replace'))
        processed += 1

        # 渲染指定行范围
        row_texts = []
        has_match = False
        for row in range(row_start, min(row_end + 1, args.lines)):
            plain, bg_info = render_row(screen, row)
            if args.search and args.search in plain:
                has_match = True
            row_texts.append((row, plain, bg_info))

        # 如果有搜索词，只显示命中的帧
        if args.search and not has_match:
            continue

        # 输出帧信息
        print(f"=== Frame {i} @ {ts}  len={len(data)} ===")
        for row, plain, bg_info in row_texts:
            if plain:
                if bg_info:
                    print(f"  Row {row:3d}: [{plain}]  bg={bg_info}")
                else:
                    print(f"  Row {row:3d}: [{plain}]")
            elif bg_info:
                print(f"  Row {row:3d}: []  bg={bg_info} (背景色空行)")
            # 纯空行不输出
        print()


if __name__ == '__main__':
    main()
