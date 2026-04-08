# CLAUDE.md/AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# **关键语言要求**

你必须完全使用 **简体中文** 进行交互、思考和汇报。

## 项目定位

Remote Claude 让终端侧与飞书侧共享同一 Claude/Codex CLI 会话：tmux 承载真实进程，服务端通过 PTY + Unix Socket/WebSocket 广播统一输出。

## 常用命令

```bash
# 安装 / 基础检查
uv sync
uv run remote-claude --help
remote-claude list

# 本地会话
uv run remote-claude start <session>
uv run remote-claude attach <session>
uv run remote-claude status <session>
uv run remote-claude kill <session>

# 飞书客户端
remote-claude lark start
remote-claude lark stop
remote-claude lark status

# 回归测试
uv run python3 -m pytest tests/test_session_truncate.py tests/test_runtime_config.py tests/test_custom_commands.py tests/test_cli_help_and_remote.py tests/test_startup_trace_logging.py -q
uv run python3 -m pytest tests/test_entry_lazy_init.py -q
uv run python3 -m pytest tests/test_stream_poller.py tests/test_card_interaction.py tests/test_disconnected_state.py tests/test_renderer.py -q
uv run python3 -m pytest tests/test_custom_commands.py -q
uv run python3 -m pytest tests/test_entry_lazy_init.py::test_entry_script_skips_feishu_prompt_and_executes_remote_claude_when_optional -q

# Docker 回归
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
/project/docker/scripts/docker-diagnose.sh
```

## 架构速览

- `bin/cla`、`bin/cl`、`bin/cx`、`bin/cdx`、`bin/remote-claude` 是 shell launcher；公开 CLI 主入口是 `remote-claude`，实际实现位于 `remote_claude.py`。
- `package.json` 负责 npm 分发与安装脚本，`pyproject.toml` 负责 Python 依赖与 pytest 配置；这是 npm + Python 双入口项目。
- `server/` 负责 PTY 代理、输出广播、ANSI 解析和终端状态恢复。
- `client/base_client.py` 抽象终端客户端共性；本地/远程客户端仅实现传输差异。
- `remote_claude.py` 负责 CLI 参数解析、命令分发与最终展示；如果是远程控制命令，CLI 展示格式优先放这里，不要把面向终端用户的展示文案塞进服务端。
- `client/base_client.py` / `client/remote_client.py` 负责远程控制链路的连接与控制命令发送；涉及 websockets 兼容性时，优先统一在这一层，不要让 connect 与 send_control 走两套依赖路径。
- `server/ws_handler.py` 负责远程控制 action 分发与单 session 语义；新增/修改 `status`、`kill`、`token`、`regenerate-token`、`list`、`lark-*` 等远程 action 时，先改这里，再决定 CLI 如何展示。
- 当前远程 `list` 的语义是：返回**当前 WebSocket 入口绑定 session** 的状态信息，不是远端全局会话枚举；如果将来要做全局枚举，应作为新能力设计，不要直接复用现有单 session action 语义。
- `lark_client/main.py` 是飞书入口；`lark_client/` 只负责展示流转，**严禁**做字符串修复或 ANSI 清理。

## 关键约束

- 配置修改必须保持原子性，`utils/runtime_config.py` 的修改型接口使用持锁读改写。
- `utils/session.py` 与 `utils/runtime_config.py` 存在循环依赖，`resolve_session_name()` 使用延迟导入。
- 涉及启动链路、help 输出、remote 参数、shell 包装脚本时，优先回归 `tests/test_custom_commands.py`、`tests/test_cli_help_and_remote.py`、`tests/test_startup_trace_logging.py`、`tests/test_entry_lazy_init.py`。
- 涉及远程控制 action、WebSocket 控制命令、远程 list/status/kill/token/regenerate-token 展示时，优先回归 `tests/test_ws_handler.py`、`tests/test_client_integration.py`、`tests/test_server_ws.py`、`tests/test_cli_help_and_remote.py`。
- 涉及 npm 打包、安装脚本、入口脚本或 Docker 逻辑时，必须补跑 Docker 回归。
- 飞书显示异常时优先检查服务端输出链路，不要在 Lark 侧补丁修复。

## 运行环境

- macOS/Linux
- 需已安装 `tmux` 和 `claude` CLI
- socket 路径：`/tmp/remote-claude/<name>.sock`
- tmux 会话前缀：`rc-`
- 详细测试矩阵见 `tests/TEST_PLAN.md`