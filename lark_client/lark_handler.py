"""
飞书消息处理器 - 基于共享内存的推送架构

架构：
  Server → .mq 共享内存 → SharedMemoryPoller → 飞书卡片
  SessionBridge 只负责：连接管理 + 输入发送

群聊/私聊统一逻辑：以 chat_id 为 key 管理所有 bridge 和会话绑定。
"""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger('LarkHandler')

from .session_bridge import SessionBridge
from .card_service import card_service
from .card_builder import (
    build_stream_card,
    build_session_list_card,
    build_status_card,
    build_help_card,
    build_dir_card,
    build_menu_card,
    build_session_closed_card,
)
from .shared_memory_poller import SharedMemoryPoller

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.session import list_active_sessions, get_socket_path

try:
    from stats import track as _track_stats
except Exception:
    def _track_stats(*args, **kwargs): pass


class LarkHandler:
    """飞书消息处理器（群聊/私聊统一逻辑）"""

    _CHAT_BINDINGS_FILE = Path("/tmp/remote-claude/lark_chat_bindings.json")

    def __init__(self):
        # chat_id → SessionBridge（活跃连接）
        self._bridges: Dict[str, SessionBridge] = {}
        # chat_id → session_name（当前连接状态）
        self._chat_sessions: Dict[str, str] = {}
        # 共享内存轮询器
        self._poller = SharedMemoryPoller(card_service)
        # chat_id → session_name 持久化绑定（重启后自动恢复）
        self._chat_bindings: Dict[str, str] = self._load_chat_bindings()

    # ── 持久化绑定 ──────────────────────────────────────────────────────────

    def _load_chat_bindings(self) -> Dict[str, str]:
        try:
            if self._CHAT_BINDINGS_FILE.exists():
                return json.loads(self._CHAT_BINDINGS_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_chat_bindings(self):
        try:
            self._CHAT_BINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._CHAT_BINDINGS_FILE.write_text(
                json.dumps(self._chat_bindings, ensure_ascii=False)
            )
        except Exception as e:
            logger.warning(f"保存绑定失败: {e}")

    def _remove_binding_by_chat(self, chat_id: str):
        self._chat_bindings.pop(chat_id, None)
        self._save_chat_bindings()

    # ── 统一 attach / detach / on_disconnect ────────────────────────────────

    async def _attach(self, chat_id: str, session_name: str) -> bool:
        """统一 attach 逻辑（私聊/群聊共用）"""
        # 断开旧 bridge
        old = self._bridges.pop(chat_id, None)
        if old:
            await old.disconnect()
        self._poller.stop(chat_id)
        self._chat_sessions.pop(chat_id, None)

        def on_disconnect():
            asyncio.create_task(self._on_disconnect(chat_id, session_name))

        bridge = SessionBridge(session_name, on_disconnect=on_disconnect)
        if await bridge.connect():
            self._bridges[chat_id] = bridge
            self._chat_sessions[chat_id] = session_name
            self._poller.start(chat_id, session_name)
            _track_stats('lark', 'attach', session_name=session_name,
                         chat_id=chat_id)
            return True
        return False

    async def _detach(self, chat_id: str):
        """统一 detach 逻辑（私聊/群聊共用）"""
        bridge = self._bridges.pop(chat_id, None)
        if bridge:
            await bridge.disconnect()
        self._chat_sessions.pop(chat_id, None)
        self._poller.stop(chat_id)

    async def _on_disconnect(self, chat_id: str, session_name: str):
        """服务端关闭连接时的统一处理"""
        logger.info(f"会话 '{session_name}' 断线, chat_id={chat_id[:8]}...")
        _track_stats('lark', 'disconnect', session_name=session_name,
                     chat_id=chat_id)
        self._bridges.pop(chat_id, None)
        self._chat_sessions.pop(chat_id, None)
        self._poller.stop(chat_id)
        self._remove_binding_by_chat(chat_id)
        card = build_session_closed_card(session_name)
        await card_service.create_and_send_card(chat_id, card)

    # ── 消息入口 ────────────────────────────────────────────────────────────

    async def handle_message(self, user_id: str, chat_id: str, text: str,
                              chat_type: str = "p2p"):
        """处理用户消息（群聊/私聊统一路由）"""
        logger.info(f"收到消息: user={user_id[:8]}..., chat={chat_id[:8]}..., type={chat_type}, text={text[:50]}")
        text = text.strip()

        if text.startswith("/"):
            await self._handle_command(user_id, chat_id, text)
        else:
            await self._forward_to_claude(user_id, chat_id, text)
            _track_stats('lark', 'message',
                         session_name=self._chat_sessions.get(chat_id, ''),
                         chat_id=chat_id)

    async def _handle_command(self, user_id: str, chat_id: str, text: str):
        """处理命令（群聊/私聊共用同一逻辑）"""
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        _track_stats('lark', 'cmd',
                     session_name=self._chat_sessions.get(chat_id, ''),
                     chat_id=chat_id, detail=command)

        if command == "/attach":
            await self._cmd_attach(user_id, chat_id, args)
        elif command == "/detach":
            await self._cmd_detach(user_id, chat_id)
        elif command == "/list":
            await self._cmd_list(user_id, chat_id)
        elif command == "/status":
            await self._cmd_status(user_id, chat_id)
        elif command == "/start":
            await self._cmd_start(user_id, chat_id, args)
        elif command == "/kill":
            await self._cmd_kill(user_id, chat_id, args)
        elif command in ("/ls", "/tree"):
            await self._cmd_ls(user_id, chat_id, args, tree=(command == "/tree"))
        elif command == "/new-group":
            await self._cmd_new_group(user_id, chat_id, args)
        elif command == "/help":
            await self._cmd_help(user_id, chat_id)
        elif command == "/menu":
            await self._cmd_menu(user_id, chat_id)
        else:
            await card_service.send_text(chat_id, f"未知命令: {command}\n使用 /help 查看帮助")

    # ── 命令处理 ─────────────────────────────────────────────────────────────

    async def _cmd_attach(self, user_id: str, chat_id: str, args: str):
        """连接到会话"""
        session_name = args.strip()

        if not session_name:
            sessions = list_active_sessions()
            current = self._chat_sessions.get(chat_id)
            session_groups = {sname: cid for cid, sname in self._chat_bindings.items() if cid.startswith("oc_")}
            card = build_session_list_card(sessions, current, session_groups=session_groups)
            card_id = await card_service.create_card(card)
            if card_id:
                await card_service.send_card(chat_id, card_id)
            return

        sessions = list_active_sessions()
        if not any(s["name"] == session_name for s in sessions):
            await card_service.send_text(
                chat_id, f"会话 '{session_name}' 不存在，使用 /list 查看可用会话"
            )
            return

        ok = await self._attach(chat_id, session_name)
        if ok:
            self._chat_bindings[chat_id] = session_name
            self._save_chat_bindings()
            await card_service.send_text(chat_id, f"✅ 已连接到会话 '{session_name}'")
        else:
            await card_service.send_text(chat_id, f"❌ 无法连接到会话 '{session_name}'")

    async def _cmd_detach(self, user_id: str, chat_id: str,
                           message_id: Optional[str] = None):
        """断开会话"""
        if chat_id not in self._bridges and chat_id not in self._chat_sessions:
            await card_service.send_text(chat_id, "当前未连接到任何会话")
            return
        self._remove_binding_by_chat(chat_id)
        await self._detach(chat_id)
        await self._cmd_menu(user_id, chat_id, message_id=message_id)

    async def _cmd_list(self, user_id: str, chat_id: str,
                         message_id: Optional[str] = None):
        """列出会话"""
        sessions = list_active_sessions()
        current = self._chat_sessions.get(chat_id)
        session_groups = {sname: cid for cid, sname in self._chat_bindings.items() if cid.startswith("oc_")}
        card = build_session_list_card(sessions, current, session_groups=session_groups)
        await self._send_or_update_card(chat_id, card, message_id)

    async def _cmd_status(self, user_id: str, chat_id: str):
        """显示状态"""
        session_name = self._chat_sessions.get(chat_id)
        bridge = self._bridges.get(chat_id)
        if bridge and bridge.running and session_name:
            card = build_status_card(True, session_name)
        else:
            card = build_status_card(False)
        card_id = await card_service.create_card(card)
        if card_id:
            await card_service.send_card(chat_id, card_id)

    async def _cmd_start(self, user_id: str, chat_id: str, args: str):
        """启动新会话"""
        parts = args.strip().split(maxsplit=1)
        if not parts:
            await card_service.send_text(
                chat_id,
                "用法: /start <会话名> [工作路径]\n\n"
                "示例:\n"
                "  /start mywork ~/dev/myproject\n"
                "  /start test ~/dev/myproject"
            )
            return

        session_name = parts[0]
        work_dir = parts[1] if len(parts) > 1 else None

        if work_dir:
            work_path = Path(work_dir).expanduser()
            if not work_path.exists():
                await card_service.send_text(chat_id, f"错误: 路径不存在: {work_dir}")
                return
            if not work_path.is_dir():
                await card_service.send_text(chat_id, f"错误: 不是目录: {work_dir}")
                return
            work_dir = str(work_path.absolute())

        sessions = list_active_sessions()
        if any(s["name"] == session_name for s in sessions):
            await card_service.send_text(
                chat_id,
                f"错误: 会话 '{session_name}' 已存在\n使用 /attach {session_name} 连接"
            )
            return

        script_dir = Path(__file__).parent.parent.absolute()
        server_script = script_dir / "server" / "server.py"
        cmd = [sys.executable, str(server_script), session_name]

        logger.info(f"启动会话: {session_name}, 工作目录: {work_dir}, 命令: {cmd}")
        _track_stats('lark', 'cmd_start', session_name=session_name, chat_id=chat_id)

        try:
            import os as _os
            env = _os.environ.copy()
            env.pop("CLAUDECODE", None)

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                cwd=work_dir,
                env=env,
            )

            socket_path = get_socket_path(session_name)
            for _ in range(120):
                await asyncio.sleep(0.1)
                if socket_path.exists():
                    break
            else:
                await card_service.send_text(chat_id, "错误: 会话启动超时")
                return

            ok = await self._attach(chat_id, session_name)
            if ok:
                self._chat_bindings[chat_id] = session_name
                self._save_chat_bindings()
                work_info = f"\n工作目录: {work_dir}" if work_dir else ""
                await card_service.send_text(
                    chat_id, f"✅ 会话 '{session_name}' 已启动并连接{work_info}"
                )
            else:
                await card_service.send_text(
                    chat_id,
                    f"会话已启动但连接失败\n使用 /attach {session_name} 重试"
                )

        except Exception as e:
            logger.error(f"启动会话失败: {e}")
            await card_service.send_text(chat_id, f"错误: 启动失败 - {e}")

    async def _cmd_start_and_new_group(self, user_id: str, chat_id: str,
                                       session_name: str, path: str):
        """在指定目录启动会话并创建专属群聊"""
        sessions = list_active_sessions()
        if any(s["name"] == session_name for s in sessions):
            # 会话已存在，直接创建群聊
            await self._cmd_new_group(user_id, chat_id, session_name)
            return

        work_path = Path(path).expanduser()
        if not work_path.is_dir():
            await card_service.send_text(chat_id, f"错误: 路径无效: {path}")
            return

        work_dir = str(work_path.absolute())
        script_dir = Path(__file__).parent.parent.absolute()
        server_script = script_dir / "server" / "server.py"
        cmd = [sys.executable, str(server_script), session_name]

        try:
            import os as _os
            env = _os.environ.copy()
            env.pop("CLAUDECODE", None)
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, cwd=work_dir, env=env,
            )

            socket_path = get_socket_path(session_name)
            for _ in range(120):
                await asyncio.sleep(0.1)
                if socket_path.exists():
                    break
            else:
                await card_service.send_text(chat_id, "错误: 会话启动超时")
                return

            await self._cmd_new_group(user_id, chat_id, session_name)

        except Exception as e:
            logger.error(f"启动并创建群聊失败: {e}")
            await card_service.send_text(chat_id, f"操作失败：{e}")

    async def _cmd_kill(self, user_id: str, chat_id: str, args: str):
        """终止会话"""
        from utils.session import cleanup_session, tmux_session_exists, tmux_kill_session

        session_name = args.strip()
        if not session_name:
            await card_service.send_text(chat_id, "用法: /kill <会话名>")
            return

        sessions = list_active_sessions()
        if not any(s["name"] == session_name for s in sessions):
            await card_service.send_text(chat_id, f"错误: 会话 '{session_name}' 不存在")
            return

        # 断开所有连接到此会话的 chat
        for cid, sname in list(self._chat_sessions.items()):
            if sname == session_name:
                await self._detach(cid)
                self._remove_binding_by_chat(cid)

        if tmux_session_exists(session_name):
            tmux_kill_session(session_name)
        cleanup_session(session_name)

        await card_service.send_text(chat_id, f"✅ 会话 '{session_name}' 已终止")

    async def _handle_list_detach(self, user_id: str, chat_id: str,
                                   message_id: Optional[str] = None):
        """会话列表卡片中断开连接，就地刷新列表"""
        self._remove_binding_by_chat(chat_id)
        await self._detach(chat_id)
        await self._cmd_list(user_id, chat_id, message_id=message_id)

    async def _handle_stream_detach(self, user_id: str, chat_id: str,
                                     session_name: str, message_id: Optional[str] = None):
        """流式卡片中断开连接，就地更新卡片为已断开状态"""
        # 读取最后一次快照的 blocks 用于展示
        blocks = []
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
            from shared_state import SharedStateReader, get_mq_path
            mq_path = get_mq_path(session_name)
            if mq_path.exists():
                reader = SharedStateReader(session_name)
                state = reader.read()
                reader.close()
                blocks = state.get("blocks", [])
        except Exception:
            pass

        self._remove_binding_by_chat(chat_id)
        await self._detach(chat_id)

        card = build_stream_card(blocks, disconnected=True, session_name=session_name)
        await self._send_or_update_card(chat_id, card, message_id)

    async def _handle_stream_reconnect(self, user_id: str, chat_id: str, session_name: str):
        """流式卡片中重新连接"""
        await self._cmd_attach(user_id, chat_id, session_name)

    async def _cmd_help(self, user_id: str, chat_id: str,
                         message_id: Optional[str] = None):
        """显示帮助"""
        card = build_help_card()
        await self._send_or_update_card(chat_id, card, message_id)

    async def _cmd_menu(self, user_id: str, chat_id: str,
                         message_id: Optional[str] = None):
        """显示快捷操作菜单"""
        sessions = list_active_sessions()
        current = self._chat_sessions.get(chat_id)
        card = build_menu_card(sessions, current_session=current)
        await self._send_or_update_card(chat_id, card, message_id)

    async def _cmd_ls(self, user_id: str, chat_id: str, args: str,
                       tree: bool = False, message_id: Optional[str] = None):
        """查看目录文件结构"""
        all_sessions = list_active_sessions()
        sessions_info = []
        for s in all_sessions:
            pid = s.get("pid")
            cwd = self._get_pid_cwd(pid) if pid else None
            sessions_info.append({"name": s["name"], "cwd": cwd or ""})

        bound_session = self._chat_sessions.get(chat_id)
        if bound_session:
            pid = next((s.get("pid") for s in all_sessions if s["name"] == bound_session), None)
            session_cwd = self._get_pid_cwd(pid) if pid else None
            root = Path(session_cwd) if session_cwd else Path.home()
        else:
            root = Path.home()

        target_arg = args.strip()
        if target_arg:
            target = Path(target_arg).expanduser()
            if not target.is_absolute():
                target = root / target
        else:
            target = root

        target = target.resolve()
        if not target.exists():
            await card_service.send_text(chat_id, f"路径不存在：{target}")
            return

        try:
            if tree:
                entries = self._collect_tree_entries(target)
            else:
                entries = self._collect_ls_entries(target)
        except Exception as e:
            await card_service.send_text(chat_id, f"读取目录失败：{e}")
            return

        session_groups = {sname: cid for cid, sname in self._chat_bindings.items() if cid.startswith("oc_")}
        card = build_dir_card(target, entries, sessions_info, tree=tree, session_groups=session_groups)
        await self._send_or_update_card(chat_id, card, message_id)

    async def _cmd_new_group(self, user_id: str, chat_id: str, args: str):
        """创建专属群聊并绑定 Claude 会话"""
        session_name = args.strip()
        if not session_name:
            await card_service.send_text(chat_id, "用法：/new-group <会话名>\n示例：/new-group myapp")
            return

        sessions = list_active_sessions()
        if not any(s["name"] == session_name for s in sessions):
            await card_service.send_text(chat_id, f"会话 '{session_name}' 不存在，请先 /start 启动")
            return

        session = next((s for s in sessions if s["name"] == session_name), None)
        pid = session.get("pid") if session else None
        cwd = self._get_pid_cwd(pid) if pid else None
        dir_label = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else session_name

        import lark_oapi as lark
        from . import config
        try:
            import json as _json
            import urllib.request
            req_body = {
                "name": f"【{dir_label}】{config.BOT_NAME}",
                "description": f"Remote Claude 专属群 - 会话 {session_name}",
                "user_id_list": [user_id],
            }
            token_resp = urllib.request.urlopen(
                urllib.request.Request(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    data=_json.dumps({"app_id": config.FEISHU_APP_ID, "app_secret": config.FEISHU_APP_SECRET}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                ), timeout=10
            )
            token_data = _json.loads(token_resp.read())
            token = token_data["tenant_access_token"]

            create_resp = urllib.request.urlopen(
                urllib.request.Request(
                    "https://open.feishu.cn/open-apis/im/v1/chats?user_id_type=open_id",
                    data=_json.dumps(req_body).encode(),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                    method="POST"
                ), timeout=10
            )
            create_data = _json.loads(create_resp.read())

            if create_data.get("code") != 0:
                await card_service.send_text(chat_id, f"创建群失败：{create_data.get('msg')}")
                return

            group_chat_id = create_data["data"]["chat_id"]
            self._chat_bindings[group_chat_id] = session_name
            self._save_chat_bindings()
            # 立即 attach，让新群即刻开始接收 Claude 输出
            await self._attach(group_chat_id, session_name)

            await card_service.send_text(
                chat_id,
                f"✅ 已创建专属群「【{dir_label}】{config.BOT_NAME}」并已连接\n"
                f"在群内直接发消息即可与 Claude 交互"
            )
        except Exception as e:
            logger.error(f"创建群失败: {e}")
            await card_service.send_text(chat_id, f"创建群失败：{e}")

    async def _cmd_disband_group(self, user_id: str, chat_id: str, session_name: str,
                                  message_id: Optional[str] = None):
        """解散与指定会话绑定的专属群聊"""
        group_chat_id = next(
            (cid for cid, sname in self._chat_bindings.items() if sname == session_name and cid.startswith("oc_")),
            None
        )
        if not group_chat_id:
            await card_service.send_text(chat_id, f"会话 '{session_name}' 没有绑定群聊")
            return

        import json as _json
        import urllib.request
        from . import config
        try:
            token_resp = urllib.request.urlopen(
                urllib.request.Request(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    data=_json.dumps({"app_id": config.FEISHU_APP_ID, "app_secret": config.FEISHU_APP_SECRET}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                ), timeout=10
            )
            token = _json.loads(token_resp.read())["tenant_access_token"]

            disband_resp = urllib.request.urlopen(
                urllib.request.Request(
                    f"https://open.feishu.cn/open-apis/im/v1/chats/{group_chat_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    method="DELETE"
                ), timeout=10
            )
            disband_data = _json.loads(disband_resp.read())
            if disband_data.get("code") != 0:
                await card_service.send_text(chat_id, f"解散群失败：{disband_data.get('msg')}")
                return

            self._remove_binding_by_chat(group_chat_id)
            await self._detach(group_chat_id)
            await self._cmd_list(user_id, chat_id, message_id=message_id)
        except Exception as e:
            logger.error(f"解散群失败: {e}")
            await card_service.send_text(chat_id, f"解散群失败：{e}")

    # ── 消息转发 ─────────────────────────────────────────────────────────────

    async def _forward_to_claude(self, user_id: str, chat_id: str, text: str):
        """转发消息给 Claude（输出由 SharedMemoryPoller 自动推卡片）"""
        bridge = self._bridges.get(chat_id)

        if not bridge or not bridge.running:
            # 尝试从持久化绑定自动恢复
            saved_session = self._chat_bindings.get(chat_id)
            if saved_session:
                logger.info(f"自动恢复绑定: chat_id={chat_id[:8]}..., session={saved_session}")
                ok = await self._attach(chat_id, saved_session)
                if not ok:
                    self._remove_binding_by_chat(chat_id)
                    await card_service.send_text(
                        chat_id, f"会话 '{saved_session}' 已不存在，请重新 /attach"
                    )
                    return
                bridge = self._bridges.get(chat_id)
            else:
                await card_service.send_text(
                    chat_id, "未连接到任何会话，请先使用 /attach <会话名> 连接"
                )
                return

        if not bridge:
            return

        success = await bridge.send_input(text)
        if success:
            self._poller.kick(chat_id)
        else:
            await card_service.send_text(chat_id, "发送失败")

    # ── 选项处理 ─────────────────────────────────────────────────────────────

    async def handle_option_select(self, user_id: str, chat_id: str, option_value: str, option_total: int = 0):
        """处理用户选择的选项（按钮点击）

        最后一个选项特殊处理：Claude CLI 的光标选择模式中，最后一个选项
        直接发数字键无效。改为先发倒数第二项的数字跳转，再发 ↓ 移到最后一项，
        最后发 Enter 确认。
        """
        logger.info(f"处理选项选择: user={user_id[:8]}..., option={option_value}, total={option_total}")
        _track_stats('lark', 'option_select',
                     session_name=self._chat_sessions.get(chat_id, ''),
                     chat_id=chat_id, detail=option_value)

        bridge = self._bridges.get(chat_id)
        if not bridge or not bridge.running:
            await card_service.send_text(chat_id, "未连接到任何会话，请先使用 /attach <会话名> 连接")
            return

        key_mapping = {
            "yes": "y",
            "no": "n",
            "allow_once": "y",
            "allow_always": "a",
            "deny": "n",
        }
        key_to_send = key_mapping.get(option_value.lower())

        if key_to_send:
            # 固定映射的选项（permission 类型）
            logger.info(f"发送按键到 Claude: {key_to_send}")
            success = await bridge.send_key(key_to_send)
        elif option_total > 1 and option_value == str(option_total):
            # 最后一个选项：发 (N-1) 次 ↓ → Enter
            import asyncio
            steps = option_total - 1
            logger.info(f"最后一个选项，发送: {steps}次↓ → Enter")
            for _ in range(steps):
                await bridge.send_raw(b"\x1b[B")  # ↓ 箭头
                await asyncio.sleep(0.05)
            success = await bridge.send_raw(b"\r")
        else:
            # 普通数字选项
            logger.info(f"发送按键到 Claude: {option_value}")
            success = await bridge.send_key(option_value)

        if success:
            self._poller.kick(chat_id)
        else:
            await card_service.send_text(chat_id, "发送选择失败")

    # ── 快捷键发送 ─────────────────────────────────────────────────────────────

    async def send_raw_key(self, user_id: str, chat_id: str, key_name: str):
        """发送原始控制键到 Claude CLI"""
        _track_stats('lark', 'raw_key',
                     session_name=self._chat_sessions.get(chat_id, ''),
                     chat_id=chat_id, detail=key_name)
        KEY_MAP = {
            "up": b"\x1b[A",         # ↑ 上箭头
            "down": b"\x1b[B",       # ↓ 下箭头
            "enter": b"\r",          # Enter
            "ctrl_o": b"\x0f",       # Ctrl+O
            "shift_tab": b"\x1b[Z",  # Shift+Tab
            "esc": b"\x1b",          # ESC
        }
        raw = KEY_MAP.get(key_name)
        if not raw:
            logger.warning(f"未知快捷键: {key_name}")
            return

        bridge = self._bridges.get(chat_id)
        if not bridge or not bridge.running:
            logger.warning(f"send_raw_key: chat_id={chat_id[:8]}... 未连接会话")
            return

        success = await bridge.send_raw(raw)
        if success:
            logger.info(f"已发送快捷键 {key_name} 到 Claude")
            self._poller.kick(chat_id)
        else:
            logger.warning(f"发送快捷键 {key_name} 失败")

    # ── 辅助方法 ─────────────────────────────────────────────────────────────

    async def _send_or_update_card(
        self, chat_id: str, card: dict, message_id: Optional[str] = None
    ):
        """有 message_id 时就地更新原卡片，否则发新消息；更新失败时降级为发新卡片"""
        if message_id:
            success = await card_service.update_card_by_message_id(message_id, card)
            if success:
                return
        await card_service.create_and_send_card(chat_id, card)

    @staticmethod
    def _collect_ls_entries(target) -> list:
        """获取一级目录内容（隐藏文件除外，目录优先）"""
        entries = []
        try:
            items = sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            for item in items:
                if item.name.startswith('.'):
                    continue
                entries.append({
                    "name": item.name,
                    "full_path": str(item),
                    "is_dir": item.is_dir(),
                    "depth": 0,
                })
        except PermissionError:
            pass
        return entries[:30]

    @staticmethod
    def _collect_tree_entries(target, max_depth: int = 2, max_items: int = 60) -> list:
        """获取树状目录内容"""
        entries = []

        def _walk(path, depth: int):
            if depth > max_depth or len(entries) >= max_items:
                return
            try:
                for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    if len(entries) >= max_items:
                        break
                    if item.name.startswith('.'):
                        continue
                    entries.append({
                        "name": item.name,
                        "full_path": str(item),
                        "is_dir": item.is_dir(),
                        "depth": depth,
                    })
                    if item.is_dir() and depth < max_depth:
                        _walk(item, depth + 1)
            except PermissionError:
                pass

        _walk(target, 0)
        return entries

    @staticmethod
    def _get_pid_cwd(pid: int) -> Optional[str]:
        """获取进程的工作目录（macOS/Linux）"""
        try:
            result = subprocess.run(
                ["lsof", "-p", str(pid), "-a", "-d", "cwd", "-F", "n"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if line.startswith("n"):
                    return line[1:].strip()
        except Exception:
            pass
        return None


# 全局处理器实例
handler = LarkHandler()
