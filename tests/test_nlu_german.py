"""Parser fuer deutsche Telefonantworten."""

import datetime as dt
import unittest

from telefonbot.nlu import german


class NormalizeTest(unittest.TestCase):
    def test_umlaute_und_satzzeichen(self):
        self.assertEqual(german.normalize("Grüß Gott, Herr Müller!"), "gruess gott herr mueller")

    def test_leerraum(self):
        self.assertEqual(german.normalize("  ja   \n genau "), "ja genau")


class YesNoTest(unittest.TestCase):
    def test_ja_varianten(self):
        for text in ("ja", "Ja genau", "korrekt", "passt so", "jawohl", "okay"):
            self.assertTrue(german.parse_yes_no(text), text)

    def test_nein_varianten(self):
        for text in ("nein", "nee", "falsch", "negativ", "auf keinen Fall nein"):
            self.assertFalse(german.parse_yes_no(text), text)

    def test_negation_schlaegt_ja(self):
        # "stimmt nicht" enthaelt "stimmt" -- darf trotzdem nicht Ja werden.
        self.assertFalse(german.parse_yes_no("das stimmt nicht"))
        self.assertFalse(german.parse_yes_no("nicht richtig"))

    def test_unverstanden(self):
        self.assertIsNone(german.parse_yes_no("Moment mal"))
        self.assertIsNone(german.parse_yes_no(""))


class NumberTest(unittest.TestCase):
    def test_ziffern(self):
        self.assertEqual(german.parse_number("ich haette gern 3 Stueck"), 3.0)

    def test_zahlwoerter(self):
        self.assertEqual(german.parse_number("sieben"), 7.0)
        self.assertEqual(german.parse_number("einundzwanzig"), 21.0)
        self.assertEqual(german.parse_number("dreissig"), 30.0)

    def test_dezimal_mit_komma(self):
        self.assertEqual(german.parse_number("zwei komma fuenf"), 2.0)
        self.assertEqual(german.parse_number("2,5"), 2.5)

    def test_keine_zahl(self):
        self.assertIsNone(german.parse_number("keine Ahnung"))


class DigitsTest(unittest.TestCase):
    def test_gesprochene_ziffern(self):
        self.assertEqual(german.parse_digits("eins zwei drei vier"), "1234")

    def test_ziffernblock(self):
        self.assertEqual(german.parse_digits("12345678"), "12345678")

    def test_laengenpruefung(self):
        self.assertEqual(german.parse_digits("1 2 3", length=3), "123")
        self.assertIsNone(german.parse_digits("1 2 3", length=8))


class DateTest(unittest.TestCase):
    TODAY = dt.date(2026, 3, 10)  # ein Dienstag

    def parse(self, text):
        return german.parse_date(text, today=self.TODAY)

    def test_relative(self):
        self.assertEqual(self.parse("heute"), "2026-03-10")
        self.assertEqual(self.parse("morgen bitte"), "2026-03-11")
        self.assertEqual(self.parse("uebermorgen"), "2026-03-12")

    def test_numerisch(self):
        self.assertEqual(self.parse("am 14.3."), "2026-03-14")
        self.assertEqual(self.parse("14.03.2027"), "2027-03-14")

    def test_monatsname(self):
        self.assertEqual(self.parse("am 14. März"), "2026-03-14")

    def test_wochentag_naechstes_vorkommen(self):
        self.assertEqual(self.parse("am Freitag"), "2026-03-13")
        # Heute ist Dienstag -- "Dienstag" meint den naechsten, nicht heute.
        self.assertEqual(self.parse("Dienstag"), "2026-03-17")

    def test_vergangenes_datum_rutscht_ins_folgejahr(self):
        self.assertEqual(self.parse("am 5.1."), "2027-01-05")

    def test_unsinniges_datum(self):
        self.assertIsNone(self.parse("am 31.2."))
        self.assertIsNone(self.parse("weiss nicht"))


class TimeTest(unittest.TestCase):
    def test_formate(self):
        self.assertEqual(german.parse_time("14:30"), "14:30")
        self.assertEqual(german.parse_time("14 Uhr 30"), "14:30")
        self.assertEqual(german.parse_time("neun Uhr"), "09:00")

    def test_umgangssprache(self):
        self.assertEqual(german.parse_time("halb drei"), "02:30")
        self.assertEqual(german.parse_time("viertel nach drei"), "03:15")
        self.assertEqual(german.parse_time("dreiviertel vier"), "03:45")

    def test_tageszeit_verschiebt(self):
        self.assertEqual(german.parse_time("drei Uhr nachmittags"), "15:00")
        self.assertEqual(german.parse_time("halb drei nachmittags"), "14:30")

    def test_ungueltig(self):
        self.assertIsNone(german.parse_time("25 Uhr 99"))
        self.assertIsNone(german.parse_time("irgendwann"))


if __name__ == "__main__":
    unittest.main()
