#!/usr/bin/env python3
"""自动应答选项解析器测试"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from lark_client.shared_memory_poller import analyze_option_block


def test_recommended_option():
    """测试推荐选项优先"""
    option_block = {
        "options": [
            {"label": "Approach A", "value": "1"},
            {"label": "Approach B (recommended)", "value": "2"},
            {"label": "Approach C", "value": "3"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "2"
    print("✓ test_recommended_option passed")


def test_chinese_recommended():
    """测试中文推荐选项"""
    option_block = {
        "options": [
            {"label": "方案A", "value": "1"},
            {"label": "方案B（推荐）", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "2"
    print("✓ test_chinese_recommended passed")


def test_recommended_case_insensitive():
    """测试推荐标记大小写不敏感"""
    option_block = {
        "options": [
            {"label": "Approach A", "value": "1"},
            {"label": "Approach B (RECOMMENDED)", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "2"
    print("✓ test_recommended_case_insensitive passed")


def test_confirm_keywords_yes():
    """测试确认类选项 Yes"""
    option_block = {
        "options": [
            {"label": "Yes", "value": "1"},
            {"label": "No", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_confirm_keywords_yes passed")


def test_confirm_keywords_ok():
    """测试确认类选项 OK"""
    option_block = {
        "options": [
            {"label": "OK", "value": "1"},
            {"label": "Cancel", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_confirm_keywords_ok passed")


def test_confirm_keywords_continue():
    """测试确认类选项 继续"""
    option_block = {
        "options": [
            {"label": "继续", "value": "1"},
            {"label": "停止", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_confirm_keywords_continue passed")


def test_confirm_keywords_sure():
    """测试确认类选项 Sure"""
    option_block = {
        "options": [
            {"label": "Sure, proceed", "value": "1"},
            {"label": "No thanks", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_confirm_keywords_sure passed")


def test_fallback_first():
    """测试兜底选择第一项（非确认类选项）"""
    option_block = {
        "options": [
            {"label": "使用方案A", "value": "1"},
            {"label": "使用方案B", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "1"
    print("✓ test_fallback_first passed")


def test_empty_options():
    """测试空选项列表"""
    option_block = {"options": []}
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_empty_options passed")


def test_no_options_key():
    """测试没有 options 键的情况"""
    option_block = {}
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_no_options_key passed")


def test_selected_value():
    """测试已有选中值"""
    option_block = {
        "selected_value": "2",
        "options": [
            {"label": "Option A", "value": "1"},
            {"label": "Option B", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "select"
    assert action_value == "2"
    print("✓ test_selected_value passed")


if __name__ == "__main__":
    test_recommended_option()
    test_chinese_recommended()
    test_recommended_case_insensitive()
    test_confirm_keywords_yes()
    test_confirm_keywords_ok()
    test_confirm_keywords_continue()
    test_confirm_keywords_sure()
    test_fallback_first()
    test_empty_options()
    test_no_options_key()
    test_selected_value()
    print("\n✅ All tests passed!")
