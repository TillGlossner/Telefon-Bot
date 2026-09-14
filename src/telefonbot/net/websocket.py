"""WebSocket nach RFC 6455 -- nur so viel, wie der Sprachclient braucht.

Warum selbst gebaut und nicht ``websockets`` aus PyPI: der Dienst soll auf einer
abgeschotteten Uni-VM ohne Paketquellen installierbar bleiben. Das Protokoll ist
an dieser Stelle ueberschaubar -- Handshake, Rahmen, Maskierung -- und
vollstaendig testbar.

Gebraucht wird es fuer den Sprachclient im Browser: Mikrofonaudio kommt als
binaere Rahmen herein, synthetisierte Ansagen gehen als binaere Rahmen hinaus,
Steuerinformationen laufen als JSON-Textrahmen.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from dataclasses import dataclass
from enum import IntEnum

log = logging.getLogger(__name__)

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
"""Konstante aus RFC 6455 fuer die Antwort im Handshake."""

MAX_PAYLOAD = 4 * 1024 * 1024
"""Ein Audioblock ist wenige hundert Byte gross -- alles darueber ist Unfug."""


class OpCode(IntEnum):
    FORTSETZUNG = 0x0
    TEXT = 0x1
    BINAER = 0x2
    SCHLIESSEN = 0x8
    PING = 0x9
    PONG = 0xA


class WebSocketError(Exception):
    """Der Gegenueber haelt sich nicht ans Protokoll."""


@dataclass(frozen=True)
class Message:
    """Eine vollstaendig empfangene Nachricht."""

    opcode: OpCode
    data: bytes

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")

    @property
    def is_binary(self) -> bool:
        return self.opcode is OpCode.BINAER


def accept_key(client_key: str) -> str:
    """Antwortschluessel des Handshakes berechnen."""
    digest = hashlib.sha1((client_key.strip() + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(opcode: OpCode, payload: bytes = b"", *, mask: bool = False) -> bytes:
    """Baut einen Rahmen. Server senden unmaskiert, Clients maskiert."""
    if len(payload) > MAX_PAYLOAD:
        raise WebSocketError(f"Nutzdaten zu gross: {len(payload)}")
    kopf = bytearray([0x80 | int(opcode)])  # FIN gesetzt, keine Fragmentierung
    laenge = len(payload)
    maskenbit = 0x80 if mask else 0x00
    if laenge < 126:
        kopf.append(maskenbit | laenge)
    elif laenge < 65536:
        kopf.append(maskenbit | 126)
        kopf.extend(laenge.to_bytes(2, "big"))
    else:
        kopf.append(maskenbit | 127)
        kopf.extend(laenge.to_bytes(8, "big"))
    if not mask:
        return bytes(kopf) + payload
    schluessel = os.urandom(4)
    kopf.extend(schluessel)
    return bytes(kopf) + bytes(b ^ schluessel[i % 4] for i, b in enumerate(payload))


class FrameReader:
    """Setzt aus einem Bytestrom vollstaendige Nachrichten zusammen."""

    def __init__(self) -> None:
        self._puffer = bytearray()
        self._teile = bytearray()
        self._teil_opcode: OpCode | None = None

    def feed(self, daten: bytes) -> list[Message]:
        """Nimmt beliebig geschnittene Bytes und gibt fertige Nachrichten zurueck."""
        self._puffer.extend(daten)
        fertig: list[Message] = []
        while True:
            rahmen = self._naechster_rahmen()
            if rahmen is None:
                return fertig
            fin, opcode, payload = rahmen

            if opcode in (OpCode.PING, OpCode.PONG, OpCode.SCHLIESSEN):
                fertig.append(Message(opcode=opcode, data=payload))
                continue

            if opcode is OpCode.FORTSETZUNG:
                if self._teil_opcode is None:
                    raise WebSocketError("Fortsetzungsrahmen ohne Anfang")
                self._teile.extend(payload)
            else:
                if self._teil_opcode is not None:
                    raise WebSocketError("Neue Nachricht vor Ende der vorherigen")
                self._teil_opcode = opcode
                self._teile = bytearray(payload)

            if fin:
                fertig.append(Message(opcode=self._teil_opcode, data=bytes(self._teile)))
                self._teile = bytearray()
                self._teil_opcode = None

    def _naechster_rahmen(self) -> tuple[bool, OpCode, bytes] | None:
        if len(self._puffer) < 2:
            return None
        erstes, zweites = self._puffer[0], self._puffer[1]
        fin = bool(erstes & 0x80)
        try:
            opcode = OpCode(erstes & 0x0F)
        except ValueError:
            raise WebSocketError(f"Unbekannter Opcode {erstes & 0x0F}") from None
        maskiert = bool(zweites & 0x80)
        laenge = zweites & 0x7F
        versatz = 2

        if laenge == 126:
            if len(self._puffer) < versatz + 2:
                return None
            laenge = int.from_bytes(self._puffer[versatz : versatz + 2], "big")
            versatz += 2
        elif laenge == 127:
            if len(self._puffer) < versatz + 8:
                return None
            laenge = int.from_bytes(self._puffer[versatz : versatz + 8], "big")
            versatz += 8
        if laenge > MAX_PAYLOAD:
            raise WebSocketError(f"Nutzdaten zu gross: {laenge}")

        schluessel = b""
        if maskiert:
            if len(self._puffer) < versatz + 4:
                return None
            schluessel = bytes(self._puffer[versatz : versatz + 4])
            versatz += 4

        if len(self._puffer) < versatz + laenge:
            return None
        payload = bytes(self._puffer[versatz : versatz + laenge])
        del self._puffer[: versatz + laenge]
        if maskiert:
            payload = bytes(b ^ schluessel[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    @property
    def pending_bytes(self) -> int:
        return len(self._puffer)


class WebSocketConnection:
    """Eine offene Verbindung auf Serverseite."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._frames = FrameReader()
        self._eingang: asyncio.Queue[Message | None] = asyncio.Queue()
        self._geschlossen = False
        self._pumpe: asyncio.Task | None = None

    @property
    def closed(self) -> bool:
        return self._geschlossen

    @property
    def peer(self) -> str:
        return str(self._writer.get_extra_info("peername"))

    def start(self) -> None:
        """Startet das Lesen im Hintergrund."""
        if self._pumpe is None:
            self._pumpe = asyncio.create_task(self._lesen())

    async def _lesen(self) -> None:
        try:
            while not self._geschlossen:
                daten = await self._reader.read(8192)
                if not daten:
                    break
                for nachricht in self._frames.feed(daten):
                    if nachricht.opcode is OpCode.SCHLIESSEN:
                        await self.close()
                        break
                    if nachricht.opcode is OpCode.PING:
                        await self._senden(OpCode.PONG, nachricht.data)
                        continue
                    if nachricht.opcode is OpCode.PONG:
                        continue
                    await self._eingang.put(nachricht)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        except WebSocketError as fehler:
            log.warning("Protokollfehler von %s: %s", self.peer, fehler)
        finally:
            self._geschlossen = True
            await self._eingang.put(None)

    async def recv(self) -> Message | None:
        """Naechste Nachricht; ``None``, wenn die Verbindung endet."""
        return await self._eingang.get()

    async def send_bytes(self, payload: bytes) -> None:
        await self._senden(OpCode.BINAER, payload)

    async def send_text(self, text: str) -> None:
        await self._senden(OpCode.TEXT, text.encode("utf-8"))

    async def _senden(self, opcode: OpCode, payload: bytes) -> None:
        if self._geschlossen:
            return
        try:
            self._writer.write(encode_frame(opcode, payload))
            await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self._geschlossen = True

    async def close(self, code: int = 1000) -> None:
        if self._geschlossen:
            return
        self._geschlossen = True
        try:
            self._writer.write(encode_frame(OpCode.SCHLIESSEN, code.to_bytes(2, "big")))
            await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # Verbindung ist ohnehin hin
                pass
            await self._eingang.put(None)
