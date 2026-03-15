#!/usr/bin/env python3
"""
Remote Claude 飞书客户端

通过飞书聊天控制 remote_claude 会话
"""

import asyncio
import json
import logging
import os
import signal
import sys
import urllib.request
from pathlib import Path


# 设置 sys.path 以导入 utils 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.session import USER_DATA_DIR


def _setup_logging():
    """配置 lark_client 日志：INFO → lark_client.log, DEBUG → lark_client.debug.log"""
    from .config import LARK_LOG_LEVEL

    log_dir = USER_DATA_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志格式（含毫秒级时间戳）
    log_format = "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # 根 logger 配置
    root_logger = logging.getLogger()
    root_logger.setLevel(LARK_LOG_LEVEL)

    # 清除默认 handler
    root_logger.handlers.clear()

    # 正常日志文件（INFO 及以上）
    info_handler = logging.FileHandler(log_dir / "lark_client.log", encoding="utf-8")
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    root_logger.addHandler(info_handler)

    # 调试日志文件（DEBUG 及以上，仅当 LARK_LOG_LEVEL=DEBUG 时写入）
    if LARK_LOG_LEVEL == logging.DEBUG:
        debug_handler = logging.FileHandler(log_dir / "lark_client.debug.log", encoding="utf-8")
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(formatter)
        root_logger.addHandler(debug_handler)

    # 第三方库保持 INFO 级别
    for _noisy in ('urllib3', 'websockets', 'asyncio'):
        logging.getLogger(_noisy).setLevel(logging.INFO)

    # 控制台输出（仅在终端交互模式下启用，守护进程模式下 stderr 已重定向到日志文件）
    if sys.stderr.isatty():
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)


# 在导入 lark SDK 之前配置日志
_setup_logging()

import lark_oapi as lark

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger, P2CardActionTriggerResponse, CallBackToast
)

from . import config
from .lark_handler import handler


async def _graceful_shutdown() -> None:
    """优雅关闭：更新所有活跃流式卡片为已断开状态后退出"""
    try:
        await handler.disconnect_all_for_shutdown()
    except Exception as e:
        print(f"[Lark] graceful shutdown 异常: {e}")
    finally:
        import os
        os._exit(0)

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

        # 检测 form 提交（输入框 Enter ↵ 按钮）
        form_value = getattr(action, 'form_value', None)
        if form_value is not None:
            command_text = (form_value.get("command") or "").strip()
            print(f"[Lark] form 提交: user={user_id[:8]}..., command={command_text!r}")
            if command_text:
                # 有输入内容 → 直通 Claude
                asyncio.create_task(handler.forward_to_claude(user_id, chat_id, command_text))
            else:
                # 空输入 → 发送原始 Enter 键（用于确认默认选项等场景）
                asyncio.create_task(handler.send_raw_key(user_id, chat_id, "enter"))
            return None

        action_type = action_value.get("action", "")

        # 处理选项选择动作
        if action_type == "select_option":
            option_value = action_value.get("value", "")
            option_total = int(action_value.get("total", "0"))
            needs_input = action_value.get("needs_input", False)
            print(f"[Lark] 用户选择了选项: {option_value} (total={option_total}, needs_input={needs_input})")
            asyncio.create_task(handler.handle_option_select(user_id, chat_id, option_value, option_total, needs_input=needs_input))
            return None

        # 列表卡片：进入会话
        if action_type == "list_attach":
            session_name = action_value.get("session", "")
            print(f"[Lark] list_attach: session={session_name}")
            asyncio.create_task(handler._cmd_attach(user_id, chat_id, session_name, message_id=message_id))
            return None

        # 列表卡片：断开连接
        if action_type == "list_detach":
            print(f"[Lark] list_detach: chat={chat_id[:8]}...")
            asyncio.create_task(handler._handle_list_detach(user_id, chat_id, message_id=message_id))
            return None

        # 列表卡片：创建群聊
        if action_type == "list_new_group":
            session_name = action_value.get("session", "")
            print(f"[Lark] list_new_group: session={session_name}")
            asyncio.create_task(handler._cmd_new_group(user_id, chat_id, session_name, message_id=message_id))
            return None

        # 列表卡片：解散群聊
        if action_type == "list_disband_group":
            session_name = action_value.get("session", "")
            print(f"[Lark] list_disband_group: session={session_name}")
            asyncio.create_task(handler._cmd_disband_group(user_id, chat_id, session_name, message_id=message_id))
            return None

        # 列表卡片：关闭会话
        if action_type == "list_kill":
            session_name = action_value.get("session", "")
            print(f"[Lark] list_kill: session={session_name}")
            asyncio.create_task(handler._cmd_kill(user_id, chat_id, session_name, message_id=message_id))
            return None

        # 目录卡片：进入子目录（继续浏览，就地更新原卡片）
        if action_type == "dir_browse":
            path = action_value.get("path", "")
            print(f"[Lark] dir_browse: path={path}")
            asyncio.create_task(handler._cmd_ls(user_id, chat_id, path, message_id=message_id))
            return None

        # 菜单卡片：会话列表翻页
        if action_type == "menu_page":
            page = int(action_value.get("page", 0))
            print(f"[Lark] menu_page: page={page}")
            asyncio.create_task(handler._cmd_menu(user_id, chat_id, message_id=message_id, page=page))
            return None

        # 目录卡片：翻页
        if action_type == "dir_page":
            path = action_value.get("path", "")
            page = int(action_value.get("page", 0))
            print(f"[Lark] dir_page: path={path}, page={page}")
            asyncio.create_task(handler._cmd_ls(user_id, chat_id, path, message_id=message_id, page=page))
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

        # 流式卡片：断开连接
        if action_type == "stream_detach":
            session_name = action_value.get("session", "")
            print(f"[Lark] stream_detach: session={session_name}")
            asyncio.create_task(handler._handle_stream_detach(user_id, chat_id, session_name, message_id=message_id))
            return None

        # 流式卡片：重新连接
        if action_type == "stream_reconnect":
            session_name = action_value.get("session", "")
            print(f"[Lark] stream_reconnect: session={session_name}")
            asyncio.create_task(handler._handle_stream_reconnect(user_id, chat_id, session_name, message_id=message_id))
            return None

        # 快捷键按钮（callback 模式）
        if action_type == "send_key":
            key_name = action_value.get("key", "")
            times = action_value.get("times", 1)
            print(f"[Lark] send_key: key={key_name}" + (f" ×{times}" if times > 1 else ""))
            async def _multi_send(k=key_name, t=times):
                for _ in range(t):
                    await handler.send_raw_key(user_id, chat_id, k)
                    await asyncio.sleep(0.15)
            asyncio.create_task(_multi_send())
            return None

        if action_type == "menu_toggle_notify":
            asyncio.create_task(handler._cmd_toggle_notify(user_id, chat_id, message_id=message_id))
            return None

        if action_type == "menu_toggle_urgent":
            asyncio.create_task(handler._cmd_toggle_urgent(user_id, chat_id, message_id=message_id))
            return None

        if action_type == "menu_toggle_bypass":
            asyncio.create_task(handler._cmd_toggle_bypass(user_id, chat_id, message_id=message_id))
            return None

        # 各卡片底部菜单按钮：辅助卡片就地→菜单，流式卡片降级新卡
        if action_type == "menu_open":
            asyncio.create_task(handler._cmd_menu(user_id, chat_id, message_id=message_id))
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
            print("在 ~/.remote-claude/.env 文件中添加:")
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

        # 代理兼容：检测 SOCKS 代理，按配置决定是否绕过
        proxy_info = urllib.request.getproxies()
        socks_proxy = (proxy_info.get('socks') or proxy_info.get('all')
                       or proxy_info.get('https') or proxy_info.get('http'))
        if socks_proxy and 'socks' in socks_proxy.lower():
            if config.LARK_NO_PROXY:
                # 用户选择绕过代理 → 清除代理环境变量
                for var in ('ALL_PROXY', 'all_proxy', 'HTTPS_PROXY', 'https_proxy',
                            'HTTP_PROXY', 'http_proxy', 'SOCKS_PROXY', 'socks_proxy'):
                    os.environ.pop(var, None)
                print(f"检测到 SOCKS 代理 ({socks_proxy})，已按 LARK_NO_PROXY=1 绕过")
            else:
                print(f"检测到 SOCKS 代理 ({socks_proxy})，将通过代理连接")
                print("  如连接失败，可在 .env 中设置 LARK_NO_PROXY=1 绕过代理")

        self.running = True
        print("\n机器人已启动，等待消息...")
        print("在飞书中发送 /help 查看使用说明\n")

        # 启动 WebSocket（阻塞）
        self.ws_client.start()

    def _signal_handler(self, signum, frame):
        """处理退出信号（SIGTERM / SIGINT）"""
        print("\n正在关闭...")
        self.running = False
        # 调度异步清理（更新所有活跃卡片为已断开状态后退出）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(_graceful_shutdown())
                )
                return
        except Exception:
            pass
        sys.exit(0)


def main():
    """入口函数"""
    bot = LarkBot()
    bot.start()


if __name__ == "__main__":
    main()
