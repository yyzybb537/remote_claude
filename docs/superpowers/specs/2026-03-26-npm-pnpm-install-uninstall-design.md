# npm/pnpm 安装体验优化与卸载清理设计

**日期**: 2026-03-26
**类型**: 功能优化
**状态**: 设计完成

## 背景

Remote Claude 通过 npm/pnpm 分发，用户可通过 `npm install -g remote-claude` 安装。当前存在以下问题：

1. **pnpm 安装后命令不可用**：pnpm 使用符号链接管理依赖，路径解析逻辑与 npm 不同，导致 `uv` 找不到或 `.venv` 路径错误
2. **卸载时交互式询问失败**：`preuninstall` 钩子中的 `read -r` 命令在 npm/pnpm 上下文中无法获取用户输入，导致脚本阻塞或异常
3. **路径检测不够健壮**：`_is_in_package_manager_cache()` 和 `_is_global_install()` 对 pnpm 路径检测不完整

## 目标

- 修复 pnpm 全局安装后的命令可用性问题
- 改进卸载流程，在 npm 上下文中自动完全清理
- 保持非 npm 环境下的交互式确认功能

## 解决方案

### 一、增强 pnpm 路径检测

**文件**: `scripts/_common.sh`

#### 1. 新增 pnpm 全局安装检测函数

```sh
# 检测是否为 pnpm 全局安装
# pnpm 全局安装需要正常初始化（不同于缓存）
_is_pnpm_global_install() {
    case "$SCRIPT_DIR" in
        # macOS pnpm 全局路径
        "$HOME"/Library/pnpm/global/*|\
        # Linux pnpm 全局路径
        "$HOME"/.local/share/pnpm/global/*|\
        # Windows pnpm 全局路径
        "$HOME"/AppData/Local/pnpm/global/*)
            return 0
            ;;
    esac
    return 1
}
```

#### 2. 修改延迟初始化逻辑

```sh
lazy_init_if_needed() {
    # 防止重入
    [ "${_LAZY_INIT_RUNNING:-}" = "1" ] && return 0

    # 包管理器缓存中跳过（但 pnpm 全局安装需要初始化）
    if _is_in_package_manager_cache && ! _is_pnpm_global_install; then
        return 0
    fi

    # 需要同步则执行
    if _needs_sync; then
        # ... 现有逻辑
    fi
    return 0
}
```

#### 3. 扩展 pnpm 缓存路径检测

在 `_is_in_package_manager_cache()` 中补充路径：

```sh
# 新增 pnpm 路径模式
*/.pnpm/*/node_modules/*|\
*/.pnpm-store/*|\
*/.store/*/node_modules/*|\
*/node_modules/.pnpm/*|\
*pnpm*node_modules*|\
*pnpm-global*|\
*/.pnpm-global/*  # 新增
```

### 二、改进卸载脚本

**文件**: `scripts/uninstall.sh`

#### 1. 新增 npm 上下文检测

```sh
# 检测是否在 npm 上下文中
# npm_lifecycle_event: npm 钩子事件名（如 preuninstall）
# npm_package_json: package.json 路径
_is_npm_context() {
    [ -n "$npm_lifecycle_event" ] || [ -n "$npm_package_json" ] || [ -n "$npm_config_loglevel" ]
}
```

#### 2. 修改配置文件清理逻辑

```sh
cleanup_config_files() {
    print_info "检查配置文件..."

    _ccf_data_dir="$HOME/.remote-claude"

    if [ ! -d "$_ccf_data_dir" ]; then
        print_detail "配置目录不存在，跳过"
        return
    fi

    # npm 环境：静默完全删除
    if _is_npm_context; then
        rm -rf "$_ccf_data_dir"
        print_success "已删除配置目录: $_ccf_data_dir"
        return
    fi

    # 非 npm 环境：交互式询问
    # ... 现有交互逻辑
}
```

#### 3. 修改 uv 缓存清理逻辑

```sh
cleanup_uv_cache() {
    # npm 环境或 CI 环境跳过交互式询问
    if _is_npm_context || [ -n "$CI" ]; then
        print_detail "npm/CI 环境跳过 uv 缓存清理（保留用户工具）"
        return
    fi

    # ... 现有交互逻辑
}
```

### 三、增强 uv 路径查找

**文件**: `scripts/_common.sh`

在 `check_and_install_uv()` 中增加查找路径：

```sh
check_and_install_uv() {
    # 1. 从 runtime.json 读取 uv_path
    _uv_path=$(_read_uv_path_from_runtime)
    if [ -n "$_uv_path" ] && [ -x "$_uv_path" ]; then
        export PATH="$(dirname "$_uv_path"):$PATH"
        return 0
    fi

    # 2. 检测系统 uv
    if command -v uv >/dev/null 2>&1; then
        _save_uv_path_to_runtime "$(command -v uv)"
        return 0
    fi

    # 3. 检查常见安装路径
    for _uv_candidate in \
        "$HOME/.local/bin/uv" \
        "$HOME/.local/share/pnpm/uv" \
        "/usr/local/bin/uv" \
        "/opt/homebrew/bin/uv"
    do
        if [ -x "$_uv_candidate" ]; then
            export PATH="$(dirname "$_uv_candidate"):$PATH"
            _save_uv_path_to_runtime "$_uv_candidate"
            return 0
        fi
    done

    # 4. 多来源安装
    # ... 现有逻辑
}
```

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `scripts/_common.sh` | 修改 | 新增 pnpm 检测函数，增强 uv 路径查找 |
| `scripts/uninstall.sh` | 修改 | 新增 npm 上下文检测，静默清理逻辑 |

## 测试场景

### 安装测试

1. **npm 全局安装**
   ```bash
   npm install -g remote-claude
   cla --version  # 应正常工作
   ```

2. **pnpm 全局安装**
   ```bash
   pnpm add -g remote-claude
   cla --version  # 应正常工作
   ```

3. **项目本地安装**
   ```bash
   npm install remote-claude
   npx cla --version  # 应正常工作
   ```

4. **从 tarball 安装**
   ```bash
   npm install ./remote-claude-1.0.4.tgz
   npx cla --version  # 应正常工作
   ```

### 卸载测试

1. **npm uninstall**
   ```bash
   npm uninstall -g remote-claude
   # 应静默删除 ~/.remote-claude 目录
   ls ~/.remote-claude  # 目录应不存在
   ```

2. **pnpm uninstall**
   ```bash
   pnpm remove -g remote-claude
   # 应静默删除 ~/.remote-claude 目录
   ```

3. **手动运行卸载脚本**
   ```bash
   sh scripts/uninstall.sh
   # 应交互式询问是否删除配置
   ```

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| pnpm 路径模式不完整 | 部分用户安装失败 | 扩展路径检测模式，增加日志调试 |
| 静默删除导致数据丢失 | 用户意外丢失配置 | 仅在 npm 上下文中静默，手动运行仍交互确认 |
| 环境变量检测误判 | 错误进入静默模式 | 使用多个环境变量组合判断 |

## 回滚方案

如果出现问题，可回退到以下临时解决方案：

```sh
# 手动初始化
cd $(dirname $(readlink -f $(which cla)))/..
sh scripts/setup.sh --npm --lazy

# 手动清理
rm -rf ~/.remote-claude
rm -rf /tmp/remote-claude
```
