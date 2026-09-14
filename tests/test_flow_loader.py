"""Laden und statische Pruefung von Flows."""

import unittest

import yaml

from telefonbot.flow.loader import FlowLoadError, load_flow
from telefonbot.flow.model import ExpectKind, NodeKind
from telefonbot.flow.validate import validate_flow
from tests.fixtures import DEMO_FLOW_YAML


def raw(**overrides):
    data = yaml.safe_load(DEMO_FLOW_YAML)
    data.update(overrides)
    return data


class LoaderTest(unittest.TestCase):
    def test_demo_flow_laedt(self):
        flow = load_flow(yaml.safe_load(DEMO_FLOW_YAML))
        self.assertEqual(flow.id, "demo")
        self.assertEqual(flow.start, "begruessung")
        self.assertEqual(flow.nodes["hauptmenue"].kind, NodeKind.ASK)
        self.assertEqual(flow.nodes["termin_datum"].expect.kind, ExpectKind.DATE)
        self.assertEqual(flow.nodes["krank_matrikel"].expect.length, 8)
        self.assertTrue(flow.slots["matrikelnummer"].sensitive)
        self.assertEqual(flow.settings.escalation_node, "weiterleitung")

    def test_expect_kurzform_als_string(self):
        flow = load_flow(yaml.safe_load(DEMO_FLOW_YAML))
        self.assertEqual(flow.nodes["termin_datum"].expect.kind, ExpectKind.DATE)

    def test_optionsliste_als_kurzform(self):
        data = raw()
        data["nodes"]["hauptmenue"]["expect"]["options"] = ["termin", "krankmeldung"]
        flow = load_flow(data)
        self.assertEqual(flow.nodes["hauptmenue"].expect.options["termin"], ["termin"])

    def test_unbekannter_knotentyp(self):
        data = raw()
        data["nodes"]["begruessung"]["type"] = "sprich"
        with self.assertRaises(FlowLoadError) as ctx:
            load_flow(data)
        self.assertIn("sprich", str(ctx.exception))

    def test_tippfehler_im_feldnamen_faellt_auf(self):
        data = raw()
        data["nodes"]["begruessung"]["nxt"] = "hauptmenue"
        with self.assertRaises(FlowLoadError) as ctx:
            load_flow(data)
        self.assertIn("nxt", str(ctx.exception))

    def test_fehlende_pflichtfelder(self):
        with self.assertRaises(FlowLoadError):
            load_flow({"start": "a", "nodes": {}})

    def test_unbekannter_operator(self):
        data = raw()
        data["nodes"]["krank_pruefen"]["cases"] = [{"when": [{"slot": "x", "op": "gleich"}], "next": "weiterleitung"}]
        with self.assertRaises(FlowLoadError) as ctx:
            load_flow(data)
        self.assertIn("gleich", str(ctx.exception))


class ValidationTest(unittest.TestCase):
    def codes(self, data, severity="error"):
        flow = load_flow(data, strict=False)
        return {i.code for i in validate_flow(flow) if i.severity == severity}

    def test_demo_flow_ohne_fehler(self):
        flow = load_flow(yaml.safe_load(DEMO_FLOW_YAML))
        errors = [i for i in validate_flow(flow) if i.severity == "error"]
        self.assertEqual(errors, [])

    def test_uebergang_ins_leere(self):
        data = raw()
        data["nodes"]["begruessung"]["next"] = "gibtsnicht"
        self.assertIn("dangling_edge", self.codes(data))

    def test_option_ohne_uebergang(self):
        data = raw()
        del data["nodes"]["hauptmenue"]["transitions"]["krankmeldung"]
        self.assertIn("unhandled_option", self.codes(data))

    def test_uebergang_ohne_option(self):
        data = raw()
        data["nodes"]["hauptmenue"]["transitions"]["urlaub"] = "weiterleitung"
        self.assertIn("unknown_transition", self.codes(data))

    def test_sackgasse_wird_erkannt(self):
        data = raw()
        # Ein say-Knoten, der auf sich selbst zeigt, erreicht nie ein Gespraechsende.
        data["nodes"]["schleife"] = {"type": "say", "text": "hm", "next": "schleife"}
        data["nodes"]["begruessung"]["next"] = "schleife"
        self.assertIn("dead_end", self.codes(data))

    def test_unerreichbarer_knoten_ist_warnung(self):
        data = raw()
        data["nodes"]["waise"] = {"type": "hangup", "text": "tschuess"}
        self.assertIn("unreachable", self.codes(data, severity="warning"))

    def test_confirm_braucht_beide_zweige(self):
        data = raw()
        del data["nodes"]["termin_bestaetigen"]["on_no"]
        self.assertIn("missing_branch", self.codes(data))

    def test_unbekannter_platzhalter_ist_warnung(self):
        data = raw()
        data["nodes"]["termin_fertig"]["text"] = "Bis dann, {vorname}."
        self.assertIn("unknown_placeholder", self.codes(data, severity="warning"))

    def test_strict_laden_wirft_bei_fehler(self):
        data = raw()
        data["nodes"]["begruessung"]["next"] = "gibtsnicht"
        with self.assertRaises(FlowLoadError):
            load_flow(data, strict=True)


if __name__ == "__main__":
    unittest.main()
