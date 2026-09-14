"""AudioSocket-Rahmenformat (Asterisk).

Ein Rahmen besteht aus einem Typ-Byte, einer 2-Byte-Laenge (big endian) und den
Nutzdaten::

    +--------+------------------+------------------+
    | typ(1) |  laenge(2, BE)   |  nutzdaten(n)    |
    +--------+------------------+------------------+

Audio ist signed linear 16 bit, 8 kHz, mono -- ueblicherweise 320 Byte (20 ms)
pro Rahmen. Das Format ist bewusst hier isoliert, damit es ohne Asterisk und
ohne Netzwerk getestet werden kann.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterator

HEADER_SIZE = 3
MAX_PAYLOAD = 65535
SAMPLE_RATE = 8000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000  # 320


class FrameKind(IntEnum):
    """Rahmentypen des AudioSocket-Protokolls."""

    HANGUP = 0x00
    ID = 0x01
    SILENCE = 0x02
    DTMF = 0x03
    """Nicht jede Asterisk-Version sendet DTMF hier -- siehe docs/04-deployment-lmu.md."""
    AUDIO = 0x10
    ERROR = 0xFF


class ProtocolError(ValueError):
    """Der Gegenueber hat etwas gesendet, das kein gueltiger Rahmen ist."""


@dataclass(frozen=True)
class Frame:
    """Ein dekodierter AudioSocket-Rahmen."""

    kind: FrameKind
    payload: bytes = b""

    @property
    def uuid(self) -> str:
        """Kanal-UUID eines ID-Rahmens (16 Byte) als Textform."""
        if self.kind is not FrameKind.ID:
            raise ProtocolError("uuid nur bei ID-Rahmen verfuegbar")
        raw = self.payload.hex()
        if len(self.payload) != 16:
            return raw
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"

    @property
    def digit(self) -> str:
        """Gedrueckte Taste eines DTMF-Rahmens."""
        if self.kind is not FrameKind.DTMF:
            raise ProtocolError("digit nur bei DTMF-Rahmen verfuegbar")
        return self.payload.decode("ascii", errors="replace")


def encode_frame(kind: FrameKind, payload: bytes = b"") -> bytes:
    """Baut einen Rahmen; zu lange Nutzdaten werden abgelehnt, nicht gekuerzt."""
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"Nutzdaten zu lang: {len(payload)} > {MAX_PAYLOAD}")
    return bytes([int(kind)]) + len(payload).to_bytes(2, "big") + payload


def encode_audio(pcm: bytes) -> Iterator[bytes]:
    """Zerlegt PCM-Daten in 20-ms-Rahmen; der Rest wird mit Stille aufgefuellt."""
    for start in range(0, len(pcm), FRAME_BYTES):
        chunk = pcm[start : start + FRAME_BYTES]
        if len(chunk) < FRAME_BYTES:
            chunk = chunk + bytes(FRAME_BYTES - len(chunk))
        yield encode_frame(FrameKind.AUDIO, chunk)


class FrameDecoder:
    """Zerlegt einen Bytestrom in Rahmen (TCP liefert keine Rahmengrenzen)."""

    def __init__(self, *, strict: bool = False) -> None:
        self._buffer = bytearray()
        self.strict = strict
        """``strict``: unbekannte Typen als Fehler melden statt zu ueberspringen."""

    def feed(self, data: bytes) -> list[Frame]:
        """Nimmt beliebig geschnittene Bytes entgegen und gibt fertige Rahmen zurueck."""
        self._buffer.extend(data)
        out: list[Frame] = []
        while True:
            if len(self._buffer) < HEADER_SIZE:
                return out
            kind_byte = self._buffer[0]
            length = int.from_bytes(self._buffer[1:3], "big")
            if len(self._buffer) < HEADER_SIZE + length:
                return out
            payload = bytes(self._buffer[HEADER_SIZE : HEADER_SIZE + length])
            del self._buffer[: HEADER_SIZE + length]
            try:
                kind = FrameKind(kind_byte)
            except ValueError:
                if self.strict:
                    raise ProtocolError(f"Unbekannter Rahmentyp 0x{kind_byte:02x}") from None
                continue  # unbekannte Typen ignorieren, Strom bleibt synchron
            out.append(Frame(kind=kind, payload=payload))

    @property
    def pending_bytes(self) -> int:
        """Noch unvollstaendige Bytes im Puffer (Diagnose)."""
        return len(self._buffer)
