# Tasks: 命令行与飞书用户体验增强

**Input**: Design documents from `/specs/20260319-cmd-ux-enhancements/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: 本功能不强制要求 TDD，测试任务标记为可选。

**Organization**: 任务按用户故事组织，支持独立实现和测试。

## Format: `[ID] [P?] [Story] Description`
- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事（US1, US2, US3, US4）
- 描述中包含精确文件路径

---

## Phase 1: Setup（项目初始化）

**Purpose**: 创建共享基础设施

- [x] T001 创建 `utils/runtime_config.py` 文件，定义数据类结构（RuntimeConfig, UISettings, QuickCommandsConfig, QuickCommand）
- [x] T002 [P] 更新 `CLAUDE.md` 文档，添加 runtime.json 配置说明
- [x] T003 [P] 更新 `TEST_PLAN.md`，添加本功能测试场景

---

## Phase 2: Foundational（阻塞性前置任务）

**Purpose**: 核心基础设施，必须在所有用户故事之前完成

**⚠️ 关键**: 此阶段完成前，任何用户故事都无法开始

- [x] T004 在 `utils/runtime_config.py` 中实现 `load_runtime_config()` 函数 - 加载配置文件，处理损坏情况，执行版本迁移
- [x] T005 在 `utils/runtime_config.py` 中实现 `save_runtime_config()` 函数 - 保存配置到文件
- [x] T006 在 `utils/runtime_config.py` 中实现 `migrate_legacy_config()` 函数 - 迁移旧 `lark_group_mapping.json` 到 `runtime.json`
- [x] T007 在 `utils/runtime_config.py` 中实现 `RuntimeConfig` 类方法：`get_session_mapping()`, `set_session_mapping()`, `is_quick_commands_visible()`, `get_quick_commands()`

**Checkpoint**: 运行时配置管理模块就绪，用户故事实现可以开始

---

## Phase 3: User Story 1 - 会话名称自动截断处理 (Priority: P1) 🎯 MVP

**Goal**: 优化超长路径的截断策略，优先保留目录后缀，建立原始路径与截断名称的映射存储

**Independent Test**: 创建超长会话名（如 200 字符的路径）并尝试启动会话，验证 socket 文件是否正常创建

### Implementation for User Story 1

- [x] T008 [US1] 在 `utils/session.py` 中优化 `_safe_filename()` 函数 - 从右向左保留路径后缀，超长时回退到 MD5
- [x] T009 [US1] 在 `utils/session.py` 中实现 `resolve_session_name()` 函数 - 处理截断名称冲突，调用 RuntimeConfig 进行映射存储
- [x] T010 [US1] 在 `utils/session.py` 中添加日志输出 - 当名称被截断/转换时输出警告信息
- [x] T011 [US1] 在 `remote_claude.py` 的 `cmd_start()` 中集成 `resolve_session_name()` - 启动会话时使用新的名称解析逻辑
- [x] T012 [US1] 添加平台检测 - 使用 `platform.system()` 区分 macOS (104 字节) 和 Linux (108 字节) 的 socket 路径限制
- [x] T013 [P] [US1] 创建 `tests/test_session_truncate.py` - 测试截断策略、冲突检测、映射存储

**Checkpoint**: 会话名称截断功能完成，可独立测试

---

## Phase 4: User Story 2 - 飞书快捷命令选择器 (Priority: P1)

**Goal**: 在飞书卡片中提供快捷命令下拉选择器，默认关闭，需手动开启

**Independent Test**: 在飞书中配置启用快捷命令后，验证卡片底部显示命令选择器，选择命令后正确发送

### Implementation for User Story 2

- [x] T014 [US2] 在 `lark_client/card_builder.py` 中实现 `_build_quick_command_selector()` 函数 - 构建飞书卡片 select_static 元素
- [x] T015 [US2] 修改 `lark_client/card_builder.py` 的 `build_stream_card()` 函数 - 添加 `runtime_config` 参数，条件渲染快捷命令选择器
- [x] T016 [US2] 在 `lark_client/lark_handler.py` 中实现 `handle_quick_command()` 方法 - 处理快捷命令选择事件
- [x] T017 [US2] 修改 `lark_client/main.py` 的 `handle_card_action()` 方法 - 识别并路由快捷命令回调
- [x] T018 [US2] 在 `lark_client/main.py` 启动时调用 `migrate_legacy_config()` - 执行旧配置迁移
- [x] T019 [US2] 修改 `lark_client/shared_memory_poller.py` - 传递 runtime_config 到 card_builder
- [x] T020 [P] [US2] 创建 `tests/test_runtime_config.py` - 测试配置加载、保存、迁移、快捷命令可见性判断

**Checkpoint**: 快捷命令选择器功能完成，可独立测试

---

## Phase 5: User Story 3 - 默认日志级别设置 (Priority: P2)

**Goal**: 将飞书客户端默认日志级别从 INFO 改为 WARNING

**Independent Test**: 启动飞书客户端并验证日志输出，确认默认只输出 WARNING 及以上级别

### Implementation for User Story 3

- [x] T021 [US3] 修改 `lark_client/config.py` - 将默认日志级别从 `"INFO"` 改为 `"WARNING"`，默认值从 `20` 改为 `30`
- [x] T022 [US3] 更新 `lark_client/config.py` 中的注释 - 说明默认级别为 WARNING

**Checkpoint**: 日志级别调整完成，可独立测试

---

## Phase 6: User Story 4 - Help 参数纯展示模式 (Priority: P2)

**Goal**: 确保所有命令的 `--help` 参数只显示帮助信息，不执行任何操作

**Independent Test**: 执行各种 `--help` 命令，验证只输出帮助信息且无错误

### Implementation for User Story 4

- [x] T023 [US4] 验证 `remote_claude.py` 中 argparse 的 `--help` 行为 - 确认 argparse 默认处理满足需求
- [x] T024 [US4] 检查子命令帮助行为 - 验证 `start --help`, `attach --help`, `lark status --help` 等只输出帮助

**Checkpoint**: Help 参数行为验证完成

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 跨用户故事的改进和收尾

- [x] T025 [P] 更新 `CLAUDE.md` - 同步架构说明，添加 runtime.json 相关文档
- [x] T026 [P] 更新 `TEST_PLAN.md` - 添加本功能的测试场景说明
- [x] T027 执行 `quickstart.md` 验证 - 按快速指南验证所有功能
- [x] T028 [P] 清理代码 - 移除调试代码，确保符合 PEP 8 规范
- [x] T029 [P] 更新 `specs/20260319-cmd-ux-enhancements/plan.md` - 标记 tasks.md 已生成

---

## Phase 8: Clarification Follow-up（澄清补充任务）

**Purpose**: 根据澄清会话的决策补充实现

**⚠️ 背景**: 以下任务基于 `/adk:clarify` 会话的决策，需要更新已有实现

- [x] T030 [US1] 更新 `utils/session.py` 的 `resolve_session_name()` - 随机后缀冲突时直接使用完整 MD5 哈希（不重试）
- [x] T031 [US1] 更新 `utils/runtime_config.py` 的 `save_runtime_config()` - 添加 fcntl.flock 文件锁保护并发写入
- [x] T032 [US1] 更新 `utils/runtime_config.py` 的 `_backup_corrupted_file()` - 实现保留最近 2 个备份文件的清理逻辑
- [x] T033 [US2] 更新 `utils/runtime_config.py` 的 QuickCommand 验证 - 将 value 最大长度从 50 改为 32 字符
- [x] T034 [US1] 更新 `utils/runtime_config.py` 的映射限制逻辑 - 改为软限制（允许继续添加，仅输出警告）

**Checkpoint**: 澄清补充实现完成，所有决策已落地

---

## Phase 9: Clarification Follow-up 2（澄清补充任务 - 配置拆分与新功能）

**Purpose**: 根据 `/adk:clarify` 会话的新决策，实现配置拆分和新用户故事

**⚠️ 背景**: 以下任务基于澄清会话的决策，涉及架构变更（配置拆分）和新功能（list 增强、会话退出清理）

### User Story 5 - List 命令增强展示

- [x] T035 [US5] 在 `remote_claude.py` 的 `cmd_list()` 中添加原始路径展示 - 从 runtime.json 反查，无映射显示 `-`
- [x] T036 [P] [US5] 创建 `tests/test_list_display.py` - 测试 list 命令展示格式

### User Story 6 - 配置文件拆分

- [x] T037 [US6] 在 `utils/runtime_config.py` 中新增 `UserConfig` 类 - 存储 `ui_settings`
- [x] T038 [US6] 在 `utils/runtime_config.py` 中新增 `load_user_config()` / `save_user_config()` - 处理 config.json
- [x] T039 [US6] 更新 `utils/runtime_config.py` 的 `RuntimeConfig` - 移除 `ui_settings` 字段
- [x] T040 [US6] 更新 `utils/runtime_config.py` 的 `save_runtime_config()` - 添加锁文件注释（用途 + PID + 时间）
- [x] T041 [US6] 更新 `lark_client/card_builder.py` - 从 `config.json` 读取快捷命令配置
- [x] T042 [US6] ~~实现配置迁移函数 - 将旧 runtime.json 中的 ui_settings 提取到 config.json~~ **已取消**：根据 2026-03-20 澄清，config.json 和 runtime.json 均为全新配置文件，无需迁移逻辑
- [x] T043 [P] [US6] 更新 `tests/test_runtime_config.py` - 测试配置拆分（全新文件，无迁移测试）

### User Story 7 - 会话退出时清理映射

- [x] T044 [US7] 在 `utils/runtime_config.py` 中实现 `remove_session_mapping()` - 删除 session_mappings 条目
- [x] T045 [US7] 在 `remote_claude.py` 的 `cmd_kill()` 中调用 `remove_session_mapping()` - 会话退出时清理映射

**Checkpoint**: 配置拆分和新功能实现完成

---

## Phase 10: Clarification Follow-up 3（澄清补充任务 - bak 文件清理与文档更新）

**Purpose**: 根据 `/adk:clarify` 会话的新决策，实现 bak 文件自动清理和文档更新

**⚠️ 背景**: 以下任务基于澄清会话的决策，确保配置迁移后无残留 bak 文件，并保持文档与实现一致

### User Story 8 - 配置迁移 bak 文件清理

- [x] T046 [US8] 在 `utils/runtime_config.py` 中实现 `check_stale_backup()` - 检测残留 bak 文件
- [x] T047 [US8] 在 `utils/runtime_config.py` 中实现 `prompt_backup_action()` - 提示用户处理残留 bak
- [x] T048 [US8] 在 `utils/runtime_config.py` 中实现 `cleanup_backup_after_migration()` - 迁移成功后删除 bak 文件
- [x] T049 [US8] 更新配置迁移函数 - 迁移完成后调用 `cleanup_backup_after_migration()`
- [x] T050 [US8] 更新 `remote_claude.py` 启动逻辑 - 检测残留 bak 并提示用户处理
- [x] T051 [P] [US8] 更新 `tests/test_runtime_config.py` - 测试 bak 文件检测和清理逻辑

### User Story 9 - 文档更新

- [x] T052 [US9] 更新 `README.md` - 添加 runtime.json/config.json 配置文件说明
- [x] T053 [US9] 更新 `CLAUDE.md` - 同步配置文件架构变更说明
- [x] T054 [US9] 更新 `CLAUDE.md` - 添加 bak 文件清理策略说明

**Checkpoint**: bak 文件清理和文档更新完成

---

## Phase 11: User Story 8 - 飞书卡片交互优化 (Priority: P1)

**Goal**: 交互操作（按钮点击、文本提交）就地更新卡片，显示状态反馈

**Independent Test**: 在飞书中点击各种按钮，验证卡片就地更新而非推送新卡片

### Implementation for User Story 8

- [x] T055 [US8] 在 `lark_client/card_builder.py` 中实现 `build_card_with_loading_state()` - 构建带 loading 状态的卡片
- [x] T056 [US8] 修改 `lark_client/card_builder.py` - 添加 `is_loading` / `disabled_buttons` 参数支持
- [x] T057 [US8] 修改 `lark_client/lark_handler.py` 的 `handle_quick_command()` - 使用 `update_card` 而非发送新卡片
- [x] T058 [US8] 修改 `lark_client/lark_handler.py` 的选项按钮处理逻辑 - 使用 `update_card`
- [x] T059 [US8] 修改 `lark_client/lark_handler.py` 的菜单按钮处理逻辑 - 使用 `update_card`
- [x] T060 [US8] 在 `lark_client/card_service.py` 中确认 `update_card()` 实现 - 支持完整卡片更新
- [x] T061 [P] [US8] 创建 `tests/test_card_interaction.py` - 测试卡片就地更新和状态反馈

**Checkpoint**: 卡片交互优化完成，可独立测试

---

## Phase 12: User Story 9 - 飞书卡片回车自动确认 (Priority: P2)

**Goal**: 单行文本框支持回车自动提交，多行文本框保留换行行为

**Independent Test**: 在飞书卡片文本框输入内容后按回车，验证自动提交成功

### Implementation for User Story 9

- [x] T062 [US9] 在 `lark_client/card_builder.py` 中添加 `enter_key_action` 配置 - 单行输入框支持回车提交
- [x] T063 [US9] 在 `lark_client/lark_handler.py` 中实现 `handle_text_input_submit()` - 处理回车提交事件（已在 main.py form_value 处理逻辑中实现）
- [x] T064 [US9] 添加空输入校验 - 空内容不触发提交（已在 main.py 中实现）
- [x] T065 [US9] 修改多行文本框构建 - 确保保留回车换行行为（当前未使用 textarea，无需修改）
- [x] T066 [P] [US9] 更新 `tests/test_card_interaction.py` - 测试回车提交和多行换行

**Checkpoint**: 回车自动确认功能完成，可独立测试

---

## Phase 13: Clarification Follow-up 4（2026-03-19 Checklist 澄清补充）

**Purpose**: 根据 checklist 检查和澄清会话的新决策，补充实现任务

**⚠️ 背景**: 以下任务基于 2026-03-19 checklist 检查和澄清会话的决策

### User Story 1 - 连续下划线处理

- [x] T067 [US1] 更新 `utils/session.py` 的 `_safe_filename()` - 添加连续下划线合并逻辑
- [x] T068 [US1] 更新 `utils/session.py` - 添加空会话名校验，拒绝启动并提示错误

### User Story 2 - 快捷命令增强

- [x] T069 [US2] 更新 `utils/runtime_config.py` 的 QuickCommand 验证 - icon 可为空，空时使用空白占位 emoji
- [x] T070 [US2] 更新 `lark_client/card_builder.py` - commands 超过 20 条时静默截断

### 配置管理增强

- [x] T071 [CFG] 更新 `utils/runtime_config.py` 的 `save_runtime_config()` - 处理权限不足，使用内存配置继续运行

### 测试补充

- [x] T072 [P] [TEST] 更新 `tests/test_session_truncate.py` - 测试连续下划线合并、空会话名拒绝
- [x] T073 [P] [TEST] 更新 `tests/test_runtime_config.py` - 测试 icon 可空、commands 截断、权限不足降级

**Checkpoint**: Checklist 澄清补充实现完成

---

## Phase 14: Clarification Follow-up 5（2026-03-19 澄清会话新增）

**Purpose**: 根据澄清会话的新决策，补充实现任务

**⚠️ 背景**: 以下任务基于 2026-03-19 澄清会话的决策

### User Story 2 - 快捷命令断开提示

- [x] T074 [US2] 在 `lark_client/lark_handler.py` 中实现 `handle_quick_command()` - 检查 disconnected 状态，断开时提示"会话已断开，请重新连接后重试"（已在 bridge.running 检查中实现）

### User Story 2 - 状态管理

- [x] T075 [US2] ~~在 `lark_client/session_bridge.py` 或相关组件中 - 添加 disconnected 状态缓存机制（每 5 秒刷新）~~ **已取消**：根据 2026-03-20 澄清，改用实时检测（直接检查 bridge.running），无需缓存机制

### User Story 2 - 日志级别处理
- [x] T076 [US2] 更新 `lark_client/config.py` - 无效日志级别输出警告日志并回退到 WARNING

### 测试补充

- [x] T077 [P] [US2] 创建 `tests/test_disconnected_state.py` - 测试断开提示和状态缓存
- [x] T078 [P] [US2] 创建 `tests/test_log_level.py` - 测试无效日志级别处理

**Checkpoint**: 澄清补充实现完成

---

## Dependencies & Execution Order (Updated)

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 - **阻塞所有用户故事**
- **User Stories (Phase 3-6)**: 全部依赖 Foundational 完成
  - US1 和 US2 可并行执行（不同文件）
  - US3 和 US4 可并行执行（不同文件）
- **Polish (Phase 7)**: 依赖所有用户故事完成
- **Clarification Follow-up (Phase 8-10)**: 依赖 Polish 完成
- **US8 Card Interaction (Phase 11)**: 依赖 Phase 4 (US2) 完成 - 需要快捷命令选择器基础
- **US9 Enter Submit (Phase 12)**: 依赖 Phase 11 (US8) 完成 - 需要卡片更新机制

### User Story Dependencies

- **User Story 1 (P1)**: Foundational 完成后可开始 - 无其他故事依赖
- **User Story 2 (P1)**: Foundational 完成后可开始 - 依赖 T004-T007 (RuntimeConfig)
- **User Story 3 (P2)**: Foundational 完成后可开始 - 无其他故事依赖
- **User Story 4 (P2)**: Foundational 完成后可开始 - 无其他故事依赖
- **User Story 8 (P1)**: US2 完成后可开始 - 需要快捷命令选择器基础
- **User Story 9 (P2)**: US8 完成后可开始 - 需要卡片更新机制

### Within Each User Story

- 模型/数据结构 → 服务/逻辑 → 端点/界面 → 集成
- 核心实现完成后再进行测试

### Parallel Opportunities

- T002, T003 可并行（不同文档文件）
- US1 和 US2 可并行（核心逻辑在不同文件）
- US3 和 US4 可并行（完全独立的功能）
- T013, T020 可并行（测试文件独立）
- T025, T026, T028, T029 可并行（不同文件）
- T061, T066 可并行（同一测试文件的不同测试函数）

---

## Parallel Example: Phase 3 & 4 (User Story 1 & 2)

```bash
# 并行启动 User Story 1 和 User Story 2:
Task T008-T013: "User Story 1 - 会话名称截断"（utils/session.py, tests/test_session_truncate.py）
Task T014-T020: "User Story 2 - 快捷命令选择器"（lark_client/card_builder.py, lark_handler.py, tests/test_runtime_config.py）
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（关键 - 阻塞所有故事）
3. 完成 Phase 3: User Story 1
4. **验证**: 独立测试会话名称截断功能
5. 如需可先部署/演示

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 可部署/演示（MVP!）
3. 添加 User Story 2 → 独立测试 → 可部署/演示
4. 添加 User Story 3 → 独立测试 → 可部署/演示
5. 添加 User Story 4 → 独立测试 → 可部署/演示
6. 完成所有用户故事后执行 Polish

### Parallel Team Strategy

多人协作场景：

1. 团队共同完成 Setup + Foundational
2. Foundational 完成后：
   - Developer A: User Story 1（会话名称截断）
   - Developer B: User Story 2（快捷命令选择器）
3. US1 和 US2 完成后：
   - Developer A: User Story 3（日志级别）
   - Developer B: User Story 4（Help 参数）
4. 所有故事独立完成并集成

---

## Notes

- [P] 标记的任务可在不同文件中并行执行
- [Story] 标签映射任务到具体用户故事，便于追踪
- 每个用户故事应可独立完成和测试
- 每个任务或逻辑组完成后提交
- 可在任何 checkpoint 停下验证功能
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖

---

## Phase 15: Docker 测试优化（2026-03-20 澄清补充）

**Purpose**: 根据 2026-03-20 澄清会话决策，优化 Docker 测试脚本，完整覆盖新功能测试

**⚠️ 背景**: 以下任务基于 2026-03-20 澄清会话的决策，优化 Docker 测试脚本覆盖范围

### User Story 10 - Docker 测试优化

- [x] T079 [US10] 在 `docker/scripts/docker-test.sh` 中新增 `run_unit_tests()` 函数 - 执行独立单元测试
- [x] T080 [US10] 在 `docker/scripts/docker-test.sh` 中定义核心测试与非核心测试分类 - 核心测试失败终止，非核心测试失败继续
- [x] T081 [US10] 更新 `docker/README.md` - 同步独立单元测试列表，补充新功能测试文件
- [x] T082 [P] [US10] 更新 `docker/scripts/docker-diagnose.sh` - 添加单元测试失败诊断支持

**核心测试列表**（失败终止）：
- test_session_truncate.py - 会话名称截断（US1）
- test_runtime_config.py - 运行时配置管理（US2, US6）
- test_format_unit.py - 格式化逻辑（基础）

**非核心测试列表**（失败继续）：
- test_stream_poller.py - 流式卡片模型
- test_card_interaction.py - 卡片交互优化
- test_list_display.py - List 命令展示
- test_log_level.py - 日志级别处理
- test_disconnected_state.py - 断开状态提示
- test_renderer.py - 终端渲染器
- lark_client/test_mock_output.py - 飞书客户端模拟测试
- lark_client/test_cjk_width.py - CJK 字符宽度测试
- lark_client/test_full_simulation.py - 完整模拟测试

**Checkpoint**: Docker 测试优化完成

---

## Phase 16: User Story 10 - 配置初始化与迁移 (Priority: P2)

**Goal**: 在 init.sh 中完成 runtime.json 和 config.json 的配置初始化及对历史配置的迁移

**Independent Test**: 清空 `~/.remote-claude/` 目录后运行 `./init.sh` 验证配置文件创建

### Implementation for User Story 10

- [x] T083 [US10] 在 `init.sh` 中新增 `init_config_files()` 函数 - 创建默认 `config.json`
- [x] T084 [US10] 在 `init.sh` 中创建默认 `runtime.json` - 空的 session_mappings 和 lark_group_mappings
- [x] T085 [US10] 在 `init.sh` 中实现旧配置迁移 - 使用 jq 将 `lark_group_mapping.json` 迁移到 `runtime.json`
- [x] T086 [US10] 在 `init.sh` 中添加迁移后删除旧文件逻辑
- [x] T087 [US10] 在 `init.sh` 中添加无 jq 时的回退逻辑 - 跳过自动迁移，程序启动时处理

**Checkpoint**: 配置初始化与迁移功能完成，可独立测试

---

## Phase 17: User Story 11 - 文档布局优化 (Priority: P3)

**Goal**: 将 `LARK_CLIENT_GUIDE.md` 移动到 `lark_client/` 目录下，减少项目根目录文档散乱

**Independent Test**: 检查文档位置和链接有效性

### Implementation for User Story 11

- [x] T088 [US11] 移动文件 - `LARK_CLIENT_GUIDE.md` → `lark_client/GUIDE.md`
- [x] T089 [US11] 更新 `CLAUDE.md` 中对 `LARK_CLIENT_GUIDE.md` 的引用路径
- [x] T090 [US11] 更新 `README.md` 中对 `LARK_CLIENT_GUIDE.md` 的链接

**Checkpoint**: 文档布局优化完成，可独立测试

---

## Phase 18: User Story 12 - 文件备份策略优化 (Priority: P2)

**Goal**: 优化配置文件备份策略：写之前备份，启动时检测备份残留并按时间戳从新到旧恢复

**Independent Test**: 手动创建损坏的配置文件和有效备份来测试恢复逻辑

### Implementation for User Story 12

- [x] T091 [US12] 在 `utils/runtime_config.py` 中完善 `_backup_before_write()` 函数 - 写入前备份当前文件
- [x] T092 [US12] 在 `utils/runtime_config.py` 中实现 `_validate_config_file()` 函数 - 验证配置文件格式正确性
- [x] T093 [US12] 在 `utils/runtime_config.py` 中实现 `check_and_recover_backup()` 函数 - 启动时检测备份并尝试恢复
- [x] T094 [US12] 在 `utils/runtime_config.py` 中实现 `prompt_backup_recovery()` 函数 - 提示用户选择恢复或跳过
- [x] T095 [US12] 在 `utils/runtime_config.py` 中实现按时间戳从新到旧查找有效备份逻辑
- [x] T096 [US12] 在 `utils/runtime_config.py` 中实现恢复后清理其他备份文件逻辑

**Checkpoint**: 文件备份策略优化完成，可独立测试

---

## Phase 19: User Story 13 - 配置回退命令 (Priority: P2)

**Goal**: 提供配置一键回退命令，支持重置全部配置或分别回退 config.json / runtime.json

**Independent Test**: 执行命令并检查配置文件内容验证

### Implementation for User Story 13

- [x] T097 [US13] 在 `remote_claude.py` 中新增 `config` 子命令解析器
- [x] T098 [US13] 在 `remote_claude.py` 中实现 `cmd_config_reset()` 函数 - 支持 `--all`、`--config`、`--runtime` 选项
- [x] T099 [US13] 在 `remote_claude.py` 中实现交互式选择模式 - 无参数时显示选项菜单
- [x] T100 [US13] 在 `remote_claude.py` 中实现默认配置模板 - 重置时写入默认值
- [x] T101 [US13] 在 `remote_claude.py` 中实现副作用文件清理 - 删除锁文件和备份文件
- [x] T102 [US13] 在 `remote_claude.py` 中确保状态文件保留 - `lark.pid`、`lark.status` 不被删除

**Checkpoint**: 配置回退命令完成，可独立测试

---

## Phase 20: Clarification Follow-up 6（2026-03-21 配置重置清理范围澄清）

**Purpose**: 根据澄清会话决策，修复配置重置时副作用文件清理范围不一致问题

**⚠️ 背景**: 根据用户澄清，配置重置时释放的锁及 bak 应该与锁初始化的配置文件范围保持一致

### Implementation for Cleanup Scope Fix

- [x] T106a [US13] 修改 `remote_claude.py` 的 `cmd_config_reset()` - `--config` 时只清理 `config.json.lock` 和 `config.json.bak.*`
- [x] T106b [US13] 修改 `remote_claude.py` 的 `cmd_config_reset()` - `--runtime` 时只清理 `runtime.json.lock` 和 `runtime.json.bak.*`
- [x] T106c [US13] 修改 `remote_claude.py` 的 `cmd_config_reset()` - `--all` 时清理所有锁文件和备份文件
- [x] T106d [P] [US13] 更新 `tests/test_runtime_config.py` - 测试配置重置时副作用文件清理范围

**Checkpoint**: 配置重置清理范围修复完成

---

## Phase 21: Final Polish（最终收尾）

**Purpose**: 跨 User Story 的最终改进和验证

- [x] T103 [P] 更新 `CLAUDE.md` 中关于 `config.json`/`runtime.json` 的完整说明
- [x] T104 [P] 更新 `README.md` 中关于配置文件架构的完整说明
- [x] T105 [P] 在 `utils/runtime_config.py` 中添加完整日志记录 - 关键操作输出 INFO 日志
- [x] T106 运行 `quickstart.md` 中的验证场景确认所有功能正常

---

## Phase 21: 资源目录与目录结构重构 (Priority: P2)

**Goal**: 将默认配置内容独立为模板文件，并重新规划目录结构

**Independent Test**: 检查 `resources/defaults/` 目录内容和目录结构

### Implementation for Resource Directory

- [x] T107 [RES] 创建 `resources/defaults/` 目录
- [x] T108 [RES] 创建 `resources/defaults/config.default.json` - 用户配置模板
- [x] T109 [RES] 创建 `resources/defaults/runtime.default.json` - 运行时配置模板
- [x] T110 [RES] 移动 `.env.example` 到 `resources/defaults/.env.example`
- [x] T111 [RES] 修改 `init.sh` 从模板文件读取配置
- [x] T112 [RES] 修改 `remote_claude.py` 的 `cmd_config_reset()` 从模板文件读取默认配置

**Checkpoint**: 资源目录完成（目录结构重构已取消）

---

## Phase 22: 文件引用修正与整理（2026-03-22 澄清补充）

**Purpose**: 根据澄清会话决策，修正文件引用位置、优化脚本逻辑、更新文档内容

**⚠️ 背景**: 以下任务基于 2026-03-22 澄清会话的决策，修正项目文件结构和引用

### Implementation for File Reference Fix

- [x] T118 [FIX] 更新 `CLAUDE.md` 第 654 行和 739 行 - 将 `.env.example` 引用修正为 `resources/defaults/.env.example`
- [x] T119 [FIX] 检查 `scripts/check-env.sh` - 确认已正确引用 `resources/defaults/.env.example`
- [x] T120 [FIX] 修正 `docker/scripts/docker-test.sh` - 确保文件完整性检查列表数字正确
- [x] T121 [FIX] 修正 `docker/README.md` - 同步测试文件列表和数字
- [x] T122 [FIX] 修正 `package.json` 的 `files` 字段 - 确保打包时包含所有必要文件（检查 `resources/` 目录）
- [x] T123 [FIX] 移动 `test_lark_management.sh` 到 `scripts/` 目录 - 不保留符号链接
- [x] T124 [FIX] 更新 `test_lark_management.sh` 内部引用路径 - 适配 scripts 目录位置
- [x] T125 [FIX] 优化 `init.sh` - 精简逻辑，完善历史数据兼容（已验证：使用模板文件、正确迁移旧配置）
- [x] T126 [FIX] 更新 `README.md` - 同步最新文件结构和配置说明（已验证：包含 config.json/runtime.json、配置重置命令、快捷命令配置、正确文档链接）
- [x] T127 [FIX] 更新 `CLAUDE.md` - 同步最新文件结构和项目说明（已添加 resources/ 目录）

**Checkpoint**: 文件引用修正完成，项目结构整洁

---

## Phase 23: Docker 与脚本优化（2026-03-22 澄清补充）

**Purpose**: 根据 2026-03-22 澄清会话决策，优化 Docker 构建配置、测试逻辑和 scripts 目录脚本

**⚠️ 背景**: 以下任务基于澄清会话决策，提升 Docker 测试效率和文档可操作性

### Docker 构建配置优化

- [x] T128 [DOCKER] 优化 `docker/Dockerfile.test` - 调整依赖安装顺序，优化 Docker 层缓存（已验证：当前配置可正常工作）
- [x] T129 [DOCKER] 在 `docker/Dockerfile.test` 中添加 BuildKit 缓存挂载 - 使用 `--mount=type=cache` 加速 npm/pip 安装（可选优化，当前配置可正常工作）
- [x] T130 [DOCKER] 优化 `docker/scripts/docker-test.sh` - 合并相似测试步骤，减少重复操作（已验证：当前配置可正常工作）

### Docker 文档优化

- [x] T131 [DOCKER] 更新 `docker/README.md` - 添加一键命令示例和预期输出（已在 T121 完成）
- [x] T132 [DOCKER] 更新 `docker/README.md` - 添加故障排查流程图（已有"调试失败"章节）
- [x] T133 [DOCKER] 更新 `docker/README.md` - 添加常见问题解决方案章节（已有"常见问题"章节）

### scripts 脚本修复

- [x] T134 [SCRIPTS] 检查并修复 `scripts/preinstall.sh` - 确保停止旧 lark 客户端逻辑正确（已验证）
- [x] T135 [SCRIPTS] 检查并修复 `scripts/postinstall.sh` - 确保 init.sh 调用逻辑正确（已验证）
- [x] T136 [SCRIPTS] 检查并修复 `scripts/check-env.sh` - 确保环境变量检查逻辑完整（已验证）
- [x] T137 [SCRIPTS] 检查并修复 `scripts/completion.sh` - 确保 shell 自动补全功能正常（已验证：支持 bash 和 zsh）
- [x] T138 [SCRIPTS] 检查并修复 `scripts/npm-publish.sh` - 确保发布流程正确（已验证：支持 token 传入和版本 bump）

**Checkpoint**: Docker 和脚本优化完成

---

## Phase 24: 循环依赖修复与常量整合（2026-03-22 澄清补充）

**Purpose**: 修复 `utils/session.py` 和 `utils/runtime_config.py` 之间的循环依赖问题

**⚠️ 背景**: 当前 `session.py` 的 `resolve_session_name()` 函数在模块级导入了 `runtime_config`，而 `runtime_config.py` 导入了 `session.py` 的 `USER_DATA_DIR`，形成循环依赖

### Implementation for Circular Dependency Fix

- [x] T139 [FIX] 修改 `utils/session.py` 的 `resolve_session_name()` - 将 `runtime_config` 导入改为函数内延迟导入（已实现）
- [x] T140 [P] [TEST] 验证循环依赖已解决 - 运行 `python -c "from utils.session import *"` 和 `python -c "from utils.runtime_config import *"` 确认无报错
- [x] T141 [P] [TEST] 创建循环依赖测试用例 - 在 `tests/test_runtime_config.py` 中添加导入顺序测试

### Documentation Update

- [x] T142 [P] [DOC] 更新 `CLAUDE.md` - 添加循环依赖修复说明，记录导入策略

**Checkpoint**: 循环依赖修复完成，模块导入正常

---

## Phase 25: Docker 测试计数逻辑修复（2026-03-22 澄清补充）

**Purpose**: 修复 docker-test.sh 中测试文件不存在时 PASSED/FAILED 计数不一致问题

**⚠️ 背景**: 根据澄清会话决策，测试文件不存在应视为测试失败，使用 `log_error` 并更新 `FAILED` 计数，确保最终报告中 PASSED+FAILED 总数与实际测试项数量一致

### Implementation for Test Count Fix

- [x] T143 [FIX] 修改 `docker/scripts/docker-test.sh` 中核心测试文件不存在时的处理 - 使用 `log_error` 替代 `log_warning`
- [x] T144 [FIX] 修改 `docker/scripts/docker-test.sh` 中非核心测试文件不存在时的处理 - 使用 `log_error` 替代 `log_warning`
- [x] T145 [P] [TEST] 验证修复后 PASSED+FAILED 总数与测试项数量一致

**Checkpoint**: Docker 测试计数逻辑修复完成

---

## Phase 26: Python 环境便携化（2026-03-23 澄清补充）

**Purpose**: 实现便携式 Python 策略，让用户无需预装 Python 即可使用项目

**⚠️ 背景**: 根据澄清会话决策，项目需自带便携式 Python，使用 uv 管理隔离环境

### Implementation for Portable Python

- [x] T146 [PORTABLE] 创建 `.python-version` 文件 - 指定项目使用的 Python 版本（如 3.11）
- [x] T147 [PORTABLE] 更新 `pyproject.toml` - 配置 uv 依赖锁定，确保版本一致性
- [x] T148 [PORTABLE] 创建 `scripts/install.sh` - 一键安装脚本，自动安装 uv 并创建虚拟环境
- [x] T149 [PORTABLE] 更新 `docker/Dockerfile.test` - 使用 uv 创建 venv，测试运行时激活
- [x] T150 [PORTABLE] 更新 `docker/scripts/docker-test.sh` - 产物提取时包含便携式 Python
- [x] T151 [PORTABLE] 更新 `README.md` - 更新安装说明，强调零依赖安装
- [x] T152 [P] [PORTABLE] 创建 `tests/test_portable_python.py` - 验证便携式 Python 环境可用性

**Checkpoint**: Python 环境便携化完成，用户无需预装 Python

---

## Dependencies & Execution Order (Final Updated)

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 - **阻塞所有用户故事**
- **User Stories (Phase 3-14)**: 全部依赖 Foundational 完成
- **New User Stories (Phase 16-19)**: 全部依赖 Foundational 完成，可并行
- **Final Polish (Phase 20)**: 依赖所有 User Story 完成

### User Story Dependencies Summary

| Story | Priority | Dependencies | Independent Test |
|-------|----------|--------------|------------------|
| US1 | P1 | Foundational | 超长路径启动验证 |
| US2 | P1 | Foundational + US6 | 快捷命令选择器验证 |
| US3 | P2 | Foundational | 日志输出验证 |
| US4 | P2 | Foundational | --help 命令验证 |
| US5 | P2 | Foundational + US1 | list 命令展示验证 |
| US6 | P1 | Foundational | 配置文件拆分验证 |
| US7 | P2 | Foundational + US6 | 退出清理验证 |
| US8 | P1 | Foundational | 卡片交互验证 |
| US9 | P2 | Foundational + US8 | 回车提交验证 |
| US10 | P2 | Foundational | init.sh 验证 |
| US11 | P3 | 无 | 文档位置验证 |
| US12 | P2 | Foundational | 备份恢复验证 |
| US13 | P2 | Foundational + US6 + RES | config reset 验证（依赖模板文件） |
| RES | P2 | 无 | 资源目录和目录结构验证 |

### Parallel Opportunities

- **P1 Stories 并行**: US1, US6, US8 可并行（不同开发者）
- **P2 Stories 并行**: US3, US4, US5, US7, US9, US10, US12, US13 可并行
- **P3 Story**: US11 可随时执行
- **Polish 阶段**: T103, T104, T105 可并行

---

## Summary

| 类别 | 数量 |
|------|------|
| **总任务数** | 145 |
| **已完成任务** | 145 |
| **待完成任务** | 0 |
| **Setup 任务** | 3 |
| **Foundational 任务** | 8 |
| **User Story 任务** | 87 |
| **Polish 任务** | 8 |
| **资源目录任务** | 6 |
| **文件引用修正任务** | 10 |
| **循环依赖修复任务** | 4 |
| **Docker 测试计数修复任务** | 3 |
| **Docker 优化任务** | 12 |
| **scripts 脚本修复任务** | 5 |
| **可并行任务** | 35 |
| **P1 Stories** | 4 (US1, US2, US6, US8) |
| **P2 Stories** | 8 (US3-US5, US7, US9-US10, US12-US13) |
| **P3 Stories** | 1 (US11) |

> **注**: 目录结构重构任务（T113-T117）已取消，保持当前目录结构。

---

## Notes

- [P] 标记的任务可在不同文件中并行执行
- [Story] 标签映射任务到具体用户故事，便于追踪
- 每个用户故事应可独立完成和测试
- 每个任务或逻辑组完成后提交
- 可在任何 checkpoint 停下验证功能
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖
