# 飞书会话卡片交互修复与初始化补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复飞书会话页交互（多行输入、合并操作入口、自动应答位置）并补齐首次 lazy 初始化默认配置复制能力。

**Architecture:** 在不改协议层的前提下，集中修改会话卡片构建和卡片动作分发：`card_builder` 负责 UI 结构与 value 编码，`main` 负责回调路由，`lark_handler` 复用现有开关逻辑并提供会话页入口。同时在 `runtime_config` 增加 `operation_panel` 配置模型与默认值，并在 `setup.sh --lazy` 成功路径调用 `init_config_files`，保持“仅缺失时复制”。

**Tech Stack:** Python 3、飞书卡片 Schema 2.0、POSIX shell、unittest/pytest 风格仓内测试

---

## 文件结构与职责映射

- `utils/runtime_config.py`
  - 新增 `OperationPanelSettings` 数据类。
  - 在 `UISettings` / `UserConfig` 中挂载并提供读取方法。
- `resources/defaults/config.default.json`
  - 增加 `ui_settings.operation_panel` 默认配置。
- `lark_client/card_builder.py`
  - 重构会话页操作区：多行输入 + 合并“操作”下拉 + 会话页自动应答按钮。
  - 移除 `/menu` 自动应答按钮。
- `lark_client/main.py`
  - 扩展 action/value 路由，支持 `key:*` / `cmd:*` / `stream_toggle_auto_answer`。
- `lark_client/lark_handler.py`
  - 增加会话页自动应答开关动作处理（复用 `_cmd_toggle_auto_answer`）。
- `scripts/setup.sh`
  - `--lazy` 成功路径调用 `init_config_files`。
- `tests/test_runtime_config.py`
  - 覆盖 `operation_panel` 默认值、序列化、缺省回退、非法键过滤。
- `tests/test_card_interaction.py`
  - 覆盖会话页卡片结构、合并下拉、自动应答按钮回调与 `/menu` 移除验证。
- `tests/test_entry_lazy_init.py`
  - 覆盖 lazy/setup 首次复制与“不覆盖已存在文件”。

---

### Task 1: 配置模型扩展（operation_panel）

**Files:**
- Modify: `utils/runtime_config.py`
- Modify: `resources/defaults/config.default.json`
- Test: `tests/test_runtime_config.py`

- [ ] **Step 1: 先写失败测试（runtime_config）**

```python
# tests/test_runtime_config.py

def test_operation_panel_defaults_and_roundtrip():
    from utils.runtime_config import UserConfig, save_user_config, load_user_config

    config = UserConfig()
    op = config.ui_settings.operation_panel
    assert op.show_builtin_keys is True
    assert op.show_custom_commands is True
    assert op.enabled_keys == ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]

    save_user_config(config)
    loaded = load_user_config()
    assert loaded.ui_settings.operation_panel.enabled_keys == op.enabled_keys


def test_operation_panel_invalid_keys_filtered():
    from utils.runtime_config import UISettings
    ui = UISettings.from_dict({
        "operation_panel": {
            "enabled_keys": ["up", "bad_key", "esc"],
            "show_builtin_keys": True,
            "show_custom_commands": True,
        }
    })
    assert ui.operation_panel.enabled_keys == ["up", "esc"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_runtime_config.py -k operation_panel -q`
Expected: FAIL，提示 `operation_panel` 属性不存在。

- [ ] **Step 3: 最小实现配置模型与默认值**

```python
# utils/runtime_config.py

@dataclass
class OperationPanelSettings:
    show_builtin_keys: bool = True
    show_custom_commands: bool = True
    enabled_keys: List[str] = field(default_factory=lambda: [
        "up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"
    ])

    _ALLOWED_KEYS = {"up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "show_builtin_keys": self.show_builtin_keys,
            "show_custom_commands": self.show_custom_commands,
            "enabled_keys": self.enabled_keys,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperationPanelSettings":
        keys = data.get("enabled_keys", ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"])
        filtered = [k for k in keys if k in cls._ALLOWED_KEYS]
        return cls(
            show_builtin_keys=data.get("show_builtin_keys", True),
            show_custom_commands=data.get("show_custom_commands", True),
            enabled_keys=filtered or ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"],
        )

# 挂到 UISettings
operation_panel: OperationPanelSettings = field(default_factory=lambda: OperationPanelSettings())

# UISettings.to_dict / from_dict 补 operation_panel
```

```json
// resources/defaults/config.default.json (ui_settings 下新增)
"operation_panel": {
  "show_builtin_keys": true,
  "show_custom_commands": true,
  "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_runtime_config.py -k operation_panel -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add utils/runtime_config.py resources/defaults/config.default.json tests/test_runtime_config.py
git commit -m "feat(config): add operation panel settings for session card actions"
```

---

### Task 2: 会话卡片重构（多行输入 + 合并操作下拉）

**Files:**
- Modify: `lark_client/card_builder.py`
- Test: `tests/test_card_interaction.py`

- [ ] **Step 1: 先写失败测试（卡片结构）**

```python
# tests/test_card_interaction.py

def test_stream_card_has_textarea_and_action_selector():
    from lark_client.card_builder import build_stream_card
    from utils.runtime_config import UserConfig

    config = UserConfig()
    card = build_stream_card(blocks=[], session_name="s1", user_config=config)
    elements = card["body"]["elements"]

    body_text = str(elements)
    assert "textarea" in body_text
    assert "操作" in body_text
    assert "key:up" in body_text


def test_menu_card_not_contains_auto_answer_button():
    from lark_client.card_builder import build_menu_card
    card = build_menu_card([], None, {}, 0, True, False, False, False, None)
    assert "menu_toggle_auto_answer" not in str(card)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_card_interaction.py -k "textarea or auto_answer" -q`
Expected: FAIL（当前仍是 `input` + `/menu` 含自动应答）。

- [ ] **Step 3: 最小实现卡片结构变更**

```python
# lark_client/card_builder.py

def _build_operation_selector(user_config, operation_panel_cfg):
    options = []
    if operation_panel_cfg.show_builtin_keys:
        key_map = [
            ("↑", "key:up"),
            ("↓", "key:down"),
            ("Ctrl+O", "key:ctrl_o"),
            ("Shift+Tab", "key:shift_tab"),
            ("ESC", "key:esc"),
            ("(↹)×3", "key:shift_tab_x3"),
        ]
        allowed = set(operation_panel_cfg.enabled_keys)
        for label, value in key_map:
            key_name = value.split(":", 1)[1]
            if key_name in allowed:
                options.append({"text": {"tag": "plain_text", "content": label}, "value": value})

    if operation_panel_cfg.show_custom_commands and user_config and user_config.ui_settings.custom_commands.is_visible():
        for cmd in user_config.ui_settings.custom_commands.commands:
            options.append({
                "text": {"tag": "plain_text", "content": f"{cmd.name}: {cmd.command}"},
                "value": f"cmd:{cmd.command}",
            })

    return {
        "tag": "action",
        "actions": [{
            "tag": "select_static",
            "placeholder": {"tag": "plain_text", "content": "操作"},
            "options": options[:20],
        }]
    }

# _build_menu_button_row 中：
# - input -> textarea
# - 删除快捷键 collapsible
# - 添加 operation selector 到同一操作区
# - 保留 Enter/发送按钮为 form_submit
```

```python
# build_menu_card 中删除 menu_toggle_auto_answer 按钮块
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_card_interaction.py -k "textarea or auto_answer" -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add lark_client/card_builder.py tests/test_card_interaction.py
git commit -m "feat(lark-card): unify action selector and move auto-answer off menu"
```

---

### Task 3: 卡片动作路由支持 key/cmd 前缀与会话页开关

**Files:**
- Modify: `lark_client/main.py`
- Test: `tests/test_card_interaction.py`

- [ ] **Step 1: 先写失败测试（路由）**

```python
# tests/test_card_interaction.py

def test_main_routes_prefixed_action_values():
    from lark_client import main
    from unittest.mock import patch, MagicMock

    event = MagicMock()
    event.event.action.value = "key:up"
    event.event.operator.open_id = "u1"
    event.event.context.open_chat_id = "c1"
    event.event.context.open_message_id = "m1"

    with patch("lark_client.main.handler.send_raw_key") as send_key:
        main.handle_card_action(event)
        send_key.assert_called()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_card_interaction.py -k prefixed_action -q`
Expected: FAIL（当前仅识别 `/xxx` 字符串命令）。

- [ ] **Step 3: 最小实现路由扩展**

```python
# lark_client/main.py

if isinstance(action_value, str):
    if action_value.startswith("key:"):
        key_name = action_value.split(":", 1)[1]
        if key_name == "shift_tab_x3":
            asyncio.create_task(_multi_send("shift_tab", 3))
        else:
            asyncio.create_task(handler.send_raw_key(user_id, chat_id, key_name))
        return None

    if action_value.startswith("cmd:"):
        command = action_value.split(":", 1)[1]
        asyncio.create_task(handler.handle_quick_command(user_id, chat_id, command))
        return None

# action_type 分支新增
if action_type == "stream_toggle_auto_answer":
    asyncio.create_task(handler._cmd_toggle_auto_answer(user_id, chat_id, message_id=message_id))
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_card_interaction.py -k prefixed_action -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add lark_client/main.py tests/test_card_interaction.py
git commit -m "feat(lark-action): route key/cmd prefixed selector values"
```

---

### Task 4: 会话页自动应答开关接入与卡片刷新

**Files:**
- Modify: `lark_client/lark_handler.py`
- Modify: `lark_client/card_builder.py`
- Test: `tests/test_card_interaction.py`

- [ ] **Step 1: 先写失败测试（会话页按钮存在且触发）**

```python
# tests/test_card_interaction.py

def test_stream_card_contains_stream_toggle_auto_answer_button():
    from lark_client.card_builder import build_stream_card
    card = build_stream_card(blocks=[], session_name="s1")
    assert "stream_toggle_auto_answer" in str(card)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_card_interaction.py -k stream_toggle_auto_answer -q`
Expected: FAIL。

- [ ] **Step 3: 最小实现按钮与刷新链路**

```python
# lark_client/card_builder.py
# 在会话页操作区追加按钮
{
  "tag": "button",
  "text": {"tag": "plain_text", "content": auto_answer_label},
  "type": auto_answer_type,
  "behaviors": [{"type": "callback", "value": {"action": "stream_toggle_auto_answer"}}],
}

# lark_client/lark_handler.py
# 复用 _cmd_toggle_auto_answer 逻辑，保持 toggle + tracker 同步
# message_id 存在时优先 update 当前卡片
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_card_interaction.py -k stream_toggle_auto_answer -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add lark_client/lark_handler.py lark_client/card_builder.py tests/test_card_interaction.py
git commit -m "feat(lark-session): add auto-answer toggle on stream card"
```

---

### Task 5: setup 与 lazy 路径统一执行 defaults 复制

**Files:**
- Modify: `scripts/setup.sh`
- Test: `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 先写失败测试（lazy 首次复制）**

```python
# tests/test_entry_lazy_init.py

def test_setup_lazy_initializes_config_and_runtime_when_missing(tmp_path: Path):
    # 准备最小 project/resources/defaults
    # 运行: sh scripts/setup.sh --lazy
    # 断言 ~/.remote-claude/config.json 与 runtime.json 已创建
    ...


def test_setup_lazy_does_not_overwrite_existing_config_files(tmp_path: Path):
    # 预写 config.json/runtime.json
    # 运行 lazy
    # 断言内容未被覆盖
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k "setup_lazy_initializes_config_and_runtime or does_not_overwrite_existing" -q`
Expected: FAIL（当前 lazy 不调用 `init_config_files`）。

- [ ] **Step 3: 最小实现 setup lazy 补调用**

```sh
# scripts/setup.sh (main 的 LAZY_MODE 分支)
_install_stage "setup-lazy-config"
init_config_files || { rc=$?; _log_script_fail "setup-lazy-config" "init_config_files" "$rc"; _install_fail_hint "$rc"; exit "$rc"; }

_install_stage "setup-lazy-done"
print_success "Python 环境初始化完成"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -k "setup_lazy_initializes_config_and_runtime or does_not_overwrite_existing" -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add scripts/setup.sh tests/test_entry_lazy_init.py
git commit -m "fix(setup): initialize default config files in lazy mode"
```

---

### Task 6: 全量回归（交互 + 配置 + 初始化）

**Files:**
- Test only: `tests/test_card_interaction.py`, `tests/test_runtime_config.py`, `tests/test_entry_lazy_init.py`

- [ ] **Step 1: 运行会话卡片相关测试**

Run: `uv run python3 -m pytest tests/test_card_interaction.py -q`
Expected: PASS。

- [ ] **Step 2: 运行配置测试**

Run: `uv run python3 -m pytest tests/test_runtime_config.py -q`
Expected: PASS。

- [ ] **Step 3: 运行 lazy/init 相关回归测试**

Run: `uv run python3 -m pytest tests/test_entry_lazy_init.py -q`
Expected: PASS。

- [ ] **Step 4: 运行精简冒烟（仅本次影响模块）**

Run: `uv run python3 -m pytest tests/test_card_interaction.py tests/test_runtime_config.py tests/test_entry_lazy_init.py -q`
Expected: PASS。

- [ ] **Step 5: Commit（若本任务仅测试无代码改动可跳过）**

```bash
git status
# 若有测试修订:
git add tests/test_card_interaction.py tests/test_runtime_config.py tests/test_entry_lazy_init.py
git commit -m "test: cover session card action panel and lazy config init"
```

---

## Spec 覆盖自检

- 多行输入 + 发送按钮：Task 2。
- 合并快捷键与自定义命令：Task 2 + Task 3。
- 自动应答迁移到会话页且从 `/menu` 移除：Task 2 + Task 4。
- `config.json` 新增 `operation_panel`：Task 1。
- `setup` 与 `setup --lazy` 都执行 defaults 复制且不覆盖：Task 5。
- 测试与回归检查：Task 1/2/3/4/5/6。

无缺口。

## Placeholder/一致性自检

- 无 TBD/TODO/“后续实现”。
- 所有新增动作名一致：`stream_toggle_auto_answer`。
- 所有 value 前缀一致：`key:` / `cmd:`。
- 控制键枚举一致：`up/down/ctrl_o/shift_tab/esc/shift_tab_x3`。

