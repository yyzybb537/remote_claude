# tests/test_token_manager.py

import os
import json
import tempfile
from pathlib import Path
from server.token_manager import TokenManager, generate_token


class TestTokenManager:
    """Token 管理器测试"""

    def test_generate_token_length(self):
        """测试 token 长度为 32 字节的 base64"""
        token = generate_token()
        assert len(token) >= 43  # 32 bytes base64 编码后至少 43 字符

    def test_generate_token_uniqueness(self):
        """测试每次生成的 token 不同"""
        token1 = generate_token()
        token2 = generate_token()
        assert token1 != token2

    def test_get_or_create_token_creates_new(self, tmp_path):
        """测试首次获取时创建新 token"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        token = manager.get_or_create_token()
        assert token is not None
        assert manager.verify_token(token)

    def test_get_or_create_token_loads_existing(self, tmp_path):
        """测试已存在时加载 token"""
        manager1 = TokenManager("test-session", data_dir=tmp_path)
        token1 = manager1.get_or_create_token()

        manager2 = TokenManager("test-session", data_dir=tmp_path)
        token2 = manager2.get_or_create_token()
        assert token1 == token2

    def test_verify_token_correct(self, tmp_path):
        """测试正确 token 验证"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        token = manager.get_or_create_token()
        assert manager.verify_token(token) is True

    def test_verify_token_incorrect(self, tmp_path):
        """测试错误 token 验证"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        manager.get_or_create_token()
        assert manager.verify_token("wrong-token") is False

    def test_regenerate_token(self, tmp_path):
        """测试重新生成 token"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        old_token = manager.get_or_create_token()

        new_token = manager.regenerate_token()
        assert new_token != old_token
        assert manager.verify_token(old_token) is False
        assert manager.verify_token(new_token) is True

    def test_token_file_permissions(self, tmp_path):
        """测试 token 文件权限为 0600"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        manager.get_or_create_token()

        token_file = tmp_path / "test-session_token.json"
        stat_info = os.stat(token_file)
        assert (stat_info.st_mode & 0o777) == 0o600

    def test_token_file_tamper_detection(self, tmp_path):
        """测试 token 文件篡改检测"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        token = manager.get_or_create_token()

        # 篡改文件
        token_file = tmp_path / "test-session_token.json"
        with open(token_file, 'r') as f:
            content = json.load(f)
        content['token'] = 'tampered-token'
        with open(token_file, 'w') as f:
            json.dump(content, f)

        # 验证应失败
        manager2 = TokenManager("test-session", data_dir=tmp_path)
        assert manager2.verify_token(token) is False

    def test_delete_token_file_removes_existing_file(self, tmp_path):
        """测试删除已存在的 token 文件"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        manager.get_or_create_token()

        token_file = tmp_path / "test-session_token.json"
        assert token_file.exists()

        assert manager.delete_token_file() is True
        assert token_file.exists() is False

    def test_delete_token_file_is_idempotent_when_missing(self, tmp_path):
        """测试删除不存在的 token 文件时保持幂等"""
        manager = TokenManager("test-session", data_dir=tmp_path)

        assert manager.delete_token_file() is True
        assert (tmp_path / "test-session_token.json").exists() is False
