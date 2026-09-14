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


class WebSocketTestClient:
    """Minimaler WebSocket-Client fuer Tests -- spricht mit dem Sprachdienst.

    Client-Rahmen muessen laut RFC maskiert sein; genau das prueft dieser
    Client auf der Serverseite mit.
    """

    def __init__(self, reader, writer):
        from telefonbot.net.websocket import FrameReader

        self._reader = reader
        self._writer = writer
        self._frames = FrameReader()
        self._offen: list = []

    @classmethod
    async def verbinde(cls, host: str, port: int, pfad: str = "/ws"):
        import base64
        import os

        reader, writer = await asyncio.open_connection(host, port)
        schluessel = base64.b64encode(os.urandom(16)).decode("ascii")
        writer.write(
            f"GET {pfad} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {schluessel}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n".encode("ascii")
        )
        await writer.drain()
        kopf = await reader.readuntil(b"\r\n\r\n")
        if b"101" not in kopf.split(b"\r\n")[0]:
            raise AssertionError(f"Kein Upgrade: {kopf!r}")
        return cls(reader, writer)

    async def sende_bytes(self, daten: bytes) -> None:
        from telefonbot.net.websocket import OpCode, encode_frame

        self._writer.write(encode_frame(OpCode.BINAER, daten, mask=True))
        await self._writer.drain()

    async def sende_json(self, objekt) -> None:
        import json

        from telefonbot.net.websocket import OpCode, encode_frame

        self._writer.write(
            encode_frame(OpCode.TEXT, json.dumps(objekt).encode("utf-8"), mask=True)
        )
        await self._writer.drain()

    async def empfange(self, timeout: float = 5.0):
        """Naechste Nachricht (Text oder binaer); ``None`` bei Verbindungsende.

        Steuerrahmen (Schliessen, Ping, Pong) sind keine Nutzdaten: ein
        Schliessen-Rahmen beendet den Strom, alles andere wird uebersprungen.
        """
        from telefonbot.net.websocket import OpCode

        while True:
            while self._offen:
                nachricht = self._offen.pop(0)
                if nachricht.opcode is OpCode.SCHLIESSEN:
                    return None
                if nachricht.opcode in (OpCode.PING, OpCode.PONG):
                    continue
                return nachricht
            daten = await asyncio.wait_for(self._reader.read(8192), timeout=timeout)
            if not daten:
                return None
            self._offen.extend(self._frames.feed(daten))

    async def empfange_json(self, typ: str | None = None, timeout: float = 5.0):
        """Wartet auf ein Steuerereignis, optional auf einen bestimmten Typ."""
        import json

        ende = asyncio.get_running_loop().time() + timeout
        while True:
            rest = ende - asyncio.get_running_loop().time()
            if rest <= 0:
                raise asyncio.TimeoutError(f"Ereignis '{typ}' kam nicht")
            nachricht = await self.empfange(timeout=rest)
            if nachricht is None:
                return None
            if nachricht.is_binary:
                continue
            ereignis = json.loads(nachricht.text)
            if typ is None or ereignis.get("typ") == typ:
                return ereignis

    async def sende_aeusserung(self, sample_rate: int = 8000) -> None:
        """Spricht einen Beitrag: Ton, dann Stille, damit die VAD das Ende erkennt."""
        from telefonbot.audio.pcm import samples_to_bytes

        audio = utterance(sample_rate)
        groesse = int(sample_rate * 0.02)
        roh = samples_to_bytes(audio)
        for start in range(0, len(roh), groesse * 2):
            await self.sende_bytes(roh[start : start + groesse * 2])

    async def warte_bis_ruhe(self, stille_s: float = 0.25, timeout: float = 10.0):
        """Wartet, bis der Bot zu Ende gesprochen hat.

        Ohne dieses Warten faellt jede Antwort als Barge-in in die laufende
        Ansage -- fuer den geradlinigen Testfall unerwuenscht.
        """
        import json

        gesammelt = []
        ende = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < ende:
            try:
                nachricht = await self.empfange(timeout=stille_s)
            except asyncio.TimeoutError:
                return gesammelt
            if nachricht is None:
                return gesammelt
            if not nachricht.is_binary:
                gesammelt.append(json.loads(nachricht.text))
        return gesammelt

    async def schliesse(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass
