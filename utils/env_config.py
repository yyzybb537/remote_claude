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


@dataclass
class EnvConfig:
    """环境变量配置"""
    # 必填
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    # 可选
    user_whitelist: List[str] = field(default_factory=list)
    group_prefix: str = "Remote-Claude"
    log_level: str = "INFO"
    startup_timeout: int = 5
    max_card_blocks: int = 50
    no_proxy: bool = False

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
            f"USER_WHITELIST={','.join(self.user_whitelist)}",
            f"GROUP_PREFIX={self.group_prefix}",
            f"LOG_LEVEL={self.log_level}",
            f"STARTUP_TIMEOUT={self.startup_timeout}",
            f"MAX_CARD_BLOCKS={self.max_card_blocks}",
            f"NO_PROXY={'1' if self.no_proxy else '0'}",
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
            user_whitelist=_parse_list(env_vars.get('USER_WHITELIST', '')),
            group_prefix=env_vars.get('GROUP_PREFIX', 'Remote-Claude'),
            log_level=env_vars.get('LOG_LEVEL', 'INFO'),
            startup_timeout=int(env_vars.get('STARTUP_TIMEOUT', '5')),
            max_card_blocks=int(env_vars.get('MAX_CARD_BLOCKS', '50')),
            no_proxy=env_vars.get('NO_PROXY', '0') == '1',
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


def load_env_config() -> EnvConfig:
    """加载环境变量配置"""
    return EnvConfig.from_env_file()


def save_env_config(config: EnvConfig) -> None:
    """保存环境变量配置"""
    config.save()
