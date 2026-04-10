"""
通信协议定义

消息格式：JSON + 换行符分隔
二进制数据使用 base64 编码
"""

import json
import base64
from dataclasses import dataclass, asdict
from typing import Optional, List
from enum import Enum


class MessageType(str, Enum):
    """消息类型"""
    INPUT = "input"          # 客户端 -> 服务端：用户输入
    OUTPUT = "output"        # 服务端 -> 客户端：Claude 输出
    HISTORY = "history"      # 历史输出（重连时）
    ERROR = "error"          # 错误消息
    RESIZE = "resize"        # 终端大小变化
    CONTROL = "control"      # 控制命令（shutdown/restart/update）
    CONTROL_RESPONSE = "control_response"  # 控制命令响应


@dataclass
class Message:
    """基础消息"""
    type: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "Message":
        obj = json.loads(data)
        msg_type = obj.get("type")

        if msg_type == MessageType.INPUT:
            return InputMessage.from_dict(obj)
        elif msg_type == MessageType.OUTPUT:
            return OutputMessage.from_dict(obj)
        elif msg_type == MessageType.HISTORY:
            return HistoryMessage.from_dict(obj)
        elif msg_type == MessageType.ERROR:
            return ErrorMessage.from_dict(obj)
        elif msg_type == MessageType.RESIZE:
            return ResizeMessage.from_dict(obj)
        elif msg_type == MessageType.CONTROL:
            return ControlMessage.from_dict(obj)
        elif msg_type == MessageType.CONTROL_RESPONSE:
            return ControlResponseMessage.from_dict(obj)
        else:
            raise ValueError(f"Unknown message type: {msg_type}")


@dataclass
class InputMessage(Message):
    """用户输入消息"""
    data: str  # base64 编码的输入
    client_id: str

    def __init__(self, data: bytes, client_id: str):
        super().__init__(type=MessageType.INPUT)
        self.data = base64.b64encode(data).decode('ascii')
        self.client_id = client_id

    def get_data(self) -> bytes:
        return base64.b64decode(self.data)

    @classmethod
    def from_dict(cls, obj: dict) -> "InputMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.data = obj["data"]
        msg.client_id = obj["client_id"]
        return msg


@dataclass
class OutputMessage(Message):
    """Claude 输出消息"""
    data: str  # base64 编码的输出

    def __init__(self, data: bytes):
        super().__init__(type=MessageType.OUTPUT)
        self.data = base64.b64encode(data).decode('ascii')

    def get_data(self) -> bytes:
        return base64.b64decode(self.data)

    @classmethod
    def from_dict(cls, obj: dict) -> "OutputMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.data = obj["data"]
        return msg


@dataclass
class HistoryMessage(Message):
    """历史输出消息（重连时发送）"""
    data: str  # base64 编码的历史输出

    def __init__(self, data: bytes):
        super().__init__(type=MessageType.HISTORY)
        self.data = base64.b64encode(data).decode('ascii')

    def get_data(self) -> bytes:
        return base64.b64decode(self.data)

    @classmethod
    def from_dict(cls, obj: dict) -> "HistoryMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.data = obj["data"]
        return msg


@dataclass
class ErrorMessage(Message):
    """错误消息"""
    message: str
    code: Optional[str] = None

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(type=MessageType.ERROR)
        self.message = message
        self.code = code

    @classmethod
    def from_dict(cls, obj: dict) -> "ErrorMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.message = obj["message"]
        msg.code = obj.get("code")
        return msg


@dataclass
class ResizeMessage(Message):
    """终端大小变化消息"""
    rows: int
    cols: int
    client_id: str

    def __init__(self, rows: int, cols: int, client_id: str):
        super().__init__(type=MessageType.RESIZE)
        self.rows = rows
        self.cols = cols
        self.client_id = client_id

    @classmethod
    def from_dict(cls, obj: dict) -> "ResizeMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.rows = obj["rows"]
        msg.cols = obj["cols"]
        msg.client_id = obj["client_id"]
        return msg


@dataclass
class ControlMessage(Message):
    """控制命令消息"""
    action: str  # shutdown / restart / update
    client_id: str

    def __init__(self, action: str, client_id: str):
        super().__init__(type=MessageType.CONTROL)
        self.action = action
        self.client_id = client_id

    @classmethod
    def from_dict(cls, obj: dict) -> "ControlMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.action = obj["action"]
        msg.client_id = obj["client_id"]
        return msg


@dataclass
class ControlResponseMessage(Message):
    """控制命令响应"""
    success: bool
    message: str

    def __init__(self, success: bool, message: str):
        super().__init__(type=MessageType.CONTROL_RESPONSE)
        self.success = success
        self.message = message

    @classmethod
    def from_dict(cls, obj: dict) -> "ControlResponseMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.success = obj["success"]
        msg.message = obj["message"]
        return msg


def encode_message(msg: Message) -> bytes:
    """编码消息为字节流（JSON + 换行符）"""
    return (msg.to_json() + "\n").encode('utf-8')


def decode_message(data: bytes) -> Message:
    """解码消息"""
    return Message.from_json(data.decode('utf-8').strip())
