# Contract: 飞书卡片交互 API

**Feature**: `20260319-cmd-ux-enhancements`
**Date**: 2026-03-19
**Version**: 1.0

## 概述

本文档定义飞书卡片交互操作的 API 接口，包括卡片就地更新和回车自动提交功能。

---

## 1. 卡片就地更新 API

### `update_card`

**描述**: 就地更新现有飞书卡片内容，不推送新卡片。

**使用场景**: 按钮点击、文本提交、选项选择等交互操作。

#### 函数签名

```python
def update_card(
    card_id: str,
    card_content: dict,
    *,
    update_scope: str = "all"  # "all" | "partial"
) -> bool:
    """
    就地更新飞书卡片

    Args:
        card_id: 卡片唯一标识
        card_content: 新的卡片内容（完整 JSON 结构）
        update_scope: 更新范围（all=完整更新，partial=增量更新）

    Returns:
        bool: 更新是否成功

    Raises:
        CardNotFoundError: 卡片不存在或已删除
        CardUpdateError: 更新失败（网络问题、权限问题等）
    """
```

#### 调用示例

```python
# 1. 构建 loading 状态卡片
loading_card = {
    "config": {"wide_screen_mode": True},
    "elements": [
        {"tag": "markdown", "content": "处理中..."},
        {"tag": "action", "actions": [
            {"tag": "button", "text": "确认", "disabled": True}
        ]}
    ]
}

# 2. 就地更新
success = card_service.update_card(card_id, loading_card)

# 3. 处理结果
if not success:
    # 降级为发送新卡片
    card_service.send_card(chat_id, loading_card)
```

#### 飞书 API 映射

```python
# 飞书开放平台 API
POST /open-apis/im/v1/messages/:message_id/cards

# 请求体
{
    "config": {"wide_screen_mode": true},
    "elements": [...]
}
```

---

## 2. 交互状态管理 API

### `build_card_with_loading_state`

**描述**: 构建带 loading 状态的卡片，用于交互过程中的视觉反馈。

#### 函数签名

```python
def build_card_with_loading_state(
    base_card: dict,
    *,
    is_loading: bool = False,
    disabled_buttons: list[str] | None = None,
    loading_text: str = "处理中..."
) -> dict:
    """
    构建带 loading 状态的卡片

    Args:
        base_card: 基础卡片内容
        is_loading: 是否处于 loading 状态
        disabled_buttons: 需要禁用的按钮 ID 列表（["all"] 表示全部）
        loading_text: loading 提示文本

    Returns:
        dict: 构建后的卡片内容
    """
```

#### 状态流转

```
[正常状态] → 用户点击按钮 → [loading 状态]
    ↓                              ↓
    ↓                        执行操作
    ↓                              ↓
    ← ← ← ← ← ← ← ← ← ← ← ← [结果状态]
```

---

## 3. 回车自动提交 API

### `handle_text_input_submit`

**描述**: 处理文本输入框的回车提交事件。

#### 函数签名

```python
async def handle_text_input_submit(
    chat_id: str,
    card_id: str,
    element_id: str,
    input_value: str,
    action_value: str
) -> None:
    """
    处理文本输入框回车提交

    Args:
        chat_id: 飞书会话 ID
        card_id: 卡片 ID
        element_id: 输入框元素 ID
        input_value: 用户输入的文本
        action_value: 按钮关联的动作值（JSON 字符串）
    """
```

#### 飞书回调事件格式

```json
{
    "action": {
        "tag": "input",
        "element_id": "message_input",
        "value": "用户输入的文本"
    },
    "open_message_id": "om_xxx",
    "open_chat_id": "oc_xxx"
}
```

---

## 4. 文本输入框构建 API

### `build_text_input`

**描述**: 构建支持回车自动提交的文本输入框。

#### 函数签名

```python
def build_text_input(
    element_id: str,
    *,
    placeholder: str = "",
    is_multiline: bool = False,
    max_length: int = 500,
    submit_action: str | None = None
) -> dict:
    """
    构建文本输入框元素

    Args:
        element_id: 元素唯一标识
        placeholder: 占位提示文本
        is_multiline: 是否多行输入（多行时回车换行，不提交）
        max_length: 最大输入长度
        submit_action: 提交动作值（JSON 字符串）

    Returns:
        dict: 飞书卡片元素 JSON
    """
```

#### 使用示例

```python
# 单行输入框（回车提交）
single_line = build_text_input(
    element_id="message_input",
    placeholder="输入消息...",
    is_multiline=False,
    submit_action='{"action": "send_message"}'
)
# 输出：带 enter_key_action 的 input 元素

# 多行输入框（回车换行）
multi_line = build_text_input(
    element_id="description_input",
    placeholder="输入详细描述...",
    is_multiline=True,
    max_length=1000
)
# 输出：textarea 元素（无 enter_key_action）
```

---

## 5. 错误处理

### 错误类型

| 错误类型 | 描述 | 处理策略 |
|----------|------|----------|
| `CardNotFoundError` | 卡片不存在或已删除 | 发送新卡片 |
| `CardUpdateError` | 卡片更新失败（网络/权限） | 发送新卡片 + 记录警告 |
| `EmptyInputError` | 空输入提交 | 忽略，不处理 |
| `InvalidActionError` | 无效的动作值 | 记录错误，显示提示 |

### 错误处理示例

```python
try:
    success = card_service.update_card(card_id, new_card)
    if not success:
        raise CardUpdateError("更新返回失败")
except CardNotFoundError:
    logger.warning(f"卡片不存在: {card_id}，发送新卡片")
    card_service.send_card(chat_id, new_card)
except CardUpdateError as e:
    logger.warning(f"卡片更新失败: {e}，发送新卡片")
    card_service.send_card(chat_id, new_card)
```

---

## 6. 防抖机制

### 快速连续交互处理

```python
import asyncio
from functools import wraps

def debounce(seconds: float = 0.5):
    """防抖装饰器，防止快速连续交互"""
    def decorator(func):
        last_call = 0

        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal last_call
            now = asyncio.get_event_loop().time()
            if now - last_call < seconds:
                logger.debug(f"防抖跳过: {func.__name__}")
                return
            last_call = now
            return await func(*args, **kwargs)
        return wrapper
    return decorator

@debounce(0.5)
async def handle_button_click(card_id: str, action_value: str):
    """按钮点击处理（500ms 防抖）"""
    ...
```

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-03-19 | 初始版本，定义卡片就地更新和回车自动提交 API |
