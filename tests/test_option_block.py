"""
OptionBlock 解析测试 - 验证 AskUserQuestion 选项块正确捕获
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lark_client.session_bridge import SessionBridge
from lark_client.components import OptionBlock, UserInput, TextBlock, StatusLine

got_option_blocks = []
all_components = []

def on_output(components):
    all_components.extend(components)
    for c in components:
        tag = repr(c.tag) if isinstance(c, OptionBlock) else ""
        q = repr(c.question) if isinstance(c, OptionBlock) else ""
        if isinstance(c, OptionBlock):
            got_option_blocks.append(c)
            print(f"  [OptionBlock] tag={tag} question={q}")
            for opt in c.options:
                print(f"    - {opt}")
        elif isinstance(c, StatusLine):
            print(f"  [StatusLine] {c.action}")
        elif isinstance(c, TextBlock):
            print(f"  [TextBlock] {c.content[:80]}")
        elif isinstance(c, UserInput):
            print(f"  [UserInput] {c.text[:80]}")


async def main():
    bridge = SessionBridge("ff", on_output=on_output)
    await bridge.connect()
    print("[测试] 触发 AskUserQuestion...")
    await bridge.send_input(
        "请用 AskUserQuestion 工具问我：你喜欢哪种编程语言？选项是 Python、Go、Rust"
    )
    print("[测试] 等待 40 秒...")
    await asyncio.sleep(40)
    await bridge.disconnect()

    print(f"\n[结果] 共收到 {len(all_components)} 个组件")
    print(f"[结果] OptionBlock 数量: {len(got_option_blocks)}")

    if got_option_blocks:
        print("✓ OptionBlock 解析成功")
        return True
    else:
        print("✗ 未检测到 OptionBlock")
        types = [type(c).__name__ for c in all_components]
        print(f"  收到的组件类型: {types}")
        return False


if __name__ == "__main__":
    ok = asyncio.run(main())
    print("\n" + ("✓ 通过" if ok else "✗ 失败"))
    sys.exit(0 if ok else 1)
