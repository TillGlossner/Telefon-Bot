"""Netzwerkbausteine: WebSocket und ein kleiner Dateiserver."""

from telefonbot.net.websocket import (
    Message,
    OpCode,
    WebSocketConnection,
    WebSocketError,
    accept_key,
    encode_frame,
)

__all__ = [
    "Message",
    "OpCode",
    "WebSocketConnection",
    "WebSocketError",
    "accept_key",
    "encode_frame",
]
