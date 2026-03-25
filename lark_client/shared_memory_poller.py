"""
共享内存轮询器 - 流式滚动卡片模型

核心理念：没有 turn、没有 message。只有一个不断增长的 blocks 流和跟踪它的滚动窗口。

数据流：
  .mq { blocks, status_line, bottom_bar }
              ↓ 每秒轮询
    _poll_once(tracker)
              ↓
    渲染 blocks[start_idx:] → 卡片 elements
              ↓ hash diff
    同一张卡片就地更新 / 超限时冻结+开新卡
"""

import asyncio
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger('SharedMemoryPoller')

# 添加 server/ 目录到路径（访问 shared_state）
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "server"))
sys.path.insert(0, str(_root))

from utils.session import ensure_user_data_dir, USER_DATA_DIR
from utils.runtime_config import (
    load_user_config,
    get_notify_ready_enabled,
    get_notify_urgent_enabled,
    increment_ready_notify_count,
    get_session_auto_answer_enabled,
)
from utils.stats_helper import safe_track_stats as _safe_track_stats
from server.biz_enum import CliType

# 模块级用户配置（用于快捷命令选择器）
_user_config = load_user_config()

# ── 自动应答选项解析 ─────────────────────────────────────────────────────────

# 无明确语义关键词（用于识别确认类选项）
VAGUE_KEYWORDS = {
    # 中文
    '继续', '好的', '是', '确认', '明白', '可以', '行', '对',
    # 英文
    'continue', 'yes', 'ok', 'proceed', 'go ahead', 'sure', 'confirm', 'alright', 'fine'
}


def analyze_option_block(option_block: dict) -> tuple:
    """分析选项块，返回应答类型和内容

    根据选项内容采用三种策略：
    1. 推荐选项优先：选择标记为 "(recommended)" 或 "推荐" 的选项
    2. 无明确语义时回复"继续"：第一个选项为确认类文本时发送"继续"
    3. 兜底选择第一项：其他情况选择第一个选项

    Args:
        option_block: 选项块字典，包含 options 列表

    Returns:
        (action_type, action_value)
        action_type: "select" | "input"
        action_value: 选项 value 或输入文本
    """
    options = option_block.get('options', [])
    if not options:
        return ("input", "继续")

    # 策略一：查找推荐选项
    for opt in options:
        label = opt.get('label', '').lower()
        if '(recommended)' in label or '推荐' in label:
            return ("select", opt.get('value'))

    # 策略二：检查第一个选项是否为无明确语义的确认类选项
    # 如果第一个选项包含模糊关键词（如"继续"、"Yes"、"OK"），则发送"继续"
    first_label = options[0].get('label', '').lower().strip()
    if any(kw in first_label for kw in VAGUE_KEYWORDS):
        return ("input", "继续")

    # 策略三：兜底选择第一项
    return ("select", options[0].get('value'))


# ── 常量 ──────────────────────────────────────────────────────────────────────
INITIAL_WINDOW = 30    # 首次 attach 最多显示最近 30 个 blocks
from .config import MAX_CARD_BLOCKS  # 单张卡片最多 N 个 blocks → 超限冻结（可通过 .env 配置）
CARD_SIZE_LIMIT = 25 * 1024  # 25KB，飞书限制 30KB，留 5KB 余量
POLL_INTERVAL = 1.0    # 轮询间隔（秒）
RAPID_INTERVAL = 0.2   # 快速轮询间隔（秒）
RAPID_DURATION = 2.0   # 快速轮询持续时间（秒）


# ── 数据模型 ──────────────────────────────────────────────────────────────────

@dataclass
class CardSlice:
    """一张飞书卡片对应的 blocks 窗口"""
    card_id: str
    sequence: int = 0
    start_idx: int = 0       # blocks[start_idx:] 开始渲染
    frozen: bool = False
    last_activity_time: float = 0.0  # 最后活动时间戳（更新/操作）
    expired: bool = False             # 是否已过期


@dataclass
class StreamTracker:
    """单个 chat_id 的流式跟踪状态"""
    chat_id: str
    session_name: str
    cards: List[CardSlice] = field(default_factory=list)
    content_hash: str = ""
    reader: Optional[Any] = None  # SharedStateReader，延迟初始化
    is_group: bool = False         # 是否为群聊
    prev_is_ready: bool = True     # 上一帧是否就绪（初始 True 避免首次误触发）
    notify_user_id: Optional[str] = None  # 就绪通知 @ 的用户 open_id
    last_notify_message_id: Optional[str] = None  # 上一条就绪通知的 message_id（用于后续加急复用）
    # 自动应答相关字段
    auto_answer_enabled: bool = False      # 从 session 级别状态加载
    pending_auto_answer: Optional[asyncio.Task] = None  # 待执行的自动应答 Task


# ── 轮询器 ────────────────────────────────────────────────────────────────────

class SharedMemoryPoller:
    """
    共享内存轮询器（流式滚动卡片模型）

    attach 时启动轮询 Task，detach/断线时停止。
    每秒读取 .mq 文件中的 blocks 流，通过 hash diff 触发飞书卡片创建/更新。
    """

    def __init__(self, card_service: Any):
        self._card_service = card_service
        self._trackers: Dict[str, StreamTracker] = {}  # chat_id → StreamTracker
        self._tasks: Dict[str, asyncio.Task] = {}       # chat_id → Task
        self._kick_events: Dict[str, asyncio.Event] = {}  # chat_id → Event（唤醒轮询）
        self._rapid_until: Dict[str, float] = {}           # chat_id → 快速模式截止时间

    def start(self, chat_id: str, session_name: str, is_group: bool = False,
              notify_user_id: Optional[str] = None) -> None:
        """attach 成功后调用：清空旧状态，启动轮询 Task"""
        self.stop(chat_id)

        # 从持久化状态加载自动应答开关
        auto_answer_enabled = get_session_auto_answer_enabled(session_name)

        tracker = StreamTracker(
            chat_id=chat_id,
            session_name=session_name,
            is_group=is_group,
            notify_user_id=notify_user_id,
            auto_answer_enabled=auto_answer_enabled,
        )
        self._trackers[chat_id] = tracker
        self._kick_events[chat_id] = asyncio.Event()

        task = asyncio.create_task(self._poll_loop(chat_id))
        task.add_done_callback(lambda t: self._on_task_done(t, chat_id))
        self._tasks[chat_id] = task
        logger.info(f"轮询器启动: chat_id={chat_id[:8]}..., session={session_name}")

    def stop(self, chat_id: str) -> None:
        """detach/断线时调用：取消 Task，清空状态，关闭 Reader"""
        task = self._tasks.pop(chat_id, None)
        if task:
            task.cancel()

        self._kick_events.pop(chat_id, None)
        self._rapid_until.pop(chat_id, None)

        tracker = self._trackers.pop(chat_id, None)
        if tracker and tracker.reader:
            try:
                tracker.reader.close()
            except OSError as e:
                logger.debug(f"关闭 Reader 失败: {e}")
            except Exception as e:
                logger.warning(f"关闭 Reader 发生意外错误: {e}")
        logger.info(f"轮询器停止: chat_id={chat_id[:8]}...")

    def stop_and_get_active_slice(self, chat_id: str) -> Optional['CardSlice']:
        """停止轮询并返回活跃（未冻结）CardSlice，原子操作。供 detach/disconnect 就地更新卡片使用。"""
        task = self._tasks.pop(chat_id, None)
        if task:
            task.cancel()

        self._kick_events.pop(chat_id, None)
        self._rapid_until.pop(chat_id, None)

        tracker = self._trackers.pop(chat_id, None)
        if not tracker:
            return None

        active = None
        if tracker.cards and not tracker.cards[-1].frozen:
            active = tracker.cards[-1]

        if tracker.reader:
            try:
                tracker.reader.close()
            except OSError as e:
                logger.debug(f"关闭 Reader 失败: {e}")
            except Exception as e:
                logger.warning(f"关闭 Reader 发生意外错误: {e}")

        logger.info(f"轮询器停止(含活跃切片): chat_id={chat_id[:8]}..., active={'有' if active else '无'}")
        return active

    def _on_task_done(self, task: asyncio.Task, chat_id: str) -> None:
        """Task 完成回调：记录异常"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"轮询 Task 异常: chat_id={chat_id[:8]}..., {exc}", exc_info=exc)

    def read_snapshot(self, chat_id: str) -> Optional[dict]:
        """直接读取指定 chat_id 的当前共享内存快照（供 handle_option_select 等即时查询使用）"""
        tracker = self._trackers.get(chat_id)
        if tracker and tracker.reader:
            try:
                return tracker.reader.read()
            except OSError as e:
                logger.warning(f"read_snapshot 失败（系统错误）: {e}")
            except json.JSONDecodeError as e:
                logger.warning(f"read_snapshot 失败（数据格式错误）: {e}")
            except Exception as e:
                logger.error(f"read_snapshot 失败: {e}", exc_info=True)
        return None

    def kick(self, chat_id: str) -> None:
        """触发立即轮询并进入快速轮询模式"""
        self._rapid_until[chat_id] = time.time() + RAPID_DURATION
        ev = self._kick_events.get(chat_id)
        if ev:
            ev.set()

    def get_active_card_id(self, chat_id: str) -> Optional[str]:
        """获取活跃（未冻结）卡片的 card_id，用于就地更新。不停止轮询。"""
        tracker = self._trackers.get(chat_id)
        if tracker and tracker.cards and not tracker.cards[-1].frozen:
            return tracker.cards[-1].card_id
        return None

    async def _poll_loop(self, chat_id: str) -> None:
        """轮询循环：支持 kick 唤醒 + 快速轮询模式"""
        while True:
            try:
                # 动态间隔：快速模式 0.2s，常规 1.0s
                rapid_until = self._rapid_until.get(chat_id, 0)
                interval = RAPID_INTERVAL if time.time() < rapid_until else POLL_INTERVAL

                # 等待 kick 事件或超时
                kick_event = self._kick_events.get(chat_id)
                if kick_event:
                    try:
                        await asyncio.wait_for(kick_event.wait(), timeout=interval)
                        kick_event.clear()
                        # kick 触发时进入快速模式
                        self._rapid_until[chat_id] = time.time() + RAPID_DURATION
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(interval)

                tracker = self._trackers.get(chat_id)
                if not tracker:
                    break
                await self._poll_once(tracker)
            except asyncio.CancelledError:
                break
            except OSError as e:
                logger.error(f"_poll_loop 系统错误: {e}")
            except Exception as e:
                logger.error(f"_poll_once 异常: {e}", exc_info=True)

    async def _poll_once(self, tracker: StreamTracker) -> None:
        """单次轮询：读取共享内存 → diff → 创建/更新卡片 → 就绪通知"""
        # 步骤 1：延迟初始化 Reader
        if tracker.reader is None:
            try:
                from server.shared_state import get_mq_path, SharedStateReader
                mq_path = get_mq_path(tracker.session_name)
                if not mq_path.exists():
                    return
                tracker.reader = SharedStateReader(tracker.session_name)
                logger.info(f"Reader 初始化成功: session={tracker.session_name}")
            except FileNotFoundError as e:
                logger.warning(f"共享内存文件不存在: {e}")
                return
            except OSError as e:
                logger.warning(f"创建 Reader 失败（系统错误）: {e}")
                return
            except Exception as e:
                logger.error(f"创建 Reader 失败: {e}", exc_info=True)
                return

        # 读取共享内存
        try:
            state = tracker.reader.read()
        except OSError as e:
            logger.error(f"读取共享内存失败（系统错误）: {e}")
            tracker.reader = None
            return
        except json.JSONDecodeError as e:
            logger.error(f"读取共享内存失败（数据格式错误）: {e}")
            tracker.reader = None
            return
        except Exception as e:
            logger.error(f"读取共享内存失败: {e}", exc_info=True)
            tracker.reader = None
            return

        blocks = state.get("blocks", [])
        status_line = state.get("status_line")
        bottom_bar = state.get("bottom_bar")
        agent_panel = state.get("agent_panel")
        option_block = state.get("option_block")
        cli_type = state.get("cli_type", "claude")

        # 步骤 2：仅计算就绪状态，不发送通知
        should_notify = self._update_ready_state(tracker, blocks, status_line, option_block)

        # 步骤 3：卡片操作（含创建/更新/拆分）
        await self._do_card_update(tracker, blocks, status_line, bottom_bar, agent_panel, option_block, cli_type)

        # 步骤 4：通知在卡片操作之后发送，确保新卡先出现
        if should_notify:
            await self._send_ready_notification(tracker, cli_type)

    async def _do_card_update(
        self, tracker: StreamTracker, blocks: List[dict],
        status_line: Optional[dict], bottom_bar: Optional[dict],
        agent_panel: Optional[dict], option_block: Optional[dict],
        cli_type: str,
    ) -> None:
        """卡片操作主体：获取活跃卡片 → 创建/更新/拆分"""
        # 获取活跃卡片（最后一张且未冻结）
        active = None
        if tracker.cards and not tracker.cards[-1].frozen:
            active = tracker.cards[-1]

        if not blocks and not status_line and not bottom_bar and not agent_panel and not option_block and active is None:
            return  # 完全无内容且无活跃卡片时不创建卡片

        if active is None:
            # 需要创建新卡片
            await self._create_new_card(tracker, blocks, status_line, bottom_bar, agent_panel, option_block, cli_type=cli_type)
            return

        # 有活跃卡片，检查是否需要更新
        blocks_slice = blocks[active.start_idx:]

        # blocks 骤降检测（compact/重启导致 blocks 从头累积）
        if len(blocks) < active.start_idx:
            logger.warning(
                f"[blocks regression] len(blocks)={len(blocks)} < start_idx={active.start_idx}, "
                f"resetting start_idx to 0 (session={tracker.session_name})"
            )
            active.start_idx = 0
            blocks_slice = blocks[0:]
            tracker.content_hash = ""  # 强制刷新

        # 超限检查
        if len(blocks_slice) > MAX_CARD_BLOCKS:
            await self._freeze_and_split(tracker, blocks, status_line, bottom_bar, agent_panel, option_block, cli_type=cli_type)
            return

        # hash diff
        new_hash = self._compute_hash(blocks_slice, status_line, bottom_bar, agent_panel, option_block)
        if new_hash == tracker.content_hash:
            return  # 无变化

        # 更新卡片
        from .card_builder import build_stream_card
        card_dict = build_stream_card(blocks_slice, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name, cli_type=cli_type, user_config=_user_config)

        # 大小超限检查（与 blocks 数量超限同一套逻辑）
        card_size = len(json.dumps(card_dict, ensure_ascii=False).encode('utf-8'))
        if card_size > CARD_SIZE_LIMIT:
            freeze_count = self._find_freeze_count(blocks_slice, tracker.session_name)
            await self._freeze_and_split(
                tracker, blocks, status_line, bottom_bar, agent_panel, option_block,
                cli_type=cli_type, freeze_count=freeze_count,
            )
            return

        active.sequence += 1
        active.last_activity_time = time.time()
        success = await self._card_service.update_card(
            card_id=active.card_id,
            sequence=active.sequence,
            card_content=card_dict,
        )

        if getattr(success, 'is_element_limit', False):
            # 元素超限：冻结旧卡 + 推新流式卡
            await self._handle_element_limit(
                tracker, blocks, status_line, bottom_bar, agent_panel, option_block,
                cli_type=cli_type,
            )
            return
        elif not success:
            # 降级：创建新卡片替代
            logger.warning(
                f"update_card 失败 card_id={active.card_id} seq={active.sequence}，降级为新卡片"
            )
            _safe_track_stats('card', 'fallback', session_name=tracker.session_name,
                         chat_id=tracker.chat_id)
            new_card_id = await self._card_service.create_card(card_dict)
            if new_card_id:
                await self._card_service.send_card(tracker.chat_id, new_card_id)
                active.card_id = new_card_id
                active.sequence = 0
        else:
            _safe_track_stats('card', 'update', session_name=tracker.session_name,
                         chat_id=tracker.chat_id)

        tracker.content_hash = new_hash
        logger.debug(
            f"[UPDATE] session={tracker.session_name} blocks={len(blocks_slice)} "
            f"seq={active.sequence} hash={new_hash[:8]}"
        )

    async def _create_new_card(
        self, tracker: StreamTracker, blocks: List[dict],
        status_line: Optional[dict], bottom_bar: Optional[dict],
        agent_panel: Optional[dict] = None,
        option_block: Optional[dict] = None,
        cli_type: str = "claude",
    ) -> None:
        """创建新卡片（首次 attach 或冻结后）"""
        if not tracker.cards:
            # 首次 attach：取最近 INITIAL_WINDOW 个 blocks
            start_idx = max(0, len(blocks) - INITIAL_WINDOW)
        else:
            # 冻结后：从上张冻结卡片的结束位置开始
            last_frozen = tracker.cards[-1]
            start_idx = last_frozen.start_idx + MAX_CARD_BLOCKS
            if start_idx >= len(blocks):
                start_idx = 0
                logger.warning(
                    f"[_create_new_card] start_idx overflow, reset to 0 "
                    f"(frozen.start_idx={last_frozen.start_idx}, total blocks={len(blocks)})"
                )

        blocks_slice = blocks[start_idx:]
        if not blocks_slice and not status_line and not bottom_bar and not agent_panel and not option_block:
            return

        from .card_builder import build_stream_card
        card_dict = build_stream_card(blocks_slice, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name, cli_type=cli_type, user_config=_user_config)

        # 新卡大小检查：超限则从头部裁剪
        card_size = len(json.dumps(card_dict, ensure_ascii=False).encode('utf-8'))
        while card_size > CARD_SIZE_LIMIT and len(blocks_slice) > 1:
            blocks_slice = blocks_slice[1:]
            start_idx += 1
            card_dict = build_stream_card(blocks_slice, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name, cli_type=cli_type, user_config=_user_config)
            card_size = len(json.dumps(card_dict, ensure_ascii=False).encode('utf-8'))

        card_id = await self._card_service.create_card(card_dict)

        if card_id:
            await self._card_service.send_card(tracker.chat_id, card_id)
            tracker.cards.append(CardSlice(
                card_id=card_id,
                start_idx=start_idx,
                last_activity_time=time.time(),
            ))
            tracker.content_hash = self._compute_hash(blocks_slice, status_line, bottom_bar, agent_panel, option_block)
            _safe_track_stats('card', 'create', session_name=tracker.session_name,
                         chat_id=tracker.chat_id)
            logger.info(
                f"[NEW] session={tracker.session_name} start_idx={start_idx} "
                f"blocks={len(blocks_slice)} card_id={card_id}"
            )
        else:
            logger.warning(f"create_card 失败 session={tracker.session_name}")

    async def _handle_element_limit(
        self, tracker: StreamTracker, blocks: List[dict],
        status_line: Optional[dict], bottom_bar: Optional[dict],
        agent_panel: Optional[dict] = None,
        option_block: Optional[dict] = None,
        cli_type: str = "claude",
    ) -> None:
        """元素超限：冻结旧卡片 + 推送新流式卡片"""
        active = tracker.cards[-1]
        logger.warning(f"元素超限，冻结卡片 {active.card_id} 并推新卡")

        # 1. 冻结旧卡片（灰色 header，无状态区和按钮）
        from .card_builder import build_stream_card
        blocks_slice = blocks[active.start_idx:]
        frozen_card = build_stream_card(blocks_slice, None, None, is_frozen=True)
        active.sequence += 1
        await self._card_service.update_card(active.card_id, active.sequence, frozen_card)
        active.frozen = True
        _safe_track_stats('card', 'freeze', session_name=tracker.session_name,
                     chat_id=tracker.chat_id)

        # 2. 创建新流式卡片，从最近 INITIAL_WINDOW 个 blocks 开始（重置窗口）
        new_start = max(0, len(blocks) - INITIAL_WINDOW)
        new_blocks = blocks[new_start:]
        if not new_blocks and not status_line and not bottom_bar:
            return
        new_card_dict = build_stream_card(
            new_blocks, status_line, bottom_bar,
            agent_panel=agent_panel, option_block=option_block,
            session_name=tracker.session_name,
            cli_type=cli_type,
            user_config=_user_config,
        )
        new_card_id = await self._card_service.create_card(new_card_dict)
        if new_card_id:
            await self._card_service.send_card(tracker.chat_id, new_card_id)
            tracker.cards.append(CardSlice(
                card_id=new_card_id,
                start_idx=new_start,
                last_activity_time=time.time(),
            ))
            tracker.content_hash = self._compute_hash(new_blocks, status_line, bottom_bar, agent_panel, option_block)
            _safe_track_stats('card', 'create', session_name=tracker.session_name,
                         chat_id=tracker.chat_id)
            logger.info(
                f"[ELEMENT_LIMIT_SPLIT] session={tracker.session_name} "
                f"new_start={new_start} blocks={len(new_blocks)} card_id={new_card_id}"
            )
            tracker.last_notify_message_id = None

    def _find_freeze_count(self, blocks_slice: List[dict], session_name: str) -> int:
        """二分查找冻结卡片能容纳的最大 blocks 数（保证卡片 JSON 大小 ≤ CARD_SIZE_LIMIT）"""
        from .card_builder import build_stream_card
        lo, hi = 1, len(blocks_slice)
        result = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            card = build_stream_card(blocks_slice[:mid], None, None,
                                     is_frozen=True, session_name=session_name)
            size = len(json.dumps(card, ensure_ascii=False).encode('utf-8'))
            if size <= CARD_SIZE_LIMIT:
                result = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return result

    async def _freeze_and_split(
        self, tracker: StreamTracker, blocks: List[dict],
        status_line: Optional[dict], bottom_bar: Optional[dict],
        agent_panel: Optional[dict] = None,
        option_block: Optional[dict] = None,
        cli_type: str = "claude",
        freeze_count: Optional[int] = None,
    ) -> None:
        """冻结当前卡片 + 开新卡"""
        active = tracker.cards[-1]
        count = freeze_count if freeze_count is not None else MAX_CARD_BLOCKS
        reason = 'size' if freeze_count is not None else 'count'

        # 冻结当前卡片（只保留前 count 个 blocks，移除状态区和按钮）
        frozen_blocks = blocks[active.start_idx:active.start_idx + count]
        from .card_builder import build_stream_card
        frozen_card = build_stream_card(frozen_blocks, None, None, is_frozen=True)
        active.sequence += 1
        await self._card_service.update_card(active.card_id, active.sequence, frozen_card)
        active.frozen = True
        _safe_track_stats('card', 'freeze', session_name=tracker.session_name,
                     chat_id=tracker.chat_id)
        logger.info(
            f"[FREEZE] session={tracker.session_name} card_id={active.card_id} "
            f"blocks=[{active.start_idx}:{active.start_idx + count}] reason={reason}"
        )

        # 创建新卡片
        new_start = active.start_idx + count
        new_blocks = blocks[new_start:]
        if not new_blocks:
            return

        new_card_dict = build_stream_card(new_blocks, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name, cli_type=cli_type, user_config=_user_config)

        # 新卡大小检查：超限则从头部裁剪
        new_card_size = len(json.dumps(new_card_dict, ensure_ascii=False).encode('utf-8'))
        while new_card_size > CARD_SIZE_LIMIT and len(new_blocks) > 1:
            new_blocks = new_blocks[1:]
            new_start += 1
            new_card_dict = build_stream_card(new_blocks, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name, cli_type=cli_type, user_config=_user_config)
            new_card_size = len(json.dumps(new_card_dict, ensure_ascii=False).encode('utf-8'))

        new_card_id = await self._card_service.create_card(new_card_dict)
        if new_card_id:
            await self._card_service.send_card(tracker.chat_id, new_card_id)
            tracker.cards.append(CardSlice(
                card_id=new_card_id,
                start_idx=new_start,
                last_activity_time=time.time(),
            ))
            tracker.content_hash = self._compute_hash(new_blocks, status_line, bottom_bar, agent_panel, option_block)
            logger.info(
                f"[NEW after FREEZE] session={tracker.session_name} start_idx={new_start} "
                f"blocks={len(new_blocks)} card_id={new_card_id}"
            )
            tracker.last_notify_message_id = None

    def _update_ready_state(
        self, tracker: StreamTracker,
        blocks: list, status_line: Optional[dict], option_block: Optional[dict],
    ) -> bool:
        """更新就绪状态，返回是否需要发送就绪通知（不执行发送）"""
        current_ready = _is_ready(blocks, status_line, option_block)
        prev_ready = tracker.prev_is_ready
        tracker.prev_is_ready = current_ready
        return current_ready and not prev_ready and tracker.is_group and get_notify_ready_enabled()

    async def _send_ready_notification(
        self, tracker: StreamTracker, cli_type: str = "claude"
    ) -> None:
        """发送就绪通知（加急或新消息），应在卡片操作完成后调用"""
        count = increment_ready_notify_count()
        uid = tracker.notify_user_id or "all"
        cli_name = "Claude" if cli_type == CliType.CLAUDE else "Codex"
        logger.info(f"就绪提醒: chat_id={tracker.chat_id[:8]}..., count={count}, uid={uid}, "
                    f"last_msg={'有' if tracker.last_notify_message_id else '无'}")

        if tracker.last_notify_message_id and uid != "all" and get_notify_urgent_enabled():
            # 已有通知消息 + 加急开关开启 → 尝试加急
            try:
                ok = await self._card_service.send_urgent_app(
                    tracker.last_notify_message_id, [uid]
                )
                if ok:
                    # 加急成功 → 5 秒后自动取消
                    asyncio.create_task(self._cancel_urgent_later(
                        tracker.last_notify_message_id, [uid], delay=5
                    ))
                else:
                    # 加急失败（权限未开通等）→ 降级发新消息
                    label = ""
                    text = f'<at user_id="{uid}">{label}</at> {cli_name} 已就绪，等待您的输入...（这是第{count}次通知）'
                    msg_id = await self._card_service.send_text(tracker.chat_id, text)
                    if msg_id:
                        tracker.last_notify_message_id = msg_id
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"加急通知失败（网络错误）: {e}")
            except OSError as e:
                logger.warning(f"加急通知失败（系统错误）: {e}")
            except Exception as e:
                logger.warning(f"加急通知失败: {e}")
        else:
            # 首次通知（或无法加急时）→ 发新消息，记录 message_id
            label = "所有人" if uid == "all" else ""
            text = f'<at user_id="{uid}">{label}</at> {cli_name} 已就绪，等待您的输入...（这是第{count}次通知）'
            try:
                msg_id = await self._card_service.send_text(tracker.chat_id, text)
                if msg_id:
                    tracker.last_notify_message_id = msg_id
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"就绪提醒发送失败（网络错误）: {e}")
            except OSError as e:
                logger.warning(f"就绪提醒发送失败（系统错误）: {e}")
            except Exception as e:
                logger.warning(f"就绪提醒发送失败: {e}")

    async def _cancel_urgent_later(self, message_id: str, user_ids: list, delay: float = 15) -> None:
        """延迟取消加急通知"""
        await asyncio.sleep(delay)
        try:
            await self._card_service.cancel_urgent_app(message_id, user_ids)
        except (ConnectionError, TimeoutError) as e:
            logger.debug(f"取消加急失败（网络错误）: {e}")
        except OSError as e:
            logger.debug(f"取消加急失败（系统错误）: {e}")
        except Exception as e:
            logger.warning(f"取消加急失败: {e}")

    @staticmethod
    def _compute_hash(
        blocks: list, status_line: Optional[dict],
        bottom_bar: Optional[dict], agent_panel: Optional[dict] = None,
        option_block: Optional[dict] = None,
    ) -> str:
        """计算内容 hash（用于 diff）"""
        data = {
            "blocks": blocks,
            "status_line": status_line,
            "bottom_bar": bottom_bar,
            "agent_panel": agent_panel,
            "option_block": option_block,
        }
        return hashlib.md5(
            json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()


# ── 模块级辅助函数 ────────────────────────────────────────────────────────────

def _is_ready(blocks: list, status_line: Optional[dict], option_block: Optional[dict]) -> bool:
    """数据层就绪判断：无 streaming block、无 status_line（option_block 不影响就绪）"""
    has_streaming = any(b.get("is_streaming", False) for b in blocks)
    return not has_streaming and status_line is None
