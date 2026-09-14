"""Gespraechsablauf: die Engine ohne Audio durchspielen."""

import datetime as dt
import unittest

import yaml

from telefonbot.flow.effects import Collect, Hangup, Invoke, Speak, Transfer
from telefonbot.flow.engine import CallContext, EngineError, FlowEngine, UserInput
from telefonbot.flow.loader import load_flow
from telefonbot.nlu.rules import RuleInterpreter
from tests.fixtures import DEMO_FLOW_YAML

HEUTE = dt.date(2026, 3, 10)


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.flow = load_flow(yaml.safe_load(DEMO_FLOW_YAML))
        self.engine = FlowEngine(
            self.flow,
            RuleInterpreter(today=HEUTE),
            context=CallContext(call_id="t1", caller="+498921800"),
        )

    def say(self, text="", dtmf="", confidence=1.0):
        return self.engine.submit(UserInput(text=text, dtmf=dtmf, confidence=confidence))

    def silence(self):
        return self.engine.submit(UserInput(timed_out=True))


class HappyPathTest(EngineTestCase):
    def test_terminbuchung_komplett(self):
        turn = self.engine.start()
        self.assertIn("Guten Tag", turn.spoken_text())
        self.assertIn("Termin oder um eine Krankmeldung", turn.spoken_text())
        self.assertIsInstance(turn.pending, Collect)

        turn = self.say("ich haette gern einen Termin")
        self.assertEqual(self.engine.slots["anliegen"], "termin")
        self.assertIn("An welchem Tag", turn.spoken_text())

        turn = self.say("am Freitag bitte")
        self.assertEqual(self.engine.slots["datum"], "2026-03-13")
        self.assertIn("2026-03-13", turn.spoken_text())  # Platzhalter gefuellt

        turn = self.say("ja genau")
        self.assertIsInstance(turn.pending, Invoke)
        self.assertEqual(turn.pending.action, "create_appointment")
        self.assertEqual(turn.pending.args, {"datum": "2026-03-13", "anliegen": "termin"})

        turn = self.engine.submit_action_result("V-4711")
        self.assertIsInstance(turn.pending, Hangup)
        self.assertIn("V-4711", turn.spoken_text())
        self.assertTrue(self.engine.finished)
        self.assertEqual(self.engine.finish_reason, "completed")

    def test_dtmf_statt_sprache(self):
        self.engine.start()
        turn = self.say(dtmf="2")
        self.assertEqual(self.engine.slots["anliegen"], "krankmeldung")
        self.assertIn("Matrikelnummer", turn.spoken_text())

        turn = self.say(dtmf="12345678")
        self.assertEqual(self.engine.slots["matrikelnummer"], "12345678")
        self.assertIsInstance(turn.pending, Hangup)

    def test_branch_nutzt_slots(self):
        self.engine.start()
        self.say(dtmf="2")
        turn = self.say("eins zwei drei vier fuenf sechs sieben acht")
        self.assertIn("12345678", turn.spoken_text())


class RepromptTest(EngineTestCase):
    def test_nicht_verstanden_fuehrt_zu_reprompt(self):
        self.engine.start()
        turn = self.say("ich weiss auch nicht so genau")
        self.assertTrue(any(isinstance(e, Speak) and e.is_reprompt for e in turn.effects))
        self.assertIn("Bitte sagen Sie Termin oder Krankmeldung", turn.spoken_text())
        self.assertIsInstance(turn.pending, Collect)
        self.assertEqual(turn.pending.attempt, 2)

    def test_eskalation_nach_zu_vielen_versuchen(self):
        self.engine.start()
        self.say("hmmm")           # Versuch 1
        self.say("keine Ahnung")   # Versuch 2
        turn = self.say("bla bla")  # ueber max_attempts -> Eskalation
        self.assertIsInstance(turn.pending, Transfer)
        self.assertEqual(turn.pending.target, "PJSIP/sekretariat")
        self.assertEqual(self.engine.context.meta["escalation_reason"], "no_match")

    def test_schweigen_zaehlt_getrennt_als_no_input(self):
        self.engine.start()
        turn = self.silence()
        self.assertIsInstance(turn.pending, Collect)
        self.silence()
        turn = self.silence()
        self.assertIsInstance(turn.pending, Transfer)
        self.assertEqual(self.engine.context.meta["escalation_reason"], "no_input")

    def test_zaehler_wird_nach_erfolg_zurueckgesetzt(self):
        self.engine.start()
        self.say("hmmm")
        self.say("Termin")
        self.assertEqual(self.engine.slots["anliegen"], "termin")
        # Am naechsten Knoten stehen wieder volle Versuche zur Verfuegung.
        self.say("bla")
        self.say("blubb")
        turn = self.say("morgen")
        self.assertEqual(self.engine.slots["datum"], "2026-03-11")
        self.assertIn("Ist das richtig", turn.spoken_text())

    def test_niedrige_asr_konfidenz_gilt_als_nicht_verstanden(self):
        self.engine.start()
        turn = self.say("Termin", confidence=0.2)
        self.assertNotIn("anliegen", self.engine.slots)
        self.assertTrue(any(isinstance(e, Speak) and e.is_reprompt for e in turn.effects))


class ConfirmTest(EngineTestCase):
    def test_nein_fuehrt_zurueck_zur_frage(self):
        self.engine.start()
        self.say("Termin")
        self.say("morgen")
        turn = self.say("nein, das stimmt nicht")
        self.assertIn("An welchem Tag", turn.spoken_text())
        turn = self.say("am 14. Maerz")
        self.assertEqual(self.engine.slots["datum"], "2026-03-14")


class GlobalCommandTest(EngineTestCase):
    def test_mitarbeiter_springt_sofort_zur_weiterleitung(self):
        self.engine.start()
        turn = self.say("ich moechte einen Mitarbeiter sprechen")
        self.assertIsInstance(turn.pending, Transfer)
        self.assertEqual(self.engine.context.meta["global_command"], "mensch")

    def test_null_taste_leitet_weiter(self):
        self.engine.start()
        turn = self.say(dtmf="0")
        self.assertIsInstance(turn.pending, Transfer)

    def test_wiederholen_zaehlt_nicht_als_fehlversuch(self):
        self.engine.start()
        for _ in range(5):
            turn = self.say("bitte nochmal")
            self.assertIsInstance(turn.pending, Collect)
        turn = self.say("Termin")
        self.assertIn("An welchem Tag", turn.spoken_text())


class ActionTest(EngineTestCase):
    def test_fehler_der_fachaktion_eskaliert(self):
        self.engine.start()
        self.say("Termin")
        self.say("morgen")
        self.say("ja")
        turn = self.engine.submit_action_result(error="Kalender nicht erreichbar")
        self.assertIsInstance(turn.pending, Transfer)
        self.assertEqual(self.engine.context.meta["last_error"], "Kalender nicht erreichbar")


class ProtocolTest(EngineTestCase):
    def test_eingabe_ohne_offene_frage(self):
        with self.assertRaises(EngineError):
            self.say("hallo")

    def test_doppelter_start(self):
        self.engine.start()
        with self.assertRaises(EngineError):
            self.engine.start()

    def test_zyklus_ohne_interaktion_bricht_ab(self):
        data = yaml.safe_load(DEMO_FLOW_YAML)
        data["nodes"]["a"] = {"type": "branch", "cases": [{"when": [], "next": "b"}], "next": "b"}
        data["nodes"]["b"] = {"type": "branch", "cases": [{"when": [], "next": "a"}], "next": "a"}
        data["nodes"]["begruessung"]["next"] = "a"
        flow = load_flow(data, strict=False)
        engine = FlowEngine(flow, RuleInterpreter(today=HEUTE))
        with self.assertRaises(EngineError):
            engine.start()

    def test_verlauf_wird_protokolliert(self):
        self.engine.start()
        self.say("Termin")
        self.assertEqual(self.engine.history[:3], ["begruessung", "hauptmenue", "termin_datum"])


if __name__ == "__main__":
    unittest.main()
