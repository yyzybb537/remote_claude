# 配置归拢与 pnpm 兼容优化实现计划

## 概述

本文档描述配置归拢与 pnpm 兼容优化的详细实现步骤。工程师应按任务顺序执行，每个任务独立可测试。

**设计文档**：`docs/superpowers/specs/2026-03-24-config-consolidation-design.md`

---

## 任务列表

### 任务 1：修改 package.json 的 pnpm 配置

**目标**：配置 pnpm 允许执行项目自身的生命周期脚本

**背景**：pnpm v10 默认阻止所有生命周期脚本执行（包括项目自身的 `postinstall`）。需要在 `onlyBuiltDependencies` 中显式声明允许执行脚本的包名。

**文件**：
- `package.json`

**package.json 变更内容**：

```json
{
  "scripts": {
    "preinstall": "sh scripts/preinstall.sh",
    "postinstall": "sh scripts/postinstall.sh",
    "preuninstall": "sh scripts/uninstall.sh"
  },
  "pnpm": {
    "onlyBuiltDependencies": ["remote-claude"]
  }
}
```

**说明**：
- 使用 `sh` 替代 `bash`，兼容不同 shell 环境（zsh、fish 等）
- `sh` 是 POSIX 标准，脚本内部通过 shebang 指定实际解释器
- `onlyBuiltDependencies: ["remote-claude"]` 告诉 pnpm 允许 `remote-claude` 包执行生命周期脚本
- 注意：`onlyBuiltDependencies` 需要填写**包名**（package.json 中的 `name` 字段），不是文件路径

**验证**：
- `pnpm install` 能正确执行 `postinstall` 脚本
- `pnpm install` 不再显示 "Ignored build scripts" 警告
- `npm install` 能正确执行 `postinstall`
- `pnpm uninstall` 能触发 `preuninstall`
- `npm uninstall` 能触发 `preuninstall`

**参考资料**：
- [pnpm onlyBuiltDependencies 文档](https://pnpm.io/package-json#pnpmonlybuiltdependencies)
- [pnpm v10 供应链安全](https://pnpm.io/supply-chain-security)

---

### 任务 2：扩展 runtime_config.py 数据类

**目标**：添加通知设置相关的数据类

**文件**：`utils/runtime_config.py`

**变更内容**：

1. 新增 `NotifySettings` dataclass（在 `QuickCommandsConfig` 后面）：

```python
@dataclass
class NotifySettings:
    """通知设置"""
    ready_enabled: bool = True      # 就绪通知开关（默认开启）
    urgent_enabled: bool = False    # 加急通知开关（默认关闭）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready_enabled": self.ready_enabled,
            "urgent_enabled": self.urgent_enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotifySettings":
        return cls(
            ready_enabled=data.get("ready_enabled", True),
            urgent_enabled=data.get("urgent_enabled", False),
        )
```

2. 扩展 `UISettings` 类（添加 `notify` 和 `bypass_enabled` 字段）：

```python
@dataclass
class UISettings:
    """UI 设置"""
    quick_commands: QuickCommandsConfig = field(default_factory=lambda: QuickCommandsConfig())
    notify: NotifySettings = field(default_factory=lambda: NotifySettings())
    bypass_enabled: bool = False  # 新会话 bypass 开关

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quick_commands": self.quick_commands.to_dict(),
            "notify": self.notify.to_dict(),
            "bypass_enabled": self.bypass_enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UISettings":
        qc_data = data.get("quick_commands", {})
        notify_data = data.get("notify", {})
        return cls(
            quick_commands=QuickCommandsConfig.from_dict(qc_data),
            notify=NotifySettings.from_dict(notify_data),
            bypass_enabled=data.get("bypass_enabled", False),
        )
```

3. 扩展 `RuntimeConfig` 类（添加 `ready_notify_count` 字段）：

在 `RuntimeConfig` 类中添加字段：
```python
ready_notify_count: int = 0  # 全局就绪通知计数器
```

更新 `to_dict()` 方法：
```python
"ready_notify_count": self.ready_notify_count,
```

更新 `from_dict()` 方法：
```python
ready_notify_count=data.get("ready_notify_count", 0),
```

**验证**：
- 运行 `uv run python3 -c "from utils.runtime_config import NotifySettings, UISettings, RuntimeConfig; ..."`
- 验证序列化/反序列化正确

---

### 任务 3：添加迁移函数到 runtime_config.py

**目标**：实现旧文件迁移逻辑

**文件**：`utils/runtime_config.py`

**变更内容**：

1. 添加旧文件路径常量（在模块级常量区域）：

```python
# 旧开关文件路径
LEGACY_NOTIFY_COUNT_FILE = USER_DATA_DIR / "ready_notify_count"
LEGACY_NOTIFY_ENABLED_FILE = USER_DATA_DIR / "ready_notify_enabled"
LEGACY_URGENT_ENABLED_FILE = USER_DATA_DIR / "urgent_notify_enabled"
LEGACY_BYPASS_ENABLED_FILE = USER_DATA_DIR / "bypass_enabled"
```

2. 添加迁移函数（在 `migrate_legacy_config()` 后面）：

```python
def migrate_legacy_notify_settings() -> None:
    """迁移旧开关文件到 config.json 和 runtime.json

    处理以下旧文件：
    - ready_notify_count -> runtime.json
    - ready_notify_enabled -> config.json (ui_settings.notify.ready_enabled)
    - urgent_notify_enabled -> config.json (ui_settings.notify.urgent_enabled)
    - bypass_enabled -> config.json (ui_settings.bypass_enabled)

    迁移完成后删除旧文件。
    """
    legacy_files = [
        LEGACY_NOTIFY_COUNT_FILE,
        LEGACY_NOTIFY_ENABLED_FILE,
        LEGACY_URGENT_ENABLED_FILE,
        LEGACY_BYPASS_ENABLED_FILE,
    ]

    # 检查是否有旧文件需要迁移
    if not any(f.exists() for f in legacy_files):
        return

    logger.info("[迁移] 检测到旧开关文件，正在迁移...")

    # 迁移 ready_notify_count 到 runtime.json
    if LEGACY_NOTIFY_COUNT_FILE.exists():
        try:
            count_str = LEGACY_NOTIFY_COUNT_FILE.read_text().strip()
            count = int(count_str)
            runtime_config = load_runtime_config()
            runtime_config.ready_notify_count = count
            save_runtime_config(runtime_config)
            LEGACY_NOTIFY_COUNT_FILE.unlink()
            logger.info(f"[迁移] ready_notify_count -> runtime.json (count={count})")
        except ValueError:
            logger.warning(f"[迁移] ready_notify_count 内容无效: {count_str}")
            LEGACY_NOTIFY_COUNT_FILE.unlink()
        except Exception as e:
            logger.warning(f"[迁移] ready_notify_count 迁移失败: {e}")

    # 迁移开关到 config.json
    user_config = load_user_config()

    if LEGACY_NOTIFY_ENABLED_FILE.exists():
        try:
            val = LEGACY_NOTIFY_ENABLED_FILE.read_text().strip()
            user_config.ui_settings.notify.ready_enabled = (val == "1")
            LEGACY_NOTIFY_ENABLED_FILE.unlink()
            logger.info(f"[迁移] ready_notify_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] ready_notify_enabled 迁移失败: {e}")
            LEGACY_NOTIFY_ENABLED_FILE.unlink()

    if LEGACY_URGENT_ENABLED_FILE.exists():
        try:
            val = LEGACY_URGENT_ENABLED_FILE.read_text().strip()
            user_config.ui_settings.notify.urgent_enabled = (val == "1")
            LEGACY_URGENT_ENABLED_FILE.unlink()
            logger.info(f"[迁移] urgent_notify_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] urgent_notify_enabled 迁移失败: {e}")
            LEGACY_URGENT_ENABLED_FILE.unlink()

    if LEGACY_BYPASS_ENABLED_FILE.exists():
        try:
            val = LEGACY_BYPASS_ENABLED_FILE.read_text().strip()
            user_config.ui_settings.bypass_enabled = (val == "1")
            LEGACY_BYPASS_ENABLED_FILE.unlink()
            logger.info(f"[迁移] bypass_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] bypass_enabled 迁移失败: {e}")
            LEGACY_BYPASS_ENABLED_FILE.unlink()

    save_user_config(user_config)
    logger.info("[迁移] 开关设置迁移完成")
```

**验证**：
- 创建旧文件后运行迁移，验证数据正确迁移
- 验证旧文件被删除

---

### 任务 4：添加访问函数到 runtime_config.py

**目标**：提供便捷的配置访问接口

**文件**：`utils/runtime_config.py`

**变更内容**（在文件末尾添加）：

```python
# ============== 通知设置访问函数 ==============

def get_notify_ready_enabled() -> bool:
    """获取就绪通知开关状态"""
    config = load_user_config()
    return config.ui_settings.notify.ready_enabled


def set_notify_ready_enabled(enabled: bool) -> None:
    """设置就绪通知开关状态"""
    config = load_user_config()
    config.ui_settings.notify.ready_enabled = enabled
    save_user_config(config)
    logger.info(f"就绪通知开关已{'开启' if enabled else '关闭'}")


def get_notify_urgent_enabled() -> bool:
    """获取加急通知开关状态"""
    config = load_user_config()
    return config.ui_settings.notify.urgent_enabled


def set_notify_urgent_enabled(enabled: bool) -> None:
    """设置加急通知开关状态"""
    config = load_user_config()
    config.ui_settings.notify.urgent_enabled = enabled
    save_user_config(config)
    logger.info(f"加急通知开关已{'开启' if enabled else '关闭'}")


def get_bypass_enabled() -> bool:
    """获取新会话 bypass 开关状态"""
    config = load_user_config()
    return config.ui_settings.bypass_enabled


def set_bypass_enabled(enabled: bool) -> None:
    """设置新会话 bypass 开关状态"""
    config = load_user_config()
    config.ui_settings.bypass_enabled = enabled
    save_user_config(config)
    logger.info(f"新会话 bypass 开关已{'开启' if enabled else '关闭'}")


def get_ready_notify_count() -> int:
    """获取就绪通知计数"""
    config = load_runtime_config()
    return config.ready_notify_count


def increment_ready_notify_count() -> int:
    """原子递增就绪通知计数器，返回新值"""
    config = load_runtime_config()
    config.ready_notify_count += 1
    save_runtime_config(config)
    return config.ready_notify_count
```

**验证**：
- 运行单元测试验证函数行为

---

### 任务 5：修改 shared_memory_poller.py

**目标**：删除旧的开关相关代码，改用 runtime_config

**文件**：`lark_client/shared_memory_poller.py`

**删除内容**：

1. 删除模块级常量（约第 691-694 行）：
```python
_READY_COUNT_FILE = USER_DATA_DIR / "ready_notify_count"
_NOTIFY_ENABLED_FILE = USER_DATA_DIR / "ready_notify_enabled"
_URGENT_ENABLED_FILE = USER_DATA_DIR / "urgent_notify_enabled"
_BYPASS_ENABLED_FILE = USER_DATA_DIR / "bypass_enabled"
```

2. 删除模块级函数（约第 697-806 行）：
- `_load_notify_enabled()`
- `_save_notify_enabled()`
- `_load_urgent_enabled()`
- `_save_urgent_enabled()`
- `_load_bypass_enabled()`
- `_save_bypass_enabled()`
- `_increment_ready_count()`

3. 删除模块级变量（约第 779-781 行）：
```python
_notify_enabled: bool = _load_notify_enabled()
_urgent_enabled: bool = _load_urgent_enabled()
_bypass_enabled: bool = _load_bypass_enabled()
```

4. 删除类方法（约第 631-662 行）：
- `get_notify_enabled()`
- `set_notify_enabled()`
- `get_urgent_enabled()`
- `set_urgent_enabled()`
- `get_bypass_enabled()`
- `set_bypass_enabled()`

**修改内容**：

1. 添加导入（在文件顶部导入区域）：
```python
from utils.runtime_config import (
    get_notify_ready_enabled,
    get_notify_urgent_enabled,
    increment_ready_notify_count,
)
```

2. 修改 `_update_ready_state()` 函数（约第 560-568 行）：

将：
```python
return current_ready and not prev_ready and tracker.is_group and _notify_enabled
```

改为：
```python
return current_ready and not prev_ready and tracker.is_group and get_notify_ready_enabled()
```

3. 修改 `_send_ready_notification()` 函数（约第 574 行）：

将：
```python
count = _increment_ready_count()
```

改为：
```python
count = increment_ready_notify_count()
```

4. 修改 `_send_ready_notification()` 函数中的加急判断（约第 580 行）：

将：
```python
if tracker.last_notify_message_id and uid != "all" and _urgent_enabled:
```

改为：
```python
if tracker.last_notify_message_id and uid != "all" and get_notify_urgent_enabled():
```

**验证**：
- 运行现有测试确保功能正常

---

### 任务 6：修改 lark_handler.py

**目标**：开关访问改用 runtime_config 函数

**文件**：`lark_client/lark_handler.py`

**变更内容**：

1. 添加导入：
```python
from utils.runtime_config import (
    get_notify_ready_enabled, set_notify_ready_enabled,
    get_notify_urgent_enabled, set_notify_urgent_enabled,
    get_bypass_enabled, set_bypass_enabled,
)
```

2. 修改 `_cmd_start()` 中的 bypass 检查（约第 344 行）：

将：
```python
if self._poller.get_bypass_enabled():
```

改为：
```python
if get_bypass_enabled():
```

3. 修改 `_cmd_menu()` 中的开关传递（约第 658-660 行）：

将：
```python
notify_enabled=self._poller.get_notify_enabled(),
urgent_enabled=self._poller.get_urgent_enabled(),
bypass_enabled=self._poller.get_bypass_enabled()
```

改为：
```python
notify_enabled=get_notify_ready_enabled(),
urgent_enabled=get_notify_urgent_enabled(),
bypass_enabled=get_bypass_enabled()
```

4. 修改 `_cmd_toggle_notify()`（约第 666-667 行）：

将：
```python
new_value = not self._poller.get_notify_enabled()
self._poller.set_notify_enabled(new_value)
```

改为：
```python
new_value = not get_notify_ready_enabled()
set_notify_ready_enabled(new_value)
```

5. 修改 `_cmd_toggle_urgent()`（约第 673-674 行）：

将：
```python
new_value = not self._poller.get_urgent_enabled()
self._poller.set_urgent_enabled(new_value)
```

改为：
```python
new_value = not get_notify_urgent_enabled()
set_notify_urgent_enabled(new_value)
```

6. 修改 `_cmd_toggle_bypass()`（约第 680-681 行）：

将：
```python
new_value = not self._poller.get_bypass_enabled()
self._poller.set_bypass_enabled(new_value)
```

改为：
```python
new_value = not get_bypass_enabled()
set_bypass_enabled(new_value)
```

**验证**：
- 运行现有测试确保功能正常

---

### 任务 7：更新配置模板文件

**目标**：更新默认配置模板

**文件**：
- `resources/defaults/config.default.json`
- `resources/defaults/runtime.default.json`

**config.default.json 变更**：

```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": []
    },
    "notify": {
      "ready_enabled": true,
      "urgent_enabled": false
    },
    "bypass_enabled": false
  }
}
```

**runtime.default.json 变更**：

```json
{
  "version": "1.0",
  "session_mappings": {},
  "lark_group_mappings": {},
  "ready_notify_count": 0
}
```

**验证**：
- 验证 JSON 格式正确

---

### 任务 8：修改 init.sh 添加迁移函数

**目标**：在 shell 层添加旧文件迁移函数

**文件**：`init.sh`

**变更内容**：

1. 在文件末尾（`main()` 函数之前）添加新函数：

```bash
# ── 迁移旧开关文件 ────────────────────────────────────────────────────────────

migrate_legacy_notify_files() {
    """迁移旧开关文件到 config.json 和 runtime.json"""
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
}
```

2. 在 `init_config_files()` 函数末尾调用迁移函数：

在 `# 3. 迁移旧 lark_group_mapping.json` 块之后添加：

```bash
    # 4. 迁移旧开关文件
    migrate_legacy_notify_files
```

**验证**：
- 创建旧文件后运行 `bash init.sh`，验证迁移正确

---

### 任务 9：创建 uninstall.sh

**目标**：创建卸载脚本

**文件**：`scripts/uninstall.sh`

**代码**：

```bash
#!/bin/bash
# Remote Claude 卸载脚本
# 用于 npm/pnpm preuninstall 钩子

set -e

# 解析安装目录
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && cd .. && pwd)"

# 颜色定义
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

print_info() { echo -e "${GREEN}ℹ${NC} $1"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }

# 用户数据目录
USER_DATA_DIR="$HOME/.remote-claude"
SOCKET_DIR="/tmp/remote-claude"

# 1. 停止飞书客户端
stop_lark_client() {
    print_info "停止飞书客户端..."
    if [ -f "$SOCKET_DIR/lark.pid" ]; then
        local pid=$(cat "$SOCKET_DIR/lark.pid" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            print_success "已停止飞书客户端 (pid=$pid)"
        fi
    fi
}

# 2. 停止所有活跃会话
stop_all_sessions() {
    print_info "停止所有活跃会话..."
    local sessions=$(tmux list-sessions -F "#{session_name}" 2>/dev/null | grep "^rc-" || true)
    if [ -n "$sessions" ]; then
        for session in $sessions; do
            tmux kill-session -t "$session" 2>/dev/null || true
            print_success "已终止会话: $session"
        done
    else
        print_info "没有活跃会话"
    fi
}

# 3. 清理符号链接
remove_symlinks() {
    print_info "清理符号链接..."

    local links=("cla" "cl" "cx" "cdx" "remote-claude")
    local bin_dirs=("/usr/local/bin" "$HOME/bin" "$HOME/.local/bin")

    for bin_dir in "${bin_dirs[@]}"; do
        for link in "${links[@]}"; do
            local link_path="$bin_dir/$link"
            if [ -L "$link_path" ]; then
                local target=$(readlink "$link_path" 2>/dev/null)
                # 只删除指向本项目的链接
                if [[ "$target" == *"remote-claude"* ]] || [[ "$target" == *"remote_claude"* ]]; then
                    rm -f "$link_path"
                    print_success "已删除: $link_path"
                fi
            fi
        done
    done
}

# 4. 清理 shell 配置文件
cleanup_shell_config() {
    print_info "清理 shell 配置文件..."

    local rc_files=("$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile")

    for rc_file in "${rc_files[@]}"; do
        if [ -f "$rc_file" ]; then
            # 移除 remote-claude 相关注释行
            if grep -q "remote-claude" "$rc_file" 2>/dev/null; then
                # 创建临时文件，移除相关行
                grep -v "remote-claude" "$rc_file" > "$rc_file.tmp" 2>/dev/null || true
                mv "$rc_file.tmp" "$rc_file"
                print_success "已清理: $rc_file"
            fi
        fi
    done
}

# 5. 清理临时目录
cleanup_temp() {
    print_info "清理临时目录..."
    if [ -d "$SOCKET_DIR" ]; then
        rm -rf "$SOCKET_DIR"
        print_success "已删除: $SOCKET_DIR"
    fi
}

# 6. 询问是否删除配置目录
ask_delete_config() {
    if [ -d "$USER_DATA_DIR" ]; then
        echo ""
        echo -e "${YELLOW}是否删除配置目录？${NC}"
        echo "  $USER_DATA_DIR"
        echo ""
        echo "  包含: config.json, runtime.json, 日志文件等"
        echo ""
        read -p "删除配置目录？ [y/N]: " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$USER_DATA_DIR"
            print_success "已删除配置目录"
        else
            print_info "保留配置目录: $USER_DATA_DIR"
        fi
    fi
}

# 主流程
main() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 卸载脚本${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    stop_lark_client
    stop_all_sessions
    remove_symlinks
    cleanup_shell_config
    cleanup_temp
    ask_delete_config

    echo ""
    print_success "卸载完成！"
    echo ""
}

main
```

**验证**：
- 运行 `sh scripts/uninstall.sh` 验证脚本执行

---

### 任务 10：更新 CLAUDE.md 文档

**目标**：更新项目文档

**文件**：`CLAUDE.md`

**变更内容**：

1. 在「配置文件架构」章节添加新字段说明
2. 更新 uninstall 相关命令说明

**验证**：
- 文档格式正确

---

## 提交策略

每个任务完成后独立提交：

1. `feat(package.json): 添加 pnpm.onlyBuiltDependencies 和 preuninstall 脚本`
2. `feat(runtime_config): 新增 NotifySettings 数据类`
3. `feat(runtime_config): 添加旧文件迁移函数`
4. `feat(runtime_config): 添加通知设置访问函数`
5. `refactor(shared_memory_poller): 移除开关相关代码，改用 runtime_config`
6. `refactor(lark_handler): 开关访问改用 runtime_config 函数`
7. `chore: 更新配置模板文件`
8. `feat(init.sh): 添加旧开关文件迁移逻辑`
9. `feat: 新增 uninstall.sh 卸载脚本`
10. `docs: 更新 CLAUDE.md 配置说明`

---

## 测试清单

- [ ] `npm install` 能正确执行 `postinstall`
- [ ] `pnpm install` 首次安装能执行初始化脚本
- [ ] `pnpm install` 重复安装不会重复运行初始化
- [ ] `npm uninstall` 能触发 `preuninstall`
- [ ] `pnpm uninstall` 能触发 `preuninstall`
- [ ] 旧文件正确迁移到 config.json/runtime.json
- [ ] 迁移后旧文件被删除
- [ ] 开关功能正常工作（菜单切换）
- [ ] uninstall.sh 能正确清理环境
