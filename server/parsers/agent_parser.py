"""Cursor Agent CLI 屏幕解析器

Cursor Agent 二进制名为 `agent`，基于 Ink 构建，终端 UI 风格与 OpenAI Codex 非常接近：
使用 `›` 作为输入提示符、圆点/星号字符作为状态/输出指示、背景色区域标记输入区。
作为最小集成，`AgentParser` 直接复用 `CodexParser` 的全套解析逻辑。

未来若需要针对 Cursor 的欢迎框（"Cursor Agent (vX.Y.Z)"）或专有面板做差异化解析，
在此子类中覆盖 `_is_welcome_box` 等钩子即可。
"""

from .codex_parser import CodexParser


class AgentParser(CodexParser):
    """Cursor Agent CLI 解析器（当前直接复用 CodexParser 逻辑）。"""
    pass
