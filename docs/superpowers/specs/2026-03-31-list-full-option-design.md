# list 命令 --full 选项 + shell 入口 help 参数设计

## 概述

1. 为 `remote-claude list` 命令添加 `--full` 选项，启用后显示完整会话名称，不进行截断
2. 为 `bin/remote-claude` 添加 `-h`/`--help` 参数处理，在 shell 层显示简明命令概览表格

## 需求一：list 命令 --full 选项

### 背景

当前 `list` 命令输出表格时，会话名称列被截断为最多 20 字符：
```python
name_display = session_name[:18] + ".." if len(session_name) > 20 else session_name
```

用户希望能够完整查看或复制会话名称。

### 命令行参数

```bash
remote-claude list [--full] [--remote --host HOST --token TOKEN]
```

- `--full`：可选布尔标志，启用后显示完整名称

### 行为差异

| 模式 | 名称列宽度 | 表格布局 |
|------|-----------|---------|
| 默认 | 最多 20 字符，超出显示 `..` | 固定宽度 |
| `--full` | 不限制，显示完整名称 | 动态宽度，根据最长名称调整 |

### 输出示例

**默认模式**：
```
类型     PID       tmux   名称                 原始路径
--------------------------------------------------------------------------------
claude   12345     是     my-session-name..   /path/to/project..
codex    67890     否     another-session..   /another/path..
--------------------------------------------------------------------------------
共 2 个会话
```

**`--full` 模式**：
```
类型     PID       tmux   名称                        原始路径
--------------------------------------------------------------------------------
claude   12345     是     my-session-name-very-long   /path/to/project
codex    67890     否     another-session             /another/path
--------------------------------------------------------------------------------
共 2 个会话
```

### 修改点

**文件**：`remote_claude.py`

1. **参数解析**（约第 1375 行）：添加 `--full` 参数
2. **`cmd_list` 函数**（约第 568-587 行）：根据 `args.full` 动态调整显示逻辑

---

## 需求二：shell 入口 -h/--help 参数

### 背景

当前 `bin/remote-claude` 没有在 shell 层处理 `-h`/`--help` 参数，所有参数都直接透传给 Python。用户希望在 shell 层就能快速查看命令概览，无需等待 Python 初始化。

### 命令行参数

```bash
remote-claude -h       # shell 层显示简明命令概览表格
remote-claude --help   # shell 层显示简明命令概览表格
```

- `-h` 或 `--help`：在 shell 层显示简明命令概览表格（不透传给 Python）

### 输出示例

```
Remote Claude - 双端共享 Claude CLI 工具

命令概览：
  命令        说明                     示例
  ───────────────────────────────────────────────────────────
  start       启动新会话               remote-claude start mywork
  attach      连接到会话               remote-claude attach mywork
  list        列出所有会话             remote-claude list
  kill        终止会话                 remote-claude kill mywork
  status      显示会话状态             remote-claude status mywork
  log         查看会话日志             remote-claude log mywork
  lark        飞书客户端管理           remote-claude lark start
  config      配置管理                 remote-claude config show
  connection  远程连接配置管理         remote-claude connection list
  token       Token 管理               remote-claude token generate mywork

选项：
  --remote    远程连接模式
  --host      远程服务器地址
  --token     认证令牌

更多信息请访问: https://github.com/anthropics/remote-claude
```

### 实现细节

**文件**：`bin/remote-claude`

在现有 `log` 和 `lark` 子命令处理之后、`_remote_claude_python` 调用之前添加：

```sh
# -h/--help：显示简明命令概览（在 shell 层处理，无需 Python 初始化）
case "${1:-}" in
    -h|--help)
        cat <<'EOF'
Remote Claude - 双端共享 Claude CLI 工具

命令概览：
  命令        说明                     示例
  ───────────────────────────────────────────────────────────
  start       启动新会话               remote-claude start mywork
  attach      连接到会话               remote-claude attach mywork
  list        列出所有会话             remote-claude list
  kill        终止会话                 remote-claude kill mywork
  status      显示会话状态             remote-claude status mywork
  log         查看会话日志             remote-claude log mywork
  lark        飞书客户端管理           remote-claude lark start
  config      配置管理                 remote-claude config show
  connection  远程连接配置管理         remote-claude connection list
  token       Token 管理               remote-claude token generate mywork

选项：
  --remote    远程连接模式
  --host      远程服务器地址
  --token     认证令牌

更多信息请运行: remote-claude --help
EOF
        exit 0
        ;;
esac
```

### 现有实现

快捷命令（`cla`, `cl`, `cx`, `cdx`）已通过 `scripts/_help.sh` 的 `_print_quick_help` 函数实现了 `-h`/`--help` 支持，显示快捷命令概览表格。本次只需为 `bin/remote-claude` 主命令添加 `help`/`-h` 支持。

### 注意事项

1. `-h` 和 `--help` 在 shell 层处理，无需等待 Python 初始化
2. 输出内容与 Python 端的帮助信息保持一致的结构
3. 快捷命令的 `-h`/`--help` 保持现有实现，显示快捷命令专用的概览表格

---

## 测试计划

### list --full 测试

1. **默认模式**：
   - 运行 `remote-claude list`
   - 验证名称列截断行为与之前一致

2. **--full 模式**：
   - 运行 `remote-claude list --full`
   - 验证名称列显示完整内容
   - 验证表格宽度正确调整

### help/-h 测试

1. **-h 选项**：
   - 运行 `remote-claude -h`
   - 验证输出简明命令概览表格

2. **--help 选项**：
   - 运行 `remote-claude --help`
   - 验证输出与 `-h` 相同

---

## 不在范围内

- `status` 命令：当前功能简单，待后续完善后再考虑添加 `--full` 选项
- 路径列截断：本次只处理名称列，路径列保持当前行为
