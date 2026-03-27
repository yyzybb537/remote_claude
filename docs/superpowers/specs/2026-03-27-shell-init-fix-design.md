# Shell 脚本初始化逻辑修复设计

**日期**: 2026-03-27
**状态**: 已批准

## 问题描述

当前 `_common.sh` 定义 `_lazy_init()` 函数并在末尾自动调用，但多个 bin 入口文件调用不存在的 `lazy_init_if_needed` 函数，导致运行时报错：

```
bin/remote-claude: 19: lazy_init_if_needed: not found
```

## 问题根因

| 组件 | 实际行为 | 预期行为 |
|------|---------|---------|
| `scripts/_common.sh` | 定义 `_lazy_init()`，末尾自动调用 | 正确 |
| `bin/remote-claude` 等 | 调用不存在的 `lazy_init_if_needed` | 不应手动调用 |
| `tests/test_entry_lazy_init.py` | 测试 `lazy_init_if_needed` 契约 | 需删除 |
| `CLAUDE.md` / `TEST_PLAN.md` | 文档引用 `lazy_init_if_needed` | 需更新 |

## 解决方案

采用**方案 A：保留自动调用**，移除不一致的手动调用逻辑。

### 变更清单

#### 1. 删除 bin 入口的手动调用

涉及文件：
- `bin/cl` - 第 14-17 行
- `bin/cdx` - 第 14-17 行
- `bin/cx` - 第 14-17 行
- `bin/cla` - 第 14-17 行

删除内容：
```sh
if ! lazy_init_if_needed; then
    echo "Remote Claude 运行期初始化失败，请执行: sh $SCRIPT_DIR/scripts/setup.sh --npm --lazy" >&2
    exit 1
fi
```

**理由**：`_common.sh` 末尾已自动调用 `_lazy_init`，无需重复调用。

#### 2. 删除相关测试文件

- 删除 `tests/test_entry_lazy_init.py` - 测试已不适用

#### 3. 更新文档

**CLAUDE.md**：
- 删除 `lazy_init_if_needed()` 相关描述
- 更新为：所有 bin 入口依赖 `scripts/_common.sh`，初始化由 `_common.sh` 末尾自动执行

**tests/TEST_PLAN.md**：
- 删除 User Story 5（npm/pnpm 首次运行惰性初始化）相关内容

#### 4. Docker 测试增强

在 `docker/scripts/docker-test.sh` 步骤 6 中添加：

```bash
# 测试所有 bin 入口脚本语法
for bin_file in bin/*; do
    if [ -f "$bin_file" ]; then
        log_info "检查 $bin_file 语法..."
        if bash -n "$bin_file" 2>/dev/null; then
            log_success "$bin_file 语法正确"
        else
            log_error "$bin_file 语法错误"
            return 1
        fi
    fi
done

# 验证 _common.sh 不暴露 lazy_init_if_needed
if grep -q "^lazy_init_if_needed" "scripts/_common.sh"; then
    log_error "_common.sh 不应暴露 lazy_init_if_needed 函数"
    return 1
fi
log_success "_common.sh 不暴露 lazy_init_if_needed（符合预期）"
```

## 影响评估

| 影响范围 | 评估 |
|---------|------|
| 用户使用 | 无影响，修复后命令正常运行 |
| 开发者 | 需了解初始化由 `_common.sh` 自动处理 |
| CI/CD | Docker 测试增加脚本检查，更健壮 |

## 验收标准

1. 所有 bin 入口命令正常运行（`--help` 不报错）
2. `grep -r "lazy_init_if_needed" bin/ scripts/` 无结果
3. Docker 测试通过新增的脚本检查步骤
4. 相关测试文件已删除，文档已更新
