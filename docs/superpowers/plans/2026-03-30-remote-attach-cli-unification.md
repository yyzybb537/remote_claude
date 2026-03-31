# 连接稳定性修复与日志分流轮转 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 server/client/bin/remote_claude.py 中的连接、参数、路径、异常与保活问题，并引入统一日志初始化模块，将客户端/服务端/lark 主日志收敛到 `/tmp/remote-claude/` 下并启用 `10MB × 5` 轮转，同时保留现有会话级调试日志。

**Architecture:** 先用测试锁定现有缺陷和目标行为，再最小化调整 CLI 参数校验、客户端断线原因透传、服务端/WebSocket 边界异常处理。日志部分通过新增统一日志初始化模块集中管理主日志文件与 `RotatingFileHandler`，各端入口只负责声明角色并接入，不改动现有 `_screen.log`、`_pty_raw.log` 等会话级调试文件的职责。

**Tech Stack:** Python 3、argparse、asyncio、websockets、logging、logging.handlers.RotatingFileHandler、pytest、POSIX shell

---

## 文件结构

### 新增文件

- `utils/logging_setup.py` — 统一创建 `/tmp/remote-claude/`、按角色配置 `RotatingFileHandler`、提供幂等 logger 初始化入口。
- `tests/test_logging_setup.py` — 验证统一日志初始化模块的路径、角色、轮转参数与幂等性。

### 修改文件

- `remote_claude.py` — 收敛远程参数校验、控制命令错误输出、startup/server/lark 日志接入点与 `/tmp` 主日志落点。
- `client/base_client.py` — 统一断线原因存储、输入/读取循环退出日志、清理阶段保护。
- `client/local_client.py` — 本地 socket 连接/读取/写入异常透传与状态一致性修复。
- `client/remote_client.py` — WebSocket 建连/发送/读取/关闭异常透传、保活相关日志与状态修复。
- `server/server.py` — 接入统一 server 主日志、修复 startup/runtime 日志切换、stderr 重定向路径、保留会话级调试日志。
- `server/ws_handler.py` — WebSocket 连接处理、错误返回、日志补齐与连接关闭边界修复。
- `lark_client/main.py` — 改为通过统一日志初始化模块配置 lark 主日志并保留控制台行为。
- `bin/remote-claude` — 如需要，仅对日志查看子命令路径或提示做与 `/tmp` 主日志一致的最小修正。
- `tests/test_cli_help_and_remote.py` — 扩展 CLI 帮助、远程参数、日志 tracing 回归测试。
- `tests/test_client_integration.py` — 扩展本地/远程客户端异常与断线原因测试。
- `tests/test_list_display.py` — 改为直接覆盖 `_normalize_original_path()` 与展示兜底逻辑。
- `tests/TEST_PLAN.md` — 补充主日志分流与轮转、连接稳定性修复测试项。
- `CLAUDE.md` — 更新主日志路径、角色拆分、轮转与调试日志职责说明。

---

### Task 1: 建立统一日志模块的失败测试

**Files:**
- Create: `utils/logging_setup.py`
- Test: `tests/test_logging_setup.py`

- [ ] **Step 1: 写失败测试，锁定日志目录、角色文件名和轮转参数**

```python
from pathlib import Path

from logging.handlers import RotatingFileHandler

from utils.logging_setup import LOG_DIR, get_role_log_path, setup_role_logging


def test_get_role_log_path_uses_tmp_directory():
    assert get_role_log_path("client") == Path("/tmp/remote-claude/client.log")
    assert get_role_log_path("server") == Path("/tmp/remote-claude/server.log")
    assert get_role_log_path("lark") == Path("/tmp/remote-claude/lark.log")


def test_setup_role_logging_uses_rotating_file_handler():
    logger = setup_role_logging("client", level=20)
    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    assert Path(handler.baseFilename) == LOG_DIR / "client.log"
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `uv run python3 -m pytest tests/test_logging_setup.py -q`
Expected: FAIL，提示 `ModuleNotFoundError: No module named 'utils.logging_setup'`

- [ ] **Step 3: 写最小实现，提供路径与 RotatingFileHandler 初始化**

```python
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("/tmp/remote-claude")
_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_ROLE_FILES = {
    "client": "client.log",
    "server": "server.log",
    "lark": "lark.log",
}


def get_role_log_path(role: str) -> Path:
    return LOG_DIR / _ROLE_FILES[role]


def setup_role_logging(role: str, level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"remote_claude.{role}")
    logger.setLevel(level)

    for handler in logger.handlers:
        if getattr(handler, "_remote_claude_role", None) == role:
            return logger

    handler = RotatingFileHandler(
        get_role_log_path(role),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler._remote_claude_role = role
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
```

- [ ] **Step 4: 运行测试，确认基础日志模块通过**

Run: `uv run python3 -m pytest tests/test_logging_setup.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/test_logging_setup.py utils/logging_setup.py
git commit -m "feat(logging): add rotating role log setup"
```

### Task 2: 完善日志模块幂等与 root logger 接入约束

**Files:**
- Modify: `utils/logging_setup.py`
- Modify: `tests/test_logging_setup.py`

- [ ] **Step 1: 写失败测试，锁定重复初始化不重复挂 handler**

```python
import logging
from logging.handlers import RotatingFileHandler

from utils.logging_setup import setup_role_logging


def test_setup_role_logging_is_idempotent():
    logger = logging.getLogger("remote_claude.client")
    logger.handlers.clear()

    setup_role_logging("client", level=logging.INFO)
    setup_role_logging("client", level=logging.INFO)

    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `uv run python3 -m pytest tests/test_logging_setup.py::test_setup_role_logging_is_idempotent -q`
Expected: FAIL，若重复挂载 handler 会看到 `assert 2 == 1`

- [ ] **Step 3: 调整实现，给 handler 打标记并清理冲突 handler**

```python
def _find_role_handler(logger: logging.Logger, role: str):
    for handler in logger.handlers:
        if getattr(handler, "_remote_claude_role", None) == role:
            return handler
    return None


def setup_role_logging(role: str, level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"remote_claude.{role}")
    logger.setLevel(level)

    existing = _find_role_handler(logger, role)
    if existing is not None:
        existing.setLevel(level)
        return logger

    handler = RotatingFileHandler(
        get_role_log_path(role),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler._remote_claude_role = role
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
```

- [ ] **Step 4: 运行日志模块测试，确认全部通过**

Run: `uv run python3 -m pytest tests/test_logging_setup.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/test_logging_setup.py utils/logging_setup.py
git commit -m "test(logging): enforce role logger idempotency"
```

### Task 3: 先写 CLI 与 list 展示回归测试

**Files:**
- Modify: `tests/test_cli_help_and_remote.py`
- Modify: `tests/test_list_display.py`
- Modify: `remote_claude.py:69-74`

- [ ] **Step 1: 扩展 list 展示测试，直接覆盖空白路径规范化**

```python
import remote_claude


def test_normalize_original_path_returns_dash_for_none():
    assert remote_claude._normalize_original_path(None) == "-"


def test_normalize_original_path_returns_dash_for_empty_string():
    assert remote_claude._normalize_original_path("") == "-"


def test_normalize_original_path_returns_dash_for_whitespace():
    assert remote_claude._normalize_original_path("   ") == "-"


def test_normalize_original_path_strips_regular_value():
    assert remote_claude._normalize_original_path(" /tmp/demo ") == "/tmp/demo"
```

- [ ] **Step 2: 扩展 CLI 失败测试，锁定远程缺参报错与 tracing**

```python
def test_validate_remote_args_requires_session_when_fallback_missing(capsys):
    args = SimpleNamespace(host="10.0.0.1", port=10000, token="t", name="")
    assert remote_claude.validate_remote_args(args) is None
    assert "错误: 请指定会话名称" in capsys.readouterr().out


def test_cmd_kill_remote_logs_tracing(monkeypatch, caplog):
    args = SimpleNamespace(remote=True, host="10.0.0.1", token="secret-token", port=10000, name="demo")
    monkeypatch.setattr(remote_claude, "run_remote_control", lambda host, port, session, token, action: 0)
    with caplog.at_level(logging.INFO):
        result = remote_claude.cmd_kill(args)
    assert result == 0
    assert any("stage=remote_args_parsed" in r.message and "command=kill" in r.message for r in caplog.records)
```

- [ ] **Step 3: 运行测试，确认当前失败**

Run: `uv run python3 -m pytest tests/test_cli_help_and_remote.py tests/test_list_display.py -q`
Expected: FAIL，至少包含 `validate_remote_args` 未校验会话名或 tracing 缺失

- [ ] **Step 4: 在 `remote_claude.py` 做最小实现，统一 list/kill/status/token 等远程参数校验入口**

```python
def validate_remote_args(args, session_fallback: str = None) -> tuple | None:
    host, port, session, token = parse_host_session(args)

    if not host:
        print("错误: 远程模式需要 --host 参数")
        return None
    if not token:
        print("错误: 远程模式需要 --token 参数")
        return None

    if not session and session_fallback:
        session = session_fallback
    if not session:
        print("错误: 请指定会话名称")
        return None

    return host, port, session, token
```

并在远程分支里统一补：

```python
_log_remote_args("kill", host, port, session, token)
_log_remote_args("status", host, port, session, token)
_log_remote_args("token", host, port, session, token)
_log_remote_args("regenerate-token", host, port, session, token)
```

- [ ] **Step 5: 重新运行测试，确认 CLI 与 list 展示回归通过**

Run: `uv run python3 -m pytest tests/test_cli_help_and_remote.py tests/test_list_display.py -q`
Expected: PASS

- [ ] **Step 6: 提交这一小步**

```bash
git add remote_claude.py tests/test_cli_help_and_remote.py tests/test_list_display.py
git commit -m "fix(cli): unify remote arg validation and path display"
```

### Task 4: 先写客户端断线与异常透传测试

**Files:**
- Modify: `tests/test_client_integration.py`
- Modify: `client/base_client.py`
- Modify: `client/local_client.py`
- Modify: `client/remote_client.py`

- [ ] **Step 1: 为 BaseClient 和 LocalClient 写失败测试**

```python
from utils.protocol import InputMessage


class DummyClient(BaseClient):
    async def connect(self):
        return True

    async def send_message(self, msg):
        raise ConnectionError("发送失败: broken pipe")

    async def read_message(self):
        return None

    async def close_connection(self):
        return None


@pytest.mark.asyncio
async def test_base_client_handle_input_records_disconnect_reason(capsys):
    client = DummyClient("demo")
    client.running = True
    await client._handle_input(b"hello")
    assert client.running is False
    assert client._connected is False
    out = capsys.readouterr().out
    assert "已断开连接: 发送失败: broken pipe" in out


@pytest.mark.asyncio
async def test_local_client_read_message_closed_sets_disconnect_reason():
    client = LocalClient("demo")
    client.reader = AsyncMock()
    client.reader.read = AsyncMock(return_value=b"")
    client._connected = True
    result = await client.read_message()
    assert result is None
    assert client._consume_disconnect_reason() == "连接已关闭"
```

- [ ] **Step 2: 运行客户端测试，确认当前失败**

Run: `uv run python3 -m pytest tests/test_client_integration.py -k "disconnect or local_client_read_message_closed_sets_disconnect_reason" -q`
Expected: FAIL，当前 LocalClient 不记录断线原因，BaseClient 断线状态不完整

- [ ] **Step 3: 在客户端代码中补统一断线原因存储与异常透传**

在 `client/base_client.py` 增加统一存储：

```python
class BaseClient(ABC):
    def __init__(self, session_name: str):
        ...
        self._disconnect_reason: Optional[str] = None

    def _set_disconnect_reason(self, reason: str) -> None:
        message = reason.strip() if isinstance(reason, str) else ""
        self._disconnect_reason = message or "连接已关闭"

    def _consume_disconnect_reason(self) -> Optional[str]:
        reason = self._disconnect_reason
        self._disconnect_reason = None
        return reason
```

在 `client/local_client.py` 里写入：

```python
if not data:
    self._connected = False
    self._set_disconnect_reason("连接已关闭")
    return None
```

以及：

```python
except Exception as e:
    self._connected = False
    self._set_disconnect_reason(f"读取失败: {e}")
    return None
```

- [ ] **Step 4: 运行客户端测试，确认断线原因透传通过**

Run: `uv run python3 -m pytest tests/test_client_integration.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add client/base_client.py client/local_client.py client/remote_client.py tests/test_client_integration.py
git commit -m "fix(client): preserve disconnect reasons across transports"
```

### Task 5: 修复远程控制链路和 WebSocketHandler 边界

**Files:**
- Modify: `remote_claude.py:194-224`
- Modify: `server/ws_handler.py`
- Test: `tests/test_server_ws.py`

- [ ] **Step 1: 写失败测试，锁定远程控制命令异常输出与 ws 认证失败路径**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from server.ws_handler import parse_url_params, WebSocketHandler


def test_parse_url_params_handles_missing_values():
    assert parse_url_params("/ws") == (None, None)


@pytest.mark.asyncio
async def test_ws_handler_rejects_invalid_token_with_error_message():
    server = MagicMock(history_buffer=b"")
    handler = WebSocketHandler(server, "demo")
    handler._authenticate = MagicMock(return_value=False)
    websocket = AsyncMock()

    await handler.handle_connection(websocket, "/ws?session=demo&token=bad")

    websocket.send.assert_awaited()
```

- [ ] **Step 2: 运行测试，确认当前失败或覆盖不足**

Run: `uv run python3 -m pytest tests/test_server_ws.py -q`
Expected: FAIL，或现有测试未覆盖错误码与关闭行为

- [ ] **Step 3: 在 `remote_claude.py` 和 `server/ws_handler.py` 做最小修复**

在 `remote_claude.py` 收敛远程控制异常：

```python
def run_remote_control(host: str, port: int, session: str, token: str, action: str) -> int:
    ...
    try:
        return asyncio.run(do_control())
    except Exception as e:
        logger.error(
            "stage=remote_command_failed command=%s session=%s host=%s port=%s error=%s",
            action,
            session,
            host,
            port,
            e,
        )
        print(f"✗ 连接失败: {e}")
        return 1
```

在 `server/ws_handler.py` 明确记录连接关闭与消息处理失败：

```python
except Exception as e:
    logger.error("stage=ws_message_failed session=%s client_id=%s error=%s", self.session_name, client_id, e)
    await self._send_error(websocket, "BAD_MESSAGE", f"消息处理失败: {e}")
```

并确保 finally 中始终移除连接。

- [ ] **Step 4: 运行 WebSocket 相关测试，确认通过**

Run: `uv run python3 -m pytest tests/test_server_ws.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add remote_claude.py server/ws_handler.py tests/test_server_ws.py
git commit -m "fix(remote): harden control and websocket error paths"
```

### Task 6: 将 server 主日志切换到统一模块并保留会话级调试日志

**Files:**
- Modify: `server/server.py`
- Modify: `utils/logging_setup.py`
- Test: `tests/test_startup_trace_logging.py`

- [ ] **Step 1: 写失败测试，锁定 server 主日志路径切到 `/tmp/remote-claude/server.log`**

```python
from pathlib import Path

from utils.logging_setup import get_role_log_path


def test_server_role_log_path_is_tmp_server_log():
    assert get_role_log_path("server") == Path("/tmp/remote-claude/server.log")
```

并在 startup trace 测试中补期望：

```python
assert "/tmp/remote-claude/server.log" in str(get_role_log_path("server"))
```

- [ ] **Step 2: 运行相关测试，确认当前失败**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_startup_trace_logging.py -q`
Expected: FAIL，当前 server 仍使用 `~/.remote-claude/startup.log` / `server.error.log`

- [ ] **Step 3: 在 `server/server.py` 接入统一 server 主日志，保留 `_screen.log` 与 `_pty_raw.log`**

将主 logger 初始化替换为统一入口，例如：

```python
from utils.logging_setup import setup_role_logging, get_role_log_path

logger = setup_role_logging("server", level=SERVER_LOG_LEVEL_MAP)
```

在 runtime 切换里避免继续写：

```python
error_log_path = os.path.expanduser('~/.remote-claude/server.error.log')
```

改为：

```python
error_log_path = str(get_role_log_path("server"))
```

并保留：

```python
self._debug_file = f"/tmp/remote-claude/{safe_name}_messages.log"
raw_log_path = f"/tmp/remote-claude/{safe_name}_pty_raw.log"
screen_path = base + "_screen.log"
```

- [ ] **Step 4: 运行日志与 startup trace 测试，确认通过**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_startup_trace_logging.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add server/server.py utils/logging_setup.py tests/test_logging_setup.py tests/test_startup_trace_logging.py
git commit -m "refactor(server): route main logs through rotating tmp logger"
```

### Task 7: 将 lark 主日志切换到统一模块

**Files:**
- Modify: `lark_client/main.py`
- Modify: `remote_claude.py:637-810`
- Test: `tests/test_cli_help_and_remote.py`

- [ ] **Step 1: 写失败测试，锁定 lark 主日志路径和启动提示**

```python
from utils.logging_setup import get_role_log_path


def test_lark_role_log_path_is_tmp_lark_log():
    assert str(get_role_log_path("lark")) == "/tmp/remote-claude/lark.log"
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_cli_help_and_remote.py -q`
Expected: FAIL，当前 lark 仍指向 `~/.remote-claude/lark_client.log`

- [ ] **Step 3: 在 `lark_client/main.py` 和 `remote_claude.py` 中切到统一 lark 主日志**

将：

```python
info_handler = logging.FileHandler(log_dir / "lark_client.log", encoding="utf-8")
```

改为通过统一模块返回 handler/logger，例如：

```python
from utils.logging_setup import setup_role_logging


def _setup_logging():
    from .config import LARK_LOG_LEVEL
    logger = setup_role_logging("lark", level=LARK_LOG_LEVEL)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for handler in logger.handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(LARK_LOG_LEVEL)
```

同时在 `remote_claude.py` 中获取 lark 日志路径时，改为统一使用 `get_role_log_path("lark")`，避免继续依赖 `get_lark_log_file()` 作为主日志真相源。

- [ ] **Step 4: 运行 lark 相关测试，确认通过**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_cli_help_and_remote.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add lark_client/main.py remote_claude.py utils/logging_setup.py tests/test_logging_setup.py tests/test_cli_help_and_remote.py
git commit -m "refactor(lark): move main logs to rotating tmp logger"
```

### Task 8: 收敛 client 主日志与 bin 入口路径行为

**Files:**
- Modify: `client/base_client.py`
- Modify: `client/remote_client.py`
- Modify: `client/local_client.py`
- Modify: `bin/remote-claude`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 写失败测试，锁定 client 角色 logger 初始化与 bin log 子命令路径**

```python
from pathlib import Path

from utils.logging_setup import get_role_log_path


def test_client_role_log_path_is_tmp_client_log():
    assert get_role_log_path("client") == Path("/tmp/remote-claude/client.log")
```

如果 `bin/remote-claude log` 有对应静态测试，补一条断言：

```python
assert "/tmp/remote-claude" in script_text
```

- [ ] **Step 2: 运行相关测试，确认当前失败或覆盖不足**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_entry_lazy_init.py -q`
Expected: FAIL，或缺少对 client 主日志路径的约束

- [ ] **Step 3: 在 client 与 bin 入口中接入统一路径**

在 `client/base_client.py` 顶部改为：

```python
from utils.logging_setup import setup_role_logging
logger = setup_role_logging("client")
```

并确保 `bin/remote-claude` 继续把 `log` 子命令会话调试日志指向 `/tmp/remote-claude/<session>_messages.log`，不要错误改成 `client.log`。如果需要仅调整提示文案，保持最小改动：

```sh
echo "📄 $LOG_FILE"
```

仍然输出会话日志，而不是主日志。

- [ ] **Step 4: 运行相关测试，确认 client/log 入口行为通过**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_entry_lazy_init.py tests/test_client_integration.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add client/base_client.py client/local_client.py client/remote_client.py bin/remote-claude tests/test_logging_setup.py tests/test_entry_lazy_init.py tests/test_client_integration.py
git commit -m "refactor(client): use shared rotating role logger"
```

### Task 9: 更新文档与测试计划

**Files:**
- Modify: `CLAUDE.md`
- Modify: `tests/TEST_PLAN.md`

- [ ] **Step 1: 写文档变更，明确主日志与调试日志职责**

在 `CLAUDE.md` 的“开发须知”或日志相关位置加入：

```md
- **主日志目录：** `/tmp/remote-claude/`
- **主日志拆分：** `client.log` / `server.log` / `lark.log`
- **日志轮转：** 主日志统一使用 `RotatingFileHandler`，参数为 `10MB × 5`
- **调试日志职责：** `_screen.log`、`_pty_raw.log`、`<session>_messages.log` 属于会话级调试日志，不与主日志混用
```

- [ ] **Step 2: 更新 `tests/TEST_PLAN.md`，补主日志分流与稳定性验证项**

加入类似条目：

```md
| 主日志路径统一 | client/server/lark 主日志均落到 `/tmp/remote-claude/` | `uv run python3 -m pytest tests/test_logging_setup.py -q` |
| 主日志轮转参数 | 使用 `RotatingFileHandler`，配置为 `10MB × 5` | `uv run python3 -m pytest tests/test_logging_setup.py::test_setup_role_logging_uses_rotating_file_handler -q` |
| 本地断线原因透传 | LocalClient 关闭/异常时保留断线原因 | `uv run python3 -m pytest tests/test_client_integration.py -k local_client_read_message_closed_sets_disconnect_reason -q` |
| 远程控制失败日志 | 远程控制链路记录 `stage=remote_command_failed` | `uv run python3 -m pytest tests/test_cli_help_and_remote.py -q` |
```

- [ ] **Step 3: 运行轻量文档相关回归，确认引用的测试命令有效**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_cli_help_and_remote.py tests/test_client_integration.py tests/test_list_display.py -q`
Expected: PASS

- [ ] **Step 4: 提交这一小步**

```bash
git add CLAUDE.md tests/TEST_PLAN.md
git commit -m "docs: document rotating tmp logs and stability coverage"
```

### Task 10: 全量验证并整理交付

**Files:**
- Modify: `remote_claude.py`
- Modify: `client/*.py`
- Modify: `server/*.py`
- Modify: `lark_client/main.py`
- Modify: `utils/logging_setup.py`
- Modify: `tests/*.py`
- Modify: `CLAUDE.md`
- Modify: `tests/TEST_PLAN.md`

- [ ] **Step 1: 运行核心回归测试**

Run: `uv run python3 -m pytest tests/test_logging_setup.py tests/test_cli_help_and_remote.py tests/test_client_integration.py tests/test_list_display.py tests/test_server_ws.py tests/test_startup_trace_logging.py -q`
Expected: PASS

- [ ] **Step 2: 运行脚本与入口回归测试**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -q`
Expected: PASS

- [ ] **Step 3: 做一次静态搜索，确认主日志已统一到 `/tmp/remote-claude/`，且会话级调试日志仍保留**

Run: `python3 - <<'PY'
from pathlib import Path
for path in Path('.').rglob('*.py'):
    text = path.read_text(encoding='utf-8')
    if 'server.error.log' in text or 'lark_client.log' in text:
        print(path)
PY`
Expected: 不再输出主日志遗留路径；允许看到 `_screen.log`、`_pty_raw.log`、`_messages.log`

- [ ] **Step 4: 查看当前 diff，确认只包含本次范围内改动**

Run: `git diff --stat`
Expected: 仅出现本计划涉及的 Python、测试、文档与必要脚本文件

- [ ] **Step 5: 提交最终整理**

```bash
git add remote_claude.py client/base_client.py client/local_client.py client/remote_client.py server/server.py server/ws_handler.py lark_client/main.py utils/logging_setup.py tests/test_logging_setup.py tests/test_cli_help_and_remote.py tests/test_client_integration.py tests/test_list_display.py tests/test_server_ws.py tests/test_startup_trace_logging.py tests/test_entry_lazy_init.py CLAUDE.md tests/TEST_PLAN.md bin/remote-claude
git commit -m "feat(logging): unify rotating role logs and harden connection flows"
```

---

## Self-Review

- **Spec coverage:**
  - 稳定性修复：Task 3、4、5、8 覆盖参数、连接、路径、异常、保活边界。
  - 统一日志模块：Task 1、2、6、7、8 覆盖 client/server/lark 三类主日志与 `10MB × 5` 轮转。
  - 保留会话级调试日志：Task 6、8 明确保留 `_screen.log`、`_pty_raw.log`、`_messages.log`。
  - 文档与测试同步：Task 9 覆盖 `CLAUDE.md` 与 `tests/TEST_PLAN.md`。
- **Placeholder scan:** 已移除 TBD/TODO/“类似 Task N” 之类占位描述；每个代码步骤都给了明确代码片段或精确命令。
- **Type consistency:** 计划统一使用 `setup_role_logging()`、`get_role_log_path()`、`_normalize_original_path()`、`validate_remote_args()` 这些名称，没有前后漂移。
