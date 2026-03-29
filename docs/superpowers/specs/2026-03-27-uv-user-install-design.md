# 设计文档：scripts 中 uv 安装改为优先 pip --user（全入口生效）

- 日期：2026-03-27
- 主题：检查 `scripts/` 中的 uv 安装过程，使用 `pip --user` 安装以避免权限问题
- 范围：`scripts/_common.sh` 为唯一实现入口，覆盖 install/setup/bin 懒初始化链路

## 1. 背景与目标

当前 uv 安装已支持多来源兜底，但 pip 路径存在系统级安装尝试，容易在无权限环境触发失败或产生额外噪音。

本次目标：

1. 将 pip 安装策略统一为“优先 `pip --user`”。
2. 保持现有多来源恢复能力（pip 失败后继续 fallback）。
3. 改动集中在 `_common.sh`，避免在 `install.sh`、`setup.sh`、bin 入口重复逻辑。
4. 归拢配置与提示文案，减少重复代码。

## 2. 设计决策

### 2.1 总体策略

在 `scripts/_common.sh:install_uv_multi_source()` 内重构 pip 安装路径：

1. `pip --user` + 清华镜像（优先）
2. `pip --user` + 官方 PyPI
3. 失败后按现有顺序走 fallback：Astral install.sh → mamba/conda → brew

### 2.2 入口一致性

不在 `scripts/install.sh`、`scripts/setup.sh`、`bin/*` 写重复安装逻辑；所有入口继续通过 `check_and_install_uv()` 收敛到同一实现。

### 2.3 配置归拢（减少重复）

在 `_common.sh` 内新增统一配置/常量（命名可按现有风格落地）：

- pip 尝试源列表（渠道名、index 参数、日志标签）
- 手动安装提示文案（统一维护）

并通过单一“pip 安装尝试函数”循环执行，替代当前两段重复 pip 分支代码。

## 3. 组件与数据流

### 3.1 关键函数职责

- `check_and_install_uv()`：
  - 先尝试 runtime 中记录路径
  - 再尝试系统 PATH
  - 最后调用 `install_uv_multi_source()`
  - 成功后统一 `_save_uv_path_to_runtime`

- `install_uv_multi_source()`（本次主要改造）：
  - 先执行统一 pip-user 尝试循环
  - 失败后执行原 fallback 链路
  - 返回最终成功/失败状态

### 3.2 数据流（保持原结构）

`入口脚本(install/setup/bin)` → `check_and_install_uv()` → `install_uv_multi_source()` → `command -v uv` 校验 → `_save_uv_path_to_runtime`

### 3.3 PATH 发现策略

继续保留并利用现有 `~/.local/bin` PATH 兜底逻辑，确保 `pip --user` 安装成功后可被立即发现。

## 4. 错误处理

1. `pip --user` 任一尝试失败：记录简洁日志，不中断整体流程。
2. pip 全失败：自动进入 fallback。
3. fallback 成功：按统一成功路径处理并写入 runtime。
4. 全部失败：返回失败并输出统一手动安装提示。

## 5. 测试与验收

## 5.1 验收标准

- 全入口（install/setup/bin 懒初始化）行为一致。
- 有权限限制时优先使用 `pip --user`，避免系统级安装权限问题。
- `pip --user` 失败时可自动 fallback，不影响可恢复性。
- 成功安装后 `command -v uv` 与 `runtime.json` 中 `uv_path` 一致有效。

## 5.2 测试场景

1. **用户态成功路径**：`pip --user` 成功，直接完成安装。
2. **用户态失败后恢复**：`pip --user` 失败，fallback 成功。
3. **路径发现回归**：`~/.local/bin` 可正确被发现，`uv_path` 正确写入。
4. **入口一致性回归**：`scripts/install.sh`、`scripts/setup.sh`、bin 懒初始化均使用同一策略。

## 6. 非目标

- 不新增安装模式配置项（避免过度设计）。
- 不调整现有 fallback 类型与顺序（仅在 pip 段前置 user-first 策略）。
- 不扩展到与 uv 安装无关的脚本重构。

## 7. 变更清单（实施级）

- 修改：`scripts/_common.sh`
  - 重构 `install_uv_multi_source()` 中 pip 分支
  - 提取 pip 尝试配置与通用尝试函数
  - 归拢手动安装提示文案（若当前分散）
- 校验：`scripts/install.sh`、`scripts/setup.sh`、`bin/*` 无需新增安装逻辑

## 8. 风险与回滚

- 风险：部分环境 `pip --user` 安装后 PATH 刷新延迟。
  - 缓解：沿用并确认 `~/.local/bin` PATH 兜底逻辑。
- 回滚：恢复 `_common.sh` 中 pip 原逻辑即可，不涉及数据结构变更。
