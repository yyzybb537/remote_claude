"""
Proxy Server

- 使用 PTY 启动 Claude CLI
- 通过 Unix Socket 接受多客户端连接
- 管理控制权状态
- 广播输出到所有连接的客户端
- 输出历史缓存
"""

import asyncio
import json
import logging
import os
import pty
import signal
import sys
import fcntl
import struct
import termios
import time

# 将项目根目录和当前目录加入 sys.path
# 根目录：protocol / utils / lark_client；当前目录：shared_state, component_parser, rich_text_renderer
_here = __import__('pathlib').Path(__file__).parent
sys.path.insert(0, str(_here))               # server/ → shared_state
sys.path.insert(0, str(_here.parent))        # 根目录 → protocol, utils, lark_client
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional

from utils.protocol import (
    Message, MessageType, InputMessage, OutputMessage,
    HistoryMessage, ResizeMessage,
    encode_message, decode_message
)
from utils.session import (
    get_socket_path, get_pid_file, ensure_socket_dir,
    generate_client_id, cleanup_session, get_env_file,
    SOCKET_DIR
)

from server.biz_enum import CliType


logger = logging.getLogger('Server')

# Server 日志级别配置
_SERVER_LOG_LEVEL = os.getenv("SERVER_LOG_LEVEL", "INFO").upper()
SERVER_LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}.get(_SERVER_LOG_LEVEL, logging.INFO)  # 默认 INFO

# 加载用户 .env 配置
try:
    from dotenv import load_dotenv
    load_dotenv(get_env_file())
except ImportError:
    logger.debug("dotenv 模块未安装，跳过 .env 加载")
except OSError as e:
    logger.warning(f"读取 .env 文件失败: {e}")

try:
    from stats import track as _track_stats
except ImportError:
    def _track_stats(*args, **kwargs): pass
except Exception as e:
    logger.warning(f"stats 模块加载异常: {e}")
    def _track_stats(*args, **kwargs): pass


# 历史缓存大小（字节）
HISTORY_BUFFER_SIZE = 100 * 1024  # 100KB


# ── VirtualScreen：将 HistoryScreen.history.top + buffer 合并为统一视图 ──────

class _VirtualBuffer:
    """统一访问接口：history rows [0..offset) + screen.buffer [offset..offset+lines)"""
    __slots__ = ('_history', '_buffer', '_offset')

    def __init__(self, history, buffer, offset):
        self._history = history   # list[dict]，来自 list(screen.history.top)
        self._buffer = buffer     # pyte screen.buffer
        self._offset = offset     # len(history)

    def __getitem__(self, row):
        if row < self._offset:
            return self._history[row]
        return self._buffer[row - self._offset]


class _VirtualCursor:
    """模拟 pyte cursor，y 偏移 history 行数"""
    __slots__ = ('y',)

    def __init__(self, y: int):
        self.y = y


class VirtualScreen:
    """HistoryScreen wrapper：将 history.top + buffer 合并为 parser 可直接读取的统一屏幕视图。

    parser 无需任何修改：
    - _split_regions 从 cursor.y+5 向上扫描找分割线，先找到当前屏幕中的分割线就停了
    - output_rows 自然包含 history 中的行号（0 到 offset-1）
    - _get_row_text/buffer[row] 通过 VirtualBuffer 透明返回对应行
    """
    __slots__ = ('_screen', '_history', '_offset')

    def __init__(self, screen):
        self._screen = screen
        self._history = list(screen.history.top) if hasattr(screen, 'history') else []
        self._offset = len(self._history)

    @property
    def columns(self):
        return self._screen.columns

    @property
    def lines(self):
        return self._offset + self._screen.lines

    @property
    def cursor(self):
        return _VirtualCursor(self._offset + self._screen.cursor.y)

    @property
    def buffer(self):
        return _VirtualBuffer(self._history, self._screen.buffer, self._offset)


# ── 全量快照架构 ─────────────────────────────────────────────────────────────

@dataclass
class _FrameObs:
    """单帧状态观测（用于时序窗口平滑）"""
    ts: float
    status_line: Optional[object]  # 本帧的 StatusLine（None=无）
    block_blink: bool = False      # 本帧最后一个 OutputBlock 是否 is_streaming=True
    has_background_agents: bool = False  # 底部栏是否有后台 agent 信息
    # 用于字符变化检测（增强闪烁判断）
    last_ob_start_row: int = -1          # 最后 OutputBlock 的起始行号（跨帧识别同一 block）
    last_ob_indicator_char: str = ''     # 指示符字符值（pyte char.data）
    last_ob_indicator_fg: str = ''       # 指示符前景色（pyte char.fg）
    last_ob_indicator_bold: bool = False # 指示符 bold 属性（影响显示亮度）


@dataclass
class ClaudeWindow:
    """全量快照：累积型 blocks + 状态型组件

    组件分两类：
    - 累积型 Block（blocks）：OutputBlock/UserInput，随对话增长
    - 状态型组件（status_line/bottom_bar/agent_panel/option_block）：全局唯一，每帧覆盖
    """
    blocks: list          # 累积型：全部历史 blocks
    status_line: object   # 状态型：StatusLine | None（窗口平滑后）
    bottom_bar: object    # 状态型：BottomBar | None
    agent_panel: object = None   # 状态型：AgentPanelBlock | None（agent 管理面板）
    option_block: object = None  # 状态型：OptionBlock | None（选项交互块）
    input_area_text: str = ''
    input_area_ansi_text: str = ''
    timestamp: float = 0.0
    layout_mode: str = "normal"  # "normal" | "option" | "detail" | "agent_list" | "agent_detail"
    cli_type: CliType = CliType.CLAUDE  # CLI 类型（决定 lark 侧的标题文案）



class OutputWatcher:
    """PTY 输出监视器：全量快照架构

    PTY 输出直接实时喂给持久化 pyte Screen；flush 时 screen 已是最新状态，
    直接 parse → 时序窗口平滑 → 累积列表合并 → 生成 ClaudeWindow 快照 → 写 debug + 共享内存。
    """

    WINDOW_SECONDS = 1.0

    def __init__(self, session_name: str, cols: int, rows: int,
                 parser=None,
                 cli_type: CliType = CliType.CLAUDE,
                 on_snapshot=None, debug_screen: bool = False,
                 debug_verbose: bool = False):
        self._session_name = session_name
        self._cols = cols
        self._rows = rows
        self._cli_type = cli_type
        self._pending = False
        self._on_snapshot = on_snapshot  # 回调：写共享内存
        self._debug_screen = debug_screen  # --debug-screen 开启后才写 _screen.log
        self._debug_verbose = debug_verbose  # --debug-verbose 开启后输出 indicator/repr 等诊断信息
        safe_name = _safe_filename(session_name)
        self._debug_file = f"/tmp/remote-claude/{safe_name}_messages.log"
        # PTY 原始字节流日志（仅 --debug-screen 开启时使用）
        self._raw_log_fd = None
        if debug_screen:
            raw_log_path = f"/tmp/remote-claude/{safe_name}_pty_raw.log"
            try:
                self._raw_log_fd = open(raw_log_path, "a", encoding="ascii", buffering=1)
            except OSError as e:
                logger.warning(f"无法创建 PTY 原始日志文件: {e}")
        # 持久化 pyte 渲染器：PTY 数据直接实时喂入，flush 时直接读 screen
        from rich_text_renderer import RichTextRenderer
        self._renderer = RichTextRenderer(columns=cols, lines=rows, debug_stream=debug_screen)
        # 持久化解析器（跨帧保留 dot_row_cache）；由调用方注入（可插拔架构）
        import logging as _logging
        _logging.getLogger('ComponentParser').setLevel(_logging.DEBUG)
        # 创建专用 logger 替换直接文件写入
        self._blink_logger = _logging.getLogger(f'OutputWatcher.{self._session_name}.blink')
        self._blink_logger.setLevel(_logging.DEBUG)
        self._flush_logger = _logging.getLogger(f'OutputWatcher.{self._session_name}.flush')
        self._flush_logger.setLevel(_logging.DEBUG)
        if parser is None:
            from parsers import ClaudeParser
            parser = ClaudeParser()
        self._parser = parser
        # 时序窗口（迁移自 MessageQueue）
        self._frame_window: deque = deque()
        # 最近快照（供外部读取）
        self.last_window: Optional[ClaudeWindow] = None
        # PTY 静止后延迟重刷：消除窗口平滑的延迟效应
        self._reflush_handle: Optional[asyncio.TimerHandle] = None
        # 调试日志截断长度（可通过 ~/.remote-claude/.debug_config 配置）
        self._debug_truncate_len = 80
        try:
            cfg_path = os.path.expanduser("~/.remote-claude/.debug_config")
            if os.path.exists(cfg_path):
                import json as _json
                with open(cfg_path) as _f:
                    _cfg = _json.load(_f)
                self._debug_truncate_len = int(_cfg.get("debug_truncate_len", 80))
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"读取调试配置失败，使用默认值: {e}")

    def resize(self, cols: int, rows: int):
        """重建 renderer 以适应新尺寸，历史随之丢失（可接受）。
        PTY resize 后 Claude 会全屏重绘，新 screen 自然会被填充。"""
        self._cols = cols
        self._rows = rows
        from rich_text_renderer import RichTextRenderer
        self._renderer = RichTextRenderer(columns=cols, lines=rows)

    def feed(self, data: bytes):
        self._renderer.feed(data)  # 直接喂持久化 screen，不再缓存原始字节
        # 诊断日志：记录 PTY 数据到达
        if data:
            logger.debug(f"[diag-feed] len={len(data)} data={data[:50]!r}")
        # 改动3：--debug-screen 开启时追加原始字节到 _pty_raw.log（base64 编码）
        if self._raw_log_fd is not None and data:
            try:
                import base64 as _b64
                ts = time.strftime('%H:%M:%S') + f'.{int(time.time() * 1000) % 1000:03d}'
                encoded = _b64.b64encode(data).decode('ascii')
                self._raw_log_fd.write(f"{ts} len={len(data)} {encoded}\n")
            except (OSError, ValueError) as e:
                logger.warning(f"写入 PTY 原始日志失败: {e}")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if not self._pending:
            self._pending = True
            loop.call_soon(lambda: asyncio.create_task(self._flush()))
        # PTY 静止后延迟重刷：每次 feed 重置计时器，
        # 静止 WINDOW_SECONDS 后再 flush 一次，消除窗口平滑的延迟效应
        # （窗口内残留的旧 blink=True 帧过期后，streaming 标记才能正确清除）
        if self._reflush_handle:
            self._reflush_handle.cancel()
        self._reflush_handle = loop.call_later(
            self.WINDOW_SECONDS,
            self._do_reflush
        )

    def _do_reflush(self):
        """PTY 静止 WINDOW_SECONDS 后重新 flush 一次。
        此时窗口内旧帧已过期，streaming/status_line 状态能正确归零。"""
        self._reflush_handle = None
        if not self._pending:
            self._pending = True
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon(lambda: asyncio.create_task(self._flush()))
            except RuntimeError:
                self._pending = False

    async def _flush(self):
        self._pending = False
        # 诊断日志：记录 flush 触发时间和帧窗口大小
        logger.debug(f"[diag-flush] ts={time.time():.6f} window_size={len(self._frame_window)}")
        try:
            from utils.components import StatusLine, BottomBar, Divider, OutputBlock, AgentPanelBlock, OptionBlock

            t0 = time.time()

            if self._debug_screen:
                self._write_screen_debug(self._renderer.screen)
            t1 = time.time()

            # 1. 构建 VirtualScreen（history.top + buffer）并解析
            # _write_screen_debug 仍用原始 screen（只写当前帧快照，不含 history）
            vscreen = VirtualScreen(self._renderer.screen)
            components = self._parser.parse(vscreen)
            input_text = self._parser.last_input_text
            input_ansi_text = self._parser.last_input_ansi_text

            # 3. 分拣：累积型 Block vs 状态型组件
            visible_blocks = []    # 累积型：OutputBlock/UserInput
            raw_status_line = None # 状态型
            raw_bottom_bar = None  # 状态型
            raw_agent_panel = None # 状态型
            raw_option_block = None  # 状态型
            for c in components:
                if isinstance(c, StatusLine):
                    raw_status_line = c
                elif isinstance(c, BottomBar):
                    raw_bottom_bar = c
                elif isinstance(c, AgentPanelBlock):
                    raw_agent_panel = c
                elif isinstance(c, OptionBlock):
                    raw_option_block = c
                elif isinstance(c, Divider):
                    pass
                else:
                    visible_blocks.append(c)

            # 4. 时序窗口平滑（先于合并，确保累积列表存储平滑后的值）
            now = time.time()
            # 4a. 记录原始帧观测（必须用未平滑的原始值）
            last_ob_blink = False
            last_ob_content = ''
            last_ob_start_row = -1
            last_ob_indicator_char = ''
            last_ob_indicator_fg = ''
            last_ob_indicator_bold = False
            for b in reversed(visible_blocks):
                if isinstance(b, OutputBlock):
                    last_ob_blink = b.is_streaming
                    last_ob_content = b.content[:40]
                    last_ob_start_row = b.start_row
                    # 读 vscreen.buffer 获取原始字符属性（支持 history 行）
                    if b.start_row >= 0:
                        try:
                            char = vscreen.buffer[b.start_row][0]
                            last_ob_indicator_char = str(getattr(char, 'data', ''))
                            last_ob_indicator_fg = str(getattr(char, 'fg', ''))
                            last_ob_indicator_bold = bool(getattr(char, 'bold', False))
                        except (KeyError, IndexError):
                            pass
                    break
            if last_ob_blink:
                self._blink_logger.debug(f"raw-blink  last_ob={last_ob_content!r}")

            self._frame_window.append(_FrameObs(
                ts=now,
                status_line=raw_status_line,
                block_blink=last_ob_blink,
                has_background_agents=getattr(raw_bottom_bar, 'has_background_agents', False) if raw_bottom_bar else False,
                last_ob_start_row=last_ob_start_row,
                last_ob_indicator_char=last_ob_indicator_char,
                last_ob_indicator_fg=last_ob_indicator_fg,
                last_ob_indicator_bold=last_ob_indicator_bold,
            ))
            cutoff = now - self.WINDOW_SECONDS
            while self._frame_window and self._frame_window[0].ts < cutoff:
                self._frame_window.popleft()

            window_list = list(self._frame_window)

            # 4b. status_line 平滑：
            # 优先选窗口内最新的"活跃状态"（有 elapsed），防止 spinner 重绘间隙
            # 屏幕遗留的已完成状态（无 elapsed）覆盖当前活跃值。
            # 若窗口内无活跃状态帧，回退到最新非 None 值（处理任务初始/刚完成场景）。
            _active_status = next(
                (o.status_line for o in reversed(window_list)
                 if o.status_line is not None and o.status_line.elapsed),
                None
            )
            display_status = _active_status or next(
                (o.status_line for o in reversed(window_list) if o.status_line is not None),
                None
            )

            # 4c. block blink 平滑：两种触发路径
            # 路径1：窗口内任意帧有 pyte blink 属性
            window_block_active = any(o.block_blink for o in window_list)

            # 路径2：窗口内同一 block 的指示符字符值/颜色/bold 有变化（增强闪烁判断）
            if not window_block_active and last_ob_start_row >= 0:
                same_block = [o for o in window_list if o.last_ob_start_row == last_ob_start_row]
                if len(same_block) >= 2:
                    chars = {o.last_ob_indicator_char for o in same_block if o.last_ob_indicator_char}
                    fgs   = {o.last_ob_indicator_fg   for o in same_block if o.last_ob_indicator_fg}
                    bolds = {o.last_ob_indicator_bold for o in same_block}
                    if len(chars) > 1 or len(fgs) > 1 or len(bolds) > 1:
                        window_block_active = True
                        # 记录字符变化触发原因
                        self._blink_logger.debug(
                            f"char-change row={last_ob_start_row}"
                            f"  chars={chars}  fgs={fgs}  bolds={bolds}"
                        )

            if window_block_active:
                for b in reversed(visible_blocks):
                    if isinstance(b, OutputBlock):
                        self._blink_logger.debug(
                            f"win-smooth last_ob={b.content[:40]!r}"
                            f"  window_frames={len(window_list)}"
                            f"  blink_frames={sum(1 for o in window_list if o.block_blink)}"
                        )
                        b.is_streaming = True
                        break

            # 5. 直接使用 visible_blocks（VirtualScreen 已包含 history.top + 当前屏幕）
            all_blocks = visible_blocks

            # 5b. 后台 agent 摘要：BottomBar 有 agent 信息但面板未展开时，
            #     生成 summary 类型的 AgentPanelBlock（确保下游始终能感知后台 agent）
            if raw_agent_panel is None and raw_bottom_bar and getattr(raw_bottom_bar, 'has_background_agents', False):
                raw_agent_panel = AgentPanelBlock(
                    panel_type="summary",
                    agent_count=raw_bottom_bar.agent_count,
                    raw_text=raw_bottom_bar.agent_summary,
                )

            # 6. 构建快照
            window = ClaudeWindow(
                blocks=all_blocks,
                status_line=display_status,
                bottom_bar=raw_bottom_bar,
                agent_panel=raw_agent_panel,
                option_block=raw_option_block,
                input_area_text=input_text,
                input_area_ansi_text=input_ansi_text,
                timestamp=now,
                layout_mode=self._parser.last_layout_mode,
                cli_type=self._cli_type,
            )
            # 诊断日志：检测最终输出中是否有同时存在 status_line 和 SystemBlock 的情况
            if display_status:
                status_prefix = display_status.raw[:30] if hasattr(display_status, 'raw') else str(display_status)[:30]
                has_systemblock_with_status = any(
                    b.__class__.__name__ == 'SystemBlock' and
                    hasattr(b, 'content') and status_prefix in b.content
                    for b in all_blocks
                )
                if has_systemblock_with_status:
                    logger.debug(f"[diag-output] BOTH status_line and SystemBlock present! status_line={status_prefix!r}")
            self.last_window = window

            # 7. 输出
            t2 = time.time()
            self._write_window_debug(window)
            t3 = time.time()
            if self._on_snapshot:
                self._on_snapshot(window)
            t4 = time.time()

            self._flush_logger.debug(
                f"[flush] screen_log={1000*(t1-t0):.1f}ms  parse={1000*(t2-t1):.1f}ms  "
                f"msg_log={1000*(t3-t2):.1f}ms  snapshot={1000*(t4-t3):.1f}ms  "
                f"total={1000*(t4-t0):.1f}ms  rows={self._rows}\n"
                f"  └─ {self._parser.last_parse_timing}"
            )

        except Exception as e:
            logger.error(f"[OutputWatcher] flush 失败: {e}", exc_info=True)

    def _write_window_debug(self, window: ClaudeWindow):
        """将 ClaudeWindow 快照写入调试文件"""
        try:
            from utils.components import OutputBlock, UserInput, OptionBlock, AgentPanelBlock, SystemBlock
            lines = [
                f"=== ClaudeWindow snapshot  {time.strftime('%H:%M:%S')} ===",
                f"session={self._session_name}",
                f"blocks={len(window.blocks)}",
            ]
            # StatusLine
            if window.status_line:
                sl = window.status_line
                if self._debug_verbose:
                    lines.append(f"status_line: {sl.raw[:120]}")
                    lines.append(f"      indicator={sl.indicator!r}  ansi_indicator={sl.ansi_indicator!r}")
                    lines.append(f"      ansi_raw={sl.ansi_raw[:120]!r}")
                    lines.append(f"      ansi_render: {sl.ansi_indicator} {sl.ansi_raw[:120]}\x1b[0m")
                else:
                    lines.append(f"status_line: {sl.ansi_raw[:120]}\x1b[0m")
            else:
                lines.append("status_line: None")
            # BottomBar
            if window.bottom_bar:
                bb = window.bottom_bar
                if self._debug_verbose:
                    lines.append(f"bottom_bar: {bb.text[:120]}")
                    lines.append(f"      ansi_text={bb.ansi_text[:120]!r}")
                    lines.append(f"      ansi_render: {bb.ansi_text[:120]}\x1b[0m")
                else:
                    lines.append(f"bottom_bar: {bb.ansi_text[:120]}\x1b[0m")
            else:
                lines.append("bottom_bar: None")
            # AgentPanelBlock（状态型，独立于 blocks）
            if window.agent_panel:
                ap = window.agent_panel
                if ap.panel_type == 'detail':
                    lines.append(f"agent_panel: detail · {ap.agent_type} › {ap.agent_name[:40]}")
                elif ap.panel_type == 'summary':
                    lines.append(f"agent_panel: summary · {ap.agent_count} agents · {ap.raw_text[:60]}")
                else:
                    lines.append(f"agent_panel: list · {ap.agent_count} agents")
                if self._debug_verbose and ap.raw_text:
                    raw_preview = ap.raw_text[:120].replace('\n', '\\n')
                    lines.append(f"      raw_text={raw_preview!r}")
            else:
                lines.append("agent_panel: None")
            # OptionBlock（状态型，独立于 blocks）
            if window.option_block:
                ob = window.option_block
                lines.append(f"option_block: sub_type={ob.sub_type} question={ob.question[:60]!r} options={len(ob.options)}")
            else:
                lines.append("option_block: None")
            if self._debug_verbose:
                lines.append(f"input_area={window.input_area_text!r}")
                if window.input_area_ansi_text:
                    lines.append(f"      ansi={window.input_area_ansi_text!r}")
                    lines.append(f"      ansi_render: {window.input_area_ansi_text}\x1b[0m")
            else:
                if window.input_area_ansi_text:
                    lines.append(f"input_area: {window.input_area_ansi_text}\x1b[0m")
                else:
                    lines.append(f"input_area: {window.input_area_text!r}")
            lines.append(f"layout_mode={window.layout_mode}")
            lines.append("")
            for i, block in enumerate(window.blocks):
                if isinstance(block, OutputBlock):
                    streaming = " [STREAMING]" if block.is_streaming else ""
                    if self._debug_verbose:
                        content_preview = block.content[:120].replace('\n', '\\n')
                        lines.append(f"[{i}] OutputBlock{streaming}: {content_preview}")
                        if block.indicator:
                            lines.append(f"      indicator={block.indicator!r}  ansi_indicator={block.ansi_indicator!r}")
                        if block.ansi_content:
                            ansi_preview = block.ansi_content[:120].replace('\n', '\\n')
                            lines.append(f"      ansi_content={ansi_preview!r}")
                            ansi_render = block.ansi_content.replace('\n', '\\n')
                            indicator_prefix = (block.ansi_indicator + ' ') if block.ansi_indicator else ''
                            lines.append(f"      ansi_render: {indicator_prefix}{ansi_render}\x1b[0m")
                    else:
                        if block.ansi_content:
                            ansi_render = block.ansi_content.replace('\n', '\\n')
                            indicator_prefix = (block.ansi_indicator + ' ') if block.ansi_indicator else ''
                            lines.append(f"[{i}] OutputBlock{streaming}: {indicator_prefix}{ansi_render}\x1b[0m")
                        else:
                            content_preview = block.content[:120].replace('\n', '\\n')
                            lines.append(f"[{i}] OutputBlock{streaming}: {content_preview}")
                elif isinstance(block, UserInput):
                    if self._debug_verbose:
                        lines.append(f"[{i}] UserInput: {block.text[:80]}")
                        if block.indicator:
                            lines.append(f"      indicator={block.indicator!r}  ansi_indicator={block.ansi_indicator!r}")
                        if block.ansi_text:
                            lines.append(f"      ansi_text={block.ansi_text[:80]!r}")
                            ansi_render = block.ansi_text.replace('\n', '\\n')
                            indicator_prefix = (block.ansi_indicator + ' ') if block.ansi_indicator else ''
                            lines.append(f"      ansi_render: {indicator_prefix}{ansi_render}\x1b[0m")
                    else:
                        if block.ansi_text:
                            ansi_render = block.ansi_text.replace('\n', '\\n')
                            indicator_prefix = (block.ansi_indicator + ' ') if block.ansi_indicator else ''
                            lines.append(f"[{i}] UserInput: {indicator_prefix}{ansi_render}\x1b[0m")
                        else:
                            lines.append(f"[{i}] UserInput: {block.text[:80]}")
                elif isinstance(block, SystemBlock):
                    if self._debug_verbose:
                        content_preview = block.content[:120].replace('\n', '\\n')
                        lines.append(f"[{i}] SystemBlock: {content_preview}")
                        if block.indicator:
                            lines.append(f"      indicator={block.indicator!r}  ansi_indicator={block.ansi_indicator!r}")
                        if block.ansi_content:
                            ansi_render = block.ansi_content.replace('\n', '\\n')
                            indicator_prefix = (block.ansi_indicator + ' ') if block.ansi_indicator else ''
                            lines.append(f"      ansi_render: {indicator_prefix}{ansi_render}\x1b[0m")
                    else:
                        if block.ansi_content:
                            ansi_render = block.ansi_content.replace('\n', '\\n')
                            indicator_prefix = (block.ansi_indicator + ' ') if block.ansi_indicator else ''
                            lines.append(f"[{i}] SystemBlock: {indicator_prefix}{ansi_render}\x1b[0m")
                        else:
                            lines.append(f"[{i}] SystemBlock: {block.content[:120].replace(chr(10), chr(92)+'n')}")
                else:
                    lines.append(f"[{i}] {type(block).__name__}: {str(block)[:self._debug_truncate_len]}")
            lines.append("")
            lines.append("-----")
            with open(self._debug_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            logger.warning(f"写入调试文件失败: {e}")
        except Exception as e:
            logger.error(f"写入调试文件发生意外错误: {e}", exc_info=True)

    @staticmethod
    def _char_to_ansi(char) -> str:
        """将 pyte Char 的颜色/样式属性转为 ANSI SGR 前缀序列。

        返回带 ANSI 转义的字符字符串，调用方需在行尾追加 \\033[0m 重置。
        仅在属性非默认时才输出对应 SGR，降低输出体积。
        """
        # 标准颜色名到 ANSI 码
        _FG_NAMES = {
            'black': 30, 'red': 31, 'green': 32, 'yellow': 33,
            'blue': 34, 'magenta': 35, 'cyan': 36, 'white': 37,
            'brown': 33,  # pyte 把 ANSI 33 解析为 brown
        }
        _BG_NAMES = {
            'black': 40, 'red': 41, 'green': 42, 'yellow': 43,
            'blue': 44, 'magenta': 45, 'cyan': 46, 'white': 47,
            'brown': 43,
        }
        _BRIGHT_FG = {
            'brightblack': 90, 'brightred': 91, 'brightgreen': 92, 'brightyellow': 93,
            'brightblue': 94, 'brightmagenta': 95, 'brightcyan': 96, 'brightwhite': 97,
        }
        _BRIGHT_BG = {
            'brightblack': 100, 'brightred': 101, 'brightgreen': 102, 'brightyellow': 103,
            'brightblue': 104, 'brightmagenta': 105, 'brightcyan': 106, 'brightwhite': 107,
        }

        sgr = []

        # bold / blink
        if getattr(char, 'bold', False):
            sgr.append('1')
        if getattr(char, 'blink', False):
            sgr.append('5')

        # 前景色
        fg = getattr(char, 'fg', 'default')
        if fg and fg != 'default':
            fg_low = str(fg).lower()
            if fg_low in _FG_NAMES:
                sgr.append(str(_FG_NAMES[fg_low]))
            elif fg_low in _BRIGHT_FG:
                sgr.append(str(_BRIGHT_FG[fg_low]))
            elif len(fg_low) == 6 and all(c in '0123456789abcdef' for c in fg_low):
                # 24-bit true color
                r = int(fg_low[0:2], 16)
                g = int(fg_low[2:4], 16)
                b = int(fg_low[4:6], 16)
                sgr.append(f'38;2;{r};{g};{b}')

        # 背景色
        bg = getattr(char, 'bg', 'default')
        if bg and bg != 'default':
            bg_low = str(bg).lower()
            if bg_low in _BG_NAMES:
                sgr.append(str(_BG_NAMES[bg_low]))
            elif bg_low in _BRIGHT_BG:
                sgr.append(str(_BRIGHT_BG[bg_low]))
            elif len(bg_low) == 6 and all(c in '0123456789abcdef' for c in bg_low):
                r = int(bg_low[0:2], 16)
                g = int(bg_low[2:4], 16)
                b = int(bg_low[4:6], 16)
                sgr.append(f'48;2;{r};{g};{b}')

        if sgr:
            return f'\033[{";".join(sgr)}m{char.data}\033[0m'
        return char.data

    def _write_screen_debug(self, screen):
        """将 pyte 屏幕内容写入调试文件（_screen.log）

        每个字符的 fg/bg 颜色通过 ANSI SGR 序列直接嵌入，
        cat _screen.log 即可在终端看到与 pyte 渲染一致的着色效果。
        """
        base = f"/tmp/remote-claude/{_safe_filename(self._session_name)}"
        try:
            # pyte 屏幕快照（覆盖写，只保留最新一帧）
            screen_path = base + "_screen.log"
            scan_limit = min(screen.cursor.y + 5, screen.lines - 1)
            lines = [
                f"=== screen snapshot  {time.strftime('%H:%M:%S')} ===",
                f"size={screen.columns}×{screen.lines}  cursor_y={screen.cursor.y}  scan_limit={scan_limit}",
                "",
            ]
            for row in range(scan_limit + 1):
                # 构建带颜色的行内容（用于终端直接 cat 显示）
                colored_buf = []
                plain_buf = [' '] * screen.columns
                for col in range(screen.columns):
                    char = screen.buffer[row].get(col)
                    if char is None:
                        colored_buf.append(' ')
                        continue
                    plain_buf[col] = char.data
                    colored_buf.append(self._char_to_ansi(char))

                rstripped_plain = ''.join(plain_buf).rstrip()
                if not rstripped_plain:
                    # 检查是否有背景色（对 Codex 背景色分割线很重要）
                    row_bgs = set()
                    for col in range(screen.columns):
                        char = screen.buffer[row].get(col)
                        if char is not None:
                            bg = getattr(char, 'bg', 'default')
                            if bg and bg != 'default':
                                row_bgs.add(str(bg))
                    if row_bgs:
                        bg_str = ','.join(sorted(row_bgs))
                        lines.append(f"{row:3d} |[bg:{bg_str} ···]")
                    else:
                        lines.append(f"{row:3d} |")
                    continue

                try:
                    c0 = screen.buffer[row][0]
                    col0_blink = getattr(c0, "blink", False)
                except (KeyError, IndexError):
                    col0_blink = False

                blink_mark = "B" if col0_blink else " "
                # rstrip 着色内容：找最后一个有内容的列号（正确处理 CJK 占 2 列的情况）
                # plain_buf 按列号索引，len(rstripped_plain) 会因 CJK 字符导致列数偏小
                last_col = 0
                for col in range(screen.columns - 1, -1, -1):
                    if plain_buf[col] != ' ':
                        last_col = col + 1
                        break
                colored_line = ''.join(colored_buf[:last_col])
                lines.append(f"{row:3d}{blink_mark}|{colored_line}")

            with open(screen_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as e:
            logger.warning(f"写入屏幕调试文件失败: {e}")
        except Exception as e:
            logger.error(f"写入屏幕调试文件发生意外错误: {e}", exc_info=True)


# ── 全量快照架构 end ─────────────────────────────────────────────────────────


class HistoryBuffer:
    """环形历史缓冲区"""

    def __init__(self, max_size: int = HISTORY_BUFFER_SIZE):
        self.max_size = max_size
        self.buffer = bytearray()

    def append(self, data: bytes):
        """追加数据"""
        self.buffer.extend(data)
        # 超出大小时截断前面的数据
        if len(self.buffer) > self.max_size:
            self.buffer = self.buffer[-self.max_size:]

    def get_all(self) -> bytes:
        """获取所有历史数据"""
        return bytes(self.buffer)

    def clear(self):
        """清空缓冲区"""
        self.buffer.clear()


class ClientConnection:
    """客户端连接"""

    def __init__(self, client_id: str, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter):
        self.client_id = client_id
        self.reader = reader
        self.writer = writer
        self.buffer = b""

    async def send(self, msg: Message):
        """发送消息"""
        try:
            data = encode_message(msg)
            self.writer.write(data)
            await self.writer.drain()
        except (ConnectionError, BrokenPipeError, OSError) as e:
            logger.warning(f"发送消息失败 ({self.client_id}): 连接错误: {e}")
        except Exception as e:
            logger.error(f"发送消息失败 ({self.client_id}): 未知错误: {e}")

    async def read_message(self) -> Optional[Message]:
        """读取一条消息"""
        while True:
            # 检查缓冲区中是否有完整消息
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    return decode_message(line)
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"解析消息失败: {e}, 数据: {line[:100]!r}")
                    continue
                except Exception as e:
                    logger.error(f"解析消息发生意外错误: {e}", exc_info=True)
                    continue

            # 读取更多数据
            try:
                data = await self.reader.read(4096)
                if not data:
                    return None
                self.buffer += data
            except (ConnectionError, BrokenPipeError, OSError):
                return None
            except Exception as e:
                logger.error(f"读取消息发生意外错误: {e}", exc_info=True)
                return None

    def close(self):
        """关闭连接"""
        try:
            self.writer.close()
        except (ConnectionError, OSError) as e:
            logger.debug(f"关闭连接时发生错误: {e}")
        except Exception as e:
            logger.warning(f"关闭连接发生意外错误: {e}")


class ProxyServer:
    """Proxy Server"""

    def __init__(self, session_name: str, cli_args: list = None,
                 cli_type: str = "claude",
                 cli_command: Optional[str] = None,
                 debug_screen: bool = False, debug_verbose: bool = False):
        self.session_name = session_name
        self.cli_args = cli_args or []
        self.cli_type = cli_type
        self.cli_command = cli_command  # 直接指定的 CLI 命令（优先级最高）
        self.debug_screen = debug_screen
        self.debug_verbose = debug_verbose
        self.socket_path = get_socket_path(session_name)
        self.pid_file = get_pid_file(session_name)

        # PTY 相关
        self.master_fd: Optional[int] = None
        self.child_pid: Optional[int] = None

        # 客户端管理
        self.clients: Dict[str, ClientConnection] = {}

        # 历史缓存
        self.history = HistoryBuffer()

        # 共享状态 mmap（向其他进程暴露快照）
        from shared_state import SharedStateWriter
        self.shared_state = SharedStateWriter(session_name)

        # 输出监视器（全量快照架构：PTY → pyte → 解析 → 平滑 → 合并 → 快照 → 共享内存）
        self.output_watcher = OutputWatcher(
            session_name=session_name,
            cols=self.PTY_COLS, rows=self.PTY_ROWS,
            parser=self._get_parser(),
            cli_type=self.cli_type,
            on_snapshot=lambda w: self.shared_state.write_snapshot(w),
            debug_screen=self.debug_screen,
            debug_verbose=self.debug_verbose,
        )

        # 运行状态
        self.running = False
        self.server: Optional[asyncio.AbstractServer] = None
        self._start_time = time.time()

    async def start(self):
        """启动服务器"""
        t0 = time.time()
        logger.info(f"正在启动 (session={self.session_name})")
        ensure_socket_dir()

        # 清理旧的 socket 文件
        if self.socket_path.exists():
            self.socket_path.unlink()

        # 启动 PTY
        t1 = time.time()
        self._start_pty()
        logger.info(f"PTY 已启动 ({(time.time()-t1)*1000:.0f}ms)")

        # 写入 PID 文件
        self.pid_file.write_text(str(os.getpid()))

        # 启动 Unix Socket 服务器
        t2 = time.time()
        self.server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path)
        )

        self.running = True
        _track_stats('session', 'start', session_name=self.session_name)
        logger.info(f"已启动: {self.socket_path} (Socket {(time.time()-t2)*1000:.0f}ms, 总计 {(time.time()-t0)*1000:.0f}ms)")

        # 启动 PTY 读取任务
        asyncio.create_task(self._read_pty())

        # 切换到运行阶段日志
        self._switch_to_runtime_logging()

        # 等待服务器关闭
        async with self.server:
            await self.server.serve_forever()

    # PTY 终端尺寸：与 lark_client 的 pyte 渲染器保持一致
    PTY_COLS = 220
    PTY_ROWS = 100  # 行数缩减至 100，历史内容通过 HistoryScreen.history.top 保存（5000 行容量）

    def _get_parser(self):
        """根据 cli_type 返回对应的解析器实例"""
        from parsers import ClaudeParser, CodexParser
        if self.cli_type == CliType.CODEX:
            return CodexParser()
        return ClaudeParser()

    def _switch_to_runtime_logging(self):
        """从启动日志切换到运行阶段日志"""
        root_logger = logging.getLogger()

        # 移除启动日志 handler（保留 stdout handler）
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.FileHandler) and \
               not hasattr(handler, '_runtime_handler') and \
               not hasattr(handler, '_debug_handler'):
                root_logger.removeHandler(handler)

        # 重定向 sys.stderr 到 ~/.remote-claude/server.error.log
        # 注意：这不会影响外层的 2>> startup.log，但 Python 的 stderr 输出会走这里
        # 适用于：print(..., file=sys.stderr)、logging 的 StreamHandler 等
        # 不适用于：C 扩展模块直接写文件描述符 2、解释器崩溃等底层错误
        error_log_path = os.path.expanduser('~/.remote-claude/server.error.log')
        sys.stderr = open(error_log_path, 'w', encoding='utf-8')
        logger.info(f"已重定向 stderr 到 {error_log_path}")

        # 添加运行阶段日志文件
        safe_name = _safe_filename(self.session_name)
        runtime_handler = logging.FileHandler(
            f"{SOCKET_DIR}/{safe_name}_server.log",
            encoding="utf-8"
        )
        runtime_handler.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        runtime_handler._runtime_handler = True  # 标记，方便后续清理
        root_logger.addHandler(runtime_handler)

        # DEBUG 级别时额外记录调试日志到独立文件
        if SERVER_LOG_LEVEL_MAP == logging.DEBUG:
            debug_handler = logging.FileHandler(
                f"{SOCKET_DIR}/{safe_name}_debug.log",
                encoding="utf-8"
            )
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.setFormatter(logging.Formatter(
                "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            debug_handler._debug_handler = True  # 标记，方便后续清理
            root_logger.addHandler(debug_handler)
            logger.info(f"已启用 DEBUG 日志: {safe_name}_debug.log")

        logger.info(f"日志已切换到运行阶段: {safe_name}_server.log")

    def _get_effective_cmd(self) -> str:
        """根据 cli_command / cli_type 返回实际执行的命令

        优先级：
        1. 直接指定的 cli_command（--cli-command 参数）
        2. 自定义命令配置（config.json）
        3. 默认值（claude 或 codex）
        """
        # 最高优先级：直接指定的 cli_command
        if self.cli_command:
            return self.cli_command

        # 次优先级：从自定义命令配置获取
        try:
            from utils.runtime_config import get_cli_command
            custom_cmd = get_cli_command(self.cli_type)
            if custom_cmd:
                return custom_cmd
        except Exception as e:
            logger.debug(f"读取自定义命令配置失败: {e}")

        # 回退到默认值
        return str(self.cli_type)

    def _start_pty(self):
        """启动 PTY 并运行 Claude"""
        # 加载环境变量快照（从 cmd_start 保存的快照文件恢复调用方 shell 的完整环境）
        from utils.session import get_env_snapshot_path
        import json as _json
        env_snapshot_path = get_env_snapshot_path(self.session_name)
        _extra_env = {}
        try:
            with open(env_snapshot_path) as _f:
                _extra_env = _json.load(_f)
            logger.info(f"环境快照已加载 ({len(_extra_env)} 个变量)")
        except FileNotFoundError:
            logger.warning("环境快照文件不存在，使用当前进程环境")
        except json.JSONDecodeError as e:
            logger.warning(f"环境快照文件格式错误: {e}，使用当前进程环境")
        except OSError as e:
            logger.warning(f"读取环境快照失败: {e}，使用当前进程环境")

        # 提前计算命令（fork 后父子进程共享，方便父进程打印和子进程执行）
        import shlex as _shlex
        _cmd_parts = _shlex.split(self._get_effective_cmd())
        _full_cmd = ' '.join(_cmd_parts + self.cli_args)

        try:
            pid, fd = pty.fork()
        except OSError:
            env_snapshot_path.unlink(missing_ok=True)
            raise

        if pid == 0:
            # 环境已加载到内存，立即删除快照文件（exec 前销毁）
            try:
                env_snapshot_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                # fork 后无法使用 logger，直接输出
                print(f"[Server] 警告: 删除环境快照失败: {e}", file=sys.stderr)
            # 以快照为权威来源完整替换子进程环境，确保 unset 的变量也消失
            # 若 snapshot 加载失败（_extra_env 为空），降级使用当前进程环境
            child_env = dict(_extra_env) if _extra_env else dict(os.environ)
            # 恢复 TERM 以支持 kitty keyboard protocol（Shift+Enter 等扩展键）
            # tmux 会将 TERM 改为 tmux-256color，导致 Claude CLI 不启用 kitty protocol
            child_env['TERM'] = 'xterm-256color'
            # 清除 tmux 标识变量（PTY 数据不经过 tmux，不应让 Claude CLI 误判终端环境）
            child_env.pop('TMUX', None)
            child_env.pop('TMUX_PANE', None)
            try:
                os.execvpe(_cmd_parts[0], _cmd_parts + self.cli_args, child_env)
            except (FileNotFoundError, PermissionError) as _e:
                msg = f"启动失败: 命令 '{_cmd_parts[0]}' 无法执行: {_e}"
                os.write(1, (msg + "\n").encode())  # 写到 PTY
                # fork 后不能安全使用 logging，直接追加写日志文件
                try:
                    import time as _t
                    _ts = _t.strftime("%Y-%m-%d %H:%M:%S")
                    _ms = int((_t.time() % 1) * 1000)
                    _log_line = f"{_ts}.{_ms:03d} [Server] ERROR {msg}\n"
                    _home = os.path.expanduser("~")
                    _log_file = os.path.join(_home, ".remote-claude", "startup.log")
                    with open(_log_file, "a", encoding="utf-8") as _f:
                        _f.write(_log_line)
                except OSError:
                    pass
                os._exit(127)  # 127 = command not found (shell convention)
            except OSError as _e:
                msg = f"启动失败: 命令 '{_cmd_parts[0]}' 执行错误: {_e}"
                os.write(1, (msg + "\n").encode())
                os._exit(126)  # 126 = command not executable
            os._exit(1)  # 理论上不可达
        else:
            # 父进程
            self.master_fd = fd
            self.child_pid = pid

            # 设置 PTY 终端大小（与 pyte 渲染器尺寸一致，避免 ANSI 光标错位）
            winsize = struct.pack('HHHH', self.PTY_ROWS, self.PTY_COLS, 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

            # 设置非阻塞
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            cli_label = self.cli_type.capitalize()
            logger.info(f"启动命令: {_full_cmd}")
            logger.info(f"{cli_label} 已启动 (PID: {pid}, PTY: {self.PTY_COLS}×{self.PTY_ROWS})")

    _COALESCE_MAX = 64 * 1024  # 64KB，防止单次广播过大

    async def _read_pty(self):
        """读取 PTY 输出并广播"""
        loop = asyncio.get_event_loop()

        while self.running and self.master_fd is not None:
            try:
                # 第一次 read（在线程池中，可能阻塞等待数据）
                data = await loop.run_in_executor(
                    None, self._read_pty_sync
                )
                if data:
                    # 贪婪合并：非阻塞读取紧接数据，合并为一次广播
                    buf = bytearray(data)
                    while len(buf) < self._COALESCE_MAX:
                        try:
                            more = os.read(self.master_fd, 4096)
                            if not more:
                                break
                            buf.extend(more)
                        except (BlockingIOError, OSError):
                            break
                    coalesced = bytes(buf)
                    # 保存到历史
                    self.history.append(coalesced)
                    # 广播给所有客户端
                    await self._broadcast_output(coalesced)
                elif data is None:
                    # 暂时无数据（BlockingIOError），稍等继续
                    await asyncio.sleep(0.01)
                else:
                    # os.read 返回 b""：PTY 已关闭（子进程退出）
                    break
            except Exception as e:
                if self.running:
                    logger.error(f"读取 PTY 错误: {e}")
                break

        # Claude 退出，获取 exit code 以便诊断
        try:
            _, status = os.waitpid(self.child_pid, os.WNOHANG)
            if status != 0:
                exit_code = os.waitstatus_to_exitcode(status)
                logger.error(f"CLI 进程异常退出 (exit_code={exit_code})")
            else:
                logger.info("Claude 已退出")
        except ChildProcessError:
            logger.info("Claude 已退出（子进程已回收）")
        except ProcessLookupError:
            logger.info("Claude 已退出（进程未找到）")
        except Exception as e:
            logger.warning(f"获取 Claude 退出状态失败: {e}")
        await self._shutdown()

    def _read_pty_sync(self) -> Optional[bytes]:
        """同步读取 PTY（在线程池中运行）"""
        try:
            return os.read(self.master_fd, 4096)
        except BlockingIOError:
            return None
        # OSError（EIO）说明子进程已退出，PTY 已关闭，向上抛出让 _read_pty 检测并退出循环

    async def _handle_client(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter):
        """处理客户端连接"""
        client_id = generate_client_id()
        client = ClientConnection(client_id, reader, writer)
        self.clients[client_id] = client

        logger.info(f"客户端连接: {client_id}")
        _track_stats('session', 'attach', session_name=self.session_name)

        # 发送历史输出
        history_data = self.history.get_all()
        if history_data:
            await client.send(HistoryMessage(history_data))

        # 处理客户端消息
        try:
            while self.running:
                msg = await client.read_message()
                if msg is None:
                    break
                await self._handle_message(client_id, msg)
        except (ConnectionError, BrokenPipeError, OSError) as e:
            logger.info(f"客户端连接断开 ({client_id}): {e}")
        except asyncio.CancelledError:
            logger.info(f"客户端任务被取消 ({client_id})")
        except Exception as e:
            logger.error(f"客户端处理错误 ({client_id}): {e}", exc_info=True)
        finally:
            # 清理
            del self.clients[client_id]
            client.close()
            logger.info(f"客户端断开: {client_id}")

    async def _handle_message(self, client_id: str, msg: Message):
        """处理客户端消息"""
        if msg.type == MessageType.INPUT:
            await self._handle_input(client_id, msg)
        elif msg.type == MessageType.RESIZE:
            await self._handle_resize(client_id, msg)

    async def _handle_input(self, client_id: str, msg: InputMessage):
        """处理输入消息"""
        try:
            data = msg.get_data()
            os.write(self.master_fd, data)
            _track_stats('terminal', 'input', session_name=self.session_name,
                         value=len(data))
        except (BrokenPipeError, OSError) as e:
            logger.error(f"写入 PTY 失败（连接错误）: {e}")
        except Exception as e:
            logger.error(f"写入 PTY 发生意外错误: {e}", exc_info=True)

        # 广播输入给其他客户端（飞书侧可以感知终端用户的输入内容）
        for cid, client in list(self.clients.items()):
            if cid != client_id:
                try:
                    await client.send(msg)
                except (ConnectionError, BrokenPipeError, OSError):
                    pass  # 广播失败可忽略
                except Exception as e:
                    logger.debug(f"广播输入失败: {e}")

    async def _handle_resize(self, client_id: str, msg: ResizeMessage):
        """处理终端大小变化：同步更新 PTY 和 pyte 渲染尺寸，清空 raw buffer。
        Claude 收到 SIGWINCH 后会全屏重绘，buffer 清空后自然恢复为新尺寸的完整屏幕数据。"""
        try:
            # output_watcher 的 rows 固定为 PTY_ROWS（100），不跟随客户端终端尺寸变化
            # terminal client 直接渲染 PTY 原始输出，不依赖 output_watcher，无需同步 rows
            self.output_watcher.resize(msg.cols, self.PTY_ROWS)
            winsize = struct.pack('HHHH', msg.rows, msg.cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError as e:
            logger.error(f"调整终端大小失败（系统错误）: {e}")
        except Exception as e:
            logger.error(f"调整终端大小失败: {e}", exc_info=True)

    async def _broadcast_output(self, data: bytes):
        """广播输出给所有客户端，同时喂给 OutputWatcher 生成快照"""
        self.output_watcher.feed(data)
        msg = OutputMessage(data)
        tasks = [client.send(msg) for client in self.clients.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _shutdown(self):
        """关闭服务器"""
        self.running = False

        # 关闭所有客户端
        for client in list(self.clients.values()):
            client.close()
        self.clients.clear()

        # 关闭服务器
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # 关闭 PTY
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass  # PTY 已关闭，可忽略
            except Exception as e:
                logger.warning(f"关闭 PTY 发生意外错误: {e}")

        # 关闭共享状态（会删除 .mq 文件）
        elapsed = int(time.time() - self._start_time)
        _track_stats('session', 'end', session_name=self.session_name, value=elapsed)
        self.shared_state.close()

        # 清理文件
        cleanup_session(self.session_name)

        logger.info("已关闭")


def run_server(session_name: str, cli_args: list = None,
               cli_type: str = "claude",
               cli_command: Optional[str] = None,
               debug_screen: bool = False, debug_verbose: bool = False):
    """运行服务器"""
    server = ProxyServer(session_name, cli_args,
                         cli_type=cli_type,
                         cli_command=cli_command,
                         debug_screen=debug_screen, debug_verbose=debug_verbose)

    # 信号处理
    def signal_handler(signum, frame):
        print("\n[Server] 收到退出信号")
        asyncio.create_task(server._shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 运行
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Remote Claude/Codex Server")
    parser.add_argument("session_name", help="会话名称")
    parser.add_argument("cli_args", nargs="*", help="传递给 CLI 的参数")
    parser.add_argument("--cli-type", default="claude", choices=["claude", "codex"],
                        help="后端 CLI 类型（默认 claude）")
    parser.add_argument("--cli-command", default=None,
                        help="直接指定 CLI 命令（优先级最高，如 'aider --model claude-sonnet-4'）")
    parser.add_argument("--debug-screen", action="store_true",
                        help="开启 pyte 屏幕快照调试日志（写入 _screen.log）")
    parser.add_argument("--debug-verbose", action="store_true",
                        help="debug 日志输出完整诊断信息（indicator、repr 等）")
    args = parser.parse_args()

    # 配置日志：启动阶段输出到 stdout + startup.log
    from utils.session import USER_DATA_DIR, _safe_filename
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 先配置基本输出（stdout）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # 添加启动日志 handler
    startup_handler = logging.FileHandler(USER_DATA_DIR / "startup.log", encoding="utf-8")
    startup_handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    startup_handler._startup_handler = True  # 标记为启动日志 handler
    logging.getLogger().addHandler(startup_handler)

    run_server(args.session_name, args.cli_args,
               cli_type=args.cli_type,
               cli_command=args.cli_command,
               debug_screen=args.debug_screen, debug_verbose=args.debug_verbose)
