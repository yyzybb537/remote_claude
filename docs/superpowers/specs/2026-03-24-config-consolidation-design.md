# 配置归拢与 pnpm 兼容优化设计

## 背景

当前项目存在以下问题：
1. `package.json` 未配置 `pnpm.onlyBuiltDependencies`，pnpm 安装时可能跳过必要的构建脚本
2. `shared_memory_poller.py` 中有 4 个开关配置使用独立文件存储，与 `runtime_config` 架构不一致，增加了文件数量和维护复杂度
3. 缺少卸载脚本，无法清理安装时写入的符号链接和 shell 配置

## 目标

1. 添加 `pnpm.onlyBuiltDependencies` 配置，确保 pnpm 安装时正确执行初始化脚本
2. 将开关配置归拢到 `config.json` 和 `runtime.json`，减少文件数量
3. 新增 `uninstall.sh` 脚本，支持清理环境

## 设计方案

### 第一部分：pnpm.onlyBuiltDependencies 配置

**修改文件**：`package.json`

```json
{
  "scripts": {
    "preinstall": "sh scripts/preinstall.sh",
    "postinstall": "sh scripts/postinstall.sh",
    "preuninstall": "sh scripts/uninstall.sh"
  },
  "pnpm": {
    "onlyBuiltDependencies": []
  }
}
```

**说明**：
- 使用 `sh` 替代 `bash`，以兼容不同 shell 环境（zsh、fish 等）
- `sh` 是 POSIX 标准，所有 Unix 系统都有，脚本内部使用 shebang 指定实际解释器
- `pnpm.onlyBuiltDependencies: []` 告诉 pnpm 不要为任何依赖包执行构建脚本
- 这可以加速安装，特别是对于包含原生模块的依赖
- 同时 pnpm 仍会执行 `scripts.postinstall`，保持与 npm/yarn 一致的行为

### 第二部分：配置归拢

#### 2.1 数据结构变更

**config.json（用户配置）新增字段**：

```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": { ... },
    "notify": {
      "ready_enabled": true,
      "urgent_enabled": false
    },
    "bypass_enabled": false
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ui_settings.notify.ready_enabled` | bool | true | 就绪通知开关 |
| `ui_settings.notify.urgent_enabled` | bool | false | 加急通知开关 |
| `ui_settings.bypass_enabled` | bool | false | 新会话 bypass 开关 |

**runtime.json（运行时状态）新增字段**：

```json
{
  "version": "1.0",
  "uv_path": "...",
  "session_mappings": { ... },
  "lark_group_mappings": { ... },
  "ready_notify_count": 0
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ready_notify_count` | int | 0 | 全局就绪通知计数器 |

#### 2.2 代码变更

**utils/runtime_config.py**：

1. 新增 `NotifySettings` dataclass
2. 扩展 `UISettings` 类：添加 `notify` 和 `bypass_enabled` 字段
3. 扩展 `RuntimeConfig` 类：添加 `ready_notify_count` 字段
4. 新增迁移函数 `migrate_legacy_notify_settings()`
5. 新增访问函数：
   - `get_notify_ready_enabled() / set_notify_ready_enabled()`
   - `get_notify_urgent_enabled() / set_notify_urgent_enabled()`
   - `get_bypass_enabled() / set_bypass_enabled()`
   - `increment_ready_notify_count()`

**lark_client/shared_memory_poller.py**：

删除以下内容：
- 模块级常量：`_READY_COUNT_FILE`、`_NOTIFY_ENABLED_FILE`、`_URGENT_ENABLED_FILE`、`_BYPASS_ENABLED_FILE`
- 模块级变量：`_notify_enabled`、`_urgent_enabled`、`_bypass_enabled`
- 模块级函数：`_load_notify_enabled()`、`_save_notify_enabled()` 等
- 类方法：`get_notify_enabled()`、`set_notify_enabled()` 等 6 个方法

修改 `_update_ready_state()` 函数，改用 `runtime_config.get_notify_ready_enabled()`

**lark_client/lark_handler.py**：

修改开关访问代码，直接调用 `runtime_config` 函数：

```python
from utils.runtime_config import (
    get_notify_ready_enabled, set_notify_ready_enabled,
    get_notify_urgent_enabled, set_notify_urgent_enabled,
    get_bypass_enabled, set_bypass_enabled,
)

# 原调用：self._poller.get_notify_enabled()
# 新调用：get_notify_ready_enabled()
```

#### 2.3 迁移策略

**双路径迁移**：init.sh（shell 层）+ runtime_config.py（Python 层）

**init.sh 迁移逻辑**（添加到 `init_config_files()` 函数）：

```bash
# 4. 迁移旧开关文件到 config.json 和 runtime.json
local LEGACY_NOTIFY_COUNT="$USER_DATA_DIR/ready_notify_count"
local LEGACY_NOTIFY_ENABLED="$USER_DATA_DIR/ready_notify_enabled"
local LEGACY_URGENT_ENABLED="$USER_DATA_DIR/urgent_notify_enabled"
local LEGACY_BYPASS_ENABLED="$USER_DATA_DIR/bypass_enabled"

if [ -f "$LEGACY_NOTIFY_COUNT" ] || [ -f "$LEGACY_NOTIFY_ENABLED" ] || \
   [ -f "$LEGACY_URGENT_ENABLED" ] || [ -f "$LEGACY_BYPASS_ENABLED" ]; then
    print_info "检测到旧开关文件，正在迁移..."

    if command -v jq &> /dev/null; then
        # 迁移 ready_notify_count 到 runtime.json
        if [ -f "$LEGACY_NOTIFY_COUNT" ]; then
            local count=$(cat "$LEGACY_NOTIFY_COUNT" 2>/dev/null)
            if [[ "$count" =~ ^[0-9]+$ ]]; then
                jq --argjson count "$count" '.ready_notify_count = $count' \
                    "$RUNTIME_FILE" > "$RUNTIME_FILE.tmp"
                mv "$RUNTIME_FILE.tmp" "$RUNTIME_FILE"
                rm -f "$LEGACY_NOTIFY_COUNT"
                print_success "已迁移 ready_notify_count 到 runtime.json (count=$count)"
            else
                rm -f "$LEGACY_NOTIFY_COUNT"
                print_warning "ready_notify_count 内容无效，已删除"
            fi
        fi

        # 迁移开关到 config.json 的 ui_settings
        local notify_ready=true
        local notify_urgent=false
        local bypass=false

        [ -f "$LEGACY_NOTIFY_ENABLED" ] && {
            [[ "$(cat "$LEGACY_NOTIFY_ENABLED")" == "1" ]] && notify_ready=true || notify_ready=false
            rm -f "$LEGACY_NOTIFY_ENABLED"
        }
        [ -f "$LEGACY_URGENT_ENABLED" ] && {
            [[ "$(cat "$LEGACY_URGENT_ENABLED")" == "1" ]] && notify_urgent=true || notify_urgent=false
            rm -f "$LEGACY_URGENT_ENABLED"
        }
        [ -f "$LEGACY_BYPASS_ENABLED" ] && {
            [[ "$(cat "$LEGACY_BYPASS_ENABLED")" == "1" ]] && bypass=true || bypass=false
            rm -f "$LEGACY_BYPASS_ENABLED"
        }

        # 更新 config.json
        jq --argjson ready "$notify_ready" --argjson urgent "$notify_urgent" \
            --argjson bypass "$bypass" \
            '.ui_settings.notify = {"ready_enabled": $ready, "urgent_enabled": $urgent} | .ui_settings.bypass_enabled = $bypass' \
            "$CONFIG_FILE" > "$CONFIG_FILE.tmp"
        mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"

        print_success "已迁移开关设置到 config.json"
    else
        print_warning "未安装 jq，跳过自动迁移（程序启动时会自动迁移）"
    fi
fi
```

**Python 迁移逻辑**（`runtime_config.py` 中的 `migrate_legacy_notify_settings()`）：

- 处理没有 jq 的情况
- 处理直接通过 `uv run` 启动的场景
- 迁移完成后删除旧文件

#### 2.4 文件清理

迁移完成后删除以下旧文件：
- `~/.remote-claude/ready_notify_count`
- `~/.remote-claude/ready_notify_enabled`
- `~/.remote-claude/urgent_notify_enabled`
- `~/.remote-claude/bypass_enabled`

### 第三部分：uninstall.sh

#### 3.1 功能清单

| 清理项 | 类型 | 处理方式 |
|--------|------|----------|
| 飞书客户端 | 进程 | 停止守护进程 |
| 活跃会话 | 进程 | 终止所有 tmux 会话 |
| `/tmp/remote-claude/` | 目录 | 删除 |
| `/usr/local/bin/cla` | 符号链接 | 删除 |
| `/usr/local/bin/cl` | 符号链接 | 删除 |
| `/usr/local/bin/cx` | 符号链接 | 删除 |
| `/usr/local/bin/cdx` | 符号链接 | 删除 |
| `/usr/local/bin/remote-claude` | 符号链接 | 删除 |
| `~/bin/` 中的链接 | 符号链接 | 删除（如存在） |
| `~/.local/bin/` 中的链接 | 符号链接 | 删除（如存在） |
| `~/.bashrc` PATH 行 | 文件修改 | 移除 remote-claude 相关注释行 |
| `~/.zshrc` PATH 行 | 文件修改 | 移除 remote-claude 相关注释行 |
| `~/.bash_profile` PATH 行 | 文件修改 | 移除 remote-claude 相关注释行 |
| `~/.bashrc` completion 行 | 文件修改 | 移除 source completion.sh 行 |
| `~/.remote-claude/` | 目录 | 询问用户是否删除 |

#### 3.2 package.json 配置

```json
{
  "scripts": {
    "preuninstall": "sh scripts/uninstall.sh"
  }
}
```

**说明**：
- npm 和 pnpm 都支持 `preuninstall` 钩子
- 使用 `sh` 替代 `bash`，兼容不同 shell 环境
- 在包被移除前执行清理

#### 3.3 核心逻辑

```bash
#!/bin/bash
# Remote Claude 卸载脚本

# 1. 停止服务
stop_lark_client
stop_all_sessions

# 2. 清理符号链接
remove_symlinks

# 3. 清理 shell 配置
cleanup_shell_config

# 4. 清理临时目录
rm -rf /tmp/remote-claude/

# 5. 询问用户是否删除配置目录
ask_delete_config_dir
```

## 变更清单

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `package.json` | 修改 | 添加 `pnpm.onlyBuiltDependencies` 和 `preuninstall` 脚本 |
| `utils/runtime_config.py` | 新增 | `NotifySettings` dataclass |
| `utils/runtime_config.py` | 修改 | `UISettings` 添加 `notify` 和 `bypass_enabled` |
| `utils/runtime_config.py` | 修改 | `RuntimeConfig` 添加 `ready_notify_count` |
| `utils/runtime_config.py` | 新增 | 迁移函数和访问函数 |
| `lark_client/shared_memory_poller.py` | 删除 | 开关相关的常量、变量、函数、方法 |
| `lark_client/shared_memory_poller.py` | 修改 | `_update_ready_state()` 改用 runtime_config |
| `lark_client/lark_handler.py` | 修改 | 开关访问改为直接调用 runtime_config 函数 |
| `init.sh` | 修改 | 添加开关文件迁移逻辑 |
| `scripts/uninstall.sh` | 新增 | 卸载脚本 |
| `resources/defaults/config.default.json` | 修改 | 添加 `notify` 和 `bypass_enabled` 默认值 |
| `resources/defaults/runtime.default.json` | 修改 | 添加 `ready_notify_count` 默认值 |

## 兼容性

- **npm**: 支持 `preinstall`、`postinstall`、`preuninstall`
- **yarn**: 支持 `preinstall`、`postinstall`、`preuninstall`
- **pnpm**: 支持 `preinstall`、`postinstall`、`preuninstall`，同时识别 `pnpm.onlyBuiltDependencies`

## 测试要点

1. **pnpm 安装测试**：验证 `postinstall` 正确执行
2. **迁移测试**：验证旧文件正确迁移到新配置
3. **卸载测试**：验证符号链接和 shell 配置正确清理
4. **兼容性测试**：验证 npm/yarn/pnpm 行为一致
