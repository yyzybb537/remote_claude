"""终端屏幕解析器包

提供可插拔的解析器架构，支持 Claude CLI、Codex CLI 和 Cursor Agent CLI。

使用方法：
    from parsers import ClaudeParser, CodexParser, AgentParser, BaseParser
"""

from .base_parser import BaseParser
from .claude_parser import ClaudeParser, ScreenParser  # ScreenParser 为向后兼容别名
from .codex_parser import CodexParser
from .agent_parser import AgentParser

__all__ = ['BaseParser', 'ClaudeParser', 'CodexParser', 'AgentParser', 'ScreenParser']
