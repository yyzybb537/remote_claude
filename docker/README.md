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

```bash
# 运行测试（测试完成后容器保持运行，可继续进入调试）
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh

# 交互式运行（直接进入 bash，手动执行测试）
docker-compose -f docker/docker-compose.test.yml run npm-test /bin/bash
# 容器内执行：
/project/docker/scripts/docker-test.sh
```

### 环境清理

```bash
docker-compose -f docker/docker-compose.test.yml down --remove-orphans
```

### 查看结果

```bash
ls -lh test-results/
cat test-results/test_report.md
```

## 宿主机使用 Docker 产物安装

Docker 测试完成后，`test-results/` 目录包含完整的安装产物，可直接在宿主机上使用：

### 产物说明

```
test-results/
├── npm-install/                 # npm 安装目录
│   ├── .venv/                   # Python 虚拟环境（便携式）
│   └── node_modules/
│       └── remote-claude/       # 完整项目代码
│           ├── bin/             # 可执行脚本（cla, cl, cx, cdx）
│           └── remote_claude.py # 主入口
├── test_report.md               # 测试报告
└── version.txt                  # 版本号
```

### 宿主机快速使用

```bash
# 方式一：直接运行（需要宿主机有 Python 3.11+）
cd test-results/npm-install/node_modules/remote-claude
./bin/cla  # 启动 Claude 会话

# 方式二：使用虚拟环境中的 Python（推荐，完全隔离）
cd test-results/npm-install/node_modules/remote-claude
.venv/bin/python remote_claude.py --help

# 方式三：激活虚拟环境后使用
source test-results/npm-install/.venv/bin/activate
remote-claude --help
```

### 可执行脚本

`bin/` 目录下提供以下快捷命令：

| 脚本 | 说明 |
|------|------|
| `cla` | 启动 Claude（以当前目录为会话名） |
| `cl` | 同 `cla`，跳过权限确认 |
| `cx` | 启动 Codex（以当前目录为会话名，跳过权限确认） |
| `cdx` | 同 `cx`，需要确认权限 |

### 前置要求

宿主机使用 Docker 产物需要：

1. **必需工具**：tmux、git
2. **CLI 工具**：Claude CLI 或 Codex CLI（至少一个）
3. **可选**：飞书企业自建应用（用于飞书客户端）

> **注意**：产物中已包含便携式 Python 虚拟环境（`.venv`），宿主机无需预装 Python。

### 验证安装

```bash
# 验证 Python 环境
test-results/npm-install/.venv/bin/python --version

# 验证依赖
test-results/npm-install/.venv/bin/python -c "import lark_oapi; print('✓ 依赖完整')"

# 验证命令可用
test-results/npm-install/node_modules/remote-claude/bin/cla --help
```

## 测试流程

Docker 测试模拟真实用户从 npm 安装 remote-claude 的完整流程：

1. **环境检查** - 验证 Python、uv、tmux、npm、Claude CLI、Codex CLI
2. **打包 npm 包** - 执行 `npm pack` 生成 `.tgz` 文件
3. **模拟用户安装** - 在临时目录执行 `npm install <packaged_file>`
4. **验证 postinstall** - 检查 .venv、pyproject.toml、Python 依赖
5. **测试基本命令** - 验证 `remote-claude --help`、`remote-claude list`、`cla` 脚本
6. **验证 Claude/Codex CLI 启动** - 测试 `cla`/`cl`/`cx`/`cdx` 快捷命令启动流程
7. **文件完整性检查** - 验证关键文件（含 resources/defaults/ 模板文件）是否存在
8. **执行独立单元测试** - 运行核心测试（失败终止）和非核心测试（失败继续）
9. **生成测试报告** - 汇总测试结果，生成 Markdown 报告
10. **清理** - 停止会话、清理 socket 文件、清理 npm 缓存

## 独立单元测试

以下单元测试不需要活跃的会话：

**核心测试**（失败终止整个测试流程）：
- `test_session_truncate.py` - 会话名称截断测试
- `test_runtime_config.py` - 运行时配置管理测试

> 注：`test_format_unit.py` 已从核心测试中移除，因为测试的方法 `_format_plain_output` 从未实现。

**非核心测试**（失败继续执行，记录警告）：
- `test_stream_poller.py` - 流式卡片模型测试
- `test_card_interaction.py` - 卡片交互优化测试
- `test_list_display.py` - List 命令展示测试
- `test_log_level.py` - 日志级别处理测试
- `test_disconnected_state.py` - 断开状态提示测试
- `test_renderer.py` - 终端渲染器测试
- `lark_client/test_mock_output.py` - 飞书客户端输出模拟测试
- `lark_client/test_cjk_width.py` - CJK 字符宽度测试
- `lark_client/test_full_simulation.py` - 完整模拟测试

> 注：`test_output_clean.py` 已移除（废弃代码）。

## 调试失败

### 进入容器

```bash
docker exec -it remote-claude-npm-test /bin/bash
```

### 重新运行测试

```bash
cd /project
/home/testuser/docker/docker-test.sh
```

### 手动执行失败的测试

```bash
cd /home/testuser/test-npm-install/node_modules/remote-claude
python3 tests/test_format_unit.py
```

### 收集诊断信息

```bash
/home/testuser/docker/scripts/docker-diagnose.sh
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

### 为什么选择 Ubuntu 而非 Alpine？

- Alpine 缺少 PTY 所需的系统库，需要额外构建
- tmux 在 Alpine 上编译复杂
- Ubuntu 22.04 稳定且体积可控

### 为什么跳过 Codex CLI？

- 用户明确选择不需要
- 节省构建时间和镜像空间
- Codex 是可选功能，不影响核心流程

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
