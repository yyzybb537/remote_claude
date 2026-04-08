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

try:
    from stats import track as _track_stats
except Exception:
    def _track_stats(*args, **kwargs): pass


def _safe_track_stats(*args, **kwargs):
    try:
        _track_stats(*args, **kwargs)
    except Exception:
        pass

from utils.runtime_config import (
    get_bypass_enabled,
    get_notify_ready_enabled,
    get_notify_urgent_enabled,
    get_vague_commands_config,
    increment_ready_notify_count,
    load_settings,
)
from utils.session import ensure_user_data_dir, USER_DATA_DIR

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
    last_activity_time: float = field(default_factory=time.time)
    expired: bool = False


@dataclass(frozen=True)
class CardRenderContext:
    status_line: Optional[dict]
    bottom_bar: Optional[dict]
    agent_panel: Optional[dict] = None
    option_block: Optional[dict] = None
    cli_type: str = "claude"


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
    auto_answer_enabled: bool = False
    pending_auto_answer: Optional[Any] = None


# ── 轮询器 ────────────────────────────────────────────────────────────────────

class SharedMemoryPoller:
    """
    共享内存轮询器（流式滚动卡片模型）

    attach 时启动轮询 Task，detach/断线时停止。
    每秒读取 .mq 文件中的 blocks 流，通过 hash diff 触发飞书卡片创建/更新。
    """

    CARD_METADATA_LIMIT = 5

    def __init__(self, card_service: Any):
        self._card_service = card_service
        self._trackers: Dict[str, StreamTracker] = {}  # chat_id → StreamTracker
        self._tasks: Dict[str, asyncio.Task] = {}       # chat_id → Task
        self._kick_events: Dict[str, asyncio.Event] = {}  # chat_id → Event（唤醒轮询）
        self._rapid_until: Dict[str, float] = {}           # chat_id → 快速模式截止时间
        self._memory_log_counter = 0

    def _get_settings(self):
        return load_settings()

    def _prune_cards(self, tracker: StreamTracker) -> None:
        if len(tracker.cards) <= self.CARD_METADATA_LIMIT:
            return

        active_card = tracker.cards[-1] if tracker.cards else None
        frozen_cards = tracker.cards[:-1] if active_card else tracker.cards
        keep_frozen = max(0, self.CARD_METADATA_LIMIT - (1 if active_card else 0))
        tracker.cards = frozen_cards[-keep_frozen:] + ([active_card] if active_card else [])

    def get_memory_stats(self) -> dict:
        card_counts = [len(tracker.cards) for tracker in self._trackers.values()]
        return {
            "tracker_count": len(self._trackers),
            "total_card_count": sum(card_counts),
            "max_cards_per_tracker": max(card_counts, default=0),
            "task_count": len(self._tasks),
            "kick_event_count": len(self._kick_events),
            "rapid_mode_count": len(self._rapid_until),
        }

    def log_memory_stats(self) -> None:
        stats = self.get_memory_stats()
        logger.info(
            "[memory] tracker_count=%s total_card_count=%s max_cards_per_tracker=%s task_count=%s kick_event_count=%s rapid_mode_count=%s",
            stats["tracker_count"],
            stats["total_card_count"],
            stats["max_cards_per_tracker"],
            stats["task_count"],
            stats["kick_event_count"],
            stats["rapid_mode_count"],
        )

    def start(self, chat_id: str, session_name: str, is_group: bool = False,
              notify_user_id: Optional[str] = None) -> None:
        """attach 成功后调用：清空旧状态，启动轮询 Task"""
        self.stop(chat_id)

        tracker = StreamTracker(chat_id=chat_id, session_name=session_name, is_group=is_group,
                                notify_user_id=notify_user_id)
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
            except Exception:
                pass
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
            except Exception:
                pass

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
            except Exception as e:
                logger.warning(f"read_snapshot 失败: {e}")
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
                self._memory_log_counter += 1
                if self._memory_log_counter % 300 == 0:
                    self.log_memory_stats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"_poll_once 异常: {e}", exc_info=True)

    async def _poll_once(self, tracker: StreamTracker) -> None:
        """单次轮询：读取共享内存 → diff → 创建/更新卡片 → 就绪通知"""
        # 步骤 1：延迟初始化 Reader
        if tracker.reader is None:
            try:
                from shared_state import get_mq_path, SharedStateReader
                mq_path = get_mq_path(tracker.session_name)
                if not mq_path.exists():
                    return
                tracker.reader = SharedStateReader(tracker.session_name)
                logger.info(f"Reader 初始化成功: session={tracker.session_name}")
            except Exception as e:
                logger.warning(f"创建 Reader 失败: {e}")
                return

        # 读取共享内存
        try:
            state = tracker.reader.read()
        except Exception as e:
            logger.error(f"读取共享内存失败: {e}")
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
        context = CardRenderContext(
            status_line=status_line,
            bottom_bar=bottom_bar,
            agent_panel=agent_panel,
            option_block=option_block,
            cli_type=cli_type,
        )
        await self._do_card_update(tracker, blocks, context)

        # 步骤 4：通知在卡片操作之后发送，确保新卡先出现
        if should_notify:
            await self._send_ready_notification(tracker, cli_type)

    def _check_card_expiry(self, tracker: StreamTracker) -> None:
        """检查并标记过期卡片。"""
        from utils.runtime_config import get_card_expiry_enabled, get_card_expiry_seconds

        if not get_card_expiry_enabled():
            return

        expiry_seconds = get_card_expiry_seconds()
        now = time.time()

        for card_slice in tracker.cards:
            if card_slice.expired or card_slice.frozen:
                continue

            elapsed = now - card_slice.last_activity_time
            if elapsed > expiry_seconds:
                card_slice.expired = True
                logger.info(
                    f"卡片已过期: card_id={card_slice.card_id}, "
                    f"elapsed={elapsed:.0f}s, expiry={expiry_seconds}s"
                )

    async def _update_card_content(self, chat_id: str, tracker: StreamTracker,
                                    card_content: dict) -> bool:
        """更新卡片内容，处理过期/冻结逻辑。"""
        if not tracker.cards:
            return False

        active_slice = tracker.cards[-1]
        if active_slice.expired or active_slice.frozen:
            logger.info(f"卡片不可更新，需要创建新卡片: chat_id={chat_id[:8]}...")
            return False

        try:
            success = await self._card_service.update_card(
                card_id=active_slice.card_id,
                sequence=active_slice.sequence + 1,
                card_content=card_content,
            )
            if success:
                active_slice.sequence += 1
                active_slice.last_activity_time = time.time()
                return True
        except Exception as e:
            logger.warning(f"卡片更新失败: {e}")

        return False

    async def _do_card_update(
        self, tracker: StreamTracker, blocks: List[dict], context: CardRenderContext,
    ) -> None:
        """卡片操作主体：获取活跃卡片 → 创建/更新/拆分"""
        self._check_card_expiry(tracker)

        # 获取活跃卡片（最后一张且未冻结且未过期）
        active = None
        if tracker.cards:
            last_card = tracker.cards[-1]
            if not last_card.frozen and not last_card.expired:
                active = last_card

        if not blocks and not context.status_line and not context.bottom_bar and not context.agent_panel and not context.option_block and active is None:
            return  # 完全无内容且无活跃卡片时不创建卡片

        if active is None:
            # 需要创建新卡片
            await self._create_new_card(tracker, blocks, context)
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
            await self._freeze_and_split(tracker, blocks, context)
            return

        # hash diff
        new_hash = self._compute_hash(blocks_slice, context)
        if new_hash == tracker.content_hash:
            return  # 无变化

        # 更新卡片
        settings = self._get_settings()
        card_dict = self._build_card(tracker, blocks_slice, context, settings=settings)

        # 大小超限检查（与 blocks 数量超限同一套逻辑）
        card_size = len(json.dumps(card_dict, ensure_ascii=False).encode('utf-8'))
        if card_size > CARD_SIZE_LIMIT:
            freeze_count = self._find_freeze_count(blocks_slice, tracker.session_name)
            await self._freeze_and_split(
                tracker, blocks, context,
                freeze_count=freeze_count,
            )
            return

        proposed_sequence = active.sequence + 1
        success = await self._card_service.update_card(
            card_id=active.card_id,
            sequence=proposed_sequence,
            card_content=card_dict,
        )

        update_committed = False
        if getattr(success, 'is_element_limit', False):
            # 元素超限：冻结旧卡 + 推新流式卡
            await self._handle_element_limit(
                tracker, blocks, context,
            )
            return
        elif not success:
            # 降级：创建新卡片替代
            logger.warning(
                f"update_card 失败 card_id={active.card_id} seq={proposed_sequence}，降级为新卡片"
            )
            new_card_id = await self._card_service.create_card(card_dict)
            if new_card_id:
                await self._card_service.send_card(tracker.chat_id, new_card_id)
                active.card_id = new_card_id
                active.sequence = 0
                tracker.content_hash = new_hash
                _safe_track_stats('card', 'fallback', session_name=tracker.session_name,
                              chat_id=tracker.chat_id)
                update_committed = True
        else:
            active.sequence = proposed_sequence
            active.last_activity_time = time.time()
            _safe_track_stats('card', 'update', session_name=tracker.session_name,
                              chat_id=tracker.chat_id)
            tracker.content_hash = new_hash
            update_committed = True

        if update_committed:
            logger.debug(
                f"[UPDATE] session={tracker.session_name} blocks={len(blocks_slice)} "
                f"seq={active.sequence} hash={new_hash[:8]}"
            )

    async def _create_new_card(
        self, tracker: StreamTracker, blocks: List[dict], context: CardRenderContext,
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
        if not blocks_slice and not context.status_line and not context.bottom_bar and not context.agent_panel and not context.option_block:
            return

        blocks_slice, trimmed_count = _trim_card_head_by_size(
            blocks_slice,
            tracker.session_name,
            context.status_line,
            context.bottom_bar,
            agent_panel=context.agent_panel,
            option_block=context.option_block,
            cli_type=context.cli_type,
        )
        start_idx += trimmed_count

        card_dict = self._build_card(tracker, blocks_slice, context)

        card_id = await self._card_service.create_card(card_dict)

        if card_id:
            await self._card_service.send_card(tracker.chat_id, card_id)
            tracker.cards.append(CardSlice(card_id=card_id, start_idx=start_idx))
            self._prune_cards(tracker)
            tracker.content_hash = self._compute_hash(blocks_slice, context)
            _safe_track_stats('card', 'create', session_name=tracker.session_name,
                              chat_id=tracker.chat_id)
            logger.info(
                f"[NEW] session={tracker.session_name} start_idx={start_idx} "
                f"blocks={len(blocks_slice)} card_id={card_id}"
            )
        else:
            logger.warning(f"create_card 失败 session={tracker.session_name}")

    async def _handle_element_limit(
        self, tracker: StreamTracker, blocks: List[dict], context: CardRenderContext,
    ) -> None:
        """元素超限：冻结旧卡片 + 推送新流式卡片"""
        active = tracker.cards[-1]
        logger.warning(f"元素超限，冻结卡片 {active.card_id} 并推新卡")

        # 1. 冻结旧卡片（灰色 header，无状态区和按钮）
        blocks_slice = blocks[active.start_idx:]
        frozen_card = self._build_card(tracker, blocks_slice, context, is_frozen=True)
        proposed_sequence = active.sequence + 1
        update_ok = await self._card_service.update_card(active.card_id, proposed_sequence, frozen_card)
        if not update_ok:
            return

        active.sequence = proposed_sequence
        active.frozen = True
        _safe_track_stats('card', 'freeze', session_name=tracker.session_name,
                          chat_id=tracker.chat_id)

        # 2. 创建新流式卡片，从最近 INITIAL_WINDOW 个 blocks 开始（重置窗口）
        new_start = max(0, len(blocks) - INITIAL_WINDOW)
        new_blocks = blocks[new_start:]
        if not new_blocks and not context.status_line and not context.bottom_bar:
            return
        new_card_dict = self._build_card(tracker, new_blocks, context)
        new_card_id = await self._card_service.create_card(new_card_dict)
        if new_card_id:
            await self._card_service.send_card(tracker.chat_id, new_card_id)
            tracker.cards.append(CardSlice(card_id=new_card_id, start_idx=new_start))
            self._prune_cards(tracker)
            tracker.content_hash = self._compute_hash(new_blocks, context)
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
        self, tracker: StreamTracker, blocks: List[dict], context: CardRenderContext,
        freeze_count: Optional[int] = None,
    ) -> None:
        """冻结当前卡片 + 开新卡"""
        active = tracker.cards[-1]
        count = freeze_count if freeze_count is not None else MAX_CARD_BLOCKS
        reason = 'size' if freeze_count is not None else 'count'

        # 冻结当前卡片（只保留前 count 个 blocks，移除状态区和按钮）
        frozen_blocks = blocks[active.start_idx:active.start_idx + count]
        frozen_card = self._build_card(tracker, frozen_blocks, context, is_frozen=True)
        proposed_sequence = active.sequence + 1
        update_ok = await self._card_service.update_card(active.card_id, proposed_sequence, frozen_card)
        if not update_ok:
            return

        active.sequence = proposed_sequence
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

        new_blocks, trimmed_count = _trim_card_head_by_size(
            new_blocks,
            tracker.session_name,
            context.status_line,
            context.bottom_bar,
            agent_panel=context.agent_panel,
            option_block=context.option_block,
            cli_type=context.cli_type,
        )
        new_start += trimmed_count
        new_card_dict = self._build_card(tracker, new_blocks, context)

        new_card_id = await self._card_service.create_card(new_card_dict)
        if new_card_id:
            await self._card_service.send_card(tracker.chat_id, new_card_id)
            tracker.cards.append(CardSlice(card_id=new_card_id, start_idx=new_start))
            self._prune_cards(tracker)
            tracker.content_hash = self._compute_hash(new_blocks, context)
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
        return current_ready and not prev_ready and tracker.is_group and _notify_enabled

    async def _send_ready_notification(
        self, tracker: StreamTracker, cli_type: str = "claude"
    ) -> None:
        """发送就绪通知（加急或新消息），应在卡片操作完成后调用"""
        count = _increment_ready_count()
        uid = tracker.notify_user_id or "all"
        cli_name = "Claude" if cli_type == "claude" else "Codex"
        logger.info(f"就绪提醒: chat_id={tracker.chat_id[:8]}..., count={count}, uid={uid}, "
                    f"last_msg={'有' if tracker.last_notify_message_id else '无'}")

        if tracker.last_notify_message_id and uid != "all" and _urgent_enabled:
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
            except Exception as e:
                logger.warning(f"就绪提醒发送失败: {e}")

    async def _cancel_urgent_later(self, message_id: str, user_ids: list, delay: float = 15) -> None:
        """延迟取消加急通知"""
        await asyncio.sleep(delay)
        try:
            await self._card_service.cancel_urgent_app(message_id, user_ids)
        except Exception as e:
            logger.warning(f"延迟取消加急失败: {e}")

    def get_notify_enabled(self) -> bool:
        """获取就绪通知开关状态"""
        return _notify_enabled

    def set_notify_enabled(self, enabled: bool) -> None:
        """更新就绪通知开关状态并持久化"""
        global _notify_enabled
        _notify_enabled = enabled
        _save_notify_enabled(enabled)
        logger.info(f"就绪通知开关已{'开启' if enabled else '关闭'}")

    def get_urgent_enabled(self) -> bool:
        """获取加急通知开关状态"""
        return _urgent_enabled

    def set_urgent_enabled(self, enabled: bool) -> None:
        """更新加急通知开关状态并持久化"""
        global _urgent_enabled
        _urgent_enabled = enabled
        _save_urgent_enabled(enabled)
        logger.info(f"加急通知开关已{'开启' if enabled else '关闭'}")

    def get_bypass_enabled(self) -> bool:
        """获取新会话 bypass 开关状态"""
        return _bypass_enabled

    def set_bypass_enabled(self, enabled: bool) -> None:
        """更新新会话 bypass 开关状态并持久化"""
        global _bypass_enabled
        _bypass_enabled = enabled
        _save_bypass_enabled(enabled)
        logger.info(f"新会话 bypass 开关已{'开启' if enabled else '关闭'}")

    def cancel_auto_answer(self, session_name: str) -> None:
        for tracker in self._trackers.values():
            if tracker.session_name != session_name:
                continue
            pending = tracker.pending_auto_answer
            if pending:
                pending.cancel()
                tracker.pending_auto_answer = None

    def get_tracker(self, chat_id: str) -> Optional[StreamTracker]:
        return self._trackers.get(chat_id)

    def _build_card(
        self,
        tracker: StreamTracker,
        blocks: List[dict],
        context: CardRenderContext,
        *,
        is_frozen: bool = False,
        settings: Optional[dict] = None,
    ):
        from .card_builder import build_stream_card

        return build_stream_card(
            blocks,
            None if is_frozen else context.status_line,
            None if is_frozen else context.bottom_bar,
            is_frozen=is_frozen,
            agent_panel=None if is_frozen else context.agent_panel,
            option_block=None if is_frozen else context.option_block,
            session_name=tracker.session_name,
            cli_type=context.cli_type,
            settings=settings,
        )

    @staticmethod
    def _compute_hash(
        blocks: list, context: CardRenderContext,
    ) -> str:
        """计算内容 hash（用于 diff）"""
        data = {
            "blocks": blocks,
            "status_line": context.status_line,
            "bottom_bar": context.bottom_bar,
            "agent_panel": context.agent_panel,
            "option_block": context.option_block,
        }
        return hashlib.md5(
            json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()


# ── 模块级辅助函数 ────────────────────────────────────────────────────────────

def _is_ready(blocks: list, status_line: Optional[dict], option_block: Optional[dict]) -> bool:
    """数据层就绪判断：无 streaming block、无 status_line（option_block 不影响就绪）"""
    has_streaming = any(b.get("is_streaming", False) for b in blocks)
    return not has_streaming and status_line is None


_READY_COUNT_FILE = USER_DATA_DIR / "ready_notify_count"
_NOTIFY_ENABLED_FILE = USER_DATA_DIR / "ready_notify_enabled"
_URGENT_ENABLED_FILE = USER_DATA_DIR / "urgent_notify_enabled"
_BYPASS_ENABLED_FILE = USER_DATA_DIR / "bypass_enabled"


def _trim_card_head_by_size(
    blocks_slice: List[dict],
    session_name: str,
    status_line: Optional[dict],
    bottom_bar: Optional[dict],
    agent_panel: Optional[dict] = None,
    option_block: Optional[dict] = None,
    cli_type: str = "claude",
) -> tuple[List[dict], int]:
    """按大小限制裁剪头部，返回裁剪后的 blocks 与裁掉的数量"""
    if not blocks_slice:
        return blocks_slice, 0

    from .card_builder import build_stream_card

    lo, hi = 0, len(blocks_slice) - 1
    trim_count = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = blocks_slice[mid:]
        card = build_stream_card(
            candidate,
            status_line,
            bottom_bar,
            agent_panel=agent_panel,
            option_block=option_block,
            session_name=session_name,
            cli_type=cli_type,
        )
        size = len(json.dumps(card, ensure_ascii=False).encode('utf-8'))
        if size <= CARD_SIZE_LIMIT:
            trim_count = mid
            hi = mid - 1
        else:
            lo = mid + 1

    trimmed = blocks_slice[trim_count:]
    return trimmed or blocks_slice[-1:], trim_count


def _load_bool_flag(file_path: Path, default: bool) -> bool:
    """读取布尔开关文件，不存在或解析失败返回默认值"""
    try:
        return file_path.read_text().strip() == "1"
    except Exception:
        return default


def _save_bool_flag(file_path: Path, enabled: bool, label: str) -> None:
    """持久化布尔开关状态"""
    try:
        ensure_user_data_dir()
        file_path.write_text("1" if enabled else "0")
    except Exception as e:
        logger.warning(f"保存{label}开关失败: {e}")


def _load_notify_enabled() -> bool:
    """读取就绪通知开关状态，不存在或解析失败返回 True（默认开启）"""
    return _load_bool_flag(_NOTIFY_ENABLED_FILE, True)


def _save_notify_enabled(enabled: bool) -> None:
    """持久化就绪通知开关状态"""
    _save_bool_flag(_NOTIFY_ENABLED_FILE, enabled, "就绪通知")


def _load_urgent_enabled() -> bool:
    """读取加急通知开关状态，不存在或解析失败返回 False（默认关闭）"""
    return _load_bool_flag(_URGENT_ENABLED_FILE, False)


def _save_urgent_enabled(enabled: bool) -> None:
    """持久化加急通知开关状态"""
    _save_bool_flag(_URGENT_ENABLED_FILE, enabled, "加急通知")


def _load_bypass_enabled() -> bool:
    """读取新会话 bypass 开关状态，不存在或解析失败返回 False（默认关闭）"""
    return _load_bool_flag(_BYPASS_ENABLED_FILE, False)


def _save_bypass_enabled(enabled: bool) -> None:
    """持久化新会话 bypass 开关状态"""
    _save_bool_flag(_BYPASS_ENABLED_FILE, enabled, "新会话 bypass")


# 模块级开关状态：启动时加载一次
_notify_enabled: bool = _load_notify_enabled()
_urgent_enabled: bool = _load_urgent_enabled()
_bypass_enabled: bool = _load_bypass_enabled()


def _increment_ready_count() -> int:
    """原子递增全局就绪提醒计数器，返回新值（持久化到文件）"""
    try:
        ensure_user_data_dir()
        try:
            count = int(_READY_COUNT_FILE.read_text().strip())
        except Exception:
            count = 0
        count += 1
        _READY_COUNT_FILE.write_text(str(count))
        return count
    except Exception as e:
        logger.warning(f"_increment_ready_count 失败: {e}")
        return 1


def _get_vague_keywords() -> set[str]:
    try:
        patterns, _ = get_vague_commands_config()
        return {str(p).strip().lower() for p in patterns if str(p).strip()}
    except Exception:
        return {'继续', '好的', '是', '确认', '明白', '可以', '行', '对', 'continue', 'yes', 'ok', 'proceed', 'go ahead', 'sure', 'confirm', 'alright', 'fine'}


def analyze_option_block(option_block: Optional[dict]) -> tuple[str, str]:
    options = (option_block or {}).get('options') or []
    selected_value = str((option_block or {}).get('selected_value') or '').strip()
    if selected_value:
        for option in options:
            value = str(option.get('value', '')).strip()
            if value == selected_value:
                return ('select', value)

    for option in options:
        label = str(option.get('label', '')).strip()
        value = str(option.get('value', '')).strip()
        lowered = label.lower()
        if 'recommended' in lowered or '推荐' in label:
            return ('select', value or '1')

    vague_keywords = _get_vague_keywords()
    for option in options:
        label = str(option.get('label', '')).strip()
        normalized = label.lower().strip()
        if normalized in vague_keywords:
            return ('input', '继续')
        if any(keyword in normalized for keyword in vague_keywords if ' ' in keyword or len(keyword) > 2):
            return ('input', '继续')
        if label in vague_keywords:
            return ('input', '继续')

    if options:
        first = options[0]
        first_label = str(first.get('label', '')).strip()
        first_value = str(first.get('value', '')).strip()
        if any(token in first_label.lower() for token in ('继续', 'yes', 'ok', 'proceed', 'sure', 'confirm')):
            return ('input', '继续')
        return ('select', first_value or '1')

    return ('input', '继续')
