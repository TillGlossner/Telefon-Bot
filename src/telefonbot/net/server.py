"""Kleiner HTTP-Server, der den Sprachclient ausliefert und auf WebSocket hochstuft.

Ein Prozess, ein Port: die Seite selbst, ihr JavaScript und die Audioverbindung.
Das erspart beim Ausprobieren jede zusaetzliche Infrastruktur -- wichtig, weil
der Browser das Mikrofon nur auf ``localhost`` oder ueber HTTPS freigibt.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Awaitable, Callable

from telefonbot.net.websocket import WebSocketConnection, accept_key

log = logging.getLogger(__name__)

MAX_KOPFZEILEN = 64 * 1024
VerbindungsHandler = Callable[[WebSocketConnection], Awaitable[None]]


class StaticWebSocketServer:
    """Liefert statische Dateien aus und nimmt WebSocket-Verbindungen an."""

    def __init__(
        self,
        handler: VerbindungsHandler,
        *,
        static_dir: str | Path,
        host: str = "127.0.0.1",
        port: int = 8099,
        ws_path: str = "/ws",
        max_connections: int = 4,
    ) -> None:
        self.handler = handler
        self.static_dir = Path(static_dir).resolve()
        self.host = host
        self.port = port
        self.ws_path = ws_path
        self.max_connections = max_connections
        self._server: asyncio.AbstractServer | None = None
        self._aktiv = 0

    @property
    def adresse(self) -> str:
        return f"http://{self.host}:{self.gebundener_port}"

    @property
    def gebundener_port(self) -> int:
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self.port

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._verbindung, self.host, self.port)
        log.info("Sprachclient erreichbar unter %s", self.adresse)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    # ------------------------------------------------------------------ intern

    async def _verbindung(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            kopf = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        if len(kopf) > MAX_KOPFZEILEN:
            await self._antwort(writer, 431, b"Kopfzeilen zu gross")
            return

        zeilen = kopf.decode("latin-1").split("\r\n")
        teile = zeilen[0].split(" ")
        if len(teile) < 2:
            await self._antwort(writer, 400, b"Fehlerhafte Anfrage")
            return
        methode, pfad = teile[0], teile[1].split("?")[0]
        kopfzeilen = {}
        for zeile in zeilen[1:]:
            if ":" in zeile:
                name, _, wert = zeile.partition(":")
                kopfzeilen[name.strip().lower()] = wert.strip()

        if pfad == self.ws_path:
            await self._hochstufen(reader, writer, kopfzeilen)
            return
        if methode != "GET":
            await self._antwort(writer, 405, b"Nur GET")
            return
        await self._datei(writer, pfad)

    async def _hochstufen(self, reader, writer, kopfzeilen: dict[str, str]) -> None:
        schluessel = kopfzeilen.get("sec-websocket-key")
        if "websocket" not in kopfzeilen.get("upgrade", "").lower() or not schluessel:
            await self._antwort(writer, 400, b"WebSocket-Upgrade erwartet")
            return
        if self._aktiv >= self.max_connections:
            await self._antwort(writer, 503, b"Zu viele Verbindungen")
            return

        antwort = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(schluessel)}\r\n\r\n"
        )
        writer.write(antwort.encode("ascii"))
        await writer.drain()

        verbindung = WebSocketConnection(reader, writer)
        verbindung.start()
        self._aktiv += 1
        try:
            await self.handler(verbindung)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Sprachverbindung abgebrochen")
        finally:
            self._aktiv -= 1
            await verbindung.close()

    async def _datei(self, writer: asyncio.StreamWriter, pfad: str) -> None:
        name = "index.html" if pfad in ("/", "") else pfad.lstrip("/")
        ziel = (self.static_dir / name).resolve()
        # Kein Ausbruch aus dem Ausgabeverzeichnis (".." im Pfad).
        if not str(ziel).startswith(str(self.static_dir)) or not ziel.is_file():
            await self._antwort(writer, 404, b"Nicht gefunden")
            return
        typ = mimetypes.guess_type(ziel.name)[0] or "application/octet-stream"
        if typ.startswith("text/") or typ in ("application/javascript", "application/json"):
            typ += "; charset=utf-8"
        await self._antwort(writer, 200, ziel.read_bytes(), typ)

    async def _antwort(
        self, writer: asyncio.StreamWriter, status: int, koerper: bytes, typ: str = "text/plain; charset=utf-8"
    ) -> None:
        texte = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
                 431: "Request Header Fields Too Large", 503: "Service Unavailable"}
        kopf = (
            f"HTTP/1.1 {status} {texte.get(status, 'OK')}\r\n"
            f"Content-Type: {typ}\r\n"
            f"Content-Length: {len(koerper)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        )
        try:
            writer.write(kopf.encode("ascii") + koerper)
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
