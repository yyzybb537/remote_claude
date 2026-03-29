# 安装可靠性与一致性修复设计（安装失败 + runtime 生成 + 变量收敛）

## 1. 背景与问题定义

当前安装链路存在三个直接影响可用性的问题：

1. 安装失败时定位困难，缺少固定日志落点。
2. `runtime.json` 生成时机不够明确，导致“失败场景未生成”与“预期行为”混淆。
3. `PROJECT_DIR/SCRIPT_DIR` 在 `bin/` 与 `scripts/` 之间虽已部分收敛，但仍有路径/变量使用不一致风险。

已观察到的显性一致性问题：
- `scripts/setup.sh` 中补全行使用 `"$PROJECT_DIR/completion.sh"`，而实际补全脚本位于 `scripts/completion.sh`，存在路径漂移风险。

## 2. 目标与约束

### 2.1 目标

- 提升安装可靠性（npm/pnpm/源码路径均可诊断、可恢复）。
- 所有安装相关流程统一写入固定日志：`/tmp/remote-claude-install.log`。
- 明确并实现：`runtime.json` **仅在安装成功时创建**。
- 收敛 `PROJECT_DIR/SCRIPT_DIR` 约定：统一以 `_common.sh` 为唯一标准来源。

### 2.2 非目标

- 不重构为多进程/状态机安装器。
- 不改动 Python 运行时核心逻辑（仅限安装链路与入口脚本一致性）。
- 不引入新配置文件或额外日志目录结构。

## 3. 设计决策

### 决策 A：固定日志路径并覆盖写

- 日志路径固定：`/tmp/remote-claude-install.log`。
- 每次安装流程开始时覆盖写（truncate），确保排障时默认查看“最近一次尝试”。
- 安装失败时，终端统一输出“请查看 `/tmp/remote-claude-install.log`”。

### 决策 B：`runtime.json` 成功后创建

- 严格遵循用户要求：失败场景不创建 `runtime.json`。
- `runtime.json` 的初始化、模板复制、迁移动作仅在成功阶段执行。
- “成功阶段”定义为：依赖安装完成且初始化流程进入配置落盘分支后。

### 决策 C：变量入口统一到 `_common.sh`

- `_common.sh` 维持并强化 `PROJECT_DIR/SCRIPT_DIR` 统一约定：
  - `PROJECT_DIR`：项目根目录
  - `SCRIPT_DIR`：`$PROJECT_DIR/scripts`
- `install.sh/setup.sh/uninstall.sh/bin/*` 仅负责最小入口赋值，实际归一逻辑由 `_common.sh` 接管。

## 4. 方案细节

### 4.1 `_common.sh`（统一上下文）

新增安装上下文初始化能力（函数级）：

- 初始化日志文件并注入上下文信息：
  - script name
  - cwd
  - shell
  - npm lifecycle 关键变量
  - 是否缓存安装
- 统一打印阶段函数（如 `precheck/uv/deps/config/finalize`），用于定位失败点。
- 失败包装输出：记录退出码 + 最后阶段。

> 原则：日志与目录归一逻辑都由 `_common.sh` 提供，避免 `install.sh`/`setup.sh` 各自实现。

### 4.2 `install.sh`（安装编排）

- 启动即调用 `_common.sh` 的安装上下文初始化函数，开启固定日志。
- 保持现有流程顺序：OS 检查 → uv 检查/安装 → venv/sync → setup。
- 任一步失败：
  - 记录失败阶段
  - 输出统一查看日志提示
  - 直接失败返回，不进入 `runtime.json` 创建相关流程。

### 4.3 `setup.sh`（成功阶段配置落盘）

- 修复补全路径：将初始化块内补全 source 路径与仓库实际路径保持一致（`scripts/completion.sh`）。
- 将 `runtime.json` 初始化与迁移动作保持在成功分支执行。
- 对 npm/pnpm 缓存跳过场景记录“跳过原因”到固定日志。

### 4.4 `uninstall.sh` 与 `bin/*`

- `uninstall.sh`：复用 `_common.sh` 变量收敛，减少重复目录推导写法。
- `bin/remote-claude`、`bin/cla`、`bin/cl`、`bin/cx`、`bin/cdx`：
  - 统一入口解析风格与变量命名。
  - 继续依赖 `_common.sh`，避免入口脚本各自演化。

## 5. 兼容性与风险控制

### 5.1 兼容性

- 保持 POSIX `sh` 兼容（不引入 bash-only 语法）。
- 不改变用户命令接口（`cla/cl/cx/cdx/remote-claude` 语义不变）。

### 5.2 风险

- 日志重定向范围过大可能影响个别命令输出阅读体验。
  - 控制策略：仅安装链路启用，不影响日常运行命令。
- 成功/失败边界定义不清可能导致 `runtime.json` 创建时机漂移。
  - 控制策略：将创建动作集中于成功阶段函数，避免分散复制。

## 6. 验收标准

满足以下条件判定完成：

1. 触发安装失败时，`/tmp/remote-claude-install.log` 必有完整阶段日志。
2. 安装失败后，`~/.remote-claude/runtime.json` 不存在（或不被本次失败流程创建）。
3. 安装成功后，`~/.remote-claude/runtime.json` 正常生成。
4. `PROJECT_DIR/SCRIPT_DIR` 的约定在 `bin/` 与 `scripts/` 中一致，无新增分叉写法。
5. 补全脚本路径与实际文件位置一致。

## 7. 测试计划更新

将以下验证补充到 `tests/TEST_PLAN.md` 并在相关测试中覆盖：

- 安装失败日志落盘：
  - 人工触发失败后检查 `/tmp/remote-claude-install.log`。
- `runtime.json` 时机：
  - 失败不创建；成功创建。
- 入口一致性：
  - `bin/*` 与 `scripts/*` 的 `PROJECT_DIR/SCRIPT_DIR` 写法不漂移。
- shell 回归：
  - 继续保证 POSIX `sh` 语法通过现有回归项。

## 8. 需要同步的文档

按仓库规则同步：

- `CLAUDE.md`：补充安装日志路径、runtime 生成时机、变量收敛约束。
- `tests/TEST_PLAN.md`：补充上述安装链路回归场景。

## 9. 实施边界

本设计只覆盖“安装问题修复与一致性收敛”，不包含功能扩展或额外配置能力。
