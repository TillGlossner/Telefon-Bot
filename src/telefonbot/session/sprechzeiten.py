"""Sprechzeiten.

Ein Sekretariatsbot muss wissen, ob gerade jemand da ist. Ausserhalb der
Sprechzeit ist "Ich verbinde Sie" eine Luege -- dann ist ein Rueckruf die
richtige Antwort. Der Dialogbaum entscheidet das selbst ueber die
Kontextvariable ``innerhalb_sprechzeit``.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

WOCHENTAGE = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
_SPANNE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


@dataclass(frozen=True)
class Zeitspanne:
    von: dt.time
    bis: dt.time

    def enthaelt(self, zeit: dt.time) -> bool:
        return self.von <= zeit < self.bis

    def __str__(self) -> str:
        return f"{self.von:%H:%M}-{self.bis:%H:%M}"


@dataclass
class Sprechzeiten:
    """Oeffnungszeiten je Wochentag plus Ausnahmetage (Feiertage, Schliesszeiten)."""

    tage: dict[str, list[Zeitspanne]] = field(default_factory=dict)
    geschlossen_an: set[dt.date] = field(default_factory=set)

    @classmethod
    def aus_konfiguration(
        cls, tage: dict[str, list[str]] | None, geschlossen: list[str] | None = None
    ) -> "Sprechzeiten":
        """Baut die Sprechzeiten aus der Konfiguration; unlesbare Angaben werden gemeldet."""
        gebaut: dict[str, list[Zeitspanne]] = {}
        for tag, spannen in (tage or {}).items():
            name = str(tag).strip().lower()
            if name not in WOCHENTAGE:
                log.warning("Sprechzeiten: unbekannter Wochentag '%s' ignoriert", tag)
                continue
            gebaut[name] = [s for s in (_spanne(v) for v in spannen or []) if s is not None]

        feiertage: set[dt.date] = set()
        for eintrag in geschlossen or []:
            try:
                feiertage.add(dt.date.fromisoformat(str(eintrag)))
            except ValueError:
                log.warning("Sprechzeiten: '%s' ist kein Datum (YYYY-MM-DD)", eintrag)
        return cls(tage=gebaut, geschlossen_an=feiertage)

    @property
    def definiert(self) -> bool:
        return any(self.tage.values())

    def ist_offen(self, zeitpunkt: dt.datetime) -> bool:
        """Ist gerade jemand erreichbar?

        Ohne konfigurierte Sprechzeiten gilt der Betrieb als durchgehend offen --
        sonst wuerde eine vergessene Konfiguration jeden Anruf umleiten.
        """
        if not self.definiert:
            return True
        if zeitpunkt.date() in self.geschlossen_an:
            return False
        name = WOCHENTAGE[zeitpunkt.weekday()]
        return any(spanne.enthaelt(zeitpunkt.time()) for spanne in self.tage.get(name, []))

    def naechste_oeffnung(self, zeitpunkt: dt.datetime, *, max_tage: int = 14) -> dt.datetime | None:
        """Wann ist wieder geoeffnet? Fuer Ansagen wie 'ab morgen um neun Uhr'."""
        if not self.definiert:
            return None
        for versatz in range(max_tage + 1):
            tag = zeitpunkt.date() + dt.timedelta(days=versatz)
            if tag in self.geschlossen_an:
                continue
            for spanne in sorted(self.tage.get(WOCHENTAGE[tag.weekday()], []), key=lambda s: s.von):
                kandidat = dt.datetime.combine(tag, spanne.von, tzinfo=zeitpunkt.tzinfo)
                if kandidat > zeitpunkt:
                    return kandidat
        return None

    def kontext(self, zeitpunkt: dt.datetime) -> dict[str, str]:
        """Kontextvariablen fuer den Dialogbaum."""
        offen = self.ist_offen(zeitpunkt)
        naechste = self.naechste_oeffnung(zeitpunkt)
        return {
            "jetzt_datum": zeitpunkt.date().isoformat(),
            "jetzt_uhrzeit": f"{zeitpunkt:%H:%M}",
            "wochentag": WOCHENTAGE[zeitpunkt.weekday()],
            "innerhalb_sprechzeit": "ja" if offen else "nein",
            "naechste_sprechzeit": _in_worten(naechste, zeitpunkt) if naechste else "",
        }


def _spanne(rohwert: str) -> Zeitspanne | None:
    treffer = _SPANNE.match(str(rohwert))
    if not treffer:
        log.warning("Sprechzeiten: '%s' ist keine Zeitspanne (Format 09:00-12:00)", rohwert)
        return None
    von = dt.time(int(treffer.group(1)), int(treffer.group(2)))
    bis = dt.time(int(treffer.group(3)), int(treffer.group(4)))
    if bis <= von:
        log.warning("Sprechzeiten: '%s' endet nicht nach dem Beginn", rohwert)
        return None
    return Zeitspanne(von=von, bis=bis)


def _in_worten(zeitpunkt: dt.datetime, jetzt: dt.datetime) -> str:
    """'heute um 14 Uhr', 'morgen um 9 Uhr', 'am Dienstag um 9 Uhr'."""
    stunde = f"{zeitpunkt.hour} Uhr" + (f" {zeitpunkt.minute}" if zeitpunkt.minute else "")
    tage = (zeitpunkt.date() - jetzt.date()).days
    if tage == 0:
        return f"heute um {stunde}"
    if tage == 1:
        return f"morgen um {stunde}"
    return f"am {WOCHENTAGE[zeitpunkt.weekday()].capitalize()} um {stunde}"
