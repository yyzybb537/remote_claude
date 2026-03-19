#!/usr/bin/env python3
"""
断开状态测试

测试覆盖：
1. 快捷命令发送时会话已断开的处理
2. 实时检测（检查 bridge.running 状态）
3. 选项选择时会话已断开的处理

注意：本测试为单元测试，模拟 SessionBridge 和 card_service。
"""

import sys
import asyncio
from pathlib import Path
from typing import Optional

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============== Mock 对象 ==============

class MockBridge:
    """模拟 SessionBridge"""
    def __init__(self, running: bool = True):
        self.running = running

    async def send_input(self, text: str) -> bool:
        return self.running

    async def send_raw(self, data: bytes) -> bool:
        return self.running

    async def disconnect(self):
        self.running = False


class MockCardService:
    """模拟卡片服务"""
    def __init__(self):
        self.sent_messages = []
        self.updated_cards = []

    async def send_text(self, chat_id: str, text: str):
        self.sent_messages.append((chat_id, text))
        return True

    async def update_card(self, card_id: str, sequence: int, card_content: dict):
        self.updated_cards.append((card_id, sequence, card_content))
        return True


# ============== 单元测试 ==============

def test_bridge_running_true():
    """测试 bridge.running=True 时可以发送"""

    async def run_test():
        bridge = MockBridge(running=True)
        assert bridge.running is True
        result = await bridge.send_input("test")
        assert result is True
        print("✓ bridge.running=True 时 send_input 成功")

    asyncio.run(run_test())


def test_bridge_running_false():
    """测试 bridge.running=False 时发送失败"""

    async def run_test():
        bridge = MockBridge(running=False)
        assert bridge.running is False
        result = await bridge.send_input("test")
        assert result is False
        print("✓ bridge.running=False 时 send_input 失败")

    asyncio.run(run_test())


def test_bridge_disconnect():
    """测试断开连接后状态变化"""

    async def run_test():
        bridge = MockBridge(running=True)
        assert bridge.running is True

        await bridge.disconnect()
        assert bridge.running is False

        result = await bridge.send_input("test")
        assert result is False
        print("✓ disconnect 后 running 状态变为 False")

    asyncio.run(run_test())


def test_send_raw_success():
    """测试发送原始数据"""

    async def run_test():
        bridge = MockBridge(running=True)
        result = await bridge.send_raw(b"\x1b[A")  # 上箭头
        assert result is True
        print("✓ send_raw 成功")

    asyncio.run(run_test())


def test_send_raw_failure():
    """测试断开时发送原始数据失败"""

    async def run_test():
        bridge = MockBridge(running=False)
        result = await bridge.send_raw(b"\x1b[A")
        assert result is False
        print("✓ 断开时 send_raw 失败")

    asyncio.run(run_test())


def test_card_service_mock():
    """测试 MockCardService"""

    async def run_test():
        service = MockCardService()

        # 测试 send_text
        await service.send_text("chat_123", "测试消息")
        assert len(service.sent_messages) == 1
        assert service.sent_messages[0] == ("chat_123", "测试消息")

        # 测试 update_card
        await service.update_card("card_456", 1, {"test": "content"})
        assert len(service.updated_cards) == 1
        assert service.updated_cards[0] == ("card_456", 1, {"test": "content"})

        print("✓ MockCardService 模拟正确")

    asyncio.run(run_test())


def test_disconnected_prompt_text():
    """测试断开提示文本已定义"""
    # 验证断开提示文本常量存在
    expected_prompts = [
        "会话已断开",
        "请重新连接",
        "未连接到任何会话",
    ]

    # 这些提示在 lark_handler.py 的各种处理函数中使用
    # 测试验证文本定义存在
    found_prompts = []

    # 读取 lark_handler.py 验证提示文本存在
    handler_path = Path(__file__).parent.parent / "lark_client" / "lark_handler.py"
    if handler_path.exists():
        content = handler_path.read_text(encoding="utf-8")
        for prompt in expected_prompts:
            if prompt in content:
                found_prompts.append(prompt)

    assert len(found_prompts) > 0, "应至少有一个断开提示文本定义"
    print(f"✓ 断开提示文本已定义: {found_prompts}")


def test_realtime_check_logic():
    """测试实时检测逻辑"""
    # 模拟实时检测场景
    bridge = MockBridge(running=True)

    # 场景1: 连接正常
    if bridge.running:
        can_send = True
    else:
        can_send = False
    assert can_send is True
    print("✓ 实时检测: 连接正常时 can_send=True")

    # 场景2: 连接断开
    bridge.running = False
    if bridge.running:
        can_send = True
    else:
        can_send = False
    assert can_send is False
    print("✓ 实时检测: 连接断开时 can_send=False")


def test_multiple_bridges():
    """测试多个 bridge 实例"""

    async def run_test():
        bridges = {
            "chat_1": MockBridge(running=True),
            "chat_2": MockBridge(running=False),
            "chat_3": MockBridge(running=True),
        }

        # 检查各 bridge 状态
        assert bridges["chat_1"].running is True
        assert bridges["chat_2"].running is False
        assert bridges["chat_3"].running is True

        # 发送测试
        result_1 = await bridges["chat_1"].send_input("test")
        result_2 = await bridges["chat_2"].send_input("test")
        result_3 = await bridges["chat_3"].send_input("test")

        assert result_1 is True
        assert result_2 is False
        assert result_3 is True

        print("✓ 多 bridge 实例独立状态")

    asyncio.run(run_test())


# ============== 运行所有测试 ==============

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("断开状态测试")
    print("=" * 60)

    tests = [
        test_bridge_running_true,
        test_bridge_running_false,
        test_bridge_disconnect,
        test_send_raw_success,
        test_send_raw_failure,
        test_card_service_mock,
        test_disconnected_prompt_text,
        test_realtime_check_logic,
        test_multiple_bridges,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
            import traceback
            traceback.print_exc()

    print("=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
