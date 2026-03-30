# Remote 模式 remote_port 透传与失败追溯日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 remote 模式下 `--remote-port` 未传递到 `server.py` 的问题，并在 `remote_claude.py/server.py` 增加失败可追溯的命令日志，同时同步更新 `README.md`。

**Architecture:** 保持现有 `remote_claude.py -> tmux -> server/server.py` 启动链路不变，仅补齐 `server.py` 入口参数解析与参数透传。日志采用“结构化摘要 + 脱敏完整命令”双轨：启动前记录上下文，失败分支复用同一追溯字段，确保可从 `startup.log` 直接定位问题。

**Tech Stack:** Python 3、argparse、logging、pytest、README 文档维护

---

## 文件结构与职责映射

- `remote_claude.py`
  - 保持 `cmd_start` 组装 server 命令的逻辑。
  - 新增命令脱敏函数与启动追溯日志字段（启动前 + 失败分支）。
- `server/server.py`
  - 在 `__main__` argparse 增加 `--remote --remote-host --remote-port`。
  - 将解析结果传入 `run_server(...)`，并记录 bootstrap 参数日志。
- `tests/test_server_ws.py`
  - 新增 server 入口参数解析与 `run_server` 参数透传测试。
- `tests/test_integration.py`
  - 新增/补充 `cmd_start` 日志追溯字段测试（mock tmux/日志写入路径）。
- `README.md`
  - 更新远程启动参数说明与排障日志说明（startup.log 中追溯字段与脱敏命令）。

---

### Task 1: 先用测试锁定 server.py 参数透传缺陷

**Files:**
- Modify: `tests/test_server_ws.py`
- Modify: `server/server.py`

- [ ] **Step 1: 写失败测试（server.py 入口 argparse 必须支持 remote 参数）**

```python
# tests/test_server_ws.py

def test_server_main_parses_remote_args_and_calls_run_server(monkeypatch):
    import runpy
    import sys

    called = {}

    def fake_run_server(session_name, cli_args, **kwargs):
        called["session_name"] = session_name
        called["cli_args"] = cli_args
        called.update(kwargs)

    monkeypatch.setattr("server.server.run_server", fake_run_server)
    monkeypatch.setattr(sys, "argv", [
        "server.py",
        "demo",
        "--remote",
        "--remote-host", "127.0.0.1",
        "--remote-port", "9999",
    ])

    runpy.run_module("server.server", run_name="__main__")

    assert called["session_name"] == "demo"
    assert called["enable_remote"] is True
    assert called["remote_host"] == "127.0.0.1"
    assert called["remote_port"] == 9999
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_server_ws.py -k parses_remote_args -q`
Expected: FAIL（`unrecognized arguments: --remote --remote-host --remote-port` 或 `enable_remote` 未传递）。

- [ ] **Step 3: 最小实现 server.py 参数补齐与透传**

```python
# server/server.py (__main__ argparse)
parser.add_argument("--remote", action="store_true", help="启用远程 WebSocket")
parser.add_argument("--remote-host", default="0.0.0.0", help="远程监听地址")
parser.add_argument("--remote-port", type=int, default=8765, help="远程监听端口")

run_server(
    args.session_name,
    args.cli_args,
    cli_type=args.cli_type,
    cli_command=args.cli_command,
    debug_screen=args.debug_screen,
    debug_verbose=args.debug_verbose,
    enable_remote=args.remote,
    remote_host=args.remote_host,
    remote_port=args.remote_port,
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_server_ws.py -k parses_remote_args -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/test_server_ws.py server/server.py
git commit -m "fix(server): pass remote args from entrypoint to run_server"
```

---

### Task 2: 为 remote_claude.py 增加“摘要 + 脱敏完整命令”追溯日志

**Files:**
- Modify: `tests/test_integration.py`
- Modify: `remote_claude.py`

- [ ] **Step 1: 写失败测试（启动日志必须包含追溯字段）**

```python
# tests/test_integration.py

def test_cmd_start_logs_sanitized_server_command_on_failure(monkeypatch, tmp_path):
    from remote_claude import cmd_start
    from types import SimpleNamespace

    log_file = tmp_path / "startup.log"
    monkeypatch.setattr("remote_claude.USER_DATA_DIR", tmp_path)
    monkeypatch.setattr("remote_claude.is_session_active", lambda _: False)
    monkeypatch.setattr("remote_claude.tmux_session_exists", lambda _: False)
    monkeypatch.setattr("remote_claude.ensure_socket_dir", lambda: None)
    monkeypatch.setattr("remote_claude.get_env_snapshot_path", lambda _: tmp_path / "env.json")
    monkeypatch.setattr("remote_claude.tmux_create_session", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("remote_claude.get_socket_path", lambda _: tmp_path / "missing.sock")
    monkeypatch.setattr("remote_claude.tmux_kill_session", lambda _: None)

    args = SimpleNamespace(
        name="demo",
        cli_args=["--token", "secret-token"],
        debug_screen=False,
        debug_verbose=False,
        cli="claude",
        remote=True,
        remote_port=9999,
        remote_host="0.0.0.0",
    )

    rc = cmd_start(args)
    assert rc == 1
    content = log_file.read_text(encoding="utf-8")
    assert "stage=server_spawn" in content
    assert "remote_port=9999" in content
    assert "server_cmd_sanitized=" in content
    assert "secret-token" not in content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_integration.py -k sanitized_server_command -q`
Expected: FAIL（日志中暂无 `stage/server_cmd_sanitized` 字段）。

- [ ] **Step 3: 最小实现日志增强（不改业务流程）**

```python
# remote_claude.py

def _sanitize_command_for_log(command: str) -> str:
    # 脱敏高风险片段（token/password/secret）
    patterns = [
        r"(?i)(--token\s+)(\S+)",
        r"(?i)(token=)([^\s]+)",
        r"(?i)(--password\s+)(\S+)",
        r"(?i)(password=)([^\s]+)",
        r"(?i)(--secret\s+)(\S+)",
        r"(?i)(secret=)([^\s]+)",
    ]
    sanitized = command
    for p in patterns:
        sanitized = re.sub(p, r"\1***", sanitized)
    return sanitized

# cmd_start 中，在 tmux_create_session 前记录
_start_logger.info(
    "stage=server_spawn session=%s cli_type=%s remote=%s remote_host=%s remote_port=%s cli_args_count=%s",
    session_name, args.cli, args.remote, args.remote_host, args.remote_port, len(cli_args)
)
_start_logger.info("server_cmd_sanitized=%s", _sanitize_command_for_log(server_cmd))

# 失败分支追加
_start_logger.error(
    "stage=server_start_failed reason=%s session=%s remote=%s remote_host=%s remote_port=%s",
    "tmux_create_failed|server_exited|startup_timeout",
    session_name, args.remote, args.remote_host, args.remote_port,
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_integration.py -k sanitized_server_command -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py remote_claude.py
git commit -m "feat(start): add sanitized command tracing logs for startup failures"
```

---

### Task 3: server.py 增加启动参数追溯日志

**Files:**
- Modify: `tests/test_server_ws.py`
- Modify: `server/server.py`

- [ ] **Step 1: 写失败测试（server bootstrap 日志必须含 remote 参数）**

```python
# tests/test_server_ws.py

def test_server_bootstrap_logs_remote_fields(caplog):
    from server.server import run_server

    with patch("server.server.ProxyServer") as mock_proxy, \
         patch("server.server.asyncio.run"):
        run_server(
            "demo",
            [],
            cli_type="claude",
            enable_remote=True,
            remote_host="127.0.0.1",
            remote_port=9999,
        )

    text = "\n".join(r.message for r in caplog.records)
    assert "stage=run_server_enter" in text
    assert "remote_port=9999" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_server_ws.py -k bootstrap_logs_remote_fields -q`
Expected: FAIL（尚无该日志字段）。

- [ ] **Step 3: 最小实现 server 追溯日志**

```python
# server/server.py
logger.info(
    "stage=run_server_enter session=%s cli_type=%s enable_remote=%s remote_host=%s remote_port=%s cli_args_count=%s",
    session_name, cli_type, enable_remote, remote_host, remote_port, len(cli_args or []),
)
```

```python
# __main__ 启动后
logger.info(
    "stage=server_bootstrap args session=%s cli_type=%s remote=%s remote_host=%s remote_port=%s cli_args_count=%s",
    args.session_name, args.cli_type, args.remote, args.remote_host, args.remote_port, len(args.cli_args or []),
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_server_ws.py -k "bootstrap_logs_remote_fields or parses_remote_args" -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/test_server_ws.py server/server.py
git commit -m "feat(server): add startup trace logs for remote arguments"
```

---

### Task 4: 更新 README 远程参数与失败追溯说明

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 写文档检查测试（文本断言）**

```bash
python3 - <<'PY'
from pathlib import Path
text = Path("README.md").read_text(encoding="utf-8")
assert "--remote-port" in text
assert "startup.log" in text
assert "脱敏" in text
print("README checks ready")
PY
```

- [ ] **Step 2: 运行检查确认失败（若缺文案）**

Run: 上述命令
Expected: 在更新前可能 FAIL（缺少“失败追溯/脱敏命令”说明）。

- [ ] **Step 3: 最小更新 README**

```markdown
## 远程连接排障

- 启动日志文件：`~/.remote-claude/startup.log`
- `remote-claude start ... --remote --remote-port <port>` 失败时，会记录：
  - 结构化摘要：`stage/session/remote_host/remote_port/exit_reason`
  - 脱敏完整命令：`server_cmd_sanitized=...`（token/password/secret 会被打码）
- 建议先 grep `stage=server_start_failed` 定位失败阶段，再查看对应 `server_cmd_sanitized`。
```

- [ ] **Step 4: 运行检查确认通过**

Run: 上述 Python 断言命令
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document remote startup trace logs and troubleshooting"
```

---

### Task 5: 全量回归与最终提交

**Files:**
- Modify: （无新增代码，仅验证）

- [ ] **Step 1: 运行目标测试集**

Run: `uv run python3 -m pytest tests/test_server_ws.py tests/test_integration.py -q`
Expected: PASS。

- [ ] **Step 2: 运行关键命令冒烟（本地）**

Run: `uv run python3 remote_claude.py start demo-remote --remote --remote-port 9999 --remote-host 127.0.0.1 -- --version`
Expected: 输出中可见 WebSocket 地址使用 9999，失败场景可在 `~/.remote-claude/startup.log` 检索到 `stage=` 与 `server_cmd_sanitized=`。

- [ ] **Step 3: 合并提交（如前面分 commit，可跳过）**

```bash
git status
git log --oneline -5
```

- [ ] **Step 4: 记录验证结果**

```markdown
- test_server_ws: PASS
- test_integration: PASS
- manual start --remote-port 9999: PASS
- startup trace fields: PASS
```

---

## 自检（plan vs spec）

- 覆盖性：已覆盖三项需求（remote_port 修复、双轨日志、README 更新）。
- 占位词：无 TBD/TODO/“后续补充”占位。
- 一致性：`remote_port` 统一使用 `--remote-port`，日志字段统一使用 `stage=...`。
