# Remote Claude 安装脚本优化设计文档

**日期**: 2026-03-25
**作者**: Claude Code
**状态**: 待实现

## 1. 背景与目标

### 1.1 当前问题

1. **npm/pnpm 全局安装不完整**: `postinstall.sh` 检测到全局安装时会跳过初始化，导致用户首次运行命令时需要等待初始化
2. **venv 可能重复初始化**: `_lazy_init` 函数虽然检查 `.venv` 是否存在，但缺乏对依赖变更的检测
3. **Python 版本管理**: 需要确保使用 uv 管理的 Python 版本，而非系统 Python

### 1.2 目标

1. npm/pnpm 安装时**完全初始化** Python 环境（创建 venv + 安装依赖）
2. 避免**不必要的重复初始化**（通过文件修改时间检查）
3. 卸载时**完整清理**残余数据
4. 确保使用 **uv 管理的 Python 版本**
5. 更新相关文档（README.md、CLAUDE.md）

## 2. 设计方案

### 2.1 核心流程

```
npm/pnpm install -g remote-claude
    ↓
postinstall.sh 执行（全局安装也执行初始化）
    ↓
检查 uv → 安装 uv（如需要）
    ↓
uv venv → 创建虚拟环境（使用 uv 管理的 Python）
    ↓
uv sync --frozen → 安装依赖
    ↓
安装完成，用户可直接使用
```

### 2.2 关键改进

#### 2.2.1 postinstall.sh 修改

**当前行为**:
- 检测到全局安装路径时直接退出，跳过初始化

**新行为**:
- 全局安装时执行完整初始化
- 添加 `--frozen` 标志确保可复现安装
- 显示进度提示

**实现细节**:
```bash
# 检测是否为全局安装
_is_global_install() {
    case "$INSTALL_DIR" in
        */node_modules/remote-claude|*/pnpm/global/*)
            return 0
            ;;
    esac
    return 1
}

# 主流程
main() {
    # 解析安装目录
    resolve_install_dir

    # 即使在全局安装路径，也执行初始化
    if _is_global_install; then
        echo "正在初始化 Remote Claude Python 环境..."
        init_python_env
    fi
}

init_python_env() {
    # 检查/安装 uv
    check_and_install_uv

    # 创建虚拟环境（如果不存在或需要更新）
    if [ ! -d "$INSTALL_DIR/.venv" ] || _needs_sync; then
        cd "$INSTALL_DIR"
        uv venv
        uv sync --frozen
    fi
}
```

#### 2.2.2 _common.sh 优化

**新增功能**:
1. `check_uv`: 确保 uv 可用，自动安装
2. `_needs_sync`: 检查是否需要重新同步依赖
3. 优化 `_lazy_init`: 只在必要时运行

**实现细节**:
```bash
# 检查是否需要重新同步依赖
# 条件：.venv 不存在，或 pyproject.toml/uv.lock 比 .venv 新
_needs_sync() {
    local venv_dir="$SCRIPT_DIR/.venv"

    # .venv 不存在，需要同步
    [ ! -d "$venv_dir" ] && return 0

    # 检查 pyproject.toml 是否比 .venv 新
    if [ -f "$SCRIPT_DIR/pyproject.toml" ] && \
       [ "$SCRIPT_DIR/pyproject.toml" -nt "$venv_dir" ]; then
        return 0
    fi

    # 检查 uv.lock 是否比 .venv 新
    if [ -f "$SCRIPT_DIR/uv.lock" ] && \
       [ "$SCRIPT_DIR/uv.lock" -nt "$venv_dir" ]; then
        return 0
    fi

    return 1
}

# 延迟初始化（优化版）
_lazy_init() {
    # 如果在包管理器缓存中，跳过
    if _is_in_package_manager_cache; then
        return 0
    fi

    # 如果需要同步（venv 不存在或依赖变更），执行初始化
    if _needs_sync; then
        echo "检测到依赖变更，正在更新 Python 环境..."
        cd "$SCRIPT_DIR"
        if command -v bash >/dev/null 2>&1; then
            bash init.sh --npm --lazy 2>/dev/null || true
        fi
    fi
}
```

#### 2.2.3 卸载脚本增强

**当前功能**:
- 清理符号链接
- 清理 shell 配置
- 清理虚拟环境
- 清理运行时文件
- 询问删除配置文件

**新增功能**:
1. 清理 uv 缓存（可选）
2. 清理 npm/pnpm 全局安装残余
3. 更完善的错误处理

**实现细节**:
```bash
# 8. 清理 uv 缓存（可选）
cleanup_uv_cache() {
    if [ -n "$AUTO_CONFIRM" ]; then
        return  # CI 环境跳过询问
    fi

    printf "${YELLOW}是否清理 uv 缓存？${NC} [y/N]: "
    read -r reply
    case "$reply" in
        [yY][eE][sS]|[yY])
            if command -v uv >/dev/null 2>&1; then
                uv cache clean 2>/dev/null || true
                print_success "已清理 uv 缓存"
            fi
            ;;
    esac
}
```

#### 2.2.4 Python 版本管理

**策略**:
1. 优先使用 `.python-version` 文件指定的版本
2. 其次使用 `pyproject.toml` 中的 `requires-python`
3. uv 会自动下载并管理 Python 版本

**验证**:
```bash
# 在虚拟环境创建后验证 Python 版本
verify_python_version() {
    local python_path="$INSTALL_DIR/.venv/bin/python3"
    if [ -f "$python_path" ]; then
        local version
        version=$("$python_path" --version 2>&1)
        echo "Python 环境: $version"

        # 验证是否由 uv 管理
        if "$python_path" -c "import sys; print(sys.executable)" | grep -q ".venv"; then
            echo "✓ Python 由 uv 虚拟环境管理"
        fi
    fi
}
```

## 3. 文件修改清单

### 3.1 修改文件

| 文件 | 修改内容 |
|------|----------|
| `scripts/postinstall.sh` | 全局安装时也执行初始化，添加进度提示 |
| `scripts/_common.sh` | 添加 `_needs_sync` 检查，优化 `_lazy_init` |
| `scripts/uninstall.sh` | 添加 uv 缓存清理，完善错误处理 |
| `scripts/install.sh` | 添加 `--frozen` 标志，优化输出 |
| `bin/remote-claude` | 确保调用 `_lazy_init` |

### 3.2 文档更新

| 文件 | 更新内容 |
|------|----------|
| `README.md` | 更新安装说明，添加 npm/pnpm 安装行为说明 |
| `CLAUDE.md` | 更新安装流程文档，记录新行为 |

## 4. 测试计划

### 4.1 功能测试

1. **npm 全局安装测试**
   ```bash
   npm install -g remote-claude
   # 验证：.venv 存在，依赖已安装
   ```

2. **pnpm 全局安装测试**
   ```bash
   pnpm add -g remote-claude
   # 验证：.venv 存在，依赖已安装
   ```

3. **重复初始化测试**
   ```bash
   # 首次运行
   cla --help
   # 再次运行（应跳过初始化）
   cla --help
   ```

4. **依赖变更检测测试**
   ```bash
   # 修改 pyproject.toml
   touch pyproject.toml
   # 运行命令（应触发重新同步）
   cla --help
   ```

5. **卸载测试**
   ```bash
   npm uninstall -g remote-claude
   # 验证：符号链接已删除，配置文件询问是否保留
   ```

### 4.2 边界情况

1. 网络中断时的处理
2. uv 安装失败时的回退
3. 磁盘空间不足时的错误提示
4. 权限不足时的处理

## 5. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 安装时间增加 | 中 | 添加进度提示，使用 `--frozen` 加速 |
| 依赖版本冲突 | 低 | 使用 `--frozen` 确保可复现安装 |
| 用户误删配置文件 | 低 | 卸载时询问确认 |
| Python 版本不兼容 | 低 | 通过 pyproject.toml 指定最低版本 |

## 6. 实现步骤

1. 修改 `scripts/_common.sh` - 添加 `_needs_sync` 和优化 `_lazy_init`
2. 修改 `scripts/postinstall.sh` - 全局安装时执行初始化
3. 修改 `scripts/install.sh` - 添加 `--frozen` 标志
4. 修改 `scripts/uninstall.sh` - 添加 uv 缓存清理
5. 更新 `README.md` - 安装说明
6. 更新 `CLAUDE.md` - 安装流程文档
7. 测试验证

## 7. 附录

### 7.1 相关文件路径

- 安装脚本: `scripts/install.sh`
- 预安装脚本: `scripts/preinstall.sh`
- 后安装脚本: `scripts/postinstall.sh`
- 卸载脚本: `scripts/uninstall.sh`
- 共享脚本: `scripts/_common.sh`
- 主入口: `bin/remote-claude`
- 包配置: `package.json`
- Python 配置: `pyproject.toml`

### 7.2 参考文档

- [uv 文档](https://docs.astral.sh/uv/)
- [npm scripts](https://docs.npmjs.com/cli/v10/using-npm/scripts)
- [pnpm 生命周期脚本](https://pnpm.io/cli/run#lifecycle-scripts)
