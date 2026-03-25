"""
流式滚动卡片模型单元测试

测试覆盖：
- card_builder.build_stream_card：各 block 类型渲染、四层结构、header 逻辑
- shared_memory_poller：CardSlice/StreamTracker 数据模型、轮询逻辑
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保能导入项目模块
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── card_builder 测试 ─────────────────────────────────────────────────────────

from lark_client.card_builder import (
    build_stream_card,
    _render_block_colored,
    _render_agent_panel,
    _determine_header,
    _extract_buttons,
    _escape_md,
    _ansi_to_lark_md,
)


class TestEscapeMd(unittest.TestCase):
    """测试 _escape_md markdown 特殊字符转义"""

    def test_asterisk(self):
        self.assertEqual(_escape_md("*bold*"), "\\*bold\\*")

    def test_underscore(self):
        self.assertEqual(_escape_md("_italic_"), "\\_italic\\_")

    def test_tilde(self):
        self.assertEqual(_escape_md("~strike~"), "\\~strike\\~")

    def test_backtick(self):
        self.assertEqual(_escape_md("`code`"), "\\`code\\`")

    def test_mixed(self):
        self.assertEqual(_escape_md("a*b_c~d`e"), "a\\*b\\_c\\~d\\`e")

    def test_empty(self):
        self.assertEqual(_escape_md(""), "")

    def test_no_special(self):
        self.assertEqual(_escape_md("hello world"), "hello world")

    def test_leading_spaces_preserved(self):
        """行首空格应替换为不间断空格"""
        self.assertEqual(_escape_md("  indented"), "\u00a0\u00a0indented")

    def test_multiline_indent(self):
        """多行内容各行缩进独立处理"""
        result = _escape_md("no indent\n  two\n    four")
        lines = result.split('\n')
        self.assertEqual(lines[0], "no indent")
        self.assertEqual(lines[1], "\u00a0\u00a0two")
        self.assertEqual(lines[2], "\u00a0\u00a0\u00a0\u00a0four")

    def test_middle_spaces_not_changed(self):
        """非行首空格不受影响"""
        self.assertEqual(_escape_md("a  b"), "a  b")


class TestAnsiToLarkMd(unittest.TestCase):
    """测试 _ansi_to_lark_md ANSI 序列解析"""

    def test_green(self):
        result = _ansi_to_lark_md("\x1b[32m●\x1b[0m text")
        self.assertIn('<font color="green">●</font>', result)
        self.assertIn("text", result)

    def test_red(self):
        result = _ansi_to_lark_md("\x1b[31merror\x1b[0m")
        self.assertIn('<font color="red">error</font>', result)

    def test_grey(self):
        result = _ansi_to_lark_md("\x1b[90mdim\x1b[0m")
        self.assertIn('<font color="grey">dim</font>', result)

    def test_bright_colors(self):
        result = _ansi_to_lark_md("\x1b[92mbright green\x1b[0m")
        self.assertIn('<font color="green">bright green</font>', result)

    def test_yellow(self):
        result = _ansi_to_lark_md("\x1b[33myellow\x1b[0m")
        self.assertIn('<font color="yellow">yellow</font>', result)

    def test_blue(self):
        result = _ansi_to_lark_md("\x1b[34mblue\x1b[0m")
        self.assertIn('<font color="blue">blue</font>', result)

    def test_magenta_maps_to_purple(self):
        result = _ansi_to_lark_md("\x1b[35mmagenta\x1b[0m")
        self.assertIn('<font color="purple">magenta</font>', result)

    def test_cyan_maps_to_turquoise(self):
        result = _ansi_to_lark_md("\x1b[36mcyan\x1b[0m")
        self.assertIn('<font color="turquoise">cyan</font>', result)

    def test_bright_blue_maps_to_wathet(self):
        result = _ansi_to_lark_md("\x1b[94mbright blue\x1b[0m")
        self.assertIn('<font color="wathet">bright blue</font>', result)

    def test_bright_magenta_maps_to_violet(self):
        result = _ansi_to_lark_md("\x1b[95mbright magenta\x1b[0m")
        self.assertIn('<font color="violet">bright magenta</font>', result)

    def test_no_ansi(self):
        result = _ansi_to_lark_md("plain text")
        self.assertEqual(result, "plain text")

    def test_empty(self):
        result = _ansi_to_lark_md("")
        self.assertEqual(result, "")

    def test_mixed_colors(self):
        result = _ansi_to_lark_md("\x1b[32m●\x1b[0m hello \x1b[31merror\x1b[0m done")
        self.assertIn('<font color="green">●</font>', result)
        self.assertIn('<font color="red">error</font>', result)
        self.assertIn("done", result)

    def test_white_maps_to_grey(self):
        """white (37) 映射为 grey"""
        result = _ansi_to_lark_md("\x1b[37mwhite\x1b[0m")
        self.assertIn('<font color="grey">white</font>', result)

    def test_bright_white_maps_to_grey(self):
        """bright white (97) 映射为 grey"""
        result = _ansi_to_lark_md("\x1b[97mbright white\x1b[0m")
        self.assertIn('<font color="grey">bright white</font>', result)

    def test_truecolor(self):
        """真彩色 38;2;R;G;B 映射为最近的飞书颜色"""
        result = _ansi_to_lark_md("\x1b[38;2;0;180;0mgreen text\x1b[0m")
        self.assertIn('<font color="green">green text</font>', result)

    def test_truecolor_red(self):
        """真彩色纯红 (255,0,0) 映射为 carmine（最近色）"""
        result = _ansi_to_lark_md("\x1b[38;2;255;0;0mred text\x1b[0m")
        self.assertIn('<font color="carmine">red text</font>', result)

    def test_256color(self):
        """256 色 38;5;N 映射为最近的飞书颜色"""
        # 索引 34 → 标准 blue（映射到 SGR 34）
        result = _ansi_to_lark_md("\x1b[38;5;4mblue text\x1b[0m")
        self.assertIn('<font color="blue">blue text</font>', result)

    def test_special_chars_escaped(self):
        """ANSI 文本中的 markdown 特殊字符应被转义"""
        result = _ansi_to_lark_md("\x1b[32m*bold*\x1b[0m")
        self.assertIn("\\*bold\\*", result)


class TestRenderBlockColored(unittest.TestCase):
    """测试各 block 类型的着色渲染"""

    def test_output_block_plain(self):
        block = {"_type": "OutputBlock", "content": "Hello world", "indicator": "●", "is_streaming": False}
        result = _render_block_colored(block)
        self.assertNotIn("```", result)
        self.assertIn("●", result)
        self.assertIn("Hello world", result)
        self.assertNotIn("⏳", result)

    def test_output_block_with_ansi(self):
        block = {
            "_type": "OutputBlock",
            "content": "Hello",
            "indicator": "●",
            "ansi_indicator": "\x1b[32m●\x1b[0m",
            "ansi_content": "\x1b[31mHello\x1b[0m",
            "is_streaming": False,
        }
        result = _render_block_colored(block)
        self.assertIn('<font color="green">●</font>', result)
        self.assertIn('<font color="red">Hello</font>', result)

    def test_output_block_streaming(self):
        block = {"_type": "OutputBlock", "content": "正在处理...", "indicator": "●", "is_streaming": True}
        result = _render_block_colored(block)
        self.assertTrue(result.startswith("⏳"))

    def test_output_block_empty(self):
        block = {"_type": "OutputBlock", "content": "", "indicator": "●"}
        result = _render_block_colored(block)
        self.assertIsNone(result)

    def test_user_input_plain(self):
        block = {"_type": "UserInput", "text": "帮我写代码"}
        result = _render_block_colored(block)
        self.assertIn("❯", result)
        self.assertIn("帮我写代码", result)
        self.assertNotIn("```", result)

    def test_user_input_with_ansi(self):
        block = {
            "_type": "UserInput",
            "text": "test",
            "ansi_indicator": "\x1b[32m❯\x1b[0m",
            "ansi_text": "\x1b[36mtest\x1b[0m",
        }
        result = _render_block_colored(block)
        self.assertIn('<font color="green">❯</font>', result)
        self.assertIn('<font color="turquoise">test</font>', result)

    def test_user_input_empty(self):
        block = {"_type": "UserInput", "text": ""}
        result = _render_block_colored(block)
        self.assertIsNone(result)

    def test_option_block(self):
        block = {"_type": "OptionBlock", "question": "选择方案", "tag": "方案", "options": []}
        result = _render_block_colored(block)
        self.assertIn("🤔 选择方案", result)
        self.assertNotIn("```", result)

    def test_option_block_tag_fallback(self):
        block = {"_type": "OptionBlock", "question": "", "tag": "类型标签"}
        result = _render_block_colored(block)
        self.assertIn("🤔 类型标签", result)

    def test_permission_block(self):
        """向后兼容：_type=PermissionBlock"""
        block = {"_type": "PermissionBlock", "title": "Bash command", "content": "rm -rf /tmp/test"}
        result = _render_block_colored(block)
        self.assertIn("🔐 Bash command", result)
        self.assertIn("rm -rf /tmp/test", result)
        self.assertNotIn("```", result)

    def test_permission_block_empty(self):
        """向后兼容：_type=PermissionBlock 空内容"""
        block = {"_type": "PermissionBlock", "title": "", "content": ""}
        result = _render_block_colored(block)
        self.assertIn("🔐 权限确认", result)

    def test_option_block_sub_type_permission(self):
        """新模式：OptionBlock + sub_type=permission"""
        block = {"_type": "OptionBlock", "sub_type": "permission", "title": "Bash command", "content": "ls -la"}
        result = _render_block_colored(block)
        self.assertIn("🔐 Bash command", result)
        self.assertIn("ls -la", result)

    def test_unknown_type(self):
        block = {"_type": "UnknownType", "data": "test"}
        result = _render_block_colored(block)
        self.assertIsNone(result)

    def test_markdown_escape_in_content(self):
        """OutputBlock content 中的 markdown 特殊字符应被转义"""
        block = {"_type": "OutputBlock", "content": "use *bold* and `code`", "indicator": "●", "is_streaming": False}
        result = _render_block_colored(block)
        self.assertIn("\\*bold\\*", result)
        self.assertIn("\\`code\\`", result)


class TestDetermineHeader(unittest.TestCase):
    """测试卡片 Header 逻辑"""

    def test_frozen(self):
        title, template = _determine_header([], None, None, is_frozen=True)
        self.assertEqual(title, "📋 会话记录")
        self.assertEqual(template, "grey")

    def test_streaming_with_status_line(self):
        blocks = [{"_type": "OutputBlock", "is_streaming": True}]
        status = {"action": "Thinking...", "elapsed": "1m 30s", "tokens": "↓ 2k tokens"}
        title, template = _determine_header(blocks, status, None, is_frozen=False)
        self.assertIn("⏳", title)
        self.assertIn("Thinking...", title)
        self.assertIn("1m 30s", title)
        self.assertEqual(template, "orange")

    def test_streaming_no_status_line(self):
        blocks = [{"_type": "OutputBlock", "is_streaming": True}]
        title, template = _determine_header(blocks, None, None, is_frozen=False)
        self.assertEqual(title, "⏳ 处理中...")
        self.assertEqual(template, "orange")

    def test_permission_block_last(self):
        """向后兼容：blocks 中的 PermissionBlock"""
        blocks = [
            {"_type": "OutputBlock", "is_streaming": False},
            {"_type": "PermissionBlock"},
        ]
        title, template = _determine_header(blocks, None, None, is_frozen=False)
        self.assertEqual(title, "🔐 等待权限确认")
        self.assertEqual(template, "red")

    def test_option_block_last(self):
        """向后兼容：blocks 中的 OptionBlock"""
        blocks = [{"_type": "OptionBlock"}]
        title, template = _determine_header(blocks, None, None, is_frozen=False)
        self.assertEqual(title, "🤔 等待选择")
        self.assertEqual(template, "blue")

    def test_option_block_param_permission(self):
        """option_block 参数：sub_type=permission → 红色"""
        blocks = [{"_type": "OutputBlock", "is_streaming": False}]
        ob = {"sub_type": "permission", "question": "Do you want to proceed?"}
        title, template = _determine_header(blocks, None, None, is_frozen=False, option_block=ob)
        self.assertEqual(title, "🔐 等待权限确认")
        self.assertEqual(template, "red")

    def test_option_block_param_option(self):
        """option_block 参数：sub_type=option → 蓝色"""
        blocks = [{"_type": "OutputBlock", "is_streaming": False}]
        ob = {"sub_type": "option", "question": "Which approach?"}
        title, template = _determine_header(blocks, None, None, is_frozen=False, option_block=ob)
        self.assertEqual(title, "🤔 等待选择")
        self.assertEqual(template, "blue")

    def test_all_complete(self):
        blocks = [{"_type": "OutputBlock", "is_streaming": False}]
        title, template = _determine_header(blocks, None, None, is_frozen=False)
        self.assertEqual(title, "✅ Claude 就绪")
        self.assertEqual(template, "green")

    def test_empty_blocks(self):
        title, template = _determine_header([], None, None, is_frozen=False)
        self.assertEqual(title, "✅ Claude 就绪")
        self.assertEqual(template, "green")


class TestExtractButtons(unittest.TestCase):
    """测试按钮提取"""

    def test_option_block_buttons(self):
        """向后兼容：blocks 中的 OptionBlock"""
        blocks = [
            {"_type": "OutputBlock", "content": "text"},
            {"_type": "OptionBlock", "options": [
                {"label": "A", "value": "1"},
                {"label": "B", "value": "2"},
            ]},
        ]
        buttons = _extract_buttons(blocks)
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0]["label"], "A")

    def test_permission_block_buttons(self):
        """向后兼容：blocks 中的 PermissionBlock"""
        blocks = [
            {"_type": "PermissionBlock", "options": [
                {"label": "Yes", "value": "yes"},
                {"label": "No", "value": "no"},
            ]},
        ]
        buttons = _extract_buttons(blocks)
        self.assertEqual(len(buttons), 2)

    def test_option_block_param_buttons(self):
        """option_block 参数优先提取按钮"""
        ob = {"sub_type": "option", "options": [
            {"label": "X", "value": "x"},
            {"label": "Y", "value": "y"},
            {"label": "Z", "value": "z"},
        ]}
        buttons = _extract_buttons([], option_block=ob)
        self.assertEqual(len(buttons), 3)
        self.assertEqual(buttons[0]["label"], "X")

    def test_option_block_param_overrides_blocks(self):
        """option_block 参数优先于 blocks 中的旧 OptionBlock"""
        blocks = [
            {"_type": "OptionBlock", "options": [
                {"label": "Old", "value": "old"},
            ]},
        ]
        ob = {"sub_type": "permission", "options": [
            {"label": "Yes", "value": "yes"},
            {"label": "No", "value": "no"},
        ]}
        buttons = _extract_buttons(blocks, option_block=ob)
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0]["label"], "Yes")

    def test_no_buttons(self):
        blocks = [{"_type": "OutputBlock", "content": "text"}]
        buttons = _extract_buttons(blocks)
        self.assertEqual(buttons, [])

    def test_empty_blocks(self):
        buttons = _extract_buttons([])
        self.assertEqual(buttons, [])


class TestBuildStreamCard(unittest.TestCase):
    """测试完整卡片构建"""

    def test_basic_output(self):
        blocks = [
            {"_type": "UserInput", "text": "你好"},
            {"_type": "OutputBlock", "content": "你好！", "indicator": "●", "is_streaming": False},
        ]
        card = build_stream_card(blocks)
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["template"], "green")
        elements = card["body"]["elements"]
        # 至少有 2 个 markdown（blocks）+ hr + menu
        md_elements = [e for e in elements if e.get("tag") == "markdown"]
        self.assertGreaterEqual(len(md_elements), 2)

    def test_frozen_card(self):
        blocks = [{"_type": "OutputBlock", "content": "历史内容", "indicator": "●"}]
        card = build_stream_card(blocks, is_frozen=True)
        self.assertEqual(card["header"]["template"], "grey")
        self.assertIn("会话记录", card["header"]["title"]["content"])
        # 冻结卡片无状态区和按钮区
        elements = card["body"]["elements"]
        # 菜单行现在在 form 里，顶层应无裸 column_set
        col_sets = [e for e in elements if e.get("tag") == "column_set"]
        self.assertEqual(len(col_sets), 0)  # 菜单已移入 form，无裸 column_set
        # 应有 form 元素（菜单 + 输入框）
        forms = [e for e in elements if e.get("tag") == "form"]
        self.assertEqual(len(forms), 1)

    def test_with_status_line(self):
        blocks = [{"_type": "OutputBlock", "content": "text", "indicator": "●", "is_streaming": True}]
        status = {"action": "Reading...", "elapsed": "5s", "tokens": "↓ 100"}
        card = build_stream_card(blocks, status_line=status)
        self.assertEqual(card["header"]["template"], "orange")
        elements = card["body"]["elements"]
        # 应有 column_set grey 背景状态区
        grey_sets = [e for e in elements if e.get("tag") == "column_set" and e.get("background_style") == "grey"]
        self.assertEqual(len(grey_sets), 1)
        # 状态区内应有 Reading... 文本
        status_md = grey_sets[0]["columns"][0]["elements"]
        status_texts = [e["content"] for e in status_md if "Reading" in e.get("content", "")]
        self.assertEqual(len(status_texts), 1)

    def test_with_bottom_bar(self):
        blocks = [{"_type": "OutputBlock", "content": "text", "indicator": "●", "is_streaming": True}]
        bottom = {"text": "▶▶ bypass permissions on", "_type": "BottomBar"}
        card = build_stream_card(blocks, status_line={"action": "Thinking..."}, bottom_bar=bottom)
        elements = card["body"]["elements"]
        # bottom_bar 文本应在 column_set grey 状态区内
        grey_sets = [e for e in elements if e.get("tag") == "column_set" and e.get("background_style") == "grey"]
        self.assertEqual(len(grey_sets), 1)
        status_md = grey_sets[0]["columns"][0]["elements"]
        bar_texts = [e["content"] for e in status_md if "bypass" in e.get("content", "")]
        self.assertEqual(len(bar_texts), 1)

    def test_with_option_buttons(self):
        """向后兼容：blocks 中的 OptionBlock"""
        blocks = [
            {"_type": "OutputBlock", "content": "分析完成", "indicator": "●"},
            {"_type": "OptionBlock", "question": "选择方案", "options": [
                {"label": "方案A", "value": "1"},
                {"label": "方案B", "value": "2"},
            ]},
        ]
        card = build_stream_card(blocks)
        self.assertEqual(card["header"]["template"], "blue")
        elements = card["body"]["elements"]
        # 应有按钮行（column_set，菜单已移入 form）
        col_sets = [e for e in elements if e.get("tag") == "column_set"]
        self.assertGreaterEqual(len(col_sets), 1)  # 至少 1 按钮行（菜单在 form 中）

    def test_with_permission_buttons(self):
        """向后兼容：blocks 中的 PermissionBlock"""
        blocks = [
            {"_type": "PermissionBlock", "title": "Bash", "content": "ls", "options": [
                {"label": "Yes", "value": "yes"},
                {"label": "No", "value": "no"},
            ]},
        ]
        card = build_stream_card(blocks)
        self.assertEqual(card["header"]["template"], "red")

    def test_with_option_block_param(self):
        """option_block 参数：选项交互"""
        blocks = [{"_type": "OutputBlock", "content": "分析完成", "indicator": "●", "is_streaming": False}]
        ob = {
            "sub_type": "option",
            "question": "选择方案",
            "options": [
                {"label": "方案A", "value": "1"},
                {"label": "方案B", "value": "2"},
            ],
        }
        card = build_stream_card(blocks, option_block=ob)
        self.assertEqual(card["header"]["template"], "blue")
        elements = card["body"]["elements"]
        col_sets = [e for e in elements if e.get("tag") == "column_set"]
        self.assertGreaterEqual(len(col_sets), 2)  # 按钮行 + 菜单行

    def test_with_permission_option_block_param(self):
        """option_block 参数：权限确认"""
        blocks = [{"_type": "OutputBlock", "content": "text", "indicator": "●", "is_streaming": False}]
        ob = {
            "sub_type": "permission",
            "title": "Bash command",
            "content": "rm -rf /tmp/test",
            "question": "Do you want to proceed?",
            "options": [
                {"label": "Yes", "value": "yes"},
                {"label": "No", "value": "no"},
            ],
        }
        card = build_stream_card(blocks, option_block=ob)
        self.assertEqual(card["header"]["template"], "red")

    def test_empty_blocks(self):
        card = build_stream_card([])
        elements = card["body"]["elements"]
        # 空 blocks 时不应有"正在生成回复..."
        md_texts = [e.get("content", "") for e in elements if e.get("tag") == "markdown"]
        self.assertFalse(any("正在生成回复" in t for t in md_texts))

    def test_four_layer_structure(self):
        """验证四层结构完整性"""
        blocks = [
            {"_type": "UserInput", "text": "测试"},
            {"_type": "OutputBlock", "content": "回复", "indicator": "●", "is_streaming": True},
            {"_type": "OptionBlock", "question": "选择", "options": [
                {"label": "A", "value": "1"},
            ]},
        ]
        status = {"action": "Processing...", "elapsed": "10s"}
        card = build_stream_card(blocks, status_line=status)
        elements = card["body"]["elements"]

        # 第一层：内容区（至少 2 个 markdown block，不含代码块）
        content_mds = []
        for e in elements:
            if e.get("tag") == "markdown":
                content_mds.append(e)
            elif e.get("tag") == "column_set" and e.get("background_style") == "grey":
                break  # 到达状态区
        self.assertGreaterEqual(len(content_mds), 2)  # UserInput + OutputBlock

        # 第二层：状态区（column_set grey 背景内含状态文本）
        grey_sets = [e for e in elements if e.get("tag") == "column_set" and e.get("background_style") == "grey"]
        self.assertEqual(len(grey_sets), 1)
        status_md = grey_sets[0]["columns"][0]["elements"]
        status_found = any("Processing" in e.get("content", "") for e in status_md)
        self.assertTrue(status_found)

        # 第三层：按钮区（column_set with select_option）
        button_sets = []
        for e in elements:
            if e.get("tag") == "column_set":
                cols = e.get("columns", [])
                for col in cols:
                    for el in col.get("elements", []):
                        behaviors = el.get("behaviors", [])
                        for b in behaviors:
                            if b.get("value", {}).get("action") == "select_option":
                                button_sets.append(e)
        self.assertGreaterEqual(len(button_sets), 1)

        # 第四层：菜单按钮（现在在 form > column_set 内）
        def _find_menu_open(column_set_elements):
            for col in column_set_elements:
                for el in col.get("elements", []):
                    behaviors = el.get("behaviors", [])
                    for b in behaviors:
                        if b.get("value", {}).get("action") == "menu_open":
                            return True
            return False

        menu_found = False
        for e in elements:
            if e.get("tag") == "column_set":
                if _find_menu_open(e.get("columns", [])):
                    menu_found = True
            elif e.get("tag") == "form":
                # 菜单行现在在 form 的第一个 element（column_set）内
                for form_el in e.get("elements", []):
                    if form_el.get("tag") == "column_set":
                        if _find_menu_open(form_el.get("columns", [])):
                            menu_found = True
        self.assertTrue(menu_found)

    def test_with_agent_panel_summary(self):
        """agent_panel summary 模式 → column_set grey 背景内纯文本"""
        blocks = [{"_type": "OutputBlock", "content": "text", "indicator": "●", "is_streaming": False}]
        panel = {"panel_type": "summary", "agent_count": 4}
        card = build_stream_card(blocks, agent_panel=panel)
        elements = card["body"]["elements"]
        # agent panel 应在 column_set grey 状态区内
        grey_sets = [e for e in elements if e.get("tag") == "column_set" and e.get("background_style") == "grey"]
        self.assertEqual(len(grey_sets), 1)
        status_md = grey_sets[0]["columns"][0]["elements"]
        agent_texts = [e["content"] for e in status_md if "🤖" in e.get("content", "")]
        self.assertEqual(len(agent_texts), 1)
        self.assertIn("4 个后台 agent", agent_texts[0])
        self.assertFalse(agent_texts[0].startswith("*"))  # 不再是斜体

    def test_with_agent_panel_list(self):
        """agent_panel list 模式 → column_set grey 背景内代码块 + agent 列表"""
        blocks = [{"_type": "OutputBlock", "content": "text", "indicator": "●", "is_streaming": True}]
        panel = {
            "panel_type": "list",
            "agent_count": 2,
            "agents": [
                {"name": "分析代码架构", "status": "running", "is_selected": True},
                {"name": "搜索相关文件", "status": "completed", "is_selected": False},
            ],
        }
        card = build_stream_card(blocks, status_line={"action": "Thinking..."}, agent_panel=panel)
        elements = card["body"]["elements"]
        grey_sets = [e for e in elements if e.get("tag") == "column_set" and e.get("background_style") == "grey"]
        self.assertEqual(len(grey_sets), 1)
        status_md = grey_sets[0]["columns"][0]["elements"]
        agent_texts = [e["content"] for e in status_md if "🤖" in e.get("content", "")]
        self.assertEqual(len(agent_texts), 1)
        content = agent_texts[0]
        self.assertIn("```", content)
        self.assertIn("后台任务 (2)", content)
        self.assertIn("❯ 分析代码架构 (running)", content)
        self.assertIn("  搜索相关文件 (completed)", content)

    def test_with_agent_panel_detail(self):
        """agent_panel detail 模式 → column_set grey 背景内代码块 + 详情"""
        blocks = [{"_type": "OutputBlock", "content": "text", "indicator": "●"}]
        panel = {
            "panel_type": "detail",
            "agent_name": "analyze-code",
            "agent_type": "Explore",
            "stats": "2m 15s · 4.3k tokens",
            "progress": "正在扫描文件结构...",
            "prompt": "分析项目的代码架构",
        }
        card = build_stream_card(blocks, agent_panel=panel)
        elements = card["body"]["elements"]
        grey_sets = [e for e in elements if e.get("tag") == "column_set" and e.get("background_style") == "grey"]
        self.assertEqual(len(grey_sets), 1)
        status_md = grey_sets[0]["columns"][0]["elements"]
        agent_texts = [e["content"] for e in status_md if "🤖" in e.get("content", "")]
        self.assertEqual(len(agent_texts), 1)
        content = agent_texts[0]
        self.assertIn("```", content)
        self.assertIn("Explore › analyze-code", content)
        self.assertIn("2m 15s · 4.3k tokens", content)
        self.assertIn("Progress: 正在扫描文件结构...", content)
        self.assertIn("Prompt: 分析项目的代码架构", content)

    def test_agent_panel_not_shown_when_frozen(self):
        """冻结卡片不显示 agent_panel"""
        blocks = [{"_type": "OutputBlock", "content": "text", "indicator": "●"}]
        panel = {"panel_type": "summary", "agent_count": 3}
        card = build_stream_card(blocks, agent_panel=panel, is_frozen=True)
        elements = card["body"]["elements"]
        agent_texts = [e for e in elements if e.get("tag") == "markdown" and "🤖" in e.get("content", "")]
        self.assertEqual(len(agent_texts), 0)

    def test_plan_block_renders_as_collapsible(self):
        """PlanBlock 渲染为 collapsible_panel"""
        blocks = [
            {"_type": "PlanBlock", "title": "实现计划", "content": "1. 分析需求\n2. 编写代码\n3. 测试"},
        ]
        card = build_stream_card(blocks)
        elements = card["body"]["elements"]
        # 过滤 PlanBlock 产生的折叠面板（header 含 📋）
        plan_panels = [
            e for e in elements
            if e.get("tag") == "collapsible_panel"
            and "📋" in e.get("header", {}).get("title", {}).get("content", "")
        ]
        self.assertEqual(len(plan_panels), 1)
        panel = plan_panels[0]
        self.assertTrue(panel.get("expanded"))
        self.assertIn("📋 实现计划", panel["header"]["title"]["content"])
        inner_mds = [e for e in panel.get("elements", []) if e.get("tag") == "markdown"]
        self.assertEqual(len(inner_mds), 1)
        self.assertIn("分析需求", inner_mds[0]["content"])

    def test_plan_block_with_ansi(self):
        """PlanBlock 含 ansi_content 时正确转换为飞书 markdown 着色"""
        blocks = [
            {
                "_type": "PlanBlock",
                "title": "计划",
                "content": "step1",
                "ansi_content": "step1",  # 无 ANSI 转义，直接当普通文本
            }
        ]
        card = build_stream_card(blocks)
        elements = card["body"]["elements"]
        plan_panels = [
            e for e in elements
            if e.get("tag") == "collapsible_panel"
            and "📋" in e.get("header", {}).get("title", {}).get("content", "")
        ]
        self.assertEqual(len(plan_panels), 1)
        inner_content = plan_panels[0]["elements"][0]["content"]
        self.assertIn("step1", inner_content)

    def test_plan_block_empty_content_skipped(self):
        """空 PlanBlock（无 content）不渲染"""
        blocks = [
            {"_type": "PlanBlock", "title": "空计划", "content": ""},
            {"_type": "OutputBlock", "content": "正常输出", "indicator": "●"},
        ]
        card = build_stream_card(blocks)
        elements = card["body"]["elements"]
        plan_panels = [
            e for e in elements
            if e.get("tag") == "collapsible_panel"
            and "📋" in e.get("header", {}).get("title", {}).get("content", "")
        ]
        self.assertEqual(len(plan_panels), 0)
        md_elements = [e for e in elements if e.get("tag") == "markdown"]
        self.assertTrue(any("正常输出" in e.get("content", "") for e in md_elements))

    def test_plan_block_mixed_with_output(self):
        """PlanBlock 与 OutputBlock 混合渲染：顺序正确"""
        blocks = [
            {"_type": "UserInput", "text": "请做计划"},
            {"_type": "PlanBlock", "title": "实现方案", "content": "步骤一\n步骤二"},
            {"_type": "OutputBlock", "content": "好的，开始执行", "indicator": "●"},
        ]
        card = build_stream_card(blocks)
        elements = card["body"]["elements"]
        # 应有 1 个 PlanBlock collapsible_panel（header 含 📋）
        plan_panels = [
            e for e in elements
            if e.get("tag") == "collapsible_panel"
            and "📋" in e.get("header", {}).get("title", {}).get("content", "")
        ]
        self.assertEqual(len(plan_panels), 1)
        # 应有至少 2 个 markdown（UserInput + OutputBlock）
        md_elements = [e for e in elements if e.get("tag") == "markdown"]
        self.assertGreaterEqual(len(md_elements), 2)
        # UserInput 应在 PlanBlock 之前（在 elements 列表中位置更靠前）
        md_pos = next(i for i, e in enumerate(elements) if e.get("tag") == "markdown")
        panel_pos = next(
            i for i, e in enumerate(elements)
            if e.get("tag") == "collapsible_panel"
            and "📋" in e.get("header", {}).get("title", {}).get("content", "")
        )
        self.assertLess(md_pos, panel_pos)


class TestRenderAgentPanel(unittest.TestCase):
    """测试 _render_agent_panel 各模式"""

    def test_summary(self):
        result = _render_agent_panel({"panel_type": "summary", "agent_count": 5})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tag"], "markdown")
        self.assertIn("5 个后台 agent", result[0]["content"])
        self.assertFalse(result[0]["content"].startswith("*"))  # 不再是斜体

    def test_list(self):
        panel = {
            "panel_type": "list",
            "agent_count": 1,
            "agents": [{"name": "task-1", "status": "running", "is_selected": False}],
        }
        result = _render_agent_panel(panel)
        self.assertEqual(len(result), 1)
        self.assertIn("```", result[0]["content"])
        self.assertIn("  task-1 (running)", result[0]["content"])

    def test_detail(self):
        panel = {
            "panel_type": "detail",
            "agent_name": "my-agent",
            "agent_type": "Plan",
            "stats": "1m",
            "progress": "working",
            "prompt": "do stuff",
        }
        result = _render_agent_panel(panel)
        self.assertEqual(len(result), 1)
        self.assertIn("Plan › my-agent", result[0]["content"])

    def test_unknown_type(self):
        result = _render_agent_panel({"panel_type": "unknown"})
        self.assertEqual(result, [])

    def test_empty_panel_type(self):
        result = _render_agent_panel({})
        self.assertEqual(result, [])


# ── shared_memory_poller 测试 ─────────────────────────────────────────────────

from lark_client.shared_memory_poller import (
    CardSlice,
    StreamTracker,
    SharedMemoryPoller,
    INITIAL_WINDOW,
    MAX_CARD_BLOCKS,
    CARD_SIZE_LIMIT,
)


class TestCardSlice(unittest.TestCase):
    """测试 CardSlice 数据模型"""

    def test_defaults(self):
        cs = CardSlice(card_id="card_123")
        self.assertEqual(cs.card_id, "card_123")
        self.assertEqual(cs.sequence, 0)
        self.assertEqual(cs.start_idx, 0)
        self.assertFalse(cs.frozen)


class TestStreamTracker(unittest.TestCase):
    """测试 StreamTracker 数据模型"""

    def test_defaults(self):
        tracker = StreamTracker(chat_id="chat_abc", session_name="test")
        self.assertEqual(tracker.cards, [])
        self.assertEqual(tracker.content_hash, "")
        self.assertIsNone(tracker.reader)


class TestPollerPollOnce(unittest.TestCase):
    """测试 _poll_once 逻辑（mock reader 和 card_service）"""

    def setUp(self):
        self.card_service = AsyncMock()
        self.card_service.create_card = AsyncMock(return_value="card_001")
        self.card_service.send_card = AsyncMock(return_value="msg_001")
        self.card_service.update_card = AsyncMock(return_value=True)
        self.poller = SharedMemoryPoller(self.card_service)

    def _make_reader(self, state: dict):
        reader = MagicMock()
        reader.read.return_value = state
        reader.close = MagicMock()
        return reader

    def test_empty_blocks_no_card(self):
        """空 blocks 不创建卡片"""
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": [], "status_line": None, "bottom_bar": None})

        asyncio.run(self.poller._poll_once(tracker))

        self.card_service.create_card.assert_not_called()
        self.assertEqual(len(tracker.cards), 0)

    def test_first_poll_creates_card(self):
        """首次轮询有 blocks → 创建新卡片"""
        blocks = [{"_type": "OutputBlock", "content": f"block {i}", "indicator": "●"} for i in range(5)]
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": blocks, "status_line": None, "bottom_bar": None})

        asyncio.run(self.poller._poll_once(tracker))

        self.card_service.create_card.assert_called_once()
        self.card_service.send_card.assert_called_once()
        self.assertEqual(len(tracker.cards), 1)
        self.assertEqual(tracker.cards[0].start_idx, 0)
        self.assertFalse(tracker.cards[0].frozen)

    def test_first_poll_with_history(self):
        """首次 attach 有大量历史 → 只取最近 INITIAL_WINDOW 个"""
        blocks = [{"_type": "OutputBlock", "content": f"block {i}", "indicator": "●"} for i in range(100)]
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": blocks, "status_line": None, "bottom_bar": None})

        asyncio.run(self.poller._poll_once(tracker))

        self.assertEqual(len(tracker.cards), 1)
        self.assertEqual(tracker.cards[0].start_idx, 100 - INITIAL_WINDOW)

    def test_update_on_change(self):
        """有变化时更新卡片"""
        blocks_v1 = [{"_type": "OutputBlock", "content": "hello", "indicator": "●"}]
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": blocks_v1, "status_line": None, "bottom_bar": None})

        # 首次 → 创建
        asyncio.run(self.poller._poll_once(tracker))
        self.assertEqual(self.card_service.create_card.call_count, 1)

        # 第二次，内容变化 → 更新
        blocks_v2 = [
            {"_type": "OutputBlock", "content": "hello", "indicator": "●"},
            {"_type": "OutputBlock", "content": "world", "indicator": "●"},
        ]
        tracker.reader = self._make_reader({"blocks": blocks_v2, "status_line": None, "bottom_bar": None})
        asyncio.run(self.poller._poll_once(tracker))

        self.card_service.update_card.assert_called_once()
        self.assertEqual(tracker.cards[0].sequence, 1)

    def test_skip_on_no_change(self):
        """无变化时跳过更新"""
        blocks = [{"_type": "OutputBlock", "content": "same", "indicator": "●"}]
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": blocks, "status_line": None, "bottom_bar": None})

        # 首次 → 创建
        asyncio.run(self.poller._poll_once(tracker))

        # 第二次，内容不变 → 跳过
        asyncio.run(self.poller._poll_once(tracker))

        self.card_service.update_card.assert_not_called()

    def test_freeze_and_split(self):
        """超限 → 冻结 + 开新卡"""
        # 创建超过 MAX_CARD_BLOCKS 的 blocks
        blocks = [{"_type": "OutputBlock", "content": f"b{i}", "indicator": "●"} for i in range(MAX_CARD_BLOCKS + 10)]
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": blocks[:5], "status_line": None, "bottom_bar": None})

        # 首次：创建卡片（5 个 blocks）
        asyncio.run(self.poller._poll_once(tracker))
        self.assertEqual(len(tracker.cards), 1)
        self.assertEqual(tracker.cards[0].start_idx, 0)

        # 现在 blocks 增长到超限
        self.card_service.create_card = AsyncMock(return_value="card_002")
        tracker.reader = self._make_reader({"blocks": blocks, "status_line": None, "bottom_bar": None})
        asyncio.run(self.poller._poll_once(tracker))

        # 应该冻结第一张 + 创建第二张
        self.assertEqual(len(tracker.cards), 2)
        self.assertTrue(tracker.cards[0].frozen)
        self.assertFalse(tracker.cards[1].frozen)
        self.assertEqual(tracker.cards[1].start_idx, MAX_CARD_BLOCKS)

    def test_update_fallback_on_failure(self):
        """update_card 失败时降级为创建新卡片"""
        blocks = [{"_type": "OutputBlock", "content": "hello", "indicator": "●"}]
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": blocks, "status_line": None, "bottom_bar": None})

        # 首次 → 创建
        asyncio.run(self.poller._poll_once(tracker))

        # 第二次 → update 失败，降级创建
        blocks_v2 = [
            {"_type": "OutputBlock", "content": "hello", "indicator": "●"},
            {"_type": "OutputBlock", "content": "world", "indicator": "●"},
        ]
        tracker.reader = self._make_reader({"blocks": blocks_v2, "status_line": None, "bottom_bar": None})
        self.card_service.update_card = AsyncMock(return_value=False)
        self.card_service.create_card = AsyncMock(return_value="card_fallback")

        asyncio.run(self.poller._poll_once(tracker))

        # 降级创建了新卡片
        self.assertEqual(tracker.cards[0].card_id, "card_fallback")
        self.assertEqual(tracker.cards[0].sequence, 0)


class TestPollerStartStop(unittest.TestCase):
    """测试 start/stop 生命周期"""

    def test_start_stop(self):
        async def _run():
            card_service = AsyncMock()
            poller = SharedMemoryPoller(card_service)

            poller.start("chat_1", "session_1")
            self.assertIn("chat_1", poller._trackers)
            self.assertIn("chat_1", poller._tasks)

            poller.stop("chat_1")
            self.assertNotIn("chat_1", poller._trackers)
            self.assertNotIn("chat_1", poller._tasks)

        asyncio.run(_run())

    def test_start_replaces_old(self):
        async def _run():
            card_service = AsyncMock()
            poller = SharedMemoryPoller(card_service)

            poller.start("chat_1", "session_1")
            old_task = poller._tasks["chat_1"]

            poller.start("chat_1", "session_2")
            # yield 控制权让 cancel 传播
            await asyncio.sleep(0)
            self.assertTrue(old_task.cancelled())
            self.assertEqual(poller._trackers["chat_1"].session_name, "session_2")

            poller.stop("chat_1")

        asyncio.run(_run())


class TestComputeHash(unittest.TestCase):
    """测试 hash 计算"""

    def test_same_content_same_hash(self):
        blocks = [{"_type": "OutputBlock", "content": "hello"}]
        h1 = SharedMemoryPoller._compute_hash(blocks, None, None)
        h2 = SharedMemoryPoller._compute_hash(blocks, None, None)
        self.assertEqual(h1, h2)

    def test_different_content_different_hash(self):
        b1 = [{"_type": "OutputBlock", "content": "hello"}]
        b2 = [{"_type": "OutputBlock", "content": "world"}]
        h1 = SharedMemoryPoller._compute_hash(b1, None, None)
        h2 = SharedMemoryPoller._compute_hash(b2, None, None)
        self.assertNotEqual(h1, h2)

    def test_status_line_affects_hash(self):
        blocks = [{"_type": "OutputBlock", "content": "hello"}]
        h1 = SharedMemoryPoller._compute_hash(blocks, None, None)
        h2 = SharedMemoryPoller._compute_hash(blocks, {"action": "thinking"}, None)
        self.assertNotEqual(h1, h2)

    def test_agent_panel_affects_hash(self):
        blocks = [{"_type": "OutputBlock", "content": "hello"}]
        h1 = SharedMemoryPoller._compute_hash(blocks, None, None)
        h2 = SharedMemoryPoller._compute_hash(blocks, None, None, {"panel_type": "summary", "agent_count": 3})
        self.assertNotEqual(h1, h2)

    def test_agent_panel_different_values_different_hash(self):
        blocks = [{"_type": "OutputBlock", "content": "hello"}]
        h1 = SharedMemoryPoller._compute_hash(blocks, None, None, {"panel_type": "summary", "agent_count": 3})
        h2 = SharedMemoryPoller._compute_hash(blocks, None, None, {"panel_type": "summary", "agent_count": 5})
        self.assertNotEqual(h1, h2)

    def test_option_block_affects_hash(self):
        blocks = [{"_type": "OutputBlock", "content": "hello"}]
        h1 = SharedMemoryPoller._compute_hash(blocks, None, None)
        h2 = SharedMemoryPoller._compute_hash(blocks, None, None, option_block={"sub_type": "option", "question": "Choose"})
        self.assertNotEqual(h1, h2)

    def test_option_block_different_values_different_hash(self):
        blocks = [{"_type": "OutputBlock", "content": "hello"}]
        h1 = SharedMemoryPoller._compute_hash(blocks, None, None, option_block={"sub_type": "option", "question": "A"})
        h2 = SharedMemoryPoller._compute_hash(blocks, None, None, option_block={"sub_type": "permission", "question": "B"})
        self.assertNotEqual(h1, h2)


class TestCardSizeLimit(unittest.TestCase):
    """测试卡片大小超限处理"""

    def setUp(self):
        self.card_service = AsyncMock()
        self.card_service.create_card = AsyncMock(return_value="card_001")
        self.card_service.send_card = AsyncMock(return_value="msg_001")
        self.card_service.update_card = AsyncMock(return_value=True)
        self.poller = SharedMemoryPoller(self.card_service)

    def _make_reader(self, state: dict):
        reader = MagicMock()
        reader.read.return_value = state
        reader.close = MagicMock()
        return reader

    def _make_large_block(self, size_bytes: int) -> dict:
        """生成指定大小的 OutputBlock"""
        content = "x" * size_bytes
        return {"_type": "OutputBlock", "content": content, "indicator": "●", "is_streaming": False}

    def test_find_freeze_count_small_blocks(self):
        """_find_freeze_count：小 blocks 全部能放入"""
        blocks = [{"_type": "OutputBlock", "content": f"b{i}", "indicator": "●"} for i in range(10)]
        count = self.poller._find_freeze_count(blocks, "test")
        # 10 个小 blocks 远未超限，应全部放入
        self.assertEqual(count, 10)

    def test_find_freeze_count_large_blocks(self):
        """_find_freeze_count：超大 blocks 时二分查找返回能容纳的数量"""
        # 每个 block 约 3KB，10 个共 30KB > 25KB，应该能放入约 8 个
        block_size = 3 * 1024
        blocks = [self._make_large_block(block_size) for _ in range(10)]
        count = self.poller._find_freeze_count(blocks, "test")
        # 结果应在 1~9 范围内（具体取决于 card 结构开销）
        self.assertGreaterEqual(count, 1)
        self.assertLess(count, 10)

        # 验证：count 个 blocks 构建的冻结卡片不超限
        from lark_client.card_builder import build_stream_card
        card = build_stream_card(blocks[:count], None, None, is_frozen=True, session_name="test")
        size = len(json.dumps(card, ensure_ascii=False).encode('utf-8'))
        self.assertLessEqual(size, CARD_SIZE_LIMIT)

        # 验证：count+1 个 blocks 构建的冻结卡片超限
        if count + 1 <= len(blocks):
            card_plus = build_stream_card(blocks[:count + 1], None, None, is_frozen=True, session_name="test")
            size_plus = len(json.dumps(card_plus, ensure_ascii=False).encode('utf-8'))
            self.assertGreater(size_plus, CARD_SIZE_LIMIT)

    def test_find_freeze_count_returns_at_least_1(self):
        """_find_freeze_count：即使单个 block 超限，也返回 1"""
        # 单个 block 就超过 25KB
        blocks = [self._make_large_block(26 * 1024)]
        count = self.poller._find_freeze_count(blocks, "test")
        self.assertEqual(count, 1)

    def test_size_limit_triggers_freeze_and_split(self):
        """卡片大小超限 → 冻结+开新卡（blocks 数量未超限）"""
        # 首先创建一张卡片
        small_blocks = [{"_type": "OutputBlock", "content": "hello", "indicator": "●"}]
        tracker = StreamTracker(chat_id="c1", session_name="s1")
        tracker.reader = self._make_reader({"blocks": small_blocks, "status_line": None, "bottom_bar": None})
        asyncio.run(self.poller._poll_once(tracker))
        self.assertEqual(len(tracker.cards), 1)

        # 再加一个超大 block，让卡片整体超出大小限制
        large_content = "y" * (26 * 1024)
        large_blocks = small_blocks + [
            {"_type": "OutputBlock", "content": large_content, "indicator": "●", "is_streaming": False}
        ]
        # blocks 数量仍 < MAX_CARD_BLOCKS，但大小超过 25KB
        self.assertLess(len(large_blocks), MAX_CARD_BLOCKS)

        self.card_service.create_card = AsyncMock(return_value="card_002")
        tracker.reader = self._make_reader({"blocks": large_blocks, "status_line": None, "bottom_bar": None})
        asyncio.run(self.poller._poll_once(tracker))

        # 应触发冻结：2 张卡片，第一张冻结
        self.assertEqual(len(tracker.cards), 2)
        self.assertTrue(tracker.cards[0].frozen)
        self.assertFalse(tracker.cards[1].frozen)

    def test_size_limit_freeze_count_less_than_block_count(self):
        """大小超限时冻结的 blocks 数 < blocks 总数，新卡从正确位置开始"""
        # 创建首张卡片（1 个小 block）
        first_block = {"_type": "OutputBlock", "content": "init", "indicator": "●"}
        tracker = StreamTracker(chat_id="c2", session_name="s2")
        tracker.reader = self._make_reader({"blocks": [first_block], "status_line": None, "bottom_bar": None})
        asyncio.run(self.poller._poll_once(tracker))

        # 现在加入大量大 block，触发大小超限
        big_block = self._make_large_block(4 * 1024)  # 每个 4KB
        many_blocks = [first_block] + [big_block] * 8  # 总计 9 个，约 32KB+ 超限
        self.card_service.create_card = AsyncMock(return_value="card_003")
        tracker.reader = self._make_reader({"blocks": many_blocks, "status_line": None, "bottom_bar": None})
        asyncio.run(self.poller._poll_once(tracker))

        # 应触发冻结
        self.assertEqual(len(tracker.cards), 2)
        self.assertTrue(tracker.cards[0].frozen)
        # 新卡 start_idx 必须 >= 1（至少冻结了第一个 block）
        self.assertGreaterEqual(tracker.cards[1].start_idx, 1)

    def test_create_new_card_trims_oversized(self):
        """_create_new_card：新卡超限时从头部裁剪"""
        # 构造 50 个小 block 的历史，然后一次性 attach（取最近 INITIAL_WINDOW=30 个）
        # 但最近 30 个已经超出大小限制
        big_block = self._make_large_block(1024)  # 每个 1KB，30 个约 30KB+ 超限
        blocks = [big_block] * 50

        tracker = StreamTracker(chat_id="c3", session_name="s3")
        tracker.reader = self._make_reader({"blocks": blocks, "status_line": None, "bottom_bar": None})
        asyncio.run(self.poller._poll_once(tracker))

        # 应创建一张卡片，start_idx >= 50 - INITIAL_WINDOW = 20（可能因裁剪更大）
        self.assertEqual(len(tracker.cards), 1)
        self.assertGreaterEqual(tracker.cards[0].start_idx, 50 - INITIAL_WINDOW)

        # 验证创建的卡片大小在限制内（send_card 被调用说明卡片创建成功）
        self.card_service.send_card.assert_called_once()


if __name__ == '__main__':
    unittest.main()
