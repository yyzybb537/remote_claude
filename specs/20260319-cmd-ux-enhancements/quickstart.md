# Quickstart: 命令行与飞书用户体验增强

**Feature**: `20260319-cmd-ux-enhancements`
**Date**: 2026-03-19

## 概述

本文档提供本功能的快速使用指南，帮助用户快速上手新增功能。

**⚠️ 重要变更（2026-03-19）**：
- 配置文件拆分为 `config.json`（用户配置）和 `runtime.json`（程序状态）
- `list` 命令展示原始路径
- 会话退出时自动清理映射
- 配置迁移后自动清理 bak 文件

---

## 1. 会话名称自动截断

### 使用场景

当工作目录路径过长导致 socket 路径超出系统限制时，系统自动截断名称。

### 快速验证

```bash
# 创建超长路径
mkdir -p /tmp/very/long/path/that/exceeds/the/maximum/socket/path/length/limit/test/project

# 进入目录并启动会话
cd /tmp/very/long/path/that/exceeds/the/maximum/socket/path/length/limit/test/project
uv run python3 remote_claude.py start .

# 验证：会话正常启动，无报错
uv run python3 remote_claude.py list
```

### 查看映射

```bash
# 查看截断名称与原始路径的映射（runtime.json 存储程序状态）
cat ~/.remote-claude/runtime.json | grep session_mappings -A 5
```

---

## 2. List 命令增强展示

### 使用方式

```bash
uv run python3 remote_claude.py list
```

### 输出格式

```
会话列表:
名称                  原始路径                                          状态
myapp_src_comp   →   /Users/dev/projects/myapp/src/components         运行中
test_session     →   /path/to/test                                     已停止
simple_name      →   -                                                 运行中
```

- **截断名称**：自动生成的短名称
- **原始路径**：从 `runtime.json` 反查，无映射显示 `-`
- **状态**：运行中/已停止

---

## 3. 飞书快捷命令选择器

### 启用步骤

1. 编辑用户配置文件：

```bash
vim ~/.remote-claude/config.json
```

2. 配置快捷命令：

```json
{
  "ui_settings": {
    "quick_commands": {
      "enabled": true,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
        {"label": "退出会话", "value": "/exit", "icon": "🚪"},
        {"label": "帮助", "value": "/help", "icon": "❓"}
      ]
    }
  }
}
```

3. 重启飞书客户端：

```bash
uv run python3 remote_claude.py lark restart
```

### 使用流程

1. 在飞书中打开已连接会话的聊天
2. 查看卡片底部菜单区域
3. 点击"快捷命令"下拉框
4. 选择命令后自动发送

### 自定义命令

支持添加任意无参数命令：

```json
{
  "label": "查看状态",
  "value": "/status",
  "icon": "📊"
}
```

**注意**：不支持带参数的命令（如 `/attach <session>`）。

---

## 4. 默认日志级别

### 行为变更

- **之前**：默认日志级别 INFO，输出较多调试信息
- **现在**：默认日志级别 WARNING，只输出警告和错误

### 调整日志级别

如需调试，设置环境变量：

```bash
# 启用 DEBUG 日志
export LARK_LOG_LEVEL=DEBUG
uv run python3 remote_claude.py lark restart

# 或启用 INFO 日志
export LARK_LOG_LEVEL=INFO
uv run python3 remote_claude.py lark restart
```

---

## 5. Help 参数行为

### 验证方式

```bash
# 主命令帮助
uv run python3 remote_claude.py --help

# 子命令帮助（不执行实际操作）
uv run python3 remote_claude.py start --help
uv run python3 remote_claude.py attach --help
uv run python3 remote_claude.py lark --help
uv run python3 remote_claude.py lark status --help
```

### 预期行为

- 只显示帮助信息
- 不执行任何实际操作
- 不输出"会话不存在"等错误信息

---

## 6. 会话退出清理

### 行为说明

当会话退出（kill 或 exit）时：
- `session_mappings` 中对应映射自动删除
- `lark_group_mappings` 保留（便于重新连接）

### 验证方式

```bash
# 启动会话
uv run python3 remote_claude.py start test_session

# 查看映射
cat ~/.remote-claude/runtime.json | grep session_mappings

# 退出会话
uv run python3 remote_claude.py kill test_session

# 确认映射已删除
cat ~/.remote-claude/runtime.json | grep session_mappings
```

---

## 7. 飞书卡片交互优化

### 功能说明

当用户在飞书卡片中进行交互操作（按钮点击、文本提交）时，卡片会就地更新而非推送新卡片，提升体验流畅度。

### 交互流程

```
用户点击按钮 → 按钮变为 disabled → 显示"处理中..." → 操作完成 → 卡片更新结果
```

### 支持的交互类型

| 交互类型 | 行为 |
|----------|------|
| 快捷命令选择 | 选择后就地更新卡片状态 |
| 选项按钮（Yes/No） | 点击后就地更新显示选择结果 |
| 菜单按钮 | 操作后就地更新显示菜单结果 |
| 文本输入提交 | 提交后就地更新显示输入结果 |

### 视觉反馈

交互过程中卡片会显示状态变化：
- 按钮 disabled（防止重复点击）
- 显示"处理中..."等提示文本
- 操作完成后恢复正常状态

---

## 8. 飞书卡片回车自动确认

### 功能说明

单行文本输入框支持回车键自动提交，无需手动点击确认按钮，提升输入效率。

### 使用方式

1. 在飞书卡片底部的消息输入框中输入内容
2. 按回车键自动提交
3. 无需点击"发送"按钮

### 支持范围

| 输入框类型 | 回车行为 |
|------------|----------|
| 单行输入框 | 触发提交 |
| 多行输入框 | 换行（不提交） |

### 注意事项

- 空输入不会触发提交
- 移动端飞书客户端（无物理回车键）仍可点击确认按钮提交
- 多行文本框中回车键用于换行，需点击按钮提交

---

## 配置文件说明

### 文件结构

```
~/.remote-claude/
├── config.json          # 用户配置（可手动编辑）
│   └── ui_settings.quick_commands
├── runtime.json         # 程序状态（自动管理）
│   ├── session_mappings
│   └── lark_group_mappings
└── runtime.json.lock    # 文件锁（写入时临时创建）
```

### config.json（用户配置）

用户可手动编辑此文件，包含：
- `ui_settings.quick_commands`：快捷命令配置

### runtime.json（程序状态）

程序自动管理，包含：
- `session_mappings`：会话名称映射
- `lark_group_mappings`：飞书群组绑定

---

## 配置迁移

### 从 lark_group_mapping.json 迁移

如果之前使用 `lark_group_mapping.json` 配置群组映射：

```bash
uv run python3 remote_claude.py lark start
# 日志输出: [迁移] 已将 lark_group_mapping.json 迁移到 runtime.json
```

> **注意**：`config.json` 和 `runtime.json` 均为全新配置文件，无需从旧版本迁移。

### 手动检查

```bash
# 确认配置已拆分
ls ~/.remote-claude/
# 输出应包含: config.json  runtime.json

# 检查用户配置
cat ~/.remote-claude/config.json

# 检查运行时状态
cat ~/.remote-claude/runtime.json
```

---

## 文件锁说明

### 锁文件位置

`~/.remote-claude/runtime.json.lock`

### 锁文件内容示例

```
# Remote Claude 配置文件锁
# 用途: 防止并发写入导致配置损坏
# 创建进程 PID: 12345
# 创建时间: 2026-03-19T14:30:00+08:00
# 说明: 此文件在配置写入时自动创建，写入完成后自动删除
#       如果程序异常退出，此文件可能残留，可安全删除
```

### 注意事项

- 正常情况下锁文件不会长期存在
- 如果程序异常退出，锁文件可能残留
- 残留的锁文件可以安全删除

---

## 故障排查

### 会话启动失败

**症状**：启动会话时报错 "socket path too long"

**解决**：
1. 确认已更新到包含本功能的版本
2. 检查 `runtime.json` 是否可写
3. 查看日志：`tail -f ~/.remote-claude/lark_client.log`

### 空会话名拒绝

**症状**：启动会话时报错 "会话名不能为空"

**解决**：
提供有效的会话名称：
```bash
# 错误
uv run python3 remote_claude.py start ""

# 正确
uv run python3 remote_claude.py start my_session
```

### 配置目录只读

**症状**：启动时警告 "配置目录权限不足，配置将仅在内存中保留"

**说明**：系统会使用内存配置继续运行，当前会话正常工作，但配置不会持久化。

**解决**：
```bash
# 检查目录权限
ls -la ~/.remote-claude/

# 修改权限
chmod u+w ~/.remote-claude/
```

### 快捷命令不显示

**症状**：卡片底部没有快捷命令下拉框

**排查步骤**：
1. 检查 `config.json` 配置：`enabled` 是否为 `true`
2. 检查命令列表：`commands` 是否非空
3. 检查会话状态：是否已连接（断开时不显示）
4. 重启飞书客户端

### 配置文件损坏

**症状**：启动时报错 "JSON decode error"

**解决**：
1. 查找备份文件：`ls ~/.remote-claude/*.json.bak.*`
2. 系统自动保留最近 2 个备份文件
3. 恢复备份：
   - `config.json`: `cp ~/.remote-claude/config.json.bak.<timestamp> ~/.remote-claude/config.json`
   - `runtime.json`: `cp ~/.remote-claude/runtime.json.bak.<timestamp> ~/.remote-claude/runtime.json`
4. 如无备份，删除后重新启动会自动创建默认配置

### 锁文件残留

**症状**：配置无法保存，提示锁文件存在

**解决**：
```bash
# 检查是否有其他进程正在写入
lsof ~/.remote-claude/runtime.json.lock

# 如果无进程占用，可安全删除
rm ~/.remote-claude/runtime.json.lock
```

### bak 文件残留

**症状**：启动时提示"检测到残留的备份文件"

**处理方式**：

系统会提示选择：
```
检测到残留的备份文件: ~/.remote-claude/runtime.json.bak.20260319_143000
1. 覆盖当前配置并重新迁移
2. 跳过（删除备份文件继续）
请选择 [1/2]:
```

- **选择 1**：从 bak 文件恢复配置，删除当前文件
- **选择 2**：删除 bak 文件，使用当前配置继续

**背景**：程序异常退出时可能残留 bak 文件，正常迁移完成后会自动删除。

### 文档与实现不一致

**症状**：README.md 或 CLAUDE.md 中的配置说明与实际不符

**解决**：
```bash
# 检查当前配置文件结构
ls -la ~/.remote-claude/

# 应看到：
# config.json      - 用户配置（可手动编辑）
# runtime.json     - 程序状态（自动管理）
# runtime.json.lock - 文件锁（临时）
```

### 无效日志级别

**症状**：日志显示"无效的日志级别 'XXX'，回退到默认值 WARNING"

**说明**：用户设置了无效的 `LARK_LOG_LEVEL` 环境变量，系统自动回退到默认值 WARNING。

**解决**：
```bash
# 设置有效日志级别
export LARK_LOG_LEVEL=DEBUG  # 或 INFO / WARNING / ERROR

# 重启飞书客户端
uv run python3 remote_claude.py lark restart
```

### 快捷命令发送时提示"会话已断开"

**症状**：选择快捷命令后提示"会话已断开，请重新连接后重试"

**原因**：会话已断开（socket 连接丢失）

**解决**：
1. 检查会话状态：`uv run python3 remote_claude.py list`
2. 如果会话已停止，重新启动：`uv run python3 remote_claude.py start <session_name>`
3. 在飞书中重新连接会话

**注意**：disconnected 状态为实时检测（直接检查连接状态），无延迟。
