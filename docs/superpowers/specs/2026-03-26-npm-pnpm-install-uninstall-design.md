# npm/pnpm 安装安全策略兼容与首次运行初始化设计

**日期**: 2026-03-26
**类型**: 功能优化
**状态**: 设计完成

## 背景

Remote Claude 通过 npm/pnpm 分发，用户可通过 `npm install -g remote-claude` 或 `pnpm add -g remote-claude` 安装。当前存在以下问题：

1. **pnpm 生命周期脚本可能不执行**：pnpm 可能因安全策略、显式批准机制或用户配置而不执行 `preinstall/postinstall/preuninstall`
2. **当前可用性过度依赖安装期 hook**：一旦 `postinstall` 未执行，首次运行命令可能因 Python 环境未初始化而失败
3. **卸载时交互式询问失败**：`preuninstall` 钩子中的 `read -r` 命令在 npm/pnpm 上下文中无法获取用户输入，导致脚本阻塞或异常
4. **文档预期与实际安全模型不一致**：README 暗示安装时自动完成初始化，但 pnpm 场景下这一假设并不可靠

## 目标

- 在**不绕过 pnpm 安全策略**的前提下保证命令可用性
- 将“安装成功”与“环境初始化完成”解耦
- 让 `cla` / `cl` / `cx` / `cdx` / `remote-claude` 在首次运行时自动完成必要初始化
- 保持卸载流程在 npm/pnpm 上下文中非交互、安全可执行
- 同步更新 README、CLAUDE.md 与 tests/TEST_PLAN.md，使文档与行为一致

## 非目标

- 不尝试规避 pnpm 的 lifecycle script 安全限制
- 不要求用户关闭 `ignore-scripts` 或修改全局安全配置
- 不新增仅为绕过 pnpm 限制而存在的旁路安装机制
- 本轮不扩展为新的 `remote-claude init` 子命令

## 解决方案

### 一、将初始化从安装期迁移到运行期

**核心决策**：不再把命令可用性绑定在 `postinstall` 是否执行，而是改为在命令首次运行时完成 Python 环境自检与惰性初始化。

#### 运行链路

```text
cla / cl / cx / cdx / remote-claude
  -> 入口脚本定位安装目录
  -> 调用共享自检/惰性初始化逻辑
  -> 若缺少 uv / .venv / 依赖不同步，则执行 lazy init
  -> 初始化成功后进入真实 CLI 主逻辑
```

#### 结果

- npm：即使 hook 执行失败，首次运行仍可恢复
- pnpm：即使 lifecycle script 因安全策略完全未执行，首次运行仍可完成初始化
- tarball / 本地安装：统一走相同初始化路径

### 二、入口脚本承担初始化触发职责

**文件**: `bin/remote-claude`、`bin/cla`、`bin/cl`、`bin/cx`、`bin/cdx`

每个 bin 入口在进入 Python 主逻辑前，统一执行以下步骤：

1. 解析当前脚本真实路径与安装根目录
2. source 共享 shell 逻辑
3. 调用统一的 `lazy_init_if_needed`（或等价函数）
4. 根据返回值决定：
   - 无需初始化：直接继续
   - 初始化成功：继续
   - 初始化失败：输出明确错误并退出非 0

#### 设计要求

- 已初始化环境下尽量静默，不增加启动噪音
- 首次初始化时仅输出必要提示，例如“首次运行，正在准备 Python 环境...”
- 失败提示聚焦“运行期初始化失败”，而不是要求用户理解 pnpm hook 机制

### 三、提升 `scripts/_common.sh` 中惰性初始化逻辑为主路径

**文件**: `scripts/_common.sh`

当前 `_lazy_init()` 已存在，但定位偏兜底。本次需要将其升级为入口脚本可稳定调用的核心能力：

#### 需要满足的行为

1. **幂等性**：已初始化环境不会重复触发 setup
2. **可重入保护**：防止 `setup.sh` 流程内部再次触发自身
3. **状态明确**：区分“无需初始化 / 需要初始化并成功 / 初始化失败”
4. **用户提示清晰**：首次运行初始化时给出简短说明
5. **兼容 pnpm 全局安装路径**：避免将真实全局安装目录误判为仅缓存目录

#### 判断条件

- `.venv` 不存在 → 需要初始化
- `pyproject.toml` 或 `uv.lock` 比 `.venv` 新 → 需要重新同步
- `uv` 不可用但可恢复 → 先安装/定位 uv，再继续初始化

### 四、降低 `package.json` 中 lifecycle scripts 的关键性

**文件**: `package.json`

当前：

- `preinstall`
- `postinstall`
- `preuninstall`

调整原则：

- `postinstall` 不再承担“命令是否可用”的关键职责
- 即使完全不执行，也不能影响首次命令恢复能力
- 可保留轻量逻辑或提示，但不应再依赖其完成 Python 环境初始化
- `preuninstall` 继续保留，但必须保证在 npm/pnpm 上下文中非交互可执行

### 五、保留卸载脚本的非交互安全行为

**文件**: `scripts/uninstall.sh`

卸载问题与 pnpm 安装安全策略不同，但同样体现“hook 中不要依赖交互”。现有方向继续保留：

- 在 npm/pnpm 生命周期上下文中：
  - 不执行 `read -r` 等交互式确认
  - 清理配置目录时走静默、安全、可预测的分支
  - 跳过不适合在 hook 中做的交互式 uv 缓存清理
- 手动运行脚本时：
  - 保留交互式确认体验

### 六、README 明确说明 pnpm 安全模型

**文件**: `README.md`

README 需要从“安装时自动完成所有初始化”的表述，调整为更准确的描述：

- pnpm 可能不会执行 lifecycle scripts，这是安全策略的一部分
- Remote Claude 不依赖该行为保证可用性
- 首次运行命令时会自动完成 Python 环境初始化
- 如自动初始化失败，提供最短的手动恢复命令

### 七、同步项目说明与测试计划

按仓库规则，本次需求变更必须同步更新：

- `CLAUDE.md`：补充 npm/pnpm 安全策略与首次运行初始化模型
- `tests/TEST_PLAN.md`：增加“生命周期脚本未执行时首次运行恢复”的测试场景

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `package.json` | 修改 | 降低 lifecycle scripts 对可用性的关键性 |
| `bin/remote-claude` | 修改 | 启动前执行运行期自检与惰性初始化 |
| `bin/cla` | 修改 | 启动前执行运行期自检与惰性初始化 |
| `bin/cl` | 修改 | 启动前执行运行期自检与惰性初始化 |
| `bin/cx` | 修改 | 启动前执行运行期自检与惰性初始化 |
| `bin/cdx` | 修改 | 启动前执行运行期自检与惰性初始化 |
| `scripts/_common.sh` | 修改 | 将惰性初始化逻辑提升为入口主路径 |
| `scripts/install.sh` | 修改 | 调整为显式安装/初始化底层实现，而非唯一关键路径 |
| `scripts/uninstall.sh` | 维持/微调 | 保持 npm/pnpm 上下文中的非交互卸载行为 |
| `README.md` | 修改 | 说明 pnpm 安全策略与首次运行初始化 |
| `CLAUDE.md` | 修改 | 同步架构与开发须知 |
| `tests/TEST_PLAN.md` | 修改 | 补充回归测试场景 |

## 测试场景

### 安装与首次运行测试

1. **npm 全局安装，hook 正常执行**
   ```bash
   npm install -g remote-claude
   cla --version  # 应正常工作
   ```

2. **pnpm 全局安装，lifecycle script 未执行**
   ```bash
   pnpm add -g remote-claude
   cla --version  # 首次运行应自动初始化并成功
   ```

3. **项目本地安装，首次运行触发初始化**
   ```bash
   npm install remote-claude
   npx cla --version  # 首次运行应自动初始化
   ```

4. **从 tarball 安装**
   ```bash
   npm install ./remote-claude-1.0.4.tgz
   npx cla --version  # 应通过运行期初始化恢复
   ```

5. **已初始化环境再次运行**
   ```bash
   cla --version
   cla --version  # 第二次不应重复初始化
   ```

6. **依赖变更后重新同步**
   ```bash
   touch pyproject.toml
   cla --version  # 应检测并重新同步环境
   ```

### 卸载测试

1. **npm uninstall**
   ```bash
   npm uninstall -g remote-claude
   # 应静默删除 ~/.remote-claude 目录
   ```

2. **pnpm uninstall**
   ```bash
   pnpm remove -g remote-claude
   # 应静默删除 ~/.remote-claude 目录
   ```

3. **手动运行卸载脚本**
   ```bash
   sh scripts/uninstall.sh
   # 应保留交互式询问是否删除配置
   ```

### 失败场景测试

1. **uv 不可安装 / 初始化失败**
   - 返回非 0
   - 输出明确的手动恢复提示

2. **入口脚本重复进入 lazy init**
   - 应被重入保护拦截，不出现无限递归

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 首次运行耗时增加 | 用户感知启动变慢 | 仅首次或依赖变更时触发，并保持提示简短 |
| 入口脚本与 setup 流程互相调用导致重入 | 初始化异常或死循环 | 保留并强化 `_LAZY_INIT_RUNNING` 保护 |
| 文档仍沿用“安装即完成初始化”旧表述 | 用户预期错误 | 同步更新 README、CLAUDE.md、TEST_PLAN |
| pnpm 全局路径识别不完整 | 某些环境首次运行仍失败 | 保留已有 pnpm 路径识别并补充回归测试 |

## 回滚方案

如果运行期初始化方案出现问题，可临时回退到以下人工修复方式：

```sh
# 手动初始化
sh scripts/setup.sh --npm --lazy

# 手动清理
rm -rf ~/.remote-claude
rm -rf /tmp/remote-claude
```
