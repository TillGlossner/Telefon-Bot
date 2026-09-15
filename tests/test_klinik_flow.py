"""Der Klinik-Baum und die Zusagen, die er einhalten muss.

Diese Tests prüfen nicht, ob der Dialog funktioniert -- das tun die anderen --
sondern ob die *Sicherheitseigenschaften* halten: Notfälle führen sofort
hinaus, ärztliche Anrufer werden nicht abgefragt, es wird nie nach Beschwerden
gefragt, und der Bot vergibt keine Termine. Wer den Baum ändert und eine dieser
Zusagen bricht, soll hier auffallen.
"""

import datetime as dt
import unittest
from pathlib import Path

from telefonbot.flow.loader import load_flow_file
from telefonbot.flow.model import ExpectKind, NodeKind
from telefonbot.session.sprechzeiten import Sprechzeiten
from telefonbot.telephony.simulator import simulate

FLOW_PFAD = Path(__file__).resolve().parent.parent / "config" / "flows" / "klinik_sekretariat.yaml"

SPRECHZEITEN = Sprechzeiten.aus_konfiguration({
    "montag": ["08:00-12:00", "13:00-16:00"],
    "dienstag": ["08:00-12:00", "13:00-16:00"],
    "mittwoch": ["08:00-12:00"],
    "donnerstag": ["08:00-12:00", "13:00-16:00"],
    "freitag": ["08:00-12:00"],
})
WERKTAG = dt.datetime(2026, 9, 15, 10, 0)    # Dienstag vormittags
ABENDS = dt.datetime(2026, 9, 15, 18, 30)


class KlinikFlowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = load_flow_file(FLOW_PFAD)

    def spiele(self, eingaben, wann=WERKTAG):
        return simulate(
            self.flow,
            eingaben,
            meta=SPRECHZEITEN.kontext(wann),
            today=wann.date(),
            action_results={"create_ticket": "V-2026-0815"},
        )

    def ansagen(self, ergebnis):
        return " ".join(text for schritt in ergebnis.steps for text in schritt.bot)


class NotfallTest(KlinikFlowTestCase):
    """Die wichtigste Eigenschaft des ganzen Baums."""

    STICHWORTE = [
        "mein Mann bekommt keine Luft",
        "ich glaube das ist ein Herzinfarkt",
        "Notfall",
        "sie ist bewusstlos",
        "Verdacht auf Schlaganfall",
    ]

    def test_notfall_wird_an_jeder_frage_erkannt(self):
        # An jedem Punkt des Dialogs, nicht nur am Anfang.
        for vorlauf in ([], ["Termin"], ["Termin", "Absage"], ["Termin", "Absage", "Anna Berger"]):
            for stichwort in self.STICHWORTE:
                ergebnis = self.spiele([*vorlauf, stichwort])
                self.assertEqual(
                    ergebnis.reason, "notfall", f"{vorlauf} + {stichwort!r} endete mit {ergebnis.reason}"
                )
                self.assertIn("1 1 2", self.ansagen(ergebnis))

    def test_notfall_beendet_das_gespraech_statt_zu_verbinden(self):
        # Warteschleife beim Sekretariat waere im Notfall das Schlimmste.
        ergebnis = self.spiele(["Notfall"])
        self.assertIsNone(ergebnis.transfer_target)
        self.assertEqual(self.flow.nodes["notfall_hinweis"].kind, NodeKind.HANGUP)

    def test_notfallweg_steht_im_ersten_satz(self):
        ergebnis = self.spiele([])
        self.assertIn("1 1 2", ergebnis.steps[0].bot[0])

    def test_notfall_nimmt_keine_daten_auf(self):
        ergebnis = self.spiele(["Termin", "Absage", "Anna Berger", "Notfall"])
        self.assertEqual(ergebnis.reason, "notfall")
        # Der Name war vorher erfasst -- aber es wird nichts weiter erfragt und
        # kein Vorgang angelegt.
        self.assertNotIn("vorgangsnummer", ergebnis.slots)


class AerztlicheAnruferTest(KlinikFlowTestCase):
    def test_werden_sofort_durchgestellt(self):
        for aeusserung in ("ich bin Ärztin aus der Praxis Dr. Berg", "Zuweisung", "Kollege aus der Chirurgie"):
            ergebnis = self.spiele([aeusserung])
            self.assertEqual(ergebnis.reason, "transferred", aeusserung)
            self.assertEqual(ergebnis.transfer_target, "PJSIP/sekretariat@uni-pbx")

    def test_ohne_datenaufnahme(self):
        ergebnis = self.spiele(["ich bin Arzt"])
        self.assertEqual(set(ergebnis.slots), {"anliegen"}, "Kollegen werden nicht abgefragt")

    def test_ausserhalb_der_sprechzeit_hinweis_auf_die_pforte(self):
        ergebnis = self.spiele(["ich bin Arzt, Zuweisung"], wann=ABENDS)
        self.assertIn("Pforte", self.ansagen(ergebnis))
        self.assertIsNone(ergebnis.transfer_target)


class KeineMedizinischeAbfrageTest(KlinikFlowTestCase):
    """Der Baum darf nach nichts Medizinischem fragen (auch MDR-relevant)."""

    VERBOTEN = ["beschwerden", "symptom", "schmerz", "wie geht es ihnen", "diagnose",
                "seit wann", "wie schlimm", "dringlich", "notfall?"]

    def test_keine_frage_nach_beschwerden(self):
        for knoten in self.flow.nodes.values():
            if knoten.kind not in (NodeKind.ASK, NodeKind.CONFIRM):
                continue
            text = (knoten.text or "").lower()
            for wort in self.VERBOTEN:
                self.assertNotIn(wort, text, f"Knoten '{knoten.id}' fragt nach '{wort}'")

    def test_keine_freitext_slots_ausser_dem_namen(self):
        # Freitext ist die Stelle, an der ungewollt Gesundheitsdaten ins
        # Protokoll geraten. Erlaubt ist nur der Name.
        freitext = [
            name for name, spec in self.flow.slots.items() if spec.kind is ExpectKind.TEXT
        ]
        self.assertEqual(sorted(freitext), ["name", "vorgangsnummer"])

    def test_personenbezogene_slots_sind_als_sensibel_markiert(self):
        for name in ("name", "rueckrufnummer", "termindatum"):
            self.assertTrue(self.flow.slots[name].sensitive, f"Slot '{name}' ist nicht maskiert")


class TerminTest(KlinikFlowTestCase):
    def test_absage_wird_abschliessend_erledigt(self):
        ergebnis = self.spiele(["Termin", "Absage", "Anna Berger", "morgen", "ja"])
        self.assertEqual(ergebnis.reason, "completed")
        self.assertEqual(ergebnis.slots["termindatum"], "2026-09-16")
        self.assertEqual(ergebnis.slots["vorgangsnummer"], "V-2026-0815")

    def test_falsch_verstandene_absage_laesst_sich_korrigieren(self):
        ergebnis = self.spiele(["Termin", "Absage", "Anna Berger", "morgen", "nein", "Anna Berger", "Freitag", "ja"])
        self.assertEqual(ergebnis.slots["termindatum"], "2026-09-18")

    def test_neuer_termin_wird_nicht_gebucht_sondern_notiert(self):
        ergebnis = self.spiele(["Termin", "neuer Termin", "Anna Berger", "089 4400 1234", "ja"])
        self.assertEqual(ergebnis.reason, "completed")
        self.assertNotIn("termindatum", ergebnis.slots, "Der Bot darf keinen Termin vergeben")
        self.assertIn("Rückruf", self.ansagen(ergebnis))

    def test_kein_knoten_bucht_einen_termin(self):
        for knoten in self.flow.nodes.values():
            if knoten.kind is NodeKind.ACTION:
                self.assertEqual(
                    knoten.action, "create_ticket", f"Knoten '{knoten.id}' ruft '{knoten.action}' auf"
                )


class AuskunftTest(KlinikFlowTestCase):
    def test_keine_auskunft_zu_befunden(self):
        ergebnis = self.spiele(["ich wollte nach meinem Befund fragen", "Anna Berger", "089 4400 1234", "ja"])
        ansagen = self.ansagen(ergebnis)
        self.assertIn("keine Auskunft", ansagen)
        self.assertEqual(ergebnis.reason, "completed")


class EskalationTest(KlinikFlowTestCase):
    def test_nach_zwei_missverstaendnissen_uebernimmt_ein_mensch(self):
        ergebnis = self.spiele(["ähm", "keine Ahnung", "weiß nicht"])
        self.assertEqual(ergebnis.reason, "transferred")

    def test_null_taste_verbindet_sofort(self):
        ergebnis = self.spiele(["#0"])
        self.assertEqual(ergebnis.reason, "transferred")

    def test_ausserhalb_der_sprechzeit_wird_nicht_ins_leere_verbunden(self):
        ergebnis = self.spiele(["#0", "Anna Berger", "089 4400 1234", "ja"], wann=ABENDS)
        self.assertIsNone(ergebnis.transfer_target)
        self.assertEqual(ergebnis.reason, "completed")
        self.assertEqual(ergebnis.slots["rueckrufnummer"], "08944001234")


if __name__ == "__main__":
    unittest.main()
