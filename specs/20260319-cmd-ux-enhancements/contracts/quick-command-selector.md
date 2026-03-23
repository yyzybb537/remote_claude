# Quick Command Selector Contract

**Feature**: `20260319-cmd-ux-enhancements`
**Version**: 1.0
**Date**: 2026-03-19

## Overview

本合约定义飞书快捷命令选择器的 UI 组件和事件处理接口。

---

## UI Component

### Component: `QuickCommandSelector`

快捷命令下拉选择器组件。

**Type**: 飞书卡片 `select_static` 元素

**Location**: 流式卡片底部菜单区域（第四层）

**Visibility**: 仅在以下条件全部满足时显示：
1. `ui_settings.quick_commands.enabled = true`
2. `ui_settings.quick_commands.commands` 非空
3. 会话已连接（`disconnected = false`）

### Card Element Schema

```json
{
  "tag": "action",
  "actions": [{
    "tag": "select_static",
    "placeholder": {
      "tag": "plain_text",
      "content": "快捷命令"
    },
    "options": [
      {
        "text": {"tag": "plain_text", "content": "🗑️ 清空对话"},
        "value": "/clear"
      },
      {
        "text": {"tag": "plain_text", "content": "📦 压缩上下文"},
        "value": "/consume"
      }
    ]
  }]
}
```

### Option Format

每个选项格式为：`{icon} {label}`

| 字段 | 来源 | 示例 | 说明 |
|------|------|------|------|
| `icon` | `QuickCommand.icon` | `🗑️` | 可空，空时使用空白占位 emoji |
| `label` | `QuickCommand.label` | `清空对话` | 显示名称 |
| `value` | `QuickCommand.value` | `/clear` | 命令值 |

---

## Event Contract

### Event: `quick_command_select`

用户选择快捷命令时触发。

**Event Type**: 卡片回调事件

**Callback Value**: 命令字符串（如 `/clear`）

### Handler: `handle_quick_command()`

处理快捷命令选择事件。

**Signature**:
```python
async def handle_quick_command(
    self,
    chat_id: str,
    command: str,
    user_id: str
) -> None:
    """处理快捷命令选择事件

    Args:
        chat_id: 聊天 ID
        command: 命令字符串（如 "/clear"）
        user_id: 用户 ID
    """
```

**Behavior**:
1. 验证会话连接状态
2. 复用现有 `_handle_command()` 逻辑发送命令
3. 更新卡片状态

### Error Handling

| 错误场景 | 处理方式 |
|---------|---------|
| 会话未连接 | 提示用户重新连接，不发送命令 |
| 命令无效 | 正常发送，由 CLI 返回错误信息 |
| 发送失败 | 输出错误日志，提示用户重试 |

---

## Configuration Contract

### Default Commands

当用户未配置 `commands` 时，使用以下默认值作为参考：

```json
[
  {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
  {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
  {"label": "退出会话", "value": "/exit", "icon": "🚪"},
  {"label": "帮助", "value": "/help", "icon": "❓"}
]
```

**注意**: 默认列表仅作为配置参考，实际使用需用户手动配置。

### Command Validation

| 规则 | 说明 |
|------|------|
| 必须以 `/` 开头 | 确保是有效命令 |
| 不能包含空格 | 不支持参数化命令 |
| 最大长度 32 字符 | 限制命令长度（2026-03-19 澄清：调整为 32 字符） |
| `icon` 可空 | 空时使用空白占位 emoji（2026-03-19 澄清） |
| `commands` 最多 20 条 | 超限时静默截断（2026-03-19 澄清） |

---

## Implementation Notes

### card_builder.py Integration

在 `build_stream_card()` 函数中：

```python
def build_stream_card(
    blocks,
    status_line,
    bottom_bar,
    is_frozen,
    agent_panel,
    option_block,
    session_name,
    disconnected,
    runtime_config=None  # 新增参数
):
    # ... 现有逻辑 ...

    # 第四层：菜单区
    menu_elements = []

    # 快捷命令选择器（仅连接时显示）
    if not disconnected and runtime_config:
        quick_commands = runtime_config.get_quick_commands()
        if quick_commands:
            menu_elements.append(_build_quick_command_selector(quick_commands))

    # ... 其他菜单按钮 ...
```

### lark_handler.py Integration

在 `LarkHandler` 类中：

```python
async def handle_card_callback(self, event: dict):
    """处理卡片回调事件"""
    action = event.get("action", {})
    value = action.get("value", "")

    # 检测是否为快捷命令
    if value.startswith("/"):
        await self.handle_quick_command(
            chat_id=event["open_chat_id"],
            command=value,
            user_id=event["operator"].get("open_id", "")
        )
```
