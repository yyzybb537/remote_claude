"""业务枚举定义"""
from enum import StrEnum


class CliType(StrEnum):
    """CLI 类型枚举"""
    CLAUDE = "claude"
    CODEX = "codex"
