"""Regel-Interpreter: Zuordnung von Aeusserungen auf erwartete Werte."""

import datetime as dt
import unittest

from telefonbot.flow.engine import UserInput
from telefonbot.flow.model import ExpectKind, ExpectSpec, GlobalCommand
from telefonbot.nlu.rules import RuleInterpreter

CHOICE = ExpectSpec(
    kind=ExpectKind.CHOICE,
    options={
        "termin": ["termin", "sprechstunde", "beratungstermin"],
        "krankmeldung": ["krankmeldung", "krank melden"],
        "pruefungsamt": ["pruefungsamt", "pruefung"],
    },
    dtmf={"1": "termin", "2": "krankmeldung", "3": "pruefungsamt"},
)


class ChoiceTest(unittest.TestCase):
    def setUp(self):
        self.nlu = RuleInterpreter(today=dt.date(2026, 3, 10))

    def interpret(self, text="", dtmf=""):
        return self.nlu.interpret(CHOICE, UserInput(text=text, dtmf=dtmf))

    def test_direktes_schluesselwort(self):
        result = self.interpret("ich brauche einen Termin")
        self.assertEqual(result.value, "termin")
        self.assertEqual(result.confidence, 1.0)

    def test_synonym_mit_mehreren_woertern(self):
        self.assertEqual(self.interpret("ich moechte mich krank melden").value, "krankmeldung")

    def test_synonym_wird_auf_zielwert_abgebildet(self):
        self.assertEqual(self.interpret("Sprechstunde").value, "termin")
        self.assertEqual(self.interpret("Prüfungsamt").value, "pruefungsamt")

    def test_tippfehler_der_spracherkennung(self):
        # Whisper verhoert sich am Telefon regelmaessig um ein, zwei Buchstaben.
        self.assertEqual(self.interpret("Terminn").value, "termin")
        self.assertEqual(self.interpret("Krankmeldug").value, "krankmeldung")

    def test_unverstanden_bleibt_leer(self):
        self.assertIsNone(self.interpret("ich wollte nur mal fragen").value)

    def test_dtmf_hat_vorrang(self):
        self.assertEqual(self.interpret(text="Termin", dtmf="3").value, "pruefungsamt")

    def test_unbekannte_taste_faellt_auf_text_zurueck(self):
        self.assertEqual(self.interpret(text="Termin", dtmf="9").value, "termin")


class YesNoTest(unittest.TestCase):
    def setUp(self):
        self.nlu = RuleInterpreter()
        self.spec = ExpectSpec(kind=ExpectKind.YES_NO)

    def test_ja_nein(self):
        self.assertEqual(self.nlu.interpret(self.spec, UserInput(text="ja")).value, "yes")
        self.assertEqual(self.nlu.interpret(self.spec, UserInput(text="nein")).value, "no")

    def test_tasten_eins_und_zwei(self):
        self.assertEqual(self.nlu.interpret(self.spec, UserInput(dtmf="1")).value, "yes")
        self.assertEqual(self.nlu.interpret(self.spec, UserInput(dtmf="2")).value, "no")


class NumberAndDigitsTest(unittest.TestCase):
    def setUp(self):
        self.nlu = RuleInterpreter()

    def test_zahl_im_erlaubten_bereich(self):
        spec = ExpectSpec(kind=ExpectKind.NUMBER, min_value=1, max_value=10)
        self.assertEqual(self.nlu.interpret(spec, UserInput(text="sieben")).value, 7)
        self.assertIsNone(self.nlu.interpret(spec, UserInput(text="dreissig")).value)

    def test_ziffernfolge_mit_laenge(self):
        spec = ExpectSpec(kind=ExpectKind.DIGITS, length=8)
        self.assertEqual(self.nlu.interpret(spec, UserInput(text="1 2 3 4 5 6 7 8")).value, "12345678")
        self.assertIsNone(self.nlu.interpret(spec, UserInput(text="1 2 3")).value)

    def test_dtmf_laenge_wird_geprueft(self):
        spec = ExpectSpec(kind=ExpectKind.DIGITS, length=8)
        self.assertIsNone(self.nlu.interpret(spec, UserInput(dtmf="123")).value)


class DateTimeTest(unittest.TestCase):
    def setUp(self):
        self.nlu = RuleInterpreter(today=dt.date(2026, 3, 10))

    def test_datum(self):
        spec = ExpectSpec(kind=ExpectKind.DATE)
        self.assertEqual(self.nlu.interpret(spec, UserInput(text="morgen")).value, "2026-03-11")

    def test_uhrzeit(self):
        spec = ExpectSpec(kind=ExpectKind.TIME)
        self.assertEqual(self.nlu.interpret(spec, UserInput(text="halb zehn")).value, "09:30")


class GlobalCommandTest(unittest.TestCase):
    def setUp(self):
        self.nlu = RuleInterpreter()
        self.commands = [
            GlobalCommand(name="mensch", phrases=["mitarbeiter", "echten menschen"], action="goto", target="x", dtmf="0"),
            GlobalCommand(name="wiederholen", phrases=["wiederholen"], action="repeat"),
        ]

    def test_phrase(self):
        found = self.nlu.match_global(self.commands, UserInput(text="geben Sie mir einen Mitarbeiter"))
        self.assertEqual(found.name, "mensch")

    def test_mehrwortphrase(self):
        found = self.nlu.match_global(self.commands, UserInput(text="ich will einen echten Menschen sprechen"))
        self.assertEqual(found.name, "mensch")

    def test_taste(self):
        self.assertEqual(self.nlu.match_global(self.commands, UserInput(dtmf="0")).name, "mensch")

    def test_kein_treffer(self):
        self.assertIsNone(self.nlu.match_global(self.commands, UserInput(text="einen Termin bitte")))

    def test_teilwort_loest_nicht_aus(self):
        # "Mitarbeiterin" ist ein anderes Wort als das Kommando "mitarbeiter";
        # Einzelwortphrasen matchen nur auf ganzen Woertern.
        self.assertIsNone(self.nlu.match_global(self.commands, UserInput(text="Frau Mueller ist Mitarbeiterin")))


if __name__ == "__main__":
    unittest.main()
