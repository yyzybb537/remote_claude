# Docker 容器自动销毁实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过环境变量 `AUTO_CLEANUP` 控制 Docker 测试容器的生命周期，支持 CI 自动销毁和本地调试保留两种模式。

**Architecture:** 修改 `docker-test.sh` 的 `cleanup()` 函数检测环境变量，CI 模式直接退出（配合 `--rm` 自动删除），本地模式保持 `sleep infinity`。

**Tech Stack:** Bash shell 脚本

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `docker/scripts/docker-test.sh` | 修改 | 添加 AUTO_CLEANUP 检测逻辑 |
| `docker/README.md` | 修改 | 更新运行测试和 CI/CD 集成文档 |

---

### Task 1: 修改 cleanup 函数

**Files:**
- Modify: `docker/scripts/docker-test.sh:756-774`

- [ ] **Step 1: 修改 cleanup() 函数添加 AUTO_CLEANUP 检测**

定位到 `cleanup()` 函数（约第 756 行），替换为：

```bash
cleanup() {
    print_header "清理"

    if [ "${AUTO_CLEANUP:-false}" = "true" ]; then
        log_info "CI 模式：测试完成，容器将自动销毁"
        exit 0
    fi

    local cid="$HOSTNAME"
    echo ""
    echo -e "${GREEN}容器保持运行，操作命令：${NC}"
    echo -e "  进入容器: docker exec -it ${cid} /bin/bash"
    echo -e "  查看报告: docker exec ${cid} cat /home/testuser/test-results/test_report.md"
    echo -e "  停止容器: docker stop ${cid}"
    echo ""

    log_success "清理完成"

    # 保持容器运行，直到手动 docker stop
    sleep infinity
}
```

- [ ] **Step 2: 验证脚本语法正确**

Run: `bash -n docker/scripts/docker-test.sh`
Expected: 无输出（语法正确）

- [ ] **Step 3: 提交代码变更**

```bash
git add docker/scripts/docker-test.sh
git commit -m "$(cat <<'EOF'
feat: 支持 AUTO_CLEANUP 环境变量控制容器生命周期

CI 模式（AUTO_CLEANUP=true）测试完成后直接退出，配合 --rm 自动删除容器。
本地调试模式（默认）保持 sleep infinity 行为不变。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 更新文档

**Files:**
- Modify: `docker/README.md:33-44`

- [ ] **Step 1: 更新"运行测试"部分**

定位到"运行测试"部分（约第 33 行），替换为：

```markdown
### 运行测试

**本地调试模式（默认，保留容器）：**

```bash
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh
```

**CI 模式（自动销毁）：**

```bash
AUTO_CLEANUP=true docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

**交互式运行（直接进入 bash）：**

```bash
docker-compose -f docker/docker-compose.test.yml run npm-test /bin/bash
# 容器内执行：
/project/docker/scripts/docker-test.sh
```
```

- [ ] **Step 2: 更新 CI/CD 集成部分**

定位到"CI/CD 集成"部分（约第 209 行），替换为：

```markdown
## CI/CD 集成

在 GitHub Actions 或其他 CI/CD 平台中集成：

```yaml
- name: Run Docker Tests
  run: |
    docker-compose -f docker/docker-compose.test.yml build
    AUTO_CLEANUP=true docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh

- name: Upload Test Results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: test-results
    path: test-results/
```

关键配置：
- `AUTO_CLEANUP=true` — 测试完成后自动退出
- `--rm` — 容器退出后自动删除
```

- [ ] **Step 3: 提交文档变更**

```bash
git add docker/README.md
git commit -m "$(cat <<'EOF'
docs: 更新 Docker 测试文档，说明两种运行模式

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 验证实现

**Files:**
- None (验证任务)

- [ ] **Step 1: 验证本地调试模式（可选，需 Docker 环境）**

如果有 Docker 环境，运行：

```bash
# 启动测试（应保持容器运行）
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh

# 验证容器仍在运行
docker ps | grep remote-claude-npm-test

# 清理
docker-compose -f docker/docker-compose.test.yml down
```

- [ ] **Step 2: 验证 CI 模式（可选，需 Docker 环境）**

```bash
# 启动测试（应自动退出并删除容器）
AUTO_CLEANUP=true docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh

# 验证容器已删除
docker ps -a | grep remote-claude-npm-test || echo "容器已自动删除"
```

---

## 完成检查

- [ ] `docker/scripts/docker-test.sh` 语法正确
- [ ] `docker/README.md` 文档更新完整
- [ ] 提交记录清晰
