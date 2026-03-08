#!/bin/bash

# 飞书客户端管理功能测试脚本

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "飞书客户端管理功能测试"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. 检查初始状态（应该未运行）
echo "1. 检查初始状态..."
python3 remote_claude.py lark status
echo ""

# 2. 启动飞书客户端
echo "2. 启动飞书客户端..."
python3 remote_claude.py lark start
echo ""

# 3. 等待 2 秒
echo "3. 等待 2 秒..."
sleep 2
echo ""

# 4. 查看状态
echo "4. 查看状态..."
python3 remote_claude.py lark status
echo ""

# 5. 尝试重复启动（应该提示已在运行）
echo "5. 尝试重复启动（应该提示已在运行）..."
python3 remote_claude.py lark start || true
echo ""

# 6. 等待 5 秒，让日志积累一些内容
echo "6. 等待 5 秒，让日志积累..."
sleep 5
echo ""

# 7. 再次查看状态（运行时长应该增加）
echo "7. 再次查看状态..."
python3 remote_claude.py lark status
echo ""

# 8. 重启
echo "8. 重启飞书客户端..."
python3 remote_claude.py lark restart
echo ""

# 9. 等待 2 秒
echo "9. 等待 2 秒..."
sleep 2
echo ""

# 10. 查看状态（启动时间应该更新）
echo "10. 查看状态（启动时间应该更新）..."
python3 remote_claude.py lark status
echo ""

# 11. 停止
echo "11. 停止飞书客户端..."
python3 remote_claude.py lark stop
echo ""

# 12. 确认已停止
echo "12. 确认已停止..."
python3 remote_claude.py lark status
echo ""

# 13. 检查残留文件（应该已清理）
echo "13. 检查残留文件..."
if [ -f /tmp/remote-claude/lark.pid ]; then
    echo "  ✗ lark.pid 未清理"
else
    echo "  ✓ lark.pid 已清理"
fi

if [ -f /tmp/remote-claude/lark.status ]; then
    echo "  ✗ lark.status 未清理"
else
    echo "  ✓ lark.status 已清理"
fi

if [ -f lark_client.log ]; then
    echo "  ✓ 日志文件存在: lark_client.log"
    echo "  日志大小: $(ls -lh lark_client.log | awk '{print $5}')"
else
    echo "  ✗ 日志文件不存在"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "测试完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
