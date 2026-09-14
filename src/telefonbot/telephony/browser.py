"""Sprachkanal ueber den Browser.

Derselbe Gespraechsablauf wie am Telefon, nur kommt das Audio nicht von
Asterisk, sondern vom Mikrofon im Browser: 16-bit-PCM, 8 kHz, 20-ms-Bloecke
ueber eine WebSocket-Verbindung. Ausgehende Ansagen gehen denselben Weg zurueck.

Dadurch laesst sich die komplette Kette -- Sprachaktivitaetserkennung, Whisper,
Entscheidungsbaum, Piper -- auf einem Rechner ausprobieren, bevor eine
Telefonanlage angebunden ist.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any, AsyncIterator

from telefonbot.audio.pcm import Samples, bytes_to_samples, samples_to_bytes
from telefonbot.net.websocket import WebSocketConnection
from telefonbot.telephony.base import AudioFrame, CallEnded, CallInfo, DtmfDigit, InboundEvent

log = logging.getLogger(__name__)

SAMPLE_RATE = 8000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000


class BrowserTransport:
    """Telefonkanal ueber eine WebSocket-Verbindung zum Browser."""

    sample_rate = SAMPLE_RATE
    frame_ms = FRAME_MS

    def __init__(self, verbindung: WebSocketConnection, *, info: CallInfo | None = None) -> None:
        self.verbindung = verbindung
        self.info = info or CallInfo(call_id="browser", caller="Mikrofon")
        self._abbrechen = False
        self._laeuft = False
        self._beendet = False

    # ---------------------------------------------------------------- Eingang

    async def events(self) -> AsyncIterator[InboundEvent]:
        """Audio und Steuerbefehle aus dem Browser."""
        while True:
            nachricht = await self.verbindung.recv()
            if nachricht is None:
                yield CallEnded("verbindung_geschlossen")
                return
            if nachricht.is_binary:
                yield AudioFrame(samples=bytes_to_samples(nachricht.data))
                continue
            try:
                befehl = json.loads(nachricht.text)
            except json.JSONDecodeError:
                log.warning("Unlesbarer Steuerbefehl: %r", nachricht.text[:80])
                continue
            art = befehl.get("typ")
            if art == "dtmf" and befehl.get("taste"):
                yield DtmfDigit(digit=str(befehl["taste"])[0])
            elif art == "auflegen":
                yield CallEnded("anrufer_hat_aufgelegt")
                return

    # ---------------------------------------------------------------- Ausgang

    async def send_audio(self, samples: Samples) -> None:
        """Ansage in Echtzeit ausgeben, abbrechbar durch :meth:`stop_audio`.

        Die Taktung ist dieselbe wie bei der Telefonanlage: ohne sie landet die
        ganze Ansage sofort im Puffer des Browsers und Barge-in liefe ins Leere.
        """
        nutzdaten = samples_to_bytes(samples)
        self._laeuft = True
        self._abbrechen = False
        await self._ereignis({"typ": "ansage_beginnt", "dauer_s": round(len(samples) / SAMPLE_RATE, 2)})
        naechster = time.monotonic()
        try:
            for start in range(0, len(nutzdaten), FRAME_BYTES):
                if self._abbrechen or self.verbindung.closed:
                    break
                block = nutzdaten[start : start + FRAME_BYTES]
                if len(block) < FRAME_BYTES:
                    block += bytes(FRAME_BYTES - len(block))
                await self.verbindung.send_bytes(block)
                naechster += FRAME_MS / 1000
                pause = naechster - time.monotonic()
                if pause > 0:
                    await asyncio.sleep(pause)
        finally:
            self._laeuft = False
            await self._ereignis({"typ": "ansage_endet"})

    async def stop_audio(self) -> None:
        """Wiedergabe abbrechen und den Puffer im Browser leeren (Barge-in)."""
        self._abbrechen = True
        await self._ereignis({"typ": "abbrechen"})

    @property
    def is_playing(self) -> bool:
        return self._laeuft

    async def hangup(self, reason: str = "completed") -> None:
        """Meldet das Gespraechsende -- schliesst die Verbindung aber nicht.

        Ueber die Leitung geht nach dem Gespraech noch das Ergebnis an die
        Oberflaeche; wer hier schliesst, wirft genau das weg. Das Schliessen
        uebernimmt der Dienst (:class:`telefonbot.voice.VoiceWebService`).
        """
        if self._beendet:
            return
        self._beendet = True
        await self._ereignis({"typ": "ende", "grund": reason})

    async def schliessen(self) -> None:
        """Verbindung tatsaechlich beenden."""
        with contextlib.suppress(Exception):
            await self.verbindung.close()

    # ------------------------------------------------------- Anzeige im Browser

    async def sende_ereignis(self, ereignis: dict[str, Any]) -> None:
        """Zusatzinformation an die Oberflaeche (Gespraechsverlauf, Zustand)."""
        await self._ereignis(ereignis)

    async def _ereignis(self, ereignis: dict[str, Any]) -> None:
        if self.verbindung.closed:
            return
        with contextlib.suppress(Exception):
            await self.verbindung.send_text(json.dumps(ereignis, ensure_ascii=False))
