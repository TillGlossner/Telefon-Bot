"""Ansagen-Cache.

Ein Entscheidungsbaum sagt immer wieder dieselben Saetze. Die einmal
synthetisierte Ansage als WAV vorzuhalten spart pro Anruf mehrere hundert
Millisekunden -- der spuerbarste Latenzgewinn im ganzen System.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from telefonbot.audio.pcm import read_wav, write_wav
from telefonbot.tts.base import Speech, TTS

log = logging.getLogger(__name__)


class CachingTTS:
    """Legt synthetisierte Ansagen als WAV ab und liefert sie beim naechsten Mal aus."""

    def __init__(self, inner: TTS, cache_dir: str | Path = "var/tts-cache") -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.hits = 0
        self.misses = 0

    @property
    def sample_rate(self) -> int:
        return self.inner.sample_rate

    def _path(self, text: str) -> Path:
        digest = hashlib.sha256(
            f"{text}|{self.sample_rate}|{type(self.inner).__name__}".encode("utf-8")
        ).hexdigest()[:32]
        return self.cache_dir / f"{digest}.wav"

    async def synthesize(self, text: str) -> Speech:
        path = self._path(text)
        if path.exists():
            try:
                samples, rate = read_wav(path)
                self.hits += 1
                return Speech(samples=samples, sample_rate=rate)
            except (OSError, ValueError):
                log.warning("Cache-Datei %s unlesbar, synthetisiere neu", path)

        speech = await self.inner.synthesize(text)
        self.misses += 1
        try:
            write_wav(path, speech.samples, speech.sample_rate)
        except OSError as exc:  # Cache ist Beiwerk, kein Grund das Gespraech zu kippen
            log.warning("Cache nicht schreibbar (%s)", exc)
        return speech

    async def warmup(self, texts: list[str] | None = None) -> None:
        """Modell laden und optional feste Ansagen vorsynthetisieren."""
        await self.inner.warmup()
        for text in texts or []:
            await self.synthesize(text)
