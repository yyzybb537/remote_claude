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
import os as _os
import subprocess
import sys
import time
from datetime import datetime as _datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger('LarkHandler')

from .session_bridge import SessionBridge
from .card_service import card_service
from .card_builder import (
    build_stream_card,
    build_status_card,
    build_help_card,
    build_dir_card,
    build_menu_card,
    build_loading_card_from_snapshot,
)
from .shared_memory_poller import SharedMemoryPoller, CardSlice

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.session import list_active_sessions, get_socket_path, get_chat_bindings_file, ensure_user_data_dir, USER_DATA_DIR, get_process_cwd
from utils.runtime_config import (
    load_settings,
    get_notify_ready_enabled,
    set_notify_ready_enabled,
    get_notify_urgent_enabled,
    set_notify_urgent_enabled,
    get_bypass_enabled,
    set_bypass_enabled,
)
from utils.stats_helper import safe_track_stats as _safe_track_stats
from utils.process import terminate_process


def _read_log_since(since: '_datetime', log_path: 'Path') -> str:
    """读取 startup.log 中 since 时间点之后的日志行"""
    if not log_path.exists():
        return ""
    lines = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ts = _datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S.%f")
            if ts >= since:
                lines.append(line)
        except ValueError:
            if lines:
                lines.append(line)
    return "\n".join(lines)

class LarkHandler:
    """飞书消息处理器（群聊/私聊统一逻辑）"""

    _CHAT_BINDINGS_FILE = get_chat_bindings_file()
    _OLD_CHAT_BINDINGS_FILE = Path("/tmp/remote-claude/lark_chat_bindings.json")
    _LARK_GROUP_IDS_FILE = Path(get_chat_bindings_file()).parent / "lark_group_ids.json"

    def __init__(self):
        # 兼容迁移：旧绑定文件存在而新路径不存在时，自动迁移
        if not self._CHAT_BINDINGS_FILE.exists() and self._OLD_CHAT_BINDINGS_FILE.exists():
            try:
                import shutil
                ensure_user_data_dir()
                shutil.move(str(self._OLD_CHAT_BINDINGS_FILE), str(self._CHAT_BINDINGS_FILE))
            except Exception as e:
                logger.warning(f"迁移旧绑定文件失败: {e}")
        # chat_id → SessionBridge（活跃连接）
        self._bridges: Dict[str, SessionBridge] = {}
        # chat_id → session_name（当前连接状态）
        self._chat_sessions: Dict[str, str] = {}
        # 共享内存轮询器
        self._poller = SharedMemoryPoller(card_service)
        # chat_id → session_name 持久化绑定（重启后自动恢复）
        self._chat_bindings: Dict[str, str] = self._load_chat_bindings()
        # 专属群聊 chat_id 集合（仅包含通过 /new-group 创建的群）
        self._group_chat_ids: set = self._load_group_chat_ids()
        # chat_id → CardSlice（用户主动断开后保留，供重连时冻结旧卡片）
        self._detached_slices: Dict[str, CardSlice] = {}
        # 正在启动中的会话名集合（防止并发点击触发竞态）
        self._starting_sessions: set = set()
        # 用户配置（用于快捷命令选择器等 UI 设置）
        self._settings = load_settings()

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
            ensure_user_data_dir()
            self._CHAT_BINDINGS_FILE.write_text(
                json.dumps(self._chat_bindings, ensure_ascii=False)
            )
        except Exception as e:
            logger.warning(f"保存绑定失败: {e}")

    def _load_group_chat_ids(self) -> set:
        try:
            if self._LARK_GROUP_IDS_FILE.exists():
                return set(json.loads(self._LARK_GROUP_IDS_FILE.read_text()))
        except Exception:
            pass
        return set()

    def _save_group_chat_ids(self):
        try:
            ensure_user_data_dir()
            self._LARK_GROUP_IDS_FILE.write_text(
                json.dumps(list(self._group_chat_ids), ensure_ascii=False)
            )
        except Exception as e:
            logger.warning(f"保存群聊 ID 失败: {e}")

    def _remove_binding_by_chat(self, chat_id: str, force: bool = False):
        """移除 chat_id 的绑定。
        群聊绑定默认不移除（避免断开后无法解散群）；
        force=True 时强制移除（用于会话终止/解散群场景）。
        """
        if not force and chat_id in self._group_chat_ids:
            return
        self._chat_bindings.pop(chat_id, None)
        self._save_chat_bindings()

    # ── 统一 attach / detach / on_disconnect ────────────────────────────────

    async def _attach(self, chat_id: str, session_name: str,
                      user_id: Optional[str] = None) -> bool:
        """统一 attach 逻辑（私聊/群聊共用）"""
        # 在断开旧连接之前，先更新旧流式卡片为已断开状态
        old_session = self._chat_sessions.get(chat_id)
        old_slice = self._poller.stop_and_get_active_slice(chat_id)
        if old_slice and old_session:
            await self._update_card_disconnected(chat_id, old_session, old_slice)

        # 断开旧 bridge
        old = self._bridges.pop(chat_id, None)
        if old:
            await old.disconnect()
        # _poller.stop 已通过 stop_and_get_active_slice 完成
        self._chat_sessions.pop(chat_id, None)
        self._detached_slices.pop(chat_id, None)

        def on_disconnect():
            asyncio.create_task(self._on_disconnect(chat_id, session_name))

        bridge = SessionBridge(session_name, on_disconnect=on_disconnect)
        if await bridge.connect():
            self._bridges[chat_id] = bridge
            self._chat_sessions[chat_id] = session_name
            self._poller.start(chat_id, session_name, is_group=(chat_id in self._group_chat_ids),
                               notify_user_id=user_id)
            _safe_track_stats('lark', 'attach', session_name=session_name,
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
        _safe_track_stats('lark', 'disconnect', session_name=session_name,
                     chat_id=chat_id)
        active_slice = self._poller.stop_and_get_active_slice(chat_id)
        self._bridges.pop(chat_id, None)
        self._chat_sessions.pop(chat_id, None)
        self._detached_slices.pop(chat_id, None)
        self._remove_binding_by_chat(chat_id)

        if active_slice:
            await self._update_card_disconnected(chat_id, session_name, active_slice)

        # 会话退出时自动解散绑定到该会话的所有专属群聊
        await self._disband_groups_for_session(session_name, source="disconnect")

    # ── 消息入口 ────────────────────────────────────────────────────────────

    async def handle_message(self, user_id: str, chat_id: str, text: str,
                              chat_type: str = "p2p"):
        """处理用户消息（群聊/私聊统一路由）"""
        logger.info(f"收到消息: user={user_id[:8]}..., chat={chat_id[:8]}..., type={chat_type}, text={text[:50]}")
        text = text.strip()

        if text.startswith("/"):
            # /cl 前缀：去掉前缀，转发给 Claude
            if text == "/cl" or text.startswith("/cl "):
                claude_text = text[3:].strip()
                if claude_text:
                    await self._forward_to_claude(user_id, chat_id, claude_text)
                    _safe_track_stats('lark', 'message',
                                 session_name=self._chat_sessions.get(chat_id, ''),
                                 chat_id=chat_id)
            else:
                await self._handle_command(user_id, chat_id, text)
        # else: 普通聊天消息（无 /cl 前缀），不再转发给 Claude

    async def forward_to_claude(self, user_id: str, chat_id: str, text: str):
        """卡片输入框直通 Claude（跳过命令路由）"""
        await self._forward_to_claude(user_id, chat_id, text)
        _safe_track_stats('lark', 'message',
                     session_name=self._chat_sessions.get(chat_id, ''),
                     chat_id=chat_id)

    async def _handle_command(self, user_id: str, chat_id: str, text: str):
        """处理命令（群聊/私聊共用同一逻辑）"""
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        _safe_track_stats('lark', 'cmd',
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

    async def _cmd_attach(self, user_id: str, chat_id: str, args: str,
                          message_id: Optional[str] = None):
        """连接到会话"""
        session_name = args.strip()

        if not session_name:
            await self._cmd_list(user_id, chat_id, message_id=message_id)
            return

        sessions = list_active_sessions()
        if not any(s["name"] == session_name for s in sessions):
            await card_service.send_text(
                chat_id, f"会话 '{session_name}' 不存在，使用 /list 查看可用会话"
            )
            return

        ok = await self._attach(chat_id, session_name, user_id=user_id)
        if ok:
            self._chat_bindings[chat_id] = session_name
            self._save_chat_bindings()
            if message_id:
                await self._cmd_list(user_id, chat_id, message_id=message_id)
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
        """列出会话（等价于菜单）"""
        await self._cmd_menu(user_id, chat_id, message_id=message_id)

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

    async def _start_server_session(
        self,
        session_name: str,
        work_dir: Optional[str],
        chat_id: str,
        cli_command: str = "claude",
    ) -> bool:
        """启动 server 进程并等待 socket 就绪

        Args:
            session_name: 会话名称
            work_dir: 工作目录（可选）
            chat_id: 飞书聊天 ID（用于错误通知）
            cli_command: CLI 命令，默认为 "claude"

        Returns:
            bool: True 表示启动成功，False 表示失败
        """
        script_dir = Path(__file__).parent.parent.absolute()
        server_script = script_dir / "server" / "server.py"
        cmd = ["uv", "run", "--project", str(script_dir), "python3", str(server_script), session_name]
        if get_bypass_enabled():
            cmd += ["--", "--dangerously-skip-permissions", "--permission-mode=dontAsk"]

        # 添加 --cli-command 参数
        cmd += ["--cli-command", cli_command]

        logger.info(f"启动会话: {session_name}, 工作目录: {work_dir}, CLI命令: {cli_command}, 执行命令: {' '.join(cmd)}")
        _safe_track_stats('lark', 'cmd_start', session_name=session_name, chat_id=chat_id)

        try:
            env = _os.environ.copy()
            env.pop("CLAUDECODE", None)

            log_path = USER_DATA_DIR / "startup.log"
            start_time = _datetime.now()

            proc = None  # 确保在 finally 中可访问
            try:
                with open(log_path, 'a') as stderr_fd:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=stderr_fd,
                        start_new_session=True,
                        cwd=work_dir,
                        env=env,
                    )

                socket_path = get_socket_path(session_name)
                for i in range(120):
                    await asyncio.sleep(0.1)
                    if socket_path.exists():
                        return True
                    if (i + 1) % 10 == 0:
                        elapsed = (i + 1) // 10
                        rc = proc.poll()
                        if rc is not None:
                            log_content = _read_log_since(start_time, log_path)
                            logger.warning(f"会话启动失败: server 进程已退出 (exitcode={rc}, elapsed={elapsed}s)\n{log_content}")
                            await card_service.send_text(chat_id, f"错误: Server 进程意外退出 (code={rc})\n\n{log_content}")
                            return False
                        logger.info(f"等待 server socket... ({elapsed}s)")
                else:
                    # 超时时终止子进程
                    terminate_process(proc)
                    log_content = _read_log_since(start_time, log_path)
                    logger.error(f"会话启动超时 (12s), session={session_name}\n{log_content}")
                    await card_service.send_text(chat_id, f"错误: 会话启动超时 (12s)\n\n{log_content}")
                    return False
            except Exception as e:
                # 异常时清理子进程
                terminate_process(proc)
                raise

        except Exception as e:
            logger.error(f"启动会话失败: {e}")
            await card_service.send_text(chat_id, f"错误: 启动失败 - {e}")
            return False

    async def _cmd_start(self, user_id: str, chat_id: str, args: str, cli_command: str = "claude"):
        """启动新会话

        Args:
            user_id: 用户 ID
            chat_id: 聊天 ID
            args: 命令参数，格式为 "<会话名> [工作路径]"
            cli_command: CLI 命令，默认为 "claude"
        """
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

        if session_name in self._starting_sessions:
            await card_service.send_text(chat_id, f"会话 '{session_name}' 正在启动中，请稍候")
            return
        self._starting_sessions.add(session_name)

        try:
            if not await self._start_server_session(session_name, work_dir, chat_id, cli_command=cli_command):
                return

            ok = False
            for attempt in range(3):
                ok = await self._attach(chat_id, session_name, user_id=user_id)
                if ok:
                    self._chat_bindings[chat_id] = session_name
                    self._save_chat_bindings()
                    break
                if attempt < 2:
                    await asyncio.sleep(0.2)
            if not ok:
                await card_service.send_text(
                    chat_id,
                    f"会话已启动但连接失败\n使用 /attach {session_name} 重试"
                )
        finally:
            self._starting_sessions.discard(session_name)

    async def _cmd_start_and_new_group(self, user_id: str, chat_id: str,
                                       session_name: str, path: str):
        """在指定目录启动会话并创建专属群聊"""
        work_path = Path(path).expanduser()
        if not work_path.is_dir():
            await card_service.send_text(chat_id, f"错误: 路径无效: {path}")
            return

        sessions = list_active_sessions()
        active_names = {s["name"] for s in sessions}
        if session_name in active_names or session_name in self._starting_sessions:
            session_name = f"{session_name}_{_datetime.now().strftime('%m%d_%H%M%S')}"

        self._starting_sessions.add(session_name)
        work_dir = str(work_path.absolute())

        try:
            if not await self._start_server_session(session_name, work_dir, chat_id):
                return
            await self._cmd_new_group(user_id, chat_id, session_name)

        except Exception as e:
            logger.error(f"启动并创建群聊失败: {e}")
            await card_service.send_text(chat_id, f"操作失败：{e}")
        finally:
            self._starting_sessions.discard(session_name)

    async def _cmd_kill(self, user_id: str, chat_id: str, args: str,
                        message_id: Optional[str] = None):
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

        # 解散绑定该会话的专属群聊（必须在断开连接之前，否则 _chat_bindings 已被清除）
        for cid in list(self._group_chat_ids):
            if self._chat_bindings.get(cid) == session_name:
                ok, err = await self._disband_group_via_api(cid)
                if not ok:
                    logger.warning(f"关闭会话时解散群 {cid} 失败: {err}")

        # 断开所有连接到此会话的 chat
        for cid, sname in list(self._chat_sessions.items()):
            if sname == session_name:
                active_slice = self._poller.stop_and_get_active_slice(cid)
                if active_slice:
                    await self._update_card_disconnected(cid, sname, active_slice)
                await self._detach(cid)
                self._remove_binding_by_chat(cid, force=True)

        # 清理所有残留绑定（包括已断开的群聊，其绑定在断开时被保留）
        for cid in [c for c, s in list(self._chat_bindings.items()) if s == session_name]:
            self._group_chat_ids.discard(cid)
            self._chat_bindings.pop(cid, None)
        self._save_chat_bindings()
        self._save_group_chat_ids()

        if tmux_session_exists(session_name):
            tmux_kill_session(session_name)
        cleanup_session(session_name)

        await card_service.send_text(chat_id, f"✅ 会话 '{session_name}' 已终止")
        await self._cmd_list(user_id, chat_id, message_id=message_id)

    async def _handle_list_detach(self, user_id: str, chat_id: str,
                                   message_id: Optional[str] = None):
        """会话列表卡片中断开连接，就地刷新列表"""
        session_name = self._chat_sessions.get(chat_id, "")
        # 更新流式卡片为已断开状态
        active_slice = self._poller.stop_and_get_active_slice(chat_id)
        if active_slice and session_name:
            await self._update_card_disconnected(chat_id, session_name, active_slice)

        self._remove_binding_by_chat(chat_id)
        await self._detach(chat_id)   # bridge.disconnect + _poller.stop（幂等）
        await self._cmd_list(user_id, chat_id, message_id=message_id)

    async def _update_card_disconnected(self, chat_id: str, session_name: str,
                                        active_slice: 'CardSlice') -> bool:
        """读取最新 blocks 并就地更新卡片为断开状态（disconnected=True）。Best-effort，不降级发新卡。"""
        blocks = []
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
            from server.shared_state import SharedStateReader, get_mq_path
            mq_path = get_mq_path(session_name)
            if mq_path.exists():
                reader = SharedStateReader(session_name)
                state = reader.read()
                reader.close()
                blocks = state.get("blocks", [])
        except Exception:
            pass
        blocks_slice = blocks[active_slice.start_idx:]
        card = build_stream_card(blocks_slice, disconnected=True, session_name=session_name)
        try:
            return await card_service.update_card(
                card_id=active_slice.card_id,
                sequence=active_slice.sequence + 1,
                card_content=card,
            )
        except Exception as e:
            logger.warning(f"_update_card_disconnected 失败 ({chat_id[:8]}...): {e}")
            return False

    async def _handle_stream_detach(self, user_id: str, chat_id: str,
                                     session_name: str, message_id: Optional[str] = None):
        """流式卡片中断开连接，就地更新卡片为已断开状态"""
        # T059: 显示 loading 状态
        card_id = self._poller.get_active_card_id(chat_id)
        snapshot = self._poller.read_snapshot(chat_id) if card_id else None
        if card_id and snapshot:
            loading_card = build_loading_card_from_snapshot(
                snapshot, session_name, "正在断开连接...", settings=self._settings
            )
            await card_service.update_card(card_id, int(time.time() * 1000) % 1000000, loading_card)

        # 停止轮询并获取活跃 CardSlice（原子操作）
        active_slice = self._poller.stop_and_get_active_slice(chat_id)

        # 读取最后快照的 blocks
        blocks = []
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
            from server.shared_state import SharedStateReader, get_mq_path
            mq_path = get_mq_path(session_name)
            if mq_path.exists():
                reader = SharedStateReader(session_name)
                state = reader.read()
                reader.close()
                blocks = state.get("blocks", [])
        except Exception:
            pass

        self._remove_binding_by_chat(chat_id)
        # _detach 中 _poller.stop() 幂等（已调用 stop_and_get_active_slice）
        await self._detach(chat_id)

        blocks_slice = blocks[active_slice.start_idx:] if active_slice else blocks
        card = build_stream_card(blocks_slice, disconnected=True, session_name=session_name)

        updated = False
        if active_slice:
            try:
                success = await card_service.update_card(
                    card_id=active_slice.card_id,
                    sequence=active_slice.sequence + 1,
                    card_content=card,
                )
                if success:
                    active_slice.sequence += 1
                    self._detached_slices[chat_id] = active_slice
                    updated = True
            except Exception as e:
                logger.warning(f"_handle_stream_detach 就地更新失败: {e}")

        if not updated:
            await self._send_or_update_card(chat_id, card, message_id)

    async def _handle_stream_reconnect(self, user_id: str, chat_id: str,
                                       session_name: str, message_id: Optional[str] = None):
        """流式卡片中重新连接：冻结旧断开卡片 → 重新 attach"""
        # T059: 显示 loading 状态（重连中）
        loading_card = build_loading_card_from_snapshot(
            None, session_name, "正在重新连接...",
            settings=self._settings, disconnected=True
        )
        old_slice = self._detached_slices.pop(chat_id, None)
        if old_slice:
            try:
                await card_service.update_card(
                    card_id=old_slice.card_id,
                    sequence=old_slice.sequence + 1,
                    card_content=loading_card,
                )
            except Exception as e:
                logger.warning(f"_handle_stream_reconnect 冻结旧卡片失败: {e}")
        elif message_id:
            try:
                await card_service.update_card_by_message_id(message_id, loading_card)
            except Exception as e:
                logger.warning(f"_handle_stream_reconnect 按 message_id 冻结失败: {e}")

        await self._cmd_attach(user_id, chat_id, session_name)

    async def _cmd_help(self, user_id: str, chat_id: str,
                         message_id: Optional[str] = None):
        """显示帮助"""
        card = build_help_card()
        await self._send_or_update_card(chat_id, card, message_id)

    async def _cmd_menu(self, user_id: str, chat_id: str,
                         message_id: Optional[str] = None, page: int = 0):
        """显示快捷操作菜单（内嵌会话列表）"""
        sessions = list_active_sessions()
        current = self._chat_sessions.get(chat_id)
        session_groups = {
            self._chat_bindings[cid]: cid
            for cid in self._group_chat_ids
            if cid in self._chat_bindings
        }

        # 自动应答开关已迁移到会话卡片，不再在 /menu 卡片展示
        card = build_menu_card(
            sessions, current_session=current, session_groups=session_groups, page=page,
            notify_enabled=get_notify_ready_enabled(),
            urgent_enabled=get_notify_urgent_enabled(),
            bypass_enabled=get_bypass_enabled(),
            settings=self._settings
        )
        await self._send_or_update_card(chat_id, card, message_id)

    async def _cmd_toggle_notify(self, user_id: str, chat_id: str,
                                  message_id: Optional[str] = None):
        """切换就绪通知开关并刷新菜单卡片"""
        new_value = not get_notify_ready_enabled()
        set_notify_ready_enabled(new_value)
        await self._cmd_menu(user_id, chat_id, message_id=message_id)

    async def _cmd_toggle_urgent(self, user_id: str, chat_id: str,
                                  message_id: Optional[str] = None):
        """切换加急通知开关并刷新菜单卡片"""
        new_value = not get_notify_urgent_enabled()
        set_notify_urgent_enabled(new_value)
        await self._cmd_menu(user_id, chat_id, message_id=message_id)

    async def _cmd_toggle_bypass(self, user_id: str, chat_id: str,
                                  message_id: Optional[str] = None):
        """切换新会话 bypass 开关并刷新菜单卡片"""
        new_value = not get_bypass_enabled()
        set_bypass_enabled(new_value)
        await self._cmd_menu(user_id, chat_id, message_id=message_id)

    async def _cmd_toggle_auto_answer(self, user_id: str, chat_id: str,
                                       message_id: Optional[str] = None,
                                       refresh_stream: bool = False):
        """切换自动应答开关并刷新卡片"""
        session_name = self._chat_sessions.get(chat_id)
        if not session_name:
            await card_service.send_text(chat_id, "当前未连接到任何会话")
            return

        # 切换状态
        from utils.runtime_config import get_session_auto_answer_enabled, set_session_auto_answer_enabled
        new_value = not get_session_auto_answer_enabled(session_name)
        set_session_auto_answer_enabled(session_name, new_value, user_id)

        # 更新 tracker 状态
        tracker = self._poller._trackers.get(chat_id)
        if tracker:
            tracker.auto_answer_enabled = new_value
            # 取消待执行的自动应答
            if not new_value and tracker.pending_auto_answer:
                tracker.pending_auto_answer.cancel()
                tracker.pending_auto_answer = None

        logger.info(f"自动应答开关切换: session={session_name}, enabled={new_value}")

        if refresh_stream:
            card_id = self._poller.get_active_card_id(chat_id)
            snapshot = self._poller.read_snapshot(chat_id) if card_id else None
            if snapshot:
                card = build_stream_card(
                    blocks=snapshot.get("blocks", []),
                    status_line=snapshot.get("status_line"),
                    bottom_bar=snapshot.get("bottom_bar"),
                    agent_panel=snapshot.get("agent_panel"),
                    option_block=snapshot.get("option_block"),
                    session_name=session_name,
                    cli_type=snapshot.get("cli_type", "claude"),
                    settings=self._settings,
                )
                if card_id:
                    try:
                        await card_service.update_card(card_id, int(time.time() * 1000) % 1000000, card)
                        return
                    except Exception as e:
                        logger.warning(f"刷新会话卡片失败（fallback 到 message_id）: {e}")
                if message_id:
                    await self._send_or_update_card(chat_id, card, message_id)
                    return

        # 刷新菜单卡片
        await self._cmd_menu(user_id, chat_id, message_id=message_id)

    async def _cmd_ls(self, user_id: str, chat_id: str, args: str,
                       tree: bool = False, message_id: Optional[str] = None, page: int = 0):
        """查看目录文件结构"""
        all_sessions = list_active_sessions()
        sessions_info = []
        for s in all_sessions:
            pid = s.get("pid")
            cwd = get_process_cwd(pid) if pid else None
            sessions_info.append({"name": s["name"], "cwd": cwd or ""})

        bound_session = self._chat_sessions.get(chat_id)
        if bound_session:
            pid = next((s.get("pid") for s in all_sessions if s["name"] == bound_session), None)
            session_cwd = get_process_cwd(pid) if pid else None
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

        session_groups = {
            self._chat_bindings[cid]: cid
            for cid in self._group_chat_ids
            if cid in self._chat_bindings
        }
        card = build_dir_card(target, entries, sessions_info, tree=tree, session_groups=session_groups, page=page, settings=self._settings)
        await self._send_or_update_card(chat_id, card, message_id)

    async def _cmd_new_group(self, user_id: str, chat_id: str, args: str,
                              message_id: Optional[str] = None):
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
        cwd = get_process_cwd(pid) if pid else None
        dir_label = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else session_name

        from . import config
        try:
            import json as _json
            import urllib.request
            import datetime
            _time_str = datetime.datetime.now().strftime("%H-%M")
            group_name = f"{config.GROUP_NAME_PREFIX}{dir_label}-{_time_str}"
            req_body = {
                "name": group_name,
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
            self._group_chat_ids.add(group_chat_id)
            self._save_group_chat_ids()
            # 立即 attach，让新群即刻开始接收 Claude 输出
            await self._attach(group_chat_id, session_name, user_id=user_id)

            # 刷新会话列表卡片，使"创建群聊"按钮变为"进入群聊"
            await self._cmd_list(user_id, chat_id, message_id=message_id)
        except Exception as e:
            logger.error(f"创建群失败: {e}")
            await card_service.send_text(chat_id, f"创建群失败：{e}")

    async def _disband_group_via_api(self, group_chat_id: str) -> tuple:
        """调用飞书 API 解散群聊，返回 (ok: bool, err_msg: str)"""
        import json as _json
        import urllib.request
        import urllib.error
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
            try:
                disband_resp = urllib.request.urlopen(
                    urllib.request.Request(
                        f"https://open.feishu.cn/open-apis/im/v1/chats/{group_chat_id}",
                        headers={"Authorization": f"Bearer {token}"},
                        method="DELETE"
                    ), timeout=10
                )
                disband_data = _json.loads(disband_resp.read())
                if disband_data.get("code") == 0:
                    return True, ""
                return False, disband_data.get("msg", "")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                try:
                    err_data = _json.loads(err_body)
                    return False, f"code={err_data.get('code')} {err_data.get('msg', '')}"
                except Exception:
                    return False, f"HTTP {e.code}"
        except Exception as e:
            return False, str(e)

    async def _disband_groups_for_session(self, session_name: str, source: str = ""):
        """解散绑定到指定会话的所有专属群聊"""
        disbanded = []
        for cid in list(self._group_chat_ids):
            if self._chat_bindings.get(cid) == session_name:
                log_prefix = f"[{source}] " if source else ""
                logger.info(f"{log_prefix}自动解散群聊: chat_id={cid[:8]}..., session={session_name}")
                # 先清理本地状态（防止并发协程重入时重复处理）
                self._group_chat_ids.discard(cid)
                self._chat_bindings.pop(cid, None)
                disbanded.append(cid)
                # 停止轮询 + 断开 bridge
                self._poller.stop(cid)
                bridge = self._bridges.pop(cid, None)
                if bridge:
                    await bridge.disconnect()
                self._chat_sessions.pop(cid, None)
                self._detached_slices.pop(cid, None)
                # 调用飞书 API 解散
                ok, err = await self._disband_group_via_api(cid)
                if not ok:
                    logger.warning(f"{log_prefix}解散群 {cid[:8]}... API 失败: {err}")
        if disbanded:
            self._save_chat_bindings()
            self._save_group_chat_ids()

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

        try:
            feishu_ok, feishu_msg = await self._disband_group_via_api(group_chat_id)
            if not feishu_ok:
                logger.error(f"解散群 API 失败: {feishu_msg}")

            # 无论 Feishu delete 是否成功，都清理本地绑定
            self._group_chat_ids.discard(group_chat_id)
            self._save_group_chat_ids()
            self._remove_binding_by_chat(group_chat_id, force=True)
            await self._detach(group_chat_id)

            if not feishu_ok:
                await card_service.send_text(
                    chat_id,
                    f"⚠️ Feishu 群解散失败（{feishu_msg}），已解除本地绑定。如需彻底解散请在飞书群内手动操作"
                )
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
                ok = await self._attach(chat_id, saved_session, user_id=user_id)
                if not ok:
                    self._group_chat_ids.discard(chat_id)
                    self._save_group_chat_ids()
                    self._remove_binding_by_chat(chat_id, force=True)
                    await card_service.send_text(
                        chat_id, f"会话 '{saved_session}' 已不存在，请重新 /attach"
                    )
                    # 会话已不存在，解散绑定到该会话的所有专属群聊
                    await self._disband_groups_for_session(saved_session, source="lazy")
                    return
                bridge = self._bridges.get(chat_id)
            else:
                await card_service.send_text(
                    chat_id, "未连接到任何会话，请先使用 /attach <会话名> 连接"
                )
                return

        if not bridge:
            return

        # 自动应答模式下，增强模糊指令
        session_name = self._chat_sessions.get(chat_id)
        if session_name:
            from utils.runtime_config import (
                get_session_auto_answer_enabled,
                get_vague_commands_config
            )
            if get_session_auto_answer_enabled(session_name):
                vague_commands, vague_prompt = get_vague_commands_config()
                text_lower = text.strip().lower()
                vague_commands_lower = {cmd.lower() for cmd in vague_commands}
                if text_lower in vague_commands_lower:
                    # 追加提示，引导模型采取行动而非只返回状态
                    text = f"{text}\n\n{vague_prompt}"
                    logger.debug(f"自动应答模式下增强模糊指令: {text[:50]}...")

        success = await bridge.send_input(text)
        if success:
            self._poller.kick(chat_id)
        else:
            await card_service.send_text(chat_id, "发送失败")

    # ── 选项处理 ─────────────────────────────────────────────────────────────

    async def handle_option_select(self, user_id: str, chat_id: str, option_value: str, option_total: int = 0, *, needs_input: bool = False):
        """闭环选项选择：箭头键导航 + 共享内存验证

        发箭头键导航到目标选项，每步从共享内存读取 selected_value 确认是否到位，
        到位后发 Enter 确认。避免数字键在溢出选项上无效的问题。
        """
        logger.info(f"处理选项选择: user={user_id[:8]}..., option={option_value}, total={option_total}")
        _safe_track_stats('lark', 'option_select',
                     session_name=self._chat_sessions.get(chat_id, ''),
                     chat_id=chat_id, detail=option_value)

        # 检查卡片是否过期
        tracker = self._poller._trackers.get(chat_id)
        if tracker and tracker.cards:
            active_slice = tracker.cards[-1]
            if active_slice.expired:
                await card_service.send_text(chat_id, "⚠️ 卡片已过期，请刷新后重试")
                return

        # 用户手动选择时取消自动应答
        session_name = self._chat_sessions.get(chat_id)
        if session_name:
            self._poller.cancel_auto_answer(session_name)

        bridge = self._bridges.get(chat_id)
        if not bridge or not bridge.running:
            await card_service.send_text(chat_id, "未连接到任何会话，请先使用 /attach <会话名> 连接")
            return

        target = option_value  # 目标选项 value（如 "2"）
        max_steps = max(option_total, 10) if option_total > 0 else 10

        # 记录初始 option_block 的 block_id，防止跨选项交互误操作
        initial_snapshot = self._poller.read_snapshot(chat_id)
        if not initial_snapshot:
            return
        initial_ob = initial_snapshot.get('option_block')
        if not initial_ob:
            return
        initial_block_id = initial_ob.get('block_id', '')

        # T058: 使用 update_card 显示 loading 状态
        card_id = self._poller.get_active_card_id(chat_id)
        if card_id:
            # 构建带 loading 状态的卡片（禁用所有选项按钮）
            loading_card = build_loading_card_from_snapshot(
                initial_snapshot, self._chat_sessions.get(chat_id), "正在选择...",
                settings=self._settings, option_block=initial_ob,
            )
            await card_service.update_card(card_id, int(time.time() * 1000) % 1000000, loading_card)

        for step in range(max_steps):
            # 1. 读取当前选中项
            snapshot = self._poller.read_snapshot(chat_id)
            if not snapshot:
                break
            ob = snapshot.get('option_block')
            if not ob:
                break  # option_block 已消失（CLI 已进入下一状态）

            # 检查 block_id 一致性
            if initial_block_id and ob.get('block_id', '') != initial_block_id:
                logger.warning(f"option_block 已切换，中止选项选择")
                break

            current = ob.get('selected_value', '')

            # 闪烁帧重试：❯ 光标字符会时隐时现，selected_value 为空时短暂重试
            if not current:
                for _retry in range(5):  # 最多重试 5 次，共 500ms
                    await asyncio.sleep(0.1)
                    snap = self._poller.read_snapshot(chat_id)
                    if not snap:
                        break
                    retry_ob = snap.get('option_block')
                    if not retry_ob:
                        break
                    current = retry_ob.get('selected_value', '')
                    if current:
                        break

            # 2. 已到位 → 发 Enter（自由输入选项只导航不发 Enter）
            if current == target:
                if needs_input:
                    logger.info(f"自由输入选项已到位: target={target}，不发送 Enter")
                    self._poller.kick(chat_id)
                    return
                logger.info(f"选项已到位: current={current} == target={target}，发送 Enter")
                success = await bridge.send_raw(b"\r")
                if success:
                    self._poller.kick(chat_id)
                else:
                    await card_service.send_text(chat_id, "发送选择失败")
                return

            # 3. 未到位 → 发箭头键
            if current and target:
                try:
                    if int(current) < int(target):
                        logger.info(f"步骤{step}: current={current} < target={target}，发送 ↓")
                        await bridge.send_raw(b"\x1b[B")  # ↓
                    else:
                        logger.info(f"步骤{step}: current={current} > target={target}，发送 ↑")
                        await bridge.send_raw(b"\x1b[A")  # ↑
                except ValueError:
                    logger.warning(f"步骤{step}: 无法比较 current={current!r} 和 target={target!r}，发送 ↓")
                    await bridge.send_raw(b"\x1b[B")
            else:
                # selected_value 重试后仍为空（真正的初始状态），默认向下
                logger.info(f"步骤{step}: selected_value 重试后仍为空，发送 ↓")
                await bridge.send_raw(b"\x1b[B")

            # 4. 等待共享内存更新（轮询直到 selected_value 变为另一个非空值或超时）
            old_selected = current
            deadline = time.time() + 2.0  # 单步超时 2s
            while time.time() < deadline:
                await asyncio.sleep(0.1)  # 100ms 轮询
                snap = self._poller.read_snapshot(chat_id)
                if not snap:
                    break
                new_ob = snap.get('option_block')
                if not new_ob:
                    break  # option_block 消失，退出
                if initial_block_id and new_ob.get('block_id', '') != initial_block_id:
                    break  # block_id 变了，外层会处理
                new_selected = new_ob.get('selected_value', '')
                # 忽略闪烁帧：只有变为另一个非空值才视为真正变化
                if new_selected and new_selected != old_selected:
                    break

        # 超过 max_steps 仍未到位，记录警告
        logger.warning(f"选项选择超步数: target={target}, steps={max_steps}")

    # ── 快捷键发送 ─────────────────────────────────────────────────────────────

    async def send_raw_key(self, user_id: str, chat_id: str, key_name: str):
        """发送原始控制键到 Claude CLI"""
        _safe_track_stats('lark', 'raw_key',
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

    # ── 快捷命令处理 ─────────────────────────────────────────────────────────────

    async def handle_quick_command(self, user_id: str, chat_id: str, command: str):
        """处理快捷命令选择事件

        Args:
            user_id: 用户 ID
            chat_id: 聊天 ID
            command: 命令字符串（如 "/clear"）
        """
        logger.info(f"处理快捷命令: user={user_id[:8]}..., command={command}")
        _safe_track_stats('lark', 'quick_command',
                     session_name=self._chat_sessions.get(chat_id, ''),
                     chat_id=chat_id, detail=command)

        bridge = self._bridges.get(chat_id)
        if not bridge or not bridge.running:
            # 尝试从持久化绑定自动恢复
            saved_session = self._chat_bindings.get(chat_id)
            if saved_session:
                logger.info(f"快捷命令自动恢复绑定: chat_id={chat_id[:8]}..., session={saved_session}")
                ok = await self._attach(chat_id, saved_session, user_id=user_id)
                if not ok:
                    await card_service.send_text(chat_id, f"会话 '{saved_session}' 已不存在，请重新 /attach")
                    return
                bridge = self._bridges.get(chat_id)
            else:
                await card_service.send_text(chat_id, "未连接到任何会话，请先使用 /attach <会话名> 连接")
                return

        if not bridge:
            return

        # T057: 使用 update_card 显示 loading 状态
        card_id = self._poller.get_active_card_id(chat_id)
        snapshot = self._poller.read_snapshot(chat_id) if card_id else None

        if card_id and snapshot:
            # 构建带 loading 状态的卡片
            loading_card = build_loading_card_from_snapshot(
                snapshot, self._chat_sessions.get(chat_id), f"执行命令 {command}...",
                settings=self._settings,
            )
            # 就地更新卡片，不等待结果
            await card_service.update_card(card_id, int(time.time() * 1000) % 1000000, loading_card)

        # 发送命令到 Claude（命令已包含换行符，如 "/clear\n"）
        success = await bridge.send_input(command)
        if success:
            self._poller.kick(chat_id)
            logger.info(f"快捷命令已发送: {command}")
        else:
            logger.warning(f"快捷命令发送失败: {command}")
            # 失败时降级为发送文本提示，poller 会自动刷新卡片
            await card_service.send_text(chat_id, f"命令发送失败，请重试")

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
        return entries

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

    async def disconnect_all_for_shutdown(self) -> None:
        """lark stop 时清理所有活跃流式卡片（更新为已断开状态）"""
        chat_ids = list(self._bridges.keys())
        for chat_id in chat_ids:
            session_name = self._chat_sessions.get(chat_id, "")
            active_slice = self._poller.stop_and_get_active_slice(chat_id)
            if active_slice and session_name:
                await self._update_card_disconnected(chat_id, session_name, active_slice)


# 全局处理器实例
handler = LarkHandler()
