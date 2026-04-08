# TEST_PLAN.md

本文档聚焦当前有效的测试入口、关键回归项和 Docker 验证流程。

## 测试分层

### 层 1：本地回归（无需前置条件）

| 类型 | 关注点 | 推荐命令 |
|------|--------|---------|
| 核心配置与命令行 | 会话名、配置迁移、CLI 行为、remote 参数、启动 tracing | `uv run python3 -m pytest tests/test_session_truncate.py tests/test_runtime_config.py tests/test_custom_commands.py tests/test_cli_help_and_remote.py tests/test_startup_trace_logging.py -q` |
| shell / 安装链路 | lazy init、shell 兼容、安装与入口脚本 | `uv run python3 -m pytest tests/test_entry_lazy_init.py -q` |
| 飞书渲染与交互 | poller、卡片交互、断连展示、终端清理 | `uv run python3 -m pytest tests/test_stream_poller.py tests/test_card_interaction.py tests/test_disconnected_state.py tests/test_renderer.py -q` |

### 层 2：集成测试（需要活跃会话）

```bash
uv run remote-claude start test
uv run python3 tests/test_integration.py
uv run remote-claude kill test
```

### 层 3：飞书视觉验证（手动）

重点检查：
- 新会话连接
- 流式输出滚动与更新
- 选项 / 权限卡片交互
- 断开重连状态
- 快捷命令选择器

---

## 快速回归

当修改命令行入口、remote 参数、shell 启动链路时，优先运行：

```bash
uv run python3 -m pytest \
  tests/test_custom_commands.py \
  tests/test_cli_help_and_remote.py \
  tests/test_startup_trace_logging.py \
  tests/test_entry_lazy_init.py -q
```

---

## Docker 回归

当修改 npm 打包、安装链路、shell 入口、启动链路或 Docker 逻辑时运行：

```bash
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

当前 Docker 脚本覆盖：
- `npm pack` / `npm install` 后的产物完整性
- `check-env.sh` 在 `REMOTE_CLAUDE_REQUIRE_FEISHU=0` 下跳过飞书检查
- `remote-claude lark start` 在 mock 凭证下不无限阻塞
- `remote-claude start` 的 Claude / Codex 启动链路
- 无效 launcher 配置下的失败退出检测
- 关键单元测试与入口脚本行为回归

### Docker 失败诊断

```bash
/project/docker/scripts/docker-diagnose.sh
```

诊断脚本会收集：
- 系统信息与依赖版本
- npm / Python 包安装信息
- 安装后文件结构
- `remote-claude list` 输出
- `/tmp/remote-claude` socket 目录状态
- `tmux list-sessions` 输出
- `~/.remote-claude/startup.log` 尾部日志
- `test-results/` 下的日志与错误摘要

---

## 精选专项回归

### 启动链路与飞书解耦

| 验证点 | 命令 |
|--------|------|
| 飞书未配置时允许本地启动 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_entry_script_skips_feishu_prompt_and_executes_remote_claude_when_optional -q` |
| bin 入口统一走项目 Python | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_bin_entry_scripts_use_remote_claude_python_consistently -q` |
| 显式跳过飞书配置检查 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_check_env_allows_skip_when_feishu_not_required -q` |
| lazy init 失败信息可见 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_lazy_init_failure_surfaces_log_hint_and_stage_details -q` |

### shell 与安装链路

| 验证点 | 命令 |
|--------|------|
| rc 自适应选择 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_get_shell_rc_prefers_zsh_when_shell_is_zsh -q` |
| shell 脚本无 bash-only 语法 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_shell_scripts_do_not_contain_bash_only_constructs -q` |
| scripts 路径统一 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_scripts_define_project_dir_before_common_source -q` |
| completion source 稳定 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_completion_script_can_be_sourced_from_random_cwd -q` |
| 安装失败日志落盘 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_install_sh_initializes_install_log_helpers -q` |
| 补全路径一致 | `uv run python3 -m pytest tests/test_entry_lazy_init.py::test_setup_completion_uses_scripts_path -q` |

### CLI / remote 参数

| 验证点 | 命令 |
|--------|------|
| management/help 不产生副作用 | `uv run python3 -m pytest tests/test_cli_help_and_remote.py::test_management_subcommand_help_and_empty_invocation_do_not_create_side_effects -q` |
| attach 远程参数顺序兼容 | `uv run python3 -m pytest tests/test_cli_help_and_remote.py::test_validate_remote_args_accepts_current_attach_order -q` |
| token/regenerate-token 远程控制链路 | `uv run python3 -m pytest tests/test_cli_help_and_remote.py::test_cmd_remote_uses_validate_remote_args_and_run_remote_control tests/test_cli_help_and_remote.py::test_cmd_regenerate_token_uses_validate_remote_args_and_run_remote_control -q` |

---

## 调试工具

```bash
uv run python3 lark_client/capture_output.py <会话名> [秒数]
cat /tmp/remote-claude/<name>_messages.log | jq .
uv run remote-claude start test --debug-screen
cat /tmp/remote-claude/test_screen.log
```
