# Feature Specification: 命令行与飞书用户体验增强

**Feature**: `20260319-cmd-ux-enhancements`
**Created**: 2026-03-19
**Status**: Draft
**Input**: User description: "1. 系统需支持对 name 进行截断操作,避免超出操作系统对 socket 的名称长度限制;2. 飞书上支持常见命令,将其作为下拉框,例如 /clear, /compact, /exit 等等,便于快速选择; 3. 默认日志级别设置为 WARN; 4. 所有cmd,对于help类型方法,只输出help,不要真正执行(不输出错误信息)"

## Clarifications

### Session 2026-03-19

- Q: 会话名称截断策略 → A: 优先保留目录后缀，舍弃前缀，尽可能保持语义可读性
- Q: QuickCommand value 最大长度（spec.md 要求 16 字符，当前实现 50 字符）→ A: 32 字符（折中方案，平衡简洁性和灵活性）
- Q: 会话名冲突处理策略（spec.md 要求完整 MD5，当前实现使用 8 字符后缀）→ A: 使用完整 MD5 哈希作为最终名称（按照 FR-021c）
- Q: 配置文件架构（spec.md 要求拆分，当前只有单一文件）→ A: 拆分为 config.json + runtime.json
- Q: 文件锁和 bak 清理功能实现时机 → A: 当前版本实现（按照 FR-021a, FR-028, FR-029）
- Q: 映射存储方式 → A: 通用运行时文件：`~/.remote-claude/runtime.json`（灵活结构，存储 session 映射、UI 设置等运行时状态）
- Q: 飞书快捷命令 UI 组件 → A: 保持 `select_static` 下拉选择器
- Q: 快捷命令选择器默认行为 → A: 默认关闭，需在 `runtime.json` 的 `ui_settings.quick_commands_enabled` 中手动开启
- Q: 配置迁移策略 → A: 安装时将旧 `lark_group_mapping.json` 迁移到 `runtime.json` 的 `lark_group_mappings` 字段，迁移后删除旧文件，统一使用新字段名
- Q: 快捷命令列表配置方式 → A: 在 `runtime.json` 中配置（统一管理运行时配置）
- Q: 快捷命令默认列表 → A: 精简核心命令：`/clear, /consume, /compact, /exit, /help`
- Q: 快捷命令参数支持 → A: 不支持参数，仅支持无参数命令（简化实现）
- Q: 配置缺失时行为 → A: 不显示快捷命令选择器（视为禁用）
- Q: 配置控制项设计 → A: 保留两者：`enabled` 布尔开关 + `commands` 命令列表（灵活控制）
- Q: runtime.json 映射数量限制 → A: 限制 500 条映射，超出时提示用户清理
- Q: runtime.json 敏感信息保护 → A: 无需特殊保护，使用系统默认文件权限
- Q: runtime.json 版本迁移策略 → A: 实现版本迁移函数，按版本号逐步升级配置
- Q: 性能要求 → A: 无显式性能要求，本地工具响应足够快
- Q: 国际化/多语言支持 → A: 仅支持中文，无国际化计划
- Q: 随机后缀冲突重试策略 → A: 直接使用完整 MD5 哈希作为最终名称（不重试）
- Q: 配置文件并发写入保护 → A: 使用文件锁（fcntl.flock），等待锁释放后写入
- Q: QuickCommand value 最大长度 → A: 16 字符（保守限制，确保命令简洁）
- Q: session_mappings 达到 500 条上限后的行为 → A: 允许继续添加，仅输出警告日志（软限制）
- Q: 配置文件损坏备份保留策略 → A: 保留最近的 2 个备份文件，自动清理更早的
- Q: `remote-claude list` 展示格式 → A: 截断名称 + 原始路径 + 原来展示的信息（三列展示）
- Q: 配置文件拆分策略 → A: 拆分为 `config.json`（用户可编辑配置）和 `runtime.json`（程序自动管理状态），使配置更语义化
- Q: 文件锁位置和名称 → A: `~/.remote-claude/runtime.json.lock`（与配置文件同目录，便于管理）
- Q: 锁文件注释内容 → A: 详细信息（用途 + 创建进程 PID + 创建时间），便于调试
- Q: 会话退出时映射清理策略 → A: 删除映射（新策略，替换原有"保留映射"策略）
- Q: 配置迁移 bak 文件清理策略 → A: 迁移/修改完成后立即删除 bak 文件；启动时检测残留 bak 文件，提示用户选择：覆盖（重新迁移）或跳过（删除 bak 继续），保证正常运行时无 bak 文件残留
- Q: README.md 更新范围 → A: 更新 README.md 和 CLAUDE.md 中关于 runtime.json/config.json 的说明，确保文档与实现一致
- Q: QuickCommand value 最大长度 → A: 32 字符（折中方案，平衡简洁性和灵活性，原 spec 要求 16 字符过于保守）
- Q: 会话名冲突处理策略 → A: 使用完整 MD5 哈希作为最终名称（按照 FR-021c，替换当前实现的「截断名称 + 8 字符后缀」）
- Q: 配置文件架构 → A: 拆分为 config.json（用户配置）和 runtime.json（程序状态）（按照 FR-025-027，替换当前单一 runtime.json）
- Q: 文件锁和 bak 文件清理实现时机 → A: 当前版本实现（按照 FR-021a, FR-028, FR-029）
- Q: 卡片交互优化适用范围 → A: 所有按钮交互 + 文本输入场景（快捷命令选择器、选项按钮、菜单按钮、文本框输入提交等）
- Q: 回车自动确认触发场景 → A: 文本框输入后按回车键自动提交
- Q: 回车提交适用范围 → A: 仅单行输入框，多行文本框保留换行行为
- Q: 卡片更新方式 → A: 使用 `update_card` API 就地更新现有卡片内容
- Q: 卡片更新视觉反馈 → A: 卡片内显示状态变化（按钮变为 disabled、显示"处理中"等）
- Q: 连续下划线处理规则 → A: 合并为单下划线（如 `a__b` → `a_b`）
- Q: QuickCommand icon 字段格式限制 → A: 无限制（由飞书卡片渲染决定），可空，默认空白占位 emoji
- Q: commands 达到 20 条上限处理 → A: 静默截断（只显示前 20 条）
- Q: 配置文件权限不足处理 → A: 使用内存配置继续运行，输出警告日志
- Q: 空会话名处理 → A: 拒绝启动并提示"会话名不能为空"
- Q: 快捷命令发送时会话已断开的提示文本 → A: "会话已断开，请重新连接后重试"
- Q: `disconnected` 状态的判定时机 → A: 实时检测（每次需要时检查 bridge.running 状态）
- Q: 快捷命令选择器的渲染和响应时间性能标准 → A: 无显式要求（本地工具，用户感知足够快即可）
- Q: 用户快速连续发送多个快捷命令的处理方式 → A: 串行处理 + 500ms 防抖（每个命令按顺序执行，重复点击被忽略）
- Q: 无效日志级别（如 `LARK_LOG_LEVEL=INVALID`）的处理 → A: 输出警告日志后回退到默认值 WARNING

### Session 2026-03-20

- Q: Docker 测试需要覆盖的范围 → A: 完整覆盖，将 spec.md 中所有新功能测试（test_runtime_config.py, test_session_truncate.py, test_card_interaction.py 等）加入 Docker 测试
- Q: Docker 测试脚本是否需要添加单元测试执行步骤 → A: 新增步骤，在"步骤 8：生成测试报告"之前新增"步骤 7.5：执行独立单元测试"
- Q: docker/README.md 独立单元测试列表是否需要更新 → A: 同步更新，补充所有新功能测试文件
- Q: 单元测试失败时的处理策略 → A: 分类处理，核心测试失败终止，非核心测试失败继续执行
- Q: 是否需要增强 Codex CLI 相关测试 → A: 保持现状，当前 Codex 测试（启动验证）已足够
- Q: config.json 和 runtime.json 是否需要迁移逻辑 → A: 不需要迁移，均为全新配置文件（仅保留 `lark_group_mapping.json` → `runtime.json` 的迁移，FR-019）

### Session 2026-03-21

- Q: 配置初始化执行位置 → A: init.sh 中用 shell 脚本直接执行（不调用 Python 函数）
- Q: 文档布局优化方案 → A: 将 LARK_CLIENT_GUIDE.md 移动到 lark_client/ 目录，其他文档保持原位
- Q: 文件备份策略优化 → A: 完整实现新策略：写前备份 + 启动时检测备份残留 + 按时间戳从新到旧找第一个有效备份恢复
- Q: 配置回退命令范围 → A: 新增 `remote-claude config reset --all` 一键重置全部 + `--config` / `--runtime` 分别回退
- Q: 配置回退时清理副作用文件范围 → A: 仅清理配置相关副作用文件（锁文件、备份文件），保留状态文件
- Q: 默认配置内容存储方式 → A: 独立模板文件 + 资源目录，在 `resources/defaults/` 下放置 `config.default.json`、`runtime.default.json`、`.env.example` 模板文件，代码通过读取模板文件进行初始化
- Q: 目录结构优化方案 → A: 重新规划目录结构：`core/`（核心逻辑）、`clients/`（客户端）、`tests/`、`resources/`、`docs/`（说明文件）
- Q: 资源目录内容范围 → A: `resources/defaults/` 包含 `config.default.json`、`runtime.default.json`、`.env.example` 三个模板文件
- Q: 默认配置内容存储方式 → A: 独立模板文件 + 资源目录：在 resources/defaults/ 下放置 config.default.json 和 runtime.default.json 模板文件，代码通过读取模板文件进行初始化
- Q: 资源目录位置 → A: resources/defaults/ 放在项目根目录
- Q: 目录结构优化方案 → A: 重新规划目录结构：core/ (核心逻辑), clients/ (客户端), tests/, resources/, docs/（说明文件），目标：减少目录数量、减少单文件数量
- Q: 默认配置内容存储方式 → A: 独立模板文件 + 资源目录，在 resources/defaults/ 下放置 config.default.json 和 runtime.default.json
- Q: 资源目录位置 → A: resources/defaults/ 放在项目根目录
- Q: 目录结构优化方案 → A: 重新规划：core/ (核心逻辑), clients/ (客户端), tests/, resources/, docs/ (说明文件)
- Q: 配置重置时副作用文件清理范围 → A: 与被重置的配置文件范围保持一致。`--config` 只清理 `config.json.lock` 和 `config.json.bak.*`；`--runtime` 只清理 `runtime.json.lock` 和 `runtime.json.bak.*`；`--all` 清理所有锁文件和备份文件

### Session 2026-03-22

- Q: `test_lark_management.sh` 移动后是否需要保留符号链接 → A: 直接移动，不保留符号链接（项目中无其他引用此文件）
- Q: Docker 构建配置优化 - 是否需要引入多阶段构建 → A: 保持单阶段构建，仅优化依赖安装顺序和缓存层
- Q: Docker 测试逻辑精简 - 测试范围确认 → A: 保留完整测试链路，但合并相似步骤减少重复
- Q: scripts 目录脚本优化范围确认 → A: 仅修复已知问题，保持现有结构
- Q: docker/README.md 优化方向 → A: 全面优化（一键命令示例 + 预期输出 + 故障排查流程图 + 常见问题解决方案）
- Q: Docker 镜像构建缓存优化 → A: 同时使用 Docker 层缓存优化和 BuildKit 缓存挂载
- Q: utils 目录常量和路径函数是否需要整合 → A: 保持现有 `utils/session.py` 作为路径常量和函数的统一定义点，但在 `utils/runtime_config.py` 中解决循环依赖问题
- Q: `utils/session.py` 和 `utils/runtime_config.py` 之间的循环依赖如何解决 → A: 将 `resolve_session_name()` 中的 `runtime_config` 导入改为延迟导入（函数内导入），避免模块级循环依赖

### Session 2026-03-22 (续)

- Q: docker-test.sh 中 `log_success`/`log_error` 调用时是否正确更新全局 PASSED/FAILED 计数 → A: 修复策略——测试文件不存在视为测试失败，使用 `log_error` 并更新 `FAILED` 计数，保持 PASSED+FAILED 总数与实际测试项数量一致

### Session 2026-03-22 (Docker 优化澄清)

- Q: Docker 构建优化范围 → A: 全量优化（依赖安装缓存优化 + 多阶段构建优化）
- Q: pnpm 替代 npm 的使用范围 → A: 仅 Docker 镜像内使用 pnpm，本地开发仍用 npm
- Q: npm 安装产物放置策略 → A: 可执行产物提取（.venv 和关键脚本到 test_results），可在宿主机运行并执行 bin 下脚本
- Q: docker-test.sh 输出统计优化方案 → A: 三级计数体系（PASSED + WARNINGS + FAILED），最终报告明确区分核心失败与非核心失败
- Q: README.md Docker 验证内容补充范围 → A: 快速验证命令 + 开发者验证手册（一键命令 + 完整流程 + 本地调试 + CI/CD 集成）

### Session 2026-03-23 (Python 环境便携化澄清)

- Q: Python 环境依赖策略 → A: 项目自带便携式 Python（打包 Python 解释器，用户无需预装）
- Q: Docker 测试 venv 使用策略 → A: Docker 构建时创建 venv，测试运行时激活使用
- Q: 宿主机产物运行策略 → A: 产物提取时包含便携式 Python，宿主机无需预装（完全自包含）
- Q: 便携式 Python 打包方式 → A: 使用 uv 管理，自动创建隔离环境
- Q: uv 管理 Python 方式 → A: Docker 镜像和安装包中预装 uv 管理的 Python，无需运行时下载

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 会话名称自动截断处理 (Priority: P1)

当用户启动会话时，如果会话名称过长导致 socket 路径超出操作系统限制（macOS AF_UNIX sun_path 104 字节限制），系统应自动截断或转换名称，确保 socket 能正常创建。

**触发条件**：
- 用户执行 `remote-claude start <会话名>` 时
- 会话名转换后的 socket 路径长度超过系统限制
- 或 tmux 会话名称超出限制

**业务规则**：
- macOS AF_UNIX sun_path 限制为 104 字节
- Socket 路径格式：`/tmp/remote-claude/<name>.sock`（固定前缀 19 字节 + 文件名 + 后缀 5 字节）
- 超长名称应使用 MD5 哈希或其他稳定转换方式
- 转换后的名称必须保持唯一性和可追溯性

**Why this priority**: P1 - 这是系统基础稳定性问题，如果不处理可能导致会话启动失败，影响所有用户。

**Technical Implementation**:

当前实现位于 `utils/session.py`：
- 已定义 `_MAX_SOCKET_PATH = 104`（macOS 限制）
- 已计算 `_MAX_FILENAME = _MAX_SOCKET_PATH - len(str(SOCKET_DIR)) - 1 - len(".sock")`
- **具体数值**：`_MAX_FILENAME ≈ 80` 字节（macOS: 104 - 19 - 5 = 80；Linux: 108 - 19 - 5 = 84）
- 已实现 `_safe_filename()` 函数：
  - 将 `/` 和 `.` 替换为 `_`
  - 超长时使用完整 32 字符 MD5 哈希

**需增强部分**：
1. 验证当前实现是否覆盖所有使用会话名的地方（socket、PID 文件、MQ 文件、tmux 会话名）
2. 添加日志记录，当名称被截断/转换时输出警告信息
3. 考虑 Linux 系统的路径长度限制（通常为 108 字节）
4. **截断策略优化**：优先保留目录路径后缀，舍弃前缀部分，以保持语义可读性
   - 示例：`/Users/dev/projects/myapp/src/components` → 优先保留 `myapp/src/components`，而非 `Users/dev/projects`
   - 实现方式：从右向左按路径分隔符切分，保留最大可容纳的完整后缀路径
5. **原始路径映射存储**：建立原始路径与截断名称的映射关系，存储于通用运行时文件 `~/.remote-claude/runtime.json`
   - 文件结构灵活，支持扩展（session 映射、lark_group_mappings、UI 设置、其他运行时状态）
   - **配置迁移**：启动时检查旧 `lark_group_mapping.json` 文件，自动迁移到 `runtime.json` 的 `lark_group_mappings` 字段，迁移后删除旧文件
   - 便于追溯：用户可通过截断名称反查原始路径
   - 冲突检测：当截断后名称发生冲突时，检查原始目录是否为同一个
     - 若为同一个：保持现有行为（复用已有会话）
     - 若非同一个：在截断名称后加入随机字符串后缀，再进行 hash 确保 uniq
   - 示例结构：
     ```json
     {
       "session_mappings": {
         "myapp_src_comp": "/Users/dev/projects/myapp/src/components",
         "other_project": "/path/to/other/project"
       },
       "lark_group_mappings": {
         "oc_xxx": "my-session"
       },
       "ui_settings": {
         "quick_commands": {
           "enabled": false,
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

**Independent Test**: 可以通过创建超长会话名（如 200 字符的路径）并尝试启动会话来独立测试，验证 socket 文件是否正常创建。

**Acceptance Scenarios**:

1. **Given** 用户执行 `remote-claude start /very/long/path/to/project/that/exceeds/the/maximum/socket/path/length/limit`，**When** 系统创建 socket，**Then** socket 路径被自动截断（保留后缀），会话正常启动，映射关系写入 `runtime.json`
2. **Given** 用户执行 `remote-claude start normal-name`，**When** 系统创建 socket，**Then** socket 路径使用原名 `normal-name.sock`，无转换
3. **Given** 会话名包含特殊字符（如 `/` 和 `.`），**When** 系统创建 socket，**Then** 特殊字符被替换为 `_`，路径合法
4. **Given** 会话名为超长目录路径 `/Users/dev/projects/myapp/src/components/utils/helpers/deep/nested/structure`，**When** 系统截断名称，**Then** 优先保留后缀部分（如 `myapp_src_components_utils...`），而非前缀
5. **Given** 两个不同目录 `/path/a/b/c` 和 `/other/a/b/c` 截断后名称相同 `a_b_c`，**When** 系统检测冲突，**Then** 第二个目录的会话名变为 `a_b_c_<hash>` 以确保唯一性
6. **Given** 同一目录 `/path/a/b/c` 被重复启动，**When** 系统检测冲突，**Then** 复用已有会话（行为与当前一致）
7. **Given** 运行时文件 `runtime.json` 存在，**When** 用户查询历史会话，**Then** 可通过截断名称反查原始路径

---

### User Story 2 - 飞书快捷命令选择器 (Priority: P1)

飞书用户在选择并发送常用命令（如 /clear, /compact, /exit 等）时，可以通过下拉框快速选择，无需手动输入命令文本。

**⚠️ 重要：此功能默认关闭，需手动开启。**

**触发条件**：
- 用户在飞书聊天界面中查看会话卡片时
- 用户需要发送常用控制命令
- **用户已在 `runtime.json` 中启用快捷命令功能**（`ui_settings.quick_commands_enabled: true`）

**业务规则**：
- **默认行为**：快捷命令选择器不显示，减少界面干扰
- **启用方式**：在 `~/.remote-claude/runtime.json` 中设置 `ui_settings.quick_commands.enabled: true` 并配置 `ui_settings.quick_commands.commands` 列表
- **命令列表配置**：用户可在 `commands` 数组中自定义快捷命令，支持无参数命令
- **默认命令列表**（当 `commands` 未配置时可作为参考）：`/clear, /consume, /compact, /exit, /help`
- 命令通过下拉选择器呈现
- 选择后自动发送命令到当前会话
- 命令选择器应在流式卡片的底部菜单区域显示

**Why this priority**: P1 - 这是核心用户体验改进，直接影响飞书用户的操作效率。但默认关闭避免对不需要此功能的用户造成干扰。

**Technical Implementation**:

**修改文件**：
1. `utils/runtime_config.py`（新增）：
   - 添加 `is_quick_commands_enabled()` 方法检查 `ui_settings.quick_commands.enabled`
   - 添加 `get_quick_commands()` 方法获取配置的命令列表
   - 迁移逻辑：启动时检查旧 `lark_group_mapping.json` 文件，自动迁移到 `runtime.json` 的 `lark_group_mappings` 字段

2. `lark_client/card_builder.py`：
   - 在 `build_stream_card()` 中添加配置检查
   - 仅当 `enabled=true` 且 `commands` 非空时渲染命令选择器
   - 使用飞书卡片 `select_static` 元素
   - 命令列表从 `runtime.json` 读取，格式示例：

```python
# 命令配置格式（从 runtime.json 读取）
# 示例配置值：
# {
#   "enabled": true,
#   "commands": [
#     {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
#     {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
#     {"label": "退出会话", "value": "/exit", "icon": "🚪"},
#     {"label": "帮助", "value": "/help", "icon": "❓"}
#   ]
# }
```

2. `lark_client/lark_handler.py`：
   - 添加 `handle_quick_command()` 方法处理命令选择事件
   - 复用现有的 `_handle_command()` 逻辑

3. 飞书卡片交互元素示例：
```json
{
  "tag": "action",
  "actions": [{
    "tag": "select_static",
    "placeholder": {"tag": "plain_text", "content": "快捷命令"},
    "options": [
      {"text": {"tag": "plain_text", "content": "🗑️ 清空对话"}, "value": "/clear"},
      {"text": {"tag": "plain_text", "content": "📦 压缩上下文"}, "value": "/compact"}
    ]
  }]
}
```

**Independent Test**: 可以在飞书卡片中独立测试命令选择器的渲染和交互，验证选择命令后是否正确发送到会话。

**Acceptance Scenarios**:

1. **Given** `ui_settings.quick_commands.enabled` 未设置或为 `false`，**When** 用户查看流式卡片，**Then** 不显示快捷命令选择器
2. **Given** `ui_settings.quick_commands.enabled: true` 且 `commands` 列表为空或缺失，**When** 用户查看流式卡片，**Then** 不显示快捷命令选择器
3. **Given** `ui_settings.quick_commands.enabled: true` 且 `commands` 非空，**When** 用户点击命令选择下拉框，**Then** 显示配置的命令列表
4. **Given** 用户点击选择"/clear"命令，**When** 系统发送命令，**Then** Claude CLI 接收到 /clear 命令并清空对话历史
5. **Given** 会话未连接（disconnected=True），**When** 用户查看卡片，**Then** 命令选择器不显示
6. **Given** 旧配置文件 `lark_group_mapping.json` 存在，**When** 飞书客户端启动，**Then** 自动迁移到 `runtime.json` 的 `lark_group_mappings` 字段，旧文件被删除
7. **Given** 用户配置自定义命令列表 `["/custom1", "/custom2"]`，**When** 用户查看流式卡片，**Then** 显示自定义命令列表而非默认列表

---

### User Story 3 - 默认日志级别设置 (Priority: P2)

系统默认日志级别设置为 WARN（WARNING），减少生产环境日志噪音，仅在需要调试时通过环境变量调整。

**触发条件**：
- 飞书客户端启动时
- Server 进程启动时
- 用户未显式设置 `LARK_LOG_LEVEL` 环境变量

**业务规则**：
- 默认日志级别从 INFO 改为 WARNING
- DEBUG 日志仅在显式设置 `LARK_LOG_LEVEL=DEBUG` 时输出
- INFO 级别日志可通过 `LARK_LOG_LEVEL=INFO` 启用
- 不影响现有的日志配置机制

**Why this priority**: P2 - 这是一个配置优化，不影响核心功能，但能改善生产环境日志可读性。

**Technical Implementation**:

**修改文件**：`lark_client/config.py`

当前实现（第 42-50 行）：
```python
# lark_client 日志级别（可选，默认 INFO）
# 支持: DEBUG / INFO / WARNING / ERROR
_LARK_LOG_LEVEL = os.getenv("LARK_LOG_LEVEL", "INFO").upper()
LARK_LOG_LEVEL = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}.get(_LARK_LOG_LEVEL, 20)  # 默认 INFO
```

修改后：
```python
# lark_client 日志级别（可选，默认 WARNING）
# 支持: DEBUG / INFO / WARNING / ERROR
_LARK_LOG_LEVEL = os.getenv("LARK_LOG_LEVEL", "WARNING").upper()
LARK_LOG_LEVEL = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}.get(_LARK_LOG_LEVEL, 30)  # 默认 WARNING
```

**Independent Test**: 可以通过启动飞书客户端并验证日志输出来独立测试，确认默认只输出 WARNING 及以上级别日志。

**Acceptance Scenarios**:

1. **Given** 用户未设置 `LARK_LOG_LEVEL` 环境变量，**When** 飞书客户端启动，**Then** 日志级别为 WARNING（30），只输出警告和错误
2. **Given** 用户设置 `LARK_LOG_LEVEL=DEBUG`，**When** 飞书客户端启动，**Then** 日志级别为 DEBUG（10），输出所有调试信息
3. **Given** 用户设置 `LARK_LOG_LEVEL=INFO`，**When** 飞书客户端启动，**Then** 日志级别为 INFO（20），输出信息和以上级别日志

---

### User Story 4 - Help 参数纯展示模式 (Priority: P2)

当用户使用 `--help` 或 `-h` 参数运行任意命令时，系统只展示帮助信息，不执行任何实际操作，不输出错误信息。

**触发条件**：
- 用户执行 `remote-claude <command> --help`
- 用户执行 `remote-claude <command> -h`
- 用户执行 `remote-claude --help` 或 `remote-claude -h`

**业务规则**：
- `--help` / `-h` 参数应优先于所有其他逻辑
- 不应执行任何可能失败或产生副作用的操作
- 不应输出"会话不存在"、"连接失败"等错误信息
- 帮助信息应清晰展示命令用法和参数说明

**Why this priority**: P2 - 这是一个命令行体验优化，遵循 Unix 命令行惯例，提升用户友好性。

**Technical Implementation**:

**修改文件**：`remote_claude.py`

当前实现使用 `argparse`，已内置 `--help` 支持：
- `parser.add_argument("--version", "-V", action="version", ...)` 已处理版本信息
- argparse 自动处理 `-h`/`--help`，打印帮助后退出

**需要处理的边缘情况**：
1. 子命令的 `--help` 已由 argparse 处理（自动）
2. 需要确保即使命令参数缺失，`--help` 也能正常工作
3. 验证当前实现是否符合预期，可能无需修改

**验证点**：
- `remote-claude start --help` 应只显示 start 命令帮助，不尝试启动会话
- `remote-claude attach --help` 应只显示 attach 命令帮助，不检查会话是否存在
- `remote-claude lark --help` 应显示 lark 子命令帮助

**Independent Test**: 可以通过执行各种 `--help` 命令来独立测试，验证只输出帮助信息且无错误。

**Acceptance Scenarios**:

1. **Given** 用户执行 `remote-claude start --help`，**When** 命令解析，**Then** 只显示 start 命令帮助信息，不尝试启动会话
2. **Given** 用户执行 `remote-claude attach --help`，**When** 命令解析，**Then** 只显示 attach 命令帮助信息，不检查会话是否存在
3. **Given** 用户执行 `remote-claude lark status --help`，**When** 命令解析，**Then** 只显示 status 子命令帮助信息，不检查客户端状态

---

### User Story 5 - List 命令增强展示 (Priority: P2)

当用户执行 `remote-claude list` 命令时，展示截断名称、原始路径和原有信息，便于用户识别会话对应的实际工作目录。

**触发条件**：
- 用户执行 `remote-claude list` 命令

**业务规则**：
- 展示格式：截断名称 + 原始路径 + 原有展示信息（如会话状态等）
- 原始路径从 `runtime.json` 的 `session_mappings` 中反查
- 若映射不存在（旧会话或手动创建的会话），原始路径显示为 `-` 或空

**Why this priority**: P2 - 这是一个体验优化，帮助用户更好地理解会话列表，但不影响核心功能。

**Technical Implementation**:

**修改文件**：`remote_claude.py`

当前实现（`cmd_list()` 函数）：
- 列出 `/tmp/remote-claude/*.sock` 文件
- 显示会话名称和状态

**增强部分**：
1. 调用 `RuntimeConfig.get_session_mapping()` 获取截断名称对应的原始路径
2. 调整输出格式，新增原始路径列

**输出格式示例**：
```
会话列表:
名称                  原始路径                                          状态
myapp_src_comp   →   /Users/dev/projects/myapp/src/components         运行中
test_session     →   /path/to/test                                     已停止
simple_name      →   -                                                 运行中
```

**Independent Test**: 可以通过启动会话并执行 `remote-claude list` 来独立测试，验证输出格式和内容正确。

**Acceptance Scenarios**:

1. **Given** 用户执行 `remote-claude list`，**When** 存在会话，**Then** 展示截断名称、原始路径（从 runtime.json 反查）和状态
2. **Given** 会话无映射记录（手动创建），**When** 列表展示，**Then** 原始路径显示为 `-`
3. **Given** 无活跃会话，**When** 用户执行 `remote-claude list`，**Then** 显示"无活跃会话"提示

---

### User Story 6 - 配置文件拆分 (Priority: P1)

将配置文件拆分为 `config.json`（用户可编辑配置）和 `runtime.json`（程序自动管理状态），使配置语义更清晰，便于用户理解和维护。

**触发条件**：
- 飞书客户端启动时
- 用户手动编辑配置时

**业务规则**：
- **config.json**：存放用户可编辑的配置（如 `ui_settings`、`quick_commands`）
- **runtime.json**：存放程序自动管理的状态（如 `session_mappings`、`lark_group_mappings`）
- 两文件独立维护，互不干扰
- 文件锁名称与配置文件对应（`runtime.json.lock`）

**Why this priority**: P1 - 这是架构变更，影响配置管理方式，需要优先实现。

**Technical Implementation**:

**文件结构示例**：

`~/.remote-claude/config.json`：
```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"}
      ]
    }
  }
}
```

`~/.remote-claude/runtime.json`：
```json
{
  "version": "1.0",
  "session_mappings": {
    "myapp_src": "/Users/dev/projects/myapp/src/components"
  },
  "lark_group_mappings": {
    "oc_xxx": "my-session"
  }
}
```

**修改文件**：
1. `utils/runtime_config.py`：
   - 新增 `load_user_config()` / `save_user_config()` 处理 `config.json`
   - 新增 `load_runtime_config()` / `save_runtime_config()` 处理 `runtime.json`
   - 调整 `is_quick_commands_visible()` 从 `config.json` 读取
   - 调整 `get_quick_commands()` 从 `config.json` 读取

**注意**：config.json 和 runtime.json 均为全新配置文件，无需迁移逻辑。首次启动时自动创建默认配置文件。

**Independent Test**: 可以通过创建和修改两个配置文件来独立测试，验证读写正确。

**Acceptance Scenarios**:

1. **Given** 用户首次启动，**When** 系统初始化配置，**Then** 创建 `config.json`（含默认 UI 设置）和空的 `runtime.json`
2. **Given** 用户编辑 `config.json` 启用快捷命令，**When** 飞书客户端启动，**Then** 快捷命令选择器显示
3. **Given** 会话启动，**When** 名称被截断，**Then** 映射写入 `runtime.json`（不影响 `config.json`）

---

### User Story 7 - 会话退出时清理映射 (Priority: P2)

当会话退出（kill 或 exit）时，同步删除 `runtime.json` 中对应的映射关系，保持配置清洁。

**触发条件**：
- 用户执行 `remote-claude kill <会话名>`
- Claude/Codex 进程正常退出

**业务规则**：
- 会话退出时删除 `session_mappings` 中对应条目
- 不删除 `lark_group_mappings`（群组绑定保留，便于重新连接）
- 删除操作需要文件锁保护

**Why this priority**: P2 - 这是清理优化，不影响核心功能，但能保持配置整洁。

**Technical Implementation**:

**修改文件**：
1. `remote_claude.py`：
   - 在 `cmd_kill()` 中添加映射删除逻辑
2. `utils/runtime_config.py`：
   - 新增 `remove_session_mapping()` 方法

**Acceptance Scenarios**:

1. **Given** 会话 `myapp_src` 存在映射，**When** 用户执行 `remote-claude kill myapp_src`，**Then** `session_mappings` 中对应条目被删除
2. **Given** 会话 `myapp_src` 绑定了飞书群组，**When** 会话退出，**Then** `lark_group_mappings` 保留（便于重新连接）

---

### User Story 8 - 飞书卡片交互优化 (Priority: P1)

当用户在飞书卡片中进行交互式操作（按钮点击、文本框输入提交）时，系统应就地更新原卡片内容，而不是推送新卡片，提升用户体验流畅度。

**触发条件**：
- 用户点击快捷命令选择器选择命令
- 用户点击选项按钮（如 Yes/No 确认）
- 用户点击菜单按钮
- 用户在单行文本框输入内容后提交

**业务规则**：
- 所有交互动作使用飞书 `update_card` API 就地更新现有卡片
- 交互过程中卡片内显示状态变化（按钮变为 disabled、显示"处理中"等）
- 更新完成后恢复正常状态或显示结果
- **排除场景**：流式输出内容变化（仍由 SharedMemoryPoller 驱动更新）

**Why this priority**: P1 - 这是核心用户体验改进，直接影响飞书用户的交互流畅度，减少卡片刷屏。

**Technical Implementation**:

**修改文件**：
1. `lark_client/lark_handler.py`：
   - 修改 `handle_quick_command()` 使用 `update_card` 而非 `send_card`
   - 修改选项按钮处理逻辑使用 `update_card`
   - 修改菜单按钮处理逻辑使用 `update_card`

2. `lark_client/card_builder.py`：
   - 新增 `build_card_with_loading_state()` 函数 - 构建带 loading 状态的卡片
   - 修改现有函数支持 `is_loading` / `disabled_buttons` 参数

3. `lark_client/card_service.py`：
   - 确认 `update_card()` 方法正确实现

**飞书卡片交互流程示例**：
```
用户点击"清空对话"按钮
    ↓
卡片就地更新：按钮 disabled + 显示"处理中..."
    ↓
发送 /clear 命令到会话
    ↓
卡片就地更新：恢复正常状态 + 显示命令已发送
```

**Independent Test**: 可以在飞书中点击各种按钮，验证卡片就地更新而非推送新卡片。

**Acceptance Scenarios**:

1. **Given** 用户点击快捷命令选择器选择"/clear"，**When** 命令处理，**Then** 原卡片按钮变为 disabled，显示"处理中"，处理完成后恢复正常
2. **Given** 用户点击选项按钮（Yes/No），**When** 选项处理，**Then** 原卡片就地更新显示选择结果
3. **Given** 用户点击菜单按钮，**When** 菜单操作，**Then** 原卡片就地更新显示菜单操作结果
4. **Given** 用户在单行文本框输入内容后提交，**When** 提交处理，**Then** 原卡片就地更新显示输入结果
5. **Given** 流式输出内容变化，**When** SharedMemoryPoller 检测到变化，**Then** 仍使用原有更新机制（不受此功能影响）

---

### User Story 9 - 飞书卡片回车自动确认 (Priority: P2)

当用户在飞书卡片的单行文本输入框中输入内容后，按回车键可自动提交，无需手动点击确认按钮，提升输入效率。

**触发条件**：
- 用户在单行文本输入框中输入内容
- 用户按下回车键

**业务规则**：
- **仅单行输入框**支持回车自动提交
- **多行文本框**保留回车换行行为（不触发提交）
- 回车提交后触发与点击确认按钮相同的处理逻辑
- 提交时卡片显示状态变化（按钮 disabled、"处理中"等）

**Why this priority**: P2 - 这是一个便捷性优化，不影响核心功能，但能提升用户输入体验。

**Technical Implementation**:

**修改文件**：
1. `lark_client/card_builder.py`：
   - 在构建单行输入框时添加 `on_confirm` 回调配置
   - 使用飞书卡片的 `action` 元素配合 `enter_key_action` 属性

2. `lark_client/lark_handler.py`：
   - 新增 `handle_text_input_submit()` 方法处理回车提交事件
   - 复用现有的文本输入处理逻辑

**飞书卡片元素示例**：
```json
{
  "tag": "input",
  "placeholder": {"tag": "plain_text", "content": "输入消息..."},
  "element_id": "message_input",
  "enter_key_action": {
    "tag": "action",
    "actions": [{
      "tag": "button",
      "text": {"tag": "plain_text", "content": "发送"},
      "type": "primary",
      "value": "{\"action\": \"send_message\"}"
    }]
  }
}
```

**Independent Test**: 可以在飞书卡片文本框输入内容后按回车，验证自动提交成功。

**Acceptance Scenarios**:

1. **Given** 用户在单行消息输入框输入"你好"，**When** 按下回车键，**Then** 消息自动发送，无需点击确认按钮
2. **Given** 用户在多行文本框输入内容，**When** 按下回车键，**Then** 换行而非提交
3. **Given** 用户在单行输入框按回车提交，**When** 提交处理，**Then** 卡片显示状态变化（与 User Story 8 一致）
4. **Given** 单行输入框为空，**When** 按下回车键，**Then** 不触发提交（空输入校验）

---

### User Story 10 - 配置初始化与迁移 (Priority: P2)

在 init.sh 中完成 runtime.json 和 config.json 的配置初始化及对历史配置的迁移，确保首次安装和升级时配置文件正确生成。

**触发条件**：
- 用户执行 `./init.sh` 初始化脚本
- 首次安装时（配置文件不存在）
- 升级时（存在旧配置文件需要迁移）

**业务规则**：
- 使用 shell 脚本直接执行配置初始化（不调用 Python 函数）
- 迁移旧 `lark_group_mapping.json` 到 `runtime.json` 的 `lark_group_mappings` 字段
- 创建默认 `config.json`（含默认 UI 设置）
- 创建空的 `runtime.json`（如不存在）
- 迁移后删除旧配置文件

**Why this priority**: P2 - 这是安装体验优化，不影响核心功能，但能确保升级平滑。

**Technical Implementation**:

**修改文件**：`init.sh`

在 `create_directories()` 函数后新增配置初始化逻辑：

```bash
# 初始化配置文件
init_config_files() {
    print_header "初始化配置文件"

    local USER_DATA_DIR="$HOME/.remote-claude"
    local CONFIG_FILE="$USER_DATA_DIR/config.json"
    local RUNTIME_FILE="$USER_DATA_DIR/runtime.json"
    local LEGACY_FILE="$USER_DATA_DIR/lark_group_mapping.json"

    # 1. 创建默认 config.json（如不存在）
    if [ ! -f "$CONFIG_FILE" ]; then
        cat > "$CONFIG_FILE" << 'EOF'
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
        {"label": "退出会话", "value": "/exit", "icon": "🚪"},
        {"label": "帮助", "value": "/help", "icon": "❓"}
      ]
    }
  }
}
EOF
        print_success "创建默认配置: $CONFIG_FILE"
    else
        print_info "配置文件已存在: $CONFIG_FILE"
    fi

    # 2. 创建空的 runtime.json（如不存在）
    if [ ! -f "$RUNTIME_FILE" ]; then
        cat > "$RUNTIME_FILE" << 'EOF'
{
  "version": "1.0",
  "session_mappings": {},
  "lark_group_mappings": {}
}
EOF
        print_success "创建运行时配置: $RUNTIME_FILE"
    else
        print_info "运行时配置已存在: $RUNTIME_FILE"
    fi

    # 3. 迁移旧 lark_group_mapping.json
    if [ -f "$LEGACY_FILE" ]; then
        print_info "检测到旧配置文件: $LEGACY_FILE"
        # 使用 jq 或 Python 解析 JSON 并合并
        if command -v jq &> /dev/null; then
            # 读取旧映射
            local legacy_mappings=$(cat "$LEGACY_FILE")
            # 合并到 runtime.json
            local runtime_content=$(cat "$RUNTIME_FILE")
            echo "$runtime_content" | jq --argjson mappings "$legacy_mappings" '.lark_group_mappings = $mappings' > "$RUNTIME_FILE.tmp"
            mv "$RUNTIME_FILE.tmp" "$RUNTIME_FILE"
            rm "$LEGACY_FILE"
            print_success "已迁移 lark_group_mapping.json 到 runtime.json"
        else
            print_warning "未安装 jq，跳过自动迁移（程序启动时会自动迁移）"
        fi
    fi
}
```

**Independent Test**: 可以通过清空 `~/.remote-claude/` 目录后运行 `./init.sh` 来验证配置文件创建。

**Acceptance Scenarios**:

1. **Given** 首次安装，**When** 运行 init.sh，**Then** 创建默认 config.json 和空的 runtime.json
2. **Given** 存在旧 lark_group_mapping.json，**When** 运行 init.sh，**Then** 迁移到 runtime.json 的 lark_group_mappings 字段并删除旧文件
3. **Given** config.json 已存在，**When** 运行 init.sh，**Then** 保持现有配置不变

---

### User Story 11 - 文档布局优化 (Priority: P3)

将 `LARK_CLIENT_GUIDE.md` 移动到 `lark_client/` 目录下，减少项目根目录文档散乱。

**触发条件**：
- 开发者整理项目文档结构时

**业务规则**：
- 将 `LARK_CLIENT_GUIDE.md` 移动到 `lark_client/GUIDE.md`
- 更新其他文档中对 `LARK_CLIENT_GUIDE.md` 的引用
- 其他文档（README.md、CLAUDE.md、CHANGELOG.md 等）保持原位

**Why this priority**: P3 - 这是文档整理优化，不影响核心功能，但能改善项目结构。

**Technical Implementation**:

**文件变更**：
1. 移动文件：`LARK_CLIENT_GUIDE.md` → `lark_client/GUIDE.md`
2. 更新引用：
   - `CLAUDE.md` 中更新文档路径
   - `README.md` 中更新链接

**Independent Test**: 可以通过检查文档链接和文件位置来验证。

**Acceptance Scenarios**:

1. **Given** 文档整理需求，**When** 移动文件，**Then** `lark_client/GUIDE.md` 存在，根目录 `LARK_CLIENT_GUIDE.md` 不存在
2. **Given** 用户查看文档，**When** 点击引用链接，**Then** 正确跳转到新位置

---

### User Story 12 - 文件备份策略优化 (Priority: P2)

优化配置文件备份策略：写之前备份，启动时检测备份残留并按时间戳从新到旧恢复。

**触发条件**：
- 程序写入配置文件时
- 程序启动检测到备份文件残留时

**业务规则**：
- **写前备份**：每次写入配置文件前，先备份当前文件到 `<name>.json.bak.<timestamp>`
- **启动检测**：检测 `*.json.bak.*` 文件是否存在
- **恢复策略**：
  1. 检查当前配置文件格式是否正确
  2. 若正确，删除所有备份文件
  3. 若不正确，按时间戳从新到旧检查备份文件
  4. 找到第一个格式正确的备份，询问用户是否恢复
  5. 恢复后删除其他备份文件

**Why this priority**: P2 - 这是数据安全增强，确保配置文件不会因异常情况丢失。

**Technical Implementation**:

**修改文件**：`utils/runtime_config.py`

```python
def _backup_before_write(path: Path) -> Path:
    """写入前备份配置文件

    Args:
        path: 配置文件路径

    Returns:
        备份文件路径
    """
    if not path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(f".json.bak.{timestamp}")
    shutil.copy2(path, backup)
    logger.debug(f"已备份配置文件: {backup}")
    return backup


def check_and_recover_backup() -> Optional[Path]:
    """启动时检测备份文件并尝试恢复

    Returns:
        恢复的备份文件路径（如有恢复）
        None: 无需恢复或用户选择不恢复
    """
    # 1. 检查当前配置文件是否有效
    config_valid = _validate_config_file(RUNTIME_CONFIG_FILE)
    user_config_valid = _validate_config_file(USER_CONFIG_FILE)

    # 2. 若都有效，清理所有备份文件
    if config_valid and user_config_valid:
        cleanup_backup_files()
        return None

    # 3. 若无效，按时间戳从新到旧找第一个有效备份
    for config_file in [RUNTIME_CONFIG_FILE, USER_CONFIG_FILE]:
        if not _validate_config_file(config_file):
            backups = sorted(
                USER_DATA_DIR.glob(f"{config_file.stem}.json.bak.*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True  # 从新到旧
            )
            for backup in backups:
                if _validate_config_file(backup):
                    # 询问用户是否恢复
                    choice = prompt_backup_recovery(backup, config_file)
                    if choice == 'recover':
                        shutil.copy2(backup, config_file)
                        cleanup_backup_files()
                        logger.info(f"已从备份恢复配置: {backup}")
                        return backup
                    else:
                        # 用户选择不恢复，删除备份继续
                        cleanup_backup_files()
                        return None

    return None


def _validate_config_file(path: Path) -> bool:
    """验证配置文件格式是否正确"""
    if not path.exists():
        return True  # 不存在视为有效（将创建默认配置）
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        # 检查必要字段
        if "version" not in data:
            return False
        return True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


def prompt_backup_recovery(backup_path: Path, config_path: Path) -> str:
    """提示用户是否从备份恢复"""
    print(f"检测到配置文件损坏: {config_path}")
    print(f"找到有效备份: {backup_path}")
    print("1. 从备份恢复")
    print("2. 使用默认配置（忽略备份）")
    choice = input("请选择 [1/2]: ").strip()
    return 'recover' if choice == '1' else 'skip'
```

**Independent Test**: 可以通过手动创建损坏的配置文件和有效备份来测试恢复逻辑。

**Acceptance Scenarios**:

1. **Given** 程序写入配置，**When** 写入前，**Then** 创建当前配置的备份
2. **Given** 启动时配置文件损坏且有有效备份，**When** 检测到备份，**Then** 提示用户是否恢复
3. **Given** 启动时配置文件正确，**When** 检测到备份文件，**Then** 自动删除备份文件
4. **Given** 有多个备份文件，**When** 需要恢复，**Then** 从新到旧选择第一个有效备份

---

### User Story 13 - 配置回退命令 (Priority: P2)

提供配置一键回退命令，支持重置全部配置或分别回退 config.json / runtime.json。

**触发条件**：
- 用户执行 `remote-claude config reset` 命令
- 配置文件损坏无法修复时
- 用户希望恢复默认配置时

**业务规则**：
- `remote-claude config reset --all`：重置全部配置文件，清理所有锁文件和备份文件
- `remote-claude config reset --config`：仅重置 config.json，只清理 `config.json.lock` 和 `config.json.bak.*`
- `remote-claude config reset --runtime`：仅重置 runtime.json，只清理 `runtime.json.lock` 和 `runtime.json.bak.*`
- 无参数时进入交互式选择模式
- 回退时清理与被重置配置相关的副作用文件（锁文件、备份文件），保留状态文件（lark.pid、lark.status）
- 清理范围必须与重置范围保持一致

**Why this priority**: P2 - 这是运维便利性功能，帮助用户快速恢复配置问题。

**Technical Implementation**:

**修改文件**：`remote_claude.py`

新增 `config` 子命令：

```python
def cmd_config_reset(args):
    """配置重置命令"""
    import shutil
    from utils.runtime_config import USER_DATA_DIR, USER_CONFIG_FILE, RUNTIME_CONFIG_FILE

    # 确定要重置的配置文件
    reset_all = args.all
    reset_config = args.config_only
    reset_runtime = args.runtime_only

    if not (reset_all or reset_config or reset_runtime):
        # 交互式选择
        print("选择要重置的配置：")
        print("1. 全部配置（config.json + runtime.json）")
        print("2. 仅用户配置（config.json）")
        print("3. 仅运行时配置（runtime.json）")
        print("4. 取消")
        choice = input("请选择 [1-4]: ").strip()
        if choice == '1':
            reset_all = True
        elif choice == '2':
            reset_config = True
        elif choice == '3':
            reset_runtime = True
        else:
            print("已取消")
            return

    # 默认配置模板
    default_config = '''{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
        {"label": "退出会话", "value": "/exit", "icon": "🚪"},
        {"label": "帮助", "value": "/help", "icon": "❓"}
      ]
    }
  }
}'''

    default_runtime = '''{
  "version": "1.0",
  "session_mappings": {},
  "lark_group_mappings": {}
}'''

    # 执行重置
    if reset_all or reset_config:
        USER_CONFIG_FILE.write_text(default_config, encoding="utf-8")
        print(f"✓ 已重置用户配置: {USER_CONFIG_FILE}")

    if reset_all or reset_runtime:
        RUNTIME_CONFIG_FILE.write_text(default_runtime, encoding="utf-8")
        print(f"✓ 已重置运行时配置: {RUNTIME_CONFIG_FILE}")

    # 清理副作用文件（锁文件、备份文件），范围与重置配置保持一致
    if reset_all or reset_config:
        config_lock = USER_DATA_DIR / "config.json.lock"
        if config_lock.exists():
            config_lock.unlink()
            print(f"✓ 已清理锁文件: {config_lock}")
        for bak_file in USER_DATA_DIR.glob("config.json.bak.*"):
            bak_file.unlink()
            print(f"✓ 已清理备份文件: {bak_file}")

    if reset_all or reset_runtime:
        runtime_lock = USER_DATA_DIR / "runtime.json.lock"
        if runtime_lock.exists():
            runtime_lock.unlink()
            print(f"✓ 已清理锁文件: {runtime_lock}")
        for bak_file in USER_DATA_DIR.glob("runtime.json.bak.*"):
            bak_file.unlink()
            print(f"✓ 已清理备份文件: {bak_file}")

    print("配置重置完成")
```

**Independent Test**: 可以通过执行命令并检查配置文件内容来验证。

**Acceptance Scenarios**:

1. **Given** 用户执行 `remote-claude config reset --all`，**When** 命令执行，**Then** config.json 和 runtime.json 恢复默认值，副作用文件被清理
2. **Given** 用户执行 `remote-claude config reset --config`，**When** 命令执行，**Then** 仅 config.json 恢复默认值
3. **Given** 用户执行 `remote-claude config reset`（无参数），**When** 命令执行，**Then** 进入交互式选择模式
4. **Given** 重置时存在副作用文件，**When** 重置完成，**Then** 锁文件和备份文件被清理，状态文件保留

---

### User Story 14 - Docker 构建优化 (Priority: P2)

优化 Docker 构建配置，使用 pnpm 加速依赖安装，优化缓存策略，并提取可执行产物到宿主机可运行位置。

**触发条件**：
- 开发者构建 Docker 测试镜像
- CI/CD 流水线运行测试

**业务规则**：
- **全量优化**：依赖安装缓存优化 + 多阶段构建优化
- **pnpm 使用范围**：仅 Docker 镜像内使用 pnpm，本地开发仍用 npm
- **可执行产物提取**：提取 `.venv` 和关键脚本到 `test_results/` 目录
- **宿主机可运行**：提取的产物可在宿主机直接运行，bin 下脚本可直接执行

**Why this priority**: P2 - 这是开发体验优化，不影响核心功能，但能提升构建效率。

**Technical Implementation**:

**修改文件**：`docker/Dockerfile.test`

1. **依赖安装缓存优化**：
   - 使用 BuildKit 缓存挂载加速 apt 和 pnpm 安装
   - 优化 Docker 层顺序，将不常变化的层放在前面

2. **引入 pnpm**：
   - 在 Docker 镜像内使用 pnpm 替代 npm
   - 利用 pnpm 的符号链接和缓存机制加速安装

3. **多阶段构建优化**：
   - 分离构建阶段和运行阶段
   - 减小最终镜像体积

**修改文件**：`docker/scripts/docker-test.sh`

4. **产物提取逻辑**：
   - 在测试完成后提取 `.venv` 目录到 `test_results/venv/`
   - 提取 `bin/` 目录脚本到 `test_results/bin/`
   - 生成宿主机运行脚本 `test_results/run.sh`

**Independent Test**: 构建 Docker 镜像并验证构建时间减少，提取的产物可在宿主机运行。

**Acceptance Scenarios**:

1. **Given** Docker 镜像使用 pnpm 构建，**When** 执行构建，**Then** 依赖安装时间相比 npm 减少约 30%
2. **Given** Docker 测试完成，**When** 查看产物，**Then** `test_results/venv/` 包含完整 Python 虚拟环境
3. **Given** Docker 测试完成，**When** 查看产物，**Then** `test_results/bin/` 包含可执行脚本
4. **Given** 宿主机 Python 版本兼容，**When** 执行 `test_results/bin/cla`，**Then** 脚本正常工作
5. **Given** 本地开发环境，**When** 执行 `npm install`，**Then** 仍使用 npm（不受 Docker pnpm 影响）

---

### User Story 15 - Docker 测试输出优化 (Priority: P3)

优化 docker-test.sh 的输出统计，使用三级计数体系，使成功/失败数量符合认知。

**触发条件**：
- Docker 测试执行完成
- 开发者查看测试报告

**业务规则**：
- **三级计数体系**：PASSED（通过）+ WARNINGS（非核心测试失败）+ FAILED（核心测试失败）
- **最终报告明确区分**：核心测试失败与非核心测试失败分别统计
- **PASSED + WARNINGS + FAILED 总数**：与实际测试项数量一致

**Why this priority**: P3 - 这是测试体验优化，不影响测试覆盖率，但能提升报告可读性。

**Technical Implementation**:

**修改文件**：`docker/scripts/docker-test.sh`

1. **统一计数函数**：
   - `log_success`：更新 PASSED 计数
   - `log_warning`：更新 WARNINGS 计数（用于非核心测试失败）
   - `log_error`：更新 FAILED 计数（用于核心测试失败）

2. **修复单元测试步骤计数**：
   - 测试文件不存在时使用 `log_error` 更新 FAILED 计数
   - 确保每个测试步骤都正确更新计数

3. **最终报告格式**：
   ```text
   测试摘要：
   - 通过: X
   - 警告（非核心失败）: Y
   - 失败（核心失败）: Z
   - 总计: X+Y+Z
   ```

**Independent Test**: 运行 Docker 测试并验证报告中计数正确。

**Acceptance Scenarios**:

1. **Given** 所有测试通过，**When** 测试完成，**Then** PASSED = 总测试项数，WARNINGS = 0，FAILED = 0
2. **Given** 非核心测试失败，**When** 测试完成，**Then** WARNINGS 计数增加，测试继续执行
3. **Given** 核心测试失败，**When** 测试完成，**Then** FAILED 计数增加，测试终止
4. **Given** 测试文件不存在，**When** 该测试步骤执行，**Then** 更新 FAILED 计数（核心测试）或 WARNINGS 计数（非核心测试）
5. **Given** 部分测试失败，**When** 查看报告，**Then** PASSED + WARNINGS + FAILED 总数等于测试步骤总数

---

### User Story 16 - README Docker 验证文档补充 (Priority: P3)

更新 README.md，补充 Docker 验证说明，包含快速验证命令和开发者验证手册。

**触发条件**：
- 新用户了解如何使用 Docker 验证项目
- 开发者进行本地调试或 CI/CD 集成

**业务规则**：
- **快速验证命令**：一键构建 + 运行测试的完整命令示例
- **开发者验证手册**：完整流程 + 本地调试技巧 + CI/CD 集成示例
- **预期输出示例**：展示成功和失败的典型输出格式

**Why this priority**: P3 - 这是文档优化，不影响功能实现，但能提升用户上手体验。

**Technical Implementation**:

**修改文件**：`README.md`

在现有 README.md 中新增 Docker 验证章节：

```markdown
## Docker 验证

### 快速验证

```bash
# 一键构建并运行测试
docker-compose -f docker/docker-compose.test.yml build && \
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh

# 查看测试报告
cat test-results/test_report.md
```

### 开发者验证手册

#### 完整验证流程

1. 构建镜像：`docker-compose -f docker/docker-compose.test.yml build`
2. 运行测试：`docker-compose -f docker/docker-compose.test.yml run npm-test`
3. 查看结果：`cat test-results/test_report.md`
4. 故障排查：`docker exec -it remote-claude-npm-test /bin/bash`

#### 本地调试技巧

```bash
# 进入容器交互调试
docker exec -it remote-claude-npm-test /bin/bash

# 重新运行单个测试
docker exec remote-claude-npm-test bash -c 'cd /project && .venv/bin/python tests/test_runtime_config.py'

# 收集诊断信息
docker exec remote-claude-npm-test /project/docker/scripts/docker-diagnose.sh
```

#### CI/CD 集成示例

```yaml
- name: Run Docker Tests
  run: |
    docker-compose -f docker/docker-compose.test.yml build
    docker-compose -f docker/docker-compose.test.yml run --rm npm-test

- name: Upload Test Results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: test-results
    path: test-results/
```
```

**Independent Test**: 查看 README.md 确认内容完整且格式正确。

**Acceptance Scenarios**:

1. **Given** 用户阅读 README.md，**When** 查看 Docker 验证章节，**Then** 找到快速验证命令和预期输出
2. **Given** 开发者需要调试，**When** 参考本地调试技巧，**Then** 能成功进入容器并运行测试
3. **Given** CI/CD 配置需要集成，**When** 参考 CI/CD 示例，**Then** 能成功配置自动化测试

---

### Edge Cases

- **跨平台路径长度限制**：Linux 和 macOS 的 socket 路径长度限制不同（108 vs 104 字节），系统应如何处理？
  - 当前实现使用 104 字节（macOS 限制），对 Linux 来说是安全的（更严格的限制）
  - 建议添加系统检测，使用各平台实际限制

- **命令选择器与会话状态不一致**：用户选择命令时会话已断开
  - 处理方式：显示提示"会话已断开，请重新连接后重试"，引导用户重新连接
  - disconnected 状态判定：实时检测（每次检查 bridge.running 状态）

- **日志级别环境变量值无效**：用户设置 `LARK_LOG_LEVEL=INVALID`
  - 处理方式：输出警告日志提示设置的值无效，回退到默认值 WARNING（30）

- **runtime.json 文件损坏**：文件存在但 JSON 格式无效
  - 处理方式：备份损坏文件，创建新的空配置，输出警告日志

- **映射条目清理**：会话被 kill 或 exit 后，映射条目自动删除
  - ~~建议：保留映射条目，便于历史追溯；定期清理可手动执行~~ **已更新为新策略：自动删除**

- **配置迁移冲突**：`runtime.json` 已存在 `lark_group_mappings`，同时存在旧 `lark_group_mapping.json`
  - 处理方式：以 `runtime.json` 为准，删除旧文件并输出警告日志

- **快捷命令配置缺失**：`ui_settings.quick_commands` 字段不存在或 `enabled` 未设置
  - 处理方式：默认为 `false`（不显示快捷命令选择器）

- **快捷命令列表为空**：`enabled: true` 但 `commands` 为空数组
  - 处理方式：不显示快捷命令选择器（需要有效命令才能显示）

- **快捷命令值无效**：用户配置了不存在的命令（如 `/unknown`）
  - 处理方式：正常发送命令，由 CLI 返回错误信息（不做前置验证）

- **快捷命令发送时会话已断开**：用户选择命令时会话已断开
  - 处理方式：提示"会话已断开，请重新连接后重试"，不发送命令

- **配置迁移 bak 文件残留**：启动时发现 `.bak` 文件未删除
  - 处理方式：提示用户选择：① 覆盖当前配置并重新迁移（删除当前文件，从 bak 恢复）② 跳过（删除 bak 文件，使用当前配置继续）
  - 目标：保证正常运行时无 bak 文件残留

- **配置文件拆分**：config.json 和 runtime.json 均为全新配置文件，无需迁移逻辑
  - config.json 存储 `ui_settings`（用户可编辑配置）
  - runtime.json 存储 `session_mappings`、`lark_group_mappings`（程序自动管理状态）
  - 首次启动时创建默认配置文件

- **卡片更新失败**：`update_card` API 调用失败（网络问题、卡片已删除等）
  - 处理方式：降级为发送新卡片，并记录警告日志

- **回车提交与移动端兼容**：移动端飞书客户端可能无物理回车键
  - 处理方式：保留确认按钮作为备选提交方式

- **快速连续交互**：用户快速点击多个按钮或快速提交
  - 处理方式：串行处理（每个命令按顺序执行）+ 500ms 防抖（重复点击被忽略，只处理最后一次）

- **连续下划线路径**：路径中包含连续分隔符（如 `/a//b`）
  - 处理方式：合并为单下划线（`a__b` → `a_b`）

- **快捷命令列表超限**：用户配置超过 20 条命令
  - 处理方式：静默截断，只显示前 20 条

- **配置文件权限不足**：配置目录为只读
  - 处理方式：使用内存配置继续运行，输出警告日志

- **空会话名**：用户尝试以空字符串启动会话
  - 处理方式：拒绝启动，提示"会话名不能为空"

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 自动处理超长会话名称，确保 socket 路径不超过操作系统限制
- **FR-002**: 会话名称转换 MUST 保持唯一性（使用 MD5 哈希或其他稳定转换）
- **FR-003**: 当名称被截断或转换时，系统 SHOULD 输出日志提示
- **FR-004**: 飞书卡片 MUST 提供快捷命令选择器，包含 /clear, /compact, /exit 等常用命令
- **FR-005**: 快捷命令选择后 MUST 自动发送命令到当前会话
- **FR-006**: 断开会话的卡片 MUST 显示连接相关命令而非控制命令
- **FR-007**: 飞书客户端默认日志级别 MUST 为 WARNING（30）
- **FR-008**: 用户 MUST 能通过 `LARK_LOG_LEVEL` 环境变量覆盖日志级别
- **FR-009**: 所有命令的 `--help` 参数 MUST 只显示帮助信息，不执行任何操作
- **FR-010**: `--help` 参数 MUST 不输出错误信息（如会话不存在）
- **FR-011**: 截断策略 MUST 优先保留目录路径后缀，舍弃前缀部分，以保持语义可读性
- **FR-012**: 系统 MUST 在 `~/.remote-claude/runtime.json` 中维护原始路径与截断名称的映射关系
- **FR-013**: 当截断名称冲突时，系统 MUST 检测原始目录是否为同一个；若非同一个，MUST 加入随机后缀确保唯一性
- **FR-014**: `runtime.json` 文件结构 MUST 灵活可扩展，支持存储 session 映射、lark_group_mappings、UI 设置等运行时状态
- **FR-015**: 快捷命令选择器功能 MUST 默认关闭，通过 `ui_settings.quick_commands.enabled` 配置项控制
- **FR-016**: 快捷命令列表 MUST 从 `ui_settings.quick_commands.commands` 配置项读取，支持用户自定义
- **FR-017**: 快捷命令 ONLY 支持无参数命令，不支持带参数的命令模板
- **FR-017a**: QuickCommand `value` 最大长度为 32 字符（2026-03-19 澄清：原 16 字符过于保守，调整为 32 字符）
- **FR-018**: 当 `commands` 列表为空或缺失时，MUST 不显示快捷命令选择器
- **FR-019**: 系统启动时 MUST 检查旧 `lark_group_mapping.json` 文件，自动迁移到 `runtime.json` 的 `lark_group_mappings` 字段，迁移后删除旧文件
- **FR-020**: 所有使用群组映射的功能 MUST 统一使用 `runtime.json` 中的 `lark_group_mappings` 字段，不再维护独立的配置文件
- **FR-021**: `session_mappings` 映射数量 SHOULD 限制为 500 条，超出时输出警告提示，但允许继续添加（软限制）
- **FR-021a**: `runtime.json` 并发写入 MUST 使用文件锁（fcntl.flock）保护
- **FR-021b**: 配置文件损坏备份 SHOULD 保留最近 2 个备份文件，自动清理更早的备份
- **FR-021c**: 截断名称冲突且原始目录不同时，MUST 直接使用完整 MD5 哈希作为最终名称（不重试随机后缀）
- **FR-022**: `runtime.json` 版本升级时 MUST 实现迁移函数，按版本号逐步升级配置，保留用户设置
- **FR-023**: `remote-claude list` MUST 展示截断名称、原始路径和原有信息（三列展示）
- **FR-024**: 原始路径 MUST 从 `runtime.json` 的 `session_mappings` 反查，无映射时显示 `-`
- **FR-025**: 配置文件 MUST 拆分为 `config.json`（用户可编辑配置）和 `runtime.json`（程序自动管理状态）
- **FR-026**: `config.json` MUST 存储 `ui_settings` 等用户可编辑配置
- **FR-027**: `runtime.json` MUST 存储 `session_mappings`、`lark_group_mappings` 等程序自动管理状态
- **FR-028**: 文件锁 MUST 命名为 `runtime.json.lock`，与配置文件同目录
- **FR-029**: 锁文件 MUST 写入详细信息（用途说明、创建进程 PID、创建时间），便于用户理解和调试
- **FR-030**: 会话退出（kill/exit）时 MUST 删除 `session_mappings` 中对应映射条目
- **FR-031**: 会话退出时 MUST NOT 删除 `lark_group_mappings`（保留群组绑定便于重连）
- **FR-032**: 配置迁移/修改完成后 MUST 立即删除 `.bak` 备份文件
- **FR-033**: 启动时检测到残留 `.bak` 文件 MUST 提示用户选择：覆盖（重新迁移）或跳过（删除 bak 继续）
- **FR-034**: 正常运行时 MUST NOT 存在 `.bak` 文件（保证配置目录清洁）
- **FR-035**: README.md 和 CLAUDE.md MUST 与配置文件架构保持一致（更新 runtime.json/config.json 说明）
- **FR-036**: 飞书卡片交互（按钮点击、文本框输入提交）MUST 使用 `update_card` API 就地更新原卡片
- **FR-037**: 交互过程中卡片 MUST 显示状态变化（按钮 disabled、"处理中"等视觉反馈）
- **FR-038**: 单行文本输入框 MUST 支持回车键自动提交
- **FR-039**: 多行文本框 MUST 保留回车换行行为（不触发自动提交）
- **FR-040**: 空输入 MUST 不触发提交（输入校验）
- **FR-041**: 截断处理时连续下划线 MUST 合并为单下划线（如 `a__b` → `a_b`）
- **FR-042**: QuickCommand `icon` 字段无格式限制，可为空，空时使用空白占位 emoji
- **FR-043**: `commands` 超过 20 条时 MUST 静默截断（只显示前 20 条）
- **FR-044**: 配置文件权限不足时 MUST 使用内存配置继续运行，输出警告日志
- **FR-045**: 空会话名 MUST 拒绝启动并提示"会话名不能为空"
- **FR-046**: `disconnected` 状态 MUST 使用实时检测（每次需要时检查 bridge.running 状态）
- **FR-047**: 快捷命令发送时会话已断开 MUST 显示提示"会话已断开，请重新连接后重试"
- **FR-048**: 无效日志级别 MUST 输出警告日志后回退到默认值 WARNING（30）
- **FR-049**: init.sh MUST 使用 shell 脚本直接执行配置初始化和迁移（不调用 Python 函数）
- **FR-050**: init.sh MUST 迁移旧 `lark_group_mapping.json` 到 `runtime.json` 的 `lark_group_mappings` 字段
- **FR-051**: init.sh MUST 创建默认 `config.json`（含默认 UI 设置）
- **FR-052**: `LARK_CLIENT_GUIDE.md` MUST 移动到 `lark_client/` 目录
- **FR-053**: 配置文件写入前 MUST 先备份当前文件
- **FR-054**: 启动时若检测到备份文件残留 MUST 按时间戳从新到旧找第一个有效备份并提示用户恢复
- **FR-055**: `remote-claude config reset --all` MUST 重置全部配置文件
- **FR-056**: `remote-claude config reset --config` MUST 仅重置 config.json
- **FR-057**: `remote-claude config reset --runtime` MUST 仅重置 runtime.json
- **FR-058**: `remote-claude config reset` 无参数时 MUST 进入交互式选择模式
- **FR-059**: 配置回退时 MUST 清理与被重置配置相关的副作用文件（锁文件、备份文件），清理范围与重置范围保持一致
- **FR-060**: 配置回退时 MUST NOT 清理状态文件（lark.pid、lark.status）
- **FR-061**: `--config` 重置时 MUST 只清理 `config.json.lock` 和 `config.json.bak.*` 文件
- **FR-062**: `--runtime` 重置时 MUST 只清理 `runtime.json.lock` 和 `runtime.json.bak.*` 文件
- **FR-063**: `--all` 重置时 MUST 清理所有锁文件（`*.lock`）和所有备份文件（`*.json.bak.*`）
- **FR-064**: `utils/session.py` 和 `utils/runtime_config.py` 之间 MUST NOT 存在模块级循环依赖
- **FR-065**: 路径常量（`SOCKET_DIR`、`USER_DATA_DIR`、`TMUX_SESSION_PREFIX`）MUST 集中定义在 `utils/session.py`
- **FR-066**: 路径函数（`get_socket_path`、`get_pid_file`、`get_mq_path` 等）MUST 集中定义在 `utils/session.py`
- **FR-067**: `resolve_session_name()` 中的 `runtime_config` 导入 MUST 使用延迟导入（函数内导入）避免循环依赖
- **FR-068**: Docker 构建优化 MUST 同时使用依赖安装缓存优化和多阶段构建优化
- **FR-069**: Docker 镜像内 MUST 使用 pnpm 替代 npm 加速依赖安装，本地开发仍用 npm
- **FR-070**: Docker 测试完成后 MUST 提取 `.venv` 和关键脚本到 `test_results/` 目录
- **FR-071**: 提取的产物 MUST 可在宿主机直接运行，bin 下脚本可直接执行
- **FR-072**: docker-test.sh MUST 使用三级计数体系（PASSED + WARNINGS + FAILED）
- **FR-073**: docker-test.sh 最终报告 MUST 明确区分核心失败和非核心失败
- **FR-074**: 测试文件不存在 MUST 视为测试失败，使用 `log_error` 并更新 FAILED 计数
- **FR-075**: README.md MUST 补充快速验证命令示例
- **FR-076**: README.md MUST 补充开发者验证手册（完整流程 + 本地调试 + CI/CD 集成）
- **FR-077**: 项目 MUST 自带便携式 Python（用户无需预装 Python）
- **FR-078**: 项目 MUST 使用 uv 管理 Python 版本和依赖，自动创建隔离环境
- **FR-079**: Docker 镜像 MUST 在构建时创建 venv，测试运行时激活使用
- **FR-080**: Docker 产物提取 MUST 包含便携式 Python（宿主机无需预装）
- **FR-081**: 安装包/Docker 镜像 MUST 预装 uv 管理的 Python，无需运行时下载

### Key Entities

- **SessionName**: 会话名称，可能包含路径分隔符和特殊字符，需要转换为合法的文件名
- **SocketPath**: Socket 文件路径，格式为 `/tmp/remote-claude/<safe_filename>.sock`
- **QuickCommand**: 快捷命令对象，包含 label（显示名称）、value（命令值）、icon（图标）
- **LogLevel**: 日志级别枚举（DEBUG=10, INFO=20, WARNING=30, ERROR=40）
- **RuntimeConfig**: 运行时配置对象，存储于 `~/.remote-claude/runtime.json`，包含 session_mappings、lark_group_mappings 等程序自动管理的状态
- **UserConfig**: 用户配置对象，存储于 `~/.remote-claude/config.json`，包含 ui_settings 等用户可编辑的配置
- **QuickCommandsConfig**: 快捷命令配置对象，包含 `enabled`（布尔开关）和 `commands`（QuickCommand 列表）字段
- **QuickCommand**: 快捷命令对象，包含 label（显示名称）、value（命令值，无参数）、icon（图标）
- **LockFile**: 文件锁对象，存储于 `~/.remote-claude/runtime.json.lock`，包含用途说明、创建进程 PID、创建时间
- **CardUpdateMode**: 卡片更新模式枚举（UPDATE = 就地更新，REPLACE = 推送新卡片）
- **TextInputBox**: 文本输入框对象，包含 `is_multiline`（是否多行）、`enter_action`（回车行为：submit/newline）
- **BackupFile**: 备份文件对象，命名格式为 `<config_name>.json.bak.<timestamp>`，用于配置恢复

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户可以使用任意长度的会话名称启动会话，不会因路径超限而失败
- **SC-002**: 超长会话名（**>80 字节，即超过 `_MAX_FILENAME` 限制**）启动成功率达到 100%
- **SC-003**: 飞书用户通过命令选择器发送命令的时间比手动输入减少 50% 以上
- **SC-004**: 默认日志输出量相比之前（INFO 级别）减少约 70%
- **SC-005**: 所有命令的 `--help` 输出无错误信息，成功率 100%
- **SC-006**: 新用户首次使用快捷命令选择器的成功率 > 90%
- **SC-007**: 截断后的会话名能保留最关键的目录标识信息（**可量化标准：截断后名称应包含至少一个完整路径段，且用户能在 5 秒内识别对应的原路径**）
- **SC-008**: 不同原始路径产生相同截断名称时，100% 正确检测冲突并确保唯一性
- **SC-009**: 通过 `runtime.json` 可 100% 反查任意截断名称的原始路径
- **SC-010**: `remote-claude list` 展示原始路径成功率 100%（有映射时显示路径，无映射时显示 `-`）
- **SC-011**: 配置文件拆分后，用户配置和程序状态隔离正确率 100%
- **SC-012**: 会话退出后，映射清理成功率达 100%
- **SC-013**: 锁文件包含完整信息（用途、PID、时间），用户理解率达 95%
- **SC-014**: 配置迁移完成后 bak 文件删除成功率达 100%
- **SC-015**: 残留 bak 文件启动检测和提示覆盖率达 100%
- **SC-016**: 正常运行时 bak 文件残留率为 0%
- **SC-017**: README.md 和 CLAUDE.md 文档与实现一致性达 100%
- **SC-018**: 卡片交互就地更新成功率达 100%（无新卡片推送）
- **SC-019**: 交互过程视觉反馈显示率达 100%（按钮 disabled、"处理中"等）
- **SC-020**: 单行文本框回车自动提交成功率达 100%
- **SC-021**: 多行文本框回车换行正确率达 100%（无误提交）
- **SC-022**: 空输入提交拦截率达 100%
- **SC-023**: init.sh 配置初始化成功率达 100%（首次安装和升级迁移）
- **SC-024**: 配置回退命令执行成功率达 100%
- **SC-025**: 配置回退后副作用文件清理率达 100%（锁文件、备份文件）
- **SC-026**: 配置回退后状态文件保留率达 100%（lark.pid、lark.status）
- **SC-027**: `--config` 重置后，`runtime.json.lock` 和 `runtime.json.bak.*` 文件保留率达 100%
- **SC-028**: `--runtime` 重置后，`config.json.lock` 和 `config.json.bak.*` 文件保留率达 100%
- **SC-029**: `utils/session.py` 和 `utils/runtime_config.py` 之间无模块级循环依赖验证通过率 100%
- **SC-030**: 路径常量和函数集中定义验证通过率 100%（无散落的路径定义）
- **SC-031**: Docker 构建时间相比优化前减少 20% 以上
- **SC-032**: Docker 产物提取成功率 100%（.venv 和 bin 脚本完整）
- **SC-033**: 提取产物在宿主机可运行成功率达 95%（依赖 Python 版本兼容）
- **SC-034**: docker-test.sh PASSED + WARNINGS + FAILED 总数与测试项数量一致率达 100%
- **SC-035**: README.md Docker 验证章节完整性达 100%（快速验证 + 开发者手册 + CI/CD 示例）
- **SC-036**: 用户无需预装 Python 即可成功运行项目（便携式验证通过率 100%）
- **SC-037**: uv 自动创建隔离环境成功率达 100%
- **SC-038**: Docker 产物在无 Python 环境的宿主机可运行成功率达 95%
- **SC-039**: 安装脚本（install.sh）执行成功率达 100%

## Assumptions

1. **平台兼容性**：假设用户主要使用 macOS 和 Linux 系统
2. **命令覆盖**：初始快捷命令列表基于常用场景，后续可根据用户反馈扩展
3. **日志级别**：假设 WARNING 级别能满足生产环境需求，调试时使用 DEBUG
4. **argparse 行为**：假设 argparse 的默认 `--help` 处理已满足需求
5. **文件安全**：假设运行环境为单用户本地机器，`runtime.json` 无需特殊权限保护
6. **uv 可用性**：假设 uv 可通过安装脚本自动安装（便携式 Python 策略）

## Dependencies

1. **飞书卡片 API**：快捷命令选择器依赖飞书 `select_static` 或类似交互元素支持
2. **argparse 库**：Help 参数处理依赖 Python argparse 模块
3. **hashlib 库**：会话名转换依赖 Python hashlib 模块（已使用）
4. **uv 包管理器**：便携式 Python 环境依赖 uv 自动管理（新增）

## Out of Scope

1. **Windows 平台支持**：当前不考虑 Windows 的 socket 路径限制
2. **命令历史记录**：不记录用户选择的快捷命令历史
3. **带参数命令**：快捷命令不支持带参数的命令模板（如 `/attach <session>`）
4. **多语言日志**：不考虑日志多语言支持
5. **国际化支持**：仅支持中文界面和提示，不考虑多语言切换
6. **系统 Python 集成**：不考虑使用系统已安装的 Python（便携式策略）
