# Research: 命令行与飞书用户体验增强

**Feature**: `20260319-cmd-ux-enhancements`
**Date**: 2026-03-19

## 概述

本文档记录 Phase 0 研究结果，解决技术上下文中的待澄清项和最佳实践决策。

---

## 1. 会话名称截断策略研究

### 问题

当前 `_safe_filename()` 实现直接使用完整 MD5 哈希，丢失了路径的语义信息。需要优化截断策略，保留路径后缀的可读性。

### 决策

**采用从右向左保留路径后缀的策略**

### 理由

1. **语义优先级**：路径后缀通常包含项目名称和具体功能模块，比前缀（用户目录、系统路径）更有辨识价值
2. **示例**：
   - 原始路径：`/Users/dev/projects/myapp/src/components/utils/helpers`
   - 当前策略：`a1b2c3d4e5f6...`（32 字符哈希，无语义）
   - 优化策略：`myapp_src_components_utils_helpers`（保留后缀）

### 实现方案

```python
def _safe_filename(session_name: str) -> str:
    """优化后的截断策略：优先保留路径后缀"""
    # 1. 替换特殊字符
    name = session_name.replace('/', '_').replace('.', '_')

    # 2. 检查长度
    if len(name) <= _MAX_FILENAME:
        return name

    # 3. 从右向左保留后缀
    parts = name.split('_')
    result = []
    total_len = 0

    for part in reversed(parts):
        new_len = total_len + len(part) + (1 if result else 0)
        if new_len > _MAX_FILENAME:
            break
        result.insert(0, part)
        total_len = new_len

    # 4. 如果单个部分都超长，回退到 MD5
    if not result:
        return hashlib.md5(session_name.encode()).hexdigest()[:_MAX_FILENAME]

    return '_'.join(result)
```

### 备选方案

| 方案 | 优点 | 缺点 | 是否采纳 |
|------|------|------|----------|
| 完整 MD5 | 无冲突 | 无语义 | ❌ 作为回退 |
| 保留前缀 | 简单 | 用户目录无意义 | ❌ |
| 保留后缀 | 语义清晰 | 需处理冲突 | ✅ 采纳 |
| 混合策略（前缀+后缀） | 信息量大 | 实现复杂 | ❌ 过度设计 |

---

## 2. 名称冲突检测机制研究

### 问题

不同原始路径可能产生相同的截断名称，需要检测和处理冲突。

### 决策

**映射存储 + 冲突检测：检查原始路径是否相同**

### 理由

1. 同一目录重复启动应复用会话（现有行为）
2. 不同目录产生相同截断名称应添加随机后缀

### 实现方案

```python
def resolve_session_name(original_path: str, config: RuntimeConfig) -> str:
    """解析会话名称，处理冲突"""
    truncated = _safe_filename(original_path)

    # 检查映射
    existing = config.get_session_mapping(truncated)
    if existing:
        if existing == original_path:
            # 同一目录，复用
            return truncated
        else:
            # 不同目录，使用完整 MD5 哈希（不重试随机后缀）
            return hashlib.md5(original_path.encode()).hexdigest()[:_MAX_FILENAME]

    # 新会话，记录映射
    config.set_session_mapping(truncated, original_path)
    return truncated
```

---

## 3. runtime.json 结构设计研究

### 问题

需要一个统一的运行时配置文件，支持会话映射、群组映射、快捷命令配置等多种数据。

### 决策（已更新 2026-03-19）

**配置文件拆分：config.json（用户配置）+ runtime.json（程序状态）**

### 决策（已更新 2026-03-21）

**默认配置内容存储方式**：独立模板文件，存放在 `resources/defaults/` 目录下：
- `config.default.json` - 用户配置模板
- `runtime.default.json` - 运行时配置模板
- `.env.example` - 环境变量示例

代码通过读取模板文件进行初始化，不再硬编码默认配置内容。

### 理由

1. **语义清晰**：用户可编辑配置与程序自动管理状态分离
2. **便于维护**：用户不会意外修改程序状态
3. **锁文件明确**：只需对 runtime.json 加锁（程序写入）

### 结构设计

**config.json（用户配置）**：
```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"}
      ]
    }
  }
}
```

**runtime.json（程序状态）**：
```json
{
  "version": "1.0",
  "session_mappings": {
    "myapp_src_comp": "/Users/dev/projects/myapp/src/components"
  },
  "lark_group_mappings": {
    "oc_xxx": "my-session"
  }
}
```

### 设计理由

1. **version 字段**：便于后续迁移
2. **config.json**：用户可手动编辑的 UI 设置
3. **runtime.json**：程序自动管理的会话状态
4. **分离好处**：用户不会意外修改程序状态，程序不会覆盖用户设置

### ~~旧决策（已废弃）~~

~~分层结构，按功能模块组织~~
~~所有配置放在单一 `runtime.json` 中~~

---

## 4. 飞书卡片 select_static 最佳实践

### 问题

快捷命令选择器需要使用飞书卡片的 select_static 元素，需要确认其用法和限制。

### 决策

**使用 select_static 元素，配合 callback 回调**

### 飞书卡片结构

```json
{
  "tag": "action",
  "actions": [{
    "tag": "select_static",
    "placeholder": {"tag": "plain_text", "content": "快捷命令"},
    "options": [
      {"text": {"tag": "plain_text", "content": "🗑️ 清空对话"}, "value": "/clear"},
      {"text": {"tag": "plain_text", "content": "📦 压缩上下文"}, "value": "/consume"}
    ]
  }]
}
```

### 注意事项

1. options 最多 100 项（本项目不超过 10 项）
2. value 最大 100 字符（命令字符串足够）
3. 回调事件通过卡片回调机制处理

---

## 5. argparse --help 行为验证

### 问题

需要验证 argparse 的默认 --help 行为是否满足"只显示帮助，不执行操作"的需求。

### 验证结果

**argparse 默认行为满足需求**

### 验证方式

```python
import argparse

parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers()

start_parser = subparsers.add_parser('start')
start_parser.add_argument('name')

# 执行: python script.py start --help
# 结果: 打印帮助信息后直接退出（sys.exit(0)）
```

### 结论

无需修改，argparse 在解析到 `--help` 时会立即打印帮助并退出，不会执行后续逻辑。

---

## 6. 配置迁移策略研究

### 问题

存在旧配置文件 `lark_group_mapping.json`，需要迁移到新的 `runtime.json`。

### 决策

**启动时自动迁移，迁移后删除旧文件**

> **注意**：此迁移仅针对旧 `lark_group_mapping.json` 文件。`config.json` 和 `runtime.json` 均为全新配置文件，无需迁移逻辑。

### 迁移流程

```
1. 检查 lark_group_mapping.json 是否存在
2. 读取旧文件内容
3. 写入 runtime.json 的 lark_group_mappings 字段
4. 删除旧文件
5. 记录日志
```

### 冲突处理

如果 `runtime.json` 已存在 `lark_group_mappings`：
- 以 `runtime.json` 为准
- 删除旧文件
- 输出警告日志

---

## 7. 配置版本迁移策略研究

### 问题

`runtime.json` 有 `version` 字段，需要定义版本升级时的迁移行为。

### 决策

**实现版本迁移函数，按版本号逐步升级配置**

### 理由

1. 用户配置应被保留，升级不应丢失设置
2. 逐步迁移模式稳定可靠，便于维护
3. 便于后续扩展新字段

### 实现方案

```python
CURRENT_VERSION = "1.0"

def migrate_config(config: dict) -> dict:
    """按版本号逐步迁移配置"""
    version = config.get("version", "1.0")

    # 版本迁移链
    migrations = {
        # "1.0": migrate_to_1_1,
        # "1.1": migrate_to_1_2,
    }

    while version in migrations:
        config = migrations[version](config)
        version = config["version"]

    return config
```

---

## 8. 文件锁注释设计研究

### 问题

锁文件需要包含注释，便于用户理解文件用途。

### 决策

**锁文件写入详细信息（用途 + PID + 创建时间）**

### 锁文件内容

```
# Remote Claude 配置文件锁
# 用途: 防止并发写入导致配置损坏
# 创建进程 PID: 12345
# 创建时间: 2026-03-19T14:30:00+08:00
# 说明: 此文件在配置写入时自动创建，写入完成后自动删除
#       如果程序异常退出，此文件可能残留，可安全删除
```

### 理由

1. **用途说明**：帮助用户理解文件目的
2. **PID 信息**：便于排查哪个进程持有锁
3. **创建时间**：便于判断锁文件是否残留
4. **安全删除说明**：告知用户残留时可安全删除

---

## 9. 会话退出清理策略研究

### 问题

会话退出时，是否清理 session_mappings 映射？

### 决策（2026-03-19 澄清会话）

**删除映射（新策略，替换原有"保留映射"策略）**

### 理由

1. **配置清洁**：避免映射表无限增长
2. **用户预期**：会话退出后，相关状态应被清理
3. **保留 lark_group_mappings**：群组绑定保留便于重新连接

### 实现方案

```python
def remove_session_mapping(truncated_name: str) -> None:
    """会话退出时删除对应的映射条目"""
    config = load_runtime_config()
    if truncated_name in config.session_mappings:
        del config.session_mappings[truncated_name]
        save_runtime_config(config)
        logger.info(f"已删除会话映射: {truncated_name}")
```

---

## 10. 配置迁移 bak 文件清理策略研究

### 问题

配置迁移过程中可能产生 `.bak` 备份文件，如何保证正常运行时无残留？

### 决策（2026-03-19 澄清会话）

**迁移成功后立即删除 bak 文件，启动时检测残留并提示用户处理**

### 理由

1. **配置目录清洁**：避免残留文件干扰用户
2. **一致性保证**：确保配置状态明确，无歧义
3. **用户体验**：异常情况（程序崩溃）后提供恢复选项

### 实现方案

```python
def cleanup_backup_after_migration():
    """迁移成功后清理 bak 文件"""
    for bak_file in USER_DATA_DIR.glob("*.json.bak*"):
        bak_file.unlink()
        logger.info(f"已删除备份文件: {bak_file}")

def check_stale_backup() -> Optional[Path]:
    """检查残留的 bak 文件"""
    config_dir = USER_DATA_DIR
    bak_files = list(config_dir.glob("*.json.bak*"))
    return bak_files[0] if bak_files else None

def prompt_backup_action(bak_path: Path) -> str:
    """提示用户处理残留 bak 文件

    返回: 'overwrite' 或 'skip'
    """
    print(f"检测到残留的备份文件: {bak_path}")
    print("1. 覆盖当前配置并重新迁移")
    print("2. 跳过（删除备份文件继续）")
    choice = input("请选择 [1/2]: ").strip()
    return 'overwrite' if choice == '1' else 'skip'
```

### 处理流程

| 场景 | 处理方式 |
|------|----------|
| 迁移/修改成功 | 立即删除 `.bak` 文件 |
| 启动时检测残留 bak | 提示用户选择覆盖或跳过 |
| 程序异常退出 | bak 残留，下次启动处理 |

---

所有 NEEDS CLARIFICATION 项已解决，可进入 Phase 1 设计阶段。

---

## 23. Python 环境便携化策略研究

### 问题

如何让用户无需预装 Python 即可使用项目？

### 决策（2026-03-23 澄清会话）

**项目自带便携式 Python，使用 uv 管理隔离环境**

### 策略详情

| 策略项 | 决策 | 理由 |
|--------|------|------|
| Python 依赖 | 项目自带便携式 Python | 降低用户安装门槛，避免版本兼容问题 |
| 包管理器 | uv 管理，自动创建隔离环境 | uv 快速且支持 Python 版本管理 |
| Docker venv | 构建时创建，运行时激活 | 确保 Docker 测试环境一致性 |
| 产物提取 | 包含便携式 Python | 宿主机无需预装，完全自包含 |
| 预装方式 | 安装包/Docker 镜像内置 | 无需运行时下载，开箱即用 |

### 实现方案

```bash
# 项目结构
remote-claude/
├── .python-version        # 指定 Python 版本（如 3.11）
├── pyproject.toml         # 项目依赖
├── uv.lock               # 依赖锁定
└── scripts/
    └── install.sh        # 安装脚本，自动使用 uv 创建环境

# 安装脚本示例
#!/bin/bash
# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# uv 自动安装 Python 并创建虚拟环境
uv sync

# 运行程序
uv run python remote_claude.py "$@"
```

### Docker 配置

```dockerfile
# Dockerfile.test
FROM python:3.11-slim

# 安装 uv
RUN pip install uv

# 创建项目目录
WORKDIR /project

# 复制依赖文件
COPY pyproject.toml uv.lock ./

# uv 创建虚拟环境并安装依赖
RUN uv sync --frozen

# 激活虚拟环境
ENV VIRTUAL_ENV=/project/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 复制项目文件
COPY . .

# 运行测试
CMD ["/project/.venv/bin/python", "-m", "pytest"]
```

### 产物提取

```bash
# docker-test.sh 产物提取
extract_artifacts() {
    mkdir -p test_results/

    # 提取 venv（包含 Python 解释器）
    docker cp remote-claude-test:/project/.venv test_results/venv

    # 提取脚本
    docker cp remote-claude-test:/project/bin test_results/bin

    # 生成宿主机运行脚本
    cat > test_results/run.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/bin/cla" "$@"
EOF
    chmod +x test_results/run.sh
}
```

### 用户安装流程

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/xxx/remote-claude/main/install.sh | bash

# 或克隆后安装
git clone https://github.com/xxx/remote-claude.git
cd remote-claude
./scripts/install.sh

# 运行
cla start my-session
```

### 优势

1. **零依赖安装**：用户无需预装 Python
2. **版本隔离**：uv 管理的 Python 不影响系统 Python
3. **快速安装**：uv 比 pip 快 10-100 倍
4. **一致性**：开发、测试、生产环境完全一致
5. **便携性**：产物可在无 Python 环境的机器上运行

---

所有 NEEDS CLARIFICATION 项已解决，可进入 Phase 1 设计阶段。

| 研究项 | 决策 | 状态 |
|--------|------|------|
| 截断策略 | 保留路径后缀 | ✅ 已解决 |
| 冲突检测 | 映射存储 + 原始路径比较 | ✅ 已解决 |
| 配置结构 | 拆分为 config.json + runtime.json | ✅ 已更新 |
| select_static 用法 | 标准飞书卡片元素 | ✅ 已解决 |
| argparse 行为 | 无需修改 | ✅ 已验证 |
| 配置迁移 | 自动迁移 + 删除旧文件 | ✅ 已设计 |
| 文件锁注释 | 用途 + PID + 创建时间 | ✅ 已解决 |
| 会话退出清理 | 删除映射（新策略） | ✅ 已更新 |
| bak 文件清理 | 迁移后删除 + 启动检测 | ✅ 已解决 |

---

## 11. 飞书卡片就地更新机制研究

### 问题

交互操作（按钮点击、文本提交）时，如何实现就地更新卡片而非推送新卡片？

### 决策（2026-03-19 澄清会话）

**使用 `update_card` API 就地更新现有卡片**

### 理由

1. **用户体验**：避免卡片刷屏，保持对话流畅
2. **视觉反馈**：通过状态变化（按钮 disabled、"处理中"）提供即时反馈
3. **飞书 API 支持**：`update_card` 支持完整卡片内容更新

### 实现方案

```python
def handle_button_click(card_id: str, action_value: str) -> None:
    """处理按钮点击，就地更新卡片"""
    # 1. 构建带 loading 状态的卡片
    loading_card = build_card_with_loading_state(
        is_loading=True,
        disabled_buttons=["all"]
    )

    # 2. 就地更新卡片
    update_card(card_id, loading_card)

    # 3. 执行实际操作
    result = execute_action(action_value)

    # 4. 更新卡片显示结果
    result_card = build_card_with_result(result)
    update_card(card_id, result_card)
```

### 降级策略

| 场景 | 处理方式 |
|------|----------|
| `update_card` 失败（网络问题） | 降级为发送新卡片 + 记录警告日志 |
| 卡片已被删除 | 发送新卡片 |
| 快速连续交互 | 按钮 disabled 防抖 500ms |

---

## 12. 飞书卡片回车自动确认研究

### 问题

如何在文本输入框中支持回车自动提交？

### 决策（2026-03-19 澄清会话）

**使用飞书卡片 `enter_key_action` 属性，仅支持单行输入框**

### 理由

1. **输入效率**：用户无需点击确认按钮，提升操作流畅度
2. **行为一致性**：单行输入框回车提交是常见 UX 模式
3. **多行保留换行**：多行文本框回车应换行而非提交

### 实现方案

```json
{
  "tag": "input",
  "placeholder": {"tag": "plain_text", "content": "输入消息..."},
  "element_id": "message_input",
  "enter_key_action": {
    "tag": "action",
    "actions": [{
      "tag": "button",
      "text": {"tag": "plain_text", "content": "发送"},
      "type": "primary",
      "value": "{\"action\": \"send_message\"}"
    }]
  }
}
```

### 注意事项

| 场景 | 行为 |
|------|------|
| 单行输入框 + 回车 | 触发提交 |
| 多行输入框 + 回车 | 换行（不提交） |
| 空输入 + 回车 | 不触发提交（前端校验） |
| 移动端（无物理回车） | 保留确认按钮备选 |

---

所有 NEEDS CLARIFICATION 项已解决，可进入 Phase 1 设计阶段。

---

## 23. Python 环境便携化策略研究

### 问题

如何让用户无需预装 Python 即可使用项目？

### 决策（2026-03-23 澄清会话）

**项目自带便携式 Python，使用 uv 管理隔离环境**

### 策略详情

| 策略项 | 决策 | 理由 |
|--------|------|------|
| Python 依赖 | 项目自带便携式 Python | 降低用户安装门槛，避免版本兼容问题 |
| 包管理器 | uv 管理，自动创建隔离环境 | uv 快速且支持 Python 版本管理 |
| Docker venv | 构建时创建，运行时激活 | 确保 Docker 测试环境一致性 |
| 产物提取 | 包含便携式 Python | 宿主机无需预装，完全自包含 |
| 预装方式 | 安装包/Docker 镜像内置 | 无需运行时下载，开箱即用 |

### 实现方案

```bash
# 项目结构
remote-claude/
├── .python-version        # 指定 Python 版本（如 3.11）
├── pyproject.toml         # 项目依赖
├── uv.lock               # 依赖锁定
└── scripts/
    └── install.sh        # 安装脚本，自动使用 uv 创建环境

# 安装脚本示例
#!/bin/bash
# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# uv 自动安装 Python 并创建虚拟环境
uv sync

# 运行程序
uv run python remote_claude.py "$@"
```

### Docker 配置

```dockerfile
# Dockerfile.test
FROM python:3.11-slim

# 安装 uv
RUN pip install uv

# 创建项目目录
WORKDIR /project

# 复制依赖文件
COPY pyproject.toml uv.lock ./

# uv 创建虚拟环境并安装依赖
RUN uv sync --frozen

# 激活虚拟环境
ENV VIRTUAL_ENV=/project/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 复制项目文件
COPY . .

# 运行测试
CMD ["/project/.venv/bin/python", "-m", "pytest"]
```

### 产物提取

```bash
# docker-test.sh 产物提取
extract_artifacts() {
    mkdir -p test_results/

    # 提取 venv（包含 Python 解释器）
    docker cp remote-claude-test:/project/.venv test_results/venv

    # 提取脚本
    docker cp remote-claude-test:/project/bin test_results/bin

    # 生成宿主机运行脚本
    cat > test_results/run.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/bin/cla" "$@"
EOF
    chmod +x test_results/run.sh
}
```

### 用户安装流程

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/xxx/remote-claude/main/install.sh | bash

# 或克隆后安装
git clone https://github.com/xxx/remote-claude.git
cd remote-claude
./scripts/install.sh

# 运行
cla start my-session
```

### 优势

1. **零依赖安装**：用户无需预装 Python
2. **版本隔离**：uv 管理的 Python 不影响系统 Python
3. **快速安装**：uv 比 pip 快 10-100 倍
4. **一致性**：开发、测试、生产环境完全一致
5. **便携性**：产物可在无 Python 环境的机器上运行

---

所有 NEEDS CLARIFICATION 项已解决，可进入 Phase 1 设计阶段。

| 研究项 | 决策 | 状态 |
|--------|------|------|
| 截断策略 | 保留路径后缀 | ✅ 已解决 |
| 冲突检测 | 映射存储 + 原始路径比较 | ✅ 已解决 |
| 配置结构 | 拆分为 config.json + runtime.json | ✅ 已更新 |
| select_static 用法 | 标准飞书卡片元素 | ✅ 已解决 |
| argparse 行为 | 无需修改 | ✅ 已验证 |
| 配置迁移 | 自动迁移 + 删除旧文件 | ✅ 已设计 |
| 文件锁注释 | 用途 + PID + 创建时间 | ✅ 已解决 |
| 会话退出清理 | 删除映射（新策略） | ✅ 已更新 |
| bak 文件清理 | 迁移后删除 + 启动检测 | ✅ 已解决 |
| 卡片就地更新 | update_card API | ✅ 已解决 |
| 回车自动确认 | enter_key_action（单行） | ✅ 已解决 |

---

## 13. 连续下划线处理规则研究

### 问题

路径中可能包含连续分隔符（如 `/a//b`），截断处理后会产生连续下划线（`a__b`），是否需要合并？

### 决策（2026-03-19 澄清会话）

**合并为单下划线**

### 理由

1. **可读性**：避免视觉上的冗余下划线
2. **一致性**：与文件系统路径语义一致
3. **简洁性**：减少不必要的字符

### 实现方案

```python
def _normalize_underscores(name: str) -> str:
    """合并连续下划线为单下划线"""
    import re
    return re.sub(r'_+', '_', name)
```

---

## 14. QuickCommand icon 字段格式研究

### 问题

icon 字段的格式限制是什么？仅支持 emoji 还是其他字符？

### 决策（2026-03-19 澄清会话）

**无格式限制，由飞书卡片渲染决定**

### 理由

1. **灵活性**：不限制用户选择图标
2. **飞书兼容**：飞书卡片支持多种字符
3. **可选性**：icon 可为空，空时使用空白占位 emoji

---

## 15. commands 数量上限处理研究

### 问题

当用户配置的命令数量超过 20 条时，如何处理？

### 决策（2026-03-19 澄清会话）

**静默截断（只显示前 20 条）**

### 理由

1. **用户体验**：不中断操作，自动处理
2. **性能考量**：避免下拉列表过长影响体验
3. **飞书限制**：飞书支持 100 条，20 条为建议值

---

## 16. 配置文件权限不足处理研究

### 问题

当配置目录为只读时，如何处理？

### 决策（2026-03-19 澄清会话）

**使用内存配置继续运行，输出警告日志**

### 理由

1. **可用性优先**：不阻止用户使用核心功能
2. **信息透明**：通过日志告知用户配置无法持久化
3. **降级策略**：内存配置保证当前会话正常工作

### 实现方案

```python
def save_runtime_config(config: RuntimeConfig) -> bool:
    """保存配置，返回是否成功"""
    try:
        path = USER_DATA_DIR / "runtime.json"
        path.write_text(json.dumps(asdict(config), indent=2))
        return True
    except PermissionError:
        logger.warning("配置目录权限不足，配置将仅在内存中保留")
        return False
```

---

## 17. 空会话名处理研究

### 问题

用户尝试以空字符串启动会话时，如何处理？

### 决策（2026-03-19 澄清会话）

**拒绝启动并提示"会话名不能为空"**

### 理由

1. **语义明确**：空会话名无意义
2. **用户友好**：明确提示错误原因
3. **避免后续问题**：防止空名称导致的文件系统错误

---

所有 NEEDS CLARIFICATION 项已解决，可进入 Phase 1 设计阶段。

---

## 23. Python 环境便携化策略研究

### 问题

如何让用户无需预装 Python 即可使用项目？

### 决策（2026-03-23 澄清会话）

**项目自带便携式 Python，使用 uv 管理隔离环境**

### 策略详情

| 策略项 | 决策 | 理由 |
|--------|------|------|
| Python 依赖 | 项目自带便携式 Python | 降低用户安装门槛，避免版本兼容问题 |
| 包管理器 | uv 管理，自动创建隔离环境 | uv 快速且支持 Python 版本管理 |
| Docker venv | 构建时创建，运行时激活 | 确保 Docker 测试环境一致性 |
| 产物提取 | 包含便携式 Python | 宿主机无需预装，完全自包含 |
| 预装方式 | 安装包/Docker 镜像内置 | 无需运行时下载，开箱即用 |

### 实现方案

```bash
# 项目结构
remote-claude/
├── .python-version        # 指定 Python 版本（如 3.11）
├── pyproject.toml         # 项目依赖
├── uv.lock               # 依赖锁定
└── scripts/
    └── install.sh        # 安装脚本，自动使用 uv 创建环境

# 安装脚本示例
#!/bin/bash
# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# uv 自动安装 Python 并创建虚拟环境
uv sync

# 运行程序
uv run python remote_claude.py "$@"
```

### Docker 配置

```dockerfile
# Dockerfile.test
FROM python:3.11-slim

# 安装 uv
RUN pip install uv

# 创建项目目录
WORKDIR /project

# 复制依赖文件
COPY pyproject.toml uv.lock ./

# uv 创建虚拟环境并安装依赖
RUN uv sync --frozen

# 激活虚拟环境
ENV VIRTUAL_ENV=/project/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 复制项目文件
COPY . .

# 运行测试
CMD ["/project/.venv/bin/python", "-m", "pytest"]
```

### 产物提取

```bash
# docker-test.sh 产物提取
extract_artifacts() {
    mkdir -p test_results/

    # 提取 venv（包含 Python 解释器）
    docker cp remote-claude-test:/project/.venv test_results/venv

    # 提取脚本
    docker cp remote-claude-test:/project/bin test_results/bin

    # 生成宿主机运行脚本
    cat > test_results/run.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/bin/cla" "$@"
EOF
    chmod +x test_results/run.sh
}
```

### 用户安装流程

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/xxx/remote-claude/main/install.sh | bash

# 或克隆后安装
git clone https://github.com/xxx/remote-claude.git
cd remote-claude
./scripts/install.sh

# 运行
cla start my-session
```

### 优势

1. **零依赖安装**：用户无需预装 Python
2. **版本隔离**：uv 管理的 Python 不影响系统 Python
3. **快速安装**：uv 比 pip 快 10-100 倍
4. **一致性**：开发、测试、生产环境完全一致
5. **便携性**：产物可在无 Python 环境的机器上运行

---

所有 NEEDS CLARIFICATION 项已解决，可进入 Phase 1 设计阶段。

---

## 18. 会话断开提示文本研究

### 问题

快捷命令发送时会话已断开，用户应看到什么提示文本？

### 决策（2026-03-19 澄清会话）

**"会话已断开，请重新连接后重试"**

### 理由

1. **清晰明确**：直接告知用户当前状态
2. **行动导向**：引导用户重新连接
3. **一致性**：与其他断开提示保持一致

---

## 19. disconnected 状态判定时机研究

### 问题

`disconnected` 状态的判定时机是什么？实时检测还是缓存状态？

### 决策（2026-03-20 澄清会话更新）

**实时检测（每次需要时检查 bridge.running 状态）**

### 理由

1. **准确性优先**：实时检测能准确反映当前连接状态，2. **简单可靠**：无需维护缓存状态和刷新逻辑
3. **延迟可接受**：检测操作本身是轻量级的，用户感知不到明显延迟

### 实现方案

```python
def is_disconnected(self) -> bool:
    """实时检测连接状态"""
    return not self._bridge.running
```

> **注意**：此决策替代了之前的"缓存状态"方案。

---

## 20. 无效日志级别处理研究

### 问题

当用户设置无效日志级别（如 `LARK_LOG_LEVEL=INVALID`）时，如何处理？

### 决策（2026-03-19 澄清会话）

**输出警告日志后回退到默认值 WARNING（30）**

### 理由

1. **用户友好**：明确告知用户配置问题
2. **系统稳定**：回退到合理默认值继续运行
3. **调试便利**：警告日志帮助用户发现配置错误

### 实现方案

```python
def parse_log_level(level_str: str) -> int:
    level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
    level = level_map.get(level_str.upper())
    if level is None:
        logger.warning(f"无效的日志级别 '{level_str}'，回退到默认值 WARNING")
        return 30
    return level
```

---

## 21. 快捷命令性能标准研究

### 问题

快捷命令选择器的渲染和响应时间是否有性能标准？

### 决策（2026-03-19 澄清会话）

**无显式要求（本地工具，用户感知足够快即可）**

### 理由

1. **本地工具**：网络延迟不是主要因素
2. **简单操作**：命令发送和卡片更新都很轻量
3. **用户感知**：实测响应时间通常在毫秒级

---

## 22. 快速连续命令处理研究

### 问题

用户快速连续发送多个快捷命令时，系统应如何处理？

### 决策（2026-03-19 澄清会话）

**串行处理 + 500ms 防抖（重复点击被忽略，只处理最后一次）**

### 理由

1. **串行处理**：保证命令执行顺序，避免竞态条件
2. **防抖机制**：防止用户误操作（如快速点击两次）
3. **500ms 阈值**：足够区分有意操作和误操作

### 实现方案

```python
import time
from threading import Lock

class CommandQueue:
    def __init__(self):
        self._queue = []
        self._lock = Lock()
        self._last_click_time = 0
        self._debounce_ms = 0.5

    def enqueue(self, command: str):
        now = time.time()
        # 防抖：500ms 内的重复点击忽略
        if now - self._last_click_time < self._debounce_ms:
            return
        self._last_click_time = now
        with self._lock:
            self._queue.append(command)

    def process_next(self) -> Optional[str]:
        with self._lock:
            if self._queue:
                return self._queue.pop(0)
        return None
```
