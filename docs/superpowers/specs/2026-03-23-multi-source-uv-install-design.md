# 设计文档：多来源 uv 安装兼容

**日期**: 2026-03-23
**状态**: 待审批

## 背景

当前 `feature/custom_command` 分支的 `init.sh` 和 `scripts/install.sh` 仅支持两种 uv 安装方式：
1. 官方脚本（`curl -LsSf https://astral.sh/uv/install.sh | sh`）
2. brew（macOS 备选）

而 `main` 分支支持 5 种安装方式：
1. 官方脚本（推荐）
2. pip + PyPI（官方源）
3. pip + 清华镜像（国内镜像）
4. conda/mamba（已有 Anaconda 环境）
5. brew（macOS 备选）

此外，当前实现每次启动都重新检测 uv 路径，存在以下问题：
- 多次检测增加启动时间
- 环境变化可能导致检测路径不一致
- 无法记录用户手动指定的路径

## 目标

1. **恢复多来源安装兼容**：支持官方脚本、pip、conda、brew 等多种安装方式
2. **路径持久化**：安装成功后将 uv 路径写入 `runtime.json`，后续启动直接读取
3. **配置优先策略**：优先使用配置路径，失败则报错退出（要求重新运行 init.sh）
4. **向后兼容**：旧配置无 `uv_path` 字段时，运行检测流程并写入配置

## 设计方案

### 核心流程

```
┌─────────────────────────────────────────────────────────────┐
│                   uv 路径检测流程                            │
├─────────────────────────────────────────────────────────────┤
│  1. 读取 runtime.json → uv_path 字段                        │
│     ├─ 字段存在                                             │
│     │   ├─ 文件存在且可执行 → 直接使用，跳过检测              │
│     │   └─ 文件不存在/不可执行 → 报错退出                     │
│     │       "uv 路径失效，请重新运行 init.sh"                │
│     └─ 字段不存在 → 运行检测流程（兼容旧配置）                │
│                                                             │
│  2. 检测流程（init.sh 首次安装或旧配置迁移）：                │
│     ├─ command -v uv → 找到则写入配置                        │
│     ├─ 未找到 → 按优先级尝试安装                             │
│     │   ├─ 官方脚本（推荐，零依赖）                          │
│     │   ├─ pip + PyPI                                       │
│     │   ├─ pip + 清华镜像                                   │
│     │   ├─ conda/mamba                                      │
│     │   └─ brew（macOS）                                    │
│     ├─ 安装成功 → 写入 uv_path 到 runtime.json               │
│     └─ 安装失败 → 提示手动安装方式                           │
└─────────────────────────────────────────────────────────────┘
```

### runtime.json 结构变更

```json
{
  "version": "1.0",
  "uv_path": "/Users/xxx/.local/bin/uv",
  "session_mappings": {},
  "lark_group_mappings": {}
}
```

**字段说明**：
- `uv_path`：uv 可执行文件的绝对路径，首次安装或检测时自动写入

### 安装方式优先级

| 优先级 | 方式 | 适用场景 | 依赖条件 |
|--------|------|----------|----------|
| 1 | 官方脚本 | 通用，推荐 | 网络可访问 astral.sh |
| 2 | pip + PyPI | GitHub/astral.sh 访问受限 | 系统预装 Python + pip |
| 3 | pip + 清华镜像 | 国内内网环境 | 系统预装 Python + pip |
| 4 | conda/mamba | 已有 Anaconda 环境 | conda 或 mamba 已安装 |
| 5 | brew | macOS 用户 | Homebrew 已安装 |

### 错误处理矩阵

| 场景 | 行为 | 用户提示 |
|------|------|----------|
| `uv_path` 不存在 | 运行检测流程 | （静默处理） |
| `uv_path` 文件不存在 | 报错退出 | `uv 路径失效（/xxx/uv 不存在），请重新运行 init.sh` |
| `uv_path` 文件不可执行 | 报错退出 | `uv 不可执行（/xxx/uv），请检查权限或重新运行 init.sh` |
| 所有安装方式失败 | 报错退出 | 列出所有可用安装方式 |

## 修改范围

### 1. `utils/runtime_config.py`

新增函数：

```python
def get_uv_path() -> Optional[str]:
    """
    从 runtime.json 读取 uv 路径。

    Returns:
        uv 路径字符串，不存在则返回 None
    """

def set_uv_path(path: str) -> None:
    """
    写入 uv 路径到 runtime.json。

    Args:
        path: uv 可执行文件的绝对路径
    """

def validate_uv_path(path: str) -> tuple[bool, str]:
    """
    验证 uv 路径是否有效。

    Args:
        path: uv 路径

    Returns:
        (是否有效, 错误信息)
    """
```

### 2. `init.sh`

修改 `check_uv()` 函数：

```bash
check_uv() {
    print_header "检查 uv"

    # 1. 从 runtime.json 读取 uv_path（需 jq）
    local RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
    if [[ -f "$RUNTIME_FILE" ]] && command -v jq &> /dev/null; then
        local UV_PATH=$(jq -r '.uv_path // empty' "$RUNTIME_FILE" 2>/dev/null)
        if [[ -n "$UV_PATH" && -x "$UV_PATH" ]]; then
            print_success "uv（$UV_PATH）"
            export PATH="$(dirname "$UV_PATH"):$PATH"
            return
        elif [[ -n "$UV_PATH" ]]; then
            # 配置路径失效
            print_error "uv 路径失效（$UV_PATH），请重新运行 init.sh"
            exit 1
        fi
    fi

    # 2. 检测已安装的 uv
    if command -v uv &> /dev/null; then
        UV_VERSION=$(uv --version)
        print_success "$UV_VERSION 已安装"
        # 写入路径到配置
        _save_uv_path
        return
    fi

    # 3. 多来源安装（恢复 main 分支逻辑）
    print_warning "未找到 uv，正在安装..."
    _install_uv_multi_source

    # 4. 安装成功后写入路径
    if command -v uv &> /dev/null; then
        print_success "uv 安装成功"
        _save_uv_path
    else
        print_error "uv 安装失败，请手动安装："
        print_info "  pip3 install uv"
        print_info "  pip3 install uv -i https://pypi.tuna.tsinghua.edu.cn/simple/"
        print_info "  conda install -c conda-forge uv"
        print_info "  详见: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
}

_install_uv_multi_source() {
    # 检测可用的 pip 命令
    local PIP_CMD=""
    if command -v pip3 &> /dev/null; then
        PIP_CMD="pip3"
    elif command -v pip &> /dev/null; then
        PIP_CMD="pip"
    fi

    # 方式一：官方安装脚本（推荐）
    if curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh 2>/dev/null; then
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式二：pip + PyPI
    if ! command -v uv &> /dev/null && [[ -n "$PIP_CMD" ]]; then
        print_warning "尝试 pip 安装 uv（官方 PyPI）..."
        ($PIP_CMD install uv --quiet 2>/dev/null || \
         $PIP_CMD install uv --quiet --break-system-packages 2>/dev/null) && \
            export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式三：pip + 清华镜像
    if ! command -v uv &> /dev/null && [[ -n "$PIP_CMD" ]]; then
        print_warning "尝试 pip 安装 uv（清华镜像）..."
        ($PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null || \
         $PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn \
            --break-system-packages 2>/dev/null) && \
            export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式四：conda/mamba
    if ! command -v uv &> /dev/null; then
        if command -v mamba &> /dev/null; then
            print_warning "尝试 mamba 安装 uv..."
            mamba install -c conda-forge uv -y --quiet 2>/dev/null || true
        elif command -v conda &> /dev/null; then
            print_warning "尝试 conda 安装 uv..."
            conda install -c conda-forge uv -y --quiet 2>/dev/null || true
        fi
    fi

    # 方式五：brew（macOS）
    if ! command -v uv &> /dev/null && [[ "$OS" == "Darwin" ]] && command -v brew &> /dev/null; then
        print_warning "尝试 brew install uv..."
        brew install uv 2>/dev/null || true
    fi
}

_save_uv_path() {
    local UV_PATH=$(command -v uv 2>/dev/null)
    if [[ -n "$UV_PATH" ]]; then
        local RUNTIME_FILE="$HOME/.remote-claude/runtime.json"
        mkdir -p "$(dirname "$RUNTIME_FILE")"

        if [[ -f "$RUNTIME_FILE" ]] && command -v jq &> /dev/null; then
            # 更新现有文件
            local TMP_FILE=$(mktemp)
            jq --arg path "$UV_PATH" '.uv_path = $path' "$RUNTIME_FILE" > "$TMP_FILE" && \
                mv "$TMP_FILE" "$RUNTIME_FILE"
            print_info "已记录 uv 路径: $UV_PATH"
        elif [[ ! -f "$RUNTIME_FILE" ]]; then
            # 创建新文件
            echo "{\"version\":\"1.0\",\"uv_path\":\"$UV_PATH\"}" > "$RUNTIME_FILE"
            print_info "已记录 uv 路径: $UV_PATH"
        fi
    fi
}
```

### 3. `scripts/install.sh`

同步修改 `check_and_install_uv()` 函数，逻辑与 `init.sh` 一致。

### 4. `resources/defaults/runtime.default.json`

更新模板：

```json
{
  "version": "1.0"
}
```

（不预设 `uv_path`，首次运行时自动写入）

### 5. `README.md`

更新安装说明，补充多来源安装方式。

## 不修改的范围

- `docker/scripts/docker-diagnose.sh` — 保持 `uv pip list` 不变
- `remote_claude.py` — 保持 `uv run python3` 调用方式不变
- `specs/` 目录下的历史设计文档

## 验证方案

1. **全新安装**：删除 `runtime.json`，运行 `init.sh`，验证自动检测 + 写入路径
2. **路径持久化**：再次运行 `init.sh`，验证直接使用配置路径，跳过检测
3. **路径失效**：修改 `runtime.json` 中的 `uv_path` 为无效路径，验证报错退出
4. **多来源安装**：
   - 模拟无网络环境，测试 pip 安装
   - 模拟 conda 环境，测试 conda 安装
5. **旧配置迁移**：删除 `uv_path` 字段，验证重新检测 + 写入

## 文件清单

| 文件 | 修改类型 |
|------|---------|
| `utils/runtime_config.py` | 新增函数 |
| `init.sh` | 修改 `check_uv()` |
| `scripts/install.sh` | 修改 `check_and_install_uv()` |
| `resources/defaults/runtime.default.json` | 保持不变 |
| `README.md` | 更新说明 |

## 风险评估

- **低风险**：修改范围明确，不影响现有 uv 运行逻辑
- **向后兼容**：无 `uv_path` 字段的旧配置自动触发检测流程
- **回退方案**：删除 `uv_path` 字段可重新触发检测

## 实现优先级

1. `utils/runtime_config.py` — 路径读写函数
2. `init.sh` — 核心安装逻辑
3. `scripts/install.sh` — 同步修改
4. `README.md` — 文档更新
