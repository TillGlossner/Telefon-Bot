"""Telefonie-Anbindung: Asterisk AudioSocket, Fake-Transport, Textsimulator."""

from telefonbot.telephony.base import (
    AudioFrame,
    AudioTransport,
    CallEnded,
    DtmfDigit,
    InboundEvent,
)
from telefonbot.telephony.protocol import Frame, FrameDecoder, FrameKind, encode_frame

__all__ = [
    "AudioFrame",
    "AudioTransport",
    "CallEnded",
    "DtmfDigit",
    "Frame",
    "FrameDecoder",
    "FrameKind",
    "InboundEvent",
    "encode_frame",
]
