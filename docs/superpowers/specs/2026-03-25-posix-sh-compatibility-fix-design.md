# POSIX sh 兼容性修复设计文档

- 创建日期: 2026-03-25
- 作者: Claude

## 修复概述

本项目修复了打包和安装脚本的 POSIX sh 兼容性问题，确保所有脚本在 sh、bash、zsh 下都能正确执行。

## 修复范围

### 修改的文件

1. **init.sh**
   - 修改 shebang 为 `#!/bin/sh`
   - 将 `source` 改为 `.` (POSIX 兼容)
   - 将 `[[ ]]` 改为 `[ ]` (POSIX 兼容)
   - 修复数组语法 `${#arr[@]}` 为手动计数器
   - 修复 `local var=$(...)` 语法问题
   - 优化 Shell 配置文件检测逻辑，不再依赖 `$SHELL` 环境变量

2. **bin/remote-claude**
   - 修改 shebang 为 `#!/bin/sh`
   - 将 `[[ ]]` 改为 `[ ]`
   - 将 `$OSTYPE` 改为 `uname` 命令

3. **scripts/check-env.sh**
   - 使用临时文件替代 `sed -i.bak`，实现跨平台兼容

4. **scripts/_common.sh**
   - 补充 pnpm 缓存目录检测模式

5. **scripts/install.sh**
   - 修改 shebang 为 `#!/bin/sh`
   - 修改文档注释

## 详细修改说明

### 1. POSIX sh 兼容性规则

| Bash 特有语法 | POSIX sh 替代方案 |
|---------------|-------------------|
| `[[ ]]` | `[ ]` |
| `source` | `.` |
| `${#arr[@]}` | 手动计数器变量 |
| `function foo()` | `foo()` (无 function 关键字) |
| `local var=$(...)` | 分离声明和赋值 |
| `echo -e` | `printf` 或 `echo` (取决于转义需求) |
| `$OSTYPE` | `uname` 命令 |

### 2. Shell 配置文件检测逻辑

**旧逻辑**:
```sh
if [[ -n "$ZSH_VERSION" ]] || [[ "$(basename "$SHELL")" == "zsh" ]]; then
    _RC="$HOME/.zshrc"
else
    _RC="$HOME/.bashrc"
fi
```

**新逻辑**:
```sh
get_shell_rc() {
    if [ -n "$ZSH_VERSION" ]; then
        echo "$HOME/.zshrc"
    elif [ -n "$BASH_VERSION" ]; then
        echo "$HOME/.bashrc"
    elif [ -f "$HOME/.zshrc" ]; then
        echo "$HOME/.zshrc"
    else
        echo "$HOME/.bashrc"
    fi
}
```

**优点**:
- 不依赖 `$SHELL` 环境变量（该变量可能在用户切换 shell 后未更新）
- 优先检测当前运行的 shell 类型（`$ZSH_VERSION`/`$BASH_VERSION`）
- 提供回退机制：检测配置文件是否存在

### 3. sed -i 跨平台兼容

**问题**: `sed -i.bak` 在 macOS (BSD sed) 和 Linux (GNU sed) 行为不一致。

**解决方案**: 使用临时文件：
```sh
tmp_file=$(mktemp)
sed "s/pattern/replacement/" "$ENV_FILE" > "$tmp_file" && mv "$tmp_file" "$ENV_FILE"
```

### 4. 数组替代方案

**问题**: POSIX sh 不支持数组 `${#arr[@]}`。

**解决方案**: 使用手动计数器：
```sh
# 初始化
WARNINGS_COUNT=0

# 添加
add_warning() {
    WARNINGS_COUNT=$((WARNINGS_COUNT + 1))
    eval "WARNING_${WARNINGS_COUNT}=\"\$1\""
}

# 遍历
print_warnings() {
    i=1
    while [ "$i" -le "$WARNINGS_COUNT" ]; do
        eval "w=\"\$WARNING_$i\""
        echo "$w"
        i=$((i + 1))
    done
}
```

### 5. pnpm 缓存目录检测

在 `_is_in_package_manager_cache()` 中添加更多 pnpm 缓存路径模式：
- `*/.pnpm/*/node_modules/*`
- `*/.store/*/node_modules/*`
- `*pnpm*node_modules*`
- `*/_cacache/*`
- `*/.npm/*`

## 测试验证

### 语法检查

```bash
sh -n init.sh           # 无语法错误
sh -n scripts/install.sh  # 无语法错误
sh -n bin/remote-claude    # 无语法错误
sh -n scripts/check-env.sh # 无语法错误
```

### 功能验证

- npm/pnpm 全局安装正常工作
- 飞书客户端启动正常工作
- 会话管理命令正常工作

- 补全功能正常工作（需要 bash/zsh 环境）

## 兼容性矩阵

| 场景 | sh | bash | zsh |
|------|----|------|-----|
| init.sh | ✅ | ✅ | ✅ |
| bin/remote-claude | ✅ | ✅ | ✅ |
| scripts/install.sh | ✅ | ✅ | ✅ |
| scripts/check-env.sh | ✅ | ✅ | ✅ |
| scripts/postinstall.sh | ✅ | ✅ | ✅ |
| scripts/uninstall.sh | ✅ | ✅ | ✅ |
| scripts/completion.sh | N/A | ✅ | ✅ |

> **scripts/completion.sh** 专门用于 tab 补全，必须在 bash/zsh 环境下运行，因此保持原有语法。

## 未修改的文件

以下文件保持原有语法（因为特定原因不需要修改）：

1. **scripts/completion.sh** - Tab 补全功能，需要在 bash/zsh 环境下才能工作
2. **docker/scripts/*.sh** - Docker 测试脚本，非用户直接执行
