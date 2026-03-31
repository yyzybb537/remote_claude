#!/usr/bin/env python3
"""EnvConfig 测试"""

import tempfile
from pathlib import Path

from utils.env_config import EnvConfig, load_env_config, save_env_config


def test_env_config_default():
    """测试默认配置"""
    config = EnvConfig()
    assert config.feishu_app_id == ""
    assert config.feishu_app_secret == ""
    assert config.group_prefix == "Remote-Claude"
    assert config.log_level == "INFO"
    assert config.is_valid() == False


def test_env_config_valid():
    """测试有效配置"""
    config = EnvConfig(feishu_app_id="test_id", feishu_app_secret="test_secret")
    assert config.is_valid() == True


def test_env_config_save_and_load():
    """测试保存和加载"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / ".env"

        # 保存
        config = EnvConfig(
            feishu_app_id="id123",
            feishu_app_secret="secret456",
            user_whitelist=["user1", "user2"],
            group_prefix="TestPrefix",
            log_level="DEBUG",
        )
        config.save(path)

        # 加载
        loaded = EnvConfig.from_env_file(path)
        assert loaded.feishu_app_id == "id123"
        assert loaded.feishu_app_secret == "secret456"
        assert loaded.user_whitelist == ["user1", "user2"]
        assert loaded.group_prefix == "TestPrefix"
        assert loaded.log_level == "DEBUG"


def test_env_config_to_env_content():
    """测试生成 .env 内容"""
    config = EnvConfig(feishu_app_id="test_id", feishu_app_secret="test_secret")
    content = config.to_env_content()

    assert "FEISHU_APP_ID=test_id" in content
    assert "FEISHU_APP_SECRET=test_secret" in content
    assert "GROUP_PREFIX=Remote-Claude" in content


def test_env_config_no_proxy():
    """测试 no_proxy 字段"""
    config = EnvConfig(feishu_app_id="id", feishu_app_secret="secret", no_proxy=True)
    content = config.to_env_content()
    assert "NO_PROXY=1" in content

    config2 = EnvConfig(feishu_app_id="id", feishu_app_secret="secret", no_proxy=False)
    content2 = config2.to_env_content()
    assert "NO_PROXY=0" in content2


if __name__ == "__main__":
    test_env_config_default()
    test_env_config_valid()
    test_env_config_save_and_load()
    test_env_config_to_env_content()
    test_env_config_no_proxy()
    print("所有测试通过 ✓")
