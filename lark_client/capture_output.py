"""
捕获 remote_claude 的实际输出用于分析
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.protocol import Message, MessageType, decode_message
from utils.session import get_socket_path


async def capture_output(session_name: str, duration: int = 30):
    """捕获会话输出"""
    socket_path = get_socket_path(session_name)

    if not socket_path.exists():
        print(f"会话 {session_name} 不存在")
        return

    print(f"连接到 {session_name}...")

    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))

    print(f"已连接，捕获 {duration} 秒的输出...")
    print("=" * 60)

    buffer = b""
    outputs = []

    async def read_messages():
        nonlocal buffer
        while True:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=1.0)
                if not data:
                    break
                buffer += data

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        msg = decode_message(line)
                        if msg.type == MessageType.OUTPUT:
                            raw_data = msg.get_data()
                            outputs.append(raw_data)
                            print(f"收到 {len(raw_data)} 字节:")
                            print(f"  原始: {raw_data[:100]}...")
                            print(f"  解码: {raw_data.decode('utf-8', errors='replace')[:100]}...")
                            print()
                    except Exception as e:
                        print(f"解析错误: {e}")
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"读取错误: {e}")
                break

    try:
        await asyncio.wait_for(read_messages(), timeout=duration)
    except asyncio.TimeoutError:
        pass

    writer.close()
    await writer.wait_closed()

    print("=" * 60)
    print(f"共收到 {len(outputs)} 条输出消息")

    # 保存原始输出到文件
    output_file = Path("/tmp/claude_raw_output.bin")
    with open(output_file, "wb") as f:
        for data in outputs:
            f.write(data)
            f.write(b"\n---\n")

    print(f"原始输出已保存到 {output_file}")

    # 合并并分析
    all_data = b"".join(outputs)
    print(f"\n合并后总长度: {len(all_data)} 字节")
    print(f"合并后内容:\n{all_data.decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    session = sys.argv[1] if len(sys.argv) > 1 else "test"
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    asyncio.run(capture_output(session, duration))
