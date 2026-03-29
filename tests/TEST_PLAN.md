# TEST_PLAN.md

本文档描述 Remote Claude 项目的测试策略、分层和执行方法。

## 测试分层

测试分为三层，从底层到顶层依次覆盖：

### 层 1：单元测试（纯本地，无依赖）

独立运行的测试脚本，验证纯逻辑功能，无需网络和服务。

| 测试文件 | 覆盖范围 | 运行命令 |
|---------|---------|---------|
| `test_stream_poller.py` | 流式卡片模型（card_builder + poller） | `uv run python3 tests/test_stream_poller.py` |
| `test_session_truncate.py` | 会话名称截断、映射存储、快捷命令验证 | `uv run python3 tests/test_session_truncate.py` |
| `test_runtime_config.py` | 运行时配置加载/保存/迁移/可见性判断 | `uv run python3 tests/test_runtime_config.py` |
| `test_history_buffer.py` | 环形历史缓冲区（Ring Buffer 实现） | `uv run python3 tests/test_history_buffer.py` |
| `test_renderer.py` | 终端渲染器 | `uv run python3 tests/test_renderer.py` |

### 层 2：集成测试（需要活跃会话）

直连 socket 的测试，验证真实消息传递和协议处理。

| 测试文件 | 覆盖范围 | 运行命令 |
|---------|---------|---------|
| `test_integration.py` | 消息协议集成 | `uv run python3 tests/test_integration.py` |
| `test_session.py` | 会话连接管理 | `uv run python3 tests/test_session.py` |
| `test_real.py` | 实时数据渲染 | `uv run python3 tests/test_real.py` |
| `test_e2e.py` | 端到端流程 | `uv run python3 tests/test_e2e.py` |
| `test_mock_conversation.py` | 模拟多轮对话 | `uv run python3 tests/test_mock_conversation.py` |

**前置条件**：启动一个测试会话
```bash
uv run python3 remote_claude.py start test
```

### 层 3：飞书视觉测试

验证飞书卡片的实际渲染效果，手动进行。

**测试场景**：
- 新会话连接：验证卡片初始状态
- 流式输出：验证内容滚动和更新
- 选项交互：验证按钮点击响应
- 权限确认：验证权限提示卡片
- Agent 面板：验证后台任务显示
- 断开重连：验证连接状态切换
- 快捷命令选择器：验证下拉选择和命令发送

---

## 本功能测试场景（命令行与飞书用户体验增强）

### User Story 1：会话名称自动截断处理

**测试文件**：`tests/test_session_truncate.py`

| 场景 | 验证点 | 测试方法 |
|------|-------|---------|
| 正常长度会话名 | 不截断，直接使用 | `test_safe_filename_normal()` |
| 包含路径分隔符 | `/` 和 `.` 替换为 `_` | `test_safe_filename_with_slash()` |
| 超长会话名截断 | 长度不超过限制，保留后缀 | `test_safe_filename_truncate()` |
| 单部分超长 | 回退到 MD5 哈希 | `test_safe_filename_md5_fallback()` |
| 映射存储 | RuntimeConfig 存取映射 | `test_runtime_config_session_mapping()` |
| 映射数量限制 | 警告日志但不阻塞 | `test_runtime_config_mapping_limit()` |
| 平台特定限制 | macOS/Linux 不同限制 | `test_max_filename_platform()` |

**独立测试**：
```bash
# 创建超长路径
mkdir -p /tmp/very/long/path/that/exceeds/the/maximum/socket/path/length/limit/test/project

# 进入目录并启动会话
cd /tmp/very/long/path/that/exceeds/the/maximum/socket/path/length/limit/test/project
uv run python3 remote_claude.py start .

# 验证：会话正常启动，无报错
uv run python3 remote_claude.py list

# 查看映射
cat ~/.remote-claude/runtime.json | grep session_mappings -A 5
```

### User Story 2：飞书快捷命令选择器

**测试文件**：`tests/test_runtime_config.py`

| 场景 | 验证点 | 测试方法 |
|------|-------|---------|
| 默认不可见 | `enabled=false` 时不显示 | `test_quick_commands_visibility_disabled()` |
| 启用但无命令 | `commands=[]` 时不显示 | `test_quick_commands_visibility_enabled_no_commands()` |
| 启用且有命令 | 正常显示选择器 | `test_quick_commands_visibility_enabled_with_commands()` |
| 禁用但有命令 | 仍不显示 | `test_quick_commands_visibility_disabled_with_commands()` |
| 获取命令列表 | 正确返回列表 | `test_get_quick_commands()` |
| 配置迁移 | 旧文件自动迁移 | `test_migrate_valid_legacy_file()` |
| 配置损坏处理 | 备份并使用默认配置 | `test_load_config_corrupted()` |

**独立测试**：
1. 配置快捷命令：
```bash
vim ~/.remote-claude/runtime.json
# 添加 ui_settings.quick_commands 配置
```

2. 重启飞书客户端：
```bash
uv run python3 remote_claude.py lark restart
```

3. 在飞书中验证卡片底部显示快捷命令选择器

### User Story 3：默认日志级别设置

| 场景 | 验证点 | 测试方法 |
|------|-------|---------|
| 未设置环境变量 | 默认 WARNING 级别 | 检查 `lark_client/config.py` 默认值 |
| 设置 DEBUG | 输出调试信息 | `LARK_LOG_LEVEL=DEBUG uv run python3 remote_claude.py lark restart` |
| 设置 INFO | 输出信息级别 | `LARK_LOG_LEVEL=INFO uv run python3 remote_claude.py lark restart` |

**验证方法**：
```bash
# 查看日志输出量
ls -la ~/.remote-claude/lark_client.log

# 启用 DEBUG 后查看详细日志
export LARK_LOG_LEVEL=DEBUG
uv run python3 remote_claude.py lark restart
tail -f ~/.remote-claude/lark_client.log
```

### User Story 4：Help 参数纯展示模式

| 场景 | 验证点 | 测试方法 |
|------|-------|---------|
| 主命令帮助 | 只显示帮助，无错误 | `uv run python3 remote_claude.py --help` |
| start 子命令帮助 | 不启动会话 | `uv run python3 remote_claude.py start --help` |
| attach 子命令帮助 | 不检查会话存在 | `uv run python3 remote_claude.py attach --help` |
| lark 子命令帮助 | 只显示帮助 | `uv run python3 remote_claude.py lark --help` |
| lark status 子命令帮助 | 不检查客户端状态 | `uv run python3 remote_claude.py lark status --help` |

---

## 测试执行流程

### 完整测试套件

```bash
# 层 1：单元测试（无需任何前置条件）
uv run python3 tests/test_stream_poller.py
uv run python3 tests/test_session_truncate.py
uv run python3 tests/test_runtime_config.py
uv run python3 tests/test_renderer.py

# 层 2：集成测试（需要活跃会话）
uv run python3 remote_claude.py start test
uv run python3 tests/test_integration.py
uv run python3 tests/test_session.py
uv run python3 tests/test_real.py
uv run python3 tests/test_e2e.py
uv run python3 tests/test_mock_conversation.py

# 清理
uv run python3 remote_claude.py kill test
```

### 快速回归测试

仅运行层 1 单元测试，快速验证核心逻辑：

```bash
uv run python3 tests/test_session_truncate.py && \
uv run python3 tests/test_runtime_config.py && \
echo "快速回归测试通过"
```

### shell 自适应与 POSIX sh 回归

| 场景 | 验证点 | 命令 |
|------|--------|------|
| rc 自适应选择 | zsh/bash/unknown shell 选择正确 rc | `uv run pytest tests/test_entry_lazy_init.py::test_get_shell_rc_prefers_zsh_when_shell_is_zsh -q` |
| init 幂等 | 重复执行不重复写块 | `uv run pytest tests/test_entry_lazy_init.py::test_upsert_rc_block_is_idempotent -q` |
| 脚本 shebang 统一 | 目标脚本均为 `#!/bin/sh` | `uv run pytest tests/test_entry_lazy_init.py::test_scripts_use_sh_shebang_for_all_shell_scripts -q` |
| 无 bash-only 语法残留 | `[[` 与 `#!/bin/bash` 被清理 | `uv run pytest tests/test_entry_lazy_init.py::test_shell_scripts_do_not_contain_bash_only_constructs -q` |
| 无显式 bash 内部调用 | 脚本互调不依赖 `bash` | `uv run pytest tests/test_entry_lazy_init.py::test_scripts_no_explicit_bash_invocation_for_internal_calls -q` |

### 安装可靠性回归

| 场景 | 验证点 | 命令 |
|------|--------|------|
| 安装失败日志落盘 | 失败后提示并可在 `/tmp/remote-claude-install.log` 定位阶段 | `uv run pytest tests/test_entry_lazy_init.py::test_install_sh_initializes_install_log_helpers -q` |
| pip 升级前置 | 安装 uv 前会先对最终选中的 pip 执行 `install --upgrade pip --user` | `uv run pytest tests/test_entry_lazy_init.py::test_install_uv_multi_source_upgrades_pip_before_uv_install -q` |
| 镜像与 trusted-host 一致性 | pip 升级与 uv/pip 安装共用内置镜像回退并附带 `--trusted-host` | `uv run pytest tests/test_entry_lazy_init.py::test_install_uv_multi_source_uses_trusted_host_for_all_pip_attempts -q` |
| 失败日志字段粒度（install-fail） | 安装步骤失败日志含 `stage/source/cmd/exit_code` 摘要 | `uv run pytest tests/test_entry_lazy_init.py::test_common_install_fail_summary_contains_required_fields -q` |
| 失败日志字段粒度（script-fail） | 脚本步骤失败日志含 `stage/source/cmd/exit_code` 摘要（含新加 script-fail 字段用例） | `uv run pytest tests/test_entry_lazy_init.py::test_common_script_fail_summary_contains_required_fields -q` |
| 补全路径一致 | setup 写入补全路径为 `scripts/completion.sh` | `uv run pytest tests/test_entry_lazy_init.py::test_setup_completion_uses_scripts_path -q` |
| runtime 成功时创建 | runtime 初始化逻辑位于成功主流程 | `uv run pytest tests/test_entry_lazy_init.py::test_setup_runtime_creation_stays_in_success_flow -q` |

---

## 特殊场景说明

### 配置文件损坏恢复

当 `runtime.json` 损坏时：
1. 系统自动备份损坏文件为 `runtime.json.bak`
2. 使用默认配置继续运行
3. 用户可手动恢复备份或重新配置

### 映射数量超限

当 `session_mappings` 超过 500 条时：
1. 系统输出警告日志
2. 新映射仍会保存（不阻塞）
3. 建议用户手动清理旧映射

### 快捷命令验证失败

当配置的快捷命令格式无效时：
- 不以 `/` 开头：跳过该命令，输出警告
- 包含空格：跳过该命令，输出警告
- 超长：跳过该命令，输出警告

---

## 回归防护清单

在修改以下模块时，必须运行对应测试：

| 修改模块 | 必须通过的测试 |
|---------|--------------|
| `utils/session.py` | `test_session_truncate.py` |
| `utils/runtime_config.py` | `test_runtime_config.py` |
| `lark_client/card_builder.py` | `test_stream_poller.py` |
| `lark_client/config.py` | 手动验证日志级别 |
| `server/parsers/*.py` | `test_component_parser.py` |
| `utils/protocol.py` | `test_integration.py` |
| `server/server.py` (HistoryBuffer) | `test_history_buffer.py` |

---

## 调试工具

### 捕获原始输出

```bash
uv run python3 lark_client/capture_output.py <会话名> [秒数]
```

### 查看共享内存快照

```bash
cat /tmp/remote-claude/<name>_messages.log | jq .
```

### 查看屏幕快照

```bash
# 启动时添加 --debug-screen
uv run python3 remote_claude.py start test --debug-screen
cat /tmp/remote-claude/test_screen.log
```
