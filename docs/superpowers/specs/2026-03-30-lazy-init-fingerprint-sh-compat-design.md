# scripts lazy init 判定与 sh 兼容优化设计

- 日期：2026-03-30
- 主题：扫描 `scripts/` 并优化：
  1. 避免每次运行都打印“检测到依赖变更，正在更新 Python 环境...”
  2. shell 全面兼容 POSIX `sh`
- 范围：`scripts/_common.sh`、`scripts/setup.sh`、`scripts/install.sh`、`scripts/uninstall.sh`、`scripts/completion.sh` 及相关回归测试

## 1. 背景

当前懒初始化路径存在两个问题：

1. `_common.sh:_needs_sync` 依赖目录级时间戳判断，容易被目录元数据变更误触发，导致频繁打印“检测到依赖变更...”。
2. `scripts/` 内仍有若干非 POSIX `sh` 写法（如 `local`、`trap ... EXIT`），在严格 `sh` 环境下兼容性不稳定。

## 2. 目标（已确认）

1. 仅在“真实触发依赖同步”时打印“检测到依赖变更...”。
2. 保持现有 lazy init 行为语义（不改外部命令使用方式）。
3. 将关键脚本统一到 POSIX `sh` 兼容语法。

## 3. 非目标

1. 不改安装链路业务功能（如镜像策略、日志格式、交互文案）。
2. 不新增复杂配置系统（仅最小必要状态文件）。
3. 不重构 `scripts/completion.sh` 的 shell 专属补全能力（仅确保 `sh` 路径不触发不兼容语法）。

## 4. 方案概述（用户已选 A）

采用“依赖指纹判定”替代目录时间戳判定，根因修复误触发：

1. 在 `_common.sh` 中新增依赖指纹函数：
   - 计算 `pyproject.toml` 与 `uv.lock` 的稳定指纹；
   - 存储到 `$PROJECT_DIR/.venv/.remote_claude_dep_fingerprint`；
   - 比较当前指纹与历史指纹判断是否需要同步。
2. `_needs_sync` 改为：
   - `.venv` 不存在 => 需要同步；
   - 指纹文件不存在 => 需要同步；
   - 指纹不一致 => 需要同步；
   - 其余 => 不需要同步。
3. `setup.sh --lazy` 成功后写回最新指纹。
4. `_lazy_init` 保留原提示语，但只在 `_needs_sync=true` 且即将执行 setup 时打印。

## 5. 详细设计

### 5.1 `_common.sh` 新增/调整函数

新增：

1. `_dep_fingerprint_file`
   - 返回指纹文件路径（固定在 `.venv` 内）。

2. `_compute_dep_fingerprint`
   - 输入：`$PROJECT_DIR/pyproject.toml`、`$PROJECT_DIR/uv.lock`（存在则参与）。
   - 实现：优先 `cksum` 聚合；不可用时降级为文件大小+mtime 组合。
   - 约束：仅使用 POSIX 工具链（`sh`/`cksum`/`awk`/`wc`/`ls` 等）。

3. `_has_dep_changed`
   - 比对当前指纹与已保存指纹；任一缺失/不一致返回“已变更”。

4. `_write_dep_fingerprint`
   - 将当前指纹写入指纹文件（原子替换：临时文件 + `mv`）。

调整：

- `_needs_sync` 从目录时间戳逻辑切换为 `_has_dep_changed`。

### 5.2 `setup.sh` 懒初始化路径

- 在 `main()` 的 `--lazy` 成功分支（`install_dependencies` 成功后）调用 `_write_dep_fingerprint`。
- 指纹写入失败不改变主流程成功返回，但记录安装日志，避免影响可用性。

### 5.3 `_lazy_init` 打印时机

- 仅在 `_needs_sync` 为真后打印：
  - `检测到依赖变更，正在更新 Python 环境...`
- 不触发同步时不打印该行。

## 6. POSIX sh 兼容改造

### 6.1 必改项

1. 移除 `local` 关键字（`_common.sh`、`uninstall.sh`、`completion.sh` 的 `sh` 可达路径）。
2. 将 `trap cleanup_tmpdir EXIT` 替换为 `trap cleanup_tmpdir 0`（POSIX 兼容）。

### 6.2 保留项（说明）

- `completion.sh` 的 zsh/bash 专属分支语法可保留（功能所需），前提是严格受 shell 分支保护，不在 `sh` 执行路径解析失败。

## 7. 错误处理策略

1. 指纹计算失败：保守判定为“需要同步”（正确性优先）。
2. setup 执行失败：维持现有失败退出与恢复提示。
3. 指纹写回失败：记录日志，不覆盖安装成功返回码。

## 8. 验证计划

### 8.1 行为回归

1. 首次运行（无 `.venv`）：触发同步并打印提示。
2. 第二次运行（无依赖变更）：不触发同步，不打印提示。
3. 修改 `uv.lock` 或 `pyproject.toml`：触发同步并打印提示。

### 8.2 兼容性回归

1. `sh scripts/install.sh --lazy` 语法与流程通过。
2. `sh scripts/setup.sh --lazy` 语法与流程通过。
3. `sh scripts/check-env.sh` 与 `sh scripts/uninstall.sh` 语法通过。

### 8.3 风险回归

1. npm/pnpm 缓存安装路径仍按既有规则跳过初始化。
2. 失败日志仍包含阶段与命令摘要，不退化。

## 9. 验收标准

1. 未发生依赖变化时，不再打印“检测到依赖变更...”。
2. 依赖真实变化时，仍能触发懒初始化并打印提示。
3. 关键脚本在 POSIX `sh` 下无语法错误。
4. 现有安装/初始化主流程行为不退化。
