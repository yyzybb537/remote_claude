# 测试覆盖检查清单: 命令行与飞书用户体验增强

**Purpose**: 发布前测试场景覆盖验证，确保所有功能验收标准可测试、边界条件已覆盖
**Created**: 2026-03-19
**Feature**: `20260319-cmd-ux-enhancements`
**Depth**: 严格（发布门槛）
**Scope**: 全功能覆盖（9 个 User Story）
**Audience**: 测试人员 / 发布审核

**Note**: 本清单用于验证测试场景完整性，检查测试是否覆盖所有验收标准和边界条件。

---

## User Story 1 - 会话名称自动截断处理

### 主流程测试覆盖

- [x] CHK001 是否定义了超长路径（>100 字符）启动会话的测试场景？[主流程, spec.md US1 AS-1] ✅ test_session_truncate.py: test_safe_filename_truncate
- [x] CHK002 是否定义了正常长度名称不截断的测试场景？[主流程, spec.md US1 AS-2] ✅ test_session_truncate.py: test_safe_filename_normal
- [x] CHK003 是否定义了特殊字符替换的测试场景？[主流程, spec.md US1 AS-3] ✅ test_session_truncate.py: test_safe_filename_with_slash
- [x] CHK004 是否定义了截断策略（保留后缀）的测试场景？[主流程, spec.md US1 AS-4] ✅ test_session_truncate.py: test_safe_filename_truncate 验证保留后缀
- [x] CHK005 是否定义了映射写入 runtime.json 的测试场景？[主流程, spec.md US1 AS-1] ✅ test_session_truncate.py: test_runtime_config_session_mapping

### 冲突检测测试覆盖

- [x] CHK006 是否定义了不同原始路径产生相同截断名称时的冲突检测测试？[异常流程, spec.md US1 AS-5] ✅ test_runtime_config.py 验证 MD5 回退
- [x] CHK007 是否定义了同一目录重复启动复用会话的测试？[主流程, spec.md US1 AS-6] ✅ test_session_truncate.py: test_runtime_config_session_mapping
- [x] CHK008 是否定义了冲突时使用 MD5 哈希的测试？[异常流程, FR-021c] ✅ test_session_truncate.py: test_safe_filename_md5_fallback
- [x] CHK009 是否定义了映射反查的测试场景？[主流程, spec.md US1 AS-7] ✅ test_session_truncate.py: test_runtime_config_session_mapping

### 边界条件测试覆盖

- [x] CHK010 是否定义了路径长度恰好等于 `_MAX_FILENAME` 时的测试？[边界条件, Gap] ✅ 已定义：正常处理
- [x] CHK011 是否定义了 macOS vs Linux 不同路径限制（104 vs 108 字节）的测试？[跨平台, spec.md Edge Cases] ✅ test_session_truncate.py: test_max_filename_platform
- [x] CHK012 是否定义了 Unicode 字符路径的截断测试？[边界条件, Gap] ✅ 已定义：按字符处理
- [x] CHK013 是否定义了路径包含空格时的处理测试？[边界条件, spec.md Edge Cases] ✅ 已定义
- [x] CHK014 是否定义了空字符串会话名的行为测试？[边界条件, Gap] ✅ test_session_truncate.py: test_safe_filename_empty_name

### 平台兼容性测试覆盖

- [x] CHK015 是否定义了 platform.system() 检测 macOS/Linux 的测试？[技术实现, T012] ✅ test_session_truncate.py: test_max_filename_platform
- [x] CHK016 是否定义了 socket 文件创建成功的验证测试？[集成测试, spec.md US1] ✅ test_integration.py 集成测试覆盖

---

## User Story 2 - 飞书快捷命令选择器

### 可见性条件测试覆盖

- [ ] CHK017 是否定义了 `enabled=false` 时不显示选择器的测试？[主流程, spec.md US2 AS-1]
- [ ] CHK018 是否定义了 `enabled=true` 但 `commands=[]` 时不显示的测试？[主流程, spec.md US2 AS-2]
- [ ] CHK019 是否定义了 `enabled=true` 且 `commands` 非空时显示的测试？[主流程, spec.md US2 AS-3]
- [ ] CHK020 是否定义了 `disconnected=true` 时不显示的测试？[主流程, spec.md US2 AS-5]

### 命令发送测试覆盖

- [ ] CHK021 是否定义了选择命令后发送到会话的测试？[主流程, spec.md US2 AS-4]
- [ ] CHK022 是否定义了自定义命令列表显示的测试？[主流程, spec.md US2 AS-7]
- [ ] CHK023 是否定义了命令值以 `/` 开头的验证测试？[验证规则, data-model.md §4]
- [ ] CHK024 是否定义了命令值不能包含空格的验证测试？[验证规则, data-model.md §4]
- [ ] CHK025 是否定义了命令值最大 32 字符的边界测试？[边界条件, FR-017a]

### 配置迁移测试覆盖

- [ ] CHK026 是否定义了旧 `lark_group_mapping.json` 迁移到 `runtime.json` 的测试？[迁移, spec.md US2 AS-6]
- [ ] CHK027 是否定义了迁移后删除旧文件的测试？[迁移, FR-019]
- [ ] CHK028 是否定义了新旧配置同时存在时的处理测试？[异常流程, spec.md Edge Cases]

### 错误处理测试覆盖

- [ ] CHK029 是否定义了会话未连接时发送命令的提示测试？[错误处理, contracts/quick-command-selector.md]
- [ ] CHK030 是否定义了无效命令（如 `/unknown`）发送后的 CLI 错误返回测试？[错误处理, spec.md Edge Cases]
- [ ] CHK031 是否定义了飞书 API 回调事件解析的测试？[集成测试, contracts/quick-command-selector.md]

---

## User Story 3 - 默认日志级别设置

### 默认行为测试覆盖

- [ ] CHK032 是否定义了未设置环境变量时默认 WARNING 的测试？[主流程, spec.md US3 AS-1]
- [ ] CHK033 是否定义了 `LARK_LOG_LEVEL=DEBUG` 启用调试日志的测试？[主流程, spec.md US3 AS-2]
- [ ] CHK034 是否定义了 `LARK_LOG_LEVEL=INFO` 启用信息日志的测试？[主流程, spec.md US3 AS-3]

### 边界条件测试覆盖

- [ ] CHK035 是否定义了无效日志级别（如 `INVALID`）时的回退测试？[异常流程, spec.md Edge Cases]
- [ ] CHK036 是否定义了日志级别大小写不敏感的测试？[边界条件, Gap]

---

## User Story 4 - Help 参数纯展示模式

### 主流程测试覆盖

- [ ] CHK037 是否定义了 `remote-claude start --help` 只显示帮助的测试？[主流程, spec.md US4 AS-1]
- [ ] CHK038 是否定义了 `remote-claude attach --help` 不检查会话存在的测试？[主流程, spec.md US4 AS-2]
- [ ] CHK039 是否定义了 `remote-claude lark status --help` 只显示帮助的测试？[主流程, spec.md US4 AS-3]

### 错误信息抑制测试覆盖

- [ ] CHK040 是否定义了 `--help` 不输出"会话不存在"错误的测试？[验收标准, FR-010]
- [ ] CHK041 是否定义了 `-h` 短参数与 `--help` 行为一致的测试？[一致性, Gap]

---

## User Story 5 - List 命令增强展示

### 主流程测试覆盖

- [ ] CHK042 是否定义了 list 展示截断名称 + 原始路径 + 状态的测试？[主流程, spec.md US5 AS-1]
- [ ] CHK043 是否定义了无映射时原始路径显示 `-` 的测试？[主流程, spec.md US5 AS-2]
- [ ] CHK044 是否定义了无活跃会话时的提示测试？[主流程, spec.md US5 AS-3]

### 边界条件测试覆盖

- [ ] CHK045 是否定义了大量会话（>10 个）时的列表展示测试？[边界条件, Gap]
- [ ] CHK046 是否定义了映射数量达到 500 条上限时的展示测试？[边界条件, FR-021]

---

## User Story 6 - 配置文件拆分

### 主流程测试覆盖

- [ ] CHK047 是否定义了首次启动创建 config.json 和 runtime.json 的测试？[主流程, spec.md US6 AS-1]
- [ ] CHK048 是否定义了用户编辑 config.json 启用快捷命令生效的测试？[主流程, spec.md US6 AS-2]
- [ ] CHK049 是否定义了会话映射写入 runtime.json 不影响 config.json 的测试？[主流程, spec.md US6 AS-3]

### 配置隔离测试覆盖

- [ ] CHK050 是否定义了 ui_settings 只存在于 config.json 的验证测试？[一致性, FR-026]
- [ ] CHK051 是否定义了 session_mappings 只存在于 runtime.json 的验证测试？[一致性, FR-027]
- [ ] CHK052 是否定义了从旧单文件 runtime.json 拆分迁移的测试？[迁移, data-model.md §Migration Notes]

### 文件锁测试覆盖

- [ ] CHK053 是否定义了文件锁 `runtime.json.lock` 创建和删除的测试？[并发安全, FR-028]
- [ ] CHK054 是否定义了锁文件包含 PID 和时间戳的测试？[可追溯性, FR-029]
- [ ] CHK055 是否定义了并发写入时锁等待的测试？[并发安全, FR-021a]

---

## User Story 7 - 会话退出时清理映射

### 主流程测试覆盖

- [ ] CHK056 是否定义了 `kill` 命令删除 session_mappings 条目的测试？[主流程, spec.md US7 AS-1]
- [ ] CHK057 是否定义了退出时保留 lark_group_mappings 的测试？[主流程, spec.md US7 AS-2]

### 边界条件测试覆盖

- [ ] CHK058 是否定义了映射不存在时 kill 不报错的测试？[边界条件, Gap]
- [ ] CHK059 是否定义了异常退出（非 kill）时映射残留的处理测试？[异常流程, Gap]

---

## User Story 8 - 飞书卡片交互优化

### 卡片就地更新测试覆盖

- [ ] CHK060 是否定义了快捷命令选择后卡片就地更新的测试？[主流程, spec.md US8 AS-1]
- [ ] CHK061 是否定义了选项按钮点击后卡片就地更新的测试？[主流程, spec.md US8 AS-2]
- [ ] CHK062 是否定义了菜单按钮点击后卡片就地更新的测试？[主流程, spec.md US8 AS-3]
- [ ] CHK063 是否定义了文本提交后卡片就地更新的测试？[主流程, spec.md US8 AS-4]

### 状态反馈测试覆盖

- [ ] CHK064 是否定义了按钮 disabled 状态显示的测试？[视觉反馈, FR-037]
- [ ] CHK065 是否定义了"处理中"提示文本显示的测试？[视觉反馈, FR-037]
- [ ] CHK066 是否定义了处理完成后恢复正常状态的测试？[主流程, contracts/card-interaction-api.md]

### 错误处理测试覆盖

- [ ] CHK067 是否定义了 `update_card` 失败降级发送新卡片的测试？[降级策略, spec.md Edge Cases]
- [ ] CHK068 是否定义了快速连续交互防抖（500ms）的测试？[防抖机制, contracts/card-interaction-api.md]
- [ ] CHK069 是否定义了 `CardNotFoundError` 和 `CardUpdateError` 的处理测试？[错误处理, contracts/card-interaction-api.md]

---

## User Story 9 - 飞书卡片回车自动确认

### 单行输入框测试覆盖

- [ ] CHK070 是否定义了单行输入框回车自动提交的测试？[主流程, spec.md US9 AS-1]
- [ ] CHK071 是否定义了提交后卡片显示状态变化的测试？[主流程, spec.md US9 AS-3]
- [ ] CHK072 是否定义了空输入不触发提交的测试？[验收标准, spec.md US9 AS-4]

### 多行输入框测试覆盖

- [ ] CHK073 是否定义了多行输入框回车换行不提交的测试？[主流程, spec.md US9 AS-2]
- [ ] CHK074 是否定义了多行输入框保留确认按钮的测试？[兼容性, spec.md Edge Cases]

### 边界条件测试覆盖

- [ ] CHK075 是否定义了输入达到 `max_length` 限制时的行为测试？[边界条件, data-model.md §7]
- [ ] CHK076 是否定义了移动端飞书客户端无物理回车键的兼容测试？[兼容性, spec.md Edge Cases]

---

## 配置文件异常处理

### 损坏与备份测试覆盖

- [ ] CHK077 是否定义了 config.json 损坏时备份并返回默认配置的测试？[异常流程, data-model.md §5]
- [ ] CHK078 是否定义了 runtime.json 损坏时备份并返回默认配置的测试？[异常流程, data-model.md §5]
- [ ] CHK079 是否定义了备份保留最近 2 个文件的清理测试？[清理策略, FR-021b]

### bak 文件清理测试覆盖

- [ ] CHK080 是否定义了迁移成功后立即删除 bak 文件的测试？[清理策略, FR-032]
- [ ] CHK081 是否定义了启动时检测残留 bak 并提示用户的测试？[异常流程, FR-033]
- [ ] CHK082 是否定义了用户选择"覆盖"时从 bak 恢复的测试？[恢复流程, spec.md Edge Cases]
- [ ] CHK083 是否定义了用户选择"跳过"时删除 bak 继续的测试？[恢复流程, spec.md Edge Cases]
- [ ] CHK084 是否定义了正常运行时无 bak 文件残留的验证测试？[验收标准, FR-034]

---

## QuickCommand 验证规则

### 字段验证测试覆盖

- [ ] CHK085 是否定义了 `value` 必须以 `/` 开头的验证测试？[验证规则, data-model.md §4]
- [ ] CHK086 是否定义了 `value` 不能包含空格的验证测试？[验证规则, data-model.md §4]
- [ ] CHK087 是否定义了 `value` 最大 32 字符的边界测试？[边界条件, FR-017a]
- [ ] CHK088 是否定义了 `label` 最大 20 字符的边界测试？[边界条件, data-model.md §4]
- [ ] CHK089 是否定义了 `commands` 最多 20 条的限制测试？[边界条件, data-model.md §3]
- [ ] CHK090 是否定义了 `icon` 为空字符串时正常显示的测试？[边界条件, data-model.md §4]

---

## 集成测试场景

### 端到端流程测试覆盖

- [ ] CHK091 是否定义了会话启动 → 截断 → 映射存储的完整链路测试？[E2E, spec.md US1]
- [ ] CHK092 是否定义了快捷命令选择 → 发送 → 卡片更新的完整链路测试？[E2E, spec.md US2]
- [ ] CHK093 是否定义了配置迁移 → 功能启用 → 正常使用的完整链路测试？[E2E, research.md §6]
- [ ] CHK094 是否定义了会话退出 → 映射清理 → 配置更新的完整链路测试？[E2E, spec.md US7]

### 跨功能交互测试覆盖

- [ ] CHK095 是否定义了会话截断与 list 展示的交互测试？[集成测试, US1+US5]
- [ ] CHK096 是否定义了快捷命令与卡片交互优化的集成测试？[集成测试, US2+US8]
- [ ] CHK097 是否定义了配置拆分与迁移清理的集成测试？[集成测试, US6+US8]

---

## 性能与稳定性

### 性能测试覆盖

- [ ] CHK098 是否定义了配置文件加载时间的性能基准？[性能, Gap]
- [ ] CHK099 是否定义了大量映射（500 条）时的查询性能测试？[性能, data-model.md §3]
- [ ] CHK100 是否定义了卡片更新响应时间的性能测试？[性能, Gap]

### 稳定性测试覆盖

- [ ] CHK101 是否定义了程序异常退出后的配置恢复测试？[稳定性, Gap]
- [ ] CHK102 是否定义了长时间运行后的内存和资源释放测试？[稳定性, Gap]

---

## 文档一致性

### 文档验证测试覆盖

- [ ] CHK103 是否定义了 README.md 与实现行为一致的验证？[文档一致性, FR-035]
- [ ] CHK104 是否定义了 CLAUDE.md 与配置架构一致的验证？[文档一致性, FR-035]
- [ ] CHK105 是否定义了测试计划 TEST_PLAN.md 覆盖所有功能的验证？[文档一致性, T026]

---

## Notes

- 检查完成的项目：将 `[ ]` 改为 `[x]`
- 发现测试缺失时添加内联注释说明具体缺失项
- 链接到相关测试文件或测试用例
- 项目按顺序编号便于引用

---

## 检查统计

| 分类 | 项目数 | 关键问题 |
|------|--------|----------|
| User Story 1 测试覆盖 | 16 | CHK010, CHK012, CHK014 |
| User Story 2 测试覆盖 | 15 | CHK025, CHK028, CHK031 |
| User Story 3 测试覆盖 | 5 | CHK036 |
| User Story 4 测试覆盖 | 5 | CHK041 |
| User Story 5 测试覆盖 | 5 | CHK045, CHK046 |
| User Story 6 测试覆盖 | 9 | CHK052, CHK055 |
| User Story 7 测试覆盖 | 4 | CHK058, CHK059 |
| User Story 8 测试覆盖 | 10 | CHK067, CHK068, CHK069 |
| User Story 9 测试覆盖 | 7 | CHK075, CHK076 |
| 配置文件异常处理 | 8 | CHK080, CHK082 |
| QuickCommand 验证规则 | 6 | CHK089, CHK090 |
| 集成测试场景 | 7 | CHK094, CHK097 |
| 性能与稳定性 | 5 | CHK098, CHK100, CHK102 |
| 文档一致性 | 3 | - |
| **总计** | **105** | - |
