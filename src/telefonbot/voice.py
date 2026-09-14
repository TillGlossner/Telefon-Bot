"""Sprachdienst fuer den Browser.

Verbindet den Sprachclient im Browser mit derselben Gespraechsschleife, die am
Telefon laeuft: dieselbe VAD, dieselbe Spracherkennung, derselbe
Entscheidungsbaum, dieselbe Sprachausgabe. Nur der Transportweg ist ein anderer.

Damit ist das hier keine Nachbildung, sondern das echte System mit einem
zweiten Eingang -- brauchbar, um Erkennung, Ansagen und Timing zu beurteilen,
bevor eine Telefonanlage angebunden ist.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path

from telefonbot.config import AppConfig
from telefonbot.net.server import StaticWebSocketServer
from telefonbot.net.websocket import WebSocketConnection
from telefonbot.nlu.rules import RuleInterpreter
from telefonbot.session.call import CallSession
from telefonbot.session.transcript import TranscriptEvent
from telefonbot.telephony.base import CallInfo
from telefonbot.telephony.browser import BrowserTransport

log = logging.getLogger(__name__)

CLIENT_DIR = Path(__file__).resolve().parent / "webclient"


class VoiceWebService:
    """Nimmt Sprachverbindungen aus dem Browser an."""

    def __init__(self, config: AppConfig, *, host: str = "127.0.0.1", port: int = 8099) -> None:
        from telefonbot.app import BotService

        self.bot = BotService(config)
        self.config = config
        self.server = StaticWebSocketServer(
            self.gespraech, static_dir=CLIENT_DIR, host=host, port=port
        )
        self._zaehler = 0

    async def gespraech(self, verbindung: WebSocketConnection) -> None:
        """Ein Gespraech ueber eine Browser-Verbindung."""
        self._zaehler += 1
        kennung = f"web-{self._zaehler:04d}"
        log.info("Sprachverbindung %s von %s", kennung, verbindung.peer)

        transport = BrowserTransport(
            verbindung, info=CallInfo(call_id=kennung, caller="Browser-Mikrofon")
        )
        jetzt = dt.datetime.now()
        session = CallSession(
            self.bot.flow,
            transport,
            self.bot.asr,
            self.bot.tts,
            interpreter=RuleInterpreter(),
            actions=self.bot.actions,
            config=self.bot.call_config,
            transcript_writer=self.bot.transcripts,
            meta=self.bot.sprechzeiten.kontext(jetzt),
        )

        schlange: asyncio.Queue[dict] = asyncio.Queue()
        session.transcript.listener = lambda ereignis: schlange.put_nowait(
            _als_anzeige(ereignis, session)
        )
        pumpe = asyncio.create_task(_pumpe(schlange, transport))

        await transport.sende_ereignis({
            "typ": "bereit",
            "flow": self.bot.flow.id,
            "version": self.bot.flow.version,
            "anruf": kennung,
            "sprechzeit": session.context.meta.get("innerhalb_sprechzeit"),
            "abtastrate": transport.sample_rate,
            "erkenner": type(self.bot.asr).__name__,
            "ausgabe": type(self.bot.tts).__name__,
        })

        self.bot.stats.call_started()
        ergebnis = None
        try:
            ergebnis = await session.run()
        finally:
            self.bot.stats.call_finished(
                kennung,
                ergebnis.reason if ergebnis else "error",
                ergebnis.transfer_target if ergebnis else None,
            )
            await asyncio.sleep(0)   # letzte Anzeige-Ereignisse noch durchlassen
            pumpe.cancel()
        if ergebnis:
            await transport.sende_ereignis({
                "typ": "ergebnis",
                "grund": ergebnis.reason,
                "weiterleitung": ergebnis.transfer_target or "",
                "dauer_s": ergebnis.duration_s,
                "slots": session.transcript.redacted_slots(ergebnis.slots),
            })
        await transport.schliessen()

    async def run(self) -> None:
        """Modelle laden und Server starten."""
        log.info("Lade Modelle -- der erste Start dauert einen Moment ...")
        await self.bot.warmup()
        await self.server.start()
        print(f"\n  Sprachclient: {self.server.adresse}\n")
        try:
            await self.server.serve_forever()
        finally:
            await self.server.stop()


async def _pumpe(schlange: asyncio.Queue, transport: BrowserTransport) -> None:
    """Anzeige-Ereignisse aus dem Gespraech an den Browser weiterreichen."""
    while True:
        ereignis = await schlange.get()
        await transport.sende_ereignis(ereignis)


def _als_anzeige(ereignis: TranscriptEvent, session: CallSession) -> dict:
    """Transkript-Ereignis in eine Anzeige-Nachricht uebersetzen."""
    knoten = session.engine.current_node
    return {
        "typ": ereignis.kind,
        "text": ereignis.text,
        "knoten": ereignis.node_id,
        "daten": ereignis.data,
        "zustand": {
            "knoten": knoten.id if knoten else "",
            "knotentyp": knoten.kind.value if knoten else "",
            "slots": session.transcript.redacted_slots(session.context.slots),
            "sprechzeit": session.context.meta.get("innerhalb_sprechzeit", ""),
        },
    }
