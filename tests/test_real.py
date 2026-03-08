#!/usr/bin/env python3
"""用真实数据测试渲染器"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import get_socket_path, list_active_sessions
from protocol import MessageType, InputMessage, encode_message, decode_message
from lark_client.rich_text_renderer import RichTextRenderer

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
    all_data = b""  # 收集所有原始数据

    # 发送输入
    print("发送: 你好")
    for data in [b'\xe4\xbd\xa0\xe5\xa5\xbd', b'\x1b', b'\r']:
        msg = InputMessage(data, "test")
        writer.write(encode_message(msg))
        await writer.drain()
        await asyncio.sleep(0.1)

    # 读取回复
    print("\n读取回复 (5秒)...")
    start = asyncio.get_event_loop().time()
    packet_count = 0

    while asyncio.get_event_loop().time() - start < 5:
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=0.1)
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
                        all_data += raw  # 累积原始数据
                        renderer.feed(raw)  # 喂入渲染器
                except:
                    pass
        except asyncio.TimeoutError:
            continue

    print(f"\n收到 {packet_count} 个包")
    print(f"原始数据总长: {len(all_data)} 字节")

    # 显示渲染结果
    print("\n=== pyte 渲染结果 (plain) ===")
    plain = renderer.get_plain_display()
    print(plain)

    print("\n=== pyte 渲染结果 (rich) ===")
    rich = renderer.get_rich_text()
    print(rich)

    # 显示 pyte 屏幕的前 10 行
    print("\n=== pyte screen.display 前 10 行 ===")
    for i, line in enumerate(renderer.screen.display[:10]):
        stripped = line.rstrip()
        if stripped:
            print(f"行{i}: {repr(stripped)}")

    writer.close()
    await writer.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())
