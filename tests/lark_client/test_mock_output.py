"""
模拟 Claude CLI 输出测试
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lark_client.terminal_buffer import TerminalBuffer


def test_real_claude_output():
    """模拟真实的 Claude CLI 输出"""
    print("=" * 60)
    print("测试：模拟真实 Claude CLI 输出")
    print("=" * 60)

    buffer = TerminalBuffer()

    # 模拟真实的 Claude CLI 输出序列
    # 这是典型的输出模式：
    # 1. 用户输入回显
    # 2. 动画（Thinking/Seasoning 等）
    # 3. 实际回复

    outputs = [
        # 输入回显
        "你好",
        "\r\n",
        # 动画开始 - 使用 \r 回到行首覆盖
        "\x1b[?25l",  # 隐藏光标
        "( · Thinking)",
        "\r\x1b[K",  # 回到行首并清除
        "( · Thinking.)",
        "\r\x1b[K",
        "( · Thinking..)",
        "\r\x1b[K",
        "( · Seasoning)",
        "\r\x1b[K",
        "( · Seasoning.)",
        "\r\x1b[K",
        "\x1b[?25h",  # 显示光标
        # 实际回复
        "你好！很高兴见到你。",
    ]

    for i, output in enumerate(outputs):
        buffer.write(output)
        content = buffer.get_content()
        print(f"步骤 {i+1}: 写入 {repr(output)[:30]}")
        print(f"  缓冲区: {repr(content)[:60]}")

    final = buffer.get_content()
    print(f"\n最终内容: '{final}'")
    print("=" * 60)
    return final


def test_overwrite_with_spaces():
    """测试带空格的覆盖"""
    print("\n" + "=" * 60)
    print("测试：带空格的覆盖")
    print("=" * 60)

    buffer = TerminalBuffer()

    # 写入长文本
    buffer.write("( · Thinking)                    ")
    print(f"写入后: '{buffer.get_content()}'")

    # 回到行首
    buffer.write("\r")

    # 写入短文本（不会覆盖全部）
    buffer.write("你好！")
    print(f"覆盖后: '{buffer.get_content()}'")

    # 这就是问题！短文本不会覆盖长文本的尾部
    # 需要先清除行

    print("=" * 60)


def test_correct_overwrite():
    """测试正确的覆盖方式"""
    print("\n" + "=" * 60)
    print("测试：正确的覆盖（使用 \\x1b[K 清除）")
    print("=" * 60)

    buffer = TerminalBuffer()

    # 写入长文本
    buffer.write("( · Thinking)                    ")
    print(f"写入后: '{buffer.get_content()}'")

    # 回到行首并清除到行尾
    buffer.write("\r\x1b[K")
    print(f"清除后: '{buffer.get_content()}'")

    # 写入短文本
    buffer.write("你好！")
    print(f"最终: '{buffer.get_content()}'")

    print("=" * 60)


def test_incremental_output():
    """测试增量输出（Claude 实际行为）"""
    print("\n" + "=" * 60)
    print("测试：增量输出")
    print("=" * 60)

    buffer = TerminalBuffer()

    # Claude 实际上是逐字符输出的
    outputs = [
        "你",
        "好",
        "！",
        "\n",
        "很",
        "高",
        "兴",
        "见",
        "到",
        "你",
        "。",
    ]

    for char in outputs:
        buffer.write(char)

    final = buffer.get_content()
    print(f"最终内容: '{final}'")
    assert final == "你好！\n很高兴见到你。", f"期望 '你好！\\n很高兴见到你。', 实际 '{final}'"
    print("✓ 测试通过")
    print("=" * 60)


def test_animation_without_clear():
    """测试没有清除的动画（问题场景）"""
    print("\n" + "=" * 60)
    print("测试：没有清除的动画（问题场景）")
    print("=" * 60)

    buffer = TerminalBuffer()

    # 如果 Claude CLI 没有使用 \x1b[K 清除
    # 只用 \r 回到行首
    outputs = [
        "( · Thinking)    ",  # 17 字符
        "\r",
        "你好！",  # 只有 3 字符（6 字节 UTF-8）
    ]

    for output in outputs:
        buffer.write(output)
        print(f"写入 {repr(output)}: '{buffer.get_content()}'")

    final = buffer.get_content()
    print(f"\n最终内容: '{final}'")
    print("问题：'你好！' 只覆盖了前3个字符位置，后面的内容还在")
    print("=" * 60)


def simulate_real_session():
    """模拟真实会话"""
    print("\n" + "=" * 60)
    print("模拟真实会话")
    print("=" * 60)

    # 这是从实际 Claude CLI 捕获的输出模式
    # 需要根据实际情况调整

    buffer = TerminalBuffer()

    # 模拟输出流
    raw_outputs = [
        b"\x1b[?2026h",  # 私有模式
        b"\x1b[?25l",    # 隐藏光标
        b"( \xc2\xb7 Thinking)",  # ( · Thinking)
        b"\r\x1b[K",
        b"( \xc2\xb7 Thinking.)",
        b"\r\x1b[K",
        b"( \xc2\xb7 Seasoning)",
        b"\r\x1b[K",
        b"\x1b[?25h",    # 显示光标
        b"\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81",  # 你好！
    ]

    for raw in raw_outputs:
        text = raw.decode('utf-8', errors='replace')
        buffer.write(text)

    final = buffer.get_content()
    print(f"最终内容: '{final}'")

    # 验证
    if final == "你好！":
        print("✓ 正确！")
    else:
        print(f"✗ 错误，期望 '你好！'")

    print("=" * 60)


if __name__ == "__main__":
    test_real_claude_output()
    test_overwrite_with_spaces()
    test_correct_overwrite()
    test_incremental_output()
    test_animation_without_clear()
    simulate_real_session()
