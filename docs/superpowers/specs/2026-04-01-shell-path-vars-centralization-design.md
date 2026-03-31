# Shell 脚本路径与变量统一设计

**日期**: 2026-04-01  
**主题**: 将 shell 脚本中的路径常量、路径推导、目录初始化和模板复制统一收敛到 `scripts/_common.sh`，并彻底移除旧兼容逻辑。

## 背景

当前 shell 脚本系统中，路径与文件变量在多个脚本内重复定义，包括：

- 用户数据目录：`$HOME/.remote-claude`
- socket 目录：`/tmp/remote-claude`
- 环境文件：`.env`
- 配置文件：`settings.json` / `state.json`
- 模板文件：`resources/defaults/env.example`、`settings.json.example`、`state.json.example`
- 飞书进程文件：`lark.pid`

这些定义散落在 `setup.sh`、`check-env.sh`、`install.sh`、`uninstall.sh`、`test_lark_management.sh` 等脚本中，已经出现过模板名与配置路径不一致的问题。最近配置结构已经统一到：

- `settings.json`
- `state.json`
- `env.example`

因此本次设计目标是：让 `_common.sh` 成为 shell 脚本侧的唯一路径真相源，并删除旧兼容分支，避免再次出现路径漂移。

## 目标

1. 所有当前有效路径常量统一定义在 `scripts/_common.sh`
2. 路径推导、目录创建、模板校验、缺省复制等通用逻辑统一封装到 `_common.sh`
3. `setup.sh`、`check-env.sh`、`install.sh`、`uninstall.sh`、`test_lark_management.sh` 不再手写路径字面量
4. 完全删除旧兼容逻辑，不再处理：
   - `config.json`
   - `runtime.json`
   - `config.default.json`
   - `runtime.default.json`
   - 旧配置迁移分支
5. 用测试守卫禁止未来重新引入路径分叉

## 非目标

1. 不修改 Python 代码中的路径处理逻辑
2. 不改变当前 shell 命令的对外行为与 CLI 参数语义
3. 不引入声明式配置表或复杂元编程式 shell 抽象
4. 不保留任何旧配置文件到新配置文件的迁移兼容

## 方案选择

### 方案 A（采用）
在 `_common.sh` 中建立统一路径变量和一组小型通用函数，其他脚本只消费这些变量与函数。

**原因**：
- 足够集中，能消除当前路径不一致问题
- 保持 shell 可读性，避免过度抽象
- 更符合当前仓库脚本风格

### 方案 B（未采用）
进一步封装更高层初始化流程函数，例如“一键初始化用户文件”。

**不采用原因**：
- 容易把各脚本职责耦合到 `_common.sh`
- 后续脚本流程调整会更难拆分

### 方案 C（未采用）
使用声明式映射表驱动路径初始化。

**不采用原因**：
- shell 中可读性差
- 调试成本高
- 不符合项目当前维护习惯

## 设计

### 一、`_common.sh` 统一路径真相源

新增统一路径初始化函数：

- `rc_init_paths`

该函数在 `_common.sh` 初始化阶段执行，导出以下变量：

- `REMOTE_CLAUDE_HOME_DIR="$HOME/.remote-claude"`
- `REMOTE_CLAUDE_SOCKET_DIR="/tmp/remote-claude"`
- `REMOTE_CLAUDE_ENV_FILE="$REMOTE_CLAUDE_HOME_DIR/.env"`
- `REMOTE_CLAUDE_SETTINGS_FILE="$REMOTE_CLAUDE_HOME_DIR/settings.json"`
- `REMOTE_CLAUDE_STATE_FILE="$REMOTE_CLAUDE_HOME_DIR/state.json"`
- `REMOTE_CLAUDE_ENV_TEMPLATE="$PROJECT_DIR/resources/defaults/env.example"`
- `REMOTE_CLAUDE_SETTINGS_TEMPLATE="$PROJECT_DIR/resources/defaults/settings.json.example"`
- `REMOTE_CLAUDE_STATE_TEMPLATE="$PROJECT_DIR/resources/defaults/state.json.example"`
- `REMOTE_CLAUDE_LARK_PID_FILE="$REMOTE_CLAUDE_SOCKET_DIR/lark.pid"`
- 如当前脚本仍需要 `lark.status`、日志文件等路径，也在此统一导出

约束：
- 除 `_common.sh` 外，其他脚本不再直接拼接上述路径
- 除 `_common.sh` 外，其他脚本不再定义自己的“路径真相源”变量，例如 `USER_DATA_DIR`、`ENV_FILE`、`CONFIG_FILE`、`RUNTIME_FILE`、`SOCKET_DIR`
- 调用方最多只创建语义性局部别名，但不允许重新拼接路径

### 二、`_common.sh` 通用文件/目录函数

新增以下小函数：

- `rc_ensure_home_dir`
  - 创建 `REMOTE_CLAUDE_HOME_DIR`
- `rc_ensure_socket_dir`
  - 创建 `REMOTE_CLAUDE_SOCKET_DIR`
- `rc_require_file <path> <label>`
  - 校验文件存在，不存在时输出统一错误并返回非零
- `rc_copy_if_missing <src> <dst> <label>`
  - 若目标不存在则复制；若已存在则保持不覆盖
- 如需要，补充 `rc_require_templates` 统一校验模板存在性

这些函数只负责单一职责：
- 目录创建
- 文件存在检查
- 缺省复制

不把具体业务流程塞进 `_common.sh`。

### 三、`setup.sh` 收口设计

`setup.sh` 保留为流程编排脚本，但不再拥有分散路径逻辑。

#### 1. `configure_lark()`
仅使用：
- `REMOTE_CLAUDE_ENV_FILE`
- `REMOTE_CLAUDE_ENV_TEMPLATE`
- `rc_ensure_home_dir`
- `rc_require_file`

行为：
- 确保用户目录存在
- 校验模板存在
- 若 `.env` 已存在则跳过
- 若用户选择配置飞书，则从 `env.example` 复制并提示填写

#### 2. `create_directories()`
仅使用：
- `rc_ensure_socket_dir`
- `rc_ensure_home_dir`

不再手写 `/tmp/remote-claude` 和 `$HOME/.remote-claude`。

#### 3. `init_config_files()`
仅处理当前规范文件：
- `REMOTE_CLAUDE_SETTINGS_FILE`
- `REMOTE_CLAUDE_STATE_FILE`
- `REMOTE_CLAUDE_SETTINGS_TEMPLATE`
- `REMOTE_CLAUDE_STATE_TEMPLATE`

逻辑：
- 确保模板存在
- 调用 `rc_copy_if_missing` 复制缺失的 `settings.json` / `state.json`
- 保留“不覆盖已有文件”的语义

删除内容：
- `lark_group_mapping.json` 迁移
- `config.json/runtime.json` 旧兼容迁移
- `config.default.json/runtime.default.json` 旧模板处理
- `migrate_legacy_notify_files()`
- `migrate_claude_command()`

### 四、`check-env.sh` 收口设计

`check-env.sh` 保留“飞书配置检查/引导”职责，但路径全部改用 `_common.sh` 提供的变量与函数。

仅使用：
- `REMOTE_CLAUDE_ENV_TEMPLATE`
- `REMOTE_CLAUDE_ENV_FILE`
- `rc_ensure_home_dir`
- `rc_require_file`

删除：
- 本地 `INSTALL_DIR`
- 本地 `ENV_FILE`
- 手写模板路径拼接

保留：
- `REMOTE_CLAUDE_REQUIRE_FEISHU=0` 时快速跳过
- `.env` 缺失时的交互引导
- 输入写回 `.env`

### 五、`install.sh` 收口设计

`install.sh` 保留安装流程逻辑，但运行目录、用户目录、配置文件路径统一来自 `_common.sh`。

要求：
- 不再手写 `$HOME/.remote-claude`、`/tmp/remote-claude`
- 若脚本需要配置文件或日志文件路径，统一通过 `_common.sh` 导出变量访问
- 不引入新的局部路径真相源

### 六、`uninstall.sh` 收口设计

`uninstall.sh` 是本次重构的重点之一。

统一使用：
- `REMOTE_CLAUDE_HOME_DIR`
- `REMOTE_CLAUDE_SOCKET_DIR`
- `REMOTE_CLAUDE_ENV_FILE`
- `REMOTE_CLAUDE_SETTINGS_FILE`
- `REMOTE_CLAUDE_STATE_FILE`
- `REMOTE_CLAUDE_LARK_PID_FILE`
- 其他当前仍有效的日志/状态文件路径

删除：
- 对旧 `config.json` / `runtime.json` 的特殊清理逻辑
- 对旧模板/旧迁移文件的兼容分支

保留：
- 清理当前规范下的安装产物
- 终止当前规范下的 lark 相关进程和状态文件

### 七、`test_lark_management.sh` 收口设计

该测试脚本中的硬编码路径统一替换为 `_common.sh` 变量，例如：
- `REMOTE_CLAUDE_LARK_PID_FILE`
- 若存在状态文件：新增统一状态文件变量
- 用户日志文件路径统一来自 `REMOTE_CLAUDE_HOME_DIR`

目标是让测试脚本和生产脚本对同一资源路径使用完全相同的定义。

### 八、`completion.sh` 处理策略

`completion.sh` 主要职责是解析项目根目录和加载补全逻辑。

本次不强行对其做全面路径重构，原则是：
- 若引用项目资源路径，则复用 `_common.sh` 已有能力
- 若仅做自身 `PROJECT_DIR` 推导，则维持现状

这样可以避免把任务扩大到与当前问题无关的补全过程。

## 删除旧兼容逻辑的明确范围

本次实现后，shell 脚本中不再允许出现以下旧结构的业务分支：

- `config.json`
- `runtime.json`
- `config.default.json`
- `runtime.default.json`
- `lark_group_mapping.json` 自动迁移
- 旧通知/bypass 文件迁移
- `CLAUDE_COMMAND` 到旧配置结构的迁移逻辑

如果仓库中仍保留这些字符串，必须满足以下二选一：
1. 它们位于测试中，且测试明确断言这些旧逻辑已被删除；或
2. 它们位于文档/历史说明中，且不再参与运行时逻辑

运行时脚本中不得继续依赖它们。

## 测试设计

### 1. `_common.sh` 行为测试

补充或更新 shell 行为测试，验证：
- `rc_init_paths` 导出统一变量
- `rc_require_file` 缺文件时返回非零
- `rc_copy_if_missing` 在目标不存在时复制，目标已存在时不覆盖
- 目录创建函数可正确创建用户目录与 socket 目录

### 2. 现有回归测试更新

重点回归：
- `tests/test_entry_lazy_init.py`
- `tests/test_custom_commands.py`
- `tests/test_runtime_config.py`

新增/更新断言：
- `setup.sh` 初始化产物是 `settings.json` / `state.json`
- `check-env.sh` 使用 `env.example`
- 旧兼容文件不再出现在运行时脚本主逻辑中

### 3. 源码守卫测试

增加文本级守卫，避免未来回归：
- `scripts/setup.sh` / `scripts/check-env.sh` / `scripts/uninstall.sh` / `scripts/install.sh` / `scripts/test_lark_management.sh` 不再手写：
  - `"$HOME/.remote-claude"`
  - `"/tmp/remote-claude"`
  - `resources/defaults/...`
- 运行时脚本不再出现：
  - `config.default.json`
  - `runtime.default.json`
  - `config.json`
  - `runtime.json`
  - `lark_group_mapping.json`

这里的守卫测试是本次重构的关键，因为目标是约束未来维护者只能通过 `_common.sh` 修改路径规范。

## 实施顺序

1. 先补 `_common.sh` 新接口的测试
2. 更新现有测试，使其表达“旧兼容逻辑已删除、统一变量存在”
3. 实现 `_common.sh` 的统一路径变量与通用函数
4. 改 `setup.sh` 与 `check-env.sh`
5. 改 `install.sh`、`uninstall.sh`、`test_lark_management.sh`
6. 跑完整相关测试集并检查失败项
7. 若有残留旧字符串，仅保留在测试/文档中，不保留在运行时路径逻辑中

## 风险与控制

### 风险 1：`_common.sh` 成为中心点后，命名错误会影响多个脚本
**控制方式**：
- 先补 `_common.sh` 行为测试
- 逐脚本切换，不一次性大爆炸修改

### 风险 2：删除旧兼容后，部分测试或脚本仍隐含依赖旧路径
**控制方式**：
- 先 grep 全量定位
- 用文本守卫测试阻断残留

### 风险 3：过度抽象导致 shell 可读性下降
**控制方式**：
- 只抽“路径与文件操作”小函数
- 不抽高层业务流程

## 验收标准

满足以下条件即可视为完成：

1. 运行时 shell 脚本中的核心路径只在 `_common.sh` 定义
2. `setup.sh` / `check-env.sh` / `install.sh` / `uninstall.sh` / `test_lark_management.sh` 不再手写这些路径
3. 旧兼容逻辑已从运行时脚本中删除
4. 相关测试全部通过
5. 新增守卫测试能阻止未来重新引入路径分叉
