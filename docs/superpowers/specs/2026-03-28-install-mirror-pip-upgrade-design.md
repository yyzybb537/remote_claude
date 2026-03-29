# 安装链路可靠性增强设计（pip 升级 + 多镜像 + 失败日志统一）

## 1. 背景与目标

当前安装链路已经具备 uv 多来源安装能力，但在以下方面仍需统一：

1. 在安装 uv 前，未显式执行 pip 自升级。
2. pip 自升级与 pip 安装 uv 的镜像/`--trusted-host` 策略不完全统一。
3. 失败日志虽有基础能力，但缺少“安装失败 vs 脚本失败”的统一分级与命令摘要规范。

本次目标：

- 安装 uv 前先升级 pip（仅升级最终选中的 pip，且强制 `--user`）。
- pip 升级与 uv/pip 安装统一使用固定内置镜像回退链路，并附带 `--trusted-host`。
- 任一步骤失败都记录日志，按分级标签输出，并包含命令摘要和退出码。

## 2. 范围与非目标

### 2.1 范围

- 主要改造 `scripts/_common.sh` 的安装公共逻辑。
- 调整 `check_and_install_uv()` 调用顺序。
- 让 `scripts/install.sh` / `scripts/setup.sh` 继续通过 `_common.sh` 复用统一能力。
- 更新/补充安装相关测试（重点 `tests/test_entry_lazy_init.py`）。

### 2.2 非目标

- 不引入用户可配置镜像策略（本次为固定内置源）。
- 不新增独立安装 helper 文件（避免重复抽象）。
- 不改变 runtime 初始化语义（失败路径不创建 `runtime.json`）。

## 3. 设计原则

1. **单点收敛**：镜像、日志、回退逻辑统一在 `_common.sh`。
2. **行为一致**：pip 升级与 uv 安装使用同一套源策略与日志模板。
3. **最小改动面**：业务脚本尽量不重复实现安装细节。
4. **可追溯**：失败必须可定位到 stage/source/cmd/exit_code。

## 4. 镜像与 trusted-host 策略

采用固定内置源，按顺序回退（前一源失败才尝试下一源）：

1. tuna
   - index: `https://pypi.tuna.tsinghua.edu.cn/simple/`
   - trusted-host: `pypi.tuna.tsinghua.edu.cn`
2. aliyun
   - index: `https://mirrors.aliyun.com/pypi/simple/`
   - trusted-host: `mirrors.aliyun.com`
3. pypi
   - index: `https://pypi.org/simple`
   - trusted-host: `pypi.org`

每次尝试均自动附加：

- `-i <index_url>`
- `--trusted-host <trusted_host>`

## 5. 函数级改造方案（_common.sh）

### 5.1 新增/统一函数

1. **镜像源枚举函数**
   返回固定内置源序列（label/index/host）。

2. **失败日志函数（统一模板）**
   失败日志格式：
   - `[install-fail][<stage>] source=<label> cmd="<summary>" exit_code=<code>`
   - `[script-fail][<stage>] cmd="<summary>" exit_code=<code>`（非安装步骤）

3. **多源执行器（通用）**
   输入：`stage`、`pip_cmd`、`base_args`
   行为：遍历固定源，拼接镜像参数执行；成功即退出，失败记录摘要后回退下一个源。

4. **pip 升级函数（新增）**
   仅升级最终选中的 pip：
   - `<pip_cmd> install --upgrade pip --user ...`
   使用多源执行器；失败记录 `[install-fail][pip-upgrade]`。

5. **uv pip 安装函数（调整）**
   保留现有语义（含 `--break-system-packages`），改为走同一多源执行器；
   失败记录 `[install-fail][uv-install]`。

### 5.2 失败摘要策略（粒度 2）

日志仅记录命令摘要模板（如 `pip install --upgrade pip --user -i <index> --trusted-host <host>`）与退出码，不写完整敏感输出。

## 6. 调用链变更

### 6.1 `check_and_install_uv()`

在确认可用 pip 命令后，流程变更为：

1. `pip --user` 自升级（多源回退）
2. pip 安装 uv（多源回退）
3. 失败后继续既有后备渠道（官方脚本、conda/mamba、brew）

约束：

- pip 升级失败要记录，但不阻断后续 uv 安装尝试（保持可恢复性）。
- uv 整体失败后，维持既有懒初始化失败语义。

### 6.2 `install.sh` / `setup.sh` / `bin/*`

- 不内联镜像和日志细节，继续调用 `_common.sh` 公共能力。
- 仅在必要处补 stage 标签，便于区分入口来源。

## 7. 错误处理与日志规范

### 7.1 分级标签

- 安装阶段失败：`[install-fail][stage]`
- 其它脚本步骤失败：`[script-fail][stage]`
- 成功信息：`[install]`（简报）

### 7.2 字段要求

失败日志至少包含：

- `stage`
- `source`（安装多源场景）
- `cmd`（摘要）
- `exit_code`

日志文件：`/tmp/remote-claude-install.log`（保持现有语义）。

## 8. 测试与验证

### 8.1 自动化测试

重点更新/补充：

- `tests/test_entry_lazy_init.py`
  - 验证 pip 升级先于 uv pip 安装触发。
  - 验证 pip 升级与 uv 安装均带 `-i` + `--trusted-host`。
  - 验证失败日志包含 stage/source/cmd/exit_code。

必要时补充安装链路场景测试，确保 fallback 顺序可观测。

### 8.2 人工验证

1. 让首个镜像失败、次镜像成功，检查回退顺序与日志。
2. 模拟 pip 升级失败，确认 uv 安装继续执行。
3. 模拟非安装步骤失败，确认出现 `[script-fail]`。

## 9. 验收标准（DoD）

1. 安装 uv 前，已执行一次 `pip install --upgrade pip --user`（针对最终选中的 pip）。
2. pip 升级、pip 安装 uv 均使用固定内置镜像回退，并附加 `--trusted-host`。
3. 任一步骤失败都有日志，且含命令摘要与退出码。
4. 不破坏既有 runtime 初始化语义与安装 fallback 主流程。

## 10. 风险与缓解

1. **测试断言漂移风险**：旧测试可能依赖原命令字符串。
   - 缓解：同步更新断言到新命令模板和日志字段。
2. **镜像可用性波动**：单个镜像偶发不可用。
   - 缓解：固定顺序多源回退 + 明确日志定位。
3. **行为分叉风险**：不同入口脚本重复实现安装细节。
   - 缓解：所有关键逻辑收敛 `_common.sh`。
