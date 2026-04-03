# 开发者指南

本文档面向在本仓库内开发 Remote Claude 的贡献者，聚焦源码结构、开发命令、测试入口和关键约束。

## 项目概览

Remote Claude 是共享 Claude/Codex CLI 会话的双端工具：本地会话运行在 tmux 中，服务端负责 PTY 代理与输出广播，终端客户端和飞书客户端共同消费同一份会话状态。

## 技术栈

- Python 3.11
- `uv`：Python 依赖与本地开发环境管理
- npm：分发与安装脚本
- tmux：承载实际 Claude/Codex 会话
- WebSocket / Unix Socket：本地与远程连接传输
- `lark-oapi`：飞书客户端接入
- pytest：测试框架

## 项目结构

- `remote_claude.py`：CLI 主入口，负责参数解析与命令分发
- `server/`：PTY 代理、输出广播、远程连接、token 管理
- `client/`：本地 Unix Socket / 远程 WebSocket 客户端
- `lark_client/`：飞书消息、卡片交互与共享状态展示
- `utils/`：会话管理、协议、日志、运行时配置
- `scripts/`：安装、卸载、shell 补全、环境检查脚本
- `tests/`：单元测试、集成测试与回归测试
- `docker/`：npm 安装链路与 Docker 回归测试

## 开发命令

### 环境准备

```bash
uv sync
```

### 本地运行

```bash
uv run remote-claude --help
uv run remote-claude start <session>
uv run remote-claude attach <session>
```

### 常用测试

```bash
# 核心配置与命令行回归
uv run python3 -m pytest tests/test_session_truncate.py tests/test_runtime_config.py tests/test_custom_commands.py tests/test_cli_help_and_remote.py tests/test_startup_trace_logging.py -q

# shell / 安装链路
uv run python3 -m pytest tests/test_entry_lazy_init.py -q

# 飞书渲染与交互
uv run python3 -m pytest tests/test_stream_poller.py tests/test_card_interaction.py tests/test_disconnected_state.py tests/test_renderer.py -q

# 单文件
uv run python3 -m pytest tests/test_custom_commands.py -q

# 单用例
uv run python3 -m pytest tests/test_entry_lazy_init.py::test_entry_script_skips_feishu_prompt_and_executes_remote_claude_when_optional -q
```

### Docker 回归

```bash
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
/project/docker/scripts/docker-diagnose.sh
```

## 关键约定

- `lark_client/` 只负责展示流转，**严禁**做字符串修复或 ANSI 清理。
- 如果飞书显示异常，优先检查服务端输出链路，不要在 Lark 侧补丁修复。
- `utils/runtime_config.py` 的修改型接口必须保持原子读改写，避免多进程竞态。
- `utils/session.py` 与 `utils/runtime_config.py` 存在循环依赖，`resolve_session_name()` 通过延迟导入规避。
- `package.json` 负责 npm 分发与安装脚本，`pyproject.toml` 负责 Python 依赖与 pytest 配置；开发时两者都要看。

## 测试约定

- 改动启动链路、help 输出、remote 参数、shell 包装脚本时，优先回归：
  - `tests/test_custom_commands.py`
  - `tests/test_cli_help_and_remote.py`
  - `tests/test_startup_trace_logging.py`
  - `tests/test_entry_lazy_init.py`
- 改动 npm 打包、安装脚本、入口脚本或 Docker 逻辑时，必须补跑 Docker 回归。
- 详细测试矩阵见 [`../tests/TEST_PLAN.md`](../tests/TEST_PLAN.md)。

## 相关文档

- [配置说明](configuration.md)
- [飞书客户端管理](feishu-client.md)
- [飞书配置](feishu-setup.md)
- [远程连接说明](remote-connection.md)
- [CLI 命令参考](cli-reference.md)
- [Docker 测试](docker-test.md)
