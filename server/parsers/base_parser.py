"""终端屏幕解析器基类

定义统一接口：parse(screen) -> List[Component]
ClaudeParser 和 CodexParser 均继承此类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pyte


@dataclass
class AutoAnswerBlock:
    """自动应答记录块

    用于记录自动应答的执行情况，写入共享内存后由客户端渲染。
    """
    block_id: str
    content: str
    action_type: str  # "select" | "input"
    selected_value: Optional[str] = None
    selected_label: Optional[str] = None
    input_text: Optional[str] = None
    timestamp: float = 0.0
    start_row: int = 0


class BaseParser(ABC):
    """终端屏幕解析器基类。

    具体实现（ClaudeParser、CodexParser 等）继承此类，
    负责将 pyte.Screen 快照解析为 Component 列表。

    Component 列表包含两类组件：
    - 累积型 Block：OutputBlock, UserInput, PlanBlock, SystemBlock
    - 状态型组件：StatusLine, BottomBar, AgentPanelBlock, OptionBlock

    OutputWatcher 读取 last_input_text / last_input_ansi_text / last_layout_mode
    等属性来辅助生成 ClaudeWindow 快照。
    """

    # 最近一次解析结果的辅助属性（由子类在 parse() 中更新）
    last_input_text: str = ''
    last_input_ansi_text: str = ''
    last_parse_timing: str = ''
    last_layout_mode: str = 'normal'
    # 诊断用：记录最近一次 parse 的区域统计与组件统计
    last_region_stats: Dict[str, Any] = None
    last_component_stats: Dict[str, Any] = None

    @abstractmethod
    def parse(self, screen: pyte.Screen) -> List:
        """解析 pyte 屏幕，返回 Component 列表。

        Args:
            screen: pyte.Screen 快照（持久化渲染器的当前状态）

        Returns:
            Component 列表，包含累积型 Block 和状态型组件的混合。
            调用方（OutputWatcher）负责按类型分拣。
        """
        ...
