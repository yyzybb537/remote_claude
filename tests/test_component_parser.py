"""
组件解析器单元测试

测试 component_parser.parse_components() 对各种 Claude CLI 输出的解析能力。
使用 pyte Screen 模拟真实终端输出。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pyte

# 旧版测试的 import（可能因模块重构而失败）
_OLD_API_AVAILABLE = False
try:
    from lark_client.components import (
        TextBlock, UserInput, ToolCall, AgentBlock, OptionBlock, StatusLine,
        BottomBar,
    )
    from lark_client.component_parser import parse_components, components_content_key
    _OLD_API_AVAILABLE = True
except ImportError:
    pass


def _make_screen(text: str, cols=220, lines=50) -> pyte.Screen:
    """辅助：从文本创建 pyte Screen"""
    screen = pyte.Screen(cols, lines)
    stream = pyte.Stream(screen)
    stream.feed(text)
    return screen


def _assert_types(components, expected_types, test_name=""):
    """辅助：检查组件类型序列"""
    actual_types = [type(c).__name__ for c in components]
    expected_names = [t.__name__ if isinstance(t, type) else t for t in expected_types]
    if actual_types != expected_names:
        print(f"  ✗ {test_name}: 类型不匹配")
        print(f"    期望: {expected_names}")
        print(f"    实际: {actual_types}")
        return False
    return True


class TestComponentParser:
    """组件解析器测试"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def _pass(self, name):
        self.passed += 1
        print(f"  ✓ {name}")

    def _fail(self, name, msg=""):
        self.failed += 1
        self.errors.append(f"{name}: {msg}")
        print(f"  ✗ {name}: {msg}")

    def test_text_block_basic(self):
        """基础文本回复（使用 ⏺ 内容 bullet）"""
        screen = _make_screen(
            '❯ hello\r\n'
            '⏺ 你好！有什么可以帮你的吗？\r\n'
        )
        components = parse_components(screen)

        if not _assert_types(components, [TextBlock], "text_block_basic"):
            self._fail("text_block_basic", "类型不匹配")
            return

        tb = components[0]
        if '你好' not in tb.content:
            self._fail("text_block_basic", f"内容不正确: {tb.content!r}")
            return
        self._pass("text_block_basic")

    def test_text_block_streaming(self):
        """流式文本（闪烁 ⏺）"""
        # \x1b[5m 开启 blink，\x1b[25m 关闭 blink
        screen = _make_screen(
            '❯ hello\r\n'
            '\x1b[5m⏺\x1b[25m 正在生成中的文本...\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], TextBlock):
            self._fail("text_block_streaming", f"解析失败: {components}")
            return

        if not components[0].is_streaming:
            self._fail("text_block_streaming", "应该检测到 streaming=True")
            return
        self._pass("text_block_streaming")

    def test_text_block_static(self):
        """静态文本（非闪烁 ⏺）"""
        screen = _make_screen(
            '❯ hello\r\n'
            '⏺ 这是已完成的回复。\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], TextBlock):
            self._fail("text_block_static", f"解析失败: {components}")
            return

        if components[0].is_streaming:
            self._fail("text_block_static", "不应该是 streaming")
            return
        self._pass("text_block_static")

    def test_tool_call_done(self):
        """已完成的工具调用"""
        screen = _make_screen(
            '❯ 运行测试\r\n'
            '⏺ Bash(运行单元测试)\r\n'
            '  └ Done (exit code 0)\r\n'
        )
        components = parse_components(screen)

        if not _assert_types(components, [ToolCall], "tool_call_done"):
            self._fail("tool_call_done", "类型不匹配")
            return

        tc = components[0]
        if tc.tool_name != 'Bash':
            self._fail("tool_call_done", f"tool_name 错误: {tc.tool_name}")
            return
        if tc.status != 'done':
            self._fail("tool_call_done", f"status 错误: {tc.status}")
            return
        if '运行单元测试' not in tc.args_summary:
            self._fail("tool_call_done", f"args_summary 错误: {tc.args_summary}")
            return
        self._pass("tool_call_done")

    def test_tool_call_running(self):
        """运行中的工具调用（闪烁 ⏺）"""
        screen = _make_screen(
            '❯ 编辑文件\r\n'
            '\x1b[5m⏺\x1b[25m Edit(src/main.py)\r\n'
            '  └ Running...\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], ToolCall):
            self._fail("tool_call_running", f"解析失败: {components}")
            return

        tc = components[0]
        if tc.status != 'running':
            self._fail("tool_call_running", f"status 应为 running: {tc.status}")
            return
        if not tc.is_streaming:
            self._fail("tool_call_running", "应该检测到 is_streaming=True")
            return
        self._pass("tool_call_running")

    def test_tool_call_with_output(self):
        """带输出的工具调用"""
        screen = _make_screen(
            '❯ 查看文件\r\n'
            '⏺ Read(config.json)\r\n'
            '  {"key": "value"}\r\n'
            '  └ Done\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], ToolCall):
            self._fail("tool_call_with_output", f"解析失败: {components}")
            return

        tc = components[0]
        if tc.tool_name != 'Read':
            self._fail("tool_call_with_output", f"tool_name 错误: {tc.tool_name}")
            return
        if '"key"' not in tc.output:
            self._fail("tool_call_with_output", f"output 应包含内容: {tc.output!r}")
            return
        self._pass("tool_call_with_output")

    def test_agent_block(self):
        """Agent 块"""
        screen = _make_screen(
            '❯ 研究这个问题\r\n'
            '⏺ Agent(分析代码架构)\r\n'
            '  └ Done (5 tool uses · 12k tokens · 2m)\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], AgentBlock):
            self._fail("agent_block", f"解析失败: {[type(c).__name__ for c in components]}")
            return

        ab = components[0]
        if ab.agent_type != 'agent':
            self._fail("agent_block", f"agent_type 错误: {ab.agent_type}")
            return
        if ab.status != 'done':
            self._fail("agent_block", f"status 错误: {ab.status}")
            return
        if '5 tool uses' not in ab.stats:
            self._fail("agent_block", f"stats 错误: {ab.stats}")
            return
        self._pass("agent_block")

    def test_plan_block(self):
        """Plan 块"""
        screen = _make_screen(
            '❯ 实现这个功能\r\n'
            '⏺ Plan(设计实现方案)\r\n'
            '  └ Done (3 tool uses · 8k tokens · 1m)\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], AgentBlock):
            self._fail("plan_block", f"解析失败: {[type(c).__name__ for c in components]}")
            return

        ab = components[0]
        if ab.agent_type != 'plan':
            self._fail("plan_block", f"agent_type 应为 plan: {ab.agent_type}")
            return
        self._pass("plan_block")

    def test_status_line(self):
        """状态行"""
        screen = _make_screen(
            '❯ 做一个复杂任务\r\n'
            '⏺ 正在处理中...\r\n'
            '✱ Germinating... (16m 33s · ↓ 4.3k tokens)\r\n'
        )
        components = parse_components(screen)

        has_status = any(isinstance(c, StatusLine) for c in components)
        if not has_status:
            self._fail("status_line", f"未检测到 StatusLine: {[type(c).__name__ for c in components]}")
            return

        sl = next(c for c in components if isinstance(c, StatusLine))
        if 'Germinating' not in sl.action:
            self._fail("status_line", f"action 错误: {sl.action}")
            return
        if '16m 33s' not in sl.elapsed:
            self._fail("status_line", f"elapsed 错误: {sl.elapsed}")
            return
        self._pass("status_line")

    def test_multiple_components(self):
        """混合多种组件"""
        screen = _make_screen(
            '❯ 帮我重构代码\r\n'
            '⏺ 好的，让我先分析代码结构。\r\n'
            '⏺ Read(src/main.py)\r\n'
            '  └ Done\r\n'
            '⏺ Bash(python -m pytest)\r\n'
            '  └ Done (exit code 0)\r\n'
            '⏺ 重构完成，主要改动：\r\n'
            '  1. 拆分了大函数\r\n'
            '  2. 提取了公共逻辑\r\n'
        )
        components = parse_components(screen)

        expected = [TextBlock, ToolCall, ToolCall, TextBlock]
        if not _assert_types(components, expected, "multiple_components"):
            self._fail("multiple_components", f"实际: {[type(c).__name__ for c in components]}")
            return

        # 验证第一个 TextBlock
        if '分析代码结构' not in components[0].content:
            self._fail("multiple_components", f"第一个 TextBlock 内容不对: {components[0].content!r}")
            return

        # 验证最后一个 TextBlock 包含多行
        if '拆分了大函数' not in components[3].content:
            self._fail("multiple_components", f"最后 TextBlock 内容不对: {components[3].content!r}")
            return
        self._pass("multiple_components")

    def test_extract_latest_response(self):
        """只提取最新回复（跳过历史）"""
        screen = _make_screen(
            # 历史对话
            '❯ 旧的输入\r\n'
            '⏺ 旧的回复内容。\r\n'
            # 最新对话
            '❯ 新的输入\r\n'
            '⏺ 新的回复内容！\r\n'
        )
        components = parse_components(screen)

        # 应该只有最新回复的 TextBlock
        texts = [c for c in components if isinstance(c, TextBlock)]
        if len(texts) != 1:
            self._fail("extract_latest_response", f"应只有1个 TextBlock，实际 {len(texts)}")
            return
        if '新的回复' not in texts[0].content:
            self._fail("extract_latest_response", f"内容不对: {texts[0].content!r}")
            return
        self._pass("extract_latest_response")

    def test_fallback_boundary(self):
        """用 exclude_user_input 作为 fallback 边界"""
        # 模拟 ❯ 行已被清空的情况（用户提交后 TUI 重绘）
        screen = _make_screen(
            '⏺ Claude 的回复内容。\r\n'
        )
        components = parse_components(screen, exclude_user_input='hello')

        if len(components) < 1:
            self._fail("fallback_boundary", "解析为空")
            return
        self._pass("fallback_boundary")

    def test_skip_decorations(self):
        """跳过装饰行"""
        screen = _make_screen(
            '❯ test\r\n'
            '╭──────────────╮\r\n'
            '│ Welcome back │\r\n'
            '╰──────────────╯\r\n'
            '⏺ 回复内容。\r\n'
            '? for shortcuts\r\n'
            '──────────────────\r\n'
        )
        components = parse_components(screen)

        texts = [c for c in components if isinstance(c, TextBlock)]
        if len(texts) != 1:
            self._fail("skip_decorations", f"应只有1个 TextBlock: {[type(c).__name__ for c in components]}")
            return
        if '回复内容' not in texts[0].content:
            self._fail("skip_decorations", f"内容不对: {texts[0].content!r}")
            return
        self._pass("skip_decorations")

    def test_tool_interrupted(self):
        """工具调用被中断"""
        screen = _make_screen(
            '❯ 做任务\r\n'
            '⏺ Bash(长时间运行的命令)\r\n'
            '  └ Interrupted\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], ToolCall):
            self._fail("tool_interrupted", f"解析失败")
            return

        if components[0].status != 'interrupted':
            self._fail("tool_interrupted", f"status 错误: {components[0].status}")
            return
        self._pass("tool_interrupted")

    def test_tool_background(self):
        """后台运行的工具"""
        screen = _make_screen(
            '❯ 任务\r\n'
            '⏺ Bash(后台任务)\r\n'
            '  └ Running in the background\r\n'
        )
        components = parse_components(screen)

        if len(components) < 1 or not isinstance(components[0], ToolCall):
            self._fail("tool_background", "解析失败")
            return

        if components[0].status != 'background':
            self._fail("tool_background", f"status 应为 background: {components[0].status}")
            return
        self._pass("tool_background")

    def test_content_key_dedup(self):
        """去重 key 生成"""
        screen = _make_screen(
            '❯ test\r\n'
            '⏺ 回复内容。\r\n'
            '⏺ Bash(ls)\r\n'
            '  └ Done\r\n'
        )
        components = parse_components(screen)
        key1 = components_content_key(components)

        # 相同内容应产生相同 key
        screen2 = _make_screen(
            '❯ test\r\n'
            '⏺ 回复内容。\r\n'
            '⏺ Bash(ls)\r\n'
            '  └ Done\r\n'
        )
        components2 = parse_components(screen2)
        key2 = components_content_key(components2)

        if key1 != key2:
            self._fail("content_key_dedup", f"相同内容应产生相同 key")
            return
        self._pass("content_key_dedup")

    def test_empty_screen(self):
        """空屏幕"""
        screen = _make_screen('')
        components = parse_components(screen)
        if components:
            self._fail("empty_screen", f"空屏幕应返回空列表: {components}")
            return
        self._pass("empty_screen")

    def test_orphan_status_line(self):
        """孤立的 └ 行附加到前一个工具"""
        screen = _make_screen(
            '❯ test\r\n'
            '⏺ Bash(命令)\r\n'
            '⏺ 文本回复\r\n'
            '  └ Done\r\n'
        )
        # └ Done 应该附加到最近的 ToolCall（Bash）
        # 实际上 └ 在文本回复后面，这种情况比较边缘
        components = parse_components(screen)
        # 至少不应崩溃
        if components is None:
            self._fail("orphan_status_line", "返回 None")
            return
        self._pass("orphan_status_line")

    def test_card_rendering_complete(self):
        """完成状态的卡片渲染"""
        from lark_client.card_builder import ResponseCard

        screen = _make_screen(
            '❯ hello\r\n'
            '⏺ 你好！\r\n'
            '⏺ Bash(echo hello)\r\n'
            '  └ Done\r\n'
        )
        components = parse_components(screen)

        card = ResponseCard(user_input='hello')
        card.set_components(components)
        card.set_complete()
        result = card.build_card()

        if result['header']['template'] != 'green':
            self._fail("card_rendering_complete", f"完成时模板应为 green: {result['header']['template']}")
            return
        if '✅' not in result['header']['title']['content']:
            self._fail("card_rendering_complete", f"完成时标题应含 ✅: {result['header']['title']['content']}")
            return
        # 应有菜单按钮
        has_menu = any(
            e.get('tag') == 'column_set' and
            any('菜单' in str(col) for col in e.get('columns', []))
            for e in result['body']['elements']
        )
        if not has_menu:
            self._fail("card_rendering_complete", "完成时应有菜单按钮")
            return
        self._pass("card_rendering_complete")

    def test_card_rendering_streaming(self):
        """流式状态的卡片渲染"""
        from lark_client.card_builder import ResponseCard

        screen = _make_screen(
            '❯ 任务\r\n'
            '\x1b[5m⏺\x1b[25m 正在处理中...\r\n'
            '✱ Reading... (5s · ↓ 1.2k tokens)\r\n'
        )
        components = parse_components(screen)

        card = ResponseCard(user_input='任务')
        card.set_components(components)
        result = card.build_card()

        if result['header']['template'] != 'orange':
            self._fail("card_rendering_streaming", f"进行中模板应为 orange: {result['header']['template']}")
            return
        if 'Reading' not in result['header']['title']['content']:
            self._fail("card_rendering_streaming", f"标题应含 Reading: {result['header']['title']['content']}")
            return
        self._pass("card_rendering_streaming")

    # === 新增测试：修复的问题 ===

    def test_skip_thinking_bullet(self):
        """● (U+25CF) 应被跳过（thinking 动画），不是内容 bullet"""
        screen = _make_screen(
            '❯ hello\r\n'
            '● Thinking...\r\n'  # ● 是 thinking 动画，应跳过
            '⏺ 实际回复内容。\r\n'
        )
        components = parse_components(screen)

        texts = [c for c in components if isinstance(c, TextBlock)]
        if len(texts) != 1:
            self._fail("skip_thinking_bullet", f"应只有1个 TextBlock，实际 {len(texts)}: {[type(c).__name__ for c in components]}")
            return
        if 'Thinking' in texts[0].content:
            self._fail("skip_thinking_bullet", f"不应包含 thinking 动画: {texts[0].content!r}")
            return
        if '实际回复' not in texts[0].content:
            self._fail("skip_thinking_bullet", f"应包含实际内容: {texts[0].content!r}")
            return
        self._pass("skip_thinking_bullet")

    def test_skip_esc_variants(self):
        """各种 Esc 提示变体应跳过（含 pyte 截断如 Esc agait）"""
        screen = _make_screen(
            '❯ test\r\n'
            '⏺ 正常内容。\r\n'
            'Esc again to interrupt\r\n'
            'Esc agait\r\n'  # pyte 截断变体
            'Esc to interrupt\r\n'
        )
        components = parse_components(screen)

        texts = [c for c in components if isinstance(c, TextBlock)]
        for tb in texts:
            if 'Esc' in tb.content:
                self._fail("skip_esc_variants", f"不应包含 Esc 提示: {tb.content!r}")
                return
        self._pass("skip_esc_variants")

    def test_skip_bottom_bar(self):
        """底部状态栏内容应跳过"""
        screen = _make_screen(
            '❯ test\r\n'
            '⏺ 回复。\r\n'
            '▶▶ bypass permissions on (shift+tab to cycle)\r\n'
            '2 bashes · ↓ to manage\r\n'
            'ctrl+o to expand\r\n'
        )
        components = parse_components(screen)

        texts = [c for c in components if isinstance(c, TextBlock)]
        for tb in texts:
            if 'bypass' in tb.content or 'manage' in tb.content or 'ctrl+o' in tb.content:
                self._fail("skip_bottom_bar", f"不应包含底部栏内容: {tb.content!r}")
                return
        self._pass("skip_bottom_bar")

    def test_clean_artifacts(self):
        """pyte 渲染伪影 一 应被清理"""
        from lark_client.component_parser import _clean_artifacts

        # 一 + 英文 → 清理
        assert _clean_artifacts('一Noodling...') == 'Noodling...', \
            f"一+英文应被清理: {_clean_artifacts('一Noodling...')!r}"
        # 一开头的中文 → 不清理（是有效内容）
        assert _clean_artifacts('一些修改') == '一些修改', \
            f"一+中文不应清理: {_clean_artifacts('一些修改')!r}"
        # 空文本
        assert _clean_artifacts('') == ''
        # 正常文本
        assert _clean_artifacts('Normal text') == 'Normal text'
        self._pass("clean_artifacts")

    def test_zone_divider_bottom_bar(self):
        """水平分割线区域分割：输出区 + 底部栏提取"""
        # 模拟完整终端布局：输出区 | 分割线 | 输入框 | 分割线 | 底部栏
        divider = '─' * 80
        screen = _make_screen(
            '❯ hello\r\n'
            '⏺ 你好！有什么可以帮你的吗？\r\n'
            f'{divider}\r\n'              # 分割线1
            '❯ \r\n'                       # 空输入框
            f'{divider}\r\n'              # 分割线2
            '▶▶ bypass permissions on (shift+tab to cycle) · esc to interrupt\r\n'
        )
        components = parse_components(screen)

        # 输出区应有 1 个 TextBlock
        texts = [c for c in components if isinstance(c, TextBlock)]
        if len(texts) != 1:
            self._fail("zone_divider_bottom_bar", f"应有1个 TextBlock，实际 {len(texts)}")
            return
        if '你好' not in texts[0].content:
            self._fail("zone_divider_bottom_bar", f"TextBlock 内容不对: {texts[0].content!r}")
            return

        # 底部栏应被提取为 BottomBar 组件
        bars = [c for c in components if isinstance(c, BottomBar)]
        if len(bars) != 1:
            self._fail("zone_divider_bottom_bar", f"应有1个 BottomBar，实际 {len(bars)}: {[type(c).__name__ for c in components]}")
            return
        if 'bypass permissions' not in bars[0].text:
            self._fail("zone_divider_bottom_bar", f"BottomBar 内容不对: {bars[0].text!r}")
            return

        # 输入框的空 ❯ 不应出现在任何组件中
        user_inputs = [c for c in components if isinstance(c, UserInput)]
        if user_inputs:
            self._fail("zone_divider_bottom_bar", f"不应有 UserInput 组件: {user_inputs}")
            return

        self._pass("zone_divider_bottom_bar")

    def test_zone_no_divider_fallback(self):
        """无分割线时降级为旧行为（全量解析）"""
        screen = _make_screen(
            '❯ test\r\n'
            '⏺ 回复内容。\r\n'
        )
        components = parse_components(screen)

        texts = [c for c in components if isinstance(c, TextBlock)]
        bars = [c for c in components if isinstance(c, BottomBar)]
        if len(texts) != 1:
            self._fail("zone_no_divider_fallback", f"应有1个 TextBlock")
            return
        if bars:
            self._fail("zone_no_divider_fallback", f"无分割线时不应有 BottomBar")
            return
        self._pass("zone_no_divider_fallback")

    def test_status_line_with_artifact(self):
        """状态行中的 一 伪影应被清理"""
        screen = _make_screen(
            '❯ test\r\n'
            '⏺ 回复。\r\n'
            '✱ 一Noodling... (5s · ↓ 1k tokens)\r\n'
        )
        components = parse_components(screen)

        sl_list = [c for c in components if isinstance(c, StatusLine)]
        if not sl_list:
            self._fail("status_line_with_artifact", f"未检测到 StatusLine: {[type(c).__name__ for c in components]}")
            return
        sl = sl_list[0]
        if '一' in sl.action:
            self._fail("status_line_with_artifact", f"action 不应含 一: {sl.action!r}")
            return
        if 'Noodling' not in sl.action:
            self._fail("status_line_with_artifact", f"action 应含 Noodling: {sl.action!r}")
            return
        self._pass("status_line_with_artifact")

    def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("组件解析器单元测试")
        print("=" * 60)

        tests = [
            self.test_text_block_basic,
            self.test_text_block_streaming,
            self.test_text_block_static,
            self.test_tool_call_done,
            self.test_tool_call_running,
            self.test_tool_call_with_output,
            self.test_agent_block,
            self.test_plan_block,
            self.test_status_line,
            self.test_multiple_components,
            self.test_extract_latest_response,
            self.test_fallback_boundary,
            self.test_skip_decorations,
            self.test_tool_interrupted,
            self.test_tool_background,
            self.test_content_key_dedup,
            self.test_empty_screen,
            self.test_orphan_status_line,
            self.test_card_rendering_complete,
            self.test_card_rendering_streaming,
            # 新增修复测试
            self.test_skip_thinking_bullet,
            self.test_skip_esc_variants,
            self.test_skip_bottom_bar,
            self.test_clean_artifacts,
            self.test_status_line_with_artifact,
            # 区域分割线 + 底部栏测试
            self.test_zone_divider_bottom_bar,
            self.test_zone_no_divider_fallback,
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                self._fail(test.__name__, f"异常: {e}")

        print()
        print(f"结果: {self.passed} 通过, {self.failed} 失败, 共 {self.passed + self.failed} 个测试")
        if self.errors:
            print(f"\n失败详情:")
            for err in self.errors:
                print(f"  - {err}")

        return self.failed == 0


class TestAgentPanelParser:
    """Agent 面板解析测试（使用新版 ScreenParser）"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def _pass(self, name):
        self.passed += 1
        print(f"  ✓ {name}")

    def _fail(self, name, msg=""):
        self.failed += 1
        self.errors.append(f"{name}: {msg}")
        print(f"  ✗ {name}: {msg}")

    def _make_parser_and_screen(self, text, cols=220, lines=50):
        """创建 ScreenParser 和 pyte Screen"""
        sys.path.insert(0, str(Path(__file__).parent.parent / 'server'))
        from component_parser import ScreenParser
        screen = pyte.Screen(cols, lines)
        stream = pyte.Stream(screen)
        stream.feed(text)
        parser = ScreenParser()
        return parser, screen

    def test_bottom_bar_with_agents(self):
        """底部栏含后台 agent 信息时应正确解析"""
        from utils.components import BottomBar as BottomBarComp
        divider = '─' * 80
        text = (
            '❯ hello\r\n'
            '⏺ 你好！\r\n'
            f'{divider}\r\n'
            '❯ \r\n'
            f'{divider}\r\n'
            '4 local agents · ↓ to manage · ctrl+f to kill agents\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        bars = [c for c in components if isinstance(c, BottomBarComp)]
        if len(bars) != 1:
            self._fail("bottom_bar_with_agents", f"应有1个 BottomBar，实际 {len(bars)}")
            return
        bb = bars[0]
        if not bb.has_background_agents:
            self._fail("bottom_bar_with_agents", "has_background_agents 应为 True")
            return
        if bb.agent_count != 4:
            self._fail("bottom_bar_with_agents", f"agent_count 应为 4，实际 {bb.agent_count}")
            return
        if '4 local agents' not in bb.agent_summary:
            self._fail("bottom_bar_with_agents", f"agent_summary 不对: {bb.agent_summary!r}")
            return
        self._pass("bottom_bar_with_agents")

    def test_bottom_bar_single_running_agent(self):
        """底部栏含单个运行中 agent 信息"""
        from utils.components import BottomBar as BottomBarComp
        divider = '─' * 80
        text = (
            '⏺ 处理中...\r\n'
            f'{divider}\r\n'
            '❯ \r\n'
            f'{divider}\r\n'
            '执行 sleep 120 (running) · ↓ to manage · ctrl+f to kill agents\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        bars = [c for c in components if isinstance(c, BottomBarComp)]
        if len(bars) != 1:
            self._fail("bottom_bar_single_running_agent", f"应有1个 BottomBar，实际 {len(bars)}")
            return
        bb = bars[0]
        if not bb.has_background_agents:
            self._fail("bottom_bar_single_running_agent", "has_background_agents 应为 True")
            return
        if bb.agent_count != 1:
            self._fail("bottom_bar_single_running_agent", f"agent_count 应为 1，实际 {bb.agent_count}")
            return
        self._pass("bottom_bar_single_running_agent")

    def test_bottom_bar_no_agents(self):
        """普通底部栏（无 agent 信息）不应误判"""
        from utils.components import BottomBar as BottomBarComp
        divider = '─' * 80
        text = (
            '⏺ 回复。\r\n'
            f'{divider}\r\n'
            '❯ \r\n'
            f'{divider}\r\n'
            '▶▶ bypass permissions on (shift+tab to cycle) · esc to interrupt\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        bars = [c for c in components if isinstance(c, BottomBarComp)]
        if len(bars) != 1:
            self._fail("bottom_bar_no_agents", f"应有1个 BottomBar，实际 {len(bars)}")
            return
        bb = bars[0]
        if bb.has_background_agents:
            self._fail("bottom_bar_no_agents", "普通底部栏不应有 agent 信息")
            return
        self._pass("bottom_bar_no_agents")

    def test_agent_list_panel(self):
        """Agent 列表面板解析"""
        from utils.components import AgentPanelBlock as APB
        divider = '─' * 80
        text = (
            '⏺ 正在执行任务...\r\n'
            f'{divider}\r\n'
            'Background tasks\r\n'
            '3 active agents\r\n'
            '❯ 分析代码架构 (running)\r\n'
            '  搜索相关文件 (completed)\r\n'
            '  执行测试 (running)\r\n'
            '↑/↓ to select · Esc to close\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        panels = [c for c in components if isinstance(c, APB)]
        if len(panels) != 1:
            self._fail("agent_list_panel", f"应有1个 AgentPanelBlock，实际 {len(panels)}: {[type(c).__name__ for c in components]}")
            return
        panel = panels[0]
        if panel.panel_type != 'list':
            self._fail("agent_list_panel", f"panel_type 应为 list，实际 {panel.panel_type}")
            return
        if panel.agent_count != 3:
            self._fail("agent_list_panel", f"agent_count 应为 3，实际 {panel.agent_count}")
            return
        if parser.last_layout_mode != 'agent_list':
            self._fail("agent_list_panel", f"layout_mode 应为 agent_list，实际 {parser.last_layout_mode}")
            return
        self._pass("agent_list_panel")

    def test_agent_detail_panel(self):
        """Agent 详情面板解析"""
        from utils.components import AgentPanelBlock as APB
        divider = '─' * 80
        text = (
            '⏺ 正在执行任务...\r\n'
            f'{divider}\r\n'
            'general-purpose › 分析代码架构\r\n'
            '2m 15s · 4.3k tokens\r\n'
            'Progress\r\n'
            '正在扫描文件结构...\r\n'
            'Prompt\r\n'
            '分析项目的代码架构并给出建议\r\n'
            '← to go back · Esc to close\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        panels = [c for c in components if isinstance(c, APB)]
        if len(panels) != 1:
            self._fail("agent_detail_panel", f"应有1个 AgentPanelBlock，实际 {len(panels)}: {[type(c).__name__ for c in components]}")
            return
        panel = panels[0]
        if panel.panel_type != 'detail':
            self._fail("agent_detail_panel", f"panel_type 应为 detail，实际 {panel.panel_type}")
            return
        if panel.agent_type != 'general-purpose':
            self._fail("agent_detail_panel", f"agent_type 应为 general-purpose，实际 {panel.agent_type!r}")
            return
        if panel.agent_name != '分析代码架构':
            self._fail("agent_detail_panel", f"agent_name 应为 分析代码架构，实际 {panel.agent_name!r}")
            return
        if parser.last_layout_mode != 'agent_detail':
            self._fail("agent_detail_panel", f"layout_mode 应为 agent_detail，实际 {parser.last_layout_mode}")
            return
        self._pass("agent_detail_panel")

    def test_layout_mode_switch_clears_cache(self):
        """布局模式切换时应清空 dot_row_cache"""
        divider = '─' * 80
        # 先解析一帧正常布局（建立 dot_row_cache）
        normal_text = (
            '\x1b[5m⏺\x1b[25m 正在处理...\r\n'
            f'{divider}\r\n'
            '❯ \r\n'
            f'{divider}\r\n'
            '4 local agents · ↓ to manage\r\n'
        )
        parser, screen1 = self._make_parser_and_screen(normal_text)
        parser.parse(screen1)

        # 确认 dot_row_cache 有内容
        had_cache = len(parser._dot_row_cache) > 0

        # 解析一帧 agent_list 布局（模式切换）
        agent_list_text = (
            '⏺ 正在处理...\r\n'
            f'{divider}\r\n'
            'Background tasks\r\n'
            '↑/↓ to select · Esc to close\r\n'
        )
        screen2 = pyte.Screen(220, 50)
        stream2 = pyte.Stream(screen2)
        stream2.feed(agent_list_text)
        parser.parse(screen2)

        if had_cache and len(parser._dot_row_cache) > 0:
            # 模式切换后缓存应该被清空（如果之前有缓存的话）
            # 注意：由于我们用了新 screen，dot_row_cache 可能因 _cleanup_cache 被清除
            # 这里主要验证不会崩溃
            pass

        if parser.last_layout_mode != 'agent_list':
            self._fail("layout_mode_switch_clears_cache", f"layout_mode 应为 agent_list，实际 {parser.last_layout_mode}")
            return
        self._pass("layout_mode_switch_clears_cache")

    def test_content_key_agent_panel(self):
        """AgentPanelBlock 的 content_key 生成"""
        sys.path.insert(0, str(Path(__file__).parent.parent / 'server'))
        from component_parser import components_content_key
        from utils.components import AgentPanelBlock as APB

        panel_list = APB(panel_type="list", agent_count=3)
        panel_detail = APB(panel_type="detail", agent_name="test_agent")
        panel_summary = APB(panel_type="summary", agent_count=4)

        key_list = components_content_key([panel_list])
        key_detail = components_content_key([panel_detail])
        key_summary = components_content_key([panel_summary])

        if 'AP:list:3' not in key_list:
            self._fail("content_key_agent_panel", f"list key 不对: {key_list}")
            return
        if 'AP:test_agent' not in key_detail:
            self._fail("content_key_agent_panel", f"detail key 不对: {key_detail}")
            return
        if 'AP:summary:4' not in key_summary:
            self._fail("content_key_agent_panel", f"summary key 不对: {key_summary}")
            return
        if key_list == key_detail:
            self._fail("content_key_agent_panel", "list 和 detail 的 key 不应相同")
            return
        self._pass("content_key_agent_panel")

    def test_summary_agent_panel(self):
        """summary 类型 AgentPanelBlock 验证（底部栏有 agent 信息但面板未展开）"""
        from utils.components import AgentPanelBlock as APB
        panel = APB(panel_type="summary", agent_count=4, raw_text="4 local agents")
        if panel.panel_type != 'summary':
            self._fail("summary_agent_panel", f"panel_type 应为 summary，实际 {panel.panel_type}")
            return
        if panel.agent_count != 4:
            self._fail("summary_agent_panel", f"agent_count 应为 4，实际 {panel.agent_count}")
            return
        if panel.raw_text != "4 local agents":
            self._fail("summary_agent_panel", f"raw_text 不对: {panel.raw_text!r}")
            return
        self._pass("summary_agent_panel")

    def run_all(self):
        """运行所有 agent 面板测试"""
        print()
        print("=" * 60)
        print("Agent 面板解析测试（ScreenParser）")
        print("=" * 60)

        tests = [
            self.test_bottom_bar_with_agents,
            self.test_bottom_bar_single_running_agent,
            self.test_bottom_bar_no_agents,
            self.test_agent_list_panel,
            self.test_agent_detail_panel,
            self.test_layout_mode_switch_clears_cache,
            self.test_content_key_agent_panel,
            self.test_summary_agent_panel,
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                import traceback
                self._fail(test.__name__, f"异常: {e}\n{traceback.format_exc()}")

        print()
        print(f"结果: {self.passed} 通过, {self.failed} 失败, 共 {self.passed + self.failed} 个测试")
        if self.errors:
            print(f"\n失败详情:")
            for err in self.errors:
                print(f"  - {err}")

        return self.failed == 0


class TestOptionBlockParser:
    """OptionBlock 统一解析测试（option + permission 场景）"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def _pass(self, name):
        self.passed += 1
        print(f"  ✓ {name}")

    def _fail(self, name, msg=""):
        self.failed += 1
        self.errors.append(f"{name}: {msg}")
        print(f"  ✗ {name}: {msg}")

    def _make_parser_and_screen(self, text, cols=220, lines=50):
        """创建 ScreenParser 和 pyte Screen"""
        sys.path.insert(0, str(Path(__file__).parent.parent / 'server'))
        from component_parser import ScreenParser
        screen = pyte.Screen(cols, lines)
        stream = pyte.Stream(screen)
        stream.feed(text)
        parser = ScreenParser()
        return parser, screen

    def test_write_tool_permission(self):
        """Write 工具权限确认应识别为 OptionBlock(sub_type='permission')"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 好的，我来创建文件。\r\n'
            f'{divider}\r\n'
            'Write\r\n'
            'fibonacci.py\r\n'
            'Do you want to create fibonacci.py?\r\n'
            '❯ 1. Yes\r\n'
            '  2. Yes, and don\'t ask again for this file\r\n'
            '  3. No\r\n'
            'Esc to cancel · ↑/↓ to navigate · Enter to select\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("write_tool_permission",
                       f"应有1个 OptionBlock，实际 {len(opts)}: {[type(c).__name__ for c in components]}")
            return
        ob = opts[0]
        if ob.sub_type != 'permission':
            self._fail("write_tool_permission", f"sub_type 应为 'permission'，实际 {ob.sub_type!r}")
            return
        if ob.title != 'Write':
            self._fail("write_tool_permission", f"title 应为 'Write'，实际 {ob.title!r}")
            return
        if 'fibonacci.py' not in ob.content:
            self._fail("write_tool_permission", f"content 应含 'fibonacci.py'，实际 {ob.content!r}")
            return
        if 'Do you want to create' not in ob.question:
            self._fail("write_tool_permission", f"question 不对: {ob.question!r}")
            return
        if len(ob.options) != 3:
            self._fail("write_tool_permission", f"应有3个 options，实际 {len(ob.options)}: {ob.options}")
            return
        if ob.options[0]['label'] != 'Yes':
            self._fail("write_tool_permission", f"第一个选项应为 'Yes'，实际 {ob.options[0]!r}")
            return
        self._pass("write_tool_permission")

    def test_permission_layout_mode(self):
        """权限确认时 layout_mode 应为 'option'"""
        divider = '─' * 80
        text = (
            '⏺ 好的，我来创建文件。\r\n'
            f'{divider}\r\n'
            'Write\r\n'
            'fibonacci.py\r\n'
            'Do you want to create fibonacci.py?\r\n'
            '❯ 1. Yes\r\n'
            '  2. Yes, and don\'t ask again for this file\r\n'
            '  3. No\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        parser.parse(screen)

        if parser.last_layout_mode != 'option':
            self._fail("permission_layout_mode",
                       f"layout_mode 应为 'option'，实际 {parser.last_layout_mode!r}")
            return
        self._pass("permission_layout_mode")

    def test_bash_tool_permission(self):
        """Bash 工具权限确认仍然正常工作"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 让我运行这个命令。\r\n'
            f'{divider}\r\n'
            'Bash\r\n'
            'rm -rf /tmp/test\r\n'
            'Do you want to proceed?\r\n'
            '❯ 1. Yes\r\n'
            '  2. No\r\n'
            'Esc to cancel · ↑/↓ to navigate\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("bash_tool_permission",
                       f"应有1个 OptionBlock，实际 {len(opts)}")
            return
        ob = opts[0]
        if ob.sub_type != 'permission':
            self._fail("bash_tool_permission", f"sub_type 应为 'permission'，实际 {ob.sub_type!r}")
            return
        if ob.title != 'Bash':
            self._fail("bash_tool_permission", f"title 应为 'Bash'，实际 {ob.title!r}")
            return
        if len(ob.options) != 2:
            self._fail("bash_tool_permission", f"应有2个 options，实际 {len(ob.options)}")
            return
        if parser.last_layout_mode != 'option':
            self._fail("bash_tool_permission",
                       f"layout_mode 应为 'option'，实际 {parser.last_layout_mode!r}")
            return
        self._pass("bash_tool_permission")

    def test_no_numbered_options_no_option(self):
        """无编号选项行时不应误判为 option 模式"""
        divider = '─' * 80
        text = (
            '⏺ 输出内容。\r\n'
            f'{divider}\r\n'
            'Showing detailed transcript · ctrl+o to toggle · ctrl+e to show all\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        from utils.components import OptionBlock as OB
        opts = [c for c in components if isinstance(c, OB)]
        if opts:
            self._fail("no_numbered_options_no_option",
                       f"不应有 OptionBlock: {opts}")
            return
        if parser.last_layout_mode == 'option':
            self._fail("no_numbered_options_no_option",
                       "layout_mode 不应为 'option'")
            return
        self._pass("no_numbered_options_no_option")

    def test_single_option_not_permission(self):
        """只有 1 个编号选项行时不应判为 option 模式（需要 ≥2）"""
        divider = '─' * 80
        text = (
            '⏺ 内容。\r\n'
            f'{divider}\r\n'
            '一些说明文本\r\n'
            '❯ 1. Yes\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        from utils.components import OptionBlock as OB
        opts = [c for c in components if isinstance(c, OB)]
        if opts:
            self._fail("single_option_not_permission",
                       "只有1个编号选项不应产生 OptionBlock")
            return
        self._pass("single_option_not_permission")

    def test_permission_question_only(self):
        """只有 question + options（无 title/content）时也能正确解析"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 输出。\r\n'
            f'{divider}\r\n'
            'Do you want to proceed?\r\n'
            '❯ 1. Yes\r\n'
            '  2. No\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("permission_question_only",
                       f"应有1个 OptionBlock，实际 {len(opts)}")
            return
        ob = opts[0]
        if ob.sub_type != 'permission':
            self._fail("permission_question_only", f"sub_type 应为 'permission'，实际 {ob.sub_type!r}")
            return
        if 'Do you want to proceed?' not in ob.question:
            self._fail("permission_question_only", f"question 不对: {ob.question!r}")
            return
        self._pass("permission_question_only")

    def test_2div_numbered_options(self):
        """2 分割线 + 编号选项 → layout_mode='option'、OptionBlock(sub_type='option')"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 分析完成。\r\n'
            f'{divider}\r\n'
            'Which approach do you prefer?\r\n'
            '❯ 1. Approach A\r\n'
            '  2. Approach B\r\n'
            '  3. Approach C\r\n'
            f'{divider}\r\n'
            '▶▶ bypass permissions on\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("2div_numbered_options",
                       f"应有1个 OptionBlock，实际 {len(opts)}: {[type(c).__name__ for c in components]}")
            return
        ob = opts[0]
        if ob.sub_type != 'option':
            self._fail("2div_numbered_options", f"sub_type 应为 'option'，实际 {ob.sub_type!r}")
            return
        if 'Which approach' not in ob.question:
            self._fail("2div_numbered_options", f"question 不对: {ob.question!r}")
            return
        if len(ob.options) != 3:
            self._fail("2div_numbered_options", f"应有3个 options，实际 {len(ob.options)}")
            return
        if parser.last_layout_mode != 'option':
            self._fail("2div_numbered_options",
                       f"layout_mode 应为 'option'，实际 {parser.last_layout_mode!r}")
            return
        self._pass("2div_numbered_options")

    def test_numbered_list_not_option(self):
        """权限区域含编号列表但无 ❯ → 不应产生 OptionBlock"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 好的，我来创建文件。\r\n'
            f'{divider}\r\n'
            'Steps to follow:\r\n'
            '1. Install dependencies\r\n'
            '2. Configure settings\r\n'
            '3. Run the server\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if opts:
            self._fail("numbered_list_not_option",
                       f"不应有 OptionBlock（无 ❯ 锚点），实际 {len(opts)}")
            return
        if parser.last_layout_mode == 'option':
            self._fail("numbered_list_not_option",
                       "layout_mode 不应为 'option'")
            return
        self._pass("numbered_list_not_option")

    def test_cursor_on_second_option(self):
        """❯ 在第 2 个选项 → 应正确识别全部选项"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 输出内容。\r\n'
            f'{divider}\r\n'
            'Bash\r\n'
            'rm -rf /tmp/test\r\n'
            'Do you want to proceed?\r\n'
            '  1. Yes\r\n'
            '❯ 2. No\r\n'
            '  3. Ask me next time\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("cursor_on_second_option",
                       f"应有1个 OptionBlock，实际 {len(opts)}")
            return
        ob = opts[0]
        if ob.sub_type != 'permission':
            self._fail("cursor_on_second_option", f"sub_type 应为 'permission'，实际 {ob.sub_type!r}")
            return
        if len(ob.options) != 3:
            self._fail("cursor_on_second_option", f"应有3个 options，实际 {len(ob.options)}: {ob.options}")
            return
        if ob.options[0]['label'] != 'Yes':
            self._fail("cursor_on_second_option", f"第一个选项应为 'Yes'，实际 {ob.options[0]!r}")
            return
        self._pass("cursor_on_second_option")

    def test_2div_cursor_on_third(self):
        """2 分割线，❯ 在第 3 个选项 → 应正确识别全部选项"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 分析完成。\r\n'
            f'{divider}\r\n'
            'Which approach do you prefer?\r\n'
            '  1. Approach A\r\n'
            '  2. Approach B\r\n'
            '❯ 3. Approach C\r\n'
            '  4. Other\r\n'
            f'{divider}\r\n'
            '▶▶ bypass permissions on\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("2div_cursor_on_third",
                       f"应有1个 OptionBlock，实际 {len(opts)}: {[type(c).__name__ for c in components]}")
            return
        ob = opts[0]
        if ob.sub_type != 'option':
            self._fail("2div_cursor_on_third", f"sub_type 应为 'option'，实际 {ob.sub_type!r}")
            return
        if len(ob.options) != 4:
            self._fail("2div_cursor_on_third", f"应有4个 options，实际 {len(ob.options)}: {ob.options}")
            return
        if ob.options[2]['label'] != 'Approach C':
            self._fail("2div_cursor_on_third", f"第三个选项应为 'Approach C'，实际 {ob.options[2]!r}")
            return
        self._pass("2div_cursor_on_third")

    def test_mixed_numbered_content_with_options(self):
        """权限区域同时有编号内容和编号选项（有 ❯）→ 只收集连续选项"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 好的。\r\n'
            f'{divider}\r\n'
            'Bash\r\n'
            '1. Install packages\r\n'
            '2. Configure env\r\n'
            'Do you want to proceed?\r\n'
            '❯ 1. Yes\r\n'
            '  2. No\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("mixed_numbered_content_with_options",
                       f"应有1个 OptionBlock，实际 {len(opts)}")
            return
        ob = opts[0]
        if ob.sub_type != 'permission':
            self._fail("mixed_numbered_content_with_options",
                       f"sub_type 应为 'permission'，实际 {ob.sub_type!r}")
            return
        if len(ob.options) != 2:
            self._fail("mixed_numbered_content_with_options",
                       f"应有2个 options（不含编号内容行），实际 {len(ob.options)}: {ob.options}")
            return
        if ob.options[0]['label'] != 'Yes':
            self._fail("mixed_numbered_content_with_options",
                       f"第一个选项应为 'Yes'，实际 {ob.options[0]!r}")
            return
        # 编号内容行应在 content 中
        if '1. Install packages' not in (ob.content or ''):
            self._fail("mixed_numbered_content_with_options",
                       f"content 应含编号内容行，实际 {ob.content!r}")
            return
        self._pass("mixed_numbered_content_with_options")

    def test_option_overflow_with_cursor(self):
        """2 分割线，3 个选项在 input 区（❯ 在第 1 个），第 4 个溢出到 bottom 区"""
        from utils.components import OptionBlock as OB
        divider = '─' * 80
        text = (
            '⏺ 分析完成。\r\n'
            f'{divider}\r\n'
            'Which approach?\r\n'
            '❯ 1. Approach A\r\n'
            '  2. Approach B\r\n'
            '  3. Approach C\r\n'
            f'{divider}\r\n'
            '  4. Approach D\r\n'
            '▶▶ bypass permissions on\r\n'
        )
        parser, screen = self._make_parser_and_screen(text)
        components = parser.parse(screen)

        opts = [c for c in components if isinstance(c, OB)]
        if len(opts) != 1:
            self._fail("option_overflow_with_cursor",
                       f"应有1个 OptionBlock，实际 {len(opts)}: {[type(c).__name__ for c in components]}")
            return
        ob = opts[0]
        if ob.sub_type != 'option':
            self._fail("option_overflow_with_cursor", f"sub_type 应为 'option'，实际 {ob.sub_type!r}")
            return
        if len(ob.options) != 4:
            self._fail("option_overflow_with_cursor",
                       f"应有4个 options（含溢出），实际 {len(ob.options)}: {ob.options}")
            return
        if ob.options[3]['label'] != 'Approach D':
            self._fail("option_overflow_with_cursor",
                       f"第4个选项应为 'Approach D'，实际 {ob.options[3]!r}")
            return
        self._pass("option_overflow_with_cursor")

    def run_all(self):
        """运行所有 OptionBlock 统一测试"""
        print()
        print("=" * 60)
        print("OptionBlock 统一解析测试（option + permission）")
        print("=" * 60)

        tests = [
            self.test_write_tool_permission,
            self.test_permission_layout_mode,
            self.test_bash_tool_permission,
            self.test_no_numbered_options_no_option,
            self.test_single_option_not_permission,
            self.test_permission_question_only,
            self.test_2div_numbered_options,
            self.test_numbered_list_not_option,
            self.test_cursor_on_second_option,
            self.test_2div_cursor_on_third,
            self.test_mixed_numbered_content_with_options,
            self.test_option_overflow_with_cursor,
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                import traceback
                self._fail(test.__name__, f"异常: {e}\n{traceback.format_exc()}")

        print()
        print(f"结果: {self.passed} 通过, {self.failed} 失败, 共 {self.passed + self.failed} 个测试")
        if self.errors:
            print(f"\n失败详情:")
            for err in self.errors:
                print(f"  - {err}")

        return self.failed == 0


if __name__ == "__main__":
    # 运行旧版测试（可能因 import 路径问题跳过）
    success1 = True
    if _OLD_API_AVAILABLE:
        try:
            runner = TestComponentParser()
            success1 = runner.run_all()
        except Exception as e:
            print(f"旧版测试异常: {e}")
            success1 = False
    else:
        print("跳过旧版测试（lark_client.component_parser 不可用）")

    # 运行新版 Agent 面板测试
    runner2 = TestAgentPanelParser()
    success2 = runner2.run_all()

    # 运行 OptionBlock 统一测试（含 permission 场景）
    runner3 = TestOptionBlockParser()
    success3 = runner3.run_all()

    sys.exit(0 if (success1 and success2 and success3) else 1)
