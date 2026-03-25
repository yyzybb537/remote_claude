# Docker 容器自动退出实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修改 Docker 测试脚本，使测试成功时容器自动退出，失败时保持运行便于调试。

**Architecture:** 修改 `cleanup()` 函数，根据 `$FAILED` 变量判断测试结果：成功则 `exit 0`，失败则 `sleep infinity`。同时更新 README 文档移除 `AUTO_CLEANUP` 说明。

**Tech Stack:** Bash shell script, Docker Compose

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `docker/scripts/docker-test.sh` | 修改 | 修改 `cleanup()` 函数添加成功判断逻辑 |
| `docker/README.md` | 修改 | 更新运行测试说明，移除 AUTO_CLEANUP 相关内容 |
| `docs/superpowers/specs/2026-03-25-docker-auto-cleanup-design.md` | 删除 | 旧设计文档被新方案替代 |
| `docs/superpowers/plans/2026-03-25-docker-auto-cleanup.md` | 删除 | 旧实现计划被新方案替代 |

---

### Task 1: 修改 cleanup() 函数

**Files:**
- Modify: `docker/scripts/docker-test.sh:760-773`

- [ ] **Step 1: 修改 cleanup() 函数添加成功判断逻辑**

将 `cleanup()` 函数从当前的 `sleep infinity` 模式改为根据 `$FAILED` 判断：

```bash
# 步骤 10：清理
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

- [ ] **Step 2: 提交修改**

```bash
git add docker/scripts/docker-test.sh
git commit -m "feat: Docker 测试成功时自动退出容器

- 测试成功（FAILED=0）时 exit 0 退出容器
- 测试失败时保持 sleep infinity 便于调试
- 移除对 AUTO_CLEANUP 环境变量的依赖

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: 更新 README 文档

**Files:**
- Modify: `docker/README.md:34-46` (运行测试部分)
- Modify: `docker/README.md:218-238` (CI/CD 集成部分)

- [ ] **Step 1: 更新"运行测试"部分**

将第 34-46 行替换为：

```markdown
### 运行测试

**CI 模式（推荐）：**

```bash
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

成功后容器自动删除，失败后容器保持运行便于调试。

**本地调试模式：**

```bash
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh
```

不使用 `--rm`，无论成功失败容器都会保留，便于查看测试产物。

**交互式运行（直接进入 bash）：**

```bash
docker-compose -f docker/docker-compose.test.yml run npm-test /bin/bash
# 容器内执行：
/project/docker/scripts/docker-test.sh
```
```

- [ ] **Step 2: 更新"CI/CD 集成"部分**

将第 222-238 行替换为：

```yaml
```yaml
- name: Run Docker Tests
  run: |
    docker-compose -f docker/docker-compose.test.yml build
    docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh

- name: Upload Test Results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: test-results
    path: test-results/
```

关键配置：
- `--rm` — 容器退出后自动删除
- 测试成功时容器自动退出，失败时保持运行便于调试
```

- [ ] **Step 3: 提交修改**

```bash
git add docker/README.md
git commit -m "docs: 更新 Docker 测试文档，说明自动退出行为

- 移除 AUTO_CLEANUP 环境变量说明
- 更新 CI 模式说明：成功自动退出，失败保留容器

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: 清理旧设计文档

**Files:**
- Delete: `docs/superpowers/specs/2026-03-25-docker-auto-cleanup-design.md`
- Delete: `docs/superpowers/plans/2026-03-25-docker-auto-cleanup.md`

- [ ] **Step 1: 删除旧设计文档和计划**

```bash
git rm docs/superpowers/specs/2026-03-25-docker-auto-cleanup-design.md
git rm docs/superpowers/plans/2026-03-25-docker-auto-cleanup.md
git commit -m "docs: 删除旧的 AUTO_CLEANUP 设计文档

被 2026-03-25-docker-auto-exit-design.md 替代

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: 验证修改

- [ ] **Step 1: 检查脚本语法**

```bash
bash -n docker/scripts/docker-test.sh
```

Expected: 无输出（语法正确）

- [ ] **Step 2: 确认所有修改已提交**

```bash
git status
```

Expected: 工作目录干净，无未提交修改
