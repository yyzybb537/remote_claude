"""
飞书卡片服务 - 支持创建和实时更新卡片
"""

import json
import logging
import time
import uuid
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

import lark_oapi as lark

logger = logging.getLogger('CardService')
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
)
from lark_oapi.api.cardkit.v1 import (
    CreateCardRequest, CreateCardRequestBody,
    UpdateCardRequest, UpdateCardRequestBody, Card
)

from . import config

import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
try:
    from stats import track as _track_stats
except Exception:
    def _track_stats(*args, **kwargs): pass


@dataclass
class CardState:
    """卡片状态"""
    card_id: str
    message_id: Optional[str] = None
    sequence: int = 0
    last_update: float = field(default_factory=time.time)


class CardService:
    """飞书卡片服务"""

    def __init__(self):
        self.client: Optional[lark.Client] = None
        self._init_client()
        # chat_id -> CardState
        self._active_cards: Dict[str, CardState] = {}
        # message_id -> CardState（反查，用于按钮点击就地更新）
        self._cards_by_message_id: Dict[str, CardState] = {}

    def _init_client(self):
        """初始化飞书客户端"""
        if config.FEISHU_APP_ID and config.FEISHU_APP_SECRET:
            self.client = lark.Client.builder() \
                .app_id(config.FEISHU_APP_ID) \
                .app_secret(config.FEISHU_APP_SECRET) \
                .build()

    async def create_card(self, card_content: Dict[str, Any]) -> Optional[str]:
        """创建卡片实体，返回 card_id（失败自动重试 1 次）"""
        if not self.client:
            print("[CardService] 客户端未初始化")
            return None

        import asyncio

        for attempt in range(2):
            try:
                request = CreateCardRequest.builder() \
                    .request_body(
                        CreateCardRequestBody.builder()
                        .type("card_json")
                        .data(json.dumps(card_content, ensure_ascii=False))
                        .build()
                    ) \
                    .build()

                response = await asyncio.to_thread(
                    self.client.cardkit.v1.card.create, request
                )

                if response.success():
                    card_id = getattr(getattr(response, "data", None), "card_id", None)
                    return card_id
                else:
                    logger.warning(f"创建卡片失败(attempt={attempt+1}): code={response.code} msg={response.msg}")
            except Exception as e:
                logger.error(f"创建卡片异常(attempt={attempt+1}): {e}")

            if attempt == 0:
                await asyncio.sleep(1)

        _track_stats('error', 'card_api', detail='create_card')
        return None

    async def send_card(self, chat_id: str, card_id: str) -> Optional[str]:
        """发送卡片消息，返回 message_id"""
        if not self.client:
            return None

        try:
            import asyncio

            card_content = {
                "type": "card",
                "data": {"card_id": card_id}
            }

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("interactive")
                    .content(json.dumps(card_content))
                    .build()
                ) \
                .build()

            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )

            if response.success():
                message_id = getattr(getattr(response, "data", None), "message_id", None)
                return message_id
            else:
                logger.warning(f"发送卡片失败: code={response.code} msg={response.msg}")
                return None
        except Exception as e:
            logger.error(f"发送卡片异常: {e}")
            return None

    async def create_and_send_card(
        self, chat_id: str, card_content: Dict[str, Any]
    ) -> Optional[str]:
        """创建卡片并发送，内部维护 message_id 反查索引，返回 message_id"""
        card_id = await self.create_card(card_content)
        if not card_id:
            return None
        message_id = await self.send_card(chat_id, card_id)
        if message_id:
            state = CardState(card_id=card_id, message_id=message_id)
            self._cards_by_message_id[message_id] = state
            logger.info(f"已记录卡片: msg={message_id}, card={card_id}")
        return message_id

    async def update_card_by_message_id(
        self, message_id: str, card_content: Dict[str, Any]
    ) -> bool:
        """按 message_id 就地更新卡片内容（通过 card_id 反查使用 CardKit update）"""
        state = self._cards_by_message_id.get(message_id)
        if not state:
            logger.warning(f"未找到 message_id 对应的卡片状态: {message_id}")
            return False
        state.sequence += 1
        return await self.update_card(state.card_id, state.sequence, card_content)

    async def update_card(self, card_id: str, sequence: int, card_content: Dict[str, Any]) -> bool:
        """更新卡片内容（失败自动重试 1 次）"""
        if not self.client:
            return False

        import asyncio

        for attempt in range(2):
            try:
                update_uuid = f"{int(time.time() * 1000)}-{uuid.uuid4()}"

                request = UpdateCardRequest.builder() \
                    .card_id(card_id) \
                    .request_body(
                        UpdateCardRequestBody.builder()
                        .uuid(update_uuid)
                        .sequence(sequence)
                        .card(
                            Card.builder()
                            .type("card_json")
                            .data(json.dumps(card_content, ensure_ascii=False))
                            .build()
                        )
                        .build()
                    ) \
                    .build()

                response = await asyncio.to_thread(
                    self.client.cardkit.v1.card.update, request
                )

                if response.success():
                    return True
                else:
                    logger.warning(f"更新卡片失败(attempt={attempt+1}): card_id={card_id} seq={sequence} code={response.code} msg={response.msg}")
            except Exception as e:
                logger.error(f"更新卡片异常(attempt={attempt+1}): card_id={card_id} seq={sequence} error={e}")

            if attempt == 0:
                await asyncio.sleep(1)

        _track_stats('error', 'card_api', detail='update_card')
        return False

    async def send_text(self, chat_id: str, text: str):
        """发送纯文本消息（备用）"""
        if not self.client:
            print(f"[Lark] 消息: {text}")
            return

        try:
            import asyncio

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()
                ) \
                .build()

            response = await asyncio.to_thread(
                self.client.im.v1.message.create, request
            )

            if not response.success():
                logger.warning(f"发送文本失败: code={response.code} msg={response.msg}")
        except Exception as e:
            logger.error(f"发送文本异常: {e}")

    # 管理活跃卡片的方法
    def get_active_card(self, chat_id: str) -> Optional[CardState]:
        """获取聊天的活跃卡片"""
        return self._active_cards.get(chat_id)

    def set_active_card(self, chat_id: str, card_state: CardState):
        """设置聊天的活跃卡片"""
        self._active_cards[chat_id] = card_state

    def clear_active_card(self, chat_id: str):
        """清除聊天的活跃卡片"""
        if chat_id in self._active_cards:
            del self._active_cards[chat_id]


# 全局实例
card_service = CardService()
