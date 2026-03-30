# 飞书会话卡片交互修复与初始化补全设计

- 日期：2026-03-30
- 主题：修复会话卡片交互问题（回车发送、快捷命令显示、自动应答位置）并补全首次 lazy 初始化配置复制逻辑
- 关联模块：`lark_client/card_builder.py`、`lark_client/main.py`、`lark_client/lark_handler.py`、`utils/runtime_config.py`、`scripts/setup.sh`、`resources/defaults/config.default.json`

## 1. 背景与问题

当前会话卡片存在以下体验问题：

1. 输入区回车行为不符合预期，用户期望支持多行输入。
2. 快捷命令在会话页面未按期展示。
3. 自动应答开关位于 `/menu`，用户期望放到会话页。
4. 现有“快捷键”与“快捷命令”分离，操作入口分散。

同时，初始化链路存在配置文件落盘缺口：

- `setup.sh` 正常路径会复制 `resources/defaults/config.default.json` 和 `runtime.default.json`；
- 但 `setup.sh --lazy` 路径不执行 `init_config_files()`，导致首次 lazy 场景下可能不生成 `~/.remote-claude/config.json` / `runtime.json`。

## 2. 目标（已确认）

1. 会话页支持**多行输入**（Enter 换行）。
2. 自动应答开关迁移到会话页，`/menu` 不保留该开关。
3. 将“快捷键”与“自定义命令”合并为统一操作入口。
4. 新增 `config.json` 配置，允许控制可用控制键范围。
5. 首次 `lazy` 与正常 `setup` 均执行 defaults 复制，且都仅在目标文件缺失时复制（不覆盖）。

## 3. 非目标

1. 不重构 SharedMemoryPoller 或协议层。
2. 不改变现有 option 选择导航算法与自动应答内部调度机制。
3. 不新增独立配置文件，继续沿用 `config.json` / `runtime.json`。

## 4. 方案概述

采用“会话页统一操作面板 + 初始化复制补全”方案：

1. 会话页底部交互区重构为：
   - 多行输入框 + 发送按钮
   - 合并后的“操作”下拉（控制键 + 自定义命令）
   - 菜单/断开按钮
   - 自动应答开关按钮
2. 回调分发统一通过前缀 value：
   - `key:<name>` → 控制键
   - `cmd:<command>` → 自定义命令
3. `config.json` 新增会话页操作配置，控制显示与允许范围。
4. `setup.sh --lazy` 在成功路径补执行 `init_config_files`（保持“文件不存在才复制”）。

## 5. 详细设计

### 5.1 会话页交互区重构（`lark_client/card_builder.py`）

#### 5.1.1 输入行为

- 将当前单行输入改为多行输入组件（textarea 语义）。
- Enter 行为改为换行，不再触发表单提交。
- 发送动作由显式“发送”按钮触发 `form_submit`。

#### 5.1.2 合并操作入口

- 移除单独“快捷键折叠面板”与独立“快捷命令选择器”。
- 新增统一“操作”下拉（单一 select）：
  - 内置控制键项（如 `↑/↓/Ctrl+O/Shift+Tab/ESC/(↹)×3`）
  - 自定义命令项（来源 `ui_settings.custom_commands`）
- 下拉项 value 使用前缀编码：
  - `key:up` / `key:shift_tab_x3`
  - `cmd:/clear`

#### 5.1.3 自动应答位置

- 在会话页底部增加自动应答开关按钮（显示当前状态与延迟秒数）。
- `/menu` 卡片移除自动应答按钮，避免双入口冲突。

### 5.2 回调路由调整（`lark_client/main.py`）

在现有卡片回调分发中补充“操作”下拉解析：

1. 收到字符串 value 且以 `key:` 开头：
   - 解析键名，调用 `handler.send_raw_key(...)`。
2. 收到字符串 value 且以 `cmd:` 开头：
   - 解析命令，调用 `handler.handle_quick_command(...)`。
3. 其他字符串 value：
   - 记录 warning 并忽略，避免卡片报错。
4. 保留现有 `form_value` 提交流程：
   - 有文本 → `forward_to_claude`
   - 空文本 → `send_raw_key(..., "enter")`

### 5.3 配置扩展（`utils/runtime_config.py` + `resources/defaults/config.default.json`）

在 `ui_settings` 下新增 `operation_panel`：

- `show_builtin_keys: bool`（默认 `true`）
- `show_custom_commands: bool`（默认 `true`）
- `enabled_keys: string[]`（默认包含当前支持的全部内置键）

行为规则：

1. 生成“操作”下拉时仅展示满足配置条件的项。
2. `enabled_keys` 外的控制键不展示、不触发。
3. 配置缺失时使用默认值，保证升级兼容。
4. 非法键名启动时过滤并记录 warning，不中断流程。

### 5.4 初始化复制补全（`scripts/setup.sh`）

#### 5.4.1 正常 setup 路径

- 保持现有 `init_config_files()` 调用顺序与行为：
  - 仅当 `config.json` / `runtime.json` 不存在时从 defaults 复制。

#### 5.4.2 lazy 路径

- 在 `--lazy` 成功路径（依赖安装成功后）补充 `init_config_files()` 调用。
- 仍遵守“仅缺失时复制，不覆盖现有文件”。
- 失败处理：
  - 若复制失败，返回非 0 并输出明确错误（模板缺失/权限问题）。

## 6. 错误处理策略

1. 操作下拉 value 解析失败：忽略并打日志，不影响后续刷新。
2. 未连接会话时触发控制键/命令：沿用现有提示“未连接到任何会话”。
3. 配置项缺失或非法：回退默认并 warning。
4. defaults 模板缺失：setup 路径显式失败，给出模板文件路径。

## 7. 测试计划

### 7.1 会话卡片交互

1. 多行输入：Enter 换行，点击发送提交。
2. 空输入发送：发送原始 Enter 键。
3. 操作下拉：
   - 选择 `key:*` 可触发对应控制键。
   - 选择 `cmd:*` 可执行自定义命令。
4. 自动应答开关：会话页可切换并立即反映。
5. `/menu`：不再展示自动应答按钮。

### 7.2 配置行为

1. `enabled_keys` 裁剪后仅显示允许的控制键。
2. `show_builtin_keys=false` 时仅展示自定义命令。
3. `show_custom_commands=false` 时仅展示控制键。
4. 非法键名不导致卡片构建失败。

### 7.3 初始化路径

1. 首次 `setup.sh`：复制 config/runtime 默认文件。
2. 首次 `setup.sh --lazy`：同样复制 config/runtime 默认文件。
3. 已存在配置文件时两种路径都不覆盖。
4. defaults 缺失时给出清晰错误。

## 8. 验收标准

1. 会话页支持多行输入，Enter 不直接发送。
2. “快捷键 + 自定义命令”合并为单一操作下拉。
3. 自动应答开关仅在会话页可见且可用。
4. `config.json` 可控制控制键开关与范围。
5. 首次 lazy 与 setup 都会补齐配置文件，且不覆盖已有文件。
