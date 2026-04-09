# Docker 测试

Docker 回归用于验证 npm 打包、安装脚本与容器内启动链路在接近真实用户环境中的可用性。本页是 Docker 测试的权威正文；测试分层与更多回归入口请参考 [`../tests/README.md`](../tests/README.md)。

## 目录内容

```text
docker/
├── Dockerfile.test              # Docker 测试镜像定义
├── docker-compose.test.yml      # Docker Compose 配置
├── scripts/
│   ├── docker-test.sh           # 主测试脚本
│   └── docker-diagnose.sh       # 失败诊断脚本
└── README.md                    # Docker 测试说明
```

## 入口

Docker 回归的默认入口是 `docker/scripts/docker-test.sh`，通常通过 `docker-compose.test.yml` 在隔离容器里执行。该链路会模拟用户从 npm 安装 `remote-claude`，再验证安装后入口脚本、基础命令与关键启动行为。

## 常用命令

```bash
# 运行完整 Docker 回归
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh

# 构建测试镜像
docker-compose -f docker/docker-compose.test.yml build

# 进入容器后手动调试
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /bin/bash

# 在容器内重新执行主测试脚本
/project/docker/scripts/docker-test.sh

# 收集失败诊断信息
/project/docker/scripts/docker-diagnose.sh

# 查看宿主机测试产物
ls -lh test-results/
```

## 当前脚本覆盖

当前 Docker 脚本重点覆盖以下场景：

1. `npm pack` 与 `npm install` 后的安装产物完整性。
2. `check-env.sh` 在 `REMOTE_CLAUDE_REQUIRE_FEISHU=0` 下跳过飞书检查。
3. `remote-claude lark start` 在 mock 凭证下不会无限阻塞。
4. `remote-claude start` 的 Claude / Codex 启动链路。
5. 关键 shell 入口脚本、安装产物和基础 CLI 行为回归。

## 产物与日志

默认测试产物输出到宿主机 `test-results/`，常见内容包括：

- `test-results/test_report.md`：测试报告汇总。
- `test-results/` 下的命令日志与失败日志。
- `test-results/diagnosis/`：执行诊断脚本后生成的诊断信息。

排查时可优先查看：

```bash
cat test-results/test_report.md
ls -lh test-results/
```

## 失败诊断

当 Docker 回归失败时，优先执行：

```bash
/project/docker/scripts/docker-diagnose.sh
```

诊断脚本会收集：

- 系统信息与依赖版本
- npm / Python 包安装信息
- 安装后文件结构
- `remote-claude list` 输出
- `/tmp/remote-claude` socket 目录状态
- `tmux list-sessions` 输出
- `~/.remote-claude/startup.log` 尾部日志
- `test-results/` 下的日志与错误摘要

若需要进一步手动复现，也可直接进入测试容器后重新运行主测试脚本。

## 与其他文档的分工

- [`../tests/README.md`](../tests/README.md)：测试分层、推荐回归命令与专项回归导航。
- [`../docs/developer.md`](../docs/developer.md)：开发者总览与其他项目级入口。
