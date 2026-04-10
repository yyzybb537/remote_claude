"""
环境变量配置管理模块

提供统一的环境变量配置读写，支持：
- 从 .env 文件加载配置
- 保存配置到 .env 文件
- 默认值处理

配置文件位置: ~/.remote-claude/.env
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger('EnvConfig')

from utils.session import USER_DATA_DIR, ensure_user_data_dir

ENV_FILE = USER_DATA_DIR / ".env"

_ENV_ALIASES = {
    'ALLOWED_USERS': ('USER_WHITELIST',),
    'GROUP_NAME_PREFIX': ('GROUP_PREFIX',),
    'LARK_LOG_LEVEL': ('LOG_LEVEL',),
    'LARK_NO_PROXY': ('NO_PROXY',),
}


@dataclass
class EnvConfig:
    """环境变量配置"""
    # 必填
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    # 可选
    allowed_users: List[str] = field(default_factory=list)
    enable_user_whitelist: bool = False
    group_name_prefix: str = "Remote-Claude"
    lark_log_level: str = "INFO"
    startup_timeout: int = 5
    max_card_blocks: int = 50
    lark_no_proxy: bool = False

    def is_valid(self) -> bool:
        """检查必填字段是否已配置"""
        return bool(self.feishu_app_id and self.feishu_app_secret)

    def to_env_content(self) -> str:
        """生成 .env 文件内容"""
        lines = [
            "# Remote Claude 环境变量配置",
            "",
            "# === 必填 ===",
            f"FEISHU_APP_ID={self.feishu_app_id}",
            f"FEISHU_APP_SECRET={self.feishu_app_secret}",
            "",
            "# === 可选 ===",
            f"ALLOWED_USERS={','.join(self.allowed_users)}",
            f"ENABLE_USER_WHITELIST={'true' if self.enable_user_whitelist else 'false'}",
            f"GROUP_NAME_PREFIX={self.group_name_prefix}",
            f"LARK_LOG_LEVEL={self.lark_log_level}",
            f"STARTUP_TIMEOUT={self.startup_timeout}",
            f"MAX_CARD_BLOCKS={self.max_card_blocks}",
            f"LARK_NO_PROXY={'1' if self.lark_no_proxy else '0'}",
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_env_file(cls, path: Path = ENV_FILE) -> "EnvConfig":
        """从 .env 文件加载配置"""
        if not path.exists():
            return cls()

        env_vars: dict = {}
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()

        return cls(
            feishu_app_id=env_vars.get('FEISHU_APP_ID', ''),
            feishu_app_secret=env_vars.get('FEISHU_APP_SECRET', ''),
            allowed_users=_parse_list(_get_env_value(env_vars, 'ALLOWED_USERS', '')),
            enable_user_whitelist=_parse_bool(_get_env_value(env_vars, 'ENABLE_USER_WHITELIST', 'false')),
            group_name_prefix=_get_env_value(env_vars, 'GROUP_NAME_PREFIX', 'Remote-Claude'),
            lark_log_level=_get_env_value(env_vars, 'LARK_LOG_LEVEL', 'INFO'),
            startup_timeout=int(env_vars.get('STARTUP_TIMEOUT', '5')),
            max_card_blocks=int(env_vars.get('MAX_CARD_BLOCKS', '50')),
            lark_no_proxy=_parse_bool(_get_env_value(env_vars, 'LARK_NO_PROXY', '0')),
        )

    def save(self, path: Path = ENV_FILE) -> None:
        """保存配置到 .env 文件"""
        ensure_user_data_dir()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_env_content())
        logger.info(f"环境变量配置已保存到 {path}")


def _parse_list(value: str) -> List[str]:
    """解析逗号分隔的列表"""
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def _parse_bool(value: str) -> bool:
    """解析布尔值"""
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _get_env_value(env_vars: dict, key: str, default: str = '') -> str:
    """优先读取新字段，不存在时回退旧字段"""
    if key in env_vars:
        return env_vars[key]
    for alias in _ENV_ALIASES.get(key, ()):
        if alias in env_vars:
            return env_vars[alias]
    return default


def load_env_config() -> EnvConfig:
    """加载环境变量配置"""
    return EnvConfig.from_env_file()


def save_env_config(config: EnvConfig) -> None:
    """保存环境变量配置"""
    config.save()
