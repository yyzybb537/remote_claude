# Docker 容器自动销毁设计

**日期**: 2026-03-25
**状态**: 待实现

## 背景

当前 Docker 测试配置中，容器在测试完成后保持运行（`sleep infinity`），需要手动执行 `docker-compose down` 清理。这在本地调试场景下有用，但在 CI/CD 环境中造成资源浪费。

## 目标

支持两种运行模式：
- **CI 模式**：测试完成后自动销毁容器
- **本地调试模式**：测试完成后保留容器，便于调试

## 设计

### 实现方案

修改 `docker/scripts/docker-test.sh` 的 `cleanup()` 函数，通过环境变量 `AUTO_CLEANUP` 控制行为：

```bash
cleanup() {
    print_header "清理"

    if [ "${AUTO_CLEANUP:-false}" = "true" ]; then
        log_info "CI 模式：测试完成，容器将自动销毁"
        exit 0
    fi

    # 本地调试模式：保持容器运行
    local cid="$HOSTNAME"
    echo ""
    echo -e "${GREEN}容器保持运行，操作命令：${NC}"
    echo -e "  进入容器: docker exec -it ${cid} /bin/bash"
    echo -e "  查看报告: docker exec ${cid} cat /home/testuser/test-results/test_report.md"
    echo -e "  停止容器: docker stop ${cid}"
    echo ""

    log_success "清理完成"
    sleep infinity
}
```

### 不修改文件

- `docker/docker-compose.test.yml` — 保持现有配置不变
- `docker/Dockerfile.test` — 无需修改

### 使用方式

**本地调试模式（默认，保留容器）：**

```bash
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh
```

**CI 模式（自动销毁）：**

```bash
AUTO_CLEANUP=true docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

关键点：
- `AUTO_CLEANUP=true` 环境变量触发 CI 模式
- `--rm` 标志确保容器退出后自动删除

### 文档更新

更新 `docker/README.md`：

1. "运行测试"部分增加两种模式的说明
2. "CI/CD 集成"部分补充 `AUTO_CLEANUP=true` 环境变量

## 影响范围

- **CI/CD**：无影响（可逐步迁移到新方式）
- **本地开发**：无影响（默认行为不变）

## 测试验证

1. 本地调试模式：执行测试后容器保持运行
2. CI 模式：设置 `AUTO_CLEANUP=true` 后容器自动退出并销毁
