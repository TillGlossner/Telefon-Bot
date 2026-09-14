"""Schnittstelle zur Sprachsynthese."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from telefonbot.audio.pcm import Samples, duration_s


@dataclass(frozen=True)
class Speech:
    """Synthetisierte Ansage."""

    samples: Samples
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return duration_s(self.samples, self.sample_rate)


class TTS(Protocol):
    """Was eine Sprachausgabe koennen muss."""

    sample_rate: int

    async def synthesize(self, text: str) -> Speech: ...

    async def warmup(self) -> None: ...
