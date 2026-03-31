# 配置与文档重构设计

**日期**: 2026-03-31
**状态**: 设计确认

## 概述

本次重构包含三个独立模块：

1. **快捷命令帮助**：统一概览表格替代重定向
2. **配置结构**：按功能域扁平化分组
3. **README 精简**：内容收敛至 docs/

---

## 第一部分：快捷命令帮助概览

### 当前问题

`cla`/`cl`/`cx`/`cdx` 的 `-h/--help` 重定向到 `remote-claude start --help`，用户无法快速了解所有快捷命令的功能差异。

### 设计方案

在 `scripts/_help.sh` 中创建共享帮助输出函数，各 bin 脚本调用后输出统一表格。

### 输出格式

```
Remote Claude 快捷命令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
命令   CLI      权限模式          用途
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cla    Claude   正常（需确认）    启动 Claude 会话
cl     Claude   跳过权限确认      快速启动 Claude 会话
cx     Codex    跳过权限确认      快速启动 Codex 会话
cdx    Codex    正常（需确认）    启动 Codex 会话
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

会话命名：当前目录路径 + 时间戳
示例：/Users/foo/project_0331_142500

更多信息: remote-claude --help
```

### 实现要点

1. 创建 `scripts/_help.sh`，定义 `_print_quick_help()` 函数
2. 修改 `bin/cla`、`bin/cl`、`bin/cx`、`bin/cdx` 的 `-h/--help` 分支，调用共享函数
3. 使用 ANSI 颜色和 Unicode 边框字符，保持与项目风格一致

---

## 第二部分：配置结构重构

### 当前结构

```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {...},
    "notify": {...},
    "bypass_enabled": false,
    "custom_commands": {...},
    "auto_answer": {...},
    "card_expiry": {...},
    "operation_panel": {...}
  }
}
```

### 问题

- `ui_settings` 嵌套过深，语义不清晰
- 配置项按历史演进堆叠，缺乏逻辑分组

### 新结构

```json
{
  "version": "2.0",
  "card": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"}
      ]
    },
    "expiry": {
      "enabled": true,
      "expiry_seconds": 3600
    }
  },
  "session": {
    "bypass": false,
    "custom_commands": {
      "enabled": true,
      "commands": [
        {"name": "Claude", "cli_type": "claude", "command": "claude"},
        {"name": "Codex", "cli_type": "codex", "command": "codex"}
      ]
    }
  },
  "behavior": {
    "auto_answer": {
      "default_delay_seconds": 10,
      "vague_commands": ["继续执行", "继续", "开始"],
      "vague_command_prompt": "..."
    },
    "notify": {
      "ready_enabled": true,
      "urgent_enabled": false
    },
    "operation_panel": {
      "show_builtin_keys": true,
      "show_custom_commands": true,
      "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc"]
    }
  }
}
```

### 分组逻辑

| 原配置路径 | 新配置路径 | 分组理由 |
|-----------|-----------|---------|
| `ui_settings.quick_commands` | `card.quick_commands` | 飞书卡片快捷按钮 |
| `ui_settings.card_expiry` | `card.expiry` | 飞书卡片过期控制 |
| `ui_settings.bypass_enabled` | `session.bypass` | 会话启动权限模式 |
| `ui_settings.custom_commands` | `session.custom_commands` | 会话 CLI 类型配置 |
| `ui_settings.auto_answer` | `behavior.auto_answer` | 运行时自动应答行为 |
| `ui_settings.notify` | `behavior.notify` | 运行时通知行为 |
| `ui_settings.operation_panel` | `behavior.operation_panel` | 飞书操作面板行为 |

### 代码改动

1. **数据类重构** (`utils/runtime_config.py`)：
   - 新增 `CardConfig`、`SessionConfig`、`BehaviorConfig` 数据类
   - `UserConfig` 从包含 `UISettings` 改为包含三个顶层配置类
   - 删除 `UISettings` 类

2. **API 函数重命名**：
   - `get_quick_commands()` → `get_card_quick_commands()`
   - `is_quick_commands_visible()` → `is_card_quick_commands_visible()`
   - `get_notify_ready_enabled()` → `get_behavior_notify_ready_enabled()`
   - 其他函数按新分组重命名

3. **版本号升级**：
   - `USER_CONFIG_VERSION` 从 `1.0` 升级到 `2.0`
   - 旧配置文件读取时输出警告，提示用户手动迁移或删除

4. **默认配置更新**：
   - `resources/defaults/config.default.json` 使用新结构

### 迁移策略

**不提供自动迁移**。原因：
- 用户配置文件通常改动较少
- 迁移代码增加维护成本
- 用户删除旧配置后重新生成更干净

用户处理方式：
1. 删除 `~/.remote-claude/config.json`
2. 重新启动会话，自动生成新格式配置
3. 手动调整个性化设置

---

## 第三部分：README 精简与文档重组

### 目标

- README.md 精简到 ~100 行
- 保留核心价值：功能介绍 + 安装 + 基本命令
- 详细内容移至 docs/ 目录

### 文档重组计划

| 原位置 | 新位置 | 内容 |
|--------|--------|------|
| README.md (配置章节) | `docs/configuration.md` | 完整配置说明 |
| README.md (飞书配置) | `docs/feishu-setup.md` | 飞书机器人配置教程 |
| README.md (远程连接) | `docs/remote-connection.md` | 远程连接详细说明 |
| README.md (管理命令) | `docs/cli-reference.md` | 完整 CLI 命令参考 |
| `lark_client/README.md` | `docs/feishu-client.md` | 飞书客户端管理指南 |
| `docker/README.md` | `docs/docker-test.md` | Docker 测试说明 |

### 新 README 结构

```markdown
# Remote Claude

一句话定位（~20 字）

## 为什么需要它？
- 3 个核心优势（~50 字）

## 快速开始

### 安装
3 种安装方式（~30 字）

### 启动
快捷命令表格（~50 字）

### 从其他终端连接
2 个命令（~20 字）

## 飞书客户端
简短说明 + 链接（~30 字）

## 更多文档
链接列表（~20 字）
```

### 删除的文件

- `lark_client/README.md` → 移至 `docs/feishu-client.md`
- `docker/README.md` → 移至 `docs/docker-test.md`

---

## 实现顺序

1. **配置结构重构**：先改代码，再更新默认配置
2. **快捷命令帮助**：创建共享脚本，修改 bin 脚本
3. **文档重组**：创建 docs/ 文件，更新 README.md

---

## 验收标准

1. `cla -h` 显示快捷命令概览表格
2. `config.default.json` 使用新的扁平化结构
3. 代码中无 `ui_settings` 相关引用
4. README.md 行数 ≤ 120 行
5. docs/ 目录包含所有详细文档
