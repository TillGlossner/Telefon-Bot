"""Sprachinterface: WebSocket-Protokoll, Dateiauslieferung und ein echtes Gespräch."""

import asyncio
import json
import unittest
from pathlib import Path

from telefonbot.asr.fake import ScriptedASR
from telefonbot.config import AppConfig
from telefonbot.net.websocket import (
    FrameReader,
    OpCode,
    WebSocketError,
    accept_key,
    encode_frame,
)
from telefonbot.tts.fake import FakeTTS
from telefonbot.voice import CLIENT_DIR, VoiceWebService
from tests.support import WebSocketTestClient

WURZEL = Path(__file__).resolve().parent.parent


class RahmenTest(unittest.TestCase):
    def test_handshake_nach_rfc6455(self):
        # Beispiel aus dem Standard, Abschnitt 1.3
        self.assertEqual(accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_text_hin_und_zurueck(self):
        nachrichten = FrameReader().feed(encode_frame(OpCode.TEXT, "Grüß Gott".encode("utf-8")))
        self.assertEqual(nachrichten[0].text, "Grüß Gott")

    def test_maskierte_clientrahmen(self):
        roh = encode_frame(OpCode.BINAER, bytes(range(256)), mask=True)
        self.assertTrue(roh[1] & 0x80, "Maskenbit muss gesetzt sein")
        nachricht = FrameReader().feed(roh)[0]
        self.assertEqual(nachricht.data, bytes(range(256)))

    def test_zerstueckelter_strom(self):
        daten = encode_frame(OpCode.TEXT, b"eins") + encode_frame(OpCode.BINAER, b"zwei")
        leser = FrameReader()
        nachrichten = []
        for index in range(len(daten)):
            nachrichten.extend(leser.feed(daten[index : index + 1]))
        self.assertEqual([n.data for n in nachrichten], [b"eins", b"zwei"])
        self.assertEqual(leser.pending_bytes, 0)

    def test_laengenformate(self):
        for groesse in (125, 126, 65535, 65536):
            nachricht = FrameReader().feed(encode_frame(OpCode.BINAER, b"x" * groesse))[0]
            self.assertEqual(len(nachricht.data), groesse)

    def test_fragmentierte_nachricht(self):
        teil1 = bytes([0x01, 0x03]) + b"abc"        # TEXT, FIN nicht gesetzt
        teil2 = bytes([0x80, 0x03]) + b"def"        # Fortsetzung mit FIN
        nachrichten = FrameReader().feed(teil1 + teil2)
        self.assertEqual(len(nachrichten), 1)
        self.assertEqual(nachrichten[0].text, "abcdef")

    def test_fortsetzung_ohne_anfang(self):
        with self.assertRaises(WebSocketError):
            FrameReader().feed(bytes([0x80, 0x01]) + b"x")

    def test_unvollstaendiger_rahmen_wartet(self):
        leser = FrameReader()
        self.assertEqual(leser.feed(encode_frame(OpCode.TEXT, b"hallo")[:4]), [])
        self.assertGreater(leser.pending_bytes, 0)

    def test_zu_grosse_nutzdaten(self):
        with self.assertRaises(WebSocketError):
            encode_frame(OpCode.BINAER, b"x" * (5 * 1024 * 1024))


def baue_dienst(aeusserungen):
    """Sprachdienst mit echtem Ablauf, aber Attrappen für Erkennung und Ausgabe."""
    config = AppConfig()
    config.flow = str(WURZEL / "config" / "flows" / "lehrstuhl_sekretariat.yaml")
    config.asr.engine = "fake"
    config.tts.engine = "fake"
    config.tts.cache_enabled = False
    config.control.enabled = False
    config.transcripts.enabled = False
    config.session.greeting_delay_s = 0.0
    dienst = VoiceWebService(config, host="127.0.0.1", port=0)
    dienst.bot.asr = ScriptedASR(list(aeusserungen))
    dienst.bot.tts = FakeTTS(sample_rate=8000, ms_per_char=1)  # kurze Ansagen, schnelle Tests
    return dienst


class DateiauslieferungTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dienst = baue_dienst([])
        await self.dienst.server.start()
        self.port = self.dienst.server.gebundener_port

    async def asyncTearDown(self):
        await self.dienst.server.stop()

    async def hole(self, pfad):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(f"GET {pfad} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        await writer.drain()
        antwort = await asyncio.wait_for(reader.read(65536), timeout=5)
        writer.close()
        return antwort

    async def test_startseite(self):
        antwort = await self.hole("/")
        self.assertIn(b"200 OK", antwort)
        self.assertIn("Sprechprobe".encode("utf-8"), antwort)

    async def test_javascript_wird_ausgeliefert(self):
        antwort = await self.hole("/client.js")
        self.assertIn(b"200 OK", antwort)
        self.assertIn(b"javascript", antwort)   # text/javascript ist der aktuelle Typ
        self.assertIn(b"charset=utf-8", antwort)

    async def test_unbekannte_datei(self):
        self.assertIn(b"404", await self.hole("/gibtsnicht.js"))

    async def test_kein_ausbruch_aus_dem_verzeichnis(self):
        # Ein Pfad mit ".." darf keine Systemdatei ausliefern.
        antwort = await self.hole("/../../../../etc/passwd")
        self.assertIn(b"404", antwort)
        self.assertNotIn(b"root:", antwort)

    async def test_client_dateien_sind_vorhanden(self):
        for name in ("index.html", "client.js", "aufnahme.js"):
            self.assertTrue((CLIENT_DIR / name).is_file(), name)


class GespraechUeberWebsocketTest(unittest.IsolatedAsyncioTestCase):
    """Ein vollständiges Gespräch über eine echte WebSocket-Verbindung."""

    async def starte(self, aeusserungen):
        self.dienst = baue_dienst(aeusserungen)
        await self.dienst.server.start()
        self.client = await WebSocketTestClient.verbinde(
            "127.0.0.1", self.dienst.server.gebundener_port
        )
        return await self.client.empfange_json("bereit")

    async def asyncTearDown(self):
        if hasattr(self, "client"):
            await self.client.schliesse()
        if hasattr(self, "dienst"):
            await self.dienst.server.stop()

    async def test_begruessung_kommt_als_audio_und_text(self):
        bereit = await self.starte([])
        self.assertEqual(bereit["flow"], "lehrstuhl_sekretariat")
        self.assertEqual(bereit["abtastrate"], 8000)
        self.assertEqual(bereit["erkenner"], "ScriptedASR")

        ereignisse = await self.client.warte_bis_ruhe()
        gesprochen = [e for e in ereignisse if e["typ"] == "bot"]
        self.assertTrue(gesprochen, "Der Bot muss sich melden")
        self.assertIn("Guten Tag", gesprochen[0]["text"])
        self.assertEqual(gesprochen[0]["knoten"], "begruessung")

    async def test_gesprochene_antwort_fuehrt_durch_den_baum(self):
        await self.starte(["ich hätte gern einen Termin", "morgen", "zehn Uhr", "Till Glossner", "ja"])
        await self.client.warte_bis_ruhe()

        for _ in range(5):
            await self.client.sende_aeusserung()
            ereignisse = await self.client.warte_bis_ruhe(timeout=15)
            if any(e["typ"] == "ergebnis" for e in ereignisse):
                break

        ergebnis = [e for e in ereignisse if e["typ"] == "ergebnis"]
        self.assertTrue(ergebnis, "Das Gespräch muss zu einem Ergebnis kommen")
        slots = ergebnis[0]["slots"]
        self.assertEqual(slots["anliegen"], "termin")
        self.assertEqual(slots["uhrzeit"], "10:00")
        self.assertEqual(ergebnis[0]["grund"], "completed")

    async def test_sensible_daten_werden_maskiert_uebertragen(self):
        await self.starte(["Rückruf bitte", "Maria Huber", "089 2180 1234", "nein"])
        await self.client.warte_bis_ruhe()
        alle = []
        for _ in range(4):
            await self.client.sende_aeusserung()
            alle.extend(await self.client.warte_bis_ruhe(timeout=15))

        zustaende = [e["zustand"] for e in alle if e.get("zustand", {}).get("slots")]
        self.assertTrue(zustaende)
        letzter = zustaende[-1]["slots"]
        self.assertEqual(letzter.get("name"), "***", "Name ist als sensibel deklariert")
        # Der Rohwert darf die Verbindung nicht verlassen.
        self.assertNotIn("Maria Huber", json.dumps(alle, ensure_ascii=False))

    async def test_tastendruck_wird_verarbeitet(self):
        await self.starte([])
        await self.client.warte_bis_ruhe()
        await self.client.sende_json({"typ": "dtmf", "taste": "1"})
        ereignisse = await self.client.warte_bis_ruhe(timeout=10)

        knoten = [e["zustand"]["knoten"] for e in ereignisse if e.get("zustand")]
        self.assertIn("termin_datum", knoten, "Taste 1 führt zur Terminfrage")

    async def test_auflegen_beendet_das_gespraech(self):
        await self.starte([])
        await self.client.warte_bis_ruhe()
        await self.client.sende_json({"typ": "auflegen"})
        ereignisse = await self.client.warte_bis_ruhe(timeout=10)
        gruende = [e.get("grund") for e in ereignisse if e["typ"] in ("ende", "ergebnis")]
        self.assertIn("caller_hangup", gruende)

    async def test_barge_in_bricht_die_ansage_ab(self):
        await self.starte(["Termin"])
        # Sofort losreden, ohne die Begrüßung abzuwarten.
        await self.client.sende_aeusserung()
        ereignisse = await self.client.warte_bis_ruhe(timeout=15)
        arten = [e["typ"] for e in ereignisse]
        self.assertIn("abbrechen", arten, "Der Server muss die Wiedergabe abbrechen")


if __name__ == "__main__":
    unittest.main()
