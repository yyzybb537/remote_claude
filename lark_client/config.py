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

# 飞书应用配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# 用户白名单（逗号分隔的 open_id 列表）
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "").split(",")
ENABLE_USER_WHITELIST = os.getenv("ENABLE_USER_WHITELIST", "false").lower() == "true"

# 机器人名称（用于群聊命名）
BOT_NAME = os.getenv("BOT_NAME", "Claude")

# 群聊名称前缀（格式：{GROUP_NAME_PREFIX}{dir}-{HH-MM}）
GROUP_NAME_PREFIX = os.getenv("GROUP_NAME_PREFIX", "【Remote-Claude】")

# 流式卡片配置
MAX_CARD_BLOCKS = int(os.getenv("MAX_CARD_BLOCKS", "50"))

# lark_client 日志级别（可选，默认 WARNING）
# 支持: DEBUG / INFO / WARNING / ERROR
# 默认 WARNING 以减少生产环境日志噪音，调试时可设为 DEBUG 或 INFO
_LARK_LOG_LEVEL = os.getenv("LARK_LOG_LEVEL", "WARNING").upper()
_LOG_LEVEL_MAP = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}
if _LARK_LOG_LEVEL in _LOG_LEVEL_MAP:
    LARK_LOG_LEVEL = _LOG_LEVEL_MAP[_LARK_LOG_LEVEL]
else:
    # 无效日志级别，输出警告并回退到 WARNING
    LARK_LOG_LEVEL = 30
    # 延迟输出警告（在 logging 配置后）
    import logging
    logging.getLogger('LarkConfig').warning(
        f"无效的日志级别 '{_LARK_LOG_LEVEL}'，回退到 WARNING。"
        f"有效值: DEBUG, INFO, WARNING, ERROR"
    )

# SOCKS 代理兼容（可选，默认 False）
# 系统有 SOCKS 代理但飞书可直连时，设为 1 绕过代理
LARK_NO_PROXY = os.getenv("LARK_NO_PROXY", "").strip() in ("1", "true", "yes")
