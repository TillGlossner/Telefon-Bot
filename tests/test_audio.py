"""PCM-Verarbeitung und Sprachaktivitaetserkennung."""

import math
import tempfile
import unittest
from array import array
from pathlib import Path

from telefonbot.audio import pcm
from telefonbot.audio.vad import EnergyVAD, SegmentEvent, SegmenterConfig, SpeechSegmenter


class PcmTest(unittest.TestCase):
    def test_bytes_hin_und_zurueck(self):
        samples = array("h", [0, 1, -1, 32767, -32768])
        self.assertEqual(list(pcm.bytes_to_samples(pcm.samples_to_bytes(samples))), list(samples))

    def test_angebrochenes_sample_wird_verworfen(self):
        self.assertEqual(len(pcm.bytes_to_samples(b"\x01\x02\x03")), 1)

    def test_resampling_aendert_laenge_aber_nicht_lautstaerke(self):
        original = pcm.tone(200, 8000, freq=400)
        up = pcm.resample(original, 8000, 16000)
        self.assertEqual(len(up), 2 * len(original))
        self.assertAlmostEqual(pcm.rms(up), pcm.rms(original), delta=200)

    def test_resampling_hin_und_zurueck_bleibt_aehnlich(self):
        original = pcm.tone(200, 8000, freq=400)
        back = pcm.resample(pcm.resample(original, 8000, 16000), 16000, 8000)
        self.assertEqual(len(back), len(original))
        self.assertAlmostEqual(pcm.rms(back), pcm.rms(original), delta=400)

    def test_gleiche_rate_kopiert_nur(self):
        original = pcm.tone(20, 8000)
        self.assertEqual(list(pcm.resample(original, 8000, 8000)), list(original))

    def test_pegel(self):
        self.assertEqual(pcm.dbfs(pcm.silence(20, 8000)), -100.0)
        self.assertGreater(pcm.dbfs(pcm.tone(20, 8000, amplitude=0.5)), -10)

    def test_bloecke(self):
        blocks = list(pcm.frames(pcm.silence(100, 8000), 160))
        self.assertEqual(len(blocks), 5)
        self.assertTrue(all(len(b) == 160 for b in blocks))

    def test_wav_schreiben_und_lesen(self):
        original = pcm.tone(50, 8000, freq=440)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unter" / "ansage.wav"
            pcm.write_wav(path, original, 8000)
            geladen, rate = pcm.read_wav(path)
        self.assertEqual(rate, 8000)
        self.assertEqual(list(geladen), list(original))

    def test_uebersteuerung_wird_begrenzt(self):
        laut = array("h", [32767] * 100)
        up = pcm.resample(laut, 8000, 16000)
        self.assertTrue(all(-32768 <= v <= 32767 for v in up))


class EnergyVadTest(unittest.TestCase):
    def setUp(self):
        self.vad = EnergyVAD()

    def test_ton_ist_sprache_stille_nicht(self):
        self.assertTrue(self.vad.is_speech(pcm.tone(20, 8000, amplitude=0.3)))
        self.assertFalse(self.vad.is_speech(pcm.silence(20, 8000)))

    def test_grundrauschen_wird_nachgefuehrt(self):
        rauschen = array("h", [int(300 * math.sin(i)) for i in range(160)])
        for _ in range(100):
            self.vad.is_speech(rauschen)
        # Nach dem Einpegeln gilt konstantes Rauschen nicht mehr als Sprache ...
        self.assertFalse(self.vad.is_speech(rauschen))
        # ... lautere Sprache aber weiterhin schon.
        self.assertTrue(self.vad.is_speech(pcm.tone(20, 8000, amplitude=0.3)))


class SegmenterTest(unittest.TestCase):
    def setUp(self):
        self.config = SegmenterConfig(frame_ms=20, start_speech_s=0.1, end_silence_s=0.4, no_input_s=1.0)
        self.segmenter = SpeechSegmenter(EnergyVAD(), self.config)

    def push_many(self, samples):
        events = []
        for frame in pcm.frames(samples, 160):
            event = self.segmenter.push(frame)
            if event:
                events.append(event)
        return events

    def test_beitrag_wird_erkannt_und_beendet(self):
        events = self.push_many(pcm.tone(500, 8000, amplitude=0.4))
        self.assertEqual(events, [SegmentEvent.SPEECH_START])
        events = self.push_many(pcm.silence(500, 8000))
        self.assertEqual(events, [SegmentEvent.SPEECH_END])

        audio = self.segmenter.take_audio()
        self.assertGreater(len(audio), 8000 * 0.4)  # Sprache ist vollstaendig im Puffer

    def test_kein_beitrag_meldet_zeitablauf(self):
        events = self.push_many(pcm.silence(1100, 8000))
        self.assertIn(SegmentEvent.NO_INPUT, events)

    def test_kurzes_knacken_startet_keinen_beitrag(self):
        events = self.push_many(pcm.tone(40, 8000, amplitude=0.5))
        self.assertEqual(events, [])

    def test_ueberlange_aeusserung_wird_abgeschnitten(self):
        self.segmenter.config.max_utterance_s = 0.5
        events = self.push_many(pcm.tone(2000, 8000, amplitude=0.4))
        self.assertIn(SegmentEvent.MAX_DURATION, events)

    def test_puffer_wird_nach_entnahme_geleert(self):
        self.push_many(pcm.tone(300, 8000, amplitude=0.4))
        self.push_many(pcm.silence(500, 8000))
        self.assertGreater(len(self.segmenter.take_audio()), 0)
        self.assertEqual(len(self.segmenter.take_audio()), 0)


if __name__ == "__main__":
    unittest.main()
