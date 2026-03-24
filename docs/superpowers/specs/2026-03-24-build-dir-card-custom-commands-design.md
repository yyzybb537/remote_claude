# build_dir_card 自定义命令按钮展示设计

## 概述

修改 `build_dir_card` 函数，在目录浏览卡片中展示用户配置的所有匹配当前 `cli_type` 的自定义命令启动按钮，采用混合布局（启动按钮横排 + 群聊按钮单独一行）。

## 动机

当前实现只显示第一个自定义命令的名称，且取的是 `command` 字段而非用户友好的 `name` 字段。用户希望能够：
1. 看到所有配置的匹配当前 cli_type 的自定义命令选项
2. 显示友好的命令名称（如 "Aider"）而非程序名（如 "aider"）
3. 通过 cli_type 字段匹配命令类型，支持多个命令使用同一 cli_type

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

**当前回调处理（main.py 第 257-262 行）：**
```python
# 目录卡片：在该目录创建新 Claude 会话
if action_type == "dir_start":
    path = action_value.get("path", "")
    session_name = action_value.get("session_name", "")
    print(f"[Lark] dir_start: path={path}, session={session_name}")
    asyncio.create_task(handler._cmd_start(user_id, chat_id, f"{session_name} {path}"))
    return None
```

## 新设计

### 1. 新增 CliType 枚举（`server/cli_type.py`）

```python
from enum import StrEnum

class CliType(StrEnum):
    """CLI 类型枚举"""
    CLAUDE = "claude"
    CODEX = "codex"
```

**用途：**
- 替换代码中所有硬编码的 `"claude"` / `"codex"` 字符串
- 用于 CustomCommand.cli_type 字段验证
- 用于 build_dir_card 参数类型约束

### 2. 修改 CustomCommand 数据类（`utils/runtime_config.py`）

```python
@dataclass
class CustomCommand:
    """自定义 CLI 命令配置"""
    name: str           # 显示名称，如 "Claude"、"Aider"
    cli_type: str       # CLI 类型（必须为 CliType 枚举值之一）
    command: str        # 实际执行的命令，如 "claude"、"aider --message-args"
    description: str = ""  # 可选描述

    def __post_init__(self):
        """验证命令格式"""
        if not self.name:
            raise ValueError("命令名称不能为空")
        if not self.command:
            raise ValueError("命令值不能为空")
        if not self.cli_type:
            raise ValueError("CLI 类型不能为空")
        # 校验 cli_type 为有效枚举值
        try:
            CliType(self.cli_type)
        except ValueError:
            raise ValueError(f"CLI 类型必须是 {list(CliType)} 之一: {self.cli_type}")
        if len(self.name) > 20:
            raise ValueError(f"命令名称最大长度 20 字符: {self.name}")
```

**配置文件示例（`config.json`）：**
```json
{
  "custom_commands": {
    "enabled": true,
    "commands": [
      {"name": "Claude", "cli_type": "claude", "command": "claude", "description": "Claude Code CLI"},
      {"name": "Aider", "cli_type": "claude", "command": "aider --model claude-sonnet-4", "description": "AI Pair Programming"},
      {"name": "Codex", "cli_type": "codex", "command": "codex", "description": "OpenAI Codex CLI"}
    ]
  }
}
```

### 3. 修改 build_dir_card 函数

**函数签名变更:**
```python
def build_dir_card(
    target,
    entries: List[Dict],
    _: List[Dict],
    tree: bool = False,
    session_groups: Optional[Dict[str, str]] = None,
    page: int = 0,
    user_config: Optional["UserConfig"] = None,
    cli_type: str = "claude",  # 新增：CLI 类型参数
) -> Dict[str, Any]:
```

**获取匹配命令列表:**
```python
def _get_matching_commands(user_config: Optional["UserConfig"], cli_type: str) -> List[Dict[str, str]]:
    """获取匹配指定 cli_type 的自定义命令列表

    Args:
        user_config: 用户配置对象
        cli_type: CLI 类型

    Returns:
        匹配的命令列表，每个元素包含 name 和 command
    """
    if not user_config or not user_config.ui_settings.custom_commands.is_visible():
        # 未启用自定义命令，返回默认命令
        return [{"name": "Claude", "command": "claude"}]

    commands = user_config.ui_settings.custom_commands.commands
    # 过滤匹配 cli_type 的命令
    matched = [
        {"name": cmd.name, "command": cmd.command}
        for cmd in commands
        if cmd.cli_type == cli_type
    ]

    # 未匹配时返回空列表（调用方决定是否展示默认按钮）
    return matched
```

**按钮布局:**
- 第一个按钮使用 `primary` 类型
- 其余按钮使用 `default` 类型
- 所有按钮横排展示在同一行
- 群聊按钮单独一行显示

**回调值变更:**
```python
{
    "action": "dir_start",
    "path": "/Users/dev/projects/myapp",
    "session_name": "myapp",
    "cli_command": "aider"  # 新增字段：实际执行的命令
}
```

### 4. 修改回调处理

**main.py handle_card_action:**
```python
# 目录卡片：在该目录创建新 Claude 会话
if action_type == "dir_start":
    path = action_value.get("path", "")
    session_name = action_value.get("session_name", "")
    cli_command = action_value.get("cli_command", "claude")  # 新增
    print(f"[Lark] dir_start: path={path}, session={session_name}, cli_command={cli_command}")
    asyncio.create_task(handler._cmd_start_with_cli_command(user_id, chat_id, f"{session_name} {path}", cli_command))
    return None
```

**lark_handler.py _cmd_start:**
```python
async def _cmd_start(self, user_id: str, chat_id: str, args: str, cli_command: str = "claude"):  # 新增参数
    """启动新会话"""
    parts = args.strip().split(maxsplit=1)
    # ... 解析参数 ...
    session_name = parts[0]
    work_dir = parts[1] if len(parts) > 1 else None
    cli_command = parts[2] if len(parts) > 2 else cli_command  # 新增参数
    # ... 启动会话逻辑 ...
```

**_start_server_session 调用修改:**
```python
async def _start_server_session(
    self,
    session_name: str,
    work_dir: str,
    chat_id: str,
    cli_command: str = "claude",  # 新增参数
) -> bool:
```

### 5. 边界情况

| 场景 | 行为 |
|------|------|
| `custom_commands.enabled=false` | 展示默认 "Claude" 按钮 |
| 配置为空列表 | 展示默认 "Claude" 按钮 |
| 配置多个命令（同一 cli_type） | 展示所有匹配命令按钮（横排）+ 群聊按钮 |
| 配置多个命令（不同 cli_type） | 只展示匹配当前 cli_type 的命令按钮 |
| cli_type 无匹配 | 隐藏启动按钮区域 |
| 按钮名称过长 | 由飞书自动截断或换行 |

