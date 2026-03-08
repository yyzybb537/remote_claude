#!/usr/bin/env python3
"""测试直接连接到 Claude 会话"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import get_socket_path, list_active_sessions
from protocol import Message, MessageType, InputMessage, OutputMessage, encode_message, decode_message
from lark_client.rich_text_renderer import RichTextRenderer

async def test_session():
    # 列出可用会话
    sessions = list_active_sessions()
    print(f"可用会话: {sessions}")

    if not sessions:
        print("没有可用会话，请先启动一个会话")
        return

    session_name = sessions[0]["name"]
    socket_path = get_socket_path(session_name)

    print(f"连接到会话: {session_name}")
    print(f"Socket: {socket_path}")

    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))

    renderer = RichTextRenderer(200, 100)
    buffer = b""

    # 读取几秒的输出
    print("\n=== 读取历史输出 (3秒) ===")

    async def read_messages():
        nonlocal buffer
        for _ in range(30):  # 最多读 30 次
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
                            raw_data = msg.get_data()
                            print(f"\n--- 收到输出包: {len(raw_data)} 字节 ---")
                            print(f"原始 bytes: {raw_data[:100]}...")
                            print(f"解码文本: {raw_data.decode('utf-8', errors='replace')[:100]}...")

                            # 测试渲染
                            renderer.clear()
                            renderer.feed(raw_data)
                            plain = renderer.get_plain_display()
                            print(f"渲染结果: {plain[:100]}...")
                    except Exception as e:
                        print(f"解析错误: {e}")
            except asyncio.TimeoutError:
                continue

    await read_messages()

    # 发送输入
    print("\n=== 发送输入: '你好' ===")

    # 发送文本
    msg = InputMessage(b'\xe4\xbd\xa0\xe5\xa5\xbd', "test_client")  # "你好"
    writer.write(encode_message(msg))
    await writer.drain()

    await asyncio.sleep(0.1)

    # 发送 Escape
    msg = InputMessage(b'\x1b', "test_client")
    writer.write(encode_message(msg))
    await writer.drain()

    await asyncio.sleep(0.1)

    # 发送 Enter
    msg = InputMessage(b'\r', "test_client")
    writer.write(encode_message(msg))
    await writer.drain()

    print("\n=== 读取回复 (5秒) ===")

    # 收集所有输出
    all_outputs = []

    async def read_response():
        nonlocal buffer
        start = asyncio.get_event_loop().time()
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
                            raw_data = msg.get_data()
                            all_outputs.append(raw_data)
                            print(f"\n--- 收到输出包 #{len(all_outputs)}: {len(raw_data)} 字节 ---")

                            # 检查是否有清屏命令
                            if b'\x1b[2J' in raw_data:
                                print("  [包含清屏命令]")
                            if b'\x1b[H' in raw_data:
                                print("  [包含光标归位命令]")

                            text = raw_data.decode('utf-8', errors='replace')
                            # 显示可见字符部分
                            visible = ''.join(c if c.isprintable() or c in '\n\r' else f'[{ord(c):02x}]' for c in text[:200])
                            print(f"  可见内容: {visible}")
                    except Exception as e:
                        print(f"解析错误: {e}")
            except asyncio.TimeoutError:
                continue

    await read_response()

    # 分析最终结果
    print("\n=== 分析 ===")
    print(f"总共收到 {len(all_outputs)} 个输出包")

    if all_outputs:
        print("\n最后一个包的渲染结果:")
        renderer.clear()
        renderer.feed(all_outputs[-1])
        print(renderer.get_plain_display())

        print("\n所有包累积的渲染结果:")
        renderer.clear()
        for data in all_outputs:
            renderer.feed(data)
        print(renderer.get_plain_display())

    writer.close()
    await writer.wait_closed()

if __name__ == '__main__':
    asyncio.run(test_session())
