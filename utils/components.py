"""
Claude CLI 输出组件模型

将 Claude 终端输出解析为结构化组件，供 CardBuilder 渲染为飞书卡片。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class OutputBlock:
    """统一输出块（文本回复、工具调用、Agent/Plan 块的统一表示）

    parser 不区分三者，统一产出此类型。content 为圆点字符之后的内容（已去掉首列圆点）。
    card_builder 可根据首行内容格式决定渲染方式。
    """
    content: str          # 完整块内容（首行去掉圆点，后续行原样，\n 连接）
    is_streaming: bool = False  # 首行首列圆点是否 blink
    start_row: int = -1   # 在终端屏幕中的起始行号（用于帧间同一 Block 识别，-1 表示未知）
    ansi_content: str = ""     # 对应 content，带 ANSI 转义码
    indicator: str = ""        # 首列圆点字符原文（如 ●）
    ansi_indicator: str = ""   # 带 ANSI 颜色的圆点字符


@dataclass
class TextBlock:
    """文本回复（保留作为向后兼容，新代码请使用 OutputBlock）"""
    content: str
    is_streaming: bool = False


@dataclass
class UserInput:
    """用户输入（❯ 行）"""
    text: str
    ansi_text: str = ""        # 对应 text，带 ANSI 转义码
    indicator: str = ""        # 首列提示符原文（❯）
    ansi_indicator: str = ""   # 带 ANSI 颜色的提示符


@dataclass
class ToolCall:
    """工具调用块（保留作为向后兼容，新代码请使用 OutputBlock）"""
    tool_name: str
    args_summary: str
    status: str = "running"
    status_detail: str = ""
    output: str = ""
    is_streaming: bool = False


@dataclass
class AgentBlock:
    """Agent/Plan 块（保留作为向后兼容，新代码请使用 OutputBlock）"""
    agent_type: str
    description: str
    status: str = "running"
    status_detail: str = ""
    stats: str = ""
    sub_calls: List[str] = field(default_factory=list)
    is_streaming: bool = False


@dataclass
class OptionBlock:
    """选项交互块（统一 option + permission 两种场景）

    状态型组件：全局唯一，存储在 ClaudeWindow.option_block，不进入 blocks 累积列表。
    - sub_type="option"：AskUserQuestion 选项（2 分割线 input_rows 中检测到编号选项）
    - sub_type="permission"：权限确认（1 分割线 bottom_rows 中检测到编号选项）
    """
    sub_type: str = "option"   # "option" | "permission"
    tag: str = ""              # 分类标签（option 场景）
    title: str = ""            # 工具名称（permission 场景）
    content: str = ""          # 详细内容（permission 场景）
    question: str = ""         # 问题文本
    options: List[dict] = field(default_factory=list)  # [{"label": str, "value": str}]
    ansi_raw: str = ""         # 整个选项区域的 ANSI 原始文本
    indicator: str = ""        # 首列字符原文
    ansi_indicator: str = ""   # 带 ANSI 颜色的首列字符


# 向后兼容别名
PermissionBlock = OptionBlock


@dataclass
class StatusLine:
    """状态行（✱ 动作... (时间 · tokens)）"""
    action: str          # 动作动词（如 "Germinating..."）
    elapsed: str = ""    # 时长（如 "16m 33s"）
    tokens: str = ""     # token 消耗（如 "↓ 4.3k tokens"）
    raw: str = ""        # 原始文本
    ansi_raw: str = ""         # 对应 raw，带 ANSI 转义码
    indicator: str = ""        # 首列星星字符原文（如 ✱）
    ansi_indicator: str = ""   # 带 ANSI 颜色的星星字符


@dataclass
class Divider:
    """水平分割线（区域边界标记，不渲染）

    Claude CLI 终端有 2 条由 ─ 组成的分割线，将屏幕分为 3 个区域：
    输出区（上）| ─── | 用户输入框（中）| ─── | 底部栏（下）
    解析时用于定位区域边界，不作为卡片内容渲染。
    """
    pass


@dataclass
class BottomBar:
    """底部栏（权限模式、后台任务等状态信息）

    固定在终端最底部的状态栏，内容如：
    - ▶▶ bypass permissions on (shift+tab to cycle) · esc to interrupt
    - 2 bashes · ↓ to manage
    - 4 local agents · ↓ to manage · ctrl+f to kill agents
    """
    text: str  # 原始文本内容
    ansi_text: str = ""  # 对应 text，带 ANSI 转义码
    has_background_agents: bool = False  # 底部栏是否包含后台 agent 信息
    agent_count: int = 0                 # 后台 agent 数量
    agent_summary: str = ""              # agent 摘要文本（如 "4 local agents"）


@dataclass
class AgentPanelBlock:
    """Agent 管理面板（用户按 ↓ 展开的列表或 Enter 查看的详情）

    出现在只有 1 条分割线的特殊布局中（输入区消失）。
    列表模式：显示所有后台 agent 及其状态
    详情模式：显示单个 agent 的详细信息
    """
    panel_type: str = "list"  # "list" | "detail"
    # 列表模式字段
    agent_count: int = 0
    agents: List[dict] = field(default_factory=list)  # [{"name": str, "status": str, "is_selected": bool}]
    # 详情模式字段
    agent_name: str = ""
    agent_type: str = ""
    stats: str = ""
    progress: str = ""
    prompt: str = ""
    # 通用字段
    raw_text: str = ""
    ansi_raw: str = ""


# 所有组件类型的联合类型
Component = Union[OutputBlock, TextBlock, UserInput, ToolCall, AgentBlock, OptionBlock, PermissionBlock, StatusLine, Divider, BottomBar, AgentPanelBlock]
