"""
Lark 客户端配置
"""

import os
from pathlib import Path
from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.session import USER_DATA_DIR, get_env_file

# 加载 .env 文件，优先从 ~/.remote-claude/.env 读取
_env_file = get_env_file()
_old_env_file = Path(__file__).resolve().parent.parent / ".env"

if not _env_file.exists() and _old_env_file.exists():
    import shutil
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(_old_env_file), str(_env_file))
    print(f"[config] 已将 .env 迁移到 {_env_file}")

load_dotenv(_env_file)


def _get_env_value(key: str, default: str = "") -> str:
    aliases = {
        "ALLOWED_USERS": ("USER_WHITELIST",),
        "GROUP_NAME_PREFIX": ("GROUP_PREFIX",),
        "LARK_LOG_LEVEL": ("LOG_LEVEL",),
        "LARK_NO_PROXY": ("NO_PROXY",),
    }
    value = os.getenv(key)
    if value not in (None, ""):
        return value
    for alias in aliases.get(key, ()):
        alias_value = os.getenv(alias)
        if alias_value not in (None, ""):
            return alias_value
    return default


# 飞书应用配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# 用户白名单（逗号分隔的 open_id 列表）
ALLOWED_USERS = _get_env_value("ALLOWED_USERS", "").split(",")
ENABLE_USER_WHITELIST = _get_env_value("ENABLE_USER_WHITELIST", "false").lower() == "true"

# 机器人名称（用于群聊命名）
BOT_NAME = os.getenv("BOT_NAME", "Claude")

# 群聊名称前缀（格式：{GROUP_NAME_PREFIX}{dir}-{HH-MM}）
GROUP_NAME_PREFIX = _get_env_value("GROUP_NAME_PREFIX", "【Remote-Claude】")

# 流式卡片配置
MAX_CARD_BLOCKS = int(os.getenv("MAX_CARD_BLOCKS", "50"))

# lark_client 日志级别（可选，默认 WARNING）
# 支持: DEBUG / INFO / WARNING / ERROR
_LARK_LOG_LEVEL = _get_env_value("LARK_LOG_LEVEL", "WARNING").upper()
_LOG_LEVEL_MAP = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}
LARK_LOG_LEVEL = _LOG_LEVEL_MAP.get(_LARK_LOG_LEVEL, _LOG_LEVEL_MAP["WARNING"])

# SOCKS 代理兼容（可选，默认 False）
# 系统有 SOCKS 代理但飞书可直连时，设为 1 绕过代理
LARK_NO_PROXY = _get_env_value("LARK_NO_PROXY", "").strip() in ("1", "true", "yes")
