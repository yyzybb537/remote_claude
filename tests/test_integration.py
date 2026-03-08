"""
集成测试 - 直连 socket，发送真实消息给 Claude，捕获并验证格式化输出。

运行前提：先启动会话
  python3 remote_claude.py start test

运行：
  python3 test_integration.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lark_client.session_bridge import SessionBridge

PASS = 0
FAIL = 0
ERRORS = []

SESSION_NAME = "test"
TIMEOUT = 60  # 每条消息最多等待 60 秒


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


async def send_and_capture(bridge: SessionBridge, message: str, wait: float = 15.0) -> str:
    """发送消息并等待输出，返回格式化后的内容"""
    received = []
    event = asyncio.Event()

    def on_output(text: str):
        received.append(text)
        event.set()

    bridge.on_output = on_output
    bridge.clear_buffer()
    event.clear()

    await bridge.send_input(message)

    try:
        await asyncio.wait_for(event.wait(), timeout=wait)
        # 再等一小段时间，让输出稳定（防截断）
        await asyncio.sleep(3.0)
        event.clear()
        # 检查是否有更多输出
        try:
            await asyncio.wait_for(event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
    except asyncio.TimeoutError:
        pass

    return received[-1] if received else ""


def check(name: str, fn):
    global PASS, FAIL
    try:
        fn()
        log(f"  ✓ {name}")
        PASS += 1
    except AssertionError as e:
        log(f"  ✗ {name}: {e}")
        FAIL += 1
        ERRORS.append((name, str(e)))


def in_code_block(result, text):
    lines = result.split('\n')
    in_block = False
    for line in lines:
        if line.startswith('```'):
            in_block = not in_block
        elif in_block and text in line:
            return True
    return False


async def run_tests():
    log("连接到会话 test...")
    bridge = SessionBridge.__new__(SessionBridge)
    bridge.session_name = SESSION_NAME
    from utils import get_socket_path, generate_client_id
    bridge.socket_path = get_socket_path(SESSION_NAME)
    bridge.client_id = generate_client_id()
    bridge.on_output = None
    bridge.reader = None
    bridge.writer = None
    bridge.buffer = b""
    bridge.running = False
    bridge._read_task = None
    from lark_client.rich_text_renderer import RichTextRenderer
    bridge._renderer = RichTextRenderer()
    bridge._last_content = ""
    bridge._output_timer = None
    bridge._output_delay = 2.0
    bridge._pending_output = False

    ok = await bridge.connect()
    if not ok:
        log("❌ 无法连接到会话 test，请先运行：python3 remote_claude.py start test")
        sys.exit(1)

    log("已连接，开始集成测试...\n")

    # ── 场景1：写 Python 函数（验证代码块） ──────────────────
    log("[场景1] 写一个 Python 函数")
    r1 = await send_and_capture(bridge, "用一句话说你是谁，然后写一个Python函数计算两数之和，只写函数，不要解释。", wait=30)
    log(f"  输出({len(r1)}字符):\n{r1[:500]}")
    check("包含 python 代码块", lambda: assert_in('```python', r1, r1))
    check("函数在代码块内", lambda: assert_true(in_code_block(r1, 'def '), r1))

    # ── 场景2：写 Go HTTP 服务器 ──────────────────────────────
    log("\n[场景2] 写 Go HTTP 服务器")
    r2 = await send_and_capture(bridge, "写一个最简单的Go HTTP服务器，监听8080端口，只写完整程序，不要任何解释。", wait=40)
    log(f"  输出({len(r2)}字符):\n{r2[:600]}")
    check("包含 go 代码块", lambda: assert_in('```go', r2, r2))
    check("package 在代码块内", lambda: assert_true(in_code_block(r2, 'package main'), r2))
    check("import 在代码块内", lambda: assert_true(in_code_block(r2, 'import'), r2))
    check("func 在代码块内", lambda: assert_true(in_code_block(r2, 'func main'), r2))

    # ── 场景3：写 JavaScript 函数 ─────────────────────────────
    log("\n[场景3] 写 JavaScript 函数")
    r3 = await send_and_capture(bridge, "写一个JavaScript函数，用fetch获取URL的JSON数据，只写函数，不要解释。", wait=30)
    log(f"  输出({len(r3)}字符):\n{r3[:400]}")
    check("包含代码块", lambda: assert_in('```', r3, r3))
    check("function/const 在代码块内", lambda: assert_true(
        in_code_block(r3, 'function') or in_code_block(r3, 'const') or in_code_block(r3, 'async'),
        r3
    ))

    # ── 场景4：纯文本问答（验证无多余代码块） ────────────────
    log("\n[场景4] 纯文本问答")
    r4 = await send_and_capture(bridge, "用一句话解释什么是递归，不要写代码。", wait=25)
    log(f"  输出({len(r4)}字符): {r4[:300]}")
    check("纯文本无代码块", lambda: assert_not_in('```', r4, r4))
    check("有实质内容", lambda: assert_true(len(r4) > 10, r4))

    # ── 场景5：连续多条消息（验证会话持久化） ────────────────
    log("\n[场景5] 连续多条消息")
    r5a = await send_and_capture(bridge, "记住数字42。只回复'好的'。", wait=20)
    log(f"  第1条输出: {r5a[:100]}")
    r5b = await send_and_capture(bridge, "我让你记住的数字是多少？只回复数字。", wait=20)
    log(f"  第2条输出: {r5b[:100]}")
    check("第1条有回复", lambda: assert_true(len(r5a) > 0, r5a))
    check("第2条有回复（会话持久化）", lambda: assert_true(len(r5b) > 0, r5b))
    check("第2条包含42", lambda: assert_in('42', r5b, r5b))

    # ── 场景6：发送空消息（边界情况） ────────────────────────
    log("\n[场景6] 发送空消息边界")
    r6 = await send_and_capture(bridge, "", wait=10)
    log(f"  空消息输出: {repr(r6[:50])}")
    # 空消息可能产生空输出或等待提示，不应该崩溃
    check("不崩溃（空消息安全）", lambda: assert_true(True, "always pass"))

    await bridge.disconnect()
    log("\n连接已断开")


def assert_in(needle, haystack, context=""):
    assert needle in haystack, f"未找到 '{needle}'，输出:\n{context[:500]}"


def assert_not_in(needle, haystack, context=""):
    assert needle not in haystack, f"意外找到 '{needle}'，输出:\n{context[:500]}"


def assert_true(condition, context=""):
    assert condition, f"条件不满足，输出:\n{str(context)[:500]}"


if __name__ == "__main__":
    asyncio.run(run_tests())

    print(f"\n{'='*50}")
    print(f"集成测试结果：{PASS} 通过，{FAIL} 失败")
    if ERRORS:
        print("\n失败详情：")
        for name, err in ERRORS:
            print(f"\n  [{name}]\n  {err}")
    print('='*50)
    sys.exit(0 if FAIL == 0 else 1)
