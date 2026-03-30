"""
测试卡片交互优化（T061）

测试场景：
1. 就地更新卡片 - update_card 被正确调用
2. Loading 状态显示 - 按钮禁用、状态文本正确
3. 快捷命令 loading 状态
4. 选项按钮 loading 状态
5. 断开/重连 loading 状态
"""

import unittest
import asyncio
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCardInteraction(unittest.TestCase):
    """卡片交互测试"""

    def test_build_stream_card_loading_state(self):
        """测试 loading 状态的卡片构建"""
        from lark_client.card_builder import build_stream_card

        # 正常状态
        normal_card = build_stream_card(
            blocks=[{"_type": "OutputBlock", "content": "test"}],
            session_name="test-session",
        )
        # 检查 card 结构
        self.assertIn("header", normal_card)
        self.assertIn("body", normal_card)
        self.assertIn("elements", normal_card["body"])

        # loading 状态
        loading_card = build_stream_card(
            blocks=[{"_type": "OutputBlock", "content": "test"}],
            session_name="test-session",
            is_loading=True,
            loading_text="处理中...",
        )
        # loading 状态 header 应该是 orange 且显示 loading 文本
        self.assertEqual(loading_card["header"]["title"]["content"], "⏳ 处理中...")
        self.assertEqual(loading_card["header"]["template"], "orange")

    def test_loading_state_disables_buttons(self):
        """测试 loading 状态禁用按钮"""
        from lark_client.card_builder import build_stream_card

        # 带选项的卡片
        option_block = {
            "sub_type": "option",
            "question": "选择一个选项",
            "options" : [
                {"label": "选项 1", "value": "1"},
                {"label": "选项 2", "value": "2"},
            ]
        }

        # 正常状态
        normal_card = build_stream_card(
            blocks=[],
            option_block=option_block,
            session_name="test-session",
        )
        # 检查按钮未被禁用
        elements = normal_card["body"]["elements"]
        for elem in elements:
            if elem.get("tag") == "action":
                for action in elem.get("actions", []):
                    if action.get("tag") == "button":
                        self.assertNotIn("disabled", action)

        # loading 状态
        loading_card = build_stream_card(
            blocks=[],
            option_block=option_block,
            session_name="test-session",
            is_loading=True,
            loading_text="处理中...",
        )
        # 检查按钮被禁用
        elements = loading_card["body"]["elements"]
        for elem in elements:
            if elem.get("tag") == "action":
                for action in elem.get("actions", []):
                    if action.get("tag") == "button":
                        self.assertTrue(action.get("disabled", False), "按钮应该被禁用")

    def test_menu_button_row_loading(self):
        """测试菜单按钮行 loading 状态"""
        from lark_client.card_builder import _build_menu_button_row

        # 正常状态
        normal_buttons = _build_menu_button_row(
            session_name="test-session",
            disconnected=False,
        )
        # 应该有输入框
        self.assertTrue(len(normal_buttons) > 0)

        # loading 状态
        loading_buttons = _build_menu_button_row(
            session_name="test-session",
            disconnected=False,
            is_loading=True,
        )
        # 所有按钮应该被禁用
        for elem in loading_buttons:
            if elem.get("tag") == "form":
                for action in elem.get("elements", []):
                    if action.get("tag") == "action":
                        for btn in action.get("actions", []):
                            if btn.get("tag") == "button":
                                self.assertTrue(btn.get("disabled", False))


class TestQuickCommandLoading(unittest.TestCase):
    """快捷命令 loading 状态测试"""

    def test_handle_quick_command_shows_loading(self):
        """测试快捷命令发送时显示 loading 状态"""
        from lark_client.lark_handler import LarkHandler

        handler = LarkHandler()
        handler._bridges = {"test_chat": MagicMock(running=True)}
        handler._chat_sessions = {"test_chat": "test-session"}
        handler._runtime_config = None
        handler._poller = MagicMock()
        handler._poller.get_active_card_id = MagicMock(return_value="card_123")
        handler._poller.read_snapshot = MagicMock(return_value={
            "blocks"  : [{"_type": "OutputBlock", "content": "test"}],
            "cli_type": "claude",
        })
        handler._poller.kick = MagicMock()

        mock_bridge = handler._bridges["test_chat"]
        mock_bridge.send_input = AsyncMock(return_value=True)

        with patch('lark_client.lark_handler.build_loading_card_from_snapshot') as mock_build_loading_card, \
                patch('lark_client.lark_handler.card_service') as mock_card_service:
            mock_build_loading_card.return_value = {"header": {}, "body": {"elements": []}}
            mock_card_service.update_card = AsyncMock(return_value=True)

            # 运行测试
            asyncio.run(handler.handle_quick_command("user_123", "test_chat", "/clear"))

            # 验证 build_loading_card_from_snapshot 被调用
            mock_build_loading_card.assert_called_once()
            # loading_text 是第三个位置参数
            call_args = mock_build_loading_card.call_args.args
            # loading_text 应包含命令
            self.assertIn("/clear", call_args[2])

            # 验证 update_card 被调用
            mock_card_service.update_card.assert_called()

            # 验证命令被发送
            mock_bridge.send_input.assert_called_once_with("/clear")

            # 验证 kick 被调用
            handler._poller.kick.assert_called_once_with("test_chat")


class TestOptionSelectLoading(unittest.TestCase):
    """选项选择 loading 状态测试"""

    def test_handle_option_select_shows_loading(self):
        """测试选项选择时显示 loading 状态"""
        from lark_client.lark_handler import LarkHandler

        handler = LarkHandler()
        handler._bridges = {"test_chat": MagicMock(running=True)}
        handler._chat_sessions = {"test_chat": "test-session"}
        handler._runtime_config = None
        handler._user_config = None

        # Mock tracker with non-expired card
        mock_tracker = MagicMock()
        mock_card_slice = MagicMock()
        mock_card_slice.expired = False  # 卡片未过期
        mock_tracker.cards = [mock_card_slice]

        handler._poller = MagicMock()
        handler._poller._trackers = {"test_chat": mock_tracker}
        handler._poller.get_active_card_id = MagicMock(return_value="card_123")
        handler._poller.read_snapshot = MagicMock(return_value={
            "blocks"      : [],
            "option_block": {
                "sub_type"      : "option",
                "block_id"      : "Q:test",
                "selected_value": "1",
                "question"      : "选择一个选项",
                "options"       : [
                    {"label": "选项 1", "value": "1"},
                    {"label": "选项 2", "value": "2"},
                ]
            },
            "cli_type"    : "claude",
        })
        handler._poller.kick = MagicMock()
        handler._poller.cancel_auto_answer = MagicMock()

        mock_bridge = handler._bridges["test_chat"]
        mock_bridge.send_raw = AsyncMock(return_value=True)

        with patch('lark_client.lark_handler.build_loading_card_from_snapshot') as mock_build_card, \
                patch('lark_client.lark_handler.card_service') as mock_card_service:
            mock_build_card.return_value = {"header": {}, "body": {"elements": []}}
            mock_card_service.update_card = AsyncMock(return_value=True)
            mock_card_service.send_text = AsyncMock()  # 添加 send_text 的 AsyncMock

            # 运行测试
            asyncio.run(handler.handle_option_select("user_123", "test_chat", "2", option_total=2))

            # 验证 build_loading_card_from_snapshot 被调用且带有 loading 参数
            mock_build_card.assert_called()
            # loading_text 是第三个位置参数
            call_args = mock_build_card.call_args.args
            self.assertEqual(call_args[2], "正在选择...")


class TestStreamDetachLoading(unittest.TestCase):
    """断开连接 loading 状态测试"""

    def test_handle_stream_detach_shows_loading(self):
        """测试断开连接时显示 loading 状态"""
        from lark_client.lark_handler import LarkHandler

        handler = LarkHandler()
        handler._chat_sessions = {"test_chat": "test-session"}
        handler._runtime_config = None
        handler._user_config = None
        handler._poller = MagicMock()
        handler._poller.get_active_card_id = MagicMock(return_value="card_123")
        handler._poller.read_snapshot = MagicMock(return_value={
            "blocks"  : [],
            "cli_type": "claude",
        })
        handler._poller.stop_and_get_active_slice = MagicMock(return_value=MagicMock(
            card_id="card_123",
            start_idx=0,
            frozen=False,
        ))

        handler._bridges = {}
        handler._detached_slices = {}

        # Mock _remove_binding_by_chat 和 _detach
        handler._remove_binding_by_chat = MagicMock()
        handler._detach = AsyncMock()

        with patch('lark_client.lark_handler.build_loading_card_from_snapshot') as mock_build_loading_card, \
                patch('lark_client.lark_handler.card_service') as mock_card_service:
            mock_build_loading_card.return_value = {"header": {}, "body": {"elements": []}}
            mock_card_service.update_card = AsyncMock(return_value=True)

            # 运行测试
            asyncio.run(handler._handle_stream_detach("user_123", "test_chat", "test-session"))

            # 验证 build_loading_card_from_snapshot 被调用
            # loading_text 是第三个位置参数
            loading_calls = [c for c in mock_build_loading_card.call_args_list
                             if len(c.args) > 2 and "断开" in c.args[2]]
            self.assertTrue(len(loading_calls) > 0, "应该有断开连接的 loading 状态卡片构建")




def test_stream_card_has_textarea_and_action_selector():
    from lark_client.card_builder import build_stream_card
    from utils.runtime_config import UserConfig

    config = UserConfig()
    card = build_stream_card(blocks=[], session_name="s1", user_config=config)
    body_text = str(card["body"]["elements"])

    assert "textarea" in body_text
    assert "操作" in body_text
    assert "key:up" in body_text


def test_menu_card_not_contains_auto_answer_button():
    from lark_client.card_builder import build_menu_card

    card = build_menu_card([], None, {}, 0, True, False, False, None)
    assert "menu_toggle_auto_answer" not in str(card)


def test_stream_card_contains_stream_toggle_auto_answer_button():
    from lark_client.card_builder import build_stream_card

    card = build_stream_card(blocks=[], session_name="s1")
    assert "stream_toggle_auto_answer" in str(card)


@patch("lark_client.main.asyncio.create_task")
def test_main_routes_prefixed_action_values(mock_create_task):
    from lark_client import main

    mock_create_task.side_effect = lambda coro: (coro.close(), MagicMock())[1]

    event = MagicMock()
    event.event.action.form_value = None
    event.event.action.value = "key:up"
    event.event.operator.open_id = "u1"
    event.event.context.open_chat_id = "c1"
    event.event.context.open_message_id = "m1"

    main.handle_card_action(event)

    assert mock_create_task.called
