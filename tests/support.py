"""Hilfen fuer Gespraechstests: ein simulierter Anrufer."""

from __future__ import annotations

import asyncio
from array import array

from telefonbot.audio.pcm import silence, tone
from telefonbot.telephony.fake import FakeTransport

SPEECH_MS = 600
TRAILING_SILENCE_MS = 1000
"""Laenger als ``end_silence_s`` -- erst dadurch gilt der Beitrag als beendet."""


def utterance(sample_rate: int = 8000, *, speech_ms: int = SPEECH_MS) -> array:
    """Audio, das die VAD als einen gesprochenen Beitrag erkennt."""
    out = array("h")
    out.extend(tone(speech_ms, sample_rate, freq=300, amplitude=0.4))
    out.extend(silence(TRAILING_SILENCE_MS, sample_rate))
    return out


def quiet(seconds: float, sample_rate: int = 8000) -> array:
    return silence(int(seconds * 1000), sample_rate)


class ScriptedCaller:
    """Ein Anrufer, der hoeflich abwartet, bis der Bot fertig gesprochen hat.

    Ohne dieses Abwarten wuerde jede Antwort als Barge-in in die laufende
    Ansage fallen; genau dieser Unterschied soll in Tests steuerbar sein.
    """

    def __init__(self, transport: FakeTransport, turns: list[str | tuple[str, str]]):
        self.transport = transport
        self.turns = turns
        self.task: asyncio.Task | None = None

    def start(self) -> asyncio.Task:
        self.task = asyncio.create_task(self._run())
        return self.task

    async def _run(self) -> None:
        for turn in self.turns:
            await self._wait_until_quiet()
            if isinstance(turn, tuple) and turn[0] == "dtmf":
                self.transport.enqueue_dtmf(turn[1])
            elif isinstance(turn, tuple) and turn[0] == "hangup":
                self.transport.enqueue_hangup()
            elif isinstance(turn, tuple) and turn[0] == "silence":
                self.transport.enqueue_audio(quiet(float(turn[1]), self.transport.sample_rate))
            else:
                self.transport.enqueue_audio(utterance(self.transport.sample_rate))

    async def _wait_until_quiet(self, settle: float = 0.02) -> None:
        """Wartet, bis der Bot eine kurze Zeit lang nichts mehr gesendet hat."""
        last = -1
        while True:
            marker = self.transport.sent_count
            if marker == last and not self.transport.sending:
                return
            last = marker
            await asyncio.sleep(settle)
