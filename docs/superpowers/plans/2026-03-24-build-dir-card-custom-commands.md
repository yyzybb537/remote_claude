# build_dir_card 自定义命令按钮展示实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) | superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修改 build_dir_card 函数，在目录浏览卡片中展示用户配置的所有匹配当前 cli_type 的自定义命令启动按钮，采用混合布局（启动按钮横排 + 群聊按钮单独一行)。

**Architecture:**
1. 新增 CliType 枚举替换硬编码字符串
2. 修改 CustomCommand 数据类增加 cli_type 字段
3. 修改 build_dir_card 函数新增 cli_type 参数和过滤展示
4. 修改回调处理传递 cli_command 参数
5. 更新配置模板增加 cli_type 字段示例

**Tech Stack:** Python 3.x, StrEnum, dataclasses, 飞书卡片 JSON V2

---

## 文件修改清单

### 新增文件
- `server/cli_type.py` - CliType 枚举定义

### 修改文件
- `utils/runtime_config.py` - CustomCommand 数据类修改
- `lark_client/card_builder.py` - build_dir_card 函数修改
- `lark_client/main.py` - dir_start 回调处理修改
- `lark_client/lark_handler.py` - _cmd_start 和 _start_server_session 函数修改
- `resources/defaults/config.default.json` - 配置模板更新
- `CLAUDE.md` - 文档更新

- `tests/test_custom_commands.py` - 测试文件更新

---

## 任务列表

### Task 1: 新增 CliType 枚举定义

**Files:**
- Create: `server/cli_type.py`
- Test: `tests/test_cli_type.py` (新建)

- [ ] **Step 1: Write失败测试**

```python
def test_cli_type_enum_values():
    """测试 CliType 枚举值是否正确"""
    from server.cli_type import CliType

    assert CliType.CLAUDE == "claude"
    assert CliType.CODEX == "codex"
    assert len(CliType) == 2


def test_cli_type_string_conversion():
    """测试枚举与字符串转换"""
    assert str(CliType.CLAUDE) == "claude"
    assert CliType("claude") == CliType.CLAUDE
    assert CliType("codex") == CliType.CODEX
```

```

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run python tests/test_cli_type.py
# 预期: 测试通过（尚未实现）
```

- [ ] **Step 3: 实现枚举定义**

```python
from enum import StrEnum

class CliType(StrEnum):
    """CLI 类型枚举"""
    CLAUDE = "claude"
    CODEX = "codex"
```

```

- [ ] **Step 4: 运行测试验证通过**

```bash
uv run python tests/test_cli_type.py
# 预期: 测试通过
```

- [ ] **Step 5: 提交**

```bash
git add server/cli_type.py tests/test_cli_type.py
git commit -m "feat: add CliType enum for CLI type identification"
```

---

### Task 2: 修改 CustomCommand 数据类

**Files:**
- Modify: `utils/runtime_config.py`
- Test: `tests/test_custom_commands.py`

- [ ] **Step 1: 写失败测试**

```python
def test_custom_command_requires_cli_type():
    """测试 CustomCommand 必须验证 cli_type 字段"""
    from utils.runtime_config import CustomCommand
    from server.cli_type import CliType
    import pytest

    # 正常情况
    cmd = CustomCommand(name="Claude", cli_type="claude", command="claude")
    assert cmd.cli_type == "claude"

    # 缺少 cli_type
    with pytest.raises(ValueError, match="CLI 类型"):
        CustomCommand(name="Test", cli_type="", command="test")

    # 无效 cli_type
    with pytest.raises(ValueError, match="CLI 类型必须是"):
        CustomCommand(name="Test", cli_type="invalid", command="test")

    # 验证枚举值
    with pytest.raises(ValueError, match="CLI 类型必须是"):
        CustomCommand(name="Test", cli_type="other_cli", command="test")
```
```

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run python tests/test_custom_commands.py
# 预期: 测试失败（CustomCommand 需要 cli_type 字段）
```

- [ ] **Step 3: 修改数据类定义**

在 `utils/runtime_config.py` 中修改 `CustomCommand` 类：

```python
@dataclass
class CustomCommand:
    """自定义 CLI 命令配置"""
    name: str           # 显示名称，如 "Claude"、"Aider"
    cli_type: str       # CLI 类型（必须为 CliType 枚举值之一)
    command: str        # 实际执行的命令，如 "claude"、"aider --message-args"
    description: str = ""  # 可选描述

```

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

同时在文件顶部添加导入:

```python
from server.cli_type import CliType
```

- [ ] **Step 4: 更新 from_dict 方法**

修改 `CustomCommand.from_dict` 方法，确保从字典创建时正确处理 cli_type 字段

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "CustomCommand":
    return cls(
        name=data.get("name", ""),
        cli_type=data.get("cli_type", ""),
        command=data.get("command", ""),
        description=data.get("description", ""),
    )
```

- [ ] **Step 5: 运行测试验证通过**

```bash
uv run python tests/test_custom_commands.py
# 预期: 测试通过
```

- [ ] **Step 6: 提交**

```bash
git add utils/runtime_config.py server/cli_type.py tests/test_custom_commands.py
git commit -m "feat: add cli_type field to CustomCommand data class"
```

---

### Task 3: 修改 build_dir_card 函数
**Files:**
- Modify: `lark_client/card_builder.py`
- Test: `tests/test_custom_commands.py`

- [ ] **Step 1: 写失败测试**

```python
def test_get_matching_commands():
    """测试 _get_matching_commands 辅助函数"""
    from lark_client.card_builder import _get_matching_commands

    # 未启用自定义命令
    user_config = None
    cli_type = "claude"
    result = _get_matching_commands(user_config, cli_type)
    assert result == [{"name": "Claude", "command": "claude"}]

    # 启用但空列表
    user_config = Mock()
    user_config.ui_settings.custom_commands.enabled = True
    user_config.ui_settings.custom_commands.commands = []
    result = _get_matching_commands(user_config, "claude")
    assert result == [{"name": "Claude", "command": "claude"}]

    # 匹配单个命令
    user_config = Mock()
    user_config.ui_settings.custom_commands.enabled = True
    user_config.ui_settings.custom_commands.commands = [
        CustomCommand(name="Claude", cli_type="claude", command="claude")
    ]
    result = _get_matching_commands(user_config, "claude")
    assert result == [{"name": "Claude", "command": "claude"}]

    # 匹配多个命令（同一 cli_type）
    user_config = Mock()
    user_config.ui_settings.custom_commands.enabled = True
    user_config.ui_settings.custom_commands.commands = [
        CustomCommand(name="Claude", cli_type="claude", command="claude"),
        CustomCommand(name="Aider", cli_type="claude", command="aider --model claude-sonnet-4"),
    ]
    result = _get_matching_commands(user_config, "claude")
    assert len(result) == 2
    assert result[0]["name"] == "Claude"
    assert result[1]["name"] == "Aider"

    # 无匹配命令
    user_config = Mock()
    user_config.ui_settings.custom_commands.enabled = True
    user_config.ui_settings.custom_commands.commands = [
        CustomCommand(name="Codex", cli_type="codex", command="codex")
    ]
    result = _get_matching_commands(user_config, "claude")
    assert result == []
```
```

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run python tests/test_custom_commands.py
# 预期: 测试失败（需要实现 _get_matching_commands)
```
- [ ] **Step 3: 实现 _get_matching_commands 辅助函数**

在 `lark_client/card_builder.py` 中新增辅助函数

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

    return matched
```

- [ ] **Step 4: 修改 build_dir_card 函数签名**

添加 `cli_type` 参数：
```python
def build_dir_card(
    target,
    entries: List[Dict],
    _: List[Dict],
    tree: bool = False,
    session_groups: Optional[Dict[str, str]] = None,
    page: int = 0,
    user_config: Optional["UserConfig"] = None,
    cli_type: str = "claude",  # 新增参数
) -> Dict[str, Any]:
```

- [ ] **Step 5: 修改按钮构建逻辑**

找到 `build_dir_card` 函数中顶层目录渲染部分（约第 1191-1253 行），修改为：
```python
# 获取匹配的命令列表
matched_commands = _get_matching_commands(user_config, cli_type)

# 如果 matched_commands:
    # 构建启动按钮（横排）
    launch_buttons = []
    for i, cmd in enumerate(matched_commands):
        btn_type = "primary" if i == 0 else "default"
        launch_buttons.append({
            "tag": "column",
            "width": "auto",
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": cmd["name"]},
                "type": btn_type,
                "behaviors": [{
                    "type": "callback",
                    "value": {
                        "action": "dir_start",
                        "path": full_path,
                        "session_name": auto_session,
                        "cli_command": cmd["command"],  # 新增字段
                    }
                }]
            }]
        })

    # 构建按钮行（第一行：启动按钮，第二行：群聊按钮）
    if launch_buttons:
        right_column_elements = [
            {
                "tag": "column_set",
                "flex_mode": "none",
                "columns": launch_buttons,
            },
            group_btn,  # 群聊按钮（保持原逻辑）
        ]
    else:
        # 无匹配命令，隐藏启动按钮
        right_column_elements = [group_btn]
```

- [ ] **Step 6: 运行测试验证通过**

```bash
uv run python tests/test_custom_commands.py
# 预期: 测试通过
```
- [ ] **Step 7: 提交**

```bash
git add lark_client/card_builder.py tests/test_custom_commands.py
git commit -m "feat: add cli_type filtering to build_dir_card"
```
---

### Task 4: 修改回调处理
**Files:**
- Modify: `lark_client/main.py`
- Modify: `lark_client/lark_handler.py`
- Test: `tests/test_custom_commands.py`

- [ ] **Step 1: 写失败测试**

```python
def test_dir_start_callback_with_cli_command():
    """测试 dir_start 回调处理 cli_command 参数"""
    # 模拟回调值
    value = {
        "action": "dir_start",
        "path": "/path/to/project",
        "session_name": "myproject",
        "cli_command": "aider --model claude-sonnet-4",
    }
    # 验证回调值包含 cli_command
    assert value.get("cli_command") == "aider --model claude-sonnet-4"
```

```

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run python tests/test_custom_commands.py
# 预期: 测试失败
```
- [ ] **Step 3: 修改 main.py 回调处理**

找到 `handle_card_action` 函数中的 `dir_start` 分支，添加 `cli_command` 参数处理
```python
# 目录卡片：在该目录创建新 Claude 会话
if action_type == "dir_start":
    path = action_value.get("path", "")
    session_name = action_value.get("session_name", "")
    cli_command = action_value.get("cli_command", "claude")  # 新增
    print(f"[Lark] dir_start: path={path}, session={session_name}, cli_command={cli_command}")
    # 调用新的处理函数
    asyncio.create_task(handler._cmd_start_with_cli_command(user_id, chat_id, f"{session_name} {path}", cli_command))
    return None
```

- [ ] **Step 4: 修改 lark_handler.py 处理函数**

新增 `_cmd_start_with_cli_command` 方法或修改 `_cmd_start` 和 `_start_server_session` 方法签名
```python
async def _cmd_start_with_cli_command(self, user_id: str, chat_id: str, args: str, cli_command: str = "claude"):
    """启动新会话（带 cli_command 参数）"""
    parts = args.strip().split(maxsplit=1)
    if not parts:
        await card_service.send_text(chat_id, "用法: /start <会话名> [工作路径]")
        return

    session_name = parts[0]
    work_dir = parts[1] if len(parts) > 1 else None

    # ... 复用 _cmd_start 的其余逻辑 ...
    await self._start_server_session(session_name, work_dir, chat_id, cli_command)
```

修改 `_start_server_session` 方法签名
```python
async def _start_server_session(self, session_name: str, work_dir: str, chat_id: str, cli_command: str = "claude") -> bool:
```

- [ ] **Step 5: 运行测试验证通过**

```bash
uv run python tests/test_custom_commands.py
# 预期: 测试通过
```
- [ ] **Step 6: 提交**

```bash
git add lark_client/main.py lark_client/lark_handler.py tests/test_custom_commands.py
git commit -m "feat: add cli_command parameter to dir_start callback"
```
---

### Task 5: 更新配置模板
**Files:**
- Modify: `resources/defaults/config.default.json`

- [ ] **Step 1: 更新配置模板**

在 `config.default.json` 中为 custom_commands 的commands 示例添加 `cli_type` 字段
```json
{
  "custom_commands": {
    "enabled": false,
    "commands": [
      {"name": "Claude", "cli_type": "claude", "command": "claude", "description": "Claude Code CLI"},
      {"name": "Codex", "cli_type": "codex", "command": "codex", "description": "OpenAI Codex CLI"}
    ]
  }
}
```

- [ ] **Step 2: 提交**

```bash
git add resources/defaults/config.default.json
git commit -m"docs: update config template with cli_type field"
```
---

### Task 6: 更新文档
**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新 CustomCommand 文档**

在 `CLAUDE.md` 中更新 CustomCommand 数据类说明，添加 `cli_type` 字段描述

```markdown
**CustomCommand 数据类**：
- `name`: 显示名称
- `cli_type`: CLI 类型（必须为 CliType 枚举值之一）
- `command`: 实际执行的命令
- `description`: 可选描述
```

- [ ] **Step 2: 更新 build_dir_card 文档**

更新 `build_dir_card` 函数说明，添加 `cli_type` 参数和按钮展示逻辑
```markdown
**build_dir_card 函数**：
- 新增 `cli_type` 参数
- 根据 cli_type 过滤展示匹配的自定义命令按钮
- 未匹配时隐藏启动按钮
```

- [ ] **Step 3: 提交**

```bash
git add CLAUDE.md
git commit -m"docs: update CustomCommand and build_dir_card documentation"
```
---

### Task 7: 更新现有测试
**Files:**
- Modify: `tests/test_custom_commands.py`

- [ ] **Step 1: 更新现有测试用例**

检查 `tests/test_custom_commands.py` 中所有创建 CustomCommand 的测试用例，确保添加 `cli_type` 字段

- [ ] **Step 2: 运行测试验证**

```bash
uv run python tests/test_custom_commands.py
# 预期: 所有测试通过
```
- [ ] **Step 3: 提交**

```bash
git add tests/test_custom_commands.py
git commit -m"test: update test cases for cli_type field"
```
---

### Task 8: 全局替换硬编码字符串
**Files:**
- 修改: `server/server.py`
- 修改: `utils/runtime_config.py`
- 修改: `lark_client/card_builder.py`
- 修改: `lark_client/shared_memory_poller.py`
- 修改: `utils/session.py`
- 修改: `tests/test_card_interaction.py`
- 修改: `tests/test_stream_poller.py`

- [ ] **Step 1: 扫描所有硬编码位置**

```bash
grep -rn '"claude"' '"codex"' --include="*.py" server/ utils/ lark_client/ tests/
# 查找所有需要替换的位置
```

- [ ] **Step 2: 替换为枚举引用**

将所有硬编码的 `"claude"` / `"codex"` 替换为 `CliType.CLAUDE`/`CliType.CODEX`
- 参数默认值使用 `cli_type="claude"` 替换为 `cli_type=CliType.CLAUDE`
- 返回值使用 `return "claude"` 替换为 `return CliType.CLAUDE`

- [ ] **Step 3: 运行所有测试**

```bash
uv run python tests/test_custom_commands.py
uv run python tests/test_card_interaction.py
uv run python tests/test_stream_poller.py
# 预期: 所有测试通过
```
- [ ] **Step 4: 提交**

```bash
git add server/server.py utils/runtime_config.py lark_client/card_builder.py lark_client/shared_memory_poller.py utils/session.py tests/
git commit -m"refactor: replace hardcoded cli_type strings with CliType enum"
```
---

## 验收标准
- [ ] 所有测试通过
- [ ] 配置文件模板包含 cli_type 字段示例
- [ ] build_dir_card 正确过滤和展示自定义命令按钮
- [ ] 回调处理正确传递 cli_command 参数
- [ ] 文档更新完整
