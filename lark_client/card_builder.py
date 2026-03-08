"""
飞书卡片构建器（Schema 2.0 格式）

主要入口：
- build_stream_card(blocks, ...)：从共享内存 blocks 流构建飞书卡片（供 SharedMemoryPoller 调用）

辅助卡片：
- build_session_list_card / build_status_card / build_help_card
- build_history_card / build_dir_card / build_menu_card / build_session_closed_card
"""

import logging
import re as _re
from typing import Dict, Any, List, Optional

_cb_logger = logging.getLogger('CardBuilder')

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


def _build_menu_button_row() -> Dict[str, Any]:
    """底部快捷菜单按钮行（⚡菜单 + 快捷键按钮），用于流式卡片"""
    buttons = [
        ("⚡ 菜单", {"action": "menu_open"}),
        ("↑", {"action": "send_key", "key": "up"}),
        ("↓", {"action": "send_key", "key": "down"}),
        ("Enter", {"action": "send_key", "key": "enter"}),
        ("Ctrl+O", {"action": "send_key", "key": "ctrl_o"}),
        ("Shift+Tab", {"action": "send_key", "key": "shift_tab"}),
        ("ESC", {"action": "send_key", "key": "esc"}),
    ]
    columns = []
    for label, value in buttons:
        columns.append({
            "tag": "column",
            "width": "auto",
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": "default",
                "behaviors": [{"type": "callback", "value": value}]
            }]
        })
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "columns": columns,
    }


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


def _build_buttons_v2(options: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Schema 2.0 按钮组：每行最多 4 个，超出时自动分多行"""
    MAX_PER_ROW = 4
    total = len(options)
    rows = []
    for row_start in range(0, total, MAX_PER_ROW):
        row_opts = options[row_start:row_start + MAX_PER_ROW]
        columns = []
        for i, opt in enumerate(row_opts):
            global_idx = row_start + i
            btn_type = "primary" if global_idx == 0 else "default"
            columns.append({
                "tag": "column",
                "elements": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": opt["label"]},
                        "type": btn_type,
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": "select_option",
                                    "value": opt["value"],
                                    "total": str(total),
                                }
                            }
                        ]
                    }
                ]
            })
        rows.append({
            "tag": "column_set",
            "flex_mode": "none",
            "columns": columns
        })
    return rows


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

    return None


def _determine_header(
    blocks: List[dict],
    status_line: Optional[dict],
    bottom_bar: Optional[dict],
    is_frozen: bool,
    option_block: Optional[dict] = None,
) -> tuple:
    """确定卡片标题和颜色模板，返回 (title, template)"""
    if is_frozen:
        return "📋 会话记录", "grey"

    has_streaming = any(b.get("is_streaming", False) for b in blocks)

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

    return "✅ Claude 就绪", "green"


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
) -> Dict[str, Any]:
    """从共享内存 blocks 流构建飞书卡片

    四层结构：
    1. 内容区：累积型 blocks
    2. 状态区：status_line + bottom_bar + agent_panel + option_block 问题文本
    3. 交互区：option_block 的选项按钮
    4. 菜单按钮
    """
    title, template = _determine_header(blocks, status_line, bottom_bar, is_frozen, option_block=option_block)

    # === 第一层：内容区 ===
    elements = []
    has_content = False

    for block_dict in blocks:
        rendered = _render_block_colored(block_dict)
        if rendered:
            has_content = True
            elements.append({"tag": "markdown", "content": rendered})


    # === 第二层：状态区（仅非冻结时，column_set 灰色背景）===
    if not is_frozen and (status_line or bottom_bar or agent_panel or option_block):
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

    # === 第三层：交互按钮区（仅非冻结时）===
    if not is_frozen:
        buttons = _extract_buttons(blocks, option_block=option_block)
        if buttons:
            elements.extend(_build_buttons_v2(buttons))

    # === 第四层：菜单按钮 ===
    elements.append({"tag": "hr"})
    elements.append(_build_menu_button_row())

    _cb_logger.debug(
        f"build_stream_card: blocks={len(blocks)} frozen={is_frozen} "
        f"title={title!r} elements={len(elements)}"
    )

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "body": {"elements": elements},
    }


# === 辅助卡片（保留不变）===

def build_session_list_card(sessions: List[Dict], current_session: Optional[str] = None, session_groups: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """构建会话列表卡片（带 Attach / New-Group 操作按钮）"""
    elements = []

    if sessions:
        for s in sessions:
            name = s["name"]
            cwd = s.get("cwd", "")
            start_time = s.get("start_time", "")
            is_current = (name == current_session)

            # 标题行：会话名 + 当前标记
            status_icon = "🟢" if is_current else "⚪"
            current_label = "（当前）" if is_current else ""
            # 纯展示用短名：优先取 cwd 最后一级目录名，否则直接用 name
            if cwd:
                short_name = cwd.rstrip("/").rsplit("/", 1)[-1] or name
            else:
                short_name = name
            meta_parts = []
            if start_time:
                meta_parts.append(f"启动：{start_time}")
            if cwd:
                import os
                home = os.path.expanduser("~")
                display_cwd = cwd.replace(home, "~")
                if len(display_cwd) > 40:
                    parts = display_cwd.rstrip("/").rsplit("/", 2)
                    display_cwd = "…/" + "/".join(parts[-2:]) if len(parts) > 2 else display_cwd[-40:]
                meta_parts.append(f"`{display_cwd}`")
            meta_str = "  ".join(meta_parts) if meta_parts else ""

            header_text = f"{status_icon} **{short_name}**{current_label}"
            if meta_str:
                header_text += f"\n{meta_str}"

            btn_label = "已连接" if is_current else "进入会话"
            btn_type = "default" if is_current else "primary"
            columns = [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 5,
                    "elements": [{"tag": "markdown", "content": header_text}]
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 2,
                    "elements": [{
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": btn_label},
                        "type": btn_type,
                        "behaviors": [{"type": "callback", "value": {
                            "action": "list_attach", "session": name
                        }}]
                    }]
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 2,
                    "elements": [{
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "进入群聊" if (session_groups and name in session_groups) else "创建群聊"},
                        "type": "default",
                        "behaviors": [{"type": "open_url", "default_url": f"https://applink.feishu.cn/client/chat/open?openChatId={session_groups[name]}"}]
                        if (session_groups and name in session_groups) else
                        [{"type": "callback", "value": {"action": "list_new_group", "session": name}}]
                    }]
                },
            ]
            if session_groups and name in session_groups:
                columns.append({
                    "tag": "column",
                    "width": "weighted",
                    "weight": 2,
                    "elements": [{
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "解散群聊"},
                        "type": "danger",
                        "behaviors": [{"type": "callback", "value": {
                            "action": "list_disband_group", "session": name
                        }}]
                    }]
                })
            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "columns": columns
            })
            elements.append({"tag": "hr"})

        if elements and elements[-1].get("tag") == "hr":
            elements.pop()
    else:
        elements.append({
            "tag": "markdown",
            "content": "暂无可用会话\n\n请先在终端启动：`python remote_claude.py start <名称>`"
        })

    elements.append({"tag": "hr"})
    elements.append(_build_menu_button_only())

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📋 可用会话"},
            "template": "blue",
        },
        "body": {"elements": elements}
    }


def build_status_card(connected: bool, session_name: Optional[str] = None) -> Dict[str, Any]:
    """构建状态卡片"""
    if connected and session_name:
        title = "🟢 已连接"
        template = "green"
        content = f"当前会话：**{session_name}**"
    else:
        title = "⚪ 未连接"
        template = "grey"
        content = "使用 `/attach <会话名>` 连接到 Claude 会话"

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "body": {"elements": [
            {"tag": "markdown", "content": content},
            {"tag": "hr"},
            _build_menu_button_only(),
        ]}
    }


def build_history_card(content: str, session_name: str = "") -> Dict[str, Any]:
    """构建历史记录卡片（attach 后展示）"""
    if session_name:
        title = f"🟢 已连接 · {session_name}"
        template = "green"
        subtitle = f"以下为会话 **{session_name}** 的最近内容："
    else:
        title = "📋 会话历史记录"
        template = "grey"
        subtitle = "以下为该会话的最近内容："
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": subtitle},
                {"tag": "hr"},
                {"tag": "markdown", "content": _safe_truncate(content, 4000)},
                {"tag": "hr"},
                _build_menu_button_only(),
            ]
        }
    }


def _dir_session_name(path: str) -> str:
    """从目录路径生成合法会话名（取最后一段，转小写，非字母数字替换为-）"""
    import os
    basename = os.path.basename(path.rstrip("/")) or "session"
    name = _re.sub(r"[^a-z0-9]+", "-", basename.lower()).strip("-")
    return name or "session"


def build_dir_card(target, entries: List[Dict], sessions: List[Dict], tree: bool = False, session_groups: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
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

    cap = 20
    total = len(entries)
    shown = entries[:cap]

    for entry in shown:
        name = entry["name"]
        is_dir = entry["is_dir"]
        depth = entry.get("depth", 0)
        full_path = entry.get("full_path", "")
        indent = "　" * depth
        icon = "📁" if is_dir else "📄"

        if is_dir and depth == 0:
            auto_session = _dir_session_name(full_path)
            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 3,
                        "elements": [{"tag": "markdown", "content": f"{icon} **{name}**"}]
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [{
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "📂 进入"},
                            "type": "default",
                            "behaviors": [{"type": "callback", "value": {
                                "action": "dir_browse", "path": full_path
                            }}]
                        }]
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [{
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "🚀 在此启动"},
                            "type": "primary",
                            "behaviors": [{"type": "callback", "value": {
                                "action": "dir_start",
                                "path": full_path,
                                "session_name": auto_session
                            }}]
                        }]
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [{
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "进入群聊" if (session_groups and auto_session in session_groups) else "创建群聊"},
                            "type": "default",
                            "behaviors": [{"type": "open_url", "default_url": f"https://applink.feishu.cn/client/chat/open?openChatId={session_groups[auto_session]}"}]
                            if (session_groups and auto_session in session_groups) else
                            [{"type": "callback", "value": {
                                "action": "dir_new_group",
                                "path": full_path,
                                "session_name": auto_session
                            }}]
                        }]
                    }
                ]
            })
        else:
            elements.append({"tag": "markdown", "content": f"{indent}{icon} {name}"})

    if total > cap:
        elements.append({"tag": "markdown", "content": f"*...（共 {total} 项，仅显示前 {cap} 项）*"})

    elements.append({"tag": "hr"})
    elements.append(_build_menu_button_only())

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
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

**历史记录**
• `/history [行数]` - 查看最近历史（默认 30 行）

**群聊协作**
• `/new-group <会话名>` - 创建专属群聊，多人共用同一 Claude

**其他**
• `/help` - 显示此帮助
• `/menu` - 快捷操作面板"""

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📖 Remote Claude 帮助"},
            "template": "blue",
        },
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
        "header": {
            "title": {"tag": "plain_text", "content": "🔴 会话已关闭"},
            "template": "red",
        },
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


def build_menu_card(sessions: List[Dict], current_session: Optional[str] = None) -> Dict[str, Any]:
    """构建快捷操作菜单卡片（/menu）"""
    elements = []

    if current_session:
        status_text = f"🟢 当前连接：**{current_session}**"
    else:
        status_text = "⚪ 未连接任何会话"
    elements.append({"tag": "markdown", "content": status_text})
    elements.append({"tag": "hr"})

    elements.append({"tag": "markdown", "content": "**会话管理**"})
    row1_buttons = []

    if current_session:
        row1_buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🔌 断开连接"},
            "type": "danger",
            "behaviors": [{"type": "callback", "value": {"action": "menu_detach"}}]
        })
    else:
        if sessions:
            first_session = sessions[0]["name"]
            row1_buttons.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"⚡ 连接 {first_session}"},
                "type": "primary",
                "behaviors": [{"type": "callback", "value": {
                    "action": "list_attach", "session": first_session
                }}]
            })

    row1_buttons.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "📋 会话列表"},
        "type": "default",
        "behaviors": [{"type": "callback", "value": {"action": "menu_list"}}]
    })
    row1_buttons.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "📖 帮助"},
        "type": "default",
        "behaviors": [{"type": "callback", "value": {"action": "menu_help"}}]
    })

    elements.append({
        "tag": "column_set",
        "flex_mode": "none",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [btn]
            }
            for btn in row1_buttons
        ]
    })

    elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": "**目录浏览**"})
    dir_columns = [
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📂 查看文件列表"},
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
                "text": {"tag": "plain_text", "content": "🌲 查看目录树"},
                "type": "default",
                "behaviors": [{"type": "callback", "value": {"action": "menu_tree"}}]
            }]
        },
    ]
    if current_session:
        dir_columns.append({
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📜 查看历史"},
                "type": "default",
                "behaviors": [{"type": "callback", "value": {"action": "menu_history"}}]
            }]
        })
    elements.append({"tag": "column_set", "flex_mode": "none", "columns": dir_columns})

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⚡ 快捷操作"},
            "template": "turquoise",
        },
        "body": {"elements": elements}
    }
