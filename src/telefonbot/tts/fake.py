"""Sprachausgabe fuer Tests: Ton statt Stimme, protokolliert die Texte."""

from __future__ import annotations

from telefonbot.audio.pcm import tone
from telefonbot.tts.base import Speech


class FakeTTS:
    """Erzeugt Audio proportional zur Textlaenge und merkt sich alle Ansagen."""

    def __init__(self, *, sample_rate: int = 8000, ms_per_char: int = 20) -> None:
        self.sample_rate = sample_rate
        self.ms_per_char = ms_per_char
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> Speech:
        self.spoken.append(text)
        duration = max(self.ms_per_char, len(text) * self.ms_per_char)
        return Speech(samples=tone(duration, self.sample_rate, freq=220), sample_rate=self.sample_rate)

    async def warmup(self) -> None:
        return None
