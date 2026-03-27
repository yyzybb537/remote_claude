# 设计文档：scripts 全量 POSIX sh 化与 shrc 自适应读写

- 日期：2026-03-27
- 主题：检查 `scripts/` 下脚本，处理直接使用 bash 的情况，使其自适应 SHELL（兼容 zsh 等）
- 范围：`scripts/` 下全部脚本 + 初始化写入/读取 shell rc 文件逻辑

## 1. 背景与目标

当前 `scripts/` 中仍有显式 `bash` 依赖（shebang、脚本互调、文案示例），在非 bash 场景（如 zsh、纯 sh 环境）会带来兼容性问题。

本次目标：

1. 将 `scripts/` 下 shell 脚本统一为 POSIX `sh` 兼容实现。
2. 将脚本内与用户可见文案中的 `bash ...` 调用统一替换为 `sh ...`。
3. 增加对 shell rc 文件（如 `~/.zshrc`、`~/.bashrc`、`~/.profile`）的自适应读取/写入判断。
4. 保证配置写入幂等，避免重复污染用户 rc 文件。

## 2. 设计决策

### 2.1 总体策略（方案 A）

采用“全量 POSIX 化 + 调用链统一 `sh` + rc 自适应”方案：

- 所有目标脚本按 POSIX `sh` 语法运行；
- 所有显式 `bash` 调用改为 `sh`；
- 通过统一公共函数管理 rc 文件选择、查重与写入；
- 保持现有入口行为和功能不变，仅修复 shell 兼容性。

### 2.2 rc 文件读取候选集（是否已配置）

按以下顺序扫描存在的文件，检查是否已有初始化块：

1. `~/.zshrc`
2. `~/.bashrc`
3. `~/.bash_profile`
4. `~/.profile`

只要任一文件命中初始化标记块，即判定“已配置”，不重复追加。

### 2.3 rc 文件写入目标选择（只写一个）

基于 `SHELL` 与文件存在性决策：

- 当前 shell 为 zsh：优先 `~/.zshrc`，不存在回退 `~/.profile`
- 当前 shell 为 bash：优先 `~/.bashrc`，其次 `~/.bash_profile`，再回退 `~/.profile`
- 其它或未知 shell：写入 `~/.profile`

首选文件不存在时允许创建，写入最小必要初始化块。

### 2.4 幂等与更新规则

采用固定标记块：

- `# >>> remote-claude init >>>`
- `# <<< remote-claude init <<<`

规则：

1. 写入前先在候选集全局查重；
2. 若已存在标记块：仅替换标记块内部内容；
3. 若不存在：追加到写入目标末尾；
4. 重复执行不新增重复块。

### 2.5 语法约束

所有改动严格使用 POSIX 语法与工具：

- 使用 `#!/bin/sh`、`[ ]`、POSIX `case`；
- 禁用 `[[ ]]`、数组、进程替换、`source` 等 bash-only 特性；
- 内部脚本调用使用 `sh <script>`。

## 3. 组件与改造边界

### 3.1 目标脚本

纳入改造：

- `scripts/setup.sh`
- `scripts/install.sh`
- `scripts/uninstall.sh`
- `scripts/preinstall.sh`
- `scripts/check-env.sh`
- `scripts/_common.sh`
- `scripts/completion.sh`
- `scripts/npm-publish.sh`
- `scripts/test_lark_management.sh`

### 3.2 公共能力集中化

在 `scripts/_common.sh` 中集中新增/整理 rc 管理函数（命名按现有风格落地）：

- `detect_shell_rc_target`：选择写入目标
- `has_init_block`：检查候选集是否已有初始化块
- `upsert_init_block`：按标记块执行追加或替换

其它脚本通过公共函数复用，不重复实现 rc 逻辑。

## 4. 数据流与行为

### 4.1 初始化读写流程

`入口脚本` → `读取候选集判重` → `选择写入目标` → `upsert 标记块` → `输出提示`

### 4.2 对用户可见行为

- 用户仍使用原有命令入口；
- 提示文案与示例命令统一为 `sh ...`；
- 重复执行安装/初始化命令时，rc 文件保持单一配置块。

## 5. 错误处理

1. 候选 rc 文件不存在：跳过读取，不报错；
2. 目标 rc 文件不可写：给出明确错误并退出当前写入步骤；
3. 标记块结构异常：按“未命中”处理并安全追加新块；
4. 单文件写入失败不应破坏其它安装流程的可观测输出。

## 6. 测试与验收

### 6.1 验收标准

- `scripts/` 目标脚本均可在 `sh` 下执行；
- 不依赖 bash 即可完成安装/初始化主流程；
- rc 目标文件选择符合自适应规则；
- 重复执行不产生重复初始化块；
- 已有旧块可被稳定识别与更新。

### 6.2 测试场景

1. zsh 环境：优先写入/更新 `~/.zshrc`；
2. bash 环境：优先 `~/.bashrc`，无则回退；
3. 未知 shell：回退 `~/.profile`；
4. 候选集任一文件已有块：不重复追加；
5. 文案与脚本互调中无显式 `bash` 残留；
6. 回归现有测试：`tests/test_custom_commands.py`、`tests/test_entry_lazy_init.py`；
7. 更新 `tests/TEST_PLAN.md`，补充 shell 兼容与 rc 自适应用例。

## 7. 非目标

- 不新增与 shell 兼容无关的功能开关；
- 不调整业务逻辑与命令交互语义；
- 不进行与本目标无关的重构。

## 8. 风险与回滚

- 风险：不同发行版对登录 shell rc 读取顺序有差异。
  - 缓解：读取候选集多文件判重，写入严格单目标并保留回退策略。
- 风险：历史手工配置不带标记块，无法自动替换。
  - 缓解：仅管理标记块内内容，避免误改用户自定义段落。
- 回滚：恢复相关脚本 shebang/调用与 `_common.sh` rc 选择逻辑即可，不涉及数据格式迁移。
