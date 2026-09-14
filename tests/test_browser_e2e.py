"""Der echte Browser gegen den echten Sprachdienst.

Chromium bringt ein simuliertes Mikrofon mit (``--use-file-for-fake-audio-capture``).
Damit laesst sich die Kette pruefen, die sonst blind bleibt: Mikrofonaufnahme,
AudioWorklet, Herunterrechnen auf 8 kHz, WebSocket-Rahmen, Sprachpausen-
Erkennung, Entscheidungsbaum, Rueckweg als Audio.

Nur Spracherkennung und -ausgabe sind Attrappen -- alles dazwischen ist das
Produktivsystem. Ohne Chromium wird der Test uebersprungen.
"""

from __future__ import annotations

import asyncio
import glob
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from telefonbot.asr.fake import ScriptedASR
from telefonbot.config import AppConfig
from telefonbot.tts.fake import FakeTTS
from telefonbot.voice import VoiceWebService

WURZEL = Path(__file__).resolve().parent.parent
GESPRAECHSDAUER_S = 22


def finde_chromium() -> str | None:
    """Sucht einen Browser -- Umgebungsvariable, Playwright-Ablage oder PATH."""
    if os.environ.get("CHROMIUM"):
        return os.environ["CHROMIUM"]
    basis = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    for muster in (f"{basis}/chromium-*/chrome-linux/chrome", f"{basis}/chromium/chrome-linux/chrome"):
        treffer = sorted(glob.glob(muster))
        if treffer:
            return treffer[-1]
    for name in ("chromium", "chromium-browser", "google-chrome"):
        pfad = shutil.which(name)
        if pfad:
            return pfad
    return None


def schreibe_testsignal(pfad: Path, *, rate: int = 48000) -> None:
    """Sprachaehnliches Signal: Tonbuendel mit Pausen, damit die VAD Beitraege schneidet."""
    werte: list[int] = []
    for _ in range(6):
        for i in range(int(rate * 1.2)):
            t = i / rate
            wert = (
                0.35 * math.sin(2 * math.pi * 220 * t)
                + 0.20 * math.sin(2 * math.pi * 440 * t)
                + 0.10 * math.sin(2 * math.pi * 900 * t)
            )
            werte.append(int(max(-1.0, min(1.0, wert)) * 32767))
        werte.extend([0] * int(rate * 1.6))
    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(rate)
        datei.writeframes(b"".join(struct.pack("<h", wert) for wert in werte))


@unittest.skipIf(finde_chromium() is None, "Kein Chromium gefunden")
class BrowserGespraechTest(unittest.IsolatedAsyncioTestCase):
    async def test_gespraech_ueber_das_browser_mikrofon(self):
        browser_pfad = finde_chromium()
        with tempfile.TemporaryDirectory() as tmp:
            arbeit = Path(tmp)
            schreibe_testsignal(arbeit / "mikro.wav")

            config = AppConfig()
            config.flow = str(WURZEL / "config" / "flows" / "lehrstuhl_sekretariat.yaml")
            config.asr.engine = "fake"
            config.tts.engine = "fake"
            config.tts.cache_enabled = False
            config.control.enabled = False
            config.transcripts.directory = str(arbeit / "transkripte")
            config.session.greeting_delay_s = 0.0

            dienst = VoiceWebService(config, host="127.0.0.1", port=0)
            dienst.bot.asr = ScriptedASR(
                ["Termin bitte", "morgen", "zehn Uhr", "Till Glossner", "ja"]
            )
            dienst.bot.tts = FakeTTS(sample_rate=8000, ms_per_char=1)
            await dienst.server.start()

            browser = subprocess.Popen(
                [
                    browser_pfad, "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--autoplay-policy=no-user-gesture-required",
                    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-audio-capture={arbeit / 'mikro.wav'}",
                    f"--user-data-dir={arbeit / 'profil'}",
                    f"http://127.0.0.1:{dienst.server.gebundener_port}/?auto=1",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                await asyncio.sleep(GESPRAECHSDAUER_S)
            finally:
                browser.terminate()
                try:
                    browser.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    browser.kill()
                await dienst.server.stop()

            self.assertEqual(dienst.bot.stats.calls_total, 1, "Der Browser muss angerufen haben")
            self.assertEqual(dict(dienst.bot.stats.reasons), {"completed": 1})

            zeilen = list((arbeit / "transkripte").glob("*.jsonl"))
            self.assertTrue(zeilen, "Es muss ein Transkript entstanden sein")
            protokoll = json.loads(zeilen[0].read_text(encoding="utf-8").splitlines()[0])

            slots = protokoll["slots"]
            self.assertEqual(slots["anliegen"], "termin")
            self.assertEqual(slots["uhrzeit"], "10:00")
            self.assertEqual(slots["name"], "***", "Name ist sensibel und darf nicht im Klartext stehen")

            knoten = [e["knoten"] for e in protokoll["ereignisse"] if e["typ"] == "user"]
            self.assertEqual(
                knoten,
                ["hauptmenue", "termin_datum", "termin_uhrzeit", "termin_name", "termin_bestaetigen"],
                "Jede erkannte Aeusserung muss am richtigen Knoten angekommen sein",
            )


if __name__ == "__main__":
    unittest.main()
