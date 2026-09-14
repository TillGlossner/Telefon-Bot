"""Kleine HTTP-Schnittstelle fuer Status, Kennzahlen und Weiterleitungen.

Absichtlich mit der Standardbibliothek und absichtlich nur auf ``127.0.0.1``:
die Schnittstelle hat keine Authentisierung und ist fuer den Dialplan von
Asterisk und fuer die Ueberwachung auf demselben Host gedacht.

Der Endpunkt ``/calls/<uuid>/outcome`` loest ein konkretes Problem: ueber
AudioSocket kann der Bot ein Gespraech nicht selbst weiterverbinden. Er
hinterlegt das Ziel hier, und der Dialplan holt es sich nach Gespraechsende ab
(siehe ``deploy/asterisk/extensions.conf``).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from telefonbot import __version__

log = logging.getLogger(__name__)


@dataclass
class Stats:
    """Laufende Kennzahlen des Dienstes."""

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    calls_total: int = 0
    calls_active: int = 0
    reasons: Counter = field(default_factory=Counter)
    transfers: int = 0
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_outcomes: int = 500
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def call_started(self) -> None:
        with self._lock:
            self.calls_total += 1
            self.calls_active += 1

    def call_finished(self, call_id: str, reason: str, transfer_target: str | None) -> None:
        with self._lock:
            self.calls_active = max(0, self.calls_active - 1)
            self.reasons[reason] += 1
            if transfer_target:
                self.transfers += 1
            self.outcomes[call_id] = {
                "reason": reason,
                "transfer_target": transfer_target or "",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            while len(self.outcomes) > self.max_outcomes:
                self.outcomes.pop(next(iter(self.outcomes)))

    def outcome(self, call_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self.outcomes.get(call_id)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()
            return {
                "version": __version__,
                "uptime_s": round(uptime, 1),
                "calls_total": self.calls_total,
                "calls_active": self.calls_active,
                "transfers": self.transfers,
                "reasons": dict(self.reasons),
            }

    def prometheus(self) -> str:
        data = self.snapshot()
        lines = [
            "# HELP telefonbot_calls_total Angenommene Anrufe seit Start",
            "# TYPE telefonbot_calls_total counter",
            f"telefonbot_calls_total {data['calls_total']}",
            "# HELP telefonbot_calls_active Aktuell laufende Gespraeche",
            "# TYPE telefonbot_calls_active gauge",
            f"telefonbot_calls_active {data['calls_active']}",
            "# HELP telefonbot_transfers_total Weiterleitungen an Menschen",
            "# TYPE telefonbot_transfers_total counter",
            f"telefonbot_transfers_total {data['transfers']}",
            "# HELP telefonbot_call_end_total Gespraechsenden nach Grund",
            "# TYPE telefonbot_call_end_total counter",
        ]
        for reason, count in data["reasons"].items():
            lines.append(f'telefonbot_call_end_total{{reason="{reason}"}} {count}')
        return "\n".join(lines) + "\n"


class _Handler(BaseHTTPRequestHandler):
    server_version = f"telefonbot/{__version__}"
    stats: Stats
    info: dict[str, Any]

    def do_GET(self) -> None:  # noqa: N802  (Vorgabe der Basisklasse)
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path in ("/", "/health"):
            return self._json({"status": "ok", **self.stats.snapshot(), **self.info})
        if path == "/metrics":
            return self._text(self.stats.prometheus(), content_type="text/plain; version=0.0.4")
        if path.startswith("/calls/") and path.endswith("/outcome"):
            call_id = path[len("/calls/") : -len("/outcome")]
            outcome = self.stats.outcome(call_id)
            if outcome is None:
                return self._json({"error": "unbekannter Anruf"}, status=404)
            return self._json(outcome)
        if path.startswith("/calls/") and path.endswith("/transfer"):
            # Nur das Ziel als reiner Text -- so kann der Dialplan es direkt lesen.
            call_id = path[len("/calls/") : -len("/transfer")]
            outcome = self.stats.outcome(call_id) or {}
            return self._text(outcome.get("transfer_target", ""))
        self._json({"error": "nicht gefunden", "pfad": path}, status=404)

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("control %s", format % args)

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._text(json.dumps(payload, ensure_ascii=False), status=status, content_type="application/json")

    def _text(self, body: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ControlServer:
    """Startet die Statusschnittstelle in einem Hintergrundthread."""

    def __init__(
        self,
        stats: Stats,
        *,
        host: str = "127.0.0.1",
        port: int = 8091,
        info: dict[str, Any] | None = None,
    ) -> None:
        handler = type("_BoundHandler", (_Handler,), {"stats": stats, "info": info or {}})
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="control")
        self._thread.start()
        log.info("Control-API auf http://%s:%s", *self._server.server_address[:2])

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
