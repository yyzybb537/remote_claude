#!/usr/bin/env python3
"""测试 CliType 枚举定义"""


def test_cli_type_enum_values():
    """测试 CliType 枚举值是否正确"""
    from server.biz_enum import CliType

    assert CliType.CLAUDE == "claude"
    assert CliType.CODEX == "codex"
    assert len(CliType) == 2


def test_cli_type_string_conversion():
    """测试枚举与字符串转换"""
    from server.biz_enum import CliType

    assert str(CliType.CLAUDE) == "claude"
    assert CliType("claude") == CliType.CLAUDE
    assert CliType("codex") == CliType.CODEX


if __name__ == "__main__":
    test_cli_type_enum_values()
    test_cli_type_string_conversion()
    print("所有测试通过!")
