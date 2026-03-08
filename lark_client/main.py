#!/usr/bin/env python3
"""
Remote Claude 飞书客户端

通过飞书聊天控制 remote_claude 会话
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import lark_oapi as lark

# 在 SDK 配置 logging 之前，先设置根 logger 和我们自己模块的 DEBUG 级别
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(name)s] %(message)s',
)
# 将噪音较大的第三方库保持 INFO 级别
for _noisy in ('urllib3', 'websockets', 'asyncio'):
    logging.getLogger(_noisy).setLevel(logging.INFO)
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger, P2CardActionTriggerResponse, CallBackToast
)

from . import config
from .lark_handler import handler

def check_user_allowed(user_id: str) -> bool:
    """检查用户是否在白名单中"""
    if not config.ENABLE_USER_WHITELIST:
        return True
    return user_id in config.ALLOWED_USERS


def handle_message_receive(data: P2ImMessageReceiveV1) -> None:
    """处理收到的消息"""
    try:
        event = data.event
        message = event.message
        sender = event.sender

        # 获取基本信息
        user_id = sender.sender_id.open_id
        chat_id = message.chat_id
        message_type = message.message_type
        chat_type = message.chat_type

        # 检查用户白名单
        if not check_user_allowed(user_id):
            print(f"[Lark] 用户 {user_id} 不在白名单中")
            return

        # 只处理文本消息
        if message_type != "text":
            print(f"[Lark] 忽略非文本消息: {message_type}")
            return

        # 解析消息内容
        content = json.loads(message.content)
        text = content.get("text", "").strip()

        # 移除 @ 提及
        if message.mentions:
            for mention in message.mentions:
                text = text.replace(f"@_{mention.key}", "").strip()
                text = text.replace(mention.key, "").strip()

        if not text:
            return

        print(f"[Lark] 收到消息: {user_id[:8]}... -> {text[:50]}...")

        # 异步处理消息（传入 chat_type 以支持群聊路由）
        asyncio.create_task(handler.handle_message(user_id, chat_id, text, chat_type=chat_type))

    except Exception as e:
        print(f"[Lark] 处理消息异常: {e}")
        import traceback
        traceback.print_exc()


def handle_card_action(event: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """处理卡片按钮点击"""
    try:
        action = event.event.action
        operator = event.event.operator
        context = event.event.context

        user_id = operator.open_id
        chat_id = context.open_chat_id
        message_id = context.open_message_id  # 原始卡片 message_id，用于就地更新
        action_value = action.value or {}

        print(f"[Lark] 收到卡片动作: user={user_id[:8]}..., action={action_value}")

        # 检查用户白名单
        if not check_user_allowed(user_id):
            print(f"[Lark] 用户 {user_id} 不在白名单中")
            toast = CallBackToast()
            toast.type = "error"
            toast.content = "您没有权限操作"
            response = P2CardActionTriggerResponse()
            response.toast = toast
            return response

        action_type = action_value.get("action", "")

        # 处理选项选择动作
        if action_type == "select_option":
            option_value = action_value.get("value", "")
            option_total = int(action_value.get("total", "0"))
            print(f"[Lark] 用户选择了选项: {option_value} (total={option_total})")
            asyncio.create_task(handler.handle_option_select(user_id, chat_id, option_value, option_total))
            return None

        # 列表卡片：进入会话
        if action_type == "list_attach":
            session_name = action_value.get("session", "")
            print(f"[Lark] list_attach: session={session_name}")
            asyncio.create_task(handler._cmd_attach(user_id, chat_id, session_name))
            return None

        # 列表卡片：创建群聊
        if action_type == "list_new_group":
            session_name = action_value.get("session", "")
            print(f"[Lark] list_new_group: session={session_name}")
            asyncio.create_task(handler._cmd_new_group(user_id, chat_id, session_name))
            return None

        # 列表卡片：解散群聊
        if action_type == "list_disband_group":
            session_name = action_value.get("session", "")
            print(f"[Lark] list_disband_group: session={session_name}")
            asyncio.create_task(handler._cmd_disband_group(user_id, chat_id, session_name, message_id=message_id))
            return None

        # 目录卡片：进入子目录（继续浏览，就地更新原卡片）
        if action_type == "dir_browse":
            path = action_value.get("path", "")
            print(f"[Lark] dir_browse: path={path}")
            asyncio.create_task(handler._cmd_ls(user_id, chat_id, path, message_id=message_id))
            return None

        # 目录卡片：在该目录创建新 Claude 会话
        if action_type == "dir_start":
            path = action_value.get("path", "")
            session_name = action_value.get("session_name", "")
            print(f"[Lark] dir_start: path={path}, session={session_name}")
            asyncio.create_task(handler._cmd_start(user_id, chat_id, f"{session_name} {path}"))
            return None

        # 目录卡片：在该目录启动会话并创建专属群聊
        if action_type == "dir_new_group":
            path = action_value.get("path", "")
            session_name = action_value.get("session_name", "")
            print(f"[Lark] dir_new_group: path={path}, session={session_name}")
            asyncio.create_task(handler._cmd_start_and_new_group(user_id, chat_id, session_name, path))
            return None

        # /menu 卡片按钮
        if action_type == "menu_detach":
            asyncio.create_task(handler._cmd_detach(user_id, chat_id, message_id=message_id))
            return None

        if action_type == "menu_list":
            asyncio.create_task(handler._cmd_list(user_id, chat_id, message_id=message_id))
            return None

        if action_type == "menu_help":
            asyncio.create_task(handler._cmd_help(user_id, chat_id, message_id=message_id))
            return None

        if action_type == "menu_ls":
            asyncio.create_task(handler._cmd_ls(user_id, chat_id, "", message_id=message_id))
            return None

        if action_type == "menu_tree":
            asyncio.create_task(handler._cmd_ls(user_id, chat_id, "", tree=True, message_id=message_id))
            return None

        if action_type == "menu_history":
            asyncio.create_task(handler._cmd_history(user_id, chat_id, "", message_id=message_id))
            return None

        # 快捷键按钮：发送原始控制键到 Claude CLI（无 toast，依靠快速轮询反馈）
        if action_type == "send_key":
            key_name = action_value.get("key", "")
            asyncio.create_task(handler.send_raw_key(user_id, chat_id, key_name))
            return None

        # 各卡片底部菜单按钮：发送新菜单卡片
        if action_type == "menu_open":
            asyncio.create_task(handler._cmd_menu(user_id, chat_id))
            return None

        # 默认响应
        return P2CardActionTriggerResponse()

    except Exception as e:
        print(f"[Lark] 处理卡片动作异常: {e}")
        import traceback
        traceback.print_exc()
        return P2CardActionTriggerResponse()


class LarkBot:
    """飞书机器人"""

    def __init__(self):
        self.ws_client = None
        self.running = False

    def start(self):
        """启动机器人"""
        # 检查配置
        if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
            print("错误: 请配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
            print("在 .env 文件中添加:")
            print("  FEISHU_APP_ID=your_app_id")
            print("  FEISHU_APP_SECRET=your_app_secret")
            return

        print("=" * 50)
        print("Remote Claude 飞书客户端")
        print("=" * 50)
        print(f"App ID: {config.FEISHU_APP_ID[:8]}...")
        print(f"白名单: {'启用' if config.ENABLE_USER_WHITELIST else '禁用'}")
        print("=" * 50)

        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # 创建事件处理器
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(handle_message_receive) \
            .register_p2_card_action_trigger(handle_card_action) \
            .build()

        # 创建 WebSocket 客户端
        self.ws_client = lark.ws.Client(
            config.FEISHU_APP_ID,
            config.FEISHU_APP_SECRET,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        self.running = True
        print("\n机器人已启动，等待消息...")
        print("在飞书中发送 /help 查看使用说明\n")

        # 启动 WebSocket（阻塞）
        self.ws_client.start()

    def _signal_handler(self, signum, frame):
        """处理退出信号"""
        print("\n正在关闭...")
        self.running = False
        if self.ws_client:
            # WebSocket 客户端没有 stop 方法，直接退出
            sys.exit(0)


def main():
    """入口函数"""
    bot = LarkBot()
    bot.start()


if __name__ == "__main__":
    main()
