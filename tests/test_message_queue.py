"""
MessageQueue + on_complete 集成测试

验证：
1. on_complete 在 Claude 回复完成后触发
2. server 写入的 debug 文件存在且有内容（验证 server 端 MessageQueue 正常工作）
"""

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lark_client.session_bridge import SessionBridge

SESSION_NAME = "ff"
DEBUG_FILE = f"/tmp/remote-claude/{SESSION_NAME}_messages.log"
TIMEOUT = 60

results = {
    "on_complete_fired": False,
    "on_complete_count": 0,
    "outputs_received": 0,
}


async def main():
    print(f"[测试] 连接到会话 {SESSION_NAME}...")

    complete_event = asyncio.Event()

    def on_output(components):
        results["outputs_received"] += 1
        print(f"  [output #{results['outputs_received']}] {len(components)} 个组件")

    def on_complete():
        results["on_complete_fired"] = True
        results["on_complete_count"] += 1
        print(f"  [on_complete] 触发！count={results['on_complete_count']}")
        complete_event.set()

    bridge = SessionBridge(SESSION_NAME, on_output=on_output, on_complete=on_complete)

    if not await bridge.connect():
        print("✗ 连接失败")
        return False

    # 清空旧的 debug 文件，确保是本次测试写的
    if os.path.exists(DEBUG_FILE):
        os.unlink(DEBUG_FILE)

    print("[测试] 发送测试问题...")
    await bridge.send_input("请用一句话回答：1+1等于几？")

    print(f"[测试] 等待 Claude 完成（最多 {TIMEOUT} 秒）...")
    try:
        await asyncio.wait_for(complete_event.wait(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        print(f"✗ 超时：{TIMEOUT} 秒内未触发 on_complete")
        await bridge.disconnect()
        return False

    # 多等 1 秒，让 server 的 OutputWatcher 也完成写入
    await asyncio.sleep(1.0)
    await bridge.disconnect()

    print("\n[验证]")
    ok = True

    # 1. on_complete 触发
    if results["on_complete_fired"]:
        print(f"✓ on_complete 触发了 {results['on_complete_count']} 次")
    else:
        print("✗ on_complete 未触发")
        ok = False

    # 2. server 写的 debug 文件存在
    if os.path.exists(DEBUG_FILE):
        size = os.path.getsize(DEBUG_FILE)
        print(f"✓ server debug 文件存在：{DEBUG_FILE}（{size} 字节）")
        content = open(DEBUG_FILE).read()
        print("\n--- debug 文件内容 ---")
        print(content)
        print("--- end ---")
        if "complete" in content:
            print("✓ debug 文件包含 complete 状态")
        else:
            print("✗ debug 文件中没有 complete 状态")
            ok = False
    else:
        print(f"✗ server debug 文件不存在：{DEBUG_FILE}")
        print("  （server 端 OutputWatcher 未正常工作）")
        ok = False

    return ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    print("\n" + ("✓ 全部通过" if ok else "✗ 测试失败"))
    sys.exit(0 if ok else 1)
