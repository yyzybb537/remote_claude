#!/usr/bin/env python3
"""
选项选择功能单元测试

覆盖：
1. Parser selected_value 检测（ClaudeParser + CodexParser）
2. SharedMemoryPoller.read_snapshot() 方法
3. handle_option_select 闭环控制逻辑
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyte
from pyte.screens import Char


# ── 辅助：构建 pyte Screen ───────────────────────────────────────────────────

def make_screen(rows=50, cols=220):
    return pyte.Screen(cols, rows)


def write_row(screen, row, text, fg='default', bg='default'):
    """将 text 从 col=0 开始写入 screen 的指定行"""
    for col, ch in enumerate(text):
        screen.buffer[row][col] = Char(data=ch, fg=fg, bg=bg)
    for col in range(len(text), screen.columns):
        screen.buffer[row][col] = Char(data=' ', fg=fg, bg=bg)


# ── 1. ClaudeParser selected_value 测试 ─────────────────────────────────────

from server.parsers.claude_parser import ClaudeParser


class TestClaudeParserSelectedValue(unittest.TestCase):

    def setUp(self):
        self.parser = ClaudeParser()

    def _make_input_screen(self, rows_text: list, start_row: int = 5):
        """构建带有选项内容的 screen，返回 (screen, input_rows)"""
        screen = make_screen()
        input_rows = []
        for i, text in enumerate(rows_text):
            r = start_row + i
            write_row(screen, r, text)
            input_rows.append(r)
        return screen, input_rows

    def test_selected_value_set_when_cursor_on_second_option(self):
        """❯ 光标在第 2 个选项上，selected_value 应为 '2'"""
        screen, input_rows = self._make_input_screen([
            '你喜欢哪种编程语言？',
            '1. Python',
            '❯ 2. Go',
            '3. Rust',
            '↑/↓ to navigate · Enter to select',
        ])
        overflow = []
        ob = self.parser._parse_input_area(screen, input_rows, [], overflow)
        self.assertIsNotNone(ob)
        self.assertEqual(ob.selected_value, '2')

    def test_selected_value_set_when_cursor_on_first_option(self):
        """❯ 光标在第 1 个选项上，selected_value 应为 '1'"""
        screen, input_rows = self._make_input_screen([
            '你喜欢哪种编程语言？',
            '❯ 1. Python',
            '2. Go',
            '3. Rust',
            '↑/↓ to navigate · Enter to select',
        ])
        overflow = []
        ob = self.parser._parse_input_area(screen, input_rows, [], overflow)
        self.assertIsNotNone(ob)
        self.assertEqual(ob.selected_value, '1')

    def test_selected_value_empty_when_no_cursor(self):
        """无 ❯ 前缀时，selected_value 应为空字符串"""
        screen, input_rows = self._make_input_screen([
            '你喜欢哪种编程语言？',
            '1. Python',
            '2. Go',
            '❯ to navigate',  # 这行会让 _has_numbered_options 通过（有 ❯），但选项上无 ❯ 前缀
        ])
        # 这种情况下 selected_value 应为空（选项行 "1." 和 "2." 均无 ❯ 前缀）
        overflow = []
        ob = self.parser._parse_input_area(screen, input_rows, [], overflow)
        if ob:
            self.assertEqual(ob.selected_value, '')

    def test_options_parsed_correctly_with_cursor(self):
        """带 ❯ 光标时，选项列表应完整包含所有选项（光标行也应包含）"""
        screen, input_rows = self._make_input_screen([
            'Which do you prefer?',
            '1. Option A',
            '❯ 2. Option B',
            '3. Option C',
            '↑/↓ to navigate · Enter to select',
        ])
        overflow = []
        ob = self.parser._parse_input_area(screen, input_rows, [], overflow)
        self.assertIsNotNone(ob)
        values = [o['value'] for o in ob.options]
        self.assertIn('1', values)
        self.assertIn('2', values)
        self.assertIn('3', values)
        self.assertEqual(ob.selected_value, '2')

    def test_permission_selected_value(self):
        """_parse_permission_area：❯ 前缀选项应写入 selected_value"""
        screen = make_screen()
        bottom_rows = []
        rows_data = [
            ('Bash command', 8),
            ('rm -rf /tmp/test', 9),
            ('Do you want to proceed?', 10),
            ('❯ 1. Yes', 11),
            ('2. No', 12),
        ]
        for text, r in rows_data:
            write_row(screen, r, text)
            bottom_rows.append(r)

        ob = self.parser._parse_permission_area(screen, bottom_rows)
        self.assertIsNotNone(ob)
        self.assertEqual(ob.sub_type, 'permission')
        self.assertEqual(ob.selected_value, '1')

    def test_permission_selected_value_second_option(self):
        """_parse_permission_area：❯ 在第 2 个选项上"""
        screen = make_screen()
        bottom_rows = []
        rows_data = [
            ('Bash command', 8),
            ('rm -rf /tmp/test', 9),
            ('Do you want to proceed?', 10),
            ('1. Yes', 11),
            ('❯ 2. No', 12),
        ]
        for text, r in rows_data:
            write_row(screen, r, text)
            bottom_rows.append(r)

        ob = self.parser._parse_permission_area(screen, bottom_rows)
        self.assertIsNotNone(ob)
        self.assertEqual(ob.selected_value, '2')


# ── 2. CodexParser selected_value 测试 ──────────────────────────────────────

from server.parsers.codex_parser import CodexParser


class TestCodexParserSelectedValue(unittest.TestCase):

    def setUp(self):
        self.parser = CodexParser()

    def test_selected_value_with_lsaquo_cursor(self):
        """Codex › (U+203A) 光标在第 2 个选项上，selected_value 应为 '2'"""
        screen = make_screen()
        input_rows = [5, 6, 7, 8]
        write_row(screen, 5, 'Implement this plan?')
        write_row(screen, 6, '1. Yes, implement this plan')
        write_row(screen, 7, '› 2. No, stay in Plan mode')
        write_row(screen, 8, '↑/↓ to navigate · Enter to select')

        overflow = []
        ob = self.parser._parse_input_area(screen, input_rows, [], overflow)
        self.assertIsNotNone(ob)
        self.assertEqual(ob.selected_value, '2')

    def test_selected_value_with_gt_cursor(self):
        """> (U+003E) 光标在第 1 个选项上，selected_value 应为 '1'"""
        screen = make_screen()
        input_rows = [5, 6, 7, 8]
        write_row(screen, 5, 'Implement this plan?')
        write_row(screen, 6, '> 1. Yes, implement this plan')
        write_row(screen, 7, '2. No, stay in Plan mode')
        write_row(screen, 8, '↑/↓ to navigate · Enter to select')

        overflow = []
        ob = self.parser._parse_input_area(screen, input_rows, [], overflow)
        self.assertIsNotNone(ob)
        self.assertEqual(ob.selected_value, '1')

    def test_selected_value_empty_when_no_cursor_prefix(self):
        """选项行均无 cursor 前缀时，selected_value 应为空"""
        screen = make_screen()
        input_rows = [5, 6, 7, 8]
        write_row(screen, 5, 'Which option?')
        write_row(screen, 6, '1. Option A')
        write_row(screen, 7, '2. Option B')
        write_row(screen, 8, '› to navigate')  # 锚点行但不是选项行

        overflow = []
        ob = self.parser._parse_input_area(screen, input_rows, [], overflow)
        if ob:
            self.assertEqual(ob.selected_value, '')

    def test_permission_selected_value_codex(self):
        """Codex _parse_permission_area：› 前缀选项应写入 selected_value"""
        screen = make_screen()
        bottom_rows = [8, 9, 10, 11, 12]
        write_row(screen, 8, 'Write file')
        write_row(screen, 9, '/tmp/test.txt')
        write_row(screen, 10, 'Do you want to proceed?')
        write_row(screen, 11, '1. Yes')
        write_row(screen, 12, '› 2. No')

        ob = self.parser._parse_permission_area(screen, bottom_rows)
        self.assertIsNotNone(ob)
        self.assertEqual(ob.sub_type, 'permission')
        self.assertEqual(ob.selected_value, '2')


from lark_client.shared_memory_poller import SharedMemoryPoller, StreamTracker, analyze_option_block


def test_selected_value_preferred_when_present():
    """analyze_option_block：selected_value 命中时优先确认当前高亮项"""
    option_block = {
        'question': '继续吗？',
        'selected_value': '2',
        'options': [
            {'label': '1. Yes', 'value': '1'},
            {'label': '2. No', 'value': '2'},
        ],
    }

    action_type, action_value = analyze_option_block(option_block)
    assert action_type == 'select'
    assert action_value == '2'


class TestReadSnapshot(unittest.TestCase):

    def _make_poller(self):
        card_service = MagicMock()
        return SharedMemoryPoller(card_service)

    def test_returns_none_when_no_tracker(self):
        """未知 chat_id → 返回 None"""
        poller = self._make_poller()
        self.assertIsNone(poller.read_snapshot('unknown_chat'))

    def test_returns_none_when_tracker_has_no_reader(self):
        """tracker 无 reader → 返回 None"""
        poller = self._make_poller()
        tracker = StreamTracker(chat_id='c1', session_name='s1')
        tracker.reader = None
        poller._trackers['c1'] = tracker
        self.assertIsNone(poller.read_snapshot('c1'))

    def test_returns_snapshot_when_reader_exists(self):
        """tracker 有 reader → 返回 reader.read() 的结果"""
        poller = self._make_poller()
        mock_reader = MagicMock()
        mock_reader.read.return_value = {'blocks': [], 'option_block': None}
        tracker = StreamTracker(chat_id='c1', session_name='s1')
        tracker.reader = mock_reader
        poller._trackers['c1'] = tracker

        result = poller.read_snapshot('c1')
        self.assertIsNotNone(result)
        self.assertEqual(result['blocks'], [])
        mock_reader.read.assert_called_once()

    def test_returns_none_on_reader_exception(self):
        """reader.read() 抛出异常 → 返回 None，不向外抛"""
        poller = self._make_poller()
        mock_reader = MagicMock()
        mock_reader.read.side_effect = RuntimeError("mmap error")
        tracker = StreamTracker(chat_id='c1', session_name='s1')
        tracker.reader = mock_reader
        poller._trackers['c1'] = tracker

        result = poller.read_snapshot('c1')
        self.assertIsNone(result)


# ── 4. handle_option_select 闭环控制逻辑测试 ─────────────────────────────────

from lark_client.lark_handler import LarkHandler


class TestHandleOptionSelect(unittest.IsolatedAsyncioTestCase):
    """测试 handle_option_select 闭环控制逻辑"""

    def _make_handler_with_mocks(self):
        """构造最小化 LarkHandler 用于测试"""
        handler = LarkHandler.__new__(LarkHandler)
        handler._bridges = {}
        handler._chat_sessions = {}
        handler._poller = MagicMock()
        handler._poller.get_tracker = MagicMock(return_value=None)
        # get_active_card_id 返回 None，跳过 update_card 调用
        handler._poller.get_active_card_id = MagicMock(return_value=None)
        # 添加 _user_config 属性
        handler._user_config = {}
        return handler

    def _make_bridge(self, running=True):
        bridge = MagicMock()
        bridge.running = running
        bridge.send_raw = AsyncMock(return_value=True)
        bridge.send_key = AsyncMock(return_value=True)
        return bridge

    def _make_snapshot(self, selected_value='1', block_id='Q:Which option?'):
        """构造包含 option_block 的 snapshot dict"""
        return {
            'blocks': [],
            'option_block': {
                '_type': 'OptionBlock',
                'sub_type': 'option',
                'selected_value': selected_value,
                'block_id': block_id,
                'options': [{'value': '1', 'label': 'A'}, {'value': '2', 'label': 'B'}],
            }
        }

    async def test_already_at_target_sends_enter(self):
        """当前选中项已是目标 → 直接发 Enter，不发箭头"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge()
        handler._bridges['chat1'] = bridge

        # selected_value == target == '2'
        handler._poller.read_snapshot = MagicMock(return_value=self._make_snapshot('2'))

        await handler.handle_option_select('user1', 'chat1', '2', option_total=3)

        # 应该发了 Enter（\r）
        bridge.send_raw.assert_called_once_with(b"\r")
        handler._poller.kick.assert_called_once_with('chat1')

    async def test_current_below_target_sends_down_arrow(self):
        """current=1 < target=3 → 发 ↓ 箭头"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge()
        handler._bridges['chat1'] = bridge

        # 第一次读取 current=1，第二次读取 current=2，第三次读取 current=3（到位）
        snapshots = [
            self._make_snapshot('1'),  # step 0：读取，未到位，发 ↓
            self._make_snapshot('1'),  # 轮询等待，未变化
            self._make_snapshot('2'),  # 轮询等待，变化了，break
            self._make_snapshot('2'),  # step 1：读取，未到位，发 ↓
            self._make_snapshot('2'),  # 轮询等待，未变化
            self._make_snapshot('3'),  # 轮询等待，变化了，break
            self._make_snapshot('3'),  # step 2：读取，到位，发 Enter
        ]
        handler._poller.read_snapshot = MagicMock(side_effect=snapshots)

        await handler.handle_option_select('user1', 'chat1', '3', option_total=5)

        # 应该发了 2 次 ↓ + 1 次 Enter
        calls = bridge.send_raw.call_args_list
        down_calls = [c for c in calls if c.args[0] == b"\x1b[B"]
        enter_calls = [c for c in calls if c.args[0] == b"\r"]
        self.assertEqual(len(down_calls), 2)
        self.assertEqual(len(enter_calls), 1)

    async def test_current_above_target_sends_up_arrow(self):
        """current=3 > target=1 → 发 ↑ 箭头"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge()
        handler._bridges['chat1'] = bridge

        snapshots = [
            self._make_snapshot('3'),  # step 0：current=3 > target=1，发 ↑
            self._make_snapshot('3'),  # 轮询等待
            self._make_snapshot('2'),  # 变化，break
            self._make_snapshot('2'),  # step 1：current=2 > target=1，发 ↑
            self._make_snapshot('2'),  # 轮询等待
            self._make_snapshot('1'),  # 变化，break
            self._make_snapshot('1'),  # step 2：到位，发 Enter
        ]
        handler._poller.read_snapshot = MagicMock(side_effect=snapshots)

        await handler.handle_option_select('user1', 'chat1', '1', option_total=5)

        calls = bridge.send_raw.call_args_list
        up_calls = [c for c in calls if c.args[0] == b"\x1b[A"]
        enter_calls = [c for c in calls if c.args[0] == b"\r"]
        self.assertEqual(len(up_calls), 2)
        self.assertEqual(len(enter_calls), 1)

    async def test_empty_selected_value_sends_down(self):
        """selected_value 为空（初始状态）→ 发 ↓"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge()
        handler._bridges['chat1'] = bridge

        # 第一次 selected_value 空，发 ↓；第二次到位
        # 闪烁帧重试会消耗额外 snapshot，需要提供足够的空值 snapshot
        snapshots = [
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test', 'options': []}},  # 初始读取
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test', 'options': []}},  # step 0 外层
            # 闪烁帧重试 5 次（全空，所以会发 ↓）
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test'}},
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test'}},
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test'}},
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test'}},
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test'}},
            # 等待变化轮询（发 ↓ 后等待 selected_value 变化）
            {'blocks': [], 'option_block': {'selected_value': '', 'block_id': 'Q:test'}},
            {'blocks': [], 'option_block': {'selected_value': '1', 'block_id': 'Q:test'}},  # 变化
            self._make_snapshot('1', block_id='Q:test'),  # step 1：到位，发 Enter
        ]
        handler._poller.read_snapshot = MagicMock(side_effect=snapshots)

        await handler.handle_option_select('user1', 'chat1', '1', option_total=5)

        calls = bridge.send_raw.call_args_list
        down_calls = [c for c in calls if c.args[0] == b"\x1b[B"]
        enter_calls = [c for c in calls if c.args[0] == b"\r"]
        self.assertGreaterEqual(len(down_calls), 1)
        self.assertEqual(len(enter_calls), 1)

    async def test_option_block_disappears_exits_cleanly(self):
        """option_block 中途消失（CLI 已进入下一状态）→ 干净退出，不发 Enter"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge()
        handler._bridges['chat1'] = bridge

        _gone = {'blocks': [], 'option_block': None}

        # step 0 外层：有 option_block（current=1），发 ↓
        # 内层轮询：option_block 消失 → 内层 break
        # step 1 外层：option_block 仍消失 → 外层 break
        def snapshots_side_effect(chat_id):
            call_count = snapshots_side_effect.count
            snapshots_side_effect.count += 1
            if call_count == 0:
                return self._make_snapshot('1')   # step 0 外层
            return _gone                           # 之后所有调用均返回 None option_block

        snapshots_side_effect.count = 0
        handler._poller.read_snapshot = MagicMock(side_effect=snapshots_side_effect)

        await handler.handle_option_select('user1', 'chat1', '3', option_total=5)

        # 不应该发 Enter
        calls = bridge.send_raw.call_args_list
        enter_calls = [c for c in calls if c.args[0] == b"\r"]
        self.assertEqual(len(enter_calls), 0)

    async def test_no_snapshot_exits_cleanly(self):
        """read_snapshot 返回 None → 干净退出"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge()
        handler._bridges['chat1'] = bridge
        handler._poller.read_snapshot = MagicMock(return_value=None)

        await handler.handle_option_select('user1', 'chat1', '2', option_total=3)

        # 无 send_raw 调用
        bridge.send_raw.assert_not_called()

    async def test_not_connected_sends_error_text(self):
        """未连接时发送错误提示文本"""
        handler = self._make_handler_with_mocks()
        # 不添加 bridge

        with patch('lark_client.lark_handler.card_service') as mock_cs:
            mock_cs.send_text = AsyncMock()
            await handler.handle_option_select('user1', 'chat1', '1')
            mock_cs.send_text.assert_called_once()
            args = mock_cs.send_text.call_args.args
            self.assertIn('chat1', args)

    async def test_bridge_not_running_sends_error_text(self):
        """bridge.running=False 时发送错误提示文本"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge(running=False)
        handler._bridges['chat1'] = bridge

        with patch('lark_client.lark_handler.card_service') as mock_cs:
            mock_cs.send_text = AsyncMock()
            await handler.handle_option_select('user1', 'chat1', '1')
            mock_cs.send_text.assert_called_once()

    async def test_block_id_change_aborts_selection(self):
        """block_id 变化（第二个选项弹出）时中止导航，不发 Enter"""
        handler = self._make_handler_with_mocks()
        bridge = self._make_bridge()
        handler._bridges['chat1'] = bridge

        # 初始读取（block_id 记录阶段）：第一个 option_block
        # step 0 外层：current=1 != target=2，发 ↓
        # 内层轮询：block_id 变成 Q:Second option?（第二个 option_block 出现）→ break
        # step 1 外层：block_id != initial_block_id → break（不发 Enter）
        snapshots = [
            self._make_snapshot('1', block_id='Q:First option?'),   # 初始读取
            self._make_snapshot('1', block_id='Q:First option?'),   # step 0 外层
            self._make_snapshot('1', block_id='Q:First option?'),   # 内层轮询
            self._make_snapshot('2', block_id='Q:Second option?'),  # block_id 变化，内层 break
            self._make_snapshot('2', block_id='Q:Second option?'),  # step 1 外层，block_id 不一致，外层 break
        ]
        handler._poller.read_snapshot = MagicMock(side_effect=snapshots)

        await handler.handle_option_select('user1', 'chat1', '2', option_total=3)

        # 不应该发 Enter
        calls = bridge.send_raw.call_args_list
        enter_calls = [c for c in calls if c.args[0] == b"\r"]
        self.assertEqual(len(enter_calls), 0)


# ── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    unittest.main(verbosity=2)
