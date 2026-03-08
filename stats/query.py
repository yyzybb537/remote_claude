"""
StatsQuery：本地统计查询 + CLI 格式化输出
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional

_DB_PATH = Path.home() / ".local" / "share" / "remote-claude" / "stats.db"


def _get_conn() -> Optional[sqlite3.Connection]:
    if not _DB_PATH.exists():
        return None
    try:
        return sqlite3.connect(str(_DB_PATH))
    except Exception:
        return None


def _date_range(range_str: str) -> tuple[str, str]:
    """解析 range 字符串，返回 (start_date, end_date)"""
    end_date = time.strftime('%Y-%m-%d')
    if range_str == 'today' or range_str is None:
        start_date = end_date
    elif range_str.endswith('d'):
        days = int(range_str[:-1])
        start_date = time.strftime(
            '%Y-%m-%d', time.localtime(time.time() - days * 86400)
        )
    elif range_str.endswith('m'):
        months = int(range_str[:-1])
        start_date = time.strftime(
            '%Y-%m-%d', time.localtime(time.time() - months * 30 * 86400)
        )
    else:
        start_date = end_date
    return start_date, end_date


def _fmt_num(n: int) -> str:
    """格式化数字（千分位逗号）"""
    return f"{n:,}"


def query_summary(range_str: str = 'today', session_name: str = '',
                  detail: bool = False) -> str:
    """生成统计摘要字符串"""
    conn = _get_conn()
    if conn is None:
        return "暂无统计数据（数据库未初始化）"

    start_date, end_date = _date_range(range_str)

    # 构建查询条件
    where = "WHERE date >= ? AND date <= ?"
    params: list = [start_date, end_date]
    if session_name:
        where += " AND session_name = ?"
        params.append(session_name)

    def _sum(category: str, event: str) -> int:
        row = conn.execute(
            f"SELECT COALESCE(SUM(value), 0) FROM events "
            f"{where} AND category=? AND event=?",
            params + [category, event]
        ).fetchone()
        return row[0] if row else 0

    def _count(category: str, event: str) -> int:
        row = conn.execute(
            f"SELECT COUNT(*) FROM events "
            f"{where} AND category=? AND event=?",
            params + [category, event]
        ).fetchone()
        return row[0] if row else 0

    # 收集各类指标
    sess_start = _count('session', 'start')
    sess_attach = _count('session', 'attach')
    sess_end = _count('session', 'end')

    term_connect = _count('terminal', 'connect')
    term_input = _count('terminal', 'input')
    term_disconnect = _count('terminal', 'disconnect')

    lark_msg = _count('lark', 'message')
    lark_opt = _count('lark', 'option_select')
    lark_key = _count('lark', 'raw_key')
    lark_cmd = _count('lark', 'cmd')
    lark_attach = _count('lark', 'attach')
    lark_cmd_start = _count('lark', 'cmd_start')

    card_create = _count('card', 'create')
    card_update = _count('card', 'update')
    card_freeze = _count('card', 'freeze')
    card_fallback = _count('card', 'fallback')

    token_total = _sum('token', 'usage')

    err_card = _count('error', 'card_api')
    err_bridge = _count('error', 'bridge_send')
    err_total = err_card + err_bridge
    card_ops = card_create + card_update
    err_rate = f"{err_total / card_ops * 100:.2f}%" if card_ops else "0%"

    # 构建输出
    if start_date == end_date:
        date_label = start_date
    else:
        date_label = f"{start_date} ~ {end_date}"

    lines = [
        f"━━━━ Remote Claude 使用统计 ({date_label}) ━━━━",
        "",
        f"会话:  启动 {_fmt_num(sess_start)} | 连接 {_fmt_num(sess_attach + term_connect + lark_attach)} | 结束 {_fmt_num(sess_end)}",
        f"终端:  输入 {_fmt_num(term_input)} 次 | 连接 {_fmt_num(term_connect)} 次",
        f"飞书:  消息 {_fmt_num(lark_msg)} | 选项 {_fmt_num(lark_opt)} | 快捷键 {_fmt_num(lark_key)} | 命令 {_fmt_num(lark_cmd)}",
        f"卡片:  创建 {_fmt_num(card_create)} | 更新 {_fmt_num(card_update)} | 冻结 {_fmt_num(card_freeze)}",
        f"Token: ~{token_total / 1000:.1f}k",
        f"错误:  API {_fmt_num(err_card)} ({err_rate})",
    ]

    if detail:
        lines += [
            "",
            "── 详细分类 ──",
            f"飞书会话:  cmd_start {_fmt_num(lark_cmd_start)} | attach {_fmt_num(lark_attach)}",
            f"卡片降级:  {_fmt_num(card_fallback)}",
            f"桥接错误:  {_fmt_num(err_bridge)}",
        ]

    conn.close()
    return "\n".join(lines)


def reset_stats() -> str:
    """清空所有统计数据"""
    conn = _get_conn()
    if conn is None:
        return "暂无统计数据"
    try:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM daily_summary")
        conn.execute("DELETE FROM meta WHERE key != 'first_run'")
        conn.commit()
        conn.close()
        return "统计数据已清空"
    except Exception as e:
        return f"清空失败: {e}"
