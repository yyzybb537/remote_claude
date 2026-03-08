#!/usr/bin/env python3
"""
Remote Claude - 双端共享 Claude CLI 工具

命令:
  start <name>   启动新会话（在 tmux 中）
  attach <name>  连接到已有会话
  list           列出所有会话
  kill <name>    终止会话
  lark           飞书客户端管理（start/stop/restart/status）
"""

import argparse
import os
import sys
import subprocess
import time
import signal
from pathlib import Path

# 确保项目根目录在 sys.path 中，以便 import client / server 子模块
_PROJECT_ROOT = str(Path(__file__).parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.session import (
    get_socket_path, get_pid_file, ensure_socket_dir,
    get_tmux_session_name, tmux_session_exists, tmux_create_session,
    tmux_kill_session,
    list_active_sessions, is_session_active, cleanup_session,
    is_lark_running, get_lark_pid, get_lark_status, get_lark_pid_file,
    save_lark_status, cleanup_lark
)


# 获取脚本所在目录
SCRIPT_DIR = Path(__file__).parent.absolute()


def cmd_start(args):
    """启动新会话"""
    session_name = args.name

    # 检查会话是否已存在
    if is_session_active(session_name):
        print(f"错误: 会话 '{session_name}' 已存在")
        print(f"使用 'remote-claude attach {session_name}' 连接")
        return 1

    # 检查 tmux 会话是否存在
    if tmux_session_exists(session_name):
        print(f"错误: tmux 会话 'rc-{session_name}' 已存在")
        print("请先使用 'remote-claude kill {session_name}' 清理")
        return 1

    ensure_socket_dir()

    # 构建 server 命令
    server_script = SCRIPT_DIR / "server" / "server.py"
    claude_args = args.claude_args if args.claude_args else []
    claude_args_str = " ".join(f"'{arg}'" for arg in claude_args)
    debug_flag = " --debug-screen" if getattr(args, "debug_screen", False) else ""
    debug_verbose_flag = " --debug-verbose" if getattr(args, "debug_verbose", False) else ""

    # 捕获用户终端环境变量（tmux 会覆盖这些值，导致 Claude CLI 无法启用 kitty keyboard protocol）
    env_prefix = ""
    for key in ('TERM_PROGRAM', 'TERM_PROGRAM_VERSION', 'COLORTERM'):
        val = os.environ.get(key)
        if val:
            env_prefix += f"{key}='{val}' "

    server_cmd = f"{env_prefix}uv run --project '{SCRIPT_DIR}' python3 '{server_script}'{debug_flag}{debug_verbose_flag} -- '{session_name}' {claude_args_str}"

    print(f"启动会话: {session_name}")

    # 创建 tmux 会话，运行 server（detached，仅后台）
    if not tmux_create_session(session_name, server_cmd, detached=True):
        print("错误: 无法创建 tmux 会话")
        return 1

    # 等待 server 启动
    socket_path = get_socket_path(session_name)
    for _ in range(50):  # 最多等待 5 秒
        if socket_path.exists():
            break
        time.sleep(0.1)
    else:
        print("错误: Server 启动超时")
        tmux_kill_session(session_name)
        return 1

    print(f"会话已启动: rc-{session_name}")
    print(f"正在连接...")

    # 直接在前台运行 client（不走 tmux），让终端能力协商序列
    # （如 kitty keyboard protocol）直接在 Claude CLI ↔ 用户终端之间流通，
    # 从而支持 Shift+Enter 等扩展键
    from client.client import run_client
    run_client(session_name)

    return 0


def cmd_attach(args):
    """连接到已有会话"""
    session_name = args.name

    # 检查会话是否存在
    if not is_session_active(session_name):
        print(f"错误: 会话 '{session_name}' 不存在")
        print("使用 'remote-claude list' 查看可用会话")
        return 1

    print(f"连接到会话: {session_name}")

    # 直接运行 client（不通过 tmux）
    from client.client import run_client
    run_client(session_name)

    return 0


def cmd_list(args):
    """列出所有会话"""
    sessions = list_active_sessions()

    if not sessions:
        print("没有活跃的会话")
        return 0

    print("活跃会话:")
    print("-" * 60)
    print(f"{'名称':<20} {'PID':<10} {'tmux':<10} {'Socket'}")
    print("-" * 60)

    for s in sessions:
        tmux_status = "是" if s["tmux"] else "否"
        print(f"{s['name']:<20} {s['pid']:<10} {tmux_status:<10} {s['socket']}")

    print("-" * 60)
    print(f"共 {len(sessions)} 个会话")

    return 0


def cmd_kill(args):
    """终止会话"""
    session_name = args.name

    # 检查会话是否存在
    if not is_session_active(session_name) and not tmux_session_exists(session_name):
        print(f"错误: 会话 '{session_name}' 不存在")
        return 1

    print(f"终止会话: {session_name}")

    # 终止 tmux 会话
    if tmux_session_exists(session_name):
        tmux_kill_session(session_name)
        print("  - tmux 会话已终止")

    # 清理文件
    cleanup_session(session_name)
    print("  - 文件已清理")

    print("完成")
    return 0


def cmd_status(args):
    """显示会话状态（连接到会话并获取状态）"""
    session_name = args.name

    if not is_session_active(session_name):
        print(f"错误: 会话 '{session_name}' 不存在")
        return 1

    # TODO: 实现状态查询
    print(f"会话 '{session_name}' 状态:")
    print("  (功能开发中)")
    return 0


def cmd_lark_start(args):
    """启动飞书客户端（守护进程）"""
    if is_lark_running():
        print("飞书客户端已在运行")
        status = get_lark_status()
        if status:
            print(f"PID: {status['pid']}")
            print(f"启动时间: {status['start_time']}")
            print(f"运行时长: {status['uptime']}")
        print("\n使用 'remote-claude lark stop' 停止")
        return 1

    print("正在启动飞书客户端...")

    ensure_socket_dir()

    # 启动守护进程（使用 -m 模块方式运行，确保相对导入正常工作）
    log_file = SCRIPT_DIR / "lark_client.log"

    try:
        # 启动进程
        process = subprocess.Popen(
            ["uv", "run", "--project", str(SCRIPT_DIR), "python3", "-m", "lark_client.main"],
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            start_new_session=True,  # 创建新的进程组
            cwd=str(SCRIPT_DIR)
        )

        # 保存 PID
        pid = process.pid
        get_lark_pid_file().write_text(str(pid))
        save_lark_status(pid)

        # 等待一下确认启动成功
        time.sleep(1)

        if is_lark_running():
            print(f"✓ 飞书客户端已启动")
            print(f"  PID: {pid}")
            print(f"  日志: {log_file}")
            print(f"\n使用 'python3 remote_claude.py lark status' 查看状态")
            print(f"使用 'python3 remote_claude.py lark stop' 停止")
            return 0
        else:
            print("✗ 启动失败，请查看日志:")
            print(f"  tail -f {log_file}")
            cleanup_lark()
            return 1

    except Exception as e:
        print(f"✗ 启动失败: {e}")
        cleanup_lark()
        return 1


def cmd_lark_stop(args):
    """停止飞书客户端"""
    if not is_lark_running():
        print("飞书客户端未运行")
        cleanup_lark()
        return 0

    pid = get_lark_pid()
    if pid is None:
        print("无法获取 PID，清理残留文件")
        cleanup_lark()
        return 1

    print(f"正在停止飞书客户端 (PID: {pid})...")

    try:
        # 发送 SIGTERM 信号
        os.kill(pid, signal.SIGTERM)

        # 等待进程退出
        for i in range(50):  # 最多等待 5 秒
            if not is_lark_running():
                break
            time.sleep(0.1)
        else:
            # 如果还没退出，强制终止
            print("进程未响应，强制终止...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)

        if not is_lark_running():
            print("✓ 飞书客户端已停止")
            cleanup_lark()
            return 0
        else:
            print("✗ 无法停止进程，请手动终止:")
            print(f"  kill -9 {pid}")
            return 1

    except ProcessLookupError:
        print("进程已不存在，清理残留文件")
        cleanup_lark()
        return 0
    except Exception as e:
        print(f"✗ 停止失败: {e}")
        return 1


def cmd_lark_restart(args):
    """重启飞书客户端"""
    print("正在重启飞书客户端...")

    # 先停止
    if is_lark_running():
        cmd_lark_stop(args)
        time.sleep(1)

    # 再启动
    return cmd_lark_start(args)


def cmd_lark_status(args):
    """显示飞书客户端状态"""
    if not is_lark_running():
        print("飞书客户端未运行")
        print("\n使用 'python3 remote_claude.py lark start' 启动")
        return 0

    status = get_lark_status()
    if status is None:
        print("无法获取状态信息")
        return 1

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("飞书客户端状态")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"状态:     运行中 ✓")
    print(f"PID:      {status['pid']}")
    print(f"启动时间: {status['start_time']}")
    print(f"运行时长: {status['uptime']}")

    # 检查日志文件
    log_file = SCRIPT_DIR / "lark_client.log"
    if log_file.exists():
        print(f"日志文件: {log_file}")
        print(f"日志大小: {log_file.stat().st_size / 1024:.1f} KB")

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 显示最近的日志（最后 5 行）
    if log_file.exists():
        print("\n最近日志:")
        print("-" * 40)
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                for line in lines[-5:]:
                    print(f"  {line.rstrip()}")
        except Exception as e:
            print(f"  无法读取日志: {e}")
        print("-" * 40)

    return 0


def cmd_stats(args):
    """显示使用统计"""
    _PROJECT_ROOT = str(Path(__file__).parent)
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    from stats.query import query_summary, reset_stats
    from stats import report_daily

    if getattr(args, 'reset', False):
        print(reset_stats())
        return 0

    if getattr(args, 'report', False):
        report_daily()
        return 0

    range_str = getattr(args, 'range', 'today') or 'today'
    session_name = getattr(args, 'session', '') or ''
    detail = getattr(args, 'detail', False)

    print(query_summary(range_str=range_str, session_name=session_name, detail=detail))
    return 0


def cmd_lark(args):
    """飞书客户端管理（兼容旧命令）"""
    # 如果没有子命令，默认显示状态或启动
    if is_lark_running():
        return cmd_lark_status(args)
    else:
        print("飞书客户端未运行")
        print("\n可用命令:")
        print("  python3 remote_claude.py lark start    - 启动客户端")
        print("  python3 remote_claude.py lark stop     - 停止客户端")
        print("  python3 remote_claude.py lark restart  - 重启客户端")
        print("  python3 remote_claude.py lark status   - 查看状态")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Remote Claude - 双端共享 Claude CLI 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s start mywork              启动名为 mywork 的会话
  %(prog)s attach mywork             连接到 mywork 会话
  %(prog)s list                      列出所有会话
  %(prog)s kill mywork               终止 mywork 会话

飞书客户端:
  %(prog)s lark start                启动飞书客户端
  %(prog)s lark stop                 停止飞书客户端
  %(prog)s lark restart              重启飞书客户端
  %(prog)s lark status               查看飞书客户端状态

终端控制:
  Ctrl+D       断开连接

飞书命令:
  /attach <名称>   连接到会话
  /detach          断开连接
  /list            列出会话
  /help            显示帮助

使用统计:
  %(prog)s stats                     今日概览
  %(prog)s stats --range 7d          最近 7 天
  %(prog)s stats --detail            详细分类
  %(prog)s stats --session mywork    按会话筛选
  %(prog)s stats --reset             清空数据
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # start 命令
    start_parser = subparsers.add_parser("start", help="启动新会话")
    start_parser.add_argument("name", help="会话名称")
    start_parser.add_argument(
        "claude_args",
        nargs="*",
        help="传递给 Claude 的参数"
    )
    start_parser.add_argument(
        "--debug-screen",
        action="store_true",
        help="开启 pyte 屏幕快照调试日志（每次 flush 写入 /tmp/remote-claude/<name>_screen.log）"
    )
    start_parser.add_argument(
        "--debug-verbose",
        action="store_true",
        help="debug 日志输出完整诊断信息（indicator、repr 等），默认只输出 ansi_render"
    )
    start_parser.set_defaults(func=cmd_start)

    # attach 命令
    attach_parser = subparsers.add_parser("attach", help="连接到已有会话")
    attach_parser.add_argument("name", help="会话名称")
    attach_parser.set_defaults(func=cmd_attach)

    # list 命令
    list_parser = subparsers.add_parser("list", help="列出所有会话")
    list_parser.set_defaults(func=cmd_list)

    # kill 命令
    kill_parser = subparsers.add_parser("kill", help="终止会话")
    kill_parser.add_argument("name", help="会话名称")
    kill_parser.set_defaults(func=cmd_kill)

    # status 命令
    status_parser = subparsers.add_parser("status", help="显示会话状态")
    status_parser.add_argument("name", help="会话名称")
    status_parser.set_defaults(func=cmd_status)

    # lark 命令（带子命令）
    lark_parser = subparsers.add_parser("lark", help="飞书客户端管理")
    lark_subparsers = lark_parser.add_subparsers(dest="lark_command", help="飞书客户端操作")

    # lark start
    lark_start_parser = lark_subparsers.add_parser("start", help="启动飞书客户端")
    lark_start_parser.set_defaults(func=cmd_lark_start)

    # lark stop
    lark_stop_parser = lark_subparsers.add_parser("stop", help="停止飞书客户端")
    lark_stop_parser.set_defaults(func=cmd_lark_stop)

    # lark restart
    lark_restart_parser = lark_subparsers.add_parser("restart", help="重启飞书客户端")
    lark_restart_parser.set_defaults(func=cmd_lark_restart)

    # lark status
    lark_status_parser = lark_subparsers.add_parser("status", help="查看飞书客户端状态")
    lark_status_parser.set_defaults(func=cmd_lark_status)

    # 如果只输入 lark 没有子命令，使用默认处理
    lark_parser.set_defaults(func=cmd_lark)

    # stats 命令
    stats_parser = subparsers.add_parser("stats", help="查看使用统计")
    stats_parser.add_argument(
        "--range", metavar="RANGE", default="today",
        help="时间范围：today（默认）、7d、30d、90d"
    )
    stats_parser.add_argument(
        "--detail", action="store_true",
        help="显示详细分类"
    )
    stats_parser.add_argument(
        "--session", metavar="NAME", default="",
        help="按会话名筛选"
    )
    stats_parser.add_argument(
        "--reset", action="store_true",
        help="清空所有统计数据"
    )
    stats_parser.add_argument(
        "--report", action="store_true",
        help="立即触发 Mixpanel 聚合上报"
    )
    stats_parser.set_defaults(func=cmd_stats)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
