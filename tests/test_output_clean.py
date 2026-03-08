"""
测试输出清理逻辑 - 包含真实的测试数据
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入实际的清理函数
from lark_client.session_bridge import SessionBridge

# 创建一个 mock 的 bridge 用于测试
bridge = SessionBridge("test", lambda x: None)

# 测试数据
TEST_OUTPUTS = [
    # 测试1: 真实的多轮对话输出（包含 [?2026h 等）
    b"""[?2026h
\xe4\xbd\xa0\xe5\xa5\xbd
[?2026l[?2026h
[?2026l[?2026h
\xe4\xbd\xa0\xe5\xa5\xbd[?2026l[?2026h
ddl
[?2026l[?2026h
ddl
[?2026l[?2026h
[?2026l[?2026h
F
[?2026l[?2026h
i
[?2026l[?2026h
d
[?2026l[?2026h
Fd
[?2026l[?2026h
il
[?2026l[?2026h
de
[?2026l[?2026h
d-
[?2026l[?2026h
\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe8\xaf\xb7\xe9\x97\xae\xe6\x9c\x89\xe4\xbb\x80\xe4\xb9\x88\xe9\x9c\x80\xe8\xa6\x81\xe5\xb8\xae\xe5\xbf\x99\xe7\x9a\x84\xef\xbc\x9f
[?2026l[?2026h
al
[?2026l[?2026h
[?2026l
""",

    # 测试2: 包含 Seasoning 动画
    b"""[?2026h
1+1\xe7\xad\x89\xe4\xba\x8e\xe5\x87\xa0?
[?2026l[?2026h
[?2026l[?2026h
1+1\xe7\xad\x89\xe4\xba\x8e\xe5\x87\xa0?;153;153;153m
[?2026l[?2026h
[?2026l[?2026h
S
[?2026l[?2026h
e
[?2026l[?2026h
a
[?2026l[?2026h
Ss
[?2026l[?2026h
eo
[?2026l[?2026h
an
[?2026l[?2026h
si
[?2026l[?2026h
on
[?2026l[?2026h
ng
[?2026l[?2026h
1 + 1 = 2
[?2026l[?2026h
[?2026l
""",

    # 测试3: 包含代码回复
    b"""[?2026h
[?2026l[?2026h
S
[?2026l[?2026h
e
[?2026l[?2026h
a
[?2026l[?2026h
Ss
[?2026l[?2026h
eo
[?2026l[?2026h
an
[?2026l[?2026h
si
[?2026l[?2026h
on
[?2026l[?2026h
ng
[?2026l[?2026h
print("Hello, World!")
\xe5\xa6\x82\xe6\x9e\x9c\xe9\x9c\x80\xe8\xa6\x81\xe6\x88\x91\xe5\x88\x9b\xe5\xbb\xba\xe4\xb8\x80\xe4\xb8\xaa\xe6\x96\x87\xe4\xbb\xb6\xef\xbc\x8c\xe8\xaf\xb7\xe5\x91\x8a\xe8\xaf\x89\xe6\x88\x91\xe3\x80\x82[?2026l[?2026h
[?2026l
""",

    # 测试4: 正常的中文回复
    b"""\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe6\x9c\x89\xe4\xbb\x80\xe4\xb9\x88\xe5\x8f\xaf\xe4\xbb\xa5\xe5\xb8\xae\xe4\xbd\xa0\xe7\x9a\x84\xe5\x90\x97\xef\xbc\x9f""",
]

EXPECTED = [
    "你好！请问有什么需要帮忙的？",  # 测试1
    "1 + 1 = 2",  # 测试2
    "print(\"Hello, World!\")\n如果需要我创建一个文件，请告诉我。",  # 测试3
    "你好！有什么可以帮你的吗？",  # 测试4
]


def test_clean_output():
    """测试输出清理"""
    print("=" * 60)
    print("输出清理测试（使用真实数据）")
    print("=" * 60)

    all_passed = True

    for i, test_input in enumerate(TEST_OUTPUTS, 1):
        print(f"\n--- 测试 {i} ---")
        print(f"原始输入 ({len(test_input)} 字节)")

        cleaned = bridge._clean_output(test_input)
        print(f"清理后 ({len(cleaned)} 字符):")
        print(cleaned if cleaned else "(空)")

        if i <= len(EXPECTED):
            expected = EXPECTED[i-1]
            if cleaned == expected:
                print("✓ 符合预期")
            else:
                print(f"✗ 不符合预期")
                print(f"  预期: {repr(expected)}")
                print(f"  实际: {repr(cleaned)}")
                all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("所有测试通过!")
    else:
        print("部分测试未通过，需要继续调整")

    return all_passed


if __name__ == "__main__":
    test_clean_output()
