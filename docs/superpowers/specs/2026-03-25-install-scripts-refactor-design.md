# 安装脚本重构设计

## 背景

当前安装流程存在以下问题：

1. **`init.sh` 位置不合理**：放在项目根目录，不符合"脚本在 scripts/" 的惯例
2. **`postinstall.sh` 功能不完整**：npm 安装时只创建 Python 环境，缺少符号链接、目录创建、配置迁移等初始化
3. **脚本职责重叠**：`install.sh` 和 `postinstall.sh` 都做 Python 环境初始化，`init.sh` 做完整初始化

## 目标

1. 统一安装入口，减少脚本数量
2. 确保 npm 安装执行完整初始化
3. 文件结构符合惯例

## 文件变更

| 操作 | 原路径 | 新路径 | 说明 |
|------|--------|--------|------|
| 移动+重命名 | `init.sh` | `scripts/setup.sh` | 初始化脚本 |
| 删除 | `scripts/postinstall.sh` | - | 功能合并到 install.sh |

**注意**：`scripts/install.sh` 保持原名不变，减少用户改动成本。

## 职责划分

### scripts/install.sh

**职责**：完整安装流程

1. 检测操作系统
2. 检查/安装 uv 包管理器
3. 创建 Python 虚拟环境
4. 安装 Python 依赖
5. 调用 `setup.sh` 完成初始化

**触发方式**：
- 用户手动运行：`./scripts/install.sh`
- npm postinstall：`sh scripts/install.sh --npm`

**参数**：
- `--npm`：跳过交互式配置（飞书配置询问）
- `--lazy`：仅执行 Python 环境初始化（用于延迟初始化）

### scripts/setup.sh

**职责**：完整初始化流程

1. 确保 `~/.local/bin` 在 PATH 中
2. 检查 tmux（版本要求 3.6+）
3. 检查 CLI 工具（Claude/Codex）
4. 配置飞书客户端（交互式）
5. 创建必要目录（`/tmp/remote-claude`、`~/.remote-claude`）
6. 初始化配置文件
7. 迁移旧配置文件
8. 设置执行权限
9. 安装快捷命令符号链接
10. 配置 shell 自动补全

**触发方式**：被 `install.sh` 调用

**参数**：
- `--npm`：跳过交互式配置
- `--lazy`：仅执行 Python 环境初始化

## 调用关系

```
用户手动安装:
  curl ... | sh scripts/install.sh
       └── scripts/install.sh
              └── scripts/setup.sh

npm 安装:
  npm install -g remote-claude
       └── package.json: postinstall
              └── sh scripts/install.sh --npm
                     └── scripts/setup.sh --npm

延迟初始化 (_common.sh):
  首次运行命令时检测依赖变更
       └── scripts/setup.sh --npm --lazy
```

## package.json 更新

```json
{
  "scripts": {
    "preinstall": "sh scripts/preinstall.sh",
    "postinstall": "sh scripts/install.sh --npm",
    "preuninstall": "sh scripts/uninstall.sh"
  },
  "files": [
    "bin/",
    "scripts/*.sh",
    "scripts/*.py",
    "remote_claude.py",
    "server/*.py",
    "server/parsers/*.py",
    "client/*.py",
    "utils/*.py",
    "lark_client/__init__.py",
    "lark_client/*.py",
    "stats/__init__.py",
    "stats/*.py",
    "pyproject.toml",
    "tests/",
    "resources/",
    ".npmrc"
  ]
}
```

**变更说明**：
- `postinstall` 从 `scripts/postinstall.sh` 改为 `scripts/install.sh --npm`
- `files` 移除 `init.sh`（已包含在 `scripts/*.sh` 中）

## install.sh 修改

### 新增 --npm 参数处理

```sh
main() {
    # 解析参数
    NPM_MODE=false
    LAZY_MODE=false
    for arg in "$@"; do
        [ "$arg" = "--npm" ] && NPM_MODE=true
        [ "$arg" = "--lazy" ] && LAZY_MODE=true
    done

    # ... 安装流程 ...

    # 调用 setup.sh
    if [ -f "$SCRIPT_DIR/setup.sh" ]; then
        if $NPM_MODE && $LAZY_MODE; then
            sh "$SCRIPT_DIR/setup.sh" --npm --lazy
        elif $NPM_MODE; then
            sh "$SCRIPT_DIR/setup.sh" --npm
        elif $LAZY_MODE; then
            sh "$SCRIPT_DIR/setup.sh" --lazy
        else
            sh "$SCRIPT_DIR/setup.sh"
        fi
    fi
}
```

### 合并 postinstall.sh 的缓存检测

原 `postinstall.sh` 的缓存检测逻辑移到 `install.sh`：

```sh
# 检测是否在包管理器缓存目录中
_is_in_package_manager_cache() {
    case "$INSTALL_DIR" in
        */.pnpm/*/node_modules/*|*/.store/*/node_modules/*|*pnpm*node_modules*|*/_cacache/*|*/.npm/*)
            return 0
            ;;
    esac
    return 1
}

main() {
    # 如果在包管理器缓存中，跳过初始化
    if _is_in_package_manager_cache; then
        echo "检测到缓存安装，跳过初始化"
        exit 0
    fi

    # ... 正常安装流程 ...
}
```

## setup.sh 修改

### SCRIPT_DIR 调整

原 `init.sh` 在项目根目录：

```sh
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# SCRIPT_DIR 指向项目根目录
```

移动后 `scripts/setup.sh`：

```sh
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# SCRIPT_DIR 指向 scripts/ 目录
# PROJECT_ROOT 指向项目根目录
```

### 引用路径更新

所有引用 `$SCRIPT_DIR` 指向项目根目录的地方需要改为 `$PROJECT_ROOT`：

```sh
# 原："$SCRIPT_DIR/resources/defaults/.env.example"
# 改："$PROJECT_ROOT/resources/defaults/.env.example"

# 原："$SCRIPT_DIR/scripts/_common.sh"
# 改："$SCRIPT_DIR/_common.sh"
```

## _common.sh 修改

延迟初始化调用路径更新：

```sh
_lazy_init() {
    # ...
    if _needs_sync; then
        cd "$SCRIPT_DIR"
        if command -v bash >/dev/null 2>&1; then
            _LAZY_INIT_RUNNING=1
            export _LAZY_INIT_RUNNING
            # 原：bash init.sh --npm --lazy
            # 改：
            bash "$SCRIPT_DIR/scripts/setup.sh" --npm --lazy 2>/dev/null || true
            _LAZY_INIT_RUNNING=0
        fi
    fi
}
```

## 文档更新

### CLAUDE.md

更新安装流程描述：

```markdown
## 安装流程

### npm/pnpm 全局安装（推荐）

```bash
npm install -g remote-claude
# 或
pnpm add -g remote-claude
```

**安装过程：**
1. npm/pnpm 下载并解压包文件
2. `postinstall` 钩子自动执行 `scripts/install.sh --npm`：
   - 检查/安装 uv 包管理器
   - 创建 Python 虚拟环境
   - 安装依赖
   - 执行 `scripts/setup.sh` 完成初始化

### 本地克隆安装

```bash
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./scripts/install.sh
```
```

### README.md

更新安装命令。

## 实施步骤

1. **移动 init.sh**
   - `git mv init.sh scripts/setup.sh`

2. **删除 postinstall.sh**
   - `git rm scripts/postinstall.sh`

3. **更新 scripts/setup.sh**
   - 调整 SCRIPT_DIR 计算
   - 更新引用路径

4. **更新 scripts/install.sh**
   - 添加 --npm 参数处理
   - 合并缓存检测逻辑（已存在于 _common.sh）
   - 更新 setup.sh 调用路径

5. **更新 scripts/_common.sh**
   - 更新延迟初始化调用路径

6. **更新 package.json**
   - 修改 postinstall 脚本
   - 更新 files 字段

8. **更新文档**
   - CLAUDE.md
   - README.md

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 用户使用旧文档运行 `./init.sh` | 命令不存在 | 保留 compat 脚本提示用户 |
| 缓存检测遗漏新路径 | 缓存中执行初始化 | 充分测试各种包管理器 |
| setup.sh 路径计算错误 | 初始化失败 | 测试各种安装场景 |

## 测试计划

1. **本地克隆安装**
   - `./scripts/install.sh` 完整流程
   - `./scripts/install.sh --npm` 跳过交互

2. **npm 全局安装**
   - `npm install -g .` 本地包安装
   - `pnpm add -g .` 本地包安装

3. **延迟初始化**
   - 删除 `.venv` 后运行命令
   - 更新 `pyproject.toml` 后运行命令

4. **缓存检测**
   - pnpm 缓存目录安装
   - npm 缓存目录安装
