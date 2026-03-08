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

# ── 常量 ──────────────────────────────────────────────────────────────────────
INITIAL_WINDOW = 30    # 首次 attach 最多显示最近 30 个 blocks
MAX_CARD_BLOCKS = 50   # 单张卡片最多 50 个 blocks → 超限冻结
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


@dataclass
class StreamTracker:
    """单个 chat_id 的流式跟踪状态"""
    chat_id: str
    session_name: str
    cards: List[CardSlice] = field(default_factory=list)
    content_hash: str = ""
    reader: Optional[Any] = None  # SharedStateReader，延迟初始化


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

    def start(self, chat_id: str, session_name: str) -> None:
        """attach 成功后调用：清空旧状态，启动轮询 Task"""
        self.stop(chat_id)

        tracker = StreamTracker(chat_id=chat_id, session_name=session_name)
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

    def _on_task_done(self, task: asyncio.Task, chat_id: str) -> None:
        """Task 完成回调：记录异常"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"轮询 Task 异常: chat_id={chat_id[:8]}..., {exc}", exc_info=exc)

    def kick(self, chat_id: str) -> None:
        """触发立即轮询并进入快速轮询模式"""
        self._rapid_until[chat_id] = time.time() + RAPID_DURATION
        ev = self._kick_events.get(chat_id)
        if ev:
            ev.set()

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
            except Exception as e:
                logger.error(f"_poll_once 异常: {e}", exc_info=True)

    async def _poll_once(self, tracker: StreamTracker) -> None:
        """单次轮询：读取共享内存 → diff → 创建/更新卡片"""
        # 延迟初始化 Reader
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

        # 获取活跃卡片（最后一张且未冻结）
        active = None
        if tracker.cards and not tracker.cards[-1].frozen:
            active = tracker.cards[-1]

        if not blocks and not status_line and not bottom_bar and not agent_panel and not option_block and active is None:
            return  # 完全无内容且无活跃卡片时不创建卡片

        if active is None:
            # 需要创建新卡片
            await self._create_new_card(tracker, blocks, status_line, bottom_bar, agent_panel, option_block)
        else:
            # 有活跃卡片，检查是否需要更新
            blocks_slice = blocks[active.start_idx:]

            # 超限检查
            if len(blocks_slice) > MAX_CARD_BLOCKS:
                await self._freeze_and_split(tracker, blocks, status_line, bottom_bar, agent_panel, option_block)
                return

            # hash diff
            new_hash = self._compute_hash(blocks_slice, status_line, bottom_bar, agent_panel, option_block)
            if new_hash == tracker.content_hash:
                return  # 无变化

            # 更新卡片
            from .card_builder import build_stream_card
            card_dict = build_stream_card(blocks_slice, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name)

            active.sequence += 1
            success = await self._card_service.update_card(
                card_id=active.card_id,
                sequence=active.sequence,
                card_content=card_dict,
            )

            if not success:
                # 降级：创建新卡片替代
                logger.warning(
                    f"update_card 失败 card_id={active.card_id} seq={active.sequence}，降级为新卡片"
                )
                _track_stats('card', 'fallback', session_name=tracker.session_name,
                             chat_id=tracker.chat_id)
                new_card_id = await self._card_service.create_card(card_dict)
                if new_card_id:
                    await self._card_service.send_card(tracker.chat_id, new_card_id)
                    active.card_id = new_card_id
                    active.sequence = 0
            else:
                _track_stats('card', 'update', session_name=tracker.session_name,
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
    ) -> None:
        """创建新卡片（首次 attach 或冻结后）"""
        if not tracker.cards:
            # 首次 attach：取最近 INITIAL_WINDOW 个 blocks
            start_idx = max(0, len(blocks) - INITIAL_WINDOW)
        else:
            # 冻结后：从上张冻结卡片的结束位置开始
            last_frozen = tracker.cards[-1]
            start_idx = last_frozen.start_idx + MAX_CARD_BLOCKS

        blocks_slice = blocks[start_idx:]
        if not blocks_slice and not status_line and not bottom_bar and not agent_panel and not option_block:
            return

        from .card_builder import build_stream_card
        card_dict = build_stream_card(blocks_slice, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name)
        card_id = await self._card_service.create_card(card_dict)

        if card_id:
            await self._card_service.send_card(tracker.chat_id, card_id)
            tracker.cards.append(CardSlice(card_id=card_id, start_idx=start_idx))
            tracker.content_hash = self._compute_hash(blocks_slice, status_line, bottom_bar, agent_panel, option_block)
            _track_stats('card', 'create', session_name=tracker.session_name,
                         chat_id=tracker.chat_id)
            logger.info(
                f"[NEW] session={tracker.session_name} start_idx={start_idx} "
                f"blocks={len(blocks_slice)} card_id={card_id}"
            )
        else:
            logger.warning(f"create_card 失败 session={tracker.session_name}")

    async def _freeze_and_split(
        self, tracker: StreamTracker, blocks: List[dict],
        status_line: Optional[dict], bottom_bar: Optional[dict],
        agent_panel: Optional[dict] = None,
        option_block: Optional[dict] = None,
    ) -> None:
        """冻结当前卡片 + 开新卡"""
        active = tracker.cards[-1]

        # 冻结当前卡片（只保留前 MAX_CARD_BLOCKS 个 blocks，移除状态区和按钮）
        frozen_blocks = blocks[active.start_idx:active.start_idx + MAX_CARD_BLOCKS]
        from .card_builder import build_stream_card
        frozen_card = build_stream_card(frozen_blocks, None, None, is_frozen=True)
        active.sequence += 1
        await self._card_service.update_card(active.card_id, active.sequence, frozen_card)
        active.frozen = True
        _track_stats('card', 'freeze', session_name=tracker.session_name,
                     chat_id=tracker.chat_id)
        logger.info(
            f"[FREEZE] session={tracker.session_name} card_id={active.card_id} "
            f"blocks=[{active.start_idx}:{active.start_idx + MAX_CARD_BLOCKS}]"
        )

        # 创建新卡片
        new_start = active.start_idx + MAX_CARD_BLOCKS
        new_blocks = blocks[new_start:]
        if not new_blocks:
            return

        new_card_dict = build_stream_card(new_blocks, status_line, bottom_bar, agent_panel=agent_panel, option_block=option_block, session_name=tracker.session_name)
        new_card_id = await self._card_service.create_card(new_card_dict)
        if new_card_id:
            await self._card_service.send_card(tracker.chat_id, new_card_id)
            tracker.cards.append(CardSlice(card_id=new_card_id, start_idx=new_start))
            tracker.content_hash = self._compute_hash(new_blocks, status_line, bottom_bar, agent_panel, option_block)
            logger.info(
                f"[NEW after FREEZE] session={tracker.session_name} start_idx={new_start} "
                f"blocks={len(new_blocks)} card_id={new_card_id}"
            )

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
