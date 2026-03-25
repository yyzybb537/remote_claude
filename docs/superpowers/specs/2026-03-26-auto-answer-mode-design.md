# 自动应答模式设计文档

## 概述

为 Remote Claude 增加"自动应答模式"功能，当 Claude CLI 提出选项让用户选择时（`OptionBlock(sub_type="option")`），自动选择推荐方案，减少人工干预。

## 核心需求

| 项目 | 描述 |
|------|------|
| **触发场景** | 仅选项选择（`OptionBlock(sub_type="option")`），不包括权限确认 |
| **选择策略** | 见下方"选择策略详解" |
| **激活方式** | 飞书菜单卡片内开关切换（session 级别，同一 session 所有连接共享） |
| **通知方式** | 卡片内容区追加持久记录 |
| **延迟机制** | 默认 10 秒，通过 `user_config` 配置，界面不可动态调整 |

### 选择策略详解

自动应答根据选项内容采用不同策略：

**策略一：推荐选项优先**
- 选项中有标记为 "(recommended)" 或 "推荐" 的 → 选择该推荐选项
- 示例：`1. Refactor the entire module (recommended)` → 选择此项

**策略二：无明确语义时回复"继续"**
- 所有选项均无推荐标记，且选项内容为无明确语义的确认类文本 → 不选择选项，直接发送 "继续"
- 无明确语义的关键词：
  - 中文：`继续`、`好的`、`是`、`确认`、`明白`、`可以`
  - 英文：`continue`、`yes`、`ok`、`proceed`、`go ahead`、`sure`、`confirm`
- 示例：
  - 选项：`1. 继续  2. 停止` → 发送 "继续"
  - 选项：`1. Yes  2. No` → 发送 "继续"

**策略三：兜底选择第一项**
- 选项中有明确语义差异（如不同方案对比）→ 选择第一个选项
- 示例：`1. 使用方案A  2. 使用方案B` → 选择第一项

## 架构设计

### 数据模型

#### config.json 配置

```json
{
  "ui_settings": {
    "auto_answer": {
      "default_delay_seconds": 10
    }
  }
}
```

#### runtime.json 新增 session 级别状态

```json
{
  "session_auto_answer": {
    "my-session": {
      "enabled": true,
      "enabled_by": "ou_xxx"
    }
  }
}
```

### 流程图

#### 开关切换流程

```
飞书卡片点击 "自动应答" 开关
        │
        更新 runtime.json 的 session_auto_answer[session_name]
        │
        同步到 SharedMemoryPoller._session_auto_answer
        │
        所有连接该 session 的 chat_id 卡片刷新显示状态
```

#### 自动应答执行流程

```
SharedMemoryPoller._poll_once()
        │
        检测到 option_block(sub_type="option")
        │
        检查 _session_auto_answer[session_name]["enabled"]
        │
        ├─ 关闭 → 正常显示选项按钮
        │
        └─ 开启 → 启动延迟定时器
                        │
                        ├─ 延迟期间用户手动选择 → 取消定时器
                        │
                        └─ 延迟后 → 执行自动选择
                                    │
                                    Server 端写入 AutoAnswerBlock 到共享内存
                                    │
                                    所有连接该 session 的客户端卡片显示记录
```

## 详细设计

### 1. 选项解析器

根据选项内容采用不同策略：

```python
# 无明确语义关键词（用于识别确认类选项）
VAGUE_KEYWORDS = {
    # 中文
    '继续', '好的', '是', '确认', '明白', '可以', '行', '对',
    # 英文
    'continue', 'yes', 'ok', 'proceed', 'go ahead', 'sure', 'confirm', 'alright', 'fine'
}

def analyze_option_block(option_block: dict) -> tuple[str, str]:
    """分析选项块，返回应答类型和内容

    Returns:
        (action_type, action_value)
        action_type: "select" | "input"
        action_value: 选项 value 或输入文本
    """
    options = option_block.get('options', [])
    if not options:
        return ("input", "继续")

    # 策略一：查找推荐选项
    for opt in options:
        label = opt.get('label', '').lower()
        if '(recommended)' in label or '推荐' in label:
            return ("select", opt.get('value'))

    # 策略二：检查是否为无明确语义的确认类选项
    all_vague = True
    for opt in options:
        label = opt.get('label', '').lower().strip()
        # 检查是否包含无明确语义关键词
        if not any(kw in label for kw in VAGUE_KEYWORDS):
            all_vague = False
            break

    if all_vague:
        return ("input", "继续")

    # 策略三：兜底选择第一项
    return ("select", options[0].get('value'))
```

**使用方式**：
- 返回 `("select", value)` → 调用 `handle_option_select` 选择该选项
- 返回 `("input", "继续")` → 调用 `bridge.send_input("继续")` 发送文本

### 2. 自动应答调度器

在 `SharedMemoryPoller` 中管理 session 级别的自动应答状态：

```python
class SharedMemoryPoller:
    def __init__(self, card_service: Any):
        # ... 现有字段
        self._session_auto_answer: Dict[str, dict] = {}  # session_name -> {"enabled": bool, "task": Task}
```

延迟执行逻辑：

```python
def _schedule_auto_answer(self, session_name: str, option_block: dict):
    """安排自动应答任务"""
    state = self._session_auto_answer.get(session_name)
    if not state or not state.get("enabled"):
        return

    # 取消之前的待执行任务
    old_task = state.get("task")
    if old_task:
        old_task.cancel()

    # 创建新任务
    delay = get_auto_answer_delay()  # 从 user_config 读取
    task = asyncio.create_task(
        self._auto_answer_after_delay(session_name, option_block, delay)
    )
    state["task"] = task

async def _auto_answer_after_delay(self, session_name: str, option_block: dict, delay: float):
    """延迟后执行自动应答"""
    try:
        await asyncio.sleep(delay)
        await self._execute_auto_answer(session_name, option_block)
    except asyncio.CancelledError:
        logger.debug(f"自动应答已取消: session={session_name}")
```

### 3. 用户手动干预

用户手动选择时取消自动应答：

```python
async def handle_option_select(self, user_id: str, chat_id: str, option_value: str, ...):
    session_name = self._chat_sessions.get(chat_id)
    if session_name:
        # 取消该 session 的待执行自动应答
        state = self._poller._session_auto_answer.get(session_name)
        if state and state.get("task"):
            state["task"].cancel()
            state["task"] = None

    # 正常处理用户选择...
```

### 4. 持久记录：AutoAnswerBlock

新增 `AutoAnswerBlock` 类型，写入共享内存：

```python
{
    "_type": "AutoAnswerBlock",
    "block_id": "AA:{timestamp}",
    "content": "自动应答：{action_desc}",
    "action_type": "select",  # "select" | "input"
    "selected_value": "1",    # action_type="select" 时有值
    "selected_label": "Refactor the entire module",
    "input_text": "继续",      # action_type="input" 时有值
    "timestamp": 1234567890.0
}
```

渲染效果：
```
⏱ 自动应答：选择了推荐方案「Refactor the entire module」
⏱ 自动应答：发送「继续」
```

### 5. 状态持久化

**runtime.json 管理**：
- 新增 `load_session_auto_answer()` / `save_session_auto_answer()` 函数
- `SharedMemoryPoller` 初始化时加载
- 开关切换时保存

**config.json 管理**：
- 新增 `get_auto_answer_delay()` 函数读取延迟配置
- 用户需手动编辑配置文件修改延迟时间

### 6. UI 变更

**菜单卡片新增开关**：

```
┌──────────────────────────────────────────┐
│ ⚙️ 设置 (会话: my-project)               │
├──────────────────────────────────────────┤
│ 🔔 就绪通知      [开启]                   │
│ 🚀 加急通知      [关闭]                   │
│ ⚡ 跳过权限      [关闭]                   │
│ 🤖 自动应答      [关闭] (10秒延迟)        │  ← 新增
└──────────────────────────────────────────┘
```

**卡片交互**：
- 点击"自动应答"按钮 → 切换开关状态
- 刷新菜单卡片显示最新状态
- 同一 session 的所有客户端同步显示

## 文件修改清单

| 文件 | 修改内容 |
|------|---------|
| `utils/runtime_config.py` | 新增 `get_auto_answer_delay()`、`load_session_auto_answer()`、`save_session_auto_answer()` 函数 |
| `lark_client/shared_memory_poller.py` | 新增 `_session_auto_answer` 字段、自动应答调度逻辑 |
| `lark_client/lark_handler.py` | 新增 `_cmd_toggle_auto_answer()`、`handle_option_select` 取消逻辑 |
| `lark_client/card_builder.py` | 新增 `AutoAnswerBlock` 渲染、菜单卡片新增开关 |
| `lark_client/main.py` | 新增 `toggle_auto_answer` action 处理 |
| `server/shared_state.py` | 支持 `AutoAnswerBlock` 类型 |
| `server/parsers/base_parser.py` | 新增 `AutoAnswerBlock` 数据类 |
| `CLAUDE.md` | 更新文档 |

## 测试场景

1. **基本功能**：开启自动应答 → 等待选项出现 → 10 秒后自动选择推荐项
2. **用户干预**：开启自动应答 → 延迟期间手动选择 → 自动应答取消
3. **多客户端同步**：客户端 A 开启 → 客户端 B 看到开关已开启
4. **持久化**：开启自动应答 → 重启飞书客户端 → 状态保持
5. **权限确认不触发**：出现权限确认（`sub_type="permission"`）→ 不触发自动应答
6. **无推荐选项**：选项无 "recommended" 标记 → 选择第一个选项
7. **无明确语义选项**：选项为「继续/停止」「Yes/No」等 → 发送"继续"而非选择选项
8. **混合语义选项**：选项为「使用方案A/使用方案B」→ 选择第一项
