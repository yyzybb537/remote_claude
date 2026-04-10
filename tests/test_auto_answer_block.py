#!/usr/bin/env python3
"""AutoAnswerBlock 数据类和渲染测试"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import asdict
from server.parsers.base_parser import AutoAnswerBlock
from lark_client.card_builder import _render_block_colored


def test_auto_answer_block_dataclass():
    """测试 AutoAnswerBlock 数据类定义"""
    # 测试创建 select 类型的 AutoAnswerBlock
    block = AutoAnswerBlock(
        block_id="AA:1234567890",
        content="自动应答：选择了推荐方案「Refactor the entire module」",
        action_type="select",
        selected_value="1",
        selected_label="Refactor the entire module",
        timestamp=1234567890.0,
        start_row=10,
    )

    assert block.block_id == "AA:1234567890"
    assert block.action_type == "select"
    assert block.selected_value == "1"
    assert block.selected_label == "Refactor the entire module"
    assert block.input_text is None
    print("✓ AutoAnswerBlock dataclass (select) passed")

    # 测试创建 input 类型的 AutoAnswerBlock
    block_input = AutoAnswerBlock(
        block_id="AA:1234567891",
        content="自动应答：发送「继续」",
        action_type="input",
        input_text="继续",
        timestamp=1234567891.0,
    )

    assert block_input.action_type == "input"
    assert block_input.input_text == "继续"
    assert block_input.selected_value is None
    assert block_input.selected_label is None
    print("✓ AutoAnswerBlock dataclass (input) passed")


def test_auto_answer_block_to_dict():
    """测试 AutoAnswerBlock 转换为字典（用于序列化）"""
    block = AutoAnswerBlock(
        block_id="AA:test",
        content="测试内容",
        action_type="select",
        selected_value="opt1",
        timestamp=1234567890.0,
    )

    block_dict = asdict(block)
    block_dict["_type"] = "AutoAnswerBlock"

    assert block_dict["_type"] == "AutoAnswerBlock"
    assert block_dict["block_id"] == "AA:test"
    assert block_dict["content"] == "测试内容"
    assert block_dict["action_type"] == "select"
    assert block_dict["selected_value"] == "opt1"
    print("✓ AutoAnswerBlock to dict passed")


def test_render_auto_answer_block_select():
    """测试渲染 select 类型的 AutoAnswerBlock"""
    block_dict = {
        "_type": "AutoAnswerBlock",
        "block_id": "AA:123",
        "content": "自动应答：选择了推荐方案「Refactor」",
        "action_type": "select",
        "selected_value": "1",
        "selected_label": "Refactor",
        "timestamp": 1234567890.0,
    }

    rendered = _render_block_colored(block_dict)
    assert rendered is not None
    assert "⏱" in rendered
    assert "自动应答" in rendered
    assert "Refactor" in rendered
    print(f"Rendered: {rendered}")
    print("✓ Render AutoAnswerBlock (select) passed")


def test_render_auto_answer_block_input():
    """测试渲染 input 类型的 AutoAnswerBlock"""
    block_dict = {
        "_type": "AutoAnswerBlock",
        "block_id": "AA:456",
        "content": "自动应答：发送「继续」",
        "action_type": "input",
        "input_text": "继续",
        "timestamp": 1234567890.0,
    }

    rendered = _render_block_colored(block_dict)
    assert rendered is not None
    assert "⏱" in rendered
    assert "继续" in rendered
    print(f"Rendered: {rendered}")
    print("✓ Render AutoAnswerBlock (input) passed")


def test_render_auto_answer_block_empty():
    """测试空内容的 AutoAnswerBlock 不渲染"""
    block_dict = {
        "_type": "AutoAnswerBlock",
        "block_id": "AA:empty",
        "content": "",
        "action_type": "select",
    }

    rendered = _render_block_colored(block_dict)
    assert rendered is None
    print("✓ Empty AutoAnswerBlock returns None passed")


def test_render_auto_answer_block_escape():
    """测试 AutoAnswerBlock 内容转义"""
    block_dict = {
        "_type": "AutoAnswerBlock",
        "block_id": "AA:escape",
        "content": "Test *bold* and _italic_",
        "action_type": "input",
        "input_text": "test",
    }

    rendered = _render_block_colored(block_dict)
    assert rendered is not None
    # 应该转义特殊字符
    assert "\\*" in rendered or "*" not in rendered.split("⏱ ")[1]
    print(f"Rendered: {rendered}")
    print("✓ AutoAnswerBlock escape passed")


if __name__ == "__main__":
    test_auto_answer_block_dataclass()
    test_auto_answer_block_to_dict()
    test_render_auto_answer_block_select()
    test_render_auto_answer_block_input()
    test_render_auto_answer_block_empty()
    test_render_auto_answer_block_escape()
    print("\n✅ All AutoAnswerBlock tests passed!")
