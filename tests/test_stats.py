#!/usr/bin/env python3
"""
stats 模块单元测试

覆盖：
- StatsCollector：track / flush / SQLite 写入
- StatsQuery：query_summary / reset_stats
- machine.get_machine_id：持久化 UUID
"""

import os
import sys
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))


class TestMachineId(unittest.TestCase):
    def test_machine_id_is_uuid_format(self):
        from stats.machine import get_machine_id
        mid = get_machine_id()
        self.assertRegex(mid, r'^[0-9a-f-]{36}$')

    def test_machine_id_persistent(self):
        from stats.machine import get_machine_id
        id1 = get_machine_id()
        id2 = get_machine_id()
        self.assertEqual(id1, id2)

    def test_get_machine_info(self):
        from stats.machine import get_machine_info
        info = get_machine_info()
        self.assertIn('hostname', info)
        self.assertIn('os', info)


class TestStatsCollector(unittest.TestCase):
    def setUp(self):
        # 使用临时数据库
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test_stats.db"
        # 替换 _DB_PATH
        import stats.collector as _mod
        self._orig_db_path = _mod._DB_PATH
        self._orig_db_dir = _mod._DB_DIR
        _mod._DB_PATH = self.db_path
        _mod._DB_DIR = self.db_path.parent

    def tearDown(self):
        import stats.collector as _mod
        _mod._DB_PATH = self._orig_db_path
        _mod._DB_DIR = self._orig_db_dir
        # 清理
        if self.db_path.exists():
            self.db_path.unlink()

    def _make_collector(self):
        from stats.collector import StatsCollector
        return StatsCollector(enabled=True)

    def test_track_and_flush_to_sqlite(self):
        c = self._make_collector()
        c.track('session', 'start', session_name='mywork')
        c.track('lark', 'message', chat_id='chat1234', value=1)
        c._flush()

        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("SELECT category, event FROM events ORDER BY id").fetchall()
        conn.close()
        c.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ('session', 'start'))
        self.assertEqual(rows[1], ('lark', 'message'))

    def test_chat_id_truncated_to_8(self):
        c = self._make_collector()
        c.track('lark', 'message', chat_id='chat_id_very_long_12345')
        c._flush()

        conn = sqlite3.connect(str(self.db_path))
        row = conn.execute("SELECT chat_id FROM events").fetchone()
        conn.close()
        c.close()

        self.assertEqual(len(row[0]), 8)

    def test_disabled_collector_no_writes(self):
        from stats.collector import StatsCollector
        c = StatsCollector(enabled=False)
        c.track('session', 'start', session_name='x')
        # 不调用 _flush，检查队列为空
        self.assertEqual(len(c._queue), 0)

    def test_track_is_nonblocking(self):
        """track() 本质上只是 deque.append，应在 1ms 内返回"""
        c = self._make_collector()
        start = time.perf_counter()
        for _ in range(100):
            c.track('card', 'update', session_name='s', chat_id='c')
        elapsed = time.perf_counter() - start
        c.close()
        self.assertLess(elapsed, 0.1)  # 100 次 track 应 <100ms

    def test_session_end_value(self):
        """session.end 的 value 应为持续秒数（整数）"""
        c = self._make_collector()
        c.track('session', 'end', session_name='s', value=3600)
        c._flush()

        conn = sqlite3.connect(str(self.db_path))
        row = conn.execute("SELECT value FROM events WHERE event='end'").fetchone()
        conn.close()
        c.close()

        self.assertEqual(row[0], 3600)


class TestStatsQuery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test_stats.db"
        import stats.collector as _col
        import stats.query as _qry
        self._orig_col_path = _col._DB_PATH
        self._orig_col_dir = _col._DB_DIR
        self._orig_qry_path = _qry._DB_PATH
        _col._DB_PATH = self.db_path
        _col._DB_DIR = self.db_path.parent
        _qry._DB_PATH = self.db_path

    def tearDown(self):
        import stats.collector as _col
        import stats.query as _qry
        _col._DB_PATH = self._orig_col_path
        _col._DB_DIR = self._orig_col_dir
        _qry._DB_PATH = self._orig_qry_path
        if self.db_path.exists():
            self.db_path.unlink()

    def _seed(self):
        from stats.collector import StatsCollector
        c = StatsCollector(enabled=True)
        c.track('session', 'start', session_name='w1')
        c.track('lark', 'message', chat_id='abc123', session_name='w1')
        c.track('lark', 'message', chat_id='abc123', session_name='w1')
        c.track('card', 'update', session_name='w1', chat_id='abc123')
        c.track('error', 'card_api', detail='create_card')
        c._flush()
        c.close()

    def test_query_summary_today(self):
        self._seed()
        from stats.query import query_summary
        output = query_summary(range_str='today')
        self.assertIn('Remote Claude', output)
        self.assertIn('会话:', output)
        self.assertIn('飞书:', output)
        self.assertIn('卡片:', output)

    def test_query_summary_no_data(self):
        from stats.query import query_summary
        output = query_summary(range_str='today')
        # 无数据库时返回提示，有数据库但无数据时返回全 0 的摘要
        self.assertTrue('暂无统计数据' in output or '0' in output)

    def test_reset_stats(self):
        self._seed()
        from stats.query import reset_stats, query_summary
        reset_stats()
        # 重置后查询结果应只包含 0
        output = query_summary(range_str='today')
        # session start 应为 0
        self.assertIn('启动 0', output)

    def test_query_with_session_filter(self):
        self._seed()
        from stats.query import query_summary
        # 存在的 session
        out_w1 = query_summary(range_str='today', session_name='w1')
        self.assertIn('Remote Claude', out_w1)
        # 不存在的 session
        out_w2 = query_summary(range_str='today', session_name='nonexistent')
        self.assertIn('启动 0', out_w2)

    def test_query_detail_flag(self):
        self._seed()
        from stats.query import query_summary
        output = query_summary(range_str='today', detail=True)
        self.assertIn('详细分类', output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
