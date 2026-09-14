"""AudioSocket: Rahmenformat und Server."""

import asyncio
import unittest
import uuid

from telefonbot.audio import pcm
from telefonbot.telephony.audiosocket import AudioSocketServer
from telefonbot.telephony.base import AudioFrame, CallEnded, DtmfDigit
from telefonbot.telephony.protocol import (
    FRAME_BYTES,
    FrameDecoder,
    FrameKind,
    ProtocolError,
    encode_audio,
    encode_frame,
)


class ProtocolTest(unittest.TestCase):
    def test_rahmen_kodieren(self):
        raw = encode_frame(FrameKind.AUDIO, b"\x01\x02")
        self.assertEqual(raw, b"\x10\x00\x02\x01\x02")

    def test_rahmen_dekodieren(self):
        frames = FrameDecoder().feed(encode_frame(FrameKind.AUDIO, b"abcd"))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].kind, FrameKind.AUDIO)
        self.assertEqual(frames[0].payload, b"abcd")

    def test_zerstueckelter_strom(self):
        # TCP kennt keine Rahmengrenzen: byteweise gefuettert muss dasselbe herauskommen.
        data = encode_frame(FrameKind.ID, uuid.uuid4().bytes) + encode_frame(FrameKind.AUDIO, b"xy")
        decoder = FrameDecoder()
        frames = []
        for index in range(len(data)):
            frames.extend(decoder.feed(data[index : index + 1]))
        self.assertEqual([f.kind for f in frames], [FrameKind.ID, FrameKind.AUDIO])
        self.assertEqual(decoder.pending_bytes, 0)

    def test_unvollstaendiger_rahmen_wartet(self):
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(b"\x10\x00\x04ab"), [])
        self.assertEqual(len(decoder.feed(b"cd")), 1)

    def test_uuid_wird_lesbar(self):
        value = uuid.uuid4()
        frame = FrameDecoder().feed(encode_frame(FrameKind.ID, value.bytes))[0]
        self.assertEqual(frame.uuid, str(value))

    def test_dtmf_ziffer(self):
        frame = FrameDecoder().feed(encode_frame(FrameKind.DTMF, b"5"))[0]
        self.assertEqual(frame.digit, "5")

    def test_unbekannter_typ_wird_uebersprungen(self):
        data = encode_frame(FrameKind.AUDIO, b"ok")
        frames = FrameDecoder().feed(b"\x77\x00\x01z" + data)
        self.assertEqual([f.payload for f in frames], [b"ok"])

    def test_unbekannter_typ_streng(self):
        with self.assertRaises(ProtocolError):
            FrameDecoder(strict=True).feed(b"\x77\x00\x01z")

    def test_zu_lange_nutzdaten(self):
        with self.assertRaises(ProtocolError):
            encode_frame(FrameKind.AUDIO, b"x" * 70000)

    def test_audio_wird_auf_20ms_rahmen_verteilt(self):
        payload = pcm.samples_to_bytes(pcm.tone(100, 8000))  # 100 ms
        rahmen = list(encode_audio(payload))
        self.assertEqual(len(rahmen), 5)
        self.assertTrue(all(len(r) == FRAME_BYTES + 3 for r in rahmen))

    def test_letzter_rahmen_wird_mit_stille_aufgefuellt(self):
        payload = pcm.samples_to_bytes(pcm.tone(30, 8000))  # 1,5 Rahmen
        rahmen = list(encode_audio(payload))
        self.assertEqual(len(rahmen), 2)
        self.assertTrue(rahmen[-1].endswith(b"\x00" * 10))


class ServerTest(unittest.IsolatedAsyncioTestCase):
    """Echter TCP-Durchlauf gegen den Server -- ohne Asterisk."""

    async def asyncSetUp(self):
        self.events = []
        self.done = asyncio.Event()

        async def handler(transport):
            async for event in transport.events():
                self.events.append(event)
                if isinstance(event, DtmfDigit):
                    await transport.send_audio(pcm.tone(40, 8000))
                if isinstance(event, CallEnded):
                    break
            self.done.set()

        self.server = AudioSocketServer(handler, host="127.0.0.1", port=0)
        await self.server.start()
        self.port = self.server._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_anruf_von_der_uuid_bis_zum_auflegen(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        call_id = uuid.uuid4()
        writer.write(encode_frame(FrameKind.ID, call_id.bytes))
        writer.write(encode_frame(FrameKind.AUDIO, pcm.samples_to_bytes(pcm.tone(20, 8000))))
        writer.write(encode_frame(FrameKind.DTMF, b"7"))
        await writer.drain()

        antwort = await asyncio.wait_for(reader.read(1024), timeout=5)
        self.assertEqual(antwort[0], FrameKind.AUDIO)

        writer.write(encode_frame(FrameKind.HANGUP))
        await writer.drain()
        await asyncio.wait_for(self.done.wait(), timeout=5)
        writer.close()

        arten = [type(e).__name__ for e in self.events]
        self.assertEqual(arten, ["AudioFrame", "DtmfDigit", "CallEnded"])
        self.assertIsInstance(self.events[0], AudioFrame)
        self.assertEqual(self.events[1].digit, "7")

    async def test_verbindungsabbruch_gilt_als_aufgelegt(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(encode_frame(FrameKind.ID, uuid.uuid4().bytes))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        await asyncio.wait_for(self.done.wait(), timeout=5)
        self.assertIsInstance(self.events[-1], CallEnded)

    async def test_zu_viele_gleichzeitige_anrufe_werden_abgewiesen(self):
        self.server.max_concurrent_calls = 0
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        antwort = await asyncio.wait_for(reader.read(1024), timeout=5)
        self.assertEqual(antwort[0], FrameKind.HANGUP)
        writer.close()


if __name__ == "__main__":
    unittest.main()
