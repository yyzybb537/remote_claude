#!/usr/bin/env python3
"""端到端测试：模拟完整的 lark_client 处理流程"""

import asyncio
import sys
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import get_socket_path, list_active_sessions
from protocol import MessageType, InputMessage, encode_message, decode_message
from lark_client.rich_text_renderer import RichTextRenderer

def clean_rich_text(rich_text: str) -> str:
    """模拟 session_bridge._clean_rich_text"""
    def strip_tags(text):
        return re.sub(r'<[^>]+>', '', text)

    lines = rich_text.split('\n')
    result_lines = []

    for line in lines:
        plain_line = strip_tags(line)
        stripped = plain_line.strip()

        if not stripped:
            continue
        if '? for shortcuts' in plain_line:
            continue
        if 'esc to' in plain_line.lower():
            continue
        if all(c in '─━═-–—│╭╮╰╯┌┐└┘├┤┬┴┼ ' for c in stripped):
            continue
        if stripped.startswith(('╭', '╰', '│', '┌', '└')):
            continue
        if '▐▛' in stripped or '▜█' in stripped or '▝▜' in stripped:
            continue

        result_lines.append(line.strip())

    return '\n'.join(result_lines).strip()

def clean_output(text: str) -> str:
    """模拟 lark_handler._clean_output"""
    # 移除 ANSI 转义码
    text = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\][^\x07]*\x07', '', text)
    text = re.sub(r'\x1b[^[\]a-zA-Z]*[a-zA-Z]', '', text)
    text = re.sub(r'\[\??\d+[a-zA-Z]', '', text)
    text = re.sub(r'\[\d+(?:;\d+)*;?[a-zA-Z]?', '', text)
    text = re.sub(r';\d+;\d+;\d+m', '', text)
    text = re.sub(r'\d+;\d+m', '', text)
    text = re.sub(r'\d+m', '', text)
    text = re.sub(r'\d+;', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # 移除动画文本
    text = re.sub(r'Evaporating…?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Seasoning…?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Whirring…?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Scurrying…?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Simmering…?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Thinking\.{0,3}', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b[a-z]{1,3}…', '', text)

    # 移除加载动画符号（保留 ❯ 和 ⏺）
    text = re.sub(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠐⠂✻✳]', '', text)

    # 移除界面提示
    text = re.sub(r'\([^)]*esc to[^)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[Ee]sc to (?:interrupt|clear)(?:\s+again)?', '', text)
    text = re.sub(r'·\s*thinking\)?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'·', '', text)

    # 按行清理
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if '? for shortcuts' in line:
            continue
        clean_lines.append(stripped)

    return '\n'.join(clean_lines).strip()

async def main():
    sessions = list_active_sessions()
    if not sessions:
        print("没有可用会话")
        return

    session_name = sessions[0]["name"]
    socket_path = get_socket_path(session_name)
    print(f"连接到: {session_name}")

    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))

    renderer = RichTextRenderer(200, 100)
    buffer = b""

    # 发送输入
    print("发送: 测试")
    for data in [b'\xe6\xb5\x8b\xe8\xaf\x95', b'\x1b', b'\r']:  # "测试"
        msg = InputMessage(data, "test")
        writer.write(encode_message(msg))
        await writer.drain()
        await asyncio.sleep(0.1)

    # 等待 1 秒（模拟 _output_delay）
    print("等待 1 秒...")
    await asyncio.sleep(1.0)

    # 读取所有输出
    print("读取输出...")
    packet_count = 0

    while True:
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=0.5)
            if not data:
                break
            buffer += data

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                try:
                    msg = decode_message(line)
                    if msg.type == MessageType.OUTPUT:
                        raw = msg.get_data()
                        packet_count += 1
                        renderer.feed(raw)
                except:
                    pass
        except asyncio.TimeoutError:
            break

    print(f"\n收到 {packet_count} 个包")

    # 模拟 session_bridge 的处理
    print("\n=== Step 1: renderer.get_rich_text() ===")
    rich_text = renderer.get_rich_text()
    print(rich_text[:500] if len(rich_text) > 500 else rich_text)

    print("\n=== Step 2: session_bridge._clean_rich_text() ===")
    cleaned_by_bridge = clean_rich_text(rich_text)
    print(cleaned_by_bridge[:500] if len(cleaned_by_bridge) > 500 else cleaned_by_bridge)

    # 模拟 lark_handler 的处理
    print("\n=== Step 3: lark_handler._clean_output() ===")
    final_output = clean_output(cleaned_by_bridge)
    print(final_output[:500] if len(final_output) > 500 else final_output)

    writer.close()
    await writer.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())
