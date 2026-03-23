---
description: "Implementation plan template for feature development"
---

# Implementation Plan: 命令行与飞书用户体验增强

**Feature**: `20260319-cmd-ux-enhancements` | **Date**: 2026-03-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/20260319-cmd-ux-enhancements/spec.md`

**Note**: This template is filled in by the `/adk:plan` command. See `.ttadk/plugins/ttadk/core/commands/adk/plan.md` for the execution workflow.

## Summary

本功能包含十三个独立的用户体验增强点：
1. **会话名称截断优化**：优化超长路径的截断策略，优先保留目录后缀，建立原始路径与截断名称的映射存储
2. **飞书快捷命令选择器**：在飞书卡片中提供快捷命令下拉选择器，默认关闭，需手动开启
3. **默认日志级别调整**：将飞书客户端默认日志级别从 INFO 改为 WARNING
4. **Help 参数纯展示**：确保所有命令的 `--help` 参数只显示帮助信息，不执行任何操作
5. **List 命令增强展示**：`remote-claude list` 展示截断名称、原始路径和原有信息
6. **配置文件拆分**：拆分为 `config.json`（用户配置）和 `runtime.json`（程序状态）
7. **会话退出清理映射**：会话退出时删除 `session_mappings` 中对应条目
8. **飞书卡片交互优化**：交互操作（按钮点击、文本提交）就地更新卡片，显示状态反馈
9. **飞书卡片回车自动确认**：单行文本框支持回车自动提交
10. **配置初始化逻辑**：在 init.sh 中使用 shell 脚本直接执行配置初始化和历史配置迁移
11. **文档布局优化**：将 `LARK_CLIENT_GUIDE.md` 移动到 `lark_client/` 目录
12. **文件备份策略优化**：写前备份 + 启动时检测备份残留并按时间戳从新到旧恢复
13. **配置回退命令**：新增 `remote-claude config reset` 命令支持一键回退配置

技术方案基于现有架构实现，主要涉及 `utils/session.py`、`utils/runtime_config.py`（新增）、`lark_client/config.py`、`lark_client/card_builder.py`、`lark_client/card_service.py` 和 `lark_client/lark_handler.py` 等文件的修改。

## Technical Context

**Language/Version**: Python 3.9+（**便携式打包，用户无需预装**）
**Package Manager**: uv（自动管理 Python 版本和依赖，创建隔离环境）
**Primary Dependencies**: argparse（CLI 解析）, hashlib（MD5 截断）, pyte（终端渲染）, lark SDK（飞书 API）
**Storage**: 文件存储（`~/.remote-claude/runtime.json` 用于运行时配置）
**Testing**: 独立测试脚本（`tests/` 目录），无需 pytest
**Target Platform**: macOS / Linux（PTY + termios）
**Project Type**: 单体项目（CLI 工具）
**Performance Goals**: 本地工具，无显式性能要求
**Constraints**: Socket 路径长度限制（macOS 104 字节，Linux 108 字节）
**Scale/Scope**: 单用户本地工具

### Python 环境策略（2026-03-23 澄清）

| 策略项 | 决策 |
|--------|------|
| **Python 依赖** | 项目自带便携式 Python（用户无需预装） |
| **包管理器** | 使用 uv 管理，自动创建隔离环境 |
| **Docker venv** | Docker 构建时创建 venv，测试运行时激活使用 |
| **产物提取** | 提取时包含便携式 Python（宿主机无需预装） |
| **预装 Python** | Docker 镜像和安装包中预装 uv 管理的 Python，无需运行时下载 |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 状态 | 说明 |
|------|------|------|
| **I. PTY 代理架构** | ✅ 通过 | 本功能不涉及 PTY 架构变更 |
| **II. 职责分界** | ✅ 通过 | 快捷命令选择器仅涉及飞书卡片渲染，不修改 Server 端；会话名称截断在 `utils/session.py` 中实现，属于工具层 |
| **III. ANSI 完整性** | ✅ 通过 | 本功能不涉及 ANSI 解析 |
| **IV. 多端共享** | ✅ 通过 | `runtime.json` 作为新的运行时配置存储，不改变多端共享架构 |
| **V. 测试分层** | ✅ 通过 | 各功能均可独立测试，无需飞书视觉测试（快捷命令选择器可通过配置验证） |

**Gate 结果**: 全部通过，可进入 Phase 0。

## Project Structure

### Documentation (this feature)

```
specs/20260319-cmd-ux-enhancements/
├── plan.md              # This file (/adk.plan command output)
├── research.md          # Phase 0 output (/adk.plan command)
├── data-model.md        # Phase 1 output (/adk.plan command)
├── quickstart.md        # Phase 1 output (/adk.plan command)
├── contracts/           # Phase 1 output (/adk.plan command)
└── tasks.md             # Phase 2 output (/adk.tasks command - NOT created by /adk.plan)
```

### Source Code (repository root)

```
remote_claude.py          # CLI 入口（Help 参数验证）

utils/
├── session.py            # 会话名称截断逻辑（修改）
└── runtime_config.py     # 运行时配置管理（新增）

lark_client/
├── config.py             # 日志级别配置（修改）
├── card_builder.py       # 快捷命令选择器渲染（修改）
└── lark_handler.py       # 快捷命令事件处理（修改）

tests/
├── test_runtime_config.py    # 运行时配置测试（新增）
└── test_session_truncate.py  # 会话名截断测试（新增）
```

**Structure Decision**: 采用单体项目结构，修改集中在 `utils/` 和 `lark_client/` 目录，新增 `utils/runtime_config.py` 作为运行时配置管理模块。后续将重新规划为 `core/`、`clients/`、`tests/`、`resources/`、`docs/` 结构。

## Complexity Tracking

*无 Constitution 违规，无需填写此表。*

---

## Generated Artifacts

| 阶段 | 文件 | 状态 |
|------|------|------|
| Phase 0 | `research.md` | ✅ 已生成 |
| Phase 1 | `data-model.md` | ✅ 已生成 |
| Phase 1 | `quickstart.md` | ✅ 已生成 |
| Phase 1 | `contracts/runtime-config-api.md` | ✅ 已生成 |
| Phase 1 | `contracts/quick-command-selector.md` | ✅ 已生成 |
| Phase 2 | `tasks.md` | ✅ 已生成 |

---

## Constitution Check (Post-Design)

*Re-check after Phase 1 design.*

| 原则 | 状态 | 说明 |
|------|------|------|
| **I. PTY 代理架构** | ✅ 通过 | 本功能不涉及 PTY 架构变更 |
| **II. 职责分界** | ✅ 通过 | `runtime_config.py` 为工具层；快捷命令渲染在 `card_builder.py`；Server 端无需修改；配置拆分保持职责清晰 |
| **III. ANSI 完整性** | ✅ 通过 | 本功能不涉及 ANSI 解析 |
| **IV. 多端共享** | ✅ 通过 | `runtime.json` + `config.json` 作为统一配置源，不影响多端共享架构 |
| **V. 测试分层** | ✅ 通过 | 各功能可独立测试，符合测试分层原则 |

**Gate 结果**: 设计阶段通过，可进入 Phase 2 任务分解。

---

## Key Changes from Clarification Session (2026-03-19)

### 配置架构变更

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 配置文件数量 | 单一 `runtime.json` | 双文件：`config.json` + `runtime.json` |
| `config.json` 内容 | N/A | 用户可编辑配置（`ui_settings`） |
| `runtime.json` 内容 | 全部配置 | 程序自动管理状态（`session_mappings`, `lark_group_mappings`） |
| 锁文件命名 | 未指定 | `runtime.json.lock` |
| 锁文件内容 | 未指定 | 用途 + PID + 创建时间 |
| 配置迁移 | 迁移 ui_settings | **无需迁移**（全新配置文件） |

### 映射清理策略变更

| 场景 | 原策略 | 新策略 |
|------|--------|--------|
| 会话退出 | 保留映射（便于追溯） | 删除映射（保持配置清洁） |
| `lark_group_mappings` | 与 `session_mappings` 同策略 | 保留（便于重连） |

### 配置迁移 bak 文件清理策略变更（2026-03-19 补充）

| 场景 | 原策略 | 新策略 |
|------|--------|--------|
| 迁移完成后 | 保留 bak 文件 | 立即删除 bak 文件 |
| 启动时检测残留 bak | 无处理 | 提示用户选择覆盖或跳过 |
| 正常运行时 | 可能存在 bak 残留 | 保证无 bak 文件残留 |

### 卡片交互优化变更（2026-03-19 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 按钮交互更新方式 | 推送新卡片 | `update_card` API 就地更新 |
| 交互视觉反馈 | 无 | 按钮 disabled + "处理中"状态 |
| 单行文本框回车 | 仅按钮提交 | 支持回车自动提交 |
| 多行文本框回车 | N/A | 保留换行行为（不提交） |

### Checklist 澄清变更（2026-03-19 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 连续下划线处理 | 未定义 | 合并为单下划线（`a__b` → `a_b`） |
| icon 字段格式 | 未定义 | 无限制，可为空，空时空白占位 emoji |
| commands 超限处理 | 未定义 | 静默截断（只显示前 20 条） |
| 配置权限不足 | 未定义 | 使用内存配置继续运行，输出警告 |
| 空会话名处理 | 未定义 | 拒绝启动并提示"会话名不能为空" |

### Docker 测试优化变更（2026-03-20 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| Docker 测试范围 | 仅集成测试 | 完整覆盖（集成测试 + 所有新功能单元测试） |
| 单元测试执行 | 无 | 新增步骤 7.5：执行独立单元测试 |
| README 测试列表 | 仅列出部分测试 | 同步更新，补充所有新功能测试文件 |
| 测试失败处理 | 未定义 | 分类处理（核心测试失败终止，非核心测试失败继续） |
| Codex 测试范围 | 启动验证 | 保持现状（启动验证已足够） |

### 配置初始化逻辑变更（2026-03-21 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 配置初始化位置 | 程序启动时执行 | init.sh 中用 shell 脚本直接执行 |
| 迁移逻辑执行 | Python 函数 | shell 脚本（init.sh 新增 `init_config()` 函数） |
| 默认配置创建 | 首次运行时自动创建 | init.sh 中直接创建默认文件 |

### 文档布局变更（2026-03-21 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| LARK_CLIENT_GUIDE.md 位置 | 项目根目录 | 移动到 `lark_client/GUIDE.md` |
| 其他文档位置 | 根目录 | 保持原位 |

### 文件备份策略变更（2026-03-21 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 备份时机 | 文件损坏后备份 | 写入前备份 |
| 启动时检测 | 检测残留 bak 并提示 | 按时间戳从新到旧找有效备份恢复 |
| 恢复策略 | 用户手动选择 | 自动找到第一个有效备份后提示用户 |

### 配置回退命令变更（2026-03-21 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 配置重置命令 | 无 | 新增 `remote-claude config reset` 子命令 |
| 重置范围 | 无 | 支持 `--all`、`--config`、`--runtime` 选项 |
| 副作用文件清理 | 无 | 重置时清理锁文件和备份文件 |

### 配置管理增强变更（2026-03-21 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 配置初始化位置 | 程序启动时 Python 函数执行 | init.sh 中 shell 脚本直接执行 |
| 文档布局 | LARK_CLIENT_GUIDE.md 在根目录 | 移动到 lark_client/GUIDE.md |
| 备份策略 | 读取时损坏才备份 | 写前备份 + 启动时检测恢复 |
| 备份恢复 | 用户手动处理 | 按时间戳从新到旧自动找有效备份恢复 |
| 配置回退 | 无命令支持 | 新增 `remote-claude config reset` 子命令 |
| 回退清理 | 不适用 | 清理锁文件和备份文件，保留状态文件 |
| 默认配置存储 | 硬编码在代码中 | 独立模板文件 `resources/defaults/` |
| 目录结构 | utils/, lark_client/, server/ 独立 | 重新规划：core/, clients/, tests/, resources/, docs/ |

### 文件引用修正变更（2026-03-22 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| `.env.example` 引用位置 | 项目根目录 | `resources/defaults/.env.example` |
| `test_lark_management.sh` 位置 | 项目根目录 | 移动到 `scripts/` 目录 |
| 测试脚本符号链接 | N/A | 不保留符号链接 |
| package.json files 字段 | 缺少部分目录 | 确保包含 `resources/` 目录 |

### 循环依赖修复变更（2026-03-22 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| `session.py` → `runtime_config.py` 导入 | 模块级导入 | 延迟导入（函数内导入） |
| 路径常量定义 | 集中在 `session.py` | 保持现状（已集中） |
| 路径函数定义 | 集中在 `session.py` | 保持现状（已集中） |
| 循环依赖处理 | 无 | `resolve_session_name()` 使用延迟导入 |

### Docker 优化变更（2026-03-22 补充）

| 变更项 | 原设计 | 新设计 |
|--------|--------|--------|
| 构建优化 | 无 | 全量优化（依赖安装缓存优化 + 多阶段构建优化） |
| pnpm 使用 | 无 | 仅 Docker 镜像内使用 pnpm，本地开发仍用 npm |
| 产物提取 | 无 | 可执行产物提取（.venv + 关键脚本到 test_results/） |
| 宿主机运行 | 无 | 提取产物可在宿主机直接运行 |
| 输出统计 | 二级计数（PASSED + FAILED） | 三级计数体系（PASSED + WARNINGS + FAILED） |
| README.md 更新 | 无 | 快速验证命令 + 开发者验证手册 |

**注意事项**：
- 由于 `.env` 配置不在宿主机上运行（可能存在路径问题），产物提取后需要用户手动配置 `.env`
- docker-test.sh 中测试文件不存在时计数问题已通过 `log_error` 解决
- README.md 中 Docker 验证章节已验证，包含完整流程
