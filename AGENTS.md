# CLAUDE.md/AGENTS.md

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
- `lark_client/main.py` 是飞书入口；`lark_client/` 只负责展示流转，**严禁**做字符串修复或 ANSI 清理。

## 关键约束

- 配置修改必须保持原子性，`utils/runtime_config.py` 的修改型接口使用持锁读改写。
- `utils/session.py` 与 `utils/runtime_config.py` 存在循环依赖，`resolve_session_name()` 使用延迟导入。
- 涉及启动链路、help 输出、remote 参数、shell 包装脚本时，优先回归 `tests/test_custom_commands.py`、`tests/test_cli_help_and_remote.py`、`tests/test_startup_trace_logging.py`、`tests/test_entry_lazy_init.py`。
- 涉及 npm 打包、安装脚本、入口脚本或 Docker 逻辑时，必须补跑 Docker 回归。
- 飞书显示异常时优先检查服务端输出链路，不要在 Lark 侧补丁修复。

## 运行环境

- macOS/Linux
- 需已安装 `tmux` 和 `claude` CLI
- socket 路径：`/tmp/remote-claude/<name>.sock`
- tmux 会话前缀：`rc-`
- 详细测试矩阵见 `tests/TEST_PLAN.md`