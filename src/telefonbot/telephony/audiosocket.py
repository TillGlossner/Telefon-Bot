"""AudioSocket-Server fuer Asterisk.

Asterisk baut pro Anruf eine TCP-Verbindung zu diesem Server auf
(``AudioSocket(<uuid>,host:port)`` im Dialplan) und schickt darueber den
Gespraechston. Wir antworten mit synthetisierter Sprache.

Warum AudioSocket und nicht ARI/externalMedia: es ist die einfachste Variante
mit direktem Zugriff auf rohes PCM, laeuft ohne zusaetzlichen Mediaserver und
bleibt vollstaendig on-premise.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import AsyncIterator, Awaitable, Callable

from telefonbot.audio.pcm import Samples, bytes_to_samples, samples_to_bytes
from telefonbot.telephony.base import AudioFrame, CallEnded, CallInfo, DtmfDigit, InboundEvent
from telefonbot.telephony.protocol import (
    FRAME_BYTES,
    FRAME_MS,
    SAMPLE_RATE,
    FrameDecoder,
    FrameKind,
    encode_frame,
)

log = logging.getLogger(__name__)

READ_CHUNK = 4096


class AudioSocketTransport:
    """Ein Telefonkanal ueber eine AudioSocket-Verbindung."""

    sample_rate = SAMPLE_RATE
    frame_ms = FRAME_MS

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        info: CallInfo | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self.info = info or CallInfo()
        self._decoder = FrameDecoder()
        self._playing = False
        self._cancel_playback = False
        self._closed = False
        self.pending_transfer: str | None = None
        """Asterisk kann ueber AudioSocket nicht weiterverbinden -- der Dialplan
        holt sich das Ziel nach Gespraechsende ueber die Control-API ab."""

    # ---------------------------------------------------------------- Eingang

    async def events(self) -> AsyncIterator[InboundEvent]:
        """Liest den Socket und uebersetzt Rahmen in Ereignisse."""
        while not self._closed:
            try:
                data = await self._reader.read(READ_CHUNK)
            except (ConnectionResetError, asyncio.IncompleteReadError):
                yield CallEnded("connection_reset")
                return
            if not data:
                yield CallEnded("connection_closed")
                return

            for frame in self._decoder.feed(data):
                if frame.kind is FrameKind.AUDIO:
                    yield AudioFrame(samples=bytes_to_samples(frame.payload))
                elif frame.kind is FrameKind.DTMF:
                    digit = frame.digit.strip()
                    if digit:
                        yield DtmfDigit(digit=digit)
                elif frame.kind is FrameKind.ID:
                    self.info.call_id = frame.uuid
                    log.info("Anruf %s angenommen", frame.uuid)
                elif frame.kind is FrameKind.HANGUP:
                    yield CallEnded("remote_hangup")
                    return
                elif frame.kind is FrameKind.ERROR:
                    code = frame.payload.hex() or "unbekannt"
                    log.warning("AudioSocket meldet Fehler %s", code)
                    yield CallEnded(f"error_{code}")
                    return

    # ---------------------------------------------------------------- Ausgang

    async def send_audio(self, samples: Samples) -> None:
        """Gibt Audio in Echtzeit aus; durch :meth:`stop_audio` abbrechbar.

        Die Rahmen werden im 20-ms-Takt getaktet. Ohne diese Taktung wuerde der
        gesamte Ansagetext in den Puffer der Telefonanlage gekippt und Barge-in
        waere wirkungslos.
        """
        payload = samples_to_bytes(samples)
        self._playing = True
        self._cancel_playback = False
        next_deadline = time.monotonic()
        try:
            for start in range(0, len(payload), FRAME_BYTES):
                if self._cancel_playback or self._closed:
                    log.debug("Wiedergabe abgebrochen (Barge-in)")
                    break
                chunk = payload[start : start + FRAME_BYTES]
                if len(chunk) < FRAME_BYTES:
                    chunk += bytes(FRAME_BYTES - len(chunk))
                self._writer.write(encode_frame(FrameKind.AUDIO, chunk))
                await self._writer.drain()
                next_deadline += FRAME_MS / 1000
                delay = next_deadline - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
        except (ConnectionResetError, BrokenPipeError):
            self._closed = True
        finally:
            self._playing = False

    async def stop_audio(self) -> None:
        self._cancel_playback = True

    @property
    def is_playing(self) -> bool:
        return self._playing

    async def hangup(self, reason: str = "completed") -> None:
        if self._closed:
            return
        self._closed = True
        log.info("Beende Anruf %s (%s)", self.info.call_id, reason)
        with contextlib.suppress(ConnectionResetError, BrokenPipeError):
            self._writer.write(encode_frame(FrameKind.HANGUP))
            await self._writer.drain()
        with contextlib.suppress(Exception):
            self._writer.close()
            await self._writer.wait_closed()


CallHandler = Callable[[AudioSocketTransport], Awaitable[None]]


class AudioSocketServer:
    """Nimmt AudioSocket-Verbindungen an und startet pro Anruf einen Handler."""

    def __init__(
        self,
        handler: CallHandler,
        *,
        host: str = "127.0.0.1",
        port: int = 8090,
        max_concurrent_calls: int = 8,
    ) -> None:
        self.handler = handler
        self.host = host
        self.port = port
        self.max_concurrent_calls = max_concurrent_calls
        self._server: asyncio.AbstractServer | None = None
        self._active: set[asyncio.Task] = set()

    @property
    def active_calls(self) -> int:
        return len(self._active)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_connect, self.host, self.port)
        log.info(
            "AudioSocket-Server laeuft auf %s:%s (max. %s parallele Anrufe)",
            self.host,
            self.port,
            self.max_concurrent_calls,
        )

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for task in list(self._active):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)

    async def _on_connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        transport = AudioSocketTransport(reader, writer, info=CallInfo(caller=str(peer)))

        if len(self._active) >= self.max_concurrent_calls:
            # Lieber sauber ablehnen als alle laufenden Gespraeche verzoegern.
            log.warning("Anruf abgewiesen: %s Gespraeche aktiv", len(self._active))
            await transport.hangup("busy")
            return

        task = asyncio.current_task()
        if task is not None:
            self._active.add(task)
        try:
            await self.handler(transport)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Anruf %s abgebrochen", transport.info.call_id)
        finally:
            if task is not None:
                self._active.discard(task)
            await transport.hangup("cleanup")
