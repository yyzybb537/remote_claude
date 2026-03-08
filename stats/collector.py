"""
StatsCollector：事件收集器

- 内存队列（deque）接收 track() 调用（O(1)，无 I/O）
- 每 10 秒或满 50 条时批量写入 SQLite（WAL 模式）
- 每日聚合上报 Mixpanel（~22 条/天）
- 所有异常均被捕获，绝不影响主流程
"""

import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

from .machine import get_machine_id, get_machine_info

# SQLite 数据库路径（持久化，不受 /tmp 清理影响）
_DB_DIR = Path.home() / ".local" / "share" / "remote-claude"
_DB_PATH = _DB_DIR / "stats.db"

# 批量写入阈值
_FLUSH_INTERVAL = 10.0   # 秒
_FLUSH_BATCH = 50        # 条

# 数据保留天数
_EVENTS_RETENTION = 90   # 天
_SUMMARY_RETENTION = 365 # 天


class StatsCollector:
    """事件收集器：内存队列 + SQLite 批量写入 + 定时 Mixpanel 聚合上报"""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._queue: deque = deque(maxlen=10000)
        self._lock = threading.Lock()
        self._machine_id = get_machine_id()
        self._conn: Optional[sqlite3.Connection] = None
        self._mp = None              # Mixpanel 实例，延迟初始化
        self._mp_token: str = ""
        self._last_flush = 0.0
        self._last_report_date: str = ""
        self._is_first_run = False   # 是否首次运行（需上报 install 事件）

        if self._enabled:
            self._init_db()
            self._check_first_run()
            # 后台线程定时 flush
            t = threading.Thread(target=self._flush_loop, daemon=True)
            t.start()

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def track(self, category: str, event: str, session_name: str = '',
              chat_id: str = '', value: int = 1, detail: str = '') -> None:
        """记录事件到本地（非阻塞，线程安全）"""
        if not self._enabled:
            return
        try:
            now = time.time()
            date = time.strftime('%Y-%m-%d', time.localtime(now))
            # chat_id 脱敏：只保留前 8 位
            safe_chat_id = chat_id[:8] if chat_id else ''
            row = (now, date, category, event, session_name,
                   safe_chat_id, value, detail, self._machine_id)
            with self._lock:
                self._queue.append(row)
                should_flush = len(self._queue) >= _FLUSH_BATCH
            if should_flush:
                threading.Thread(target=self._flush, daemon=True).start()
        except Exception:
            pass

    def set_mixpanel_token(self, token: str) -> None:
        """配置 Mixpanel token（来自 .env）"""
        if not token:
            return
        self._mp_token = token
        try:
            import mixpanel
            self._mp = mixpanel.Mixpanel(token)
        except ImportError:
            pass  # mixpanel 未安装时静默跳过

    def check_and_report(self) -> None:
        """检查是否需要上报昨日数据（跨天检测，可在后台调用）"""
        if not self._enabled or not self._mp:
            return
        try:
            today = time.strftime('%Y-%m-%d')
            if self._last_report_date == today:
                return
            yesterday = time.strftime('%Y-%m-%d',
                                      time.localtime(time.time() - 86400))
            self.report_daily(yesterday)
            self._last_report_date = today
        except Exception:
            pass

    def report_daily(self, date: Optional[str] = None) -> None:
        """聚合指定日期数据并上报 Mixpanel（默认昨天）"""
        if not self._enabled or not self._mp:
            return
        try:
            if date is None:
                date = time.strftime('%Y-%m-%d',
                                     time.localtime(time.time() - 86400))
            self._flush()  # 先把队列里的数据落库

            conn = self._get_conn()
            rows = conn.execute(
                "SELECT category, event, COUNT(*), SUM(value) "
                "FROM events WHERE date=? GROUP BY category, event",
                (date,)
            ).fetchall()

            if not rows:
                return

            machine_info = get_machine_info()
            for category, event, count, total_value in rows:
                self._mp_track('daily_summary', {
                    'category': category,
                    'event': event,
                    'count': count,
                    'total_value': total_value,
                    'date': date,
                    **machine_info,
                })

            # 上报 heartbeat
            active_sessions = self._count_active_sessions(date, conn)
            self._mp_track('heartbeat', {
                'date': date,
                'active_sessions': active_sessions,
                **machine_info,
            })

            # 写入 daily_summary 表（本地留存）
            for category, event, count, total_value in rows:
                conn.execute(
                    "INSERT OR REPLACE INTO daily_summary "
                    "(date, category, event, count, total_value) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (date, category, event, count, total_value)
                )
            conn.commit()

        except Exception:
            pass

    def close(self) -> None:
        """关闭前刷新队列"""
        if self._enabled:
            try:
                self._flush()
            except Exception:
                pass

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """初始化 SQLite 数据库"""
        try:
            _DB_DIR.mkdir(parents=True, exist_ok=True)
            conn = self._get_conn()
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    event TEXT NOT NULL,
                    session_name TEXT DEFAULT '',
                    chat_id TEXT DEFAULT '',
                    value INTEGER DEFAULT 1,
                    detail TEXT DEFAULT '',
                    machine_id TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_summary (
                    date TEXT,
                    category TEXT,
                    event TEXT,
                    count INTEGER,
                    total_value INTEGER,
                    PRIMARY KEY (date, category, event)
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_events_date
                    ON events(date);
                CREATE INDEX IF NOT EXISTS idx_events_category
                    ON events(category, event);
            """)
            conn.commit()
            # 清理过期数据
            self._cleanup_old_data(conn)
        except Exception:
            pass

    def _check_first_run(self) -> None:
        """检查是否首次运行"""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT value FROM meta WHERE key='first_run'"
            ).fetchone()
            if row is None:
                self._is_first_run = True
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('first_run', ?)",
                    (time.strftime('%Y-%m-%d'),)
                )
                conn.commit()
        except Exception:
            pass

    def _get_conn(self) -> sqlite3.Connection:
        """获取 SQLite 连接（线程本地）"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        return self._conn

    def _flush(self) -> None:
        """批量写入 SQLite"""
        with self._lock:
            if not self._queue:
                return
            rows = list(self._queue)
            self._queue.clear()

        try:
            conn = self._get_conn()
            conn.executemany(
                "INSERT INTO events "
                "(timestamp, date, category, event, session_name, "
                "chat_id, value, detail, machine_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows
            )
            conn.commit()
            self._last_flush = time.time()
        except Exception:
            # 写失败，把数据放回队列头部（尽力保留）
            with self._lock:
                for row in reversed(rows):
                    self._queue.appendleft(row)

    def _flush_loop(self) -> None:
        """后台定时 flush 线程"""
        while True:
            try:
                time.sleep(10)
                elapsed = time.time() - self._last_flush
                with self._lock:
                    has_data = bool(self._queue)
                if has_data and elapsed >= _FLUSH_INTERVAL:
                    self._flush()
                self.check_and_report()
            except Exception:
                pass

    def _cleanup_old_data(self, conn: sqlite3.Connection) -> None:
        """清理过期数据"""
        try:
            conn.execute(
                "DELETE FROM events WHERE date < date('now', ?)",
                (f"-{_EVENTS_RETENTION} days",)
            )
            conn.execute(
                "DELETE FROM daily_summary WHERE date < date('now', ?)",
                (f"-{_SUMMARY_RETENTION} days",)
            )
            conn.commit()
        except Exception:
            pass

    def _mp_track(self, event_name: str, properties: dict) -> None:
        """上报单条 Mixpanel 事件"""
        if not self._mp:
            return
        try:
            self._mp.track(self._machine_id, event_name, properties)
        except Exception:
            pass

    def _count_active_sessions(self, date: str,
                               conn: sqlite3.Connection) -> int:
        """统计指定日期有 start 事件的会话数"""
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT session_name) FROM events "
                "WHERE date=? AND category='session' AND event='start'",
                (date,)
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def report_install(self) -> None:
        """首次运行时上报 install 事件和 user profile"""
        if not self._mp or not self._is_first_run:
            return
        try:
            machine_info = get_machine_info()
            import datetime
            self._mp.people_set(self._machine_id, {
                '$name': machine_info['hostname'],
                **machine_info,
                'first_seen': datetime.datetime.now().isoformat(),
            })
            self._mp_track('install', machine_info)
        except Exception:
            pass
