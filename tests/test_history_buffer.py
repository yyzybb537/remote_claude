#!/usr/bin/env python3
"""
HistoryBuffer 单元测试

测试覆盖：
1. 基本写入和读取
2. 环形缓冲区覆盖逻辑
3. 边界条件（空数据、超大数据、精确满）
4. clear 方法
5. len 方法
"""

import pytest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHistoryBuffer:
    """测试 HistoryBuffer 环形缓冲区"""

    def get_buffer(self, max_size: int = 100):
        """获取 HistoryBuffer 实例"""
        from server.server import HistoryBuffer
        return HistoryBuffer(max_size)

    def test_empty_buffer(self):
        """测试空缓冲区"""
        buf = self.get_buffer(100)
        assert len(buf) == 0
        assert buf.get_all() == b""

    def test_single_append(self):
        """测试单次追加"""
        buf = self.get_buffer(100)
        data = b"hello world"
        buf.append(data)
        assert len(buf) == len(data)
        assert buf.get_all() == data

    def test_multiple_appends(self):
        """测试多次追加"""
        buf = self.get_buffer(100)
        data1 = b"hello "
        data2 = b"world"
        buf.append(data1)
        buf.append(data2)
        assert len(buf) == len(data1) + len(data2)
        assert buf.get_all() == data1 + data2

    def test_append_empty_data(self):
        """测试追加空数据"""
        buf = self.get_buffer(100)
        buf.append(b"hello")
        buf.append(b"")
        assert len(buf) == 5
        assert buf.get_all() == b"hello"

    def test_exact_capacity(self):
        """测试精确填满缓冲区"""
        buf = self.get_buffer(10)
        data = b"0123456789"  # 正好 10 字节
        buf.append(data)
        assert len(buf) == 10
        assert buf.get_all() == data

    def test_overflow_single_append(self):
        """测试单次追加超过容量"""
        buf = self.get_buffer(10)
        data = b"0123456789ABCDEF"  # 16 字节
        buf.append(data)
        # 只保留最后 10 字节
        assert len(buf) == 10
        assert buf.get_all() == b"6789ABCDEF"

    def test_overflow_multiple_appends(self):
        """测试多次追加超过容量"""
        buf = self.get_buffer(10)
        buf.append(b"01234")  # 5 字节
        buf.append(b"56789")  # 5 字节，正好满
        buf.append(b"ABCDEF")  # 6 字节，触发覆盖
        # 总共 16 字节，缓冲区 10 字节，应保留最后 10 字节
        assert len(buf) == 10
        assert buf.get_all() == b"6789ABCDEF"

    def test_ring_buffer_wrap(self):
        """测试环形缓冲区回绕"""
        buf = self.get_buffer(10)
        # 先填充一部分
        buf.append(b"AAAA")  # [AAAA______]
        # 再填充一部分
        buf.append(b"BBBB")  # [AAAABBBB__]
        # 再填充超过容量
        buf.append(b"CCCCCC")  # 应该覆盖最旧的 4 字节
        # 预期：保留最后 10 字节 = "BB" + "CCCCCC" (BBBB 被部分覆盖) + 之前
        # 实际：6 字节 + 已有 8 字节 = 14 字节，保留最后 10 字节
        assert len(buf) == 10
        assert buf.get_all() == b"BBCCCCCC"

    def test_large_overflow_keeps_tail(self):
        """测试大块数据溢出时保留尾部"""
        buf = self.get_buffer(10)
        buf.append(b"hello")
        buf.append(b"X" * 100)  # 100 字节
        assert len(buf) == 10
        assert buf.get_all() == b"X" * 10

    def test_clear(self):
        """测试清空"""
        buf = self.get_buffer(100)
        buf.append(b"hello world")
        buf.clear()
        assert len(buf) == 0
        assert buf.get_all() == b""

    def test_clear_empty_buffer(self):
        """测试清空空缓冲区"""
        buf = self.get_buffer(100)
        buf.clear()
        assert len(buf) == 0
        assert buf.get_all() == b""

    def test_len_after_operations(self):
        """测试各种操作后的长度"""
        buf = self.get_buffer(100)
        assert len(buf) == 0

        buf.append(b"a" * 50)
        assert len(buf) == 50

        buf.append(b"b" * 30)
        assert len(buf) == 80

        buf.append(b"c" * 50)  # 总共 130，超限
        assert len(buf) == 100

        buf.clear()
        assert len(buf) == 0

    def test_sequential_overflow(self):
        """测试连续溢出场景"""
        buf = self.get_buffer(20)
        for i in range(10):
            buf.append(f"{i:02d}".encode())  # 每次追加 2 字节
        # 总共 20 字节，正好填满
        assert len(buf) == 20
        assert buf.get_all() == b"00010203040506070809"

        # 再追加 10 字节，触发覆盖
        buf.append(b"ABCDEFGHIJ")
        assert len(buf) == 20
        # 应保留最后 20 字节
        assert buf.get_all() == b"0506070809ABCDEFGHIJ"

    def test_single_byte_operations(self):
        """测试单字节操作"""
        buf = self.get_buffer(5)
        for i in range(7):
            buf.append(bytes([ord('A') + i]))
        assert len(buf) == 5
        assert buf.get_all() == b"CDEFG"

    def test_append_exactly_double_capacity(self):
        """测试追加恰好两倍容量的数据"""
        buf = self.get_buffer(10)
        data = b"A" * 20  # 正好两倍
        buf.append(data)
        assert len(buf) == 10
        assert buf.get_all() == b"A" * 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
