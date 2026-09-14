"""Sprechzeiten und ihre Wirkung im Entscheidungsbaum."""

import datetime as dt
import unittest
from pathlib import Path

from telefonbot.config import load_config
from telefonbot.flow.loader import load_flow_file
from telefonbot.session.sprechzeiten import Sprechzeiten
from telefonbot.telephony.simulator import simulate

FLOW = Path(__file__).resolve().parent.parent / "config" / "flows" / "lehrstuhl_sekretariat.yaml"

STANDARD = {
    "montag": ["09:00-12:00", "14:00-16:00"],
    "dienstag": ["09:00-12:00", "14:00-16:00"],
    "freitag": ["09:00-12:00"],
}


class SprechzeitenTest(unittest.TestCase):
    def setUp(self):
        self.sz = Sprechzeiten.aus_konfiguration(STANDARD, ["2026-12-24"])

    def test_innerhalb_und_ausserhalb(self):
        self.assertTrue(self.sz.ist_offen(dt.datetime(2026, 9, 14, 10, 0)))    # Montag vormittags
        self.assertFalse(self.sz.ist_offen(dt.datetime(2026, 9, 14, 13, 0)))   # Mittagspause
        self.assertTrue(self.sz.ist_offen(dt.datetime(2026, 9, 14, 15, 59)))
        self.assertFalse(self.sz.ist_offen(dt.datetime(2026, 9, 14, 16, 0)))   # Ende ist exklusiv
        self.assertFalse(self.sz.ist_offen(dt.datetime(2026, 9, 16, 10, 0)))   # Mittwoch nicht gepflegt

    def test_feiertag_schliesst(self):
        self.assertFalse(self.sz.ist_offen(dt.datetime(2026, 12, 24, 10, 0)))

    def test_ohne_konfiguration_immer_offen(self):
        leer = Sprechzeiten.aus_konfiguration({})
        self.assertTrue(leer.ist_offen(dt.datetime(2026, 9, 13, 3, 0)))  # Sonntagnacht
        self.assertIsNone(leer.naechste_oeffnung(dt.datetime(2026, 9, 13, 3, 0)))

    def test_naechste_oeffnung(self):
        naechste = self.sz.naechste_oeffnung(dt.datetime(2026, 9, 14, 17, 0))  # Montagabend
        self.assertEqual(naechste, dt.datetime(2026, 9, 15, 9, 0))             # Dienstag frueh

    def test_naechste_oeffnung_ueberspringt_geschlossene_tage(self):
        naechste = self.sz.naechste_oeffnung(dt.datetime(2026, 9, 15, 17, 0))  # Dienstagabend
        self.assertEqual(naechste, dt.datetime(2026, 9, 18, 9, 0))             # erst Freitag

    def test_kontextvariablen(self):
        kontext = self.sz.kontext(dt.datetime(2026, 9, 14, 17, 0))
        self.assertEqual(kontext["innerhalb_sprechzeit"], "nein")
        self.assertEqual(kontext["wochentag"], "montag")
        self.assertEqual(kontext["jetzt_uhrzeit"], "17:00")
        self.assertEqual(kontext["naechste_sprechzeit"], "morgen um 9 Uhr")

    def test_unlesbare_angaben_werden_verworfen_nicht_geworfen(self):
        sz = Sprechzeiten.aus_konfiguration(
            {"montag": ["9 bis 12", "14:00-16:00"], "mondtag": ["09:00-10:00"]}, ["kein datum"]
        )
        self.assertEqual([str(s) for s in sz.tage["montag"]], ["14:00-16:00"])
        self.assertNotIn("mondtag", sz.tage)
        self.assertEqual(sz.geschlossen_an, set())

    def test_endezeit_vor_beginn_wird_verworfen(self):
        sz = Sprechzeiten.aus_konfiguration({"montag": ["16:00-09:00"]})
        self.assertFalse(sz.definiert)


class FlowMitSprechzeitenTest(unittest.TestCase):
    """Der Beispielbaum muss sich je nach Uhrzeit anders verhalten."""

    def setUp(self):
        self.flow = load_flow_file(FLOW)
        self.sz = Sprechzeiten.aus_konfiguration(STANDARD)

    def spiele(self, wann, eingaben):
        return simulate(self.flow, eingaben, meta=self.sz.kontext(wann), today=wann.date())

    def test_innerhalb_wird_verbunden(self):
        result = self.spiele(dt.datetime(2026, 9, 14, 10, 0), ["Mitarbeiter bitte"])
        self.assertEqual(result.reason, "transferred")
        self.assertEqual(result.transfer_target, "PJSIP/sekretariat@uni-pbx")

    def test_ausserhalb_wird_ein_rueckruf_aufgenommen(self):
        result = self.spiele(
            dt.datetime(2026, 9, 14, 19, 30),
            ["Mitarbeiter bitte", "Maria Huber", "089 2180 1234", "nein"],
        )
        self.assertEqual(result.reason, "completed")
        self.assertIsNone(result.transfer_target)
        self.assertEqual(result.slots["name"], "Maria Huber")
        self.assertEqual(result.slots["rueckrufnummer"], "08921801234")

    def test_ausserhalb_wird_der_hinweis_angesagt(self):
        result = self.spiele(dt.datetime(2026, 9, 14, 19, 30), ["Termin"])
        ansagen = " ".join(text for step in result.steps for text in step.bot)
        self.assertIn("nicht besetzt", ansagen)
        self.assertIn("morgen um 9 Uhr", ansagen)

    def test_innerhalb_ohne_zusatzhinweis(self):
        result = self.spiele(dt.datetime(2026, 9, 14, 10, 0), ["Termin"])
        ansagen = " ".join(text for step in result.steps for text in step.bot)
        self.assertNotIn("nicht besetzt", ansagen)

    def test_termin_laeuft_zu_jeder_uhrzeit_durch(self):
        result = self.spiele(
            dt.datetime(2026, 9, 14, 22, 0),
            ["Termin", "morgen", "zehn Uhr", "Till Glossner", "ja"],
        )
        self.assertEqual(result.reason, "completed")
        self.assertEqual(result.slots["datum"], "2026-09-15")
        self.assertEqual(result.slots["uhrzeit"], "10:00")


class KonfigurationTest(unittest.TestCase):
    def test_beispielkonfiguration_enthaelt_sprechzeiten(self):
        config = load_config(Path(__file__).resolve().parent.parent / "config" / "config.example.yaml", env={})
        self.assertIn("montag", config.sprechzeiten.tage)
        sz = Sprechzeiten.aus_konfiguration(config.sprechzeiten.tage, config.sprechzeiten.geschlossen_an)
        self.assertTrue(sz.definiert)
        self.assertFalse(sz.ist_offen(dt.datetime(2026, 12, 24, 10, 0)))


if __name__ == "__main__":
    unittest.main()
