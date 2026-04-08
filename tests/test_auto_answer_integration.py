#!/usr/bin/env python3
"""自动应答集成测试

测试内容：
1. 配置函数测试 - get_auto_answer_delay, get_card_expiry_enabled, get_card_expiry_seconds,
   set_session_auto_answer_enabled, get_session_auto_answer_enabled
2. CardSlice 过期标记测试
3. 选项解析器测试 - analyze_option_block
4. AutoAnswerBlock 数据类测试
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def runtime_config_store(tmp_path, monkeypatch):
    """隔离运行时配置，避免集成测试读写真实用户目录。"""
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


def test_config_functions(runtime_config_store):
    """测试配置函数"""
    runtime_config = runtime_config_store

    # 测试默认值
    assert runtime_config.get_auto_answer_delay() == 10
    assert runtime_config.get_card_expiry_enabled() is True
    assert runtime_config.get_card_expiry_seconds() == 3600

    # 测试 session 状态
    runtime_config.set_session_auto_answer_enabled("test-session", True, "ou_test")
    assert runtime_config.get_session_auto_answer_enabled("test-session") is True

    runtime_config.set_session_auto_answer_enabled("test-session", False)
    assert runtime_config.get_session_auto_answer_enabled("test-session") is False


def test_card_slice_expiry(runtime_config_store):
    """测试 CardSlice 过期标记"""
    from lark_client.shared_memory_poller import CardSlice
    import time

    runtime_config = runtime_config_store

    # 创建一个 2 小时前的卡片
    old_slice = CardSlice(
        card_id="test-card",
        last_activity_time=time.time() - 7200,  # 2 小时前
    )

    # 模拟过期检测
    expiry = runtime_config.get_card_expiry_seconds()
    elapsed = time.time() - old_slice.last_activity_time

    assert elapsed > expiry, f"Card should be expired: elapsed={elapsed}, expiry={expiry}"


def test_option_analyzer():
    """测试选项解析器"""
    from lark_client.shared_memory_poller import analyze_option_block

    # 测试推荐选项
    result = analyze_option_block({
        "options": [
            {"label": "A", "value": "1"},
            {"label": "B (recommended)", "value": "2"},
        ]
    })
    assert result == ("select", "2"), f"Expected ('select', '2'), got {result}"

    # 测试无明确语义
    result = analyze_option_block({
        "options": [
            {"label": "继续", "value": "1"},
            {"label": "停止", "value": "2"},
        ]
    })
    assert result == ("input", "继续"), f"Expected ('input', '继续'), got {result}"

    # 测试兜底
    result = analyze_option_block({
        "options": [
            {"label": "方案A", "value": "1"},
            {"label": "方案B", "value": "2"},
        ]
    })
    assert result == ("select", "1"), f"Expected ('select', '1'), got {result}"


def test_auto_answer_block():
    """测试 AutoAnswerBlock"""
    from server.parsers.base_parser import AutoAnswerBlock

    # 测试 select 类型
    block = AutoAnswerBlock(
        block_id="AA:123",
        content="自动应答：选择了推荐方案「方案A」",
        action_type="select",
        selected_value="1",
        selected_label="方案A",
        timestamp=1234567890.0
    )
    assert block.action_type == "select"
    assert block.selected_value == "1"

    # 测试 input 类型
    block = AutoAnswerBlock(
        block_id="AA:456",
        content="自动应答：发送「继续」",
        action_type="input",
        input_text="继续",
        timestamp=1234567890.0
    )
    assert block.action_type == "input"
    assert block.input_text == "继续"
