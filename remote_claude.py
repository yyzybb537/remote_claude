#!/usr/bin/env python3
"""
Remote Claude - 双端共享 Claude CLI 工具

命令:
  start <name>       启动新会话（在 tmux 中）
  attach <name>      连接到已有会话
  list               列出所有会话
  kill <name>        终止会话
  status <name>      显示会话状态
  lark               飞书客户端管理（start/stop/restart/status）
  stats              查看使用统计
  update             更新 remote-claude 到最新版本
"""

import argparse
import logging
import os
import sys
import subprocess
import time
import json
import signal
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中，以便 import client / server 子模块
_PROJECT_ROOT = str(Path(__file__).parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.session import (
    get_socket_path, ensure_socket_dir, tmux_session_exists, tmux_create_session,
    tmux_kill_session,
    list_active_sessions, is_session_active, cleanup_session,
    is_lark_running, get_lark_pid, get_lark_status, get_lark_pid_file,
    save_lark_status, cleanup_lark,
    USER_DATA_DIR, ensure_user_data_dir, get_lark_log_file,
    get_env_snapshot_path,
)
from server.biz_enum import CliType

# 获取脚本所在目录
SCRIPT_DIR = Path(__file__).parent.absolute()

# 读取版本号（仅 import 时读取一次）
try:
    import json as _json

    _VERSION = _json.loads((SCRIPT_DIR / "package.json").read_text())["version"]
except (OSError, json.JSONDecodeError, KeyError):
    _VERSION = "unknown"


def cmd_start(args):
    """启动新会话"""
    original_session_name = args.name

    # 使用 resolve_session_name() 处理名称截断和冲突
    # 注意: resolve_session_name 内部已会调用 save_runtime_config，无需重复保存
    from utils.runtime_config import load_runtime_config
    config = load_runtime_config()
    from utils.session import resolve_session_name
    session_name = resolve_session_name(original_session_name, config)

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

    # 将当前 shell 的完整环境变量保存到快照文件（权限 0600 防止密钥泄露）
    # tmux new-session 继承的是 tmux 服务器的全局环境，而非调用方 shell 的环境，
    # 通过快照文件将完整环境传递给 server.py 的 _start_pty()
    import json
    env_snapshot_path = get_env_snapshot_path(session_name)
    env_fd = os.open(str(env_snapshot_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(env_fd, 'w') as f:
        json.dump(dict(os.environ), f)

    # 构建 server 命令
    server_script = SCRIPT_DIR / "server" / "server.py"
    cli_args = args.cli_args if args.cli_args else []
    cli_args_str = " ".join(f"'{arg}'" for arg in cli_args)
    debug_flag = " --debug-screen" if args.debug_screen else ""
    debug_verbose_flag = " --debug-verbose" if args.debug_verbose else ""
    cli_type_flag = f" --cli-type {args.cli}"

    # 捕获用户终端环境变量（tmux 会覆盖这些值，导致 Claude CLI 无法启用 kitty keyboard protocol）
    env_prefix = ""
    for key in ('TERM_PROGRAM', 'TERM_PROGRAM_VERSION', 'COLORTERM'):
        val = os.environ.get(key)
        if val:
            env_prefix += f"{key}='{val}' "

    # 远程模式参数
    remote_flag = ""
    if args.remote:
        remote_flag = f" --remote --remote-port {args.remote_port} --remote-host {args.remote_host}"

    server_cmd = f"{env_prefix}uv run --project '{SCRIPT_DIR}' python3 '{server_script}'{debug_flag}{debug_verbose_flag}{cli_type_flag}{remote_flag} -- '{session_name}' {cli_args_str}"

    # 配置启动日志（写文件 + stdout）
    _log_path = USER_DATA_DIR / "startup.log"
    _start_logger = logging.getLogger('Start')
    if not _start_logger.handlers:
        _handler_file = logging.FileHandler(_log_path, encoding="utf-8")
        _handler_file.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        _start_logger.addHandler(_handler_file)
        _start_logger.setLevel(logging.INFO)
        _start_logger.propagate = False

    start_time = datetime.now()
    _start_logger.info(f"启动会话: {session_name}")
    _start_logger.info(f"server_cmd: {server_cmd}")

    # 创建 tmux 会话，运行 server（detached，仅后台）
    if not tmux_create_session(session_name, server_cmd, detached=True):
        print("错误: 无法创建 tmux 会话")
        return 1

    # 等待 server 启动（超时时间可通过环境变量 STARTUP_TIMEOUT 配置，默认 5 秒）
    try:
        startup_timeout = int(os.environ.get("STARTUP_TIMEOUT", "5"))
        if startup_timeout < 1:
            startup_timeout = 5
    except ValueError:
        startup_timeout = 5

    socket_path = get_socket_path(session_name)
    wait_interval = 0.1  # 100ms
    max_attempts = int(startup_timeout / wait_interval)
    for i in range(max_attempts):
        if socket_path.exists():
            break
        # 检查 tmux 会话是否仍在运行（server 启动失败时会退出）
        if not tmux_session_exists(session_name):
            print("错误: Server 进程已退出")
            # 输出启动日志辅助诊断
            if _log_path.exists():
                lines = []
                for line in _log_path.read_text(encoding="utf-8").splitlines():
                    try:
                        ts = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S.%f")
                        if ts >= start_time:
                            lines.append(line)
                    except ValueError:
                        if lines:  # 多行日志的续行，附到上一条
                            lines.append(line)
                if lines:
                    print(f"--- Server 日志 ({_log_path}) ---")
                    print("\n".join(lines))
                    print("-------------------")
            return 1
        time.sleep(wait_interval)
        if (i + 1) % 10 == 0:
            elapsed = (i + 1) // 10
            print(f"等待 Server 启动... ({elapsed}s)")
    else:
        print(f"错误: Server 启动超时 ({startup_timeout}s)")
        # 过滤出本次启动后的日志行
        if _log_path.exists():
            lines = []
            for line in _log_path.read_text(encoding="utf-8").splitlines():
                try:
                    ts = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S.%f")
                    if ts >= start_time:
                        lines.append(line)
                except ValueError:
                    if lines:  # 多行日志的续行，附到上一条
                        lines.append(line)
            if lines:
                print(f"--- Server 日志 ({_log_path}) ---")
                print("\n".join(lines))
                print("-------------------")
        tmux_kill_session(session_name)
        return 1

    # 再次检查 tmux 会话（socket 可能刚创建就被 server 关闭）
    if not tmux_session_exists(session_name):
        print("错误: Server 进程已退出")
        return 1

    print(f"会话已启动: rc-{session_name}")
    print(f"正在连接...")

    # 直接在前台运行 client（不走 tmux），让终端能力协商序列
    # （如 kitty keyboard protocol）直接在 Claude CLI ↔ 用户终端之间流通，
    # 从而支持 Shift+Enter 等扩展键
    from client.client import run_client
    return run_client(session_name)


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
    return run_client(session_name)


def cmd_list(args):
    """列出所有会话"""
    sessions = list_active_sessions()

    if not sessions:
        print("没有活跃的会话")
        return 0

    # 加载运行时配置获取会话映射
    from utils.runtime_config import load_runtime_config
    config = load_runtime_config()

    # ANSI 颜色码
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    RESET = "\033[0m"

    print("活跃会话:")
    print("-" * 80)
    print(f"{'类型':<8} {'PID':<8} {'tmux':<6} {'名称':<20} {'原始路径'}")
    print("-" * 80)

    for s in sessions:
        tmux_status = "是" if s["tmux"] else "否"
        cli_type = s.get('cli_type', 'claude')
        session_name = s['name']
        # 从映射中获取原始路径
        original_path = config.get_session_mapping(session_name) or "-"

        # 根据类型选择颜色
        if cli_type == 'codex':
            cli_colored = f"{GREEN}{cli_type}{RESET}"
        else:
            cli_colored = f"{YELLOW}{cli_type}{RESET}"
        # 带颜色的字段需要单独计算宽度
        padding = " " * (8 - len(cli_type))
        name_display = session_name[:18] + ".." if len(session_name) > 20 else session_name
        path_display = original_path[:50] + ".." if len(original_path) > 52 else original_path
        print(f"{cli_colored}{padding} {s['pid']:<8} {tmux_status:<6} {name_display:<20} {path_display}")

    print("-" * 80)
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

    # 删除会话映射
    from utils.runtime_config import remove_session_mapping
    remove_session_mapping(session_name)

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

    # 检测残留的 bak 文件
    from utils.runtime_config import check_stale_backup, prompt_backup_action, cleanup_backup_files
    bak_file = check_stale_backup()
    if bak_file:
        action = prompt_backup_action(bak_file)
        if action == 'overwrite':
            # 从 bak 恢复
            print("正在从备份恢复配置...")
            try:
                # bak_file.name = "config.json.bak.20260320_143015" ->. split('.bak')[0] = "config.json"
                original_file = bak_file.name.split('.bak')[0]
                original_path = bak_file.parent / original_file
                import shutil
                shutil.copy2(bak_file, original_path)
                print(f"已从备份恢复: {original_path}")
                bak_file.unlink()
            except (OSError, shutil.Error) as e:
                print(f"恢复备份失败: {e}")
                return 1
        else:
            # 跳过：删除 bak 文件
            bak_file.unlink()
            print(f"已删除备份文件: {bak_file}")

    # 清理可能残留的其他 bak 文件
    cleanup_backup_files()

    print("正在启动飞书客户端...")

    ensure_socket_dir()
    ensure_user_data_dir()

    # 启动守护进程（使用 -m 模块方式运行，确保相对导入正常工作）
    log_file = get_lark_log_file()

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
    except PermissionError as e:
        print(f"✗ 权限不足，无法停止进程: {e}")
        return 1
    except OSError as e:
        print(f"✗ 停止失败（系统错误）: {e}")
        return 1
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
    print(f"版本:     v{_VERSION}")
    print(f"PID:      {status['pid']}")
    print(f"启动时间: {status['start_time']}")
    print(f"运行时长: {status['uptime']}")

    # 检查日志文件
    log_file = get_lark_log_file()
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
        except OSError as e:
            print(f"  无法读取日志（系统错误）: {e}")
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


def cmd_update(args):
    """更新 remote-claude 到最新版本"""
    import subprocess as _sp

    git_dir = SCRIPT_DIR / ".git"
    if git_dir.exists():
        # 源码安装：git pull 更新
        print(f"检测到源码安装（{SCRIPT_DIR}）")
        print("正在更新...")
        result = _sp.run(["git", "pull"], cwd=SCRIPT_DIR)
        if result.returncode != 0:
            print("❌ git pull 失败")
            return 1
        # 同步 Python 依赖
        _sp.run(["uv", "sync"], cwd=SCRIPT_DIR)
        print("✅ 更新完成")
    else:
        # npm 安装：区分本地和全局
        install_dir_str = str(SCRIPT_DIR)
        if "node_modules" in install_dir_str:
            # 本地 npm 安装：找到项目根目录（node_modules 的上两级）
            project_root = SCRIPT_DIR.parent.parent
            print(f"检测到 npm 本地安装（{project_root}）")
            print("正在更新...")
            result = _sp.run(["npm", "install", "remote-claude@latest"], cwd=project_root)
        else:
            # 全局 npm 安装
            print("检测到 npm 全局安装")
            print("正在更新...")
            result = _sp.run(["npm", "install", "-g", "remote-claude@latest"])
        if result.returncode != 0:
            print("❌ npm 更新失败")
            return 1
        print("✅ 更新完成，请重启终端使新版本生效")
    return 0


def cmd_connect(args):
    """连接到远程会话"""
    from client.http_client import run_http_client

    # 解析 host/session/port
    host = args.host
    session = args.session
    port = args.port or 8765
    token = args.token

    # 支持 host:port/session 格式
    if '/' in host:
        parts = host.split('/')
        host_part = parts[0]
        session = parts[1] if len(parts) > 1 else session
        if ':' in host_part:
            host, port_str = host_part.split(':')
            port = int(port_str)

    if not session:
        print("错误: 请指定会话名称")
        return 1

    return run_http_client(host, session, token, port)


def cmd_remote(args):
    """远程控制命令"""
    from client.http_client import HTTPClient
    import asyncio

    host = args.host
    session = args.session
    token = args.token
    port = args.port or 8765

    # 解析 host:port/session 格式
    if '/' in host:
        parts = host.split('/')
        host_part = parts[0]
        session = parts[1] if len(parts) > 1 else session
        if ':' in host_part:
            host, port_str = host_part.split(':')
            port = int(port_str)

    if not session:
        print("错误: 请指定会话名称")
        return 1

    client = HTTPClient(host, session, token, port)

    async def run_action():
        try:
            result = await client.send_control(args.action)
            if result['success']:
                print(f"✓ {result['message']}")
                return 0
            else:
                print(f"✗ {result['message']}")
                return 1
        except Exception as e:
            print(f"✗ 连接失败: {e}")
            return 1

    return asyncio.run(run_action())


def cmd_token(args):
    """显示会话 token"""
    from server.token_manager import TokenManager

    manager = TokenManager(args.session, USER_DATA_DIR)
    token = manager.get_or_create_token()
    print(f"Session: {args.session}")
    print(f"Token: {token}")
    return 0


def cmd_regenerate_token(args):
    """重新生成 token"""
    from server.token_manager import TokenManager

    manager = TokenManager(args.session, USER_DATA_DIR)
    old_token = manager._token
    new_token = manager.regenerate_token()
    print(f"Session: {args.session}")
    print(f"旧 Token 已失效")
    print(f"新 Token: {new_token}")
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


def cmd_config(args):
    """配置管理（无子命令时显示帮助）"""
    print("配置管理命令:")
    print("\n  remote-claude config reset [选项]")
    print()
    print("选项:")
    print("  --all       重置全部配置文件（config.json + runtime.json）")
    print("  --config    仅重置用户配置（config.json）")
    print("  --runtime   仅重置运行时配置（runtime.json）")
    print()
    print("不带选项时进入交互式选择模式")
    return 0


def cmd_config_reset(args):
    """配置重置命令"""
    from utils.runtime_config import (
        USER_DATA_DIR,
        USER_CONFIG_FILE,
        RUNTIME_CONFIG_FILE,
        USER_CONFIG_LOCK_FILE,
        RUNTIME_LOCK_FILE,
        cleanup_backup_files,
        ConfigType,
    )

    # 确定要重置的配置文件
    reset_all = getattr(args, 'all', False)
    reset_config = getattr(args, 'config_only', False)
    reset_runtime = getattr(args, 'runtime_only', False)

    if not (reset_all or reset_config or reset_runtime):
        # 交互式选择
        print("选择要重置的配置：")
        print("1. 全部配置（config.json + runtime.json）")
        print("2. 仅用户配置（config.json）")
        print("3. 仅运行时配置（runtime.json）")
        print("4. 取消")
        try:
            choice = input("请选择 [1-4]: ").strip()
        except EOFError:
            print("\n已取消")
            return 1

        if choice == '1':
            reset_all = True
        elif choice == '2':
            reset_config = True
        elif choice == '3':
            reset_runtime = True
        else:
            print("已取消")
            return 0

    config_template = SCRIPT_DIR / "resources" / "defaults" / "config.default.json"
    runtime_template = SCRIPT_DIR / "resources" / "defaults" / "runtime.default.json"

    if not config_template.exists():
        print(f"✗ 未找到配置模板: {config_template}")
        return 1

    if not runtime_template.exists():
        print(f"✗ 未找到运行时模板: {runtime_template}")
        return 1

    # 执行重置
    try:
        if reset_all or reset_config:
            USER_CONFIG_FILE.write_text(config_template.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"✓ 已重置用户配置: {USER_CONFIG_FILE}")

        if reset_all or reset_runtime:
            RUNTIME_CONFIG_FILE.write_text(runtime_template.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"✓ 已重置运行时配置: {RUNTIME_CONFIG_FILE}")

        # 清理副作用文件（锁文件、备份文件），范围与重置配置保持一致
        # 状态文件（lark.pid、lark.status）不清理
        if reset_all or reset_config:
            try:
                USER_CONFIG_LOCK_FILE.unlink()
                print(f"✓ 已清理锁文件: {USER_CONFIG_LOCK_FILE}")
            except FileNotFoundError:
                pass
            cleanup_backup_files(ConfigType.CONFIG)
            print("✓ 已清理 config 备份文件")

        if reset_all or reset_runtime:
            try:
                RUNTIME_LOCK_FILE.unlink()
                print(f"✓ 已清理锁文件: {RUNTIME_LOCK_FILE}")
            except FileNotFoundError:
                pass
            cleanup_backup_files(ConfigType.RUNTIME)
            print("✓ 已清理 runtime 备份文件")

        print()
        print("配置重置完成")
        return 0

    except PermissionError:
        print(f"✗ 权限不足，无法写入配置目录: {USER_DATA_DIR}")
        return 1
    except OSError as e:
        print(f"✗ 重置失败（系统错误）: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Remote Claude - 双端共享 Claude CLI 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s start mywork              启动名为 mywork 的会话
  %(prog)s start mywork --cli codex  启动 codex 会话
  %(prog)s attach mywork             连接到 mywork 会话
  %(prog)s list                      列出所有会话
  %(prog)s kill mywork               终止 mywork 会话
  %(prog)s status mywork             显示 mywork 会话状态

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

更新:
  %(prog)s update                    更新到最新版本

远程连接:
  %(prog)s start mywork --remote     启动会话并开启远程连接
  %(prog)s token mywork              显示会话 token
  %(prog)s connect myserver mywork --token <TOKEN>  连接远程会话
  %(prog)s remote shutdown myserver mywork --token <TOKEN>  远程关闭会话
"""
    )

    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"remote-claude v{_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # start 命令
    start_parser = subparsers.add_parser("start", help="启动新会话")
    start_parser.add_argument("name", help="会话名称")
    start_parser.add_argument(
        "cli_args",
        nargs="*",
        help="传递给 CLI 的参数"
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
    start_parser.add_argument(
        "--cli",
        default=CliType.CLAUDE,
        choices=[CliType.CLAUDE, CliType.CODEX],
        help="后端 CLI 类型（默认 claude）"
    )
    start_parser.add_argument(
        "--remote",
        action="store_true",
        help="启用远程连接模式"
    )
    start_parser.add_argument(
        "--remote-port",
        type=int,
        default=8765,
        help="远程连接端口（默认: 8765）"
    )
    start_parser.add_argument(
        "--remote-host",
        default="0.0.0.0",
        help="远程连接监听地址（默认: 0.0.0.0）"
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

    # config 命令（带子命令）
    config_parser = subparsers.add_parser("config", help="配置管理")
    config_subparsers = config_parser.add_subparsers(dest="config_command", help="配置操作")

    # config reset
    config_reset_parser = config_subparsers.add_parser("reset", help="重置配置文件")
    config_reset_parser.add_argument(
        "--all", action="store_true",
        help="重置全部配置文件"
    )
    config_reset_parser.add_argument(
        "--config", dest="config_only", action="store_true",
        help="仅重置用户配置"
    )
    config_reset_parser.add_argument(
        "--runtime", dest="runtime_only", action="store_true",
        help="仅重置运行时配置"
    )
    config_reset_parser.set_defaults(func=cmd_config_reset)

    # 如果只输入 config 没有子命令
    config_parser.set_defaults(func=cmd_config)

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

    # update 命令
    update_parser = subparsers.add_parser("update", help="更新 remote-claude 到最新版本")
    update_parser.set_defaults(func=cmd_update)

    # connect 命令
    connect_parser = subparsers.add_parser("connect", help="连接到远程会话")
    connect_parser.add_argument("host", help="服务器地址（或 host:port/session）")
    connect_parser.add_argument("session", nargs="?", help="会话名称")
    connect_parser.add_argument("--token", required=True, help="认证 token")
    connect_parser.add_argument("--port", type=int, help="端口（默认: 8765）")
    connect_parser.set_defaults(func=cmd_connect)

    # remote 命令
    remote_parser = subparsers.add_parser("remote", help="远程控制")
    remote_parser.add_argument("action", choices=["shutdown", "restart", "update"],
                               help="控制命令")
    remote_parser.add_argument("host", help="服务器地址（或 host:port/session）")
    remote_parser.add_argument("session", nargs="?", help="会话名称")
    remote_parser.add_argument("--token", required=True, help="认证 token")
    remote_parser.add_argument("--port", type=int, help="端口")
    remote_parser.set_defaults(func=cmd_remote)

    # token 命令
    token_parser = subparsers.add_parser("token", help="显示会话 token")
    token_parser.add_argument("session", help="会话名称")
    token_parser.set_defaults(func=cmd_token)

    # regenerate-token 命令
    regen_parser = subparsers.add_parser("regenerate-token", help="重新生成 token")
    regen_parser.add_argument("session", help="会话名称")
    regen_parser.set_defaults(func=cmd_regenerate_token)

    args, remaining = parser.parse_known_args()

    if args.command is None:
        parser.print_help()
        return 0

    # 将剩余参数合并到 cli_args（支持 cx/cdx 脚本中使用 -- 分隔符）
    if args.command == "start" and hasattr(args, 'cli_args'):
        args.cli_args = args.cli_args + remaining

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
