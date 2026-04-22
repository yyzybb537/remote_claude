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
# 单张卡片最多容纳 N 个 blocks，超限时冻结+开新卡（值越小 → 活跃卡片越短，越贴近对话底部）
MAX_CARD_BLOCKS = int(os.getenv("MAX_CARD_BLOCKS", "15"))

# lark_client 日志级别（可选，默认 INFO）
# 支持: DEBUG / INFO / WARNING / ERROR
_LARK_LOG_LEVEL = os.getenv("LARK_LOG_LEVEL", "INFO").upper()
LARK_LOG_LEVEL = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}.get(_LARK_LOG_LEVEL, 20)  # 默认 INFO

# SOCKS 代理兼容（可选，默认 False）
# 系统有 SOCKS 代理但飞书可直连时，设为 1 绕过代理
LARK_NO_PROXY = os.getenv("LARK_NO_PROXY", "").strip() in ("1", "true", "yes")
