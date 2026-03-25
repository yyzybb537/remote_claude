#!/bin/bash

# 飞书客户端管理功能测试脚本
# 用法: 从项目根目录运行 scripts/test_lark_management.sh

set -e

# 获取项目根目录（脚本位于 scripts/ 目录）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 引入共享脚本（提供颜色定义、打印函数、uv 管理函数）
# _common.sh 会自动从 runtime.json 读取 uv_path，并设置 PATH
. "$PROJECT_ROOT/scripts/_common.sh"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "飞书客户端管理功能测试"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. 检查初始状态（应该未运行）
echo "1. 检查初始状态..."
uv run remote-claude lark status
echo ""

# 2. 启动飞书客户端
echo "2. 启动飞书客户端..."
uv run remote-claude lark start
echo ""

# 3. 等待 2 秒
echo "3. 等待 2 秒..."
sleep 2
echo ""

# 4. 查看状态
echo "4. 查看状态..."
uv run remote-claude lark status
echo ""

# 5. 尝试重复启动（应该提示已在运行）
echo "5. 尝试重复启动（应该提示已在运行）..."
uv run remote-claude lark start || true
echo ""

# 6. 等待 5 秒，让日志积累一些内容
echo "6. 等待 5 秒，让日志积累..."
sleep 5
echo ""

# 7. 再次查看状态（运行时长应该增加）
echo "7. 再次查看状态..."
uv run remote-claude lark status
echo ""

# 8. 重启
echo "8. 重启飞书客户端..."
uv run remote-claude lark restart
echo ""

# 9. 等待 2 秒
echo "9. 等待 2 秒..."
sleep 2
echo ""

# 10. 查看状态（启动时间应该更新）
echo "10. 查看状态（启动时间应该更新）..."
uv run remote-claude lark status
echo ""

# 11. 停止
echo "11. 停止飞书客户端..."
uv run remote-claude lark stop
echo ""

# 12. 确认已停止
echo "12. 确认已停止..."
uv run remote-claude lark status
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

if [ -f "$HOME/.remote-claude/lark_client.log" ]; then
    echo "  ✓ 日志文件存在: ~/.remote-claude/lark_client.log"
    echo "  日志大小: $(ls -lh "$HOME/.remote-claude/lark_client.log" | awk '{print $5}')"
else
    echo "  ✗ 日志文件不存在"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "测试完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
