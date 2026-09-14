"""Transport fuer Tests: ein Anruf ohne Telefonanlage.

Der Transport spielt vorbereitete Audioabschnitte ein und sammelt alles, was
der Bot ausgibt. Damit laesst sich der komplette Ablauf inklusive Barge-in
deterministisch testen -- ohne Asterisk, ohne Modelle, in Millisekunden.
"""

from __future__ import annotations

import asyncio
from array import array
from typing import AsyncIterator

from telefonbot.audio.pcm import Samples
from telefonbot.telephony.base import AudioFrame, CallEnded, CallInfo, DtmfDigit, InboundEvent


class FakeTransport:
    """In-Memory-Transport mit steuerbarem Ereignisstrom."""

    def __init__(
        self,
        script: list[InboundEvent] | None = None,
        *,
        sample_rate: int = 8000,
        frame_ms: int = 20,
        info: CallInfo | None = None,
        playback_steps: int = 4,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.info = info or CallInfo(call_id="fake")
        self.playback_steps = playback_steps
        """So oft gibt die Wiedergabe die Kontrolle ab -- ersetzt Echtzeit im Test."""
        self._queue: asyncio.Queue[InboundEvent] = asyncio.Queue()
        for event in script or []:
            self._queue.put_nowait(event)
        self.sent: list[Samples] = []
        self.sending = False
        self.hangup_reason: str | None = None
        self.stopped_playback = 0
        self._cancel_playback = False

    @property
    def frame_size(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000)

    # ------------------------------------------------------------ Steuerung

    def enqueue(self, event: InboundEvent) -> None:
        self._queue.put_nowait(event)

    def enqueue_audio(self, samples: Samples) -> None:
        """Legt Audio blockweise in den Ereignisstrom."""
        size = self.frame_size
        for start in range(0, len(samples), size):
            chunk = samples[start : start + size]
            if len(chunk) < size:
                chunk = array("h", chunk) + array("h", bytes(2 * (size - len(chunk))))
            self._queue.put_nowait(AudioFrame(samples=chunk))

    def enqueue_dtmf(self, digits: str) -> None:
        for digit in digits:
            self._queue.put_nowait(DtmfDigit(digit=digit))

    def enqueue_hangup(self, reason: str = "remote_hangup") -> None:
        self._queue.put_nowait(CallEnded(reason))

    # ------------------------------------------------------------ Transport

    async def events(self) -> AsyncIterator[InboundEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if isinstance(event, CallEnded):
                return

    async def send_audio(self, samples: Samples) -> None:
        self.sent.append(samples)
        self.sending = True
        self._cancel_playback = False
        try:
            for _ in range(self.playback_steps):
                if self._cancel_playback:
                    break
                await asyncio.sleep(0)
        finally:
            self.sending = False

    async def stop_audio(self) -> None:
        self.stopped_playback += 1
        self._cancel_playback = True

    async def hangup(self, reason: str = "completed") -> None:
        if self.hangup_reason is None:
            self.hangup_reason = reason

    # ------------------------------------------------------------- Auswertung

    @property
    def sent_count(self) -> int:
        return len(self.sent)

    @property
    def sent_samples(self) -> int:
        return sum(len(chunk) for chunk in self.sent)
