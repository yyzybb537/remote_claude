# Docker 测试

本目录包含 Docker 测试配置，用于验证 npm 包在不同环境下的完整性和功能可用性。

## 目录结构

```
docker/
├── Dockerfile.test              # Docker 测试镜像定义
├── docker-compose.test.yml      # Docker Compose 配置
├── scripts/
│   ├── docker-test.sh           # 主测试脚本
│   └── docker-diagnose.sh       # 失败诊断脚本
└── README.md                    # 本文档
```

## 快速开始

### 构建镜像

```bash
docker-compose -f docker/docker-compose.test.yml build
```

### 运行测试

**CI 模式（推荐）：**

```bash
KEEP_CONTAINER_ALIVE=0 docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

成功后容器自动退出，失败时也不会在脚本内部驻留。

**本地调试模式：**

```bash
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh
```

默认 `KEEP_CONTAINER_ALIVE=1`，脚本执行完成后容器保持运行，便于查看测试产物。

**交互式运行（直接进入 bash）：**

### 查看结果

```bash
ls -lh test-results/
cat test-results/test_report.md
```

## 测试流程

Docker 测试模拟真实用户从 npm 安装 remote-claude 的完整流程：

1. **环境检查** - 验证 Python、uv、tmux、npm、Claude CLI
2. **打包 npm 包** - 执行 `npm pack` 生成 `.tgz` 文件
3. **模拟用户安装** - 在临时目录执行 `npm install <packaged_file>`
4. **验证 postinstall** - 检查 .venv、pyproject.toml、Python 依赖
5. **测试 env 配置与启动行为** - 验证 `check-env.sh` 非阻塞、`lark start`/`remote-claude start` 启动链路
6. **测试基本命令** - 验证 `remote-claude --help`、`remote-claude list`、`cla` 脚本
7. **执行单元测试** - 运行独立单元测试（不需要活跃会话）
8. **文件完整性检查** - 验证当前打包产物中的关键入口与模板文件存在
9. **生成测试报告** - 汇总测试结果，生成 Markdown 报告
10. **清理** - 停止会话、清理 socket 文件、清理 npm 缓存

## 独立单元测试

以下单元测试不需要活跃的会话：

- `test_format_unit.py` - 格式化逻辑单元测试
- `test_stream_poller.py` - 流式卡片模型测试
- `test_renderer.py` - 终端渲染器测试
- `test_output_clean.py` - 输出清理器测试
- `lark_client/test_mock_output.py` - 飞书客户端输出模拟测试
- `lark_client/test_cjk_width.py` - CJK 字符宽度测试
- `lark_client/test_full_simulation.py` - 完整模拟测试

## 调试失败

### 进入容器

```bash
docker exec -it remote-claude-npm-test /bin/bash
```

### 重新运行测试

```bash
cd /project
/project/docker/scripts/docker-test.sh
```

### 手动执行失败的测试

```bash
cd /home/testuser/test-npm-install/node_modules/remote-claude
python3 tests/test_format_unit.py
```

### 收集诊断信息

```bash
/project/docker/scripts/docker-diagnose.sh
```

诊断信息将保存到 `/home/testuser/test-results/diagnosis/` 目录。

## 清理

```bash
# 停止并删除容器
docker-compose -f docker/docker-compose.test.yml down

# 删除镜像
docker rmi remote-claude-npm-test

# 删除测试结果
rm -rf test-results
```

## CI/CD 集成

在 GitHub Actions 或其他 CI/CD 平台中集成：

```yaml
- name: Run Docker Tests
  run: |
    docker-compose -f docker/docker-compose.test.yml build
    docker-compose -f docker/docker-compose.test.yml run --rm npm-test

- name: Upload Test Results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: test-results
    path: test-results/
```

## 设计决策

### 为什么选择 Debian slim 而非 Alpine？

- Alpine 缺少 PTY 所需的系统库，需要额外构建
- tmux 在 Alpine 上编译复杂
- Debian slim 稳定且体积可控

### 为什么保留 Codex CLI？

- 项目支持 Claude/Codex 双入口
- Docker 回归需要覆盖 Codex 安装可用性
- 避免 npm 包发布后出现入口缺失

### 为什么使用非 root 用户？

- 模拟真实用户安装场景
- 避免权限问题导致的假阳性测试

## 文件说明

- `Dockerfile.test` - 定义 Docker 测试镜像，包含所有必要的依赖
- `docker-compose.test.yml` - Docker Compose 配置，挂载项目代码和测试结果目录
- `docker-test.sh` - 主测试脚本，执行完整的测试流程
- `docker-diagnose.sh` - 诊断脚本，测试失败时收集诊断信息
- `test-results/` - 测试结果输出目录（包含测试报告和日志）

## 常见问题

### 测试失败但本地成功？

Docker 环境可能与本地环境不同。检查：

1. Docker 镜像中的依赖版本是否满足要求
2. 文件权限是否正确
3. 环境变量是否正确设置

### npm install 失败？

查看日志：

```bash
cat test-results/npm_install.log
```

### 单元测试失败？

查看具体的测试日志：

```bash
cat test-results/test_format_unit.log
```

## 联系支持

如遇问题，请将 `/home/testuser/test-results/` 目录或 `diagnosis.tar.gz` 打包并发送给开发者。
