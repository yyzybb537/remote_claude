#!/usr/bin/env python3
"""
发送飞书文本消息到指定群/用户
用法: uv run python3 tools/send_lark_msg.py <chat_id> <message>
"""
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path.home() / ".remote-claude" / ".env")


def _get_env_value(key: str, default: str = "") -> str:
    aliases = {
        "LARK_LOG_LEVEL": ("LOG_LEVEL",),
        "LARK_NO_PROXY": ("NO_PROXY",),
        "GROUP_NAME_PREFIX": ("GROUP_PREFIX",),
        "ALLOWED_USERS": ("USER_WHITELIST",),
    }
    value = os.getenv(key)
    if value not in (None, ""):
        return value
    for alias in aliases.get(key, ()):
        alias_value = os.getenv(alias)
        if alias_value not in (None, ""):
            return alias_value
    return default

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody


def send_text(chat_id: str, text: str) -> bool:
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        print("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")
        return False

    client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

    request = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
        .msg_type("text")
        .content(json.dumps({"text": text}))
        .build()
    ).build()

    # lark-oapi SDK 的 message.create 是同步方法，直接调用即可
    resp = client.im.v1.message.create(request)
    if resp.success():
        print(f"✅ 发送成功")
        return True
    else:
        print(f"❌ 发送失败: {resp.code} {resp.msg}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: uv run python3 tools/send_lark_msg.py <chat_id> <message>")
        sys.exit(1)
    chat_id = sys.argv[1]
    message = " ".join(sys.argv[2:])
    success = send_text(chat_id, message)
    sys.exit(0 if success else 1)
