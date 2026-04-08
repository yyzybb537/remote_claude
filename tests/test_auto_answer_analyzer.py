#!/usr/bin/env python3
"""自动应答选项解析器测试"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from lark_client.shared_memory_poller import analyze_option_block


@pytest.fixture
def runtime_config_store(tmp_path, monkeypatch):
    user_data_dir = tmp_path / "remote-claude"
    monkeypatch.setenv("REMOTE_CLAUDE_USER_DATA_DIR", str(user_data_dir))

    import utils.session as session_module
    import utils.runtime_config as runtime_config_module

    user_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(session_module, "USER_DATA_DIR", user_data_dir)
    monkeypatch.setattr(runtime_config_module, "USER_DATA_DIR", user_data_dir)
    monkeypatch.setattr(runtime_config_module, "SETTINGS_FILE", user_data_dir / "settings.json")
    monkeypatch.setattr(runtime_config_module, "STATE_FILE", user_data_dir / "state.json")
    monkeypatch.setattr(runtime_config_module, "SETTINGS_LOCK_FILE", user_data_dir / "settings.json.lock")
    monkeypatch.setattr(runtime_config_module, "STATE_LOCK_FILE", user_data_dir / "state.json.lock")

    runtime_config_module.cleanup_backup_files()
    return runtime_config_module


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


def test_vague_keywords_continue():
    """测试无明确语义选项发送继续"""
    option_block = {
        "options": [
            {"label": "继续", "value": "1"},
            {"label": "停止", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_vague_keywords_continue passed")


def test_vague_keywords_yes():
    """测试英文确认选项"""
    option_block = {
        "options": [
            {"label": "Yes", "value": "1"},
            {"label": "No", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_vague_keywords_yes passed")


def test_fallback_first():
    """测试兜底选择第一项"""
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


def test_mixed_vague_keywords():
    """测试混合模糊关键词"""
    # 测试 OK
    option_block = {
        "options": [
            {"label": "OK", "value": "1"},
            {"label": "Cancel", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_mixed_vague_keywords OK passed")

    # 测试 Sure
    option_block = {
        "options": [
            {"label": "Sure, proceed", "value": "1"},
            {"label": "No thanks", "value": "2"},
        ]
    }
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_mixed_vague_keywords Sure passed")


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


def test_vague_keywords(runtime_config_store):
    """测试模糊关键词来自配置文件"""
    runtime_config = runtime_config_store
    settings = runtime_config.load_settings()
    settings.session.auto_answer_vague_patterns = ["继续", "go ahead", "sure"]
    runtime_config.save_settings(settings)

    # 通过配置生效
    action_type, action_value = analyze_option_block({
        "options": [
            {"label": "go ahead", "value": "1"},
            {"label": "cancel", "value": "2"},
        ]
    })
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_vague_keywords passed")


def test_no_options_key():
    """测试没有 options 键的情况"""
    option_block = {}
    action_type, action_value = analyze_option_block(option_block)
    assert action_type == "input"
    assert action_value == "继续"
    print("✓ test_no_options_key passed")


if __name__ == "__main__":
    test_recommended_option()
    test_vague_keywords_continue()
    test_vague_keywords_yes()
    test_fallback_first()
    test_empty_options()
    test_chinese_recommended()
    test_mixed_vague_keywords()
    test_recommended_case_insensitive()
    test_vague_keywords()
    test_no_options_key()
    print("\n✅ All tests passed!")
