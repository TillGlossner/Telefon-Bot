"""Spracherkennung fuer Tests: liefert vorgegebene Texte."""

from __future__ import annotations

from telefonbot.asr.base import Transcript
from telefonbot.audio.pcm import Samples, duration_s


class ScriptedASR:
    """Gibt der Reihe nach die vorbereiteten Aeusserungen zurueck."""

    sample_rate = 16000

    def __init__(self, utterances: list[str | Transcript] | None = None) -> None:
        self.queue: list[str | Transcript] = list(utterances or [])
        self.calls: list[float] = []

    def add(self, utterance: str | Transcript) -> None:
        self.queue.append(utterance)

    async def transcribe(self, samples: Samples, sample_rate: int) -> Transcript:
        self.calls.append(duration_s(samples, sample_rate))
        if not self.queue:
            return Transcript(text="", confidence=0.0)
        item = self.queue.pop(0)
        if isinstance(item, Transcript):
            return item
        return Transcript(text=item, confidence=0.95, duration_s=duration_s(samples, sample_rate))

    async def warmup(self) -> None:
        return None
