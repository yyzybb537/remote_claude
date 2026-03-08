"""
Proxy Server

- 使用 PTY 启动 Claude CLI
- 通过 Unix Socket 接受多客户端连接
- 管理控制权状态
- 广播输出到所有连接的客户端
- 输出历史缓存
"""

import asyncio
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
from pathlib import Path
from typing import Dict, List, Optional

from utils.protocol import (
    Message, MessageType, InputMessage, OutputMessage,
    HistoryMessage, ErrorMessage, ResizeMessage,
    encode_message, decode_message
)
from utils.session import (
    get_socket_path, get_pid_file, ensure_socket_dir,
    generate_client_id, cleanup_session
)

try:
    from stats import track as _track_stats
except Exception:
    def _track_stats(*args, **kwargs): pass


# 历史缓存大小（字节）
HISTORY_BUFFER_SIZE = 100 * 1024  # 100KB


# ── 全量快照架构 ─────────────────────────────────────────────────────────────

@dataclass
class _FrameObs:
    """单帧状态观测（用于时序窗口平滑）"""
    ts: float
    status_line: Optional[object]  # 本帧的 StatusLine（None=无）
    block_blink: bool = False      # 本帧最后一个 OutputBlock 是否 is_streaming=True
    has_background_agents: bool = False  # 底部栏是否有后台 agent 信息


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



class OutputWatcher:
    """PTY 输出监视器：全量快照架构

    PTY 输出直接实时喂给持久化 pyte Screen；flush 时 screen 已是最新状态，
    直接 parse → 时序窗口平滑 → 累积列表合并 → 生成 ClaudeWindow 快照 → 写 debug + 共享内存。
    """

    WINDOW_SECONDS = 1.0

    def __init__(self, session_name: str, cols: int, rows: int,
                 on_snapshot=None, debug_screen: bool = False,
                 debug_verbose: bool = False):
        self._session_name = session_name
        self._cols = cols
        self._rows = rows
        self._pending = False
        self._on_snapshot = on_snapshot  # 回调：写共享内存
        self._debug_screen = debug_screen  # --debug-screen 开启后才写 _screen.log
        self._debug_verbose = debug_verbose  # --debug-verbose 开启后输出 indicator/repr 等诊断信息
        safe_name = session_name.replace('/', '_')
        self._debug_file = f"/tmp/remote-claude/{safe_name}_messages.log"
        # 持久化 pyte 渲染器：PTY 数据直接实时喂入，flush 时直接读 screen
        from rich_text_renderer import RichTextRenderer
        self._renderer = RichTextRenderer(columns=cols, lines=rows)
        # 持久化解析器（跨帧保留 dot_row_cache）
        from component_parser import ScreenParser
        import logging as _logging
        _logging.getLogger('ComponentParser').setLevel(_logging.DEBUG)
        _blink_handler = _logging.FileHandler(
            f"/tmp/remote-claude/{safe_name}_blink.log"
        )
        _blink_handler.setFormatter(_logging.Formatter('%(asctime)s %(message)s', '%H:%M:%S'))
        _logging.getLogger('ComponentParser').addHandler(_blink_handler)
        self._parser = ScreenParser()
        # 时序窗口（迁移自 MessageQueue）
        self._frame_window: deque = deque()
        # 最近快照（供外部读取）
        self.last_window: Optional[ClaudeWindow] = None
        # PTY 静止后延迟重刷：消除窗口平滑的延迟效应
        self._reflush_handle: Optional[asyncio.TimerHandle] = None

    def resize(self, cols: int, rows: int):
        """重建 renderer 以适应新尺寸，历史随之丢失（可接受）。
        PTY resize 后 Claude 会全屏重绘，新 screen 自然会被填充。"""
        self._cols = cols
        self._rows = rows
        from rich_text_renderer import RichTextRenderer
        self._renderer = RichTextRenderer(columns=cols, lines=rows)

    def feed(self, data: bytes):
        self._renderer.feed(data)  # 直接喂持久化 screen，不再缓存原始字节
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
        try:
            from utils.components import StatusLine, BottomBar, Divider, OutputBlock, AgentPanelBlock, OptionBlock

            t0 = time.time()

            if self._debug_screen:
                self._write_screen_debug(self._renderer.screen)
            t1 = time.time()

            # 1. 解析（ScreenParser 不改；pyte 已在 feed() 里实时更新）
            components = self._parser.parse(self._renderer.screen)
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
            for b in reversed(visible_blocks):
                if isinstance(b, OutputBlock):
                    last_ob_blink = b.is_streaming
                    last_ob_content = b.content[:40]
                    break
            if last_ob_blink:
                _blink_log = open(f"/tmp/remote-claude/{self._session_name}_blink.log", "a")
                _blink_log.write(
                    f"[{time.strftime('%H:%M:%S')}] raw-blink  last_ob={last_ob_content!r}\n"
                )
                _blink_log.close()

            self._frame_window.append(_FrameObs(
                ts=now,
                status_line=raw_status_line,
                block_blink=last_ob_blink,
                has_background_agents=getattr(raw_bottom_bar, 'has_background_agents', False) if raw_bottom_bar else False,
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

            # 4c. block blink 平滑：窗口内任意帧有 blink → streaming
            #     修改 visible_blocks 中最后一个 OutputBlock（平滑后再合并）
            window_block_active = any(o.block_blink for o in window_list)
            if window_block_active:
                for b in reversed(visible_blocks):
                    if isinstance(b, OutputBlock):
                        _blink_log = open(f"/tmp/remote-claude/{self._session_name}_blink.log", "a")
                        _blink_log.write(
                            f"[{time.strftime('%H:%M:%S')}] win-smooth last_ob={b.content[:40]!r}"
                            f"  window_frames={len(window_list)}"
                            f"  blink_frames={sum(1 for o in window_list if o.block_blink)}\n"
                        )
                        _blink_log.close()
                        b.is_streaming = True
                        break

            # 5. 直接使用 visible_blocks（pyte 2000 行已保留全部历史）
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
            )
            self.last_window = window

            # 7. 输出
            t2 = time.time()
            self._write_window_debug(window)
            t3 = time.time()
            if self._on_snapshot:
                self._on_snapshot(window)
            t4 = time.time()

            with open(f"/tmp/remote-claude/{self._session_name.replace('/', '_')}_flush.log", "a") as _f:
                _f.write(
                    f"[flush] screen_log={1000*(t1-t0):.1f}ms  parse={1000*(t2-t1):.1f}ms  "
                    f"msg_log={1000*(t3-t2):.1f}ms  snapshot={1000*(t4-t3):.1f}ms  "
                    f"total={1000*(t4-t0):.1f}ms  rows={self._rows}\n"
                    f"  └─ {self._parser.last_parse_timing}\n"
                )

        except Exception as e:
            print(f"[OutputWatcher] flush 失败: {e}")

    def _write_window_debug(self, window: ClaudeWindow):
        """将 ClaudeWindow 快照写入调试文件"""
        try:
            from utils.components import OutputBlock, UserInput, OptionBlock, AgentPanelBlock
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
                    lines.append(f"status_line: {sl.ansi_indicator} {sl.ansi_raw[:120]}\x1b[0m")
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
                else:
                    lines.append(f"[{i}] {type(block).__name__}: {str(block)[:80]}")
            lines.append("")
            lines.append("-----")
            with open(self._debug_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass

    def _write_screen_debug(self, screen):
        """将 pyte 屏幕内容写入调试文件（_screen.log）"""
        base = f"/tmp/remote-claude/{self._session_name.replace('/', '_')}"
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
                buf = [' '] * screen.columns
                for col, char in screen.buffer[row].items():
                    buf[col] = char.data
                rstripped = ''.join(buf).rstrip()
                if not rstripped:
                    lines.append(f"{row:3d} |")
                    continue
                try:
                    c0 = screen.buffer[row][0]
                    col0_blink = getattr(c0, "blink", False)
                except (KeyError, IndexError):
                    col0_blink = False
                blink_mark = "B" if col0_blink else " "
                lines.append(f"{row:3d}{blink_mark}|{rstripped}")
            with open(screen_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass


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
        except Exception as e:
            print(f"[Server] 发送消息失败 ({self.client_id}): {e}")

    async def read_message(self) -> Optional[Message]:
        """读取一条消息"""
        while True:
            # 检查缓冲区中是否有完整消息
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    return decode_message(line)
                except Exception as e:
                    print(f"[Server] 解析消息失败: {e}")
                    continue

            # 读取更多数据
            try:
                data = await self.reader.read(4096)
                if not data:
                    return None
                self.buffer += data
            except Exception:
                return None

    def close(self):
        """关闭连接"""
        try:
            self.writer.close()
        except Exception:
            pass


class ProxyServer:
    """Proxy Server"""

    def __init__(self, session_name: str, claude_args: list = None,
                 debug_screen: bool = False, debug_verbose: bool = False):
        self.session_name = session_name
        self.claude_args = claude_args or []
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
        ensure_socket_dir()

        # 清理旧的 socket 文件
        if self.socket_path.exists():
            self.socket_path.unlink()

        # 启动 PTY
        self._start_pty()

        # 写入 PID 文件
        self.pid_file.write_text(str(os.getpid()))

        # 启动 Unix Socket 服务器
        self.server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path)
        )

        self.running = True
        _track_stats('session', 'start', session_name=self.session_name)
        print(f"[Server] 已启动: {self.socket_path}")

        # 启动 PTY 读取任务
        asyncio.create_task(self._read_pty())

        # 等待服务器关闭
        async with self.server:
            await self.server.serve_forever()

    # PTY 终端尺寸：与 lark_client 的 pyte 渲染器保持一致
    PTY_COLS = 220
    PTY_ROWS = 2000

    def _start_pty(self):
        """启动 PTY 并运行 Claude"""
        pid, fd = pty.fork()

        if pid == 0:
            # 恢复 TERM 以支持 kitty keyboard protocol（Shift+Enter 等扩展键）
            # tmux 会将 TERM 改为 tmux-256color，导致 Claude CLI 不启用 kitty protocol
            os.environ['TERM'] = 'xterm-256color'
            # 清除 tmux 标识变量（PTY 数据不经过 tmux，不应让 Claude CLI 误判终端环境）
            for key in ('TMUX', 'TMUX_PANE'):
                os.environ.pop(key, None)
            os.execvp("claude", ["claude"] + self.claude_args)
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

            print(f"[Server] Claude 已启动 (PID: {pid}, PTY: {self.PTY_COLS}×{self.PTY_ROWS})")

    async def _read_pty(self):
        """读取 PTY 输出并广播"""
        loop = asyncio.get_event_loop()

        while self.running and self.master_fd is not None:
            try:
                # 使用 asyncio 读取
                data = await loop.run_in_executor(
                    None, self._read_pty_sync
                )
                if data:
                    # 保存到历史
                    self.history.append(data)
                    # 广播给所有客户端
                    await self._broadcast_output(data)
                elif data is None:
                    # 暂时无数据（BlockingIOError），稍等继续
                    await asyncio.sleep(0.01)
                else:
                    # os.read 返回 b""：PTY 已关闭（子进程退出）
                    break
            except Exception as e:
                if self.running:
                    print(f"[Server] 读取 PTY 错误: {e}")
                break

        # Claude 退出
        print("[Server] Claude 已退出")
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

        print(f"[Server] 客户端连接: {client_id}")
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
        except Exception as e:
            print(f"[Server] 客户端处理错误 ({client_id}): {e}")
        finally:
            # 清理
            del self.clients[client_id]
            client.close()
            print(f"[Server] 客户端断开: {client_id}")

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
        except Exception as e:
            print(f"[Server] 写入 PTY 错误: {e}")

        # 广播输入给其他客户端（飞书侧可以感知终端用户的输入内容）
        for cid, client in list(self.clients.items()):
            if cid != client_id:
                try:
                    await client.send(msg)
                except Exception:
                    pass

    async def _handle_resize(self, client_id: str, msg: ResizeMessage):
        """处理终端大小变化：同步更新 PTY 和 pyte 渲染尺寸，清空 raw buffer。
        Claude 收到 SIGWINCH 后会全屏重绘，buffer 清空后自然恢复为新尺寸的完整屏幕数据。"""
        try:
            # output_watcher 的 rows 固定为 PTY_ROWS（2000），不跟随客户端终端尺寸变化
            # terminal client 直接渲染 PTY 原始输出，不依赖 output_watcher，无需同步 rows
            self.output_watcher.resize(msg.cols, self.PTY_ROWS)
            winsize = struct.pack('HHHH', msg.rows, msg.cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            print(f"[Server] 调整终端大小错误: {e}")

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
            except Exception:
                pass

        # 关闭共享状态（会删除 .mq 文件）
        elapsed = int(time.time() - self._start_time)
        _track_stats('session', 'end', session_name=self.session_name, value=elapsed)
        self.shared_state.close()

        # 清理文件
        cleanup_session(self.session_name)

        print("[Server] 已关闭")


def run_server(session_name: str, claude_args: list = None,
               debug_screen: bool = False, debug_verbose: bool = False):
    """运行服务器"""
    server = ProxyServer(session_name, claude_args, debug_screen=debug_screen,
                         debug_verbose=debug_verbose)

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
    parser = argparse.ArgumentParser(description="Remote Claude Server")
    parser.add_argument("session_name", help="会话名称")
    parser.add_argument("claude_args", nargs="*", help="传递给 Claude 的参数")
    parser.add_argument("--debug-screen", action="store_true",
                        help="开启 pyte 屏幕快照调试日志（写入 _screen.log）")
    parser.add_argument("--debug-verbose", action="store_true",
                        help="debug 日志输出完整诊断信息（indicator、repr 等）")
    args = parser.parse_args()

    run_server(args.session_name, args.claude_args, debug_screen=args.debug_screen,
               debug_verbose=args.debug_verbose)
