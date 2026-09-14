"""Sprachaktivitaetserkennung und Turn-Taking.

Zwei Dinge entscheiden darueber, ob sich ein Telefonbot natuerlich anfuehlt:
wann er merkt, dass der Anrufer fertig ist, und ob man ihm ins Wort fallen darf
(Barge-in). Beides haengt an der VAD.

Standard ist hier eine energiebasierte VAD mit mitlaufendem Grundrauschpegel --
robust genug fuer Telefonie (schmalbandig, 8 kHz) und ohne Modell. Wo mehr
Genauigkeit noetig ist, laesst sich Silero-VAD ueber dieselbe Schnittstelle
einhaengen (:class:`SileroVAD`, benoetigt onnxruntime).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from telefonbot.audio.pcm import Samples, dbfs

log = logging.getLogger(__name__)


class VAD(Protocol):
    """Entscheidet pro Block, ob Sprache vorliegt."""

    def is_speech(self, frame: Samples) -> bool: ...
    def reset(self) -> None: ...


class EnergyVAD:
    """Energiebasierte VAD mit adaptivem Grundrauschpegel.

    Der Rauschpegel wird waehrend Stille langsam nachgefuehrt; als Sprache gilt,
    was ``margin_db`` darueber liegt. So funktioniert die Erkennung auch bei
    rauschenden Leitungen, ohne feste Schwelle pro Anschluss.
    """

    def __init__(
        self,
        *,
        margin_db: float = 12.0,
        floor_db: float = -55.0,
        adapt_rate: float = 0.05,
    ) -> None:
        self.margin_db = margin_db
        self.floor_db = floor_db
        self.adapt_rate = adapt_rate
        self._noise_db = floor_db

    @property
    def noise_db(self) -> float:
        return self._noise_db

    def is_speech(self, frame: Samples) -> bool:
        level = dbfs(frame)
        threshold = max(self._noise_db + self.margin_db, self.floor_db + self.margin_db)
        speech = level > threshold
        if not speech:
            # Nur in Sprechpausen nachfuehren, sonst "lernt" die VAD die Stimme.
            self._noise_db += self.adapt_rate * (level - self._noise_db)
            self._noise_db = max(self._noise_db, -90.0)
        return speech

    def reset(self) -> None:
        self._noise_db = self.floor_db


class SegmentEvent(str, Enum):
    """Ereignisse des Turn-Taking."""

    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    NO_INPUT = "no_input"
    MAX_DURATION = "max_duration"


@dataclass
class SegmenterConfig:
    """Zeiten des Turn-Taking, alle in Sekunden."""

    frame_ms: int = 20
    start_speech_s: float = 0.12
    """So lange muss Sprache anliegen, bevor ein Beitrag beginnt (Knackser-Schutz)."""
    end_silence_s: float = 0.8
    """So lange Stille beendet den Beitrag des Anrufers."""
    no_input_s: float = 6.0
    max_utterance_s: float = 30.0


class SpeechSegmenter:
    """Schneidet aus einem Blockstrom die Aeusserung des Anrufers heraus.

    Rein zustandsbasiert und ohne Zeitmessung: der Fortschritt ergibt sich aus
    der Anzahl der Bloecke. Dadurch laesst sich Turn-Taking in Tests exakt
    durchspielen statt mit ``sleep``.
    """

    def __init__(self, vad: VAD, config: SegmenterConfig | None = None) -> None:
        self.vad = vad
        self.config = config or SegmenterConfig()
        self.reset()

    def reset(self) -> None:
        self._speech_frames = 0
        self._silence_frames = 0
        self._total_frames = 0
        self._in_speech = False
        self._finished = False
        self.buffer: list[Samples] = []
        self.vad.reset()

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def finished(self) -> bool:
        """Ein Beitrag wurde erkannt und wartet auf :meth:`take_audio`."""
        return self._finished

    def _n(self, seconds: float) -> int:
        return max(1, int(seconds * 1000 / self.config.frame_ms))

    def push(self, frame: Samples) -> SegmentEvent | None:
        """Naechsten Block einspeisen; liefert ein Ereignis, wenn eines eintritt.

        Nach einem abgeschlossenen Beitrag werden weitere Bloecke ignoriert, bis
        :meth:`reset` aufgerufen wird -- sonst wuerde die nachlaufende Stille den
        Puffer leeren, den der Aufrufer gerade abholen will.
        """
        if self._finished:
            return None
        self._total_frames += 1
        speech = self.vad.is_speech(frame)

        if self._in_speech:
            self.buffer.append(frame)
            if speech:
                self._silence_frames = 0
            else:
                self._silence_frames += 1
                if self._silence_frames >= self._n(self.config.end_silence_s):
                    self._in_speech = False
                    self._finished = True
                    return SegmentEvent.SPEECH_END
            if len(self.buffer) >= self._n(self.config.max_utterance_s):
                self._in_speech = False
                self._finished = True
                return SegmentEvent.MAX_DURATION
            return None

        if speech:
            self._speech_frames += 1
            self.buffer.append(frame)
            if self._speech_frames >= self._n(self.config.start_speech_s):
                self._in_speech = True
                self._silence_frames = 0
                return SegmentEvent.SPEECH_START
            return None

        # Stille vor dem Beitrag: angesammelte Einzelblocker verwerfen.
        self._speech_frames = 0
        self.buffer.clear()
        if self._total_frames >= self._n(self.config.no_input_s):
            return SegmentEvent.NO_INPUT
        return None

    def take_audio(self) -> Samples:
        """Gibt die gesammelte Aeusserung zurueck und leert den Puffer."""
        from array import array

        out = array("h")
        for frame in self.buffer:
            out.extend(frame)
        self.buffer.clear()
        return out


class SileroVAD:
    """Optionale, genauere VAD auf Basis von Silero (ONNX).

    Wird erst beim ersten Aufruf geladen; ohne ``onnxruntime`` faellt der Bot
    auf :class:`EnergyVAD` zurueck.
    """

    def __init__(self, model_path: str, *, sample_rate: int = 16000, threshold: float = 0.5):
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._session = None
        self._state = None

    def _ensure_loaded(self):
        if self._session is None:
            import numpy as np  # noqa: F401  (nur mit Extra "vad" installiert)
            import onnxruntime

            self._session = onnxruntime.InferenceSession(
                self.model_path, providers=["CPUExecutionProvider"]
            )
            self.reset()
        return self._session

    def is_speech(self, frame: Samples) -> bool:
        import numpy as np

        session = self._ensure_loaded()
        audio = np.array(frame, dtype=np.float32).reshape(1, -1) / 32768.0
        outputs = session.run(
            None,
            {
                "input": audio,
                "state": self._state,
                "sr": np.array(self.sample_rate, dtype=np.int64),
            },
        )
        probability, self._state = float(outputs[0][0][0]), outputs[1]
        return probability >= self.threshold

    def reset(self) -> None:
        if self._session is not None:
            import numpy as np

            self._state = np.zeros((2, 1, 128), dtype=np.float32)
