# scripts 路径变量收敛设计（统一 source `_common.sh`）

- 日期：2026-03-30
- 主题：修复并防止 `错误: 无法定位安装目录模板文件: lark/resources/defaults/.env.example`
- 范围：`scripts/*.sh`（包含测试/发布辅助脚本）

## 1. 背景与问题

当前 `scripts/` 下脚本存在多处独立路径定义与参数化目录传入用法，导致路径真相源分叉。在特定入口下（尤其历史目录参数传入/子目录上下文），`check-env.sh` 可能把模板路径解析为：

- `lark/resources/defaults/.env.example`

从而触发“无法定位安装目录模板文件”错误。

## 2. 目标（已确认）

1. 收敛 `PROJECT_DIR / SCRIPT_DIR` 定义位置：最终定义只在 `scripts/_common.sh`。
2. 每个 `scripts/*.sh` 都必须 `source scripts/_common.sh`。
3. 统一后不退化：`source` / 直接执行 / 软链执行均可用。
4. 移除“将目录作为参数传入脚本以决定路径”的使用方式。
5. 对历史目录参数传入采用**显式报错退出**策略。

## 3. 非目标

1. 不改业务功能与交互语义（仅路径初始化层收敛）。
2. 不新增旁路配置机制。
3. 不做与本问题无关的重构。

## 4. 设计方案

### 4.1 统一脚本入口骨架（适用全部 `scripts/*.sh`）

每个脚本顶部统一执行：

1. 解析脚本真实路径（跟随 symlink）。
2. 计算初始 `PROJECT_DIR`（脚本目录上一级）。
3. 立即 `.` 加载 `"$PROJECT_DIR/scripts/_common.sh"`。
4. 后续逻辑只消费 `_common.sh` 导出的 `PROJECT_DIR/SCRIPT_DIR`。

约束：禁止在业务脚本中再把 `ROOT_DIR/PROJECT_ROOT/INSTALL_DIR` 等变量作为“路径真相源”。

### 4.2 `_common.sh` 作为唯一路径收敛点

`_common.sh` 负责：

1. 归一化 `PROJECT_DIR/SCRIPT_DIR`。
2. 校验 `scripts` 目录布局并 fail-fast。
3. 导出统一变量供全部脚本使用。

### 4.3 移除目录参数模式（关键约束）

- 脚本不再接受“目录参数”来决定安装/项目根。
- 对历史调用若仍传目录参数：**立即报错并非 0 退出**。
- 仓内调用点同步去参，改为无目录参数调用。

### 4.4 `check-env.sh` 专项修复

1. 模板路径统一固定为：`$PROJECT_DIR/resources/defaults/.env.example`。
2. 不允许再根据调用参数偏移到 `lark/` 等子目录。
3. 保持 `source` 与直接执行双语义退出方式（`return ... || exit ...`）。

## 5. 变更边界

- 覆盖：`scripts/*.sh` 全量（含 `test_lark_management.sh`、`npm-publish.sh` 等辅助脚本）。
- 不覆盖：`scripts/` 以外模块的功能性改造。

## 6. 错误处理策略

1. 无法定位项目根或 `_common.sh`：立即失败并输出明确错误。
2. 检测到目录参数传入：立即失败并提示目录参数已废弃。
3. 模板文件缺失：沿用明确错误输出并退出。

## 7. 验证与回归

### 7.1 一致性检查

1. 扫描 `scripts/*.sh`，确认全部采用统一入口并 source `_common.sh`。
2. 扫描仓内调用点，确认不再向脚本传目录参数。

### 7.2 行为回归（必须）

对关键脚本（重点 `check-env.sh`）验证：

1. 直接执行：`sh scripts/check-env.sh`
2. source 执行：`. scripts/check-env.sh`
3. 软链执行：通过 symlink 触发

期望：三类入口均不再出现 `lark/resources/defaults/.env.example` 误路径。

### 7.3 负向用例（新增）

- 向 `check-env.sh` 传任意目录参数应立即报错并非 0 退出。

## 8. 最终验收标准

1. 所有 `scripts/*.sh` 均 source `_common.sh`。
2. `PROJECT_DIR/SCRIPT_DIR` 最终收敛仅在 `_common.sh`。
3. 历史目录传参语义已移除且有明确失败反馈。
4. 目标报错消失，并保持 `source` / 直接执行 / 软链执行兼容不退化。
