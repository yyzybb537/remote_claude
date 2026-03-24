# build_dir_card 自定义命令按钮展示设计

## 概述

修改 `build_dir_card` 函数，在目录浏览卡片中展示用户配置的所有自定义命令启动按钮，采用混合布局（启动按钮横排 + 群聊按钮单独一行）。

## 动机

当前实现只显示第一个自定义命令的名称，且取的是 `command` 字段而非用户友好的 `name` 字段。用户希望能够：
1. 看到所有配置的自定义命令选项
2. 显示友好的命令名称（如 "Aider"）而非程序名（如 "aider"）

## 当前实现

**代码位置：** `lark_client/card_builder.py:1128-1299`（`build_dir_card` 函数）

**当前逻辑（第 1143-1148 行）：**
```python
# 获取实际命令名（优先从自定义命令配置获取）
claude_cmd_name = "Claude"
if user_config and user_config.ui_settings.custom_commands.is_visible():
    for cmd in user_config.ui_settings.custom_commands.commands:
        if cmd.name == "claude":
            claude_cmd_name = cmd.command.split()[0]  # 取程序名
            break
```

**当前布局：**
```
┌─────────────────────────────────────────────┐
│ 📁 **project-name**           [Claude] [群聊] │
└─────────────────────────────────────────────┘
```

## 新设计

### 布局变更

**混合布局：**
- 第一行：目录名称 + 所有启动按钮（横排）
- 第二行：群聊按钮

**示例（配置多个命令）：**
```
┌─────────────────────────────────────────────┐
│ 📁 **project-name**     [Claude][Codex][Aider] │
│                          [群聊]               │
└─────────────────────────────────────────────┘
```

**示例（未配置自定义命令）：**
```
┌─────────────────────────────────────────────┐
│ 📁 **project-name**              [Claude]   │
│                          [群聊]               │
└─────────────────────────────────────────────┘
```

### 数据结构

**获取命令列表逻辑：**
```python
def _get_launch_commands(user_config: Optional["UserConfig"]) -> List[Dict[str, str]]:
    """获取启动命令按钮列表

    Returns:
        [{"name": "Claude", "command": "claude"}, ...]
    """
    default_commands = [{"name": "Claude", "command": "claude"}]

    if not user_config or not user_config.ui_settings.custom_commands.is_visible():
        return default_commands

    commands = user_config.ui_settings.custom_commands.commands
    if not commands:
        return default_commands

    return [{"name": cmd.name, "command": cmd.command} for cmd in commands]
```

### 卡片结构变更

**原结构（单按钮）：**
```python
{
    "tag": "column",
    "width": "weighted",
    "weight": 2,
    "elements": [
        {"tag": "button", "text": "Claude", "type": "primary", ...},
        {"tag": "button", "text": "群聊", "type": "default", ...},
    ]
}
```

**新结构（多按钮）：**
```python
{
    "tag": "column",
    "width": "weighted",
    "weight": 2,
    "elements": [
        # 第一行：启动按钮（column_set 横排）
        {
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                {"tag": "column", "width": "auto", "elements": [
                    {"tag": "button", "text": "Claude", "type": "primary", ...}
                ]},
                {"tag": "column", "width": "auto", "elements": [
                    {"tag": "button", "text": "Codex", "type": "primary", ...}
                ]},
                # ... 更多命令按钮
            ]
        },
        # 第二行：群聊按钮
        {"tag": "button", "text": "群聊", "type": "default", ...},
    ]
}
```

### 按钮行为

每个启动按钮的 `behaviors` 需要传递：
- `action`: "dir_start"
- `path`: 目录完整路径
- `session_name`: 自动生成的会话名
- `cli_command`: 实际执行的命令（如 "claude"、"aider"）

**回调值示例：**
```python
{
    "action": "dir_start",
    "path": "/Users/dev/projects/myapp",
    "session_name": "myapp",
    "cli_command": "aider"  # 新增字段
}
```

## 后端修改

### lark_handler.py

`handle_dir_start` 函数需要新增 `cli_command` 参数支持：

```python
async def handle_dir_start(self, event, value: dict):
    path = value.get("path", "")
    session_name = value.get("session_name", "")
    cli_command = value.get("cli_command", "claude")  # 新增，默认 claude

    # 使用 cli_command 启动会话
    await self._start_session(session_name, path, cli_command)
```

### remote_claude.py

`cmd_start` 函数需要支持 `cli_command` 参数：

```python
def cmd_start(args):
    session_name = args.session_name
    working_dir = args.working_dir
    cli_command = getattr(args, 'cli_command', 'claude')  # 新增参数
    # ...
```

## 实现步骤

1. **card_builder.py**：修改 `build_dir_card` 函数
   - 新增 `_get_launch_commands` 辅助函数
   - 修改顶层目录渲染逻辑，生成多按钮布局
   - 为每个按钮添加 `cli_command` 回调值

2. **lark_handler.py**：修改 `handle_dir_start` 函数
   - 解析 `cli_command` 参数
   - 传递给会话启动逻辑

3. **remote_claude.py**：修改 `cmd_start` 函数（如需要）
   - 支持接收 `cli_command` 参数

## 边界情况

| 场景 | 行为 |
|------|------|
| 未配置自定义命令 | 显示默认 "Claude" 按钮 |
| 配置为空列表 | 显示默认 "Claude" 按钮 |
| 配置 1 个命令 | 显示该命令按钮 + 群聊按钮 |
| 配置多个命令 | 显示所有命令按钮（横排）+ 群聊按钮 |
| 命令名称过长 | 由飞书自动截断或换行 |
