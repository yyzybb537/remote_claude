# 设计文档：统一 uv 使用方式，实现零 Python 依赖安装

**日期**: 2026-03-23
**状态**: 待审批

## 背景

当前项目中存在 Python 执行方式混用：
- `uv run python3` — 推荐方式
- `source .venv/bin/activate` + `python3` — install.sh 中使用
- `.venv/bin/python` — 文档中提及
- `pip3` — 安装 uv 的备选方案

此外，`init.sh` 和 `scripts/install.sh` 中使用 `pip3 install uv` 作为备选安装方式，这要求用户预装 Python/pip，违背"零依赖安装"目标。

## 目标

1. **统一 Python 执行方式**：全部使用 `uv run python3` 或 `uv pip`
2. **实现零 Python 依赖安装**：用户无需预装 Python，只需 uv 官方脚本
3. **不修改用户环境配置**：保留现有 shell rc 写入逻辑不变

## 修改范围

### 1. `scripts/install.sh`

| 位置 | 当前内容 | 修改为 |
|------|---------|--------|
| `check_and_install_uv` 函数 | pip3 安装备选方案 | 移除，仅保留官方脚本安装 |
| `verify_installation` 函数 | `source .venv/bin/activate` + `python3` | `uv run python3` |
| `show_next_steps` 函数 | 仅说明 activate | 保留 activate 说明，补充推荐 `uv run` |

**修改后 `check_and_install_uv` 逻辑**：
```bash
# 方式一：官方安装脚本
curl -LsSf https://astral.sh/uv/install.sh | sh

# 方式二（macOS）：brew install uv

# 失败时提示用户手动安装，不再尝试 pip3
```

### 2. `init.sh`

| 位置 | 当前内容 | 修改为 |
|------|---------|--------|
| `check_uv` 函数 | pip3/conda/brew 多种备选方案 | 移除 pip3/conda 备选，仅保留官方脚本和 brew |
| `setup_path` 函数 | 写入 `.bash_profile` | **不修改**（保留现有逻辑） |
| `configure_shell` 函数 | 写入 `.bashrc`/`.zshrc` | **不修改**（保留现有逻辑） |

**修改后 `check_uv` 逻辑**：
```bash
# 方式一：官方安装脚本
curl -LsSf https://astral.sh/uv/install.sh | sh

# 方式二（macOS）：brew install uv

# 失败时提示用户访问官方文档，不再尝试 pip3/conda
```

### 3. `docker/scripts/docker-diagnose.sh`

| 位置 | 当前内容 | 修改为 |
|------|---------|--------|
| 第 115 行 | `pip3 list` | `uv pip list` |
| 第 121 行 | `.venv/bin/pip list` | `uv pip list` |

### 4. `README.md`

| 位置 | 当前内容 | 修改为 |
|------|---------|--------|
| 第 81 行 | `.venv/bin/python remote_claude.py --help` | `uv run python3 remote_claude.py --help` |

### 5. `docker/README.md`

| 位置 | 当前内容 | 修改为 |
|------|---------|--------|
| 第 77 行 | `.venv/bin/python remote_claude.py --help` | `uv run python3 remote_claude.py --help` |
| 第 109 行 | `test-results/npm-install/.venv/bin/python --version` | `uv run python3 --version` |
| 第 112 行 | `test-results/npm-install/.venv/bin/python -c "..."` | `uv run python3 -c "..."` |

## 不修改的范围

- `specs/` 目录下的设计文档（历史记录）
- `init.sh` 中的 `setup_path`、`configure_shell` 函数（保留自动写入 shell rc 的逻辑）
- `init.sh` 中的 tmux 安装逻辑
- `init.sh` 中的快捷命令符号链接逻辑

## 安装流程优化

**优化前**：
```
curl | sh → 安装 uv
    ↓ (失败)
pip3 install uv → 需要 Python/pip
    ↓ (失败)
conda install uv → 需要 conda
```

**优化后**：
```
curl | sh → 安装 uv（官方脚本，独立工作）
    ↓ (失败)
brew install uv → macOS 备选
    ↓ (失败)
提示用户手动安装 → 访问官方文档
```

**依赖安装流程**：
```
uv python install 3.11 → 安装隔离的 Python（如系统无合适版本）
uv sync → 安装项目依赖到 .venv
```

## 验证方案

1. **本地测试**：在无 Python 环境的容器中运行 `scripts/install.sh`
2. **Docker 测试**：运行 `docker/scripts/docker-test.sh` 验证完整流程
3. **功能测试**：运行 `uv run python3 tests/test_runtime_config.py`

## 文件清单

| 文件 | 修改类型 |
|------|---------|
| `scripts/install.sh` | 修改 |
| `init.sh` | 修改 |
| `docker/scripts/docker-diagnose.sh` | 修改 |
| `README.md` | 修改 |
| `docker/README.md` | 修改 |

## 风险评估

- **低风险**：修改范围明确，不影响现有 shell 配置写入逻辑
- **向后兼容**：已安装用户不受影响，`uv run` 自动使用现有 `.venv`
