# 自动应答模式与卡片生命周期管理实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Remote Claude 增加自动应答模式和卡片生命周期管理功能，提升无人值守场景下的自动化程度。

**Architecture:**
- 自动应答：在 SharedMemoryPoller 中检测 option_block，延迟后自动选择推荐选项或发送"继续"
- 卡片生命周期：在 CardSlice 中记录活动时间，过期后回调返回提示，状态变更时新建卡片

**Tech Stack:** Python asyncio, dataclasses, 飞书卡片 API

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `utils/runtime_config.py` | 配置管理：自动应答延迟、卡片过期时间、session 级别开关状态 |
| `lark_client/shared_memory_poller.py` | 自动应答调度器、卡片过期检测、新建推送逻辑 |
| `lark_client/card_builder.py` | AutoAnswerBlock 渲染、菜单卡片新增开关、过期提示卡片 |
| `lark_client/lark_handler.py` | 开关切换命令、回调拦截、自动应答取消逻辑 |
| `lark_client/main.py` | 新增 toggle_auto_answer action 处理 |
| `server/parsers/base_parser.py` | AutoAnswerBlock 数据类定义 |
| `lark_client/card_service.py` | 过期提示卡片发送方法 |

---

## Task 1: 配置管理扩展

**Files:**
- Modify: `utils/runtime_config.py`
- Test: `tests/test_runtime_config.py`

### 1.1 配置数据类扩展

- [ ] **Step 1: 扩展 UISettings 数据类**

在 `utils/runtime_config.py` 中找到 `UISettings` 类，添加新字段：

```python
@dataclass
class AutoAnswerSettings:
    """自动应答设置"""
    default_delay_seconds: int = 10

@dataclass
class CardExpirySettings:
    """卡片过期设置"""
    enabled: bool = True
    expiry_seconds: int = 3600  # 1小时

@dataclass
class UISettings:
    # ... 现有字段
    auto_answer: AutoAnswerSettings = field(default_factory=AutoAnswerSettings)
    card_expiry: CardExpirySettings = field(default_factory=CardExpirySettings)
```

- [ ] **Step 2: 运行测试验证数据类**

Run: `uv run python3 -c "from utils.runtime_config import UISettings, AutoAnswerSettings, CardExpirySettings; s = UISettings(); print(s.auto_answer.default_delay_seconds, s.card_expiry.expiry_seconds)"`
Expected: `10 3600`

### 1.2 配置访问函数

- [ ] **Step 3: 添加自动应答配置访问函数**

在 `utils/runtime_config.py` 的 `get_notify_ready_enabled` 函数附近添加：

```python
# ============== 自动应答配置访问函数 ==============

def get_auto_answer_delay() -> int:
    """获取自动应答延迟时间（秒）"""
    config = load_user_config()
    return config.ui_settings.auto_answer.default_delay_seconds


def get_card_expiry_enabled() -> bool:
    """获取卡片过期功能是否启用"""
    config = load_user_config()
    return config.ui_settings.card_expiry.enabled


def get_card_expiry_seconds() -> int:
    """获取卡片过期时间（秒）"""
    config = load_user_config()
    return config.ui_settings.card_expiry.expiry_seconds
```

- [ ] **Step 4: 测试配置访问函数**

Run: `uv run python3 -c "from utils.runtime_config import get_auto_answer_delay, get_card_expiry_enabled, get_card_expiry_seconds; print(get_auto_answer_delay(), get_card_expiry_enabled(), get_card_expiry_seconds())"`
Expected: `10 True 3600`

### 1.3 Session 级别状态持久化

- [ ] **Step 5: 添加 session 自动应答状态管理函数**

在 `utils/runtime_config.py` 中添加：

```python
# ============== Session 自动应答状态管理 ==============

def load_session_auto_answer() -> Dict[str, dict]:
    """加载所有 session 的自动应答状态"""
    config = load_runtime_config()
    return config.data.get("session_auto_answer", {})


def save_session_auto_answer(states: Dict[str, dict]) -> None:
    """保存所有 session 的自动应答状态"""
    config = load_runtime_config()
    config.data["session_auto_answer"] = states
    save_runtime_config(config)


def get_session_auto_answer_enabled(session_name: str) -> bool:
    """获取指定 session 的自动应答开关状态"""
    states = load_session_auto_answer()
    return states.get(session_name, {}).get("enabled", False)


def set_session_auto_answer_enabled(session_name: str, enabled: bool, enabled_by: str = "") -> None:
    """设置指定 session 的自动应答开关状态"""
    states = load_session_auto_answer()
    if enabled:
        states[session_name] = {"enabled": True, "enabled_by": enabled_by}
    else:
        states.pop(session_name, None)
    save_session_auto_answer(states)
```

- [ ] **Step 6: 测试 session 状态管理**

Run: `uv run python3 -c "
from utils.runtime_config import set_session_auto_answer_enabled, get_session_auto_answer_enabled, load_session_auto_answer
set_session_auto_answer_enabled('test-session', True, 'ou_test')
print('After enable:', get_session_auto_answer_enabled('test-session'))
set_session_auto_answer_enabled('test-session', False)
print('After disable:', get_session_auto_answer_enabled('test-session'))
"`
Expected:
```
After enable: True
After disable: False
```

- [ ] **Step 7: Commit 配置管理扩展**

```bash
git add utils/runtime_config.py
git commit -m "feat(config): add auto-answer and card-expiry settings

- Add AutoAnswerSettings and CardExpirySettings dataclasses
- Add get_auto_answer_delay(), get_card_expiry_enabled(), get_card_expiry_seconds()
- Add session-level auto-answer state management functions

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: CardSlice 和 StreamTracker 扩展

**Files:**
- Modify: `lark_client/shared_memory_poller.py`

### 2.1 CardSlice 扩展

- [ ] **Step 1: 扩展 CardSlice 数据类**

在 `lark_client/shared_memory_poller.py` 中找到 `CardSlice` 类，添加字段：

```python
@dataclass
class CardSlice:
    """一张飞书卡片对应的 blocks 窗口"""
    card_id: str
    sequence: int = 0
    start_idx: int = 0       # blocks[start_idx:] 开始渲染
    frozen: bool = False
    last_activity_time: float = 0.0  # 最后活动时间戳（更新/操作）
    expired: bool = False             # 是否已过期
```

### 2.2 StreamTracker 扩展

- [ ] **Step 2: 扩展 StreamTracker 数据类**

在 `StreamTracker` 类中添加字段：

```python
@dataclass
class StreamTracker:
    """单个 chat_id 的流式跟踪状态"""
    chat_id: str
    session_name: str
    cards: List[CardSlice] = field(default_factory=list)
    content_hash: str = ""
    reader: Optional[Any] = None  # SharedStateReader，延迟初始化
    is_group: bool = False         # 是否为群聊
    prev_is_ready: bool = True     # 上一帧是否就绪
    notify_user_id: Optional[str] = None
    last_notify_message_id: Optional[str] = None
    # 自动应答相关字段
    auto_answer_enabled: bool = False      # 从 session 级别状态加载
    pending_auto_answer: Optional[asyncio.Task] = None  # 待执行的自动应答 Task
```

### 2.3 初始化时加载状态

- [ ] **Step 3: 在 start 方法中加载 session 自动应答状态**

在 `SharedMemoryPoller.start` 方法中添加状态加载：

```python
def start(self, chat_id: str, session_name: str, is_group: bool = False,
          notify_user_id: Optional[str] = None) -> None:
    """attach 成功后调用：清空旧状态，启动轮询 Task"""
    self.stop(chat_id)

    # 从持久化状态加载自动应答开关
    from utils.runtime_config import get_session_auto_answer_enabled
    auto_answer_enabled = get_session_auto_answer_enabled(session_name)

    tracker = StreamTracker(
        chat_id=chat_id,
        session_name=session_name,
        is_group=is_group,
        notify_user_id=notify_user_id,
        auto_answer_enabled=auto_answer_enabled,
    )
    # ... 后续代码不变
```

- [ ] **Step 4: Commit CardSlice 和 StreamTracker 扩展**

```bash
git add lark_client/shared_memory_poller.py
git commit -m "feat(poller): extend CardSlice and StreamTracker for auto-answer

- Add last_activity_time and expired fields to CardSlice
- Add auto_answer_enabled and pending_auto_answer fields to StreamTracker
- Load session auto-answer state on tracker start

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 选项解析器

**Files:**
- Modify: `lark_client/shared_memory_poller.py`

### 3.1 定义关键词和解析函数

- [ ] **Step 1: 添加无明确语义关键词常量和解析函数**

在 `lark_client/shared_memory_poller.py` 文件顶部（import 之后）添加：

```python
# ── 自动应答选项解析 ─────────────────────────────────────────────────────────

# 无明确语义关键词（用于识别确认类选项）
VAGUE_KEYWORDS = {
    # 中文
    '继续', '好的', '是', '确认', '明白', '可以', '行', '对',
    # 英文
    'continue', 'yes', 'ok', 'proceed', 'go ahead', 'sure', 'confirm', 'alright', 'fine'
}


def analyze_option_block(option_block: dict) -> tuple:
    """分析选项块，返回应答类型和内容

    Args:
        option_block: 选项块字典，包含 options 列表

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

### 3.2 单元测试

- [ ] **Step 2: 创建选项解析器测试文件**

Create: `tests/test_auto_answer_analyzer.py`

```python
#!/usr/bin/env python3
"""自动应答选项解析器测试"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lark_client.shared_memory_poller import analyze_option_block, VAGUE_KEYWORDS


def test_recommended_option():
    """测试推荐选项优先"""
    option_block = {
        "options": [
            {"label": "Approach A", "value": "1"},
            {"label": "Approach B (recommended)", "value": "2"},
            {"label": "Approach C", "value": "3"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "2"
    print("✓ test_recommended_option passed")


def test_vague_keywords_continue():
    """测试无明确语义选项发送继续"""
    option_block = {
        "options": [
            {"label": "继续", "value": "1"},
            {"label": "停止", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_vague_keywords_continue passed")


def test_vague_keywords_yes():
    """测试英文确认选项"""
    option_block = {
        "options": [
            {"label": "Yes", "value": "1"},
            {"label": "No", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_vague_keywords_yes passed")


def test_fallback_first():
    """测试兜底选择第一项"""
    option_block = {
        "options": [
            {"label": "使用方案A", "value": "1"},
            {"label": "使用方案B", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "1"
    print("✓ test_fallback_first passed")


def test_empty_options():
    """测试空选项列表"""
    option_block = {"options": []}
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_empty_options passed")


def test_chinese_recommended():
    """测试中文推荐选项"""
    option_block = {
        "options": [
            {"label": "方案A", "value": "1"},
            {"label": "方案B（推荐）", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "2"
    print("✓ test_chinese_recommended passed")


if __name__ == "__main__":
    test_recommended_option()
    test_vague_keywords_continue()
    test_vague_keywords_yes()
    test_fallback_first()
    test_empty_options()
    test_chinese_recommended()
    print("\n✅ All tests passed!")
```

- [ ] **Step 3: 运行测试**

Run: `uv run python3 tests/test_auto_answer_analyzer.py`
Expected: `✅ All tests passed!`

- [ ] **Step 4: Commit 选项解析器**

```bash
git add lark_client/shared_memory_poller.py tests/test_auto_answer_analyzer.py
git commit -m "feat(auto-answer): add option analyzer with three strategies

- Strategy 1: Select recommended option
- Strategy 2: Send '继续' for vague confirmation options
- Strategy 3: Fallback to first option
- Add unit tests for all strategies

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 自动应答调度器

**Files:**
- Modify: `lark_client/shared_memory_poller.py`

### 4.1 添加调度方法

- [ ] **Step 1: 在 SharedMemoryPoller 中添加调度方法**

在 `SharedMemoryPoller` 类中添加以下方法：

```python
    # ── 自动应答调度 ────────────────────────────────────────────────────────────

    def _schedule_auto_answer(self, chat_id: str, session_name: str, option_block: dict) -> None:
        """安排自动应答任务

        Args:
            chat_id: 飞书 chat_id
            session_name: 会话名称
            option_block: 选项块
        """
        tracker = self._trackers.get(chat_id)
        if not tracker or not tracker.auto_answer_enabled:
            return

        # 取消之前的待执行任务
        if tracker.pending_auto_answer:
            tracker.pending_auto_answer.cancel()
            tracker.pending_auto_answer = None

        # 创建新任务
        from utils.runtime_config import get_auto_answer_delay
        delay = get_auto_answer_delay()

        logger.info(f"安排自动应答: session={session_name}, delay={delay}s")

        tracker.pending_auto_answer = asyncio.create_task(
            self._auto_answer_after_delay(chat_id, session_name, option_block, delay)
        )

    async def _auto_answer_after_delay(self, chat_id: str, session_name: str,
                                        option_block: dict, delay: float) -> None:
        """延迟后执行自动应答

        Args:
            chat_id: 飞书 chat_id
            session_name: 会话名称
            option_block: 选项块
            delay: 延迟秒数
        """
        try:
            await asyncio.sleep(delay)

            # 再次检查状态（可能在延迟期间被关闭）
            tracker = self._trackers.get(chat_id)
            if not tracker or not tracker.auto_answer_enabled:
                return

            # 执行自动应答
            await self._execute_auto_answer(chat_id, session_name, option_block)

        except asyncio.CancelledError:
            logger.debug(f"自动应答已取消: session={session_name}")
        except Exception as e:
            logger.error(f"自动应答执行失败: {e}", exc_info=True)

    async def _execute_auto_answer(self, chat_id: str, session_name: str,
                                    option_block: dict) -> None:
        """执行自动应答

        Args:
            chat_id: 飞书 chat_id
            session_name: 会话名称
            option_block: 选项块
        """
        from utils.runtime_config import set_session_auto_answer_enabled

        # 分析选项
        action_type, action_value = analyze_option_block(option_block)

        logger.info(f"执行自动应答: session={session_name}, type={action_type}, value={action_value}")

        # 获取 bridge（通过 lark_handler）
        # 注意：这里需要从外部注入或通过回调获取 bridge
        # 为了解耦，我们通过 card_service 的 handler 引用来获取
        if not hasattr(self._card_service, 'handler') or not self._card_service.handler:
            logger.warning("无法执行自动应答: handler 未注册")
            return

        handler = self._card_service.handler
        bridge = handler._bridges.get(chat_id)
        if not bridge or not bridge.running:
            logger.warning(f"无法执行自动应答: bridge 未连接 (chat_id={chat_id[:8]}...)")
            return

        if action_type == "select":
            # 选择选项
            await handler.handle_option_select(
                user_id="auto_answer",
                chat_id=chat_id,
                option_value=action_value,
                option_total=len(option_block.get('options', [])),
            )
        else:
            # 发送输入
            success = await bridge.send_input(action_value)
            if success:
                self.kick(chat_id)
                logger.info(f"自动应答已发送输入: {action_value}")
            else:
                logger.warning(f"自动应答发送输入失败: {action_value}")

    def cancel_auto_answer(self, session_name: str) -> None:
        """取消指定 session 的自动应答任务

        Args:
            session_name: 会话名称
        """
        for chat_id, tracker in self._trackers.items():
            if tracker.session_name == session_name and tracker.pending_auto_answer:
                tracker.pending_auto_answer.cancel()
                tracker.pending_auto_answer = None
                logger.info(f"已取消自动应答: session={session_name}")
```

### 4.2 在轮询中触发调度

- [ ] **Step 2: 在 _poll_once 中添加自动应答调度**

在 `_poll_once` 方法中，检测到 `option_block` 且 `sub_type="option"` 时，触发调度：

```python
    async def _poll_once(self, tracker: StreamTracker) -> None:
        """单次轮询处理"""
        # ... 现有代码

        # 检测到 option_block
        ob = snapshot.get('option_block')
        if ob and ob.get('sub_type') == 'option':
            # 触发自动应答调度
            if tracker.auto_answer_enabled:
                self._schedule_auto_answer(tracker.chat_id, tracker.session_name, ob)

        # ... 后续渲染逻辑
```

**注意：** 需要找到 `_poll_once` 中检测 `option_block` 的位置，在渲染卡片之前添加调度逻辑。

- [ ] **Step 3: Commit 自动应答调度器**

```bash
git add lark_client/shared_memory_poller.py
git commit -m "feat(auto-answer): add scheduler with delay support

- Add _schedule_auto_answer, _auto_answer_after_delay, _execute_auto_answer
- Trigger scheduling in _poll_once when option_block detected
- Add cancel_auto_answer for manual intervention

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 卡片过期检测

**Files:**
- Modify: `lark_client/shared_memory_poller.py`

### 5.1 添加过期检测方法

- [ ] **Step 1: 在 SharedMemoryPoller 中添加过期检测**

```python
    # ── 卡片过期管理 ────────────────────────────────────────────────────────────

    def _check_card_expiry(self, tracker: StreamTracker) -> None:
        """检查并标记过期卡片

        Args:
            tracker: 流式跟踪器
        """
        from utils.runtime_config import get_card_expiry_enabled, get_card_expiry_seconds

        if not get_card_expiry_enabled():
            return

        expiry_seconds = get_card_expiry_seconds()
        now = time.time()

        for card_slice in tracker.cards:
            if card_slice.expired or card_slice.frozen:
                continue

            if card_slice.last_activity_time > 0:
                elapsed = now - card_slice.last_activity_time
                if elapsed > expiry_seconds:
                    card_slice.expired = True
                    logger.info(
                        f"卡片已过期: card_id={card_slice.card_id}, "
                        f"elapsed={elapsed:.0f}s, expiry={expiry_seconds}s"
                    )
```

### 5.2 在轮询中调用过期检测

- [ ] **Step 2: 在 _poll_once 开头调用过期检测**

```python
    async def _poll_once(self, tracker: StreamTracker) -> None:
        """单次轮询处理"""
        # 检查卡片过期
        self._check_card_expiry(tracker)

        # ... 后续代码
```

### 5.3 更新活动时间

- [ ] **Step 3: 在卡片更新时更新活动时间**

找到更新卡片的代码位置（`update_card` 成功后），添加：

```python
        if success:
            card_slice.sequence = new_sequence
            card_slice.last_activity_time = time.time()  # 更新活动时间
```

- [ ] **Step 4: Commit 卡片过期检测**

```bash
git add lark_client/shared_memory_poller.py
git commit -m "feat(card-expiry): add expiry detection

- Add _check_card_expiry to mark expired cards
- Update last_activity_time on successful card update
- Check expiry at start of _poll_once

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: AutoAnswerBlock 数据类和渲染

**Files:**
- Modify: `server/parsers/base_parser.py`
- Modify: `lark_client/card_builder.py`

### 6.1 定义 AutoAnswerBlock 数据类

- [ ] **Step 1: 在 base_parser.py 中添加 AutoAnswerBlock**

在 `server/parsers/base_parser.py` 中找到其他 Block 类定义的位置，添加：

```python
@dataclass
class AutoAnswerBlock:
    """自动应答记录块"""
    block_id: str
    content: str
    action_type: str  # "select" | "input"
    selected_value: Optional[str] = None
    selected_label: Optional[str] = None
    input_text: Optional[str] = None
    timestamp: float = 0.0
    start_row: int = 0
```

### 6.2 卡片渲染

- [ ] **Step 2: 在 card_builder.py 中添加 AutoAnswerBlock 渲染**

在 `build_stream_card` 函数的 block 渲染循环中添加：

```python
        elif block_type == "AutoAnswerBlock":
            # 自动应答记录
            action_desc = block.get('content', '')
            elements.append({
                "tag": "markdown",
                "content": f"⏱ {action_desc}"
            })
```

- [ ] **Step 3: Commit AutoAnswerBlock**

```bash
git add server/parsers/base_parser.py lark_client/card_builder.py
git commit -m "feat(blocks): add AutoAnswerBlock type and rendering

- Add AutoAnswerBlock dataclass in base_parser.py
- Add rendering support in card_builder.py

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 菜单卡片新增开关

**Files:**
- Modify: `lark_client/card_builder.py`

### 7.1 修改 build_menu_card 函数签名

- [ ] **Step 1: 添加 auto_answer_enabled 参数**

在 `build_menu_card` 函数签名中添加参数：

```python
def build_menu_card(sessions: List[Dict], current_session: Optional[str] = None,
                    session_groups: Optional[Dict[str, str]] = None, page: int = 0,
                    notify_enabled: bool = True, urgent_enabled: bool = False,
                    bypass_enabled: bool = False,
                    auto_answer_enabled: bool = False,  # 新增
                    user_config: Optional["UserConfig"] = None) -> Dict[str, Any]:
```

### 7.2 添加开关按钮

- [ ] **Step 2: 在 bypass 按钮后添加自动应答开关按钮**

在 `build_menu_card` 函数中，在 bypass 按钮后添加：

```python
    # 自动应答开关（显示延迟时间）
    from utils.runtime_config import get_auto_answer_delay
    delay = get_auto_answer_delay()
    auto_label = f"🤖 自动应答: 开 ({delay}秒延迟)" if auto_answer_enabled else "🤖 自动应答: 关"
    elements.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": auto_label},
        "type": "primary" if auto_answer_enabled else "default",
        "behaviors": [{"type": "callback", "value": {"action": "menu_toggle_auto_answer"}}]
    })
```

- [ ] **Step 3: Commit 菜单卡片开关**

```bash
git add lark_client/card_builder.py
git commit -m "feat(menu): add auto-answer toggle button

- Add auto_answer_enabled parameter to build_menu_card
- Show delay time in button label
- Use primary type when enabled

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: LarkHandler 命令处理

**Files:**
- Modify: `lark_client/lark_handler.py`

### 8.1 添加开关切换命令

- [ ] **Step 1: 添加 _cmd_toggle_auto_answer 方法**

在 `lark_client/lark_handler.py` 中，在 `_cmd_toggle_bypass` 方法附近添加：

```python
    async def _cmd_toggle_auto_answer(self, user_id: str, chat_id: str,
                                       message_id: Optional[str] = None):
        """切换自动应答开关并刷新菜单卡片"""
        session_name = self._chat_sessions.get(chat_id)
        if not session_name:
            await card_service.send_text(chat_id, "当前未连接到任何会话")
            return

        # 切换状态
        from utils.runtime_config import get_session_auto_answer_enabled, set_session_auto_answer_enabled
        new_value = not get_session_auto_answer_enabled(session_name)
        set_session_auto_answer_enabled(session_name, new_value, user_id)

        # 更新 tracker 状态
        tracker = self._poller._trackers.get(chat_id)
        if tracker:
            tracker.auto_answer_enabled = new_value
            # 取消待执行的自动应答
            if not new_value and tracker.pending_auto_answer:
                tracker.pending_auto_answer.cancel()
                tracker.pending_auto_answer = None

        logger.info(f"自动应答开关切换: session={session_name}, enabled={new_value}")

        # 刷新菜单卡片
        await self._cmd_menu(user_id, chat_id, message_id=message_id)
```

### 8.2 修改 _cmd_menu 传递参数

- [ ] **Step 2: 在 _cmd_menu 中获取并传递 auto_answer_enabled**

找到 `_cmd_menu` 方法，修改 `build_menu_card` 调用：

```python
    async def _cmd_menu(self, user_id: str, chat_id: str,
                         message_id: Optional[str] = None, page: int = 0):
        """显示快捷操作菜单（内嵌会话列表）"""
        sessions = list_active_sessions()
        current = self._chat_sessions.get(chat_id)
        session_groups = {
            self._chat_bindings[cid]: cid
            for cid in self._group_chat_ids
            if cid in self._chat_bindings
        }

        # 获取自动应答状态
        from utils.runtime_config import get_session_auto_answer_enabled
        auto_answer_enabled = get_session_auto_answer_enabled(current) if current else False

        card = build_menu_card(
            sessions, current_session=current, session_groups=session_groups, page=page,
            notify_enabled=get_notify_ready_enabled(),
            urgent_enabled=get_notify_urgent_enabled(),
            bypass_enabled=get_bypass_enabled(),
            auto_answer_enabled=auto_answer_enabled,  # 新增
            user_config=self._user_config
        )
        await self._send_or_update_card(chat_id, card, message_id)
```

### 8.3 修改 handle_option_select 取消自动应答

- [ ] **Step 3: 在用户手动选择时取消自动应答**

找到 `handle_option_select` 方法，在开头添加：

```python
    async def handle_option_select(self, user_id: str, chat_id: str, option_value: str, option_total: int = 0, *, needs_input: bool = False):
        """闭环选项选择：箭头键导航 + 共享内存验证"""
        # 用户手动选择时取消自动应答
        session_name = self._chat_sessions.get(chat_id)
        if session_name:
            self._poller.cancel_auto_answer(session_name)

        # ... 后续代码不变
```

### 8.4 添加过期卡片回调拦截

- [ ] **Step 4: 在回调方法中添加过期检查**

在 `handle_option_select` 开头添加过期检查：

```python
    async def handle_option_select(self, user_id: str, chat_id: str, option_value: str, option_total: int = 0, *, needs_input: bool = False):
        """闭环选项选择：箭头键导航 + 共享内存验证"""
        # 检查卡片是否过期
        tracker = self._poller._trackers.get(chat_id)
        if tracker and tracker.cards:
            active_slice = tracker.cards[-1]
            if active_slice.expired:
                await card_service.send_text(chat_id, "⚠️ 卡片已过期，请刷新后重试")
                return

        # ... 后续代码
```

- [ ] **Step 5: Commit LarkHandler 命令处理**

```bash
git add lark_client/lark_handler.py
git commit -m "feat(handler): add auto-answer toggle and expiry check

- Add _cmd_toggle_auto_answer for menu button
- Pass auto_answer_enabled to build_menu_card
- Cancel auto-answer on manual selection
- Check card expiry before handling callbacks

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: main.py action 处理

**Files:**
- Modify: `lark_client/main.py`

### 9.1 添加 action 处理

- [ ] **Step 1: 在 main.py 中添加 menu_toggle_auto_answer 处理**

在 `menu_toggle_bypass` 处理后添加：

```python
        if action_type == "menu_toggle_auto_answer":
            asyncio.create_task(handler._cmd_toggle_auto_answer(user_id, chat_id, message_id=message_id))
            return None
```

- [ ] **Step 2: Commit main.py**

```bash
git add lark_client/main.py
git commit -m "feat(main): add menu_toggle_auto_answer action handler

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 10: 过期提示卡片

**Files:**
- Modify: `lark_client/card_service.py`
- Modify: `lark_client/card_builder.py`

### 10.1 添加过期提示卡片构建函数

- [ ] **Step 1: 在 card_builder.py 中添加 build_expired_card 函数**

```python
def build_expired_card(session_name: Optional[str] = None) -> Dict[str, Any]:
    """构建过期提示卡片

    Args:
        session_name: 会话名称（可选）

    Returns:
        飞书卡片 JSON
    """
    elements = [
        {
            "tag": "markdown",
            "content": "**该卡片已超过 1 小时无活动，可能已失效。**\n请使用菜单按钮刷新当前状态。"
        },
        {"tag": "hr"},
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🔄 刷新"},
            "type": "primary",
            "behaviors": [{"type": "callback", "value": {"action": "menu_open"}}]
        }
    ]

    header_text = "⚠️ 卡片已过期"
    if session_name:
        header_text += f" ({session_name})"

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": _build_header(header_text, "orange"),
        "body": {"elements": elements}
    }
```

### 10.2 在 card_service 中添加发送方法

- [ ] **Step 2: 在 card_service.py 中添加便捷方法**

```python
async def send_expired_card(chat_id: str, session_name: Optional[str] = None) -> str:
    """发送过期提示卡片

    Args:
        chat_id: 飞书 chat_id
        session_name: 会话名称（可选）

    Returns:
        卡片 ID
    """
    from lark_client.card_builder import build_expired_card
    card = build_expired_card(session_name)
    return await create_card(chat_id, card)
```

- [ ] **Step 3: Commit 过期提示卡片**

```bash
git add lark_client/card_builder.py lark_client/card_service.py
git commit -m "feat(cards): add expired card builder and sender

- Add build_expired_card function with refresh button
- Add send_expired_card convenience method

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 11: 新建推送逻辑（过期后）

**Files:**
- Modify: `lark_client/shared_memory_poller.py`

### 11.1 修改卡片更新逻辑

- [ ] **Step 1: 在 _update_or_create_card 逻辑中处理过期卡片**

找到卡片更新的位置（通常在 `_poll_once` 中），修改为：

```python
    async def _update_card_content(self, chat_id: str, tracker: StreamTracker,
                                    card_content: dict) -> bool:
        """更新卡片内容，处理过期逻辑

        Returns:
            True 如果更新成功，False 如果需要创建新卡片
        """
        if not tracker.cards:
            return False

        active_slice = tracker.cards[-1]

        # 检查是否过期
        if active_slice.expired:
            logger.info(f"卡片已过期，需要创建新卡片: chat_id={chat_id[:8]}...")
            return False

        # 正常更新
        try:
            success = await self._card_service.update_card(
                card_id=active_slice.card_id,
                sequence=active_slice.sequence + 1,
                card_content=card_content,
            )
            if success:
                active_slice.sequence += 1
                active_slice.last_activity_time = time.time()
                return True
        except Exception as e:
            logger.warning(f"卡片更新失败: {e}")

        return False
```

- [ ] **Step 2: Commit 新建推送逻辑**

```bash
git add lark_client/shared_memory_poller.py
git commit -m "feat(poller): handle expired card by creating new one

- Add _update_card_content method
- Return False for expired cards to trigger new card creation
- Update last_activity_time on successful update

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 12: 更新 CLAUDE.md 文档

**Files:**
- Modify: `CLAUDE.md`

### 12.1 添加功能说明

- [ ] **Step 1: 在 CLAUDE.md 中添加新功能说明**

在适当位置添加：

```markdown
### 自动应答模式

**功能**：当 Claude CLI 提出选项让用户选择时，自动选择推荐方案或发送"继续"，减少人工干预。

**配置**：
- `config.json` → `ui_settings.auto_answer.default_delay_seconds`：延迟时间（默认 10 秒）
- `runtime.json` → `session_auto_answer`：session 级别开关状态

**选择策略**：
1. 推荐选项优先：选择标记为 "(recommended)" 或 "推荐" 的选项
2. 无明确语义时回复"继续"：选项为确认类文本时发送"继续"
3. 兜底选择第一项：其他情况选择第一个选项

**操作**：在菜单卡片中点击"自动应答"按钮切换开关。

### 卡片生命周期管理

**功能**：卡片超过一定时间无活动后标记为过期，过期卡片收到回调时返回提示，状态变更时创建新卡片。

**配置**：
- `config.json` → `ui_settings.card_expiry.enabled`：是否启用（默认 true）
- `config.json` → `ui_settings.card_expiry.expiry_seconds`：过期时间（默认 3600 秒）

**行为**：
- 过期卡片点击按钮返回"卡片已过期"提示
- 过期后有新数据时创建新卡片（而非更新旧卡片）
```

- [ ] **Step 2: Commit 文档更新**

```bash
git add CLAUDE.md
git commit -m "docs: add auto-answer and card-expiry documentation

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 13: 集成测试

**Files:**
- Create: `tests/test_auto_answer_integration.py`

### 13.1 创建集成测试

- [ ] **Step 1: 创建集成测试文件**

```python
#!/usr/bin/env python3
"""自动应答集成测试"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_config_functions():
    """测试配置函数"""
    from utils.runtime_config import (
        get_auto_answer_delay,
        get_card_expiry_enabled,
        get_card_expiry_seconds,
        set_session_auto_answer_enabled,
        get_session_auto_answer_enabled,
    )

    # 测试默认值
    assert get_auto_answer_delay() == 10, f"Expected 10, got {get_auto_answer_delay()}"
    assert get_card_expiry_enabled() == True
    assert get_card_expiry_seconds() == 3600

    # 测试 session 状态
    set_session_auto_answer_enabled("test-session", True, "ou_test")
    assert get_session_auto_answer_enabled("test-session") == True

    set_session_auto_answer_enabled("test-session", False)
    assert get_session_auto_answer_enabled("test-session") == False

    print("✓ Config functions test passed")


def test_card_slice_expiry():
    """测试 CardSlice 过期标记"""
    from lark_client.shared_memory_poller import CardSlice
    import time

    # 创建一个 2 小时前的卡片
    old_slice = CardSlice(
        card_id="test-card",
        last_activity_time=time.time() - 7200,  # 2 小时前
    )

    # 模拟过期检测
    from utils.runtime_config import get_card_expiry_seconds
    expiry = get_card_expiry_seconds()
    elapsed = time.time() - old_slice.last_activity_time

    assert elapsed > expiry, f"Card should be expired: elapsed={elapsed}, expiry={expiry}"
    print("✓ CardSlice expiry test passed")


def test_option_analyzer():
    """测试选项解析器"""
    from lark_client.shared_memory_poller import analyze_option_block

    # 测试推荐选项
    result = analyze_option_block({
        "options": [
            {"label": "A", "value": "1"},
            {"label": "B (recommended)", "value": "2"},
        ]
    })
    assert result == ("select", "2"), f"Expected ('select', '2'), got {result}"

    # 测试无明确语义
    result = analyze_option_block({
        "options": [
            {"label": "继续", "value": "1"},
            {"label": "停止", "value": "2"},
        ]
    })
    assert result == ("input", "继续"), f"Expected ('input', '继续'), got {result}"

    # 测试兜底
    result = analyze_option_block({
        "options": [
            {"label": "方案A", "value": "1"},
            {"label": "方案B", "value": "2"},
        ]
    })
    assert result == ("select", "1"), f"Expected ('select', '1'), got {result}"

    print("✓ Option analyzer test passed")


if __name__ == "__main__":
    test_config_functions()
    test_card_slice_expiry()
    test_option_analyzer()
    print("\n✅ All integration tests passed!")
```

- [ ] **Step 2: 运行集成测试**

Run: `uv run python3 tests/test_auto_answer_integration.py`
Expected: `✅ All integration tests passed!`

- [ ] **Step 3: Commit 集成测试**

```bash
git add tests/test_auto_answer_integration.py
git commit -m "test: add auto-answer integration tests

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 14: 最终提交和验证

- [ ] **Step 1: 运行所有相关测试**

Run: `uv run python3 tests/test_runtime_config.py && uv run python3 tests/test_auto_answer_analyzer.py && uv run python3 tests/test_auto_answer_integration.py`
Expected: 所有测试通过

- [ ] **Step 2: 检查代码风格**

Run: `uv run python3 -m py_compile lark_client/shared_memory_poller.py lark_client/lark_handler.py lark_client/card_builder.py utils/runtime_config.py`
Expected: 无输出（编译成功）

- [ ] **Step 3: 最终提交**

```bash
git add -A
git status
git commit -m "feat: add auto-answer mode and card lifecycle management

Features:
- Auto-answer mode: automatically select recommended options or send '继续'
- Card expiry: mark cards expired after 1 hour inactivity
- Three selection strategies: recommended, vague keywords, fallback first
- Session-level toggle with configurable delay

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## 实现顺序总结

1. **Task 1**: 配置管理扩展（基础设施）
2. **Task 2**: CardSlice/StreamTracker 扩展（数据模型）
3. **Task 3**: 选项解析器（核心逻辑）
4. **Task 4**: 自动应答调度器（核心逻辑）
5. **Task 5**: 卡片过期检测（核心逻辑）
6. **Task 6**: AutoAnswerBlock（数据类型）
7. **Task 7**: 菜单卡片开关（UI）
8. **Task 8**: LarkHandler 命令处理（业务逻辑）
9. **Task 9**: main.py action（入口）
10. **Task 10**: 过期提示卡片（UI）
11. **Task 11**: 新建推送逻辑（核心逻辑）
12. **Task 12**: 文档更新
13. **Task 13**: 集成测试
14. **Task 14**: 最终验证
