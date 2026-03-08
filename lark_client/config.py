"""
Lark 客户端配置
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 飞书应用配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# 用户白名单（逗号分隔的 open_id 列表）
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "").split(",")
ENABLE_USER_WHITELIST = os.getenv("ENABLE_USER_WHITELIST", "false").lower() == "true"

# 机器人名称（用于群聊命名）
BOT_NAME = os.getenv("BOT_NAME", "Claude")
