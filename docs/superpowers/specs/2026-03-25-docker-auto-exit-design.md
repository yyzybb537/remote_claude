# Docker 容器自动退出设计

**日期**: 2026-03-25
**状态**: 待实现

## 背景

当前 Docker 测试配置中，容器在测试完成后始终通过 `sleep infinity` 保持运行，需要手动停止。这导致：
- CI 环境中成功测试后容器仍占用资源
- 用户需要额外执行 `docker stop` 清理

## 目标

- **测试成功**：容器自动退出，配合 `--rm` 自动删除
- **测试失败**：容器保持运行，便于调试

## 设计

### 修改范围

仅修改 `docker/scripts/docker-test.sh` 的 `cleanup()` 函数。

### 实现方案

修改 `cleanup()` 函数，根据 `$FAILED` 变量判断测试结果：

```bash
cleanup() {
    print_header "清理"

    if [ $FAILED -eq 0 ]; then
        log_success "所有测试通过，容器将自动退出"
        exit 0
    fi

    # 测试失败：保持容器运行便于调试
    local cid="$HOSTNAME"
    echo ""
    echo -e "${GREEN}容器保持运行，操作命令：${NC}"
    echo -e "  进入容器: docker exec -it ${cid} /bin/bash"
    echo -e "  查看报告: docker exec ${cid} cat /home/testuser/test-results/test_report.md"
    echo -e "  停止容器: docker stop ${cid}"
    echo ""

    log_warning "存在 $FAILED 个失败测试，容器保持运行便于调试"
    sleep infinity
}
```

### 成功判断标准

`$FAILED == 0`，即所有测试（包括核心和非核心）都通过。

### 行为说明

| 场景 | 行为 | 容器状态 |
|------|------|---------|
| 所有测试通过 | `exit 0` | 退出，配合 `--rm` 自动删除 |
| 有测试失败 | `sleep infinity` | 保持运行，便于调试 |

### 文档更新

更新 `docker/README.md`：

1. 移除 `AUTO_CLEANUP` 相关说明
2. 更新"运行测试"部分，说明默认行为

## 使用方式

**CI 模式（推荐）：**

```bash
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

成功后容器自动删除，失败后容器保持运行。

**本地调试模式：**

```bash
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh
```

不使用 `--rm`，无论成功失败容器都会保留，便于查看测试产物。

## 影响范围

- **CI/CD**：成功测试后不再占用资源
- **本地开发**：测试失败时仍可进入容器调试

## 移除的功能

- `AUTO_CLEANUP` 环境变量（不再需要手动指定）
