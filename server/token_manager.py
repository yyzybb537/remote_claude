# server/token_manager.py

import secrets
import base64
import json
import hashlib
import os
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone


def generate_token() -> str:
    """生成 32 字节随机 token (base64 编码)"""
    random_bytes = secrets.token_bytes(32)
    return base64.b64encode(random_bytes).decode('ascii')


class TokenManager:
    """会话 Token 管理器

    负责：
    - 生成 32 字节随机 token（base64 编码）
    - 持久化 token 到文件（权限 0600）
    - 验证 token 正确性
    - 检测文件篡改（通过 SHA-256 hash）
    - 支持重新生成 token
    """

    TOKEN_FILE_MODE = 0o600  # 仅所有者可读写

    def __init__(self, session_name: str, data_dir: Path = None):
        """初始化 Token 管理器

        Args:
            session_name: 会话名称
            data_dir: 数据目录，默认 ~/.remote-claude
        """
        self.session_name = session_name
        self.data_dir = data_dir or Path.home() / ".remote-claude"
        self.token_file = self.data_dir / f"{session_name}_token.json"
        self._token: Optional[str] = None
        self._file_hash: Optional[str] = None

    def get_or_create_token(self) -> str:
        """获取或创建 token

        如果 token 已存在则加载，否则创建新的 token。

        Returns:
            token 字符串
        """
        if self._token:
            return self._token

        loaded = self._load_token()
        if loaded:
            self._token = loaded['token']
            return self._token

        # 创建新 token
        self._token = generate_token()
        self._save_token(self._token)
        return self._token

    def regenerate_token(self) -> str:
        """重新生成 token

        使旧 token 失效，生成新 token。

        Returns:
            新的 token 字符串
        """
        self._token = generate_token()
        self._save_token(self._token)
        return self._token

    def verify_token(self, token: str) -> bool:
        """验证 token

        Args:
            token: 要验证的 token 字符串

        Returns:
            True 如果 token 正确，False 否则
        """
        if not self._token:
            loaded = self._load_token()
            if not loaded:
                return False
            self._token = loaded['token']

        return secrets.compare_digest(self._token, token)

    def _load_token(self) -> Optional[dict]:
        """从文件加载 token

        Returns:
            token 数据字典，如果加载失败则返回 None
        """
        if not self.token_file.exists():
            return None

        try:
            with open(self.token_file, 'r') as f:
                content = f.read()

            data = json.loads(content)

            # 验证文件完整性
            if not self._verify_file_integrity(content, data):
                return None

            return data
        except Exception:
            return None

    def _save_token(self, token: str):
        """保存 token 到文件

        Args:
            token: token 字符串
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()
        data = {
            "session": self.session_name,
            "token": token,
            "created_at": now,
            "last_used_at": now,
        }

        content = json.dumps(data, indent=2)

        # 计算 hash 并添加
        file_hash = self._compute_file_hash(content)
        data['file_hash'] = file_hash
        content = json.dumps(data, indent=2)

        # 写入文件，使用 os.open 设置权限
        fd = os.open(str(self.token_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, self.TOKEN_FILE_MODE)
        try:
            os.write(fd, content.encode('utf-8'))
        finally:
            os.close(fd)

    def _compute_file_hash(self, content: str) -> str:
        """计算文件内容 hash

        Args:
            content: 文件内容字符串

        Returns:
            hash 字符串，格式为 "sha256:<hex>"
        """
        return "sha256:" + hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _verify_file_integrity(self, content: str, data: dict) -> bool:
        """验证文件完整性

        Args:
            content: 文件原始内容
            data: 解析后的 JSON 数据

        Returns:
            True 如果完整性验证通过，False 否则
        """
        if 'file_hash' not in data:
            return False

        stored_hash = data['file_hash']
        # 计算不含 file_hash 字段的 hash
        temp_data = {k: v for k, v in data.items() if k != 'file_hash'}
        temp_content = json.dumps(temp_data, indent=2)
        computed_hash = self._compute_file_hash(temp_content)

        return stored_hash == computed_hash
