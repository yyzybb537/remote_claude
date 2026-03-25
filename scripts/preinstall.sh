#!/bin/sh
# 升级前尝试停止旧的 lark 客户端（失败不报错）
# 先检查命令是否存在，避免命令不存在时的错误输出
if command -v remote-claude >/dev/null 2>&1; then
    remote-claude lark stop 2>/dev/null || true
fi
exit 0
