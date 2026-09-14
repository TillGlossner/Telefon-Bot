"""Konfiguration, Simulator, Diagramm-Export, Control-API und CLI."""

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from telefonbot.cli import main
from telefonbot.config import AppConfig, load_config
from telefonbot.control.server import ControlServer, Stats
from telefonbot.flow.graph import to_mermaid
from telefonbot.flow.loader import load_flow, load_flow_file
from telefonbot.telephony.simulator import simulate
from tests.fixtures import DEMO_FLOW_YAML

FLOWS = Path(__file__).resolve().parent.parent / "config" / "flows"


class ConfigTest(unittest.TestCase):
    def test_vorgaben_ohne_datei(self):
        config = load_config(None, env={})
        self.assertEqual(config.telephony.port, 8090)
        self.assertEqual(config.asr.engine, "whisper")

    def test_yaml_ueberschreibt_vorgaben(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                yaml.safe_dump({"telephony": {"port": 9000}, "asr": {"model": "medium"}}),
                encoding="utf-8",
            )
            config = load_config(path, env={})
        self.assertEqual(config.telephony.port, 9000)
        self.assertEqual(config.asr.model, "medium")
        self.assertEqual(config.telephony.host, "127.0.0.1")  # unberuehrt

    def test_umgebung_ueberschreibt_yaml(self):
        config = load_config(None, env={"TELEFONBOT_TELEPHONY_PORT": "9100"})
        self.assertEqual(config.telephony.port, 9100)

    def test_mehrteilige_feldnamen(self):
        config = load_config(None, env={"TELEFONBOT_TELEPHONY_MAX_CONCURRENT_CALLS": "32"})
        self.assertEqual(config.telephony.max_concurrent_calls, 32)

    def test_wahrheitswerte_aus_text(self):
        config = load_config(None, env={"TELEFONBOT_SESSION_BARGE_IN": "nein"})
        self.assertFalse(config.session.barge_in)
        config = load_config(None, env={"TELEFONBOT_SESSION_BARGE_IN": "ja"})
        self.assertTrue(config.session.barge_in)

    def test_unbekannte_einstellung_bricht_nicht_ab(self):
        config = load_config(None, env={"TELEFONBOT_GIBTS_NICHT": "1"})
        self.assertIsInstance(config, AppConfig)

    def test_fehlende_datei_ist_kein_fehler(self):
        config = load_config("/gibt/es/nicht.yaml", env={})
        self.assertEqual(config.flow, AppConfig().flow)


class SimulatorTest(unittest.TestCase):
    def setUp(self):
        self.flow = load_flow(yaml.safe_load(DEMO_FLOW_YAML))

    def test_gespraech_mit_vorgegebenen_antworten(self):
        result = simulate(
            self.flow,
            ["Termin", "am 14. Maerz", "ja"],
            today=dt.date(2026, 3, 10),
            action_results={"create_appointment": "V-99"},
        )
        self.assertEqual(result.reason, "completed")
        self.assertEqual(result.slots["datum"], "2026-03-14")
        self.assertEqual(result.slots["ticket_id"], "V-99")
        self.assertIn("V-99", result.transcript()[-1])

    def test_tasteneingabe_mit_raute_praefix(self):
        result = simulate(self.flow, ["#2", "#12345678"], today=dt.date(2026, 3, 10))
        self.assertEqual(result.slots["matrikelnummer"], "12345678")

    def test_schweigen_als_leere_eingabe(self):
        result = simulate(self.flow, ["", "", ""], today=dt.date(2026, 3, 10))
        self.assertEqual(result.reason, "transferred")
        self.assertEqual(result.transfer_target, "PJSIP/sekretariat")

    def test_interaktive_funktion(self):
        antworten = iter(["Termin", "morgen", "ja"])
        result = simulate(self.flow, lambda ansagen: next(antworten), today=dt.date(2026, 3, 10))
        self.assertEqual(result.reason, "completed")


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.flow = load_flow(yaml.safe_load(DEMO_FLOW_YAML))
        self.diagram = to_mermaid(self.flow)

    def test_kopf_und_start(self):
        self.assertTrue(self.diagram.startswith("%% Flow demo"))
        self.assertIn("flowchart TD", self.diagram)
        self.assertIn("START(( )) --> begruessung", self.diagram)

    def test_alle_knoten_enthalten(self):
        for node_id in self.flow.nodes:
            self.assertIn(node_id, self.diagram)

    def test_beschriftete_uebergaenge(self):
        self.assertIn("hauptmenue -->|termin| termin_datum", self.diagram)
        self.assertIn("termin_bestaetigen -->|ja| termin_buchen", self.diagram)
        self.assertIn("termin_buchen -.->|Fehler| weiterleitung", self.diagram)

    def test_globale_kommandos_sichtbar(self):
        self.assertIn("GLOBAL_mensch", self.diagram)

    def test_anfuehrungszeichen_brechen_das_diagramm_nicht(self):
        data = yaml.safe_load(DEMO_FLOW_YAML)
        data["nodes"]["begruessung"]["text"] = 'Sagen Sie "Termin" | jetzt'
        diagram = to_mermaid(load_flow(data, strict=False))
        self.assertNotIn('"Termin"', diagram)
        self.assertIn("'Termin'", diagram)


class ControlApiTest(unittest.TestCase):
    def setUp(self):
        self.stats = Stats()
        self.server = ControlServer(self.stats, host="127.0.0.1", port=0, info={"flow": "demo"})
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def test_health(self):
        status, body = self.get("/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["flow"], "demo")

    def test_kennzahlen_zaehlen_anrufe(self):
        self.stats.call_started()
        self.stats.call_finished("abc", "completed", None)
        self.stats.call_started()
        self.stats.call_finished("def", "transferred", "PJSIP/sekretariat")

        _, body = self.get("/metrics")
        self.assertIn("telefonbot_calls_total 2", body)
        self.assertIn("telefonbot_calls_active 0", body)
        self.assertIn("telefonbot_transfers_total 1", body)
        self.assertIn('telefonbot_call_end_total{reason="completed"} 1', body)

    def test_weiterleitungsziel_fuer_den_dialplan(self):
        self.stats.call_started()
        self.stats.call_finished("uuid-1", "transferred", "PJSIP/sekretariat")
        status, body = self.get("/calls/uuid-1/transfer")
        self.assertEqual(status, 200)
        self.assertEqual(body, "PJSIP/sekretariat")

    def test_unbekannter_anruf(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/calls/gibtsnicht/outcome")
        self.assertEqual(ctx.exception.code, 404)

    def test_alte_ergebnisse_werden_verworfen(self):
        self.stats.max_outcomes = 3
        for index in range(5):
            self.stats.call_started()
            self.stats.call_finished(f"c{index}", "completed", None)
        self.assertEqual(len(self.stats.outcomes), 3)
        self.assertIsNone(self.stats.outcome("c0"))
        self.assertIsNotNone(self.stats.outcome("c4"))


class CliTest(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> tuple[int, str]:
        """Fuehrt die CLI aus und faengt die Ausgabe ab, statt sie in den Testlauf zu schreiben."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_beispielbaeume_bestehen_die_pruefung(self):
        code, ausgabe = self.run_cli(["pruefen", *[str(p) for p in sorted(FLOWS.glob("*.yaml"))]])
        self.assertEqual(code, 0)
        self.assertIn("0 Fehler", ausgabe)

    def test_fehlerhafter_baum_gibt_exitcode_eins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kaputt.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "kaputt",
                        "start": "a",
                        "nodes": {"a": {"type": "say", "text": "hi", "next": "b"}},
                    }
                ),
                encoding="utf-8",
            )
            code, ausgabe = self.run_cli(["pruefen", str(path)])
            self.assertEqual(code, 1)
            self.assertIn("dangling_edge", ausgabe)

    def test_graph_wird_geschrieben(self):
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / "unter" / "flow.mmd"
            code, _ = self.run_cli(["graph", str(FLOWS / "minimal_demo.yaml"), "-o", str(ziel)])
            self.assertEqual(code, 0)
            self.assertIn("flowchart TD", ziel.read_text(encoding="utf-8"))

    def test_spielen_mit_vorgegebenen_eingaben(self):
        code, ausgabe = self.run_cli(
            ["spielen", str(FLOWS / "minimal_demo.yaml"), "--eingaben", "ja"]
        )
        self.assertEqual(code, 0)
        self.assertIn("Das Sekretariat meldet sich bei Ihnen", ausgabe)

    def test_beispielbaum_laedt_streng(self):
        flow = load_flow_file(FLOWS / "lehrstuhl_sekretariat.yaml")
        self.assertEqual(flow.settings.escalation_node, "weiterleitung")
        self.assertTrue(flow.slots["matrikelnummer"].sensitive)


if __name__ == "__main__":
    unittest.main()


class BenchmarkHelperTest(unittest.TestCase):
    """Die Wortfehlerrate im Benchmark-Skript entscheidet über die Modellwahl."""

    @staticmethod
    def _wer():
        import importlib.util

        pfad = Path(__file__).resolve().parent.parent / "scripts" / "benchmark_asr.py"
        spec = importlib.util.spec_from_file_location("benchmark_asr", pfad)
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        return modul.wortfehlerrate

    def test_gleicher_text(self):
        self.assertEqual(self._wer()("guten Tag", "Guten Tag!"), 0.0)

    def test_ein_falsches_wort_von_vier(self):
        self.assertAlmostEqual(self._wer()("ich haette gern Termin", "ich haette gern Termine"), 0.25)

    def test_leere_referenz(self):
        self.assertEqual(self._wer()("", "irgendwas"), 0.0)
