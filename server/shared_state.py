"""
会话共享状态 (mmap) — 全量快照架构

Server 进程将 ClaudeWindow 快照全量写入 mmap 文件，其他进程可通过
SharedStateReader 随时读取最新快照。

设计原则：
- 每次 write_snapshot() 全量写入序列化后的 ClaudeWindow JSON
- 读端一次 read() 获取完整快照，无需逐条拼装
- 写入复杂度 O(blocks 总数)，但避免了增量状态污染问题

内存布局（200MB mmap 文件）：
  [Header      64B] @0       magic(4B) + version(4B) + snapshot_len(4B) + sequence(4B) + 保留
  [Snapshot  ~200MB] @64     JSON 序列化的 ClaudeWindow 快照

文件路径：/tmp/remote-claude/<name>.mq
"""

import json
import mmap
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Optional

# ── 布局常量 ──────────────────────────────────────────────────────────────────
MMAP_SIZE        = 200 * 1024 * 1024  # 200MB
HEADER_SIZE      = 64

HEADER_OFFSET    = 0
COMPLETED_OFFSET = HEADER_SIZE  # @64，快照数据起始

MAGIC   = b'RCMQ'
VERSION = 2

# Header 内字段偏移
_H_MAGIC          = 0   # 4B
_H_VERSION        = 4   # 4B uint32
_H_SNAPSHOT_LEN   = 8   # 4B uint32 — 快照 JSON 长度
_H_SEQUENCE       = 12  # 4B uint32 — 写入序列号（单调递增）
# [16:64] 保留


def get_mq_path(session_name: str) -> Path:
    """获取会话的共享状态文件路径"""
    from utils.session import get_mq_path as _get_mq_path
    return _get_mq_path(session_name)


def _component_to_dict(c) -> dict:
    d = asdict(c)
    d['_type'] = type(c).__name__
    return d


def _block_id_from_dict(d: dict) -> str:
    """从已序列化的 component dict 计算 block_id（与 server._block_id 逻辑一致）"""
    t = d.get('_type', '')
    if t == 'UserInput':
        return f"U:{d.get('text', '')[:80]}"
    elif t == 'OutputBlock':
        content = d.get('content', '')
        first_line = content.split('\n', 1)[0].strip()[:80]
        return f"O:{first_line}"
    elif t == 'OptionBlock':
        sub = d.get('sub_type', 'option')
        if sub == 'permission':
            return f"P:{d.get('question', '')[:80]}"
        return f"Q:{d.get('question', '')[:80]}"
    elif t == 'PermissionBlock':
        # 向后兼容旧数据
        return f"P:{d.get('question', '')[:80]}"
    elif t == 'AgentPanelBlock':
        pt = d.get('panel_type', '')
        if pt == 'detail':
            return f"AP:{d.get('agent_name', '')[:80]}"
        elif pt == 'summary':
            return f"AP:summary:{d.get('agent_count', 0)}"
        return f"AP:list:{d.get('agent_count', 0)}"
    return ""


# ── Writer ────────────────────────────────────────────────────────────────────

class SharedStateWriter:
    """写端：Server 进程持有，生命周期与 ProxyServer 相同"""

    def __init__(self, session_name: str):
        self._path = get_mq_path(session_name)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        self._f = open(self._path, 'w+b')
        self._f.truncate(MMAP_SIZE)
        self._f.flush()
        self._mm = mmap.mmap(self._f.fileno(), MMAP_SIZE)

        # 写入 header 初始值（magic + version + 全零计数字段）
        self._mm.seek(HEADER_OFFSET)
        self._mm.write(MAGIC)
        self._mm.write(struct.pack('>I', VERSION))
        self._mm.write(b'\x00' * (HEADER_SIZE - 8))
        self._mm.flush()

        self._sequence = 0

    def write_snapshot(self, window) -> None:
        """全量写入 ClaudeWindow 快照"""
        try:
            blocks = []
            for b in window.blocks:
                d = _component_to_dict(b)
                d['block_id'] = _block_id_from_dict(d)
                blocks.append(d)
            # agent_panel 序列化（状态型组件，独立于 blocks）
            agent_panel_dict = None
            if window.agent_panel:
                agent_panel_dict = _component_to_dict(window.agent_panel)
                agent_panel_dict['block_id'] = _block_id_from_dict(agent_panel_dict)

            # option_block 序列化（状态型组件，独立于 blocks）
            option_block_dict = None
            if window.option_block:
                option_block_dict = _component_to_dict(window.option_block)
                option_block_dict['block_id'] = _block_id_from_dict(option_block_dict)

            snapshot = {
                "blocks": blocks,
                "status_line": _component_to_dict(window.status_line) if window.status_line else None,
                "bottom_bar": _component_to_dict(window.bottom_bar) if window.bottom_bar else None,
                "agent_panel": agent_panel_dict,
                "option_block": option_block_dict,
                "input_area_text": window.input_area_text,
                "timestamp": window.timestamp,
                "layout_mode": window.layout_mode,
            }
            data = json.dumps(snapshot, ensure_ascii=False).encode('utf-8')

            # 超出可用空间则跳过（理论上 200MB 足够）
            if COMPLETED_OFFSET + len(data) > MMAP_SIZE:
                return

            self._sequence += 1
            mm = self._mm
            mm.seek(COMPLETED_OFFSET)
            mm.write(data)

            # 更新 header（snapshot_len + sequence）
            mm.seek(HEADER_OFFSET + _H_SNAPSHOT_LEN)
            mm.write(struct.pack('>II', len(data), self._sequence))
            mm.flush()
        except Exception:
            pass

    def close(self):
        try:
            self._mm.close()
            self._f.close()
            self._path.unlink(missing_ok=True)
        except Exception:
            pass


# ── Reader ────────────────────────────────────────────────────────────────────

class SharedStateReader:
    """读端：其他进程持有，按需调用 read() 获取最新快照"""

    def __init__(self, session_name: str):
        path = get_mq_path(session_name)
        self._f = open(path, 'rb')
        self._mm = mmap.mmap(self._f.fileno(), MMAP_SIZE, access=mmap.ACCESS_READ)

    def read(self) -> dict:
        """读取当前完整快照，返回 dict"""
        mm = self._mm

        # 校验 magic
        mm.seek(HEADER_OFFSET)
        if mm.read(4) != MAGIC:
            return {"blocks": [], "status_line": None, "bottom_bar": None, "option_block": None}

        # 校验版本
        version = struct.unpack('>I', mm.read(4))[0]
        if version < 2:
            return {"blocks": [], "status_line": None, "bottom_bar": None, "option_block": None}

        # 读 snapshot_len + sequence
        snapshot_len, sequence = struct.unpack('>II', mm.read(8))
        if snapshot_len == 0:
            return {"blocks": [], "status_line": None, "bottom_bar": None, "option_block": None}

        # 读快照 JSON
        mm.seek(COMPLETED_OFFSET)
        try:
            return json.loads(mm.read(snapshot_len).decode('utf-8'))
        except Exception:
            return {"blocks": [], "status_line": None, "bottom_bar": None, "option_block": None}

    def close(self):
        try:
            self._mm.close()
            self._f.close()
        except Exception:
            pass
