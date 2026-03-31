"""
飞书卡片构建器（Schema 2.0 格式）

主要入口：
- build_stream_card(blocks, ...)：从共享内存 blocks 流构建飞书卡片（供 SharedMemoryPoller 调用）

辅助卡片：
- build_menu_card（内嵌会话列表 + 快捷操作，/menu 和 /list 共用）
- build_status_card / build_help_card / build_dir_card / build_session_closed_card
"""

import logging
import re as _re
import pathlib as _pl
import json as _json
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.runtime_config import UserConfig

from server.biz_enum import CliType

_cb_logger = logging.getLogger('CardBuilder')

# CLI 类型 → 显示名称映射（用于卡片标题中的"就绪"文案）
CLI_NAMES: Dict[CliType, str] = {
    CliType.CLAUDE: "Claude",
    CliType.CODEX: "Codex",
}

# 版本号：从 package.json 读取，import 时只读一次
try:
    _pkg = _pl.Path(__file__).parent.parent / "package.json"
    _VERSION = "v" + _json.loads(_pkg.read_text())["version"]
except Exception:
    _VERSION = ""


def _get_matching_commands(user_config: Optional["UserConfig"]) -> List[Dict[str, str]]:
    """获取自定义命令列表

    Args:
        user_config: 用户配置对象

    Returns:
        命令列表，每个元素包含 name 和 command。
        如果未配置自定义命令，返回默认命令列表。
    """
    if not user_config or not user_config.session.custom_commands.is_visible():
        # 未配置自定义命令，返回默认命令列表（Claude 和 Codex）
        return [
            {"name": "Claude", "command": str(CliType.CLAUDE)},
            {"name": "Codex", "command": str(CliType.CODEX)},
        ]

    commands = user_config.session.custom_commands.commands
    matched = [
        {"name": cmd.name, "command": cmd.command}
        for cmd in commands
    ]

    return matched


def _build_header(title: str, template: str) -> dict:
    """构建卡片 header，自动附加版本号副标题"""
    h: dict = {"title": {"tag": "plain_text", "content": title}, "template": template}
    if _VERSION:
        h["subtitle"] = {"tag": "plain_text", "content": _VERSION}
    return h

# ANSI SGR 前景色码 → 飞书颜色
# 飞书支持: blue, wathet, turquoise, green, yellow, orange, red, carmine, violet, purple, indigo, grey
_SGR_FG_TO_LARK = {
    30: 'grey',      # black
    31: 'red',       # red
    32: 'green',     # green
    33: 'yellow',    # yellow
    34: 'blue',      # blue
    35: 'purple',    # magenta → purple
    36: 'turquoise', # cyan → turquoise
    90: 'grey',      # bright black
    91: 'red',       # bright red
    92: 'green',     # bright green
    93: 'yellow',    # bright yellow
    94: 'wathet',    # bright blue → wathet (浅蓝)
    95: 'violet',    # bright magenta → violet
    96: 'turquoise', # bright cyan → turquoise
    37: 'grey',      # white → grey（飞书无白色）
    97: 'grey',      # bright white → grey
}
_ANSI_RE = _re.compile(r'\x1b\[([\d;]*)m')

# 飞书 12 色的近似 RGB 值
_LARK_COLORS_RGB = {
    'blue': (51, 112, 255),
    'wathet': (120, 163, 245),
    'turquoise': (45, 183, 181),
    'green': (52, 181, 74),
    'yellow': (250, 200, 0),
    'orange': (255, 125, 0),
    'red': (245, 74, 69),
    'carmine': (204, 41, 71),
    'violet': (155, 89, 182),
    'purple': (124, 58, 237),
    'indigo': (79, 70, 229),
    'grey': (143, 149, 158),
}


def _rgb_to_lark(r, g, b) -> str:
    """RGB → 最近的飞书颜色（欧几里得距离）"""
    best, best_d = 'grey', float('inf')
    for name, (cr, cg, cb) in _LARK_COLORS_RGB.items():
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_d:
            best, best_d = name, d
    return best


def _256_to_lark(n: int) -> str:
    """256 色索引 → 飞书颜色"""
    if n < 8:
        return _SGR_FG_TO_LARK.get(n + 30, 'grey')
    if n < 16:
        return _SGR_FG_TO_LARK.get(n - 8 + 90, 'grey')
    if n < 232:  # 6x6x6 色立方
        n -= 16
        r = (n // 36) * 51
        g = ((n % 36) // 6) * 51
        b = (n % 6) * 51
        return _rgb_to_lark(r, g, b)
    # 232-255: 灰阶
    return 'grey'


def _escape_md(text: str) -> str:
    """转义飞书 markdown 特殊字符，并保留行首缩进

    飞书 markdown 会压缩普通空格，将行首空格替换为不间断空格 (\\u00a0) 保留缩进。
    """
    if not text:
        return ""
    text = text.replace('\\', '\\\\')
    for ch in ('*', '_', '~', '`'):
        text = text.replace(ch, '\\' + ch)
    # 行首空格 → 不间断空格，防止飞书 markdown 压缩缩进
    lines = text.split('\n')
    for i, line in enumerate(lines):
        stripped = line.lstrip(' ')
        indent = len(line) - len(stripped)
        if indent > 0:
            lines[i] = '\u00a0' * indent + stripped
    return '\n'.join(lines)


def _ansi_to_lark_md(ansi_text: str) -> str:
    """将 ANSI 转义序列转为飞书 <font color> markdown"""
    if not ansi_text:
        return ""
    result = []
    current_color = None
    pos = 0
    for match in _ANSI_RE.finditer(ansi_text):
        # 匹配前的文本
        text = ansi_text[pos:match.start()]
        if text:
            escaped = _escape_md(text)
            if current_color:
                result.append(f'<font color="{current_color}">{escaped}</font>')
            else:
                result.append(escaped)
        # 解析 SGR 码（顺序消费，支持真彩色和 256 色）
        codes = [int(c) for c in match.group(1).split(';') if c] if match.group(1) else [0]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                current_color = None
                i += 1
            elif c == 38 and i + 1 < len(codes):
                if codes[i + 1] == 2 and i + 4 < len(codes):      # 38;2;R;G;B 真彩色
                    current_color = _rgb_to_lark(codes[i + 2], codes[i + 3], codes[i + 4])
                    i += 5
                elif codes[i + 1] == 5 and i + 2 < len(codes):    # 38;5;N 256 色
                    current_color = _256_to_lark(codes[i + 2])
                    i += 3
                else:
                    i += 1
            elif c == 48 and i + 1 < len(codes):                   # 背景色，跳过
                if codes[i + 1] == 2:
                    i += 5
                elif codes[i + 1] == 5:
                    i += 3
                else:
                    i += 1
            elif c in _SGR_FG_TO_LARK:
                current_color = _SGR_FG_TO_LARK[c]
                i += 1
            else:
                i += 1
        pos = match.end()
    # 尾部文本
    tail = ansi_text[pos:]
    if tail:
        escaped = _escape_md(tail)
        if current_color:
            result.append(f'<font color="{current_color}">{escaped}</font>')
        else:
            result.append(escaped)
    merged = ''.join(result)
    # 逐行后处理：行首缩进保留 + 分割线替换
    lines = merged.split('\n')
    for i, line in enumerate(lines):
        # 去除 <font> 标签后检测是否为纯分割线字符行（终端分割线在卡片中无意义，直接移除）
        plain = _re.sub(r'</?font[^>]*>', '', line).strip(' \u00a0')
        if len(plain) >= 4 and all(c in '╌─━═' for c in plain):
            lines[i] = ''
            continue
        # 行首空格 → 不间断空格，防止飞书 markdown 压缩缩进
        stripped = line.lstrip(' ')
        indent = len(line) - len(stripped)
        if indent > 0:
            lines[i] = '\u00a0' * indent + stripped
    return '\n'.join(lines)


def _safe_truncate(text: str, limit: int) -> str:
    """安全截断：不在代码块中间截断，超出时附加提示"""
    if len(text) <= limit:
        return text

    truncated = text[:limit]
    fence_count = truncated.count('```')
    if fence_count % 2 == 1:
        last_fence = truncated.rfind('```')
        truncated = truncated[:last_fence].rstrip()
    else:
        last_newline = truncated.rfind('\n')
        if last_newline > limit * 0.8:
            truncated = truncated[:last_newline]

    return truncated.rstrip() + '\n\n*...（内容过长，仅显示部分）*'


def _build_quick_command_selector(quick_commands: List[Any]) -> Dict[str, Any]:
    """构建快捷命令选择器

    Args:
        quick_commands: QuickCommand 对象列表

    Returns:
        飞书卡片 action 元素，包含 select_static
    """
    # 飞书 select_static 最多支持 20 个选项，超出时截断并输出警告
    MAX_OPTIONS = 20
    if len(quick_commands) > MAX_OPTIONS:
        _cb_logger.warning(
            f"快捷命令数量 {len(quick_commands)} 超过上限 {MAX_OPTIONS}，"
            f"仅显示前 {MAX_OPTIONS} 条"
        )
    commands_to_use = quick_commands[:MAX_OPTIONS]

    options = []
    for cmd in commands_to_use:
        # 构建选项文本：icon + label
        icon = cmd.icon if cmd.icon else ""
        text = f"{icon} {cmd.label}".strip() if icon else cmd.label
        options.append({
            "text": {"tag": "plain_text", "content": text},
            "value": cmd.value,
        })

    return {
        "tag": "action",
        "actions": [{
            "tag": "select_static",
            "placeholder": {"tag": "plain_text", "content": "快捷命令"},
            "options": options,
        }]
    }


def _build_operation_selector(user_config: Optional["UserConfig"]) -> Optional[Dict[str, Any]]:
    """构建会话页操作下拉（快捷键 + 自定义命令）"""
    options: List[Dict[str, Any]] = []

    show_builtin_keys = True
    show_custom_commands = True

    enabled_keys = set()
    if user_config:
        panel_cfg = user_config.behavior.operation_panel
        show_builtin_keys = panel_cfg.show_builtin_keys
        show_custom_commands = panel_cfg.show_custom_commands
        enabled_keys = set(panel_cfg.enabled_keys)

    if show_builtin_keys:
        key_map = [
            ("↑", "up"),
            ("↓", "down"),
            ("Ctrl+O", "ctrl_o"),
            ("Shift+Tab", "shift_tab"),
            ("ESC", "esc"),
            ("(↹)×3", "shift_tab_x3"),
        ]
        for label, key_name in key_map:
            if key_name in enabled_keys:
                options.append({
                    "text": {"tag": "plain_text", "content": label},
                    "value": f"key:{key_name}",
                })

    if (
        show_custom_commands
        and user_config
        and user_config.session.custom_commands.is_visible()
    ):
        for cmd in user_config.session.custom_commands.commands:
            options.append({
                "text": {"tag": "plain_text", "content": f"{cmd.name}: {cmd.command}"},
                "value": f"cmd:{cmd.command}",
            })

    if not options:
        return None

    if len(options) > 20:
        _cb_logger.warning(f"操作下拉选项数量 {len(options)} 超过 20，已截断")
        options = options[:20]

    return {
        "tag": "action",
        "actions": [{
            "tag": "select_static",
            "placeholder": {"tag": "plain_text", "content": "操作"},
            "options": options,
        }]
    }


def _build_menu_button_row(session_name: Optional[str] = None, disconnected: bool = False, is_loading: bool = False, disabled_buttons: Optional[List[str]] = None, user_config: Optional["UserConfig"] = None) -> List[Dict[str, Any]]:
    """底部快捷菜单按钮行，用于流式卡片"""
    disabled_set = set(disabled_buttons or [])

    if is_loading:
        disabled_set.add("all")

    if disconnected:
        cols = [
            {
                "tag": "column",
                "width": "auto",
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "⚡ 菜单"},
                    "type": "default",
                    **({"disabled": True} if "all" in disabled_set or "menu_open" in disabled_set else {"behaviors": [{"type": "callback", "value": {"action": "menu_open"}}]})
                }]
            },
            {
                "tag": "column",
                "width": "auto",
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🔗 重新连接"},
                    "type": "primary",
                    **({"disabled": True} if "all" in disabled_set or "stream_reconnect" in disabled_set else {"behaviors": [{"type": "callback", "value": {
                        "action": "stream_reconnect", "session": session_name or ""
                    }}]})
                }]
            },
        ]
        return [{"tag": "column_set", "flex_mode": "none", "columns": cols}]

    def _make_menu_button(text: str, btn_type: str, action: str, extra_value: Optional[dict] = None) -> dict:
        btn: Dict[str, Any] = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": text},
            "type": btn_type,
        }
        if "all" in disabled_set or action in disabled_set:
            btn["disabled"] = True
        else:
            value = {"action": action}
            if extra_value:
                value.update(extra_value)
            btn["behaviors"] = [{"type": "callback", "value": value}]
        return btn

    if session_name:
        menu_columns = [
            {
                "tag": "column",
                "width": "auto",
                "elements": [_make_menu_button("⚡ 菜单", "default", "menu_open")]
            },
            {
                "tag": "column",
                "width": "auto",
                "elements": [_make_menu_button("🔌 断开", "danger", "stream_detach", {"session": session_name})]
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{"tag": "markdown", "content": " "}]
            },
            {
                "tag": "column",
                "width": "auto",
                "elements": [{
                    "tag": "button",
                    "name": "enter_submit",
                    "text": {"tag": "plain_text", "content": "发送"},
                    "type": "primary",
                    "action_type": "form_submit",
                    **({"disabled": True} if "all" in disabled_set else {})
                }]
            },
        ]
    else:
        menu_columns = [
            {
                "tag": "column",
                "width": "auto",
                "elements": [_make_menu_button("⚡ 菜单", "default", "menu_open")]
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{"tag": "markdown", "content": " "}]
            },
            {
                "tag": "column",
                "width": "auto",
                "elements": [{
                    "tag": "button",
                    "name": "enter_submit",
                    "text": {"tag": "plain_text", "content": "发送"},
                    "type": "primary",
                    "action_type": "form_submit",
                    **({"disabled": True} if "all" in disabled_set else {})
                }]
            },
        ]

    menu_enter_row = {"tag": "column_set", "flex_mode": "none", "columns": menu_columns}

    input_box: Dict[str, Any] = {
        "tag": "textarea",
        "name": "command",
        "placeholder": {"tag": "plain_text", "content": "输入消息..."},
    }
    if "all" in disabled_set:
        input_box["disabled"] = True

    form_elements: List[Dict[str, Any]] = [menu_enter_row, input_box]

    action_items: List[Dict[str, Any]] = []
    operation_selector = _build_operation_selector(user_config)
    if operation_selector:
        selector_action = dict(operation_selector["actions"][0])
        if "all" in disabled_set:
            selector_action["disabled"] = True
        action_items.append(selector_action)

    if session_name:
        from utils.runtime_config import get_auto_answer_delay, get_session_auto_answer_enabled

        auto_answer_enabled = get_session_auto_answer_enabled(session_name)
        delay_seconds = get_auto_answer_delay()
        auto_answer_label = (
            f"🤖 自动应答: 开 ({delay_seconds}秒)"
            if auto_answer_enabled
            else f"🤖 自动应答: 关 ({delay_seconds}秒)"
        )
        auto_answer_btn: Dict[str, Any] = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": auto_answer_label},
            "type": "primary" if auto_answer_enabled else "default",
            "behaviors": [{"type": "callback", "value": {"action": "stream_toggle_auto_answer"}}],
        }
        if "all" in disabled_set:
            auto_answer_btn.pop("behaviors", None)
            auto_answer_btn["disabled"] = True
        action_items.append(auto_answer_btn)

    if action_items:
        form_elements.append({"tag": "action", "actions": action_items})

    return [{
        "tag": "form",
        "name": "claude_input",
        "elements": form_elements,
    }]


def _build_menu_button_only() -> Dict[str, Any]:
    """底部菜单按钮行（仅 ⚡菜单 按钮），用于辅助卡片"""
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "columns": [{
            "tag": "column",
            "width": "auto",
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "⚡ 菜单"},
                "type": "default",
                "behaviors": [{"type": "callback", "value": {"action": "menu_open"}}]
            }]
        }],
    }


def _build_buttons_v2(options: List[Dict[str, str]], is_loading: bool = False) -> List[Dict[str, Any]]:
    """Schema 2.0 按钮组：每个按钮独占一行，顶部加一条 hr

    Args:
        options: 选项列表，每个选项包含 label 和 value
        is_loading: 是否处于 loading 状态（禁用所有按钮）
    """
    total = len(options)
    elements = [{"tag": "hr"}]
    for i, opt in enumerate(options):
        btn_type = "primary" if i == 0 else "default"
        btn: Dict[str, Any] = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"{i+1}. {opt['label']}"},
            "type": btn_type,
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "select_option",
                        "value": opt["value"],
                        "needs_input": opt.get("needs_input", False),
                        "total": str(total),
                    }
                }
            ]
        }
        if is_loading:
            btn["disabled"] = True
        elements.append({
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "horizontal_align": "left",
                    "elements": [btn]
                }
            ]
        })
    return elements


# === 流式卡片构建（主入口）===

def _render_agent_panel(agent_panel: dict) -> List[Dict[str, Any]]:
    """将 AgentPanelBlock 渲染为飞书 elements 列表

    - summary → 纯文本（灰色背景已提供视觉区分）
    - list → 代码块（agent 列表）
    - detail → 代码块（agent 详情）
    """
    panel_type = agent_panel.get("panel_type", "")

    if panel_type == "summary":
        count = agent_panel.get("agent_count", 0)
        return [{"tag": "markdown", "content": f"🤖 {count} 个后台 agent"}]

    elif panel_type == "list":
        count = agent_panel.get("agent_count", 0)
        agents = agent_panel.get("agents", [])
        lines = [f"🤖 后台任务 ({count})"]
        for a in agents:
            prefix = "❯" if a.get("is_selected") else " "
            lines.append(f"{prefix} {a.get('name', '')} ({a.get('status', '')})")
        return [{"tag": "markdown", "content": "```\n" + "\n".join(lines) + "\n```"}]

    elif panel_type == "detail":
        name = agent_panel.get("agent_name", "")
        atype = agent_panel.get("agent_type", "")
        stats = agent_panel.get("stats", "")
        progress = agent_panel.get("progress", "")
        prompt = agent_panel.get("prompt", "")
        lines = [f"🤖 {atype} › {name}"]
        if stats:
            lines.append(stats)
        if progress:
            lines.append(f"Progress: {progress}")
        if prompt:
            lines.append(f"Prompt: {prompt}")
        return [{"tag": "markdown", "content": "```\n" + "\n".join(lines) + "\n```"}]

    return []


def _render_block_colored(block_dict: dict) -> Optional[str]:
    """将单个 block dict 渲染为飞书 markdown（ANSI 着色）

    优先使用 ansi_* 字段解析为 <font color> 着色，
    无 ANSI 字段时回退到纯文本 + _escape_md。
    """
    typ = block_dict.get("_type", "")

    if typ == "OutputBlock":
        content = block_dict.get("content", "")
        if not content:
            return None
        ansi_content = block_dict.get("ansi_content", "")
        ansi_ind = block_dict.get("ansi_indicator", "")
        indicator = block_dict.get("indicator", "●")
        streaming = block_dict.get("is_streaming", False)
        prefix = "⏳ " if streaming else ""
        ind_md = _ansi_to_lark_md(ansi_ind) if ansi_ind else _escape_md(indicator)
        content_md = _ansi_to_lark_md(ansi_content) if ansi_content else _escape_md(content)
        return f"{prefix}{ind_md} {content_md}"

    elif typ == "UserInput":
        text = block_dict.get("text", "")
        if not text:
            return None
        ansi_text = block_dict.get("ansi_text", "")
        ansi_ind = block_dict.get("ansi_indicator", "")
        ind_md = _ansi_to_lark_md(ansi_ind) if ansi_ind else "❯"
        text_md = _ansi_to_lark_md(ansi_text) if ansi_text else _escape_md(text)
        return f"{ind_md} {text_md}"

    elif typ == "OptionBlock":
        sub = block_dict.get("sub_type", "option")
        if sub == "permission":
            # 权限确认模式（向后兼容旧数据中 PermissionBlock 在 blocks 里的情况）
            title = block_dict.get("title", "")
            content = block_dict.get("content", "")
            parts = []
            if title:
                parts.append(f"🔐 {_escape_md(title)}")
            if content:
                parts.append(_escape_md(content))
            if not parts:
                parts.append("🔐 权限确认")
            return "\n".join(parts)
        else:
            question = block_dict.get("question", "")
            tag = block_dict.get("tag", "")
            display = question or tag or "请选择"
            return f"🤔 {_escape_md(display)}"

    elif typ == "PermissionBlock":
        # 向后兼容旧数据
        title = block_dict.get("title", "")
        content = block_dict.get("content", "")
        parts = []
        if title:
            parts.append(f"🔐 {_escape_md(title)}")
        if content:
            parts.append(_escape_md(content))
        if not parts:
            parts.append("🔐 权限确认")
        return "\n".join(parts)

    elif typ == "SystemBlock":
        content = block_dict.get("content", "")
        if not content:
            return None
        ansi_content = block_dict.get("ansi_content", "")
        ansi_ind = block_dict.get("ansi_indicator", "")
        indicator = block_dict.get("indicator", "✻")
        ind_md = _ansi_to_lark_md(ansi_ind) if ansi_ind else _escape_md(indicator)
        content_md = _ansi_to_lark_md(ansi_content) if ansi_content else _escape_md(content)
        return f"{ind_md} {content_md}"

    elif typ == "AutoAnswerBlock":
        # 自动应答记录
        content = block_dict.get("content", "")
        if not content:
            return None
        return f"⏱ {_escape_md(content)}"

    return None


def _render_plan_block(block_dict: dict) -> Optional[Dict[str, Any]]:
    """将 PlanBlock 渲染为飞书 collapsible_panel element"""
    content = block_dict.get("content", "")
    if not content:
        return None
    title = block_dict.get("title", "计划")
    ansi_content = block_dict.get("ansi_content", "")
    content_md = _ansi_to_lark_md(ansi_content) if ansi_content else _escape_md(content)
    return {
        "tag": "collapsible_panel",
        "expanded": True,
        "header": {"title": {"tag": "plain_text", "content": f"📋 {title}"}},
        "elements": [{"tag": "markdown", "content": content_md}],
    }


def _determine_header(
    blocks: List[dict],
    status_line: Optional[dict],
    bottom_bar: Optional[dict],
    is_frozen: bool,
    option_block: Optional[dict] = None,
    disconnected: bool = False,
    cli_type: str = "claude",
    is_loading: bool = False,
    loading_text: str = "处理中...",
) -> tuple:
    """确定卡片标题和颜色模板，返回 (title, template)"""
    if disconnected:
        return "⚪ 已断开", "grey"

    if is_frozen:
        return "📋 会话记录", "grey"

    # loading 状态优先显示
    if is_loading:
        return f"⏳ {loading_text}", "orange"

    # 优化：只检查最后一个 block 是否 streaming
    # 原因：Claude CLI 的输出模型是追加式的，streaming 状态只出现在最新 block
    # 如果中间 block 仍在 streaming（理论上不应该发生），它会在下一帧变成最后一个
    has_streaming = blocks[-1].get("is_streaming", False) if blocks else False

    if has_streaming or status_line:
        if status_line:
            action = status_line.get('action', '处理中...')
            elapsed = status_line.get('elapsed', '')
            tokens = status_line.get('tokens', '')
            stats_parts = [p for p in [elapsed, tokens] if p]
            stats_str = f" ({' · '.join(stats_parts)})" if stats_parts else ""
            return f"⏳ {action}{stats_str}", "orange"
        return "⏳ 处理中...", "orange"

    # 优先从 option_block 状态型组件判定
    if option_block:
        if option_block.get("sub_type") == "permission":
            return "🔐 等待权限确认", "red"
        return "🤔 等待选择", "blue"

    # 向后兼容：检查 blocks 中的旧 OptionBlock/PermissionBlock
    last_type = blocks[-1].get("_type", "") if blocks else ""
    if last_type == "PermissionBlock":
        return "🔐 等待权限确认", "red"
    if last_type == "OptionBlock":
        sub = blocks[-1].get("sub_type", "option")
        if sub == "permission":
            return "🔐 等待权限确认", "red"
        return "🤔 等待选择", "blue"

    # 尝试将 cli_type 转换为枚举，失败时使用默认值
    try:
        cli_type_enum = CliType(cli_type)
    except ValueError:
        cli_type_enum = CliType.CLAUDE
    cli_name = CLI_NAMES.get(cli_type_enum, "Unknown")
    return f"✅ {cli_name} 就绪", "green"


def _extract_buttons(blocks: List[dict], option_block: Optional[dict] = None) -> List[Dict[str, str]]:
    """从 option_block 状态型组件提取按钮选项，降级搜索 blocks 中的旧 OptionBlock/PermissionBlock"""
    # 优先从 option_block 参数提取
    if option_block:
        return option_block.get("options", [])
    # 向后兼容：搜索 blocks
    for block in reversed(blocks):
        typ = block.get("_type", "")
        if typ in ("OptionBlock", "PermissionBlock"):
            return block.get("options", [])
    return []


def build_stream_card(
    blocks: List[dict],
    status_line: Optional[dict] = None,
    bottom_bar: Optional[dict] = None,
    is_frozen: bool = False,
    agent_panel: Optional[dict] = None,
    option_block: Optional[dict] = None,
    session_name: Optional[str] = None,
    disconnected: bool = False,
    cli_type: str = "claude",
    user_config: Optional["UserConfig"] = None,
    is_loading: bool = False,
    disabled_buttons: Optional[List[str]] = None,
    loading_text: str = "处理中...",
) -> Dict[str, Any]:
    """从共享内存 blocks 流构建飞书卡片

    四层结构：
    1. 内容区：累积型 blocks
    2. 状态区：status_line + bottom_bar + agent_panel + option_block 问题文本（断开时隐藏）
    3. 交互区：option_block 的选项按钮（断开时隐藏）
    4. 菜单按钮（断开时变为 [⚡菜单] [🔗重新连接]）

    Args:
        blocks: 累积型 block 列表
        status_line: 状态行组件
        bottom_bar: 底部栏组件
        is_frozen: 是否冻结（历史记录卡片）
        agent_panel: agent 面板组件
        option_block: 选项交互组件
        session_name: 会话名
        disconnected: 是否断开连接
        cli_type: CLI 类型（claude/codex）
        user_config: 用户配置对象（用于快捷命令选择器）
        is_loading: 是否处于 loading 状态（按钮禁用、显示处理中）
        disabled_buttons: 需要禁用的按钮动作列表（如 ["menu_open", "stream_detach"]）
        loading_text: loading 状态时的提示文本

    Example:
        构建 loading 状态卡片（用于交互时显示处理中）::

            # 从 snapshot 构建 loading 卡片
            loading_card = build_stream_card(
                blocks=snapshot.get("blocks", []),
                status_line=snapshot.get("status_line"),
                bottom_bar=snapshot.get("bottom_bar"),
                agent_panel=snapshot.get("agent_panel"),
                option_block=snapshot.get("option_block"),
                session_name=session_name,
                cli_type=snapshot.get("cli_type", "claude"),
                user_config=user_config,
                is_loading=True,
                loading_text="正在处理...",
            )

            # 空白 loading 卡片（无 snapshot）
            loading_card = build_stream_card(
                blocks=[],
                session_name=session_name,
                is_loading=True,
                loading_text="正在连接...",
                disconnected=True,
            )
    """
    title, template = _determine_header(
        blocks, status_line, bottom_bar, is_frozen,
        option_block=option_block, disconnected=disconnected,
        cli_type=cli_type,
        is_loading=is_loading, loading_text=loading_text,
    )

    # === 第一层：内容区 ===
    elements = []
    has_content = False

    for block_dict in blocks:
        typ = block_dict.get("_type", "")
        if typ == "PlanBlock":
            plan_el = _render_plan_block(block_dict)
            if plan_el:
                has_content = True
                elements.append(plan_el)
            continue
        rendered = _render_block_colored(block_dict)
        if rendered:
            has_content = True
            elements.append({"tag": "markdown", "content": rendered})


    # === 第二层：状态区（仅非冻结且非断开时，column_set 灰色背景）===
    if not is_frozen and not disconnected and (status_line or bottom_bar or agent_panel or option_block):
        status_elements = []
        if status_line:
            ansi_raw = status_line.get('ansi_raw', '')
            if ansi_raw:
                status_elements.append({"tag": "markdown", "content": _ansi_to_lark_md(ansi_raw)})
            else:
                action = status_line.get('action', '')
                elapsed = status_line.get('elapsed', '')
                tokens = status_line.get('tokens', '')
                stats_parts = [p for p in [elapsed, tokens] if p]
                stats_str = f" ({' · '.join(stats_parts)})" if stats_parts else ""
                status_elements.append({"tag": "markdown", "content": f"✱ {_escape_md(action)}{stats_str}"})
        if bottom_bar:
            # status_line 和 bottom_bar 之间加分割线
            if status_line and status_elements:
                status_elements.append({"tag": "hr"})
            ansi_text = bottom_bar.get('ansi_text', '')
            if ansi_text:
                status_elements.append({"tag": "markdown", "content": _ansi_to_lark_md(ansi_text)})
            else:
                bar_text = bottom_bar.get('text', '')
                if bar_text:
                    status_elements.append({"tag": "markdown", "content": _escape_md(bar_text)})
        if agent_panel:
            status_elements.extend(_render_agent_panel(agent_panel))
        # option_block 显示在状态区（优先用 ansi_raw 渲染颜色）
        if option_block:
            # 前面有内容时加分割线
            if status_elements:
                status_elements.append({"tag": "hr"})
            ob_ansi = option_block.get("ansi_raw", "")
            if ob_ansi:
                status_elements.append({"tag": "markdown", "content": _ansi_to_lark_md(ob_ansi)})
            else:
                sub = option_block.get("sub_type", "option")
                if sub == "permission":
                    ob_title = option_block.get("title", "")
                    ob_content = option_block.get("content", "")
                    ob_parts = []
                    if ob_title:
                        ob_parts.append(f"🔐 {_escape_md(ob_title)}")
                    if ob_content:
                        ob_parts.append(_escape_md(ob_content))
                    if not ob_parts:
                        ob_parts.append("🔐 权限确认")
                    status_elements.append({"tag": "markdown", "content": "\n".join(ob_parts)})
                else:
                    ob_question = option_block.get("question", "")
                    ob_tag = option_block.get("tag", "")
                    ob_display = ob_question or ob_tag or "请选择"
                    status_elements.append({"tag": "markdown", "content": f"🤔 {_escape_md(ob_display)}"})
        if status_elements:
            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "grey",
                "columns": [{
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": status_elements,
                }],
            })

    # === 第三层：交互按钮区（仅非冻结且非断开时）===
    if not is_frozen and not disconnected:
        buttons = _extract_buttons(blocks, option_block=option_block)
        if buttons:
            elements.extend(_build_buttons_v2(buttons, is_loading=is_loading))

    # === 第四层：菜单按钮 ===
    elements.append({"tag": "hr"})

    # loading 状态时显示处理中提示
    if is_loading and not disconnected:
        elements.append({
            "tag": "column_set",
            "flex_mode": "none",
            "background_style": "grey",
            "columns": [{
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{"tag": "markdown", "content": f"⏳ {loading_text}"}],
            }],
        })

    # 操作入口统一在 _build_menu_button_row 内的“操作”下拉，不再单独展示快捷命令选择器
    menu_elements = _build_menu_button_row(
        session_name=session_name,
        disconnected=disconnected,
        is_loading=is_loading,
        disabled_buttons=disabled_buttons,
        user_config=user_config,
    )
    elements.extend(menu_elements)

    _cb_logger.debug(
        f"build_stream_card: blocks={len(blocks)} frozen={is_frozen} "
        f"title={title!r} elements={len(elements)}"
    )

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": _build_header(title, template),
        "body": {"elements": elements},
    }


# === 辅助卡片（保留不变）===

def _build_session_list_elements(sessions: List[Dict], current_session: Optional[str], session_groups: Optional[Dict[str, str]], page: int = 0) -> List[Dict]:
    """构建会话列表元素（供 build_menu_card 复用）"""
    import os
    elements = []
    if sessions:
        PER_PAGE = 8
        total = len(sessions)
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        shown = sessions[page * PER_PAGE : (page + 1) * PER_PAGE]
        for s in shown:
            name = s["name"]
            cwd = s.get("cwd", "")
            start_time = s.get("start_time", "")
            cli_type = s.get("cli_type", "claude")
            is_current = (name == current_session)

            # CLI 类型颜色和标签：Claude=黄色，Codex=绿色
            try:
                cli_type_enum = CliType(cli_type)
            except ValueError:
                cli_type_enum = CliType.CLAUDE
            cli_color = "yellow" if cli_type_enum == CliType.CLAUDE else "green"
            cli_label = CLI_NAMES.get(cli_type_enum, "Claude")

            status_icon = "🟢" if is_current else "⚪"
            current_label = "（当前）" if is_current else ""
            if cwd:
                short_name = cwd.rstrip("/").rsplit("/", 1)[-1] or name
            else:
                short_name = name

            # 构建4行内容：名字、cli类型、启动时间、目录
            lines = [f"{status_icon} **{short_name}**{current_label}"]
            lines.append(f"<font color=\"{cli_color}\">{cli_label}</font>")

            if start_time:
                lines.append(f"启动：{start_time}")

            if cwd:
                home = os.path.expanduser("~")
                display_cwd = cwd.replace(home, "~")
                if len(display_cwd) > 40:
                    parts = display_cwd.rstrip("/").rsplit("/", 2)
                    display_cwd = "…/" + "/".join(parts[-2:]) if len(parts) > 2 else display_cwd[-40:]
                lines.append(f"`{display_cwd}`")

            header_text = "\n".join(lines)

            if is_current:
                btn_label = "断开连接"
                btn_type = "danger"
                btn_action = "list_detach"
            else:
                btn_label = "进入会话"
                btn_type = "primary"
                btn_action = "list_attach"
            has_group = bool(session_groups and name in session_groups)

            # 右列按钮（纵向堆叠）
            right_buttons = [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": btn_label},
                    "type": btn_type,
                    "behaviors": [{"type": "callback", "value": {
                        "action": btn_action, "session": name
                    }}]
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "进入群聊" if has_group else "创建群聊"},
                    "type": "default",
                    "behaviors": [{"type": "open_url",
                                   "default_url": f"https://applink.feishu.cn/client/chat/open?openChatId={session_groups[name]}",
                                   "android_url": f"https://applink.feishu.cn/client/chat/open?openChatId={session_groups[name]}",
                                   "ios_url": f"https://applink.feishu.cn/client/chat/open?openChatId={session_groups[name]}",
                                   "pc_url": f"https://applink.feishu.cn/client/chat/open?openChatId={session_groups[name]}"}]
                    if has_group else
                    [{"type": "callback", "value": {"action": "list_new_group", "session": name}}]
                },
            ]
            if has_group:
                right_buttons.append({
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "解散群聊"},
                    "type": "danger",
                    "behaviors": [{"type": "callback", "value": {
                        "action": "list_disband_group", "session": name
                    }}]
                })
            right_buttons.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🗑️ 关闭"},
                "type": "danger",
                "confirm": {
                    "title": {"tag": "plain_text", "content": "确认关闭会话"},
                    "text": {"tag": "plain_text", "content": f"确定要关闭「{name}」吗？此操作不可撤销。"}
                },
                "behaviors": [{"type": "callback", "value": {
                    "action": "list_kill", "session": name
                }}]
            })
            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 3,
                        "elements": [{"tag": "markdown", "content": header_text}]
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": right_buttons
                    },
                ]
            })
            elements.append({"tag": "hr"})

        if elements and elements[-1].get("tag") == "hr":
            elements.pop()

        if total > PER_PAGE:
            prev_disabled = page == 0
            next_disabled = page >= total_pages - 1
            prev_btn = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "⬅ 上一页"},
                "type": "default",
                **({"disabled": True} if prev_disabled else {"behaviors": [{"type": "callback", "value": {
                    "action": "menu_page", "page": page - 1
                }}]})
            }
            next_btn = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "下一页 ➡"},
                "type": "default",
                **({"disabled": True} if next_disabled else {"behaviors": [{"type": "callback", "value": {
                    "action": "menu_page", "page": page + 1
                }}]})
            }
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "horizontal_spacing": "small",
                "columns": [
                    {"tag": "column", "width": "weighted", "weight": 1, "elements": [{"tag": "markdown", "content": " "}]},
                    {"tag": "column", "width": "auto", "elements": [prev_btn]},
                    {"tag": "column", "width": "auto", "vertical_align": "center", "elements": [
                        {"tag": "markdown", "content": f"第 {page + 1}/{total_pages} 页"}
                    ]},
                    {"tag": "column", "width": "auto", "elements": [next_btn]},
                    {"tag": "column", "width": "weighted", "weight": 1, "elements": [{"tag": "markdown", "content": " "}]},
                ]
            })
    else:
        elements.append({
            "tag": "markdown",
            "content": "暂无可用会话\n\n请先在终端启动：`python remote_claude.py start <名称>`"
        })
    return elements


def build_status_card(connected: bool, session_name: Optional[str] = None) -> Dict[str, Any]:
    """构建状态卡片"""
    if connected and session_name:
        title = "🟢 已连接"
        template = "green"
        content = f"当前会话：**{session_name}**"
    else:
        title = "⚪ 未连接"
        template = "grey"
        content = "使用 `/attach <会话名>` 连接到 Claude/Codex 会话"

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": _build_header(title, template),
        "body": {"elements": [
            {"tag": "markdown", "content": content},
            {"tag": "hr"},
            _build_menu_button_only(),
        ]}
    }


def _dir_session_name(path: str) -> str:
    """从目录路径生成合法会话名（取最后一段，转小写，非字母数字替换为-）"""
    import os
    basename = os.path.basename(path.rstrip("/")) or "session"
    name = _re.sub(r"[^a-z0-9]+", "-", basename.lower()).strip("-")
    return name or "session"


def build_dir_card(
    target,
    entries: List[Dict],
    _: List[Dict],
    tree: bool = False,
    session_groups: Optional[Dict[str, str]] = None,
    page: int = 0,
    user_config: Optional["UserConfig"] = None,
) -> Dict[str, Any]:
    """构建目录浏览卡片

    顶层目录（depth==0）带两个操作按钮：
    - 「📂 进入」：导航进入该子目录（继续浏览）
    - 「🚀 在此启动」：在该目录创建新 Claude 会话

    entries 格式: [{"name": str, "full_path": str, "is_dir": bool, "depth": int}]
    sessions 格式: [{"name": str, "cwd": str}]（仅用于信息展示，不影响按钮可用性）
    """
    import os
    title = f"🌲 {target}" if tree else f"📂 {target}"
    elements = []

    target_str = str(target).rstrip("/") or "/"
    parent_path = os.path.dirname(target_str)
    if parent_path and parent_path != target_str:
        elements.append({
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [{
                "tag": "column",
                "width": "auto",
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "⬆️ 返回上级"},
                    "type": "default",
                    "behaviors": [{"type": "callback", "value": {
                        "action": "dir_browse", "path": parent_path
                    }}]
                }]
            }]
        })
        elements.append({"tag": "hr"})

    PER_PAGE = 12
    total = len(entries)
    if tree:
        # tree 模式不分页，直接展示全部（已有 max_items 上限）
        shown = entries
        page = 0
        total_pages = 1
    else:
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        shown = entries[page * PER_PAGE : (page + 1) * PER_PAGE]

    for entry in shown:
        name = entry["name"]
        is_dir = entry["is_dir"]
        depth = entry.get("depth", 0)
        full_path = entry.get("full_path", "")
        indent = "　" * depth
        icon = "📁" if is_dir else "📄"

        if is_dir and depth == 0:
            auto_session = _dir_session_name(full_path)
            # 前缀匹配：找 session_groups 中精确匹配或以 auto_session + "_" 开头的条目（取最后一个，即最新的）
            matched_group_cid = None
            if session_groups:
                for sn, cid in session_groups.items():
                    if sn == auto_session or sn.startswith(auto_session + "_"):
                        matched_group_cid = cid
            group_btn = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "进入群聊" if matched_group_cid else "创建群聊"},
                "type": "default",
                "behaviors": [{"type": "open_url",
                               "default_url": f"https://applink.feishu.cn/client/chat/open?openChatId={matched_group_cid}",
                               "android_url": f"https://applink.feishu.cn/client/chat/open?openChatId={matched_group_cid}",
                               "ios_url": f"https://applink.feishu.cn/client/chat/open?openChatId={matched_group_cid}",
                               "pc_url": f"https://applink.feishu.cn/client/chat/open?openChatId={matched_group_cid}"}]
                if matched_group_cid else
                [{"type": "callback", "value": {
                    "action": "dir_new_group",
                    "path": full_path,
                    "session_name": auto_session
                }}]
            }

            commands = _get_matching_commands(user_config)

            # 构建启动按钮（横排）
            launch_buttons = []
            for i, cmd in enumerate(commands):
                btn_type = "primary" if i == 0 else "default"
                launch_buttons.append({
                    "tag": "column",
                    "width": "auto",
                    "elements": [{
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": cmd["name"]},
                        "type": btn_type,
                        "behaviors": [{
                            "type": "callback",
                            "value": {
                                "action": "dir_start",
                                "path": full_path,
                                "session_name": auto_session,
                                "cli_command": cmd["command"],
                            }
                        }]
                    }]
                })

            # 构建右侧列元素
            if launch_buttons:
                right_column_elements = [
                    {
                        "tag": "column_set",
                        "flex_mode": "none",
                        "columns": launch_buttons,
                    },
                    group_btn,
                ]
            else:
                # 无匹配命令，隐藏启动按钮
                right_column_elements = [group_btn]

            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 4,
                        "elements": [{
                            "tag": "interactive_container",
                            "width": "fill",
                            "height": "auto",
                            "behaviors": [{"type": "callback", "value": {
                                "action": "dir_browse", "path": full_path
                            }}],
                            "elements": [{"tag": "markdown", "content": f"📁 **{name}**"}]
                        }]
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": right_column_elements
                    }
                ]
            })
            elements.append({"tag": "hr"})
        else:
            elements.append({"tag": "markdown", "content": f"{indent}{icon} {name}"})

    if not tree and total > PER_PAGE:
        prev_disabled = page == 0
        next_disabled = page >= total_pages - 1
        prev_btn = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "⬅ 上一页"},
            "type": "default",
            **({"disabled": True} if prev_disabled else {"behaviors": [{"type": "callback", "value": {
                "action": "dir_page", "path": target_str, "page": page - 1
            }}]})
        }
        next_btn = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "下一页 ➡"},
            "type": "default",
            **({"disabled": True} if next_disabled else {"behaviors": [{"type": "callback", "value": {
                "action": "dir_page", "path": target_str, "page": page + 1
            }}]})
        }
        elements.append({
            "tag": "column_set",
            "flex_mode": "none",
            "horizontal_spacing": "small",
            "columns": [
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [{"tag": "markdown", "content": " "}]},
                {"tag": "column", "width": "auto", "elements": [prev_btn]},
                {"tag": "column", "width": "auto", "vertical_align": "center", "elements": [
                    {"tag": "markdown", "content": f"第 {page + 1}/{total_pages} 页"}
                ]},
                {"tag": "column", "width": "auto", "elements": [next_btn]},
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [{"tag": "markdown", "content": " "}]},
            ]
        })

    elements.append({"tag": "hr"})
    elements.append(_build_menu_button_only())

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": _build_header(title, "blue"),
        "body": {"elements": elements}
    }


def build_help_card() -> Dict[str, Any]:
    """构建帮助卡片"""
    help_content = """**🚀 快速开始**
• `/menu` - 弹出快捷操作面板（推荐入口）

**会话管理**
• `/start <会话名> [工作路径]` - 启动新会话并自动连接
• `/attach <会话名>` - 连接到已有会话
• `/detach` - 断开当前会话
• `/list` - 列出所有可用会话（带一键 Attach 按钮）
• `/kill <会话名>` - 终止会话
• `/status` - 显示当前连接状态

**目录浏览**
• `/ls [路径]` - 查看文件列表
• `/tree [路径]` - 查看目录树（2 层）

**群聊协作**
• `/new-group <会话名>` - 创建专属群聊，多人共用同一 Claude

**其他**
• `/help` - 显示此帮助
• `/menu` - 快捷操作面板"""

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": _build_header("📖 Remote Claude 帮助", "blue"),
        "body": {"elements": [
            {"tag": "markdown", "content": help_content},
            {"tag": "hr"},
            _build_menu_button_only(),
        ]}
    }


def build_session_closed_card(session_name: str) -> Dict[str, Any]:
    """构建会话关闭通知卡片（服务端关闭时推送给用户）"""
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": _build_header("🔴 会话已关闭", "red"),
        "body": {"elements": [
            {"tag": "markdown", "content": f"会话 **{session_name}** 已关闭，连接已自动断开。\n\n如需继续，请重新启动会话或连接到其他会话。"},
            {"tag": "hr"},
            {
                "tag": "column_set",
                "flex_mode": "none",
                "columns": [
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [{
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "📋 查看会话"},
                            "type": "primary",
                            "behaviors": [{"type": "callback", "value": {"action": "menu_list"}}]
                        }]
                    },
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [{
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "⚡ 菜单"},
                            "type": "default",
                            "behaviors": [{"type": "callback", "value": {"action": "menu_open"}}]
                        }]
                    }
                ]
            }
        ]}
    }


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


def build_menu_card(sessions: List[Dict], current_session: Optional[str] = None,
                    session_groups: Optional[Dict[str, str]] = None, page: int = 0,
                    notify_enabled: bool = True, urgent_enabled: bool = False,
                    bypass_enabled: bool = False,
                    user_config: Optional["UserConfig"] = None) -> Dict[str, Any]:
    """构建快捷操作菜单卡片（/menu 和 /list 共用）：内嵌会话列表 + 快捷操作"""
    elements = []

    elements.append({"tag": "markdown", "content": "**会话管理**"})
    elements.append({"tag": "hr"})
    elements.extend(_build_session_list_elements(sessions, current_session, session_groups, page=page))

    elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": "**快捷操作**"})
    elements.append({
        "tag": "column_set",
        "flex_mode": "none",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📂 文件列表"},
                    "type": "default",
                    "behaviors": [{"type": "callback", "value": {"action": "menu_ls"}}]
                }]
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🌲 目录树"},
                    "type": "default",
                    "behaviors": [{"type": "callback", "value": {"action": "menu_tree"}}]
                }]
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🔄 刷新"},
                    "type": "default",
                    "behaviors": [{"type": "callback", "value": {"action": "menu_open"}}]
                }]
            },
        ]
    })

    notify_label = "🔔 完成通知: 开" if notify_enabled else "🔕 完成通知: 关"
    if not notify_enabled:
        urgent_label = "🔇 加急通知: 关"
        urgent_button: Dict[str, Any] = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": urgent_label},
            "type": "default",
            "disabled": True,
        }
    elif urgent_enabled:
        urgent_label = "🔔 加急通知: 开"
        urgent_button = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": urgent_label},
            "type": "default",
            "behaviors": [{"type": "callback", "value": {"action": "menu_toggle_urgent"}}]
        }
    else:
        urgent_label = "🔕 加急通知: 关"
        urgent_button = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": urgent_label},
            "type": "default",
            "behaviors": [{"type": "callback", "value": {"action": "menu_toggle_urgent"}}]
        }
    elements.append({
        "tag": "column_set",
        "flex_mode": "none",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": notify_label},
                    "type": "default",
                    "behaviors": [{"type": "callback", "value": {"action": "menu_toggle_notify"}}]
                }]
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [urgent_button]
            },
        ]
    })

    bypass_label = "🔓 新会话bypass: 开" if bypass_enabled else "🔒 新会话bypass: 关"
    elements.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": bypass_label},
        "type": "default",
        "behaviors": [{"type": "callback", "value": {"action": "menu_toggle_bypass"}}]
    })

    # 自动应答按钮已迁移到会话流式卡片操作区（stream_toggle_auto_answer）

    # 自定义命令配置显示
    elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": "**自定义命令**"})

    if user_config and user_config.session.custom_commands.is_visible():
        custom_cmds = user_config.session.custom_commands.commands
        for cmd in custom_cmds:
            # 格式: "claude → aider (AI pair programming)"
            desc = f" _{cmd.description}_" if cmd.description else ""
            elements.append({
                "tag": "markdown",
                "content": f"- **{cmd.name}** → `{cmd.command}`{desc}"
            })
    else:
        elements.append({
            "tag": "markdown",
            "content": "_未配置，使用默认命令_"
        })

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": _build_header("⚡ 快捷操作", "turquoise"),
        "body": {"elements": elements}
    }


def build_loading_card_from_snapshot(
    snapshot: Optional[dict],
    session_name: str,
    loading_text: str,
    user_config: Optional["UserConfig"] = None,
    **kwargs,
) -> Dict[str, Any]:
    """从共享内存快照构建 loading 状态卡片的便捷函数

    简化 lark_handler 中的调用，避免重复的 snapshot 字段提取逻辑。

    Args:
        snapshot: 共享内存快照（可为 None）
        session_name: 会话名称
        loading_text: loading 提示文本
        user_config: 用户配置对象
        **kwargs: 其他传递给 build_stream_card 的参数（如 disconnected, option_block）

    Returns:
        飞书卡片 dict

    Example:
        loading_card = build_loading_card_from_snapshot(
            snapshot, session_name, "正在断开连接...",
            user_config=self._user_config, disconnected=True
        )
    """
    if snapshot:
        # 优先使用 kwargs 中的 option_block，否则从 snapshot 获取
        # 使用 get 避免修改传入的 kwargs dict
        option_block = kwargs.get("option_block")
        if option_block is None:
            option_block = snapshot.get('option_block')
        # 复制 kwargs 以避免副作用（排除已处理的 option_block）
        other_kwargs = {k: v for k, v in kwargs.items() if k != "option_block"}
        return build_stream_card(
            blocks=snapshot.get("blocks", []),
            status_line=snapshot.get("status_line"),
            bottom_bar=snapshot.get("bottom_bar"),
            agent_panel=snapshot.get("agent_panel"),
            option_block=option_block,
            session_name=session_name,
            cli_type=snapshot.get("cli_type", "claude"),
            user_config=user_config,
            is_loading=True,
            loading_text=loading_text,
            **other_kwargs,
        )
    else:
        return build_stream_card(
            blocks=[],
            session_name=session_name,
            user_config=user_config,
            is_loading=True,
            loading_text=loading_text,
            **kwargs,
        )
