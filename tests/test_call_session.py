"""Vollstaendige Telefonate -- mit Fake-Telefonie, Fake-ASR und Fake-TTS."""

import asyncio
import datetime as dt
import unittest

import yaml

from telefonbot.asr.fake import ScriptedASR
from telefonbot.flow.loader import load_flow
from telefonbot.nlu.rules import RuleInterpreter
from telefonbot.session.actions import ActionRegistry
from telefonbot.session.call import CallConfig, CallSession
from telefonbot.telephony.base import CallInfo
from telefonbot.telephony.fake import FakeTransport
from telefonbot.tts.fake import FakeTTS
from tests.fixtures import DEMO_FLOW_YAML
from tests.support import ScriptedCaller, quiet, utterance

HEUTE = dt.date(2026, 3, 10)


async def appointment_action(args, context):
    return "V-4711"


def build_session(utterances, *, transport=None, actions=None, config=None, timeout_s=None):
    data = yaml.safe_load(DEMO_FLOW_YAML)
    if timeout_s is not None:
        # Kurze Zeitgrenzen halten Zeitablauf-Tests schnell, ohne den Pfad zu aendern.
        data["settings"]["timeout_s"] = timeout_s
    flow = load_flow(data)
    transport = transport or FakeTransport(info=CallInfo(call_id="test-1", caller="+4989210"))
    registry = actions or ActionRegistry()
    if "create_appointment" not in registry:
        registry.register("create_appointment", appointment_action)
    session = CallSession(
        flow,
        transport,
        ScriptedASR(utterances),
        FakeTTS(),
        interpreter=RuleInterpreter(today=HEUTE),
        actions=registry,
        config=config or CallConfig(greeting_delay_s=0.0),
    )
    return session, transport


class HappyPathTest(unittest.IsolatedAsyncioTestCase):
    async def test_terminbuchung_per_sprache(self):
        session, transport = build_session(["einen Termin bitte", "am Freitag", "ja genau"])
        caller = ScriptedCaller(transport, ["termin", "freitag", "ja"])
        caller.start()

        result = await asyncio.wait_for(session.run(), timeout=10)

        self.assertEqual(result.reason, "completed")
        self.assertEqual(result.slots["anliegen"], "termin")
        self.assertEqual(result.slots["datum"], "2026-03-13")
        self.assertEqual(result.slots["ticket_id"], "V-4711")
        self.assertEqual(transport.hangup_reason, "completed")

        gesprochen = " ".join(t for k, t in result.transcript.dialogue() if k == "bot")
        self.assertIn("Guten Tag", gesprochen)
        self.assertIn("V-4711", gesprochen)

    async def test_transkript_haelt_beide_seiten_fest(self):
        session, transport = build_session(["einen Termin bitte", "morgen", "ja"])
        ScriptedCaller(transport, ["termin", "morgen", "ja"]).start()
        result = await asyncio.wait_for(session.run(), timeout=10)

        rollen = [k for k, _ in result.transcript.dialogue()]
        self.assertEqual(rollen[:4], ["bot", "bot", "user", "bot"])

    async def test_sensible_slots_werden_maskiert(self):
        session, transport = build_session(["Krankmeldung", "eins zwei drei vier fuenf sechs sieben acht"])
        ScriptedCaller(transport, ["krank", "matrikel"]).start()
        result = await asyncio.wait_for(session.run(), timeout=10)

        self.assertEqual(result.slots["matrikelnummer"], "12345678")
        exportiert = result.transcript.to_dict(slots=result.slots)
        self.assertEqual(exportiert["slots"]["matrikelnummer"], "***")
        self.assertEqual(exportiert["slots"]["anliegen"], "krankmeldung")


class DtmfTest(unittest.IsolatedAsyncioTestCase):
    async def test_auswahl_per_taste(self):
        session, transport = build_session([])
        ScriptedCaller(transport, [("dtmf", "2"), ("dtmf", "12345678")]).start()
        result = await asyncio.wait_for(session.run(), timeout=10)

        self.assertEqual(result.slots["anliegen"], "krankmeldung")
        self.assertEqual(result.slots["matrikelnummer"], "12345678")

    async def test_zu_kurze_nummer_wird_nicht_uebernommen(self):
        # Die Raute beendet die Eingabe sofort; 123 ist keine achtstellige
        # Matrikelnummer und darf deshalb nicht im Slot landen.
        session, transport = build_session([], timeout_s=0.4)
        ScriptedCaller(transport, [("dtmf", "2"), ("dtmf", "123#")]).start()
        result = await asyncio.wait_for(session.run(), timeout=20)

        self.assertEqual(result.slots["anliegen"], "krankmeldung")
        self.assertNotIn("matrikelnummer", result.slots)
        self.assertEqual(result.reason, "transferred")


class BargeInTest(unittest.IsolatedAsyncioTestCase):
    async def test_anrufer_faellt_der_ansage_ins_wort(self):
        transport = FakeTransport(playback_steps=40)
        session, transport = build_session(["einen Termin bitte"], transport=transport)
        # Der Anrufer redet sofort los, ohne die Begruessung abzuwarten.
        transport.enqueue_audio(utterance())
        transport.enqueue_hangup()

        result = await asyncio.wait_for(session.run(), timeout=10)

        self.assertGreaterEqual(transport.stopped_playback, 1)
        self.assertEqual(result.slots.get("anliegen"), "termin")
        self.assertEqual(result.reason, "caller_hangup")

    async def test_ohne_barge_in_wird_ansage_zu_ende_gesprochen(self):
        transport = FakeTransport(playback_steps=40)
        session, transport = build_session(
            ["einen Termin bitte"], transport=transport, config=CallConfig(greeting_delay_s=0.0, barge_in=False)
        )
        transport.enqueue_audio(utterance())
        transport.enqueue_hangup()

        await asyncio.wait_for(session.run(), timeout=10)
        self.assertEqual(transport.stopped_playback, 0)


class TimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_schweigen_fuehrt_ueber_nachfragen_zur_weiterleitung(self):
        session, transport = build_session([])  # Stille kommt als Audio, nicht als Zeitablauf
        # Dreimal nur Stille: zwei Nachfragen, dann Weiterleitung ans Sekretariat.
        for _ in range(3):
            transport.enqueue_audio(quiet(6.0))
        result = await asyncio.wait_for(session.run(), timeout=15)

        self.assertEqual(result.reason, "transferred")
        self.assertEqual(result.transfer_target, "PJSIP/sekretariat")
        self.assertTrue(result.transferred)

    async def test_stiller_kanal_laeuft_in_den_zeitablauf(self):
        # Manche Anlagen senden bei Stille gar keine Pakete -- der Timeout muss
        # trotzdem greifen, sonst haengt das Gespraech.
        session, transport = build_session([], timeout_s=0.4)
        result = await asyncio.wait_for(session.run(), timeout=20)
        self.assertEqual(result.reason, "transferred")


class HangupTest(unittest.IsolatedAsyncioTestCase):
    async def test_auflegen_beendet_das_gespraech(self):
        session, transport = build_session([])
        transport.enqueue_hangup()
        result = await asyncio.wait_for(session.run(), timeout=10)

        self.assertEqual(result.reason, "caller_hangup")
        self.assertEqual(transport.hangup_reason, "caller_hangup")


class ActionFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_fehler_im_fachsystem_leitet_weiter(self):
        async def failing(args, context):
            raise RuntimeError("Kalender offline")

        registry = ActionRegistry()
        registry.register("create_appointment", failing)
        session, transport = build_session(["Termin", "morgen", "ja"], actions=registry)
        ScriptedCaller(transport, ["termin", "morgen", "ja"]).start()

        result = await asyncio.wait_for(session.run(), timeout=10)
        self.assertEqual(result.reason, "transferred")
        self.assertIn("Kalender offline", session.context.meta["last_error"])


if __name__ == "__main__":
    unittest.main()
