"""测试 CONTROL 消息类型"""

from utils.protocol import (
    Message, MessageType, ControlMessage, ControlResponseMessage,
    encode_message, decode_message
)


def test_control_message_creation():
    """测试 CONTROL 消息创建"""
    msg = ControlMessage("shutdown", "client-123")
    assert msg.type == MessageType.CONTROL
    assert msg.action == "shutdown"
    assert msg.client_id == "client-123"


def test_control_message_encode_decode():
    """测试 CONTROL 消息编解码"""
    msg = ControlMessage("restart", "client-456")
    encoded = encode_message(msg)
    decoded = decode_message(encoded.strip())
    assert decoded.type == MessageType.CONTROL
    assert decoded.action == "restart"
    assert decoded.client_id == "client-456"


def test_control_response_message():
    """测试 CONTROL_RESPONSE 消息"""
    msg = ControlResponseMessage(True, "重启成功")
    encoded = encode_message(msg)
    decoded = decode_message(encoded.strip())
    assert decoded.type == MessageType.CONTROL_RESPONSE
    assert decoded.success is True
    assert decoded.message == "重启成功"
