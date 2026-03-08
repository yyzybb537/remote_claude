"""
模拟完整的 Lark 对话流程测试
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lark_client.session_bridge import SessionBridge, SessionManager


class MockConversation:
    """模拟多轮对话测试"""

    def __init__(self, session_name: str = "test"):
        self.session_name = session_name
        self.received_outputs = []
        self.bridge = None

    def on_output(self, text: str):
        """输出回调"""
        print(f"\n{'='*50}")
        print(f"[收到 Claude 回复] ({len(text)} 字符)")
        print(f"{'='*50}")
        print(text)
        print(f"{'='*50}\n")
        self.received_outputs.append(text)

    async def connect(self) -> bool:
        """连接到会话"""
        self.bridge = SessionBridge(self.session_name, self.on_output)
        if await self.bridge.connect():
            print(f"[Mock] 已连接到会话 '{self.session_name}'")
            return True
        else:
            print(f"[Mock] 连接失败")
            return False

    async def send_and_wait(self, message: str, wait_time: float = 5.0) -> str:
        """发送消息并等待回复"""
        print(f"\n[Mock] 发送消息: {message}")
        self.received_outputs.clear()

        if await self.bridge.send_input(message):
            print(f"[Mock] 消息已发送，等待回复 ({wait_time} 秒)...")
            await asyncio.sleep(wait_time)

            if self.received_outputs:
                return '\n'.join(self.received_outputs)
            else:
                return "(无回复)"
        else:
            return "(发送失败)"

    async def disconnect(self):
        """断开连接"""
        if self.bridge:
            await self.bridge.disconnect()
            print("[Mock] 已断开连接")


async def run_conversation_test():
    """运行多轮对话测试"""
    print("=" * 60)
    print("多轮对话模拟测试")
    print("=" * 60)

    # 测试对话列表
    conversations = [
        "你好",
        "1+1等于几?",
        "用Python写一个hello world",
    ]

    mock = MockConversation("test")

    if not await mock.connect():
        print("[错误] 无法连接到 test 会话")
        print("请先启动会话: python remote_claude.py start test")
        return

    try:
        for i, message in enumerate(conversations, 1):
            print(f"\n{'#'*60}")
            print(f"# 第 {i} 轮对话")
            print(f"{'#'*60}")

            response = await mock.send_and_wait(message, wait_time=8.0)

            print(f"\n[结果] 第 {i} 轮:")
            print(f"  输入: {message}")
            print(f"  输出: {response[:100]}..." if len(response) > 100 else f"  输出: {response}")

            # 检查回复质量
            if response == "(无回复)":
                print("  状态: ❌ 未收到回复")
            elif response == "(发送失败)":
                print("  状态: ❌ 发送失败")
            elif len(response) < 5:
                print("  状态: ⚠️ 回复太短")
            else:
                print("  状态: ✓ 收到有效回复")

            # 等待一下再发送下一条
            await asyncio.sleep(2)

    finally:
        await mock.disconnect()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_conversation_test())
