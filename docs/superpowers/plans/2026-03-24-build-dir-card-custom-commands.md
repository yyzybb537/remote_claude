# build_dir_card 自定义命令多按钮展示实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在目录浏览卡片中展示用户配置的所有自定义命令启动按钮，支持多 CLI 启动。

**Architecture:** 修改 `build_dir_card` 函数，将单个启动按钮改为多按钮横排布局，每个按钮携带 `cli_command` 参数。后端 `lark_handler.py` 解析并使用对应命令启动会话。

**Tech Stack:** Python, 飞书卡片 JSON V2, dataclasses

---

## 文件结构

| 文件 | 职责 | 修改类型 |
|------|------|---------|
| `lark_client/card_builder.py` | 卡片构建，新增 `_get_launch_commands` 辅助函数，修改 `build_dir_card` | 修改 |
| `lark_client/lark_handler.py` | 消息处理，修改 `_start_server_session` 支持 `cli_command` 参数 | 修改 |
| `lark_client/main.py` | 回调处理，解析 `cli_command` 并传递 | 修改 |
| `tests/test_custom_commands.py` | 新增卡片构建测试 | 修改 |

---

### Task 1: 新增 `_get_launch_commands` 辅助函数

**Files:**
- Modify: `lark_client/card_builder.py:1142-1148`

- [ ] **Step 1: 在 `build_dir_card` 函数之前添加辅助函数**

在 `_dir_session_name` 函数（第 1120 行）之后，`build_dir_card` 函数（第 1128 行）之前添加：

```python
def _get_launch_commands(user_config: Optional["UserConfig"]) -> List[Dict[str, str]]:
    """获取启动命令按钮列表

    Args:
        user_config: 用户配置对象

    Returns:
        命令列表，每项包含 {"name": str, "command": str}
        默认返回 [{"name": "Claude", "command": "claude"}]
    """
    default_commands = [{"name": "Claude", "command": "claude"}]

    if not user_config or not user_config.ui_settings.custom_commands.is_visible():
        return default_commands

    commands = user_config.ui_settings.custom_commands.commands
    if not commands:
        return default_commands

    return [{"name": cmd.name, "command": cmd.command} for cmd in commands]
```

- [ ] **Step 2: 验证语法正确**

Run: `python3 -c "import ast; ast.parse(open('lark_client/card_builder.py').read())"`
Expected: 无输出（语法正确）

- [ ] **Step 3: Commit**

```bash
git add lark_client/card_builder.py
git commit -m "feat(card_builder): 新增 _get_launch_commands 辅助函数

获取用户配置的自定义命令列表，用于目录浏览卡片多按钮展示

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: 修改 `build_dir_card` 函数，生成多按钮布局

**Files:**
- Modify: `lark_client/card_builder.py:1142-1253`

- [ ] **Step 1: 删除旧的 `claude_cmd_name` 逻辑**

删除第 1142-1148 行的旧代码：
```python
    # 获取实际命令名（优先从自定义命令配置获取）
    claude_cmd_name = "Claude"
    if user_config and user_config.ui_settings.custom_commands.is_visible():
        for cmd in user_config.ui_settings.custom_commands.commands:
            if cmd.name == "claude":
                claude_cmd_name = cmd.command.split()[0]  # 取命令名第一部分
                break
```

替换为：
```python
    # 获取启动命令列表
    launch_commands = _get_launch_commands(user_config)
```

- [ ] **Step 2: 修改顶层目录渲染逻辑，生成多按钮布局**

将第 1233-1249 行的右列按钮代码：
```python
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": claude_cmd_name},
                                "type": "primary",
                                "behaviors": [{"type": "callback", "value": {
                                    "action": "dir_start",
                                    "path": full_path,
                                    "session_name": auto_session
                                }}]
                            },
                            group_btn
                        ]
                    }
```

替换为：
```python
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [
                            # 第一行：启动按钮横排
                            {
                                "tag": "column_set",
                                "flex_mode": "none",
                                "columns": [
                                    {
                                        "tag": "column",
                                        "width": "auto",
                                        "elements": [{
                                            "tag": "button",
                                            "text": {"tag": "plain_text", "content": cmd["name"]},
                                            "type": "primary",
                                            "behaviors": [{
                                                "type": "callback",
                                                "value": {
                                                    "action": "dir_start",
                                                    "path": full_path,
                                                    "session_name": auto_session,
                                                    "cli_command": cmd["command"],
                                                }
                                            }]
                                        }]
                                    }
                                    for cmd in launch_commands
                                ]
                            },
                            # 第二行：群聊按钮
                            group_btn
                        ]
                    }
```

- [ ] **Step 3: 验证语法正确**

Run: `python3 -c "import ast; ast.parse(open('lark_client/card_builder.py').read())"`
Expected: 无输出（语法正确）

- [ ] **Step 4: Commit**

```bash
git add lark_client/card_builder.py
git commit -m "feat(card_builder): build_dir_card 支持多启动按钮

- 使用 _get_launch_commands 获取命令列表
- 混合布局：启动按钮横排 + 群聊按钮单独一行
- 每个按钮携带 cli_command 参数

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: 修改 `lark_client/main.py` 解析 `cli_command` 参数

**Files:**
- Modify: `lark_client/main.py:257-261`

- [ ] **Step 1: 修改 `dir_start` 回调处理，提取 `cli_command`**

将第 257-261 行：
```python
        if action_type == "dir_start":
            path = action_value.get("path", "")
            session_name = action_value.get("session_name", "")
            print(f"[Lark] dir_start: path={path}, session={session_name}")
            asyncio.create_task(handler._cmd_start(user_id, chat_id, f"{session_name} {path}"))
            return None
```

替换为：
```python
        if action_type == "dir_start":
            path = action_value.get("path", "")
            session_name = action_value.get("session_name", "")
            cli_command = action_value.get("cli_command", "claude")
            print(f"[Lark] dir_start: path={path}, session={session_name}, cli_command={cli_command}")
            asyncio.create_task(handler._cmd_start_with_cli(
                user_id, chat_id, session_name, path, cli_command
            ))
            return None
```

- [ ] **Step 2: 验证语法正确**

Run: `python3 -c "import ast; ast.parse(open('lark_client/main.py').read())"`
Expected: 无输出（语法正确）

- [ ] **Step 3: Commit**

```bash
git add lark_client/main.py
git commit -m "feat(main): dir_start 回调支持 cli_command 参数

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: 修改 `lark_handler.py` 支持自定义 CLI 命令启动

**Files:**
- Modify: `lark_client/lark_handler.py`

- [ ] **Step 1: 修改 `_start_server_session` 函数签名，新增 `cli_command` 参数**

将第 316-336 行的函数签名和命令构建部分：
```python
    async def _start_server_session(
        self,
        session_name: str,
        work_dir: Optional[str],
        chat_id: str,
    ) -> bool:
        """启动 server 进程并等待 socket 就绪

        Args:
            session_name: 会话名称
            work_dir: 工作目录（可选）
            chat_id: 飞书聊天 ID（用于错误通知）

        Returns:
            bool: True 表示启动成功，False 表示失败
        """
        script_dir = Path(__file__).parent.parent.absolute()
        server_script = script_dir / "server" / "server.py"
        cmd = ["uv", "run", "--project", str(script_dir), "python3", str(server_script), session_name]
        if get_bypass_enabled():
            cmd += ["--", "--dangerously-skip-permissions", "--permission-mode=dontAsk"]
```

替换为：
```python
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
            cli_command: CLI 命令（默认 "claude"）

        Returns:
            bool: True 表示启动成功，False 表示失败
        """
        script_dir = Path(__file__).parent.parent.absolute()
        server_script = script_dir / "server" / "server.py"
        cmd = [
            "uv", "run", "--project", str(script_dir), "python3",
            str(server_script), session_name,
            "--cli-command", cli_command,
        ]
        if get_bypass_enabled():
            cmd += ["--", "--dangerously-skip-permissions", "--permission-mode=dontAsk"]
```

- [ ] **Step 2: 新增 `_cmd_start_with_cli` 方法**

在 `_cmd_start` 方法之后（约第 437 行），添加新方法：

```python
    async def _cmd_start_with_cli(
        self, user_id: str, chat_id: str,
        session_name: str, work_dir: str, cli_command: str
    ):
        """使用指定 CLI 命令启动新会话（目录浏览卡片入口）"""
        if session_name in self._starting_sessions:
            await card_service.send_text(chat_id, f"会话 '{session_name}' 正在启动中，请稍候")
            return
        self._starting_sessions.add(session_name)

        try:
            if not await self._start_server_session(
                session_name, work_dir, chat_id, cli_command
            ):
                return

            ok = await self._attach(chat_id, session_name, user_id=user_id)
            if ok:
                self._chat_bindings[chat_id] = session_name
                self._save_chat_bindings()
            else:
                await card_service.send_text(
                    chat_id,
                    f"会话已启动但连接失败\n使用 /attach {session_name} 重试"
                )
        finally:
            self._starting_sessions.discard(session_name)
```

- [ ] **Step 3: 更新 `_cmd_start_and_new_group` 方法**

将第 455 行：
```python
            if not await self._start_server_session(session_name, work_dir, chat_id):
```

替换为：
```python
            if not await self._start_server_session(session_name, work_dir, chat_id, "claude"):
```

- [ ] **Step 4: 验证语法正确**

Run: `python3 -c "import ast; ast.parse(open('lark_client/lark_handler.py').read())"`
Expected: 无输出（语法正确）

- [ ] **Step 5: Commit**

```bash
git add lark_client/lark_handler.py
git commit -m "feat(lark_handler): 支持自定义 CLI 命令启动会话

- _start_server_session 新增 cli_command 参数
- 新增 _cmd_start_with_cli 方法供目录浏览卡片调用

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: 修改 `server/server.py` 支持 `--cli-command` 参数

**Files:**
- Modify: `server/server.py`

- [ ] **Step 1: 查看当前参数解析位置**

Run: `grep -n "argparse\|ArgumentParser" server/server.py | head -20`

- [ ] **Step 2: 添加 `--cli-command` 参数并传递给 PTY 启动命令**

根据实际代码结构，在参数解析部分添加 `--cli-command` 参数，默认值为 `claude`。在启动 PTY 子进程时，使用该参数作为 CLI 命令。

（具体代码位置需根据 Step 1 结果确定）

- [ ] **Step 3: Commit**

```bash
git add server/server.py
git commit -m "feat(server): 支持 --cli-command 参数指定 CLI 命令

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: 新增单元测试

**Files:**
- Modify: `tests/test_custom_commands.py`

- [ ] **Step 1: 添加 `_get_launch_commands` 测试类**

在文件末尾 `if __name__ == "__main__":` 之前添加：

```python
# 需要在 import 部分添加：
# import sys
# from pathlib import Path
# sys.path.insert(0, str(Path(__file__).parent.parent))
# from lark_client.card_builder import _get_launch_commands


class TestGetLaunchCommands:
    """测试 _get_launch_commands 辅助函数"""

    def test_default_without_config(self):
        """测试无配置时返回默认值"""
        result = _get_launch_commands(None)
        assert result == [{"name": "Claude", "command": "claude"}]

    def test_default_with_disabled_config(self):
        """测试配置未启用时返回默认值"""
        config = UserConfig()
        config.ui_settings.custom_commands.enabled = False
        config.ui_settings.custom_commands.commands = [
            CustomCommand("Codex", "codex")
        ]
        result = _get_launch_commands(config)
        assert result == [{"name": "Claude", "command": "claude"}]

    def test_custom_commands(self):
        """测试自定义命令列表"""
        config = UserConfig()
        config.ui_settings.custom_commands.enabled = True
        config.ui_settings.custom_commands.commands = [
            CustomCommand("Claude", "/opt/claude", "Custom Claude"),
            CustomCommand("Codex", "/opt/codex", "Custom Codex"),
        ]
        result = _get_launch_commands(config)
        assert len(result) == 2
        assert result[0] == {"name": "Claude", "command": "/opt/claude"}
        assert result[1] == {"name": "Codex", "command": "/opt/codex"}

    def test_empty_commands_returns_default(self):
        """测试空命令列表返回默认值"""
        config = UserConfig()
        config.ui_settings.custom_commands.enabled = True
        config.ui_settings.custom_commands.commands = []
        result = _get_launch_commands(config)
        assert result == [{"name": "Claude", "command": "claude"}]
```

- [ ] **Step 2: 在 import 部分添加必要的导入**

在文件开头 import 部分添加：
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from lark_client.card_builder import _get_launch_commands
```

- [ ] **Step 3: 运行测试验证**

Run: `uv run python3 tests/test_custom_commands.py -v`
Expected: 所有测试通过

- [ ] **Step 4: Commit**

```bash
git add tests/test_custom_commands.py
git commit -m "test: 新增 _get_launch_commands 单元测试

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: 集成测试验证

**Files:**
- Manual test

- [ ] **Step 1: 启动飞书客户端**

Run: `uv run python3 remote_claude.py lark restart`

- [ ] **Step 2: 在飞书中测试 `/ls` 命令**

在飞书中发送 `/ls`，观察目录浏览卡片是否显示多个启动按钮。

- [ ] **Step 3: 验证按钮点击行为**

点击不同按钮，确认会话使用正确的 CLI 命令启动。

- [ ] **Step 4: 检查日志**

Run: `tail -f ~/.remote-claude/lark_client.log`
Expected: 日志中显示正确的 `cli_command` 值

---

## 边界情况检查清单

| 场景 | 预期行为 | 验证方法 |
|------|---------|---------|
| 未配置自定义命令 | 显示单个 "Claude" 按钮 | 测试覆盖 |
| 配置为空列表 | 显示单个 "Claude" 按钮 | 测试覆盖 |
| 配置 1 个命令 | 显示该命令按钮 + 群聊按钮 | 手动验证 |
| 配置多个命令 | 显示所有命令按钮横排 + 群聊按钮 | 手动验证 |
| 按钮回调值 | 包含正确的 `cli_command` 字段 | 日志验证 |
