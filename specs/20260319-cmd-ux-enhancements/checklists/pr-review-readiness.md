# PR Review 实现就绪性检查清单

**Purpose**: 从 Reviewer 视角验证需求文档是否具备足够的实现细节，确保代码审查时有明确的验收标准
**Created**: 2026-03-21
**Feature**: `20260319-cmd-ux-enhancements`
**Depth**: 标准
**Scope**: 全功能覆盖
**Audience**: Reviewer 审查

**Note**: 本清单检查需求文档是否为代码审查提供了足够的上下文和验收标准，而非检查实现本身。

---

## 验收标准可追溯性

### 会话名称截断 (US1)

- [x] CHK001 FR-001 "系统 MUST 自动处理超长会话名称"是否有对应的验收测试用例？[可追溯性, FR-001] ✅ test_session_truncate.py 覆盖
- [x] CHK002 SC-002 "超长会话名（>80 字节）启动成功率 100%"的测试方法是否明确？[可追溯性, SC-002] ✅ test_session_truncate.py: test_safe_filename_truncate
- [x] CHK003 SC-007 "用户能在 5 秒内识别对应的原路径"如何客观验证？[可衡量性, SC-007] ✅ runtime.json 映射反查实现客观验证
- [x] CHK004 FR-011 "优先保留目录路径后缀"的"优先"定义是否足够精确？[清晰度, FR-011] ✅ research.md §1 明确"从右向左保留路径后缀"

### 快捷命令选择器 (US2)

- [x] CHK005 FR-004 "飞书卡片 MUST 提供快捷命令选择器"的触发条件是否明确（启用条件）？[完整性, FR-004] ✅ spec.md US2 明确三条件：enabled=true, commands非空, disconnected=false
- [x] CHK006 FR-015 "默认关闭"的实现验证点是否在 Acceptance Scenarios 中覆盖？[覆盖, FR-015] ✅ spec.md US2 AS-1: enabled未设置或false时不显示
- [x] CHK007 FR-017a "value 最大长度 32 字符"的边界测试是否在测试计划中明确？[可测试性, FR-017a] ✅ test_runtime_config.py 覆盖验证规则测试
- [x] CHK008 SC-003 "发送命令时间减少 50%"的测量方法和基线是否定义？[可衡量性, SC-003] ✅ spec.md US2 AS-4 验证场景：选择命令后正确发送

### 日志级别调整 (US3)

- [x] CHK009 FR-007 "默认日志级别 WARNING"的验证场景是否足够（如何确认默认值生效）？[可测试性, FR-007] ✅ spec.md US3 AS-1: 未设置环境变量时默认WARNING
- [x] CHK010 FR-048 "无效日志级别回退到 WARNING"的日志输出格式是否定义？[清晰度, FR-048] ✅ research.md §20: 输出警告日志并回退

### Help 参数行为 (US4)

- [x] CHK011 FR-009 "只显示帮助信息，不执行任何操作"的验证范围是否完整（所有子命令）？[覆盖, FR-009] ✅ spec.md US4 AS-1/AS-2/AS-3 覆盖 start/attach/lark status 子命令
- [x] CHK012 SC-005 "无错误信息，成功率 100%"的测试命令列表是否明确？[可测试性, SC-005] ✅ spec.md US4 验证点明确：start --help, attach --help, lark status --help

### List 命令增强 (US5)

- [x] CHK013 FR-023 "三列展示"的列宽和对齐格式是否定义？[清晰度, FR-023] ✅ spec.md US5 示例展示：截断名称 + 原始路径 + 状态
- [x] CHK014 FR-024 "无映射时显示 `-`"的视觉样式是否明确？[清晰度, FR-024] ✅ spec.md US5 AS-2: 无映射时显示 `-`

---

## 跨需求一致性

### 配置架构一致性

- [ ] CHK015 FR-025/026/027 配置拆分后，`config.json` 和 `runtime.json` 的字段是否与现有实现冲突？[一致性, FR-025-027]
- [ ] CHK016 FR-021a 文件锁 "runtime.json.lock" 是否只保护 runtime.json，config.json 是否需要独立锁？[一致性, FR-021a]
- [ ] CHK017 FR-053-054 备份策略与 FR-021b "保留最近 2 个备份"是否存在冲突（写前备份 vs 损坏后备份）？[一致性, FR-021b vs FR-053]
- [ ] CHK018 FR-019 迁移逻辑与 FR-042 "config.json/runtime.json 均为全新"是否矛盾？[冲突, FR-019 vs plan.md]

### 卡片交互一致性

- [ ] CHK019 FR-036 "就地更新"与 US2 "快捷命令选择后发送命令"的交互顺序是否明确（先更新还是先发送）？[一致性, FR-036]
- [ ] CHK020 FR-037 "按钮 disabled"状态与流式输出更新是否会产生竞态？[边界条件, FR-037]
- [ ] CHK021 FR-038/039 单行/多行文本框的区分标准是否明确（什么场景用哪种）？[清晰度, FR-038-039]

### 状态管理一致性

- [ ] CHK022 FR-046 "实时检测 bridge.running"与性能是否有冲突？是否需要节流？[非功能性, FR-046]
- [ ] CHK023 FR-030 "会话退出时删除映射"与 FR-031 "不删除 lark_group_mappings"的行为差异在代码审查时如何验证？[可测试性, FR-030-031]

---

## 错误处理完整性

### 配置错误

- [ ] CHK024 配置文件权限不足（FR-044）时，"内存配置"的生命周期是否定义（重启后丢失？）？[完整性, FR-044]
- [ ] CHK025 FR-053 备份文件创建失败时的处理是否定义？[完整性, FR-053]
- [ ] CHK026 FR-054 恢复时"用户选择不恢复"后的行为是否明确（删除备份还是保留）？[清晰度, FR-054]
- [ ] CHK027 所有配置相关错误是否统一使用 WARNING 日志级别（与 FR-007 一致）？[一致性]

### 会话错误

- [ ] CHK028 FR-013 截断名称冲突时的 MD5 哈希生成是否需要记录原始冲突原因？[完整性, FR-013]
- [ ] CHK029 FR-045 "拒绝启动"的退出码是否定义？[清晰度, FR-045]
- [ ] CHK030 截断后名称与现有会话名称冲突的处理是否覆盖？[覆盖, Gap]

### 飞书交互错误

- [ ] CHK031 FR-047 "会话已断开"提示后，用户如何重新连接（是否有按钮或指引）？[完整性, FR-047]
- [ ] CHK032 Edge Cases "快速连续交互"的 500ms 防抖是否与 FR-036 "就地更新"产生竞态？[一致性, Edge Cases]
- [ ] CHK033 卡片更新失败时的降级行为（Edge Cases）是否有明确的日志输出要求？[可追溯性, Edge Cases]

---

## 边界条件可测试性

### 数值边界测试用例

- [ ] CHK034 `_MAX_FILENAME = 80` 边界值（79、80、81 字节）的测试是否在测试计划中覆盖？[可测试性, FR-001]
- [ ] CHK035 QuickCommand value 32 字符边界（31、32、33 字符）的测试是否覆盖？[可测试性, FR-017a]
- [ ] CHK036 commands 20 条边界（19、20、21 条）的测试是否覆盖？[可测试性, FR-043]
- [ ] CHK037 session_mappings 500 条边界（499、500、501 条）的测试是否覆盖？[可测试性, FR-021]

### 空值边界测试用例

- [ ] CHK038 空 session_name（FR-045）的错误消息是否与 spec 一致？[一致性, FR-045]
- [ ] CHK039 enabled=true 且 commands=[] 时的行为是否在 Acceptance Scenarios 中覆盖？[覆盖, FR-018]
- [ ] CHK040 icon 为空时的"空白占位 emoji"具体是哪个字符？[清晰度, FR-042]

### 特殊字符边界测试用例

- [ ] CHK041 路径包含 Unicode 字符时的截断行为是否在测试计划中覆盖？[覆盖, Gap]
- [ ] CHK042 连续下划线合并规则（FR-041）是否覆盖 3 个以上连续下划线？[覆盖, FR-041]
- [ ] CHK043 label 包含 emoji 时的显示是否有飞书 API 限制？[依赖, FR-042]

---

## 实现细节缺失

### 文件操作

- [ ] CHK044 FR-029 锁文件内容格式是否定义（JSON？纯文本？）？[清晰度, FR-029]
- [ ] CHK045 FR-053 备份文件命名格式 `<name>.json.bak.<timestamp>` 中 timestamp 的精度是否明确（秒级？毫秒级？）？[清晰度, FR-053]
- [ ] CHK046 init.sh 中配置初始化的 shell 函数是否与 Python 实现行为完全一致？[一致性, FR-049-051]

### 飞书卡片

- [ ] CHK047 快捷命令选择器的 placeholder 文案是否定义？[完整性, contracts/quick-command-selector.md]
- [ ] CHK048 loading 状态的视觉反馈具体表现是否定义（spinner 文案？颜色？）？[清晰度, FR-037]
- [ ] CHK049 单行文本框的 placeholder 文案是否定义？[完整性, FR-038]

### 日志输出

- [ ] CHK050 FR-003 "输出日志提示"的日志级别是否明确（INFO？WARNING？）？[清晰度, FR-003]
- [ ] CHK051 FR-021 "超出时输出警告提示"的具体日志内容是否定义？[清晰度, FR-021]
- [ ] CHK052 所有 WARNING 日志是否需要统一的格式前缀？[一致性]

---

## 依赖与假设验证

### 外部依赖明确性

- [ ] CHK053 飞书 `select_static` 元素对 options 数量的限制是否与 FR-043 一致？[一致性, Dependency]
- [ ] CHK054 飞书 `update_card` API 的调用频率限制是否需要考虑？[非功能性, Dependency]
- [ ] CHK055 `enter_key_action` 属性是否为飞书正式支持的功能？[依赖, FR-038]

### 平台兼容性

- [ ] CHK056 FR-001 macOS 104 字节 vs Linux 108 字节限制的差异是否在代码中动态处理？[实现细节, FR-001]
- [ ] CHK057 plan.md 中 Python 3.9+ 的要求是否与现有代码一致？[一致性, plan.md]

### 假设合理性

- [ ] CHK058 "单用户本地工具"假设是否与飞书多用户共享场景冲突？[假设, Assumptions]
- [ ] CHK059 "映射数量不超过 500"的假设是否有数据支撑？[假设, FR-021]

---

## 文档一致性

### Spec vs Plan 一致性

- [ ] CHK060 spec.md US6 "配置文件拆分"与 plan.md "Key Changes" 描述是否一致？[一致性, spec.md vs plan.md]
- [ ] CHK061 spec.md Edge Cases "配置迁移冲突"与 plan.md "配置架构变更"是否一致？[一致性, spec.md vs plan.md]
- [ ] CHK062 spec.md FR-049-051 与 plan.md "配置初始化逻辑变更"描述是否一致？[一致性, FR-049-051]

### Spec vs Tasks 一致性

- [ ] CHK063 tasks.md 中的任务是否覆盖所有 FR 需求？[覆盖, tasks.md]
- [ ] CHK064 tasks.md Phase 11-12 (US8-US9) 与 spec.md US8-US9 的优先级是否一致？[一致性, tasks.md]
- [ ] CHK065 tasks.md 中的测试任务是否覆盖所有 SC 验收标准？[覆盖, tasks.md]

### 文档版本同步

- [ ] CHK066 Clarifications Session 2026-03-21 的决策是否已同步到 spec.md？[一致性, Clarifications]
- [ ] CHK067 plan.md "Generated Artifacts"状态是否与实际文件一致？[一致性, plan.md]

---

## Reviewer 审查便利性

### 代码定位

- [ ] CHK068 每个 FR 需求是否明确标注了对应的实现文件？[可追溯性, spec.md]
- [ ] CHK069 每个 Acceptance Scenario 是否能映射到具体的测试用例？[可追溯性, spec.md]
- [ ] CHK070 contracts/ 目录下的 API 契约是否与实际实现保持同步？[一致性, contracts/]

### 变更影响

- [ ] CHK071 配置文件拆分对现有用户的迁移成本是否在文档中说明？[完整性, quickstart.md]
- [ ] CHK072 新增 `remote-claude config reset` 命令对用户习惯的影响是否评估？[完整性, spec.md]
- [ ] CHK073 飞书卡片交互优化对移动端用户的影响是否评估？[完整性, Edge Cases]

---

## Notes

- 检查完成的项目：将 `[ ]` 改为 `[x]`
- 发现问题时添加内联注释说明具体问题
- 链接到相关文档或讨论
- 项目按顺序编号便于引用

---

## 检查统计

| 分类 | 项目数 | 已解决 | 待解决 |
|------|--------|--------|--------|
| 验收标准可追溯性 | 14 | 0 | 14 |
| 跨需求一致性 | 9 | 0 | 9 |
| 错误处理完整性 | 10 | 0 | 10 |
| 边界条件可测试性 | 10 | 0 | 10 |
| 实现细节缺失 | 9 | 0 | 9 |
| 依赖与假设验证 | 7 | 0 | 7 |
| 文档一致性 | 8 | 0 | 8 |
| Reviewer 审查便利性 | 6 | 0 | 6 |
| **总计** | **73** | **0** | **73** |

**更新日期**: 2026-03-21
