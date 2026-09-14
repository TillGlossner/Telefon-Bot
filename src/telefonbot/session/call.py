"""Ein Telefonat von der Begruessung bis zum Auflegen.

Hier laufen alle Teile zusammen: Telefonie liefert Audio, die VAD schneidet
Aeusserungen heraus, die Spracherkennung macht Text daraus, der
Entscheidungsbaum entscheidet, die Sprachausgabe antwortet.

Die beiden Dinge, an denen sich ein Telefonbot im Alltag entscheidet, sind hier
umgesetzt:

* **Barge-in** -- der Anrufer darf der Ansage ins Wort fallen; der Anfang
  seines Satzes geht dabei nicht verloren, weil derselbe Segmentierer schon
  waehrend der Ansage mitlaeuft.
* **Sauberes Aufgeben** -- nach zu vielen Missverstaendnissen wird an einen
  Menschen weitergeleitet, statt den Anrufer in einer Schleife festzuhalten.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from telefonbot.asr.base import ASR
from telefonbot.audio.pcm import Samples, resample
from telefonbot.audio.vad import EnergyVAD, SegmentEvent, SegmenterConfig, SpeechSegmenter
from telefonbot.flow.effects import Collect, Hangup, Invoke, Speak, Transfer, Turn
from telefonbot.flow.engine import CallContext, FlowEngine, UserInput
from telefonbot.flow.model import ExpectKind, Flow
from telefonbot.nlu.rules import RuleInterpreter
from telefonbot.session.actions import ActionContext, ActionError, ActionRegistry
from telefonbot.session.transcript import REDACTED, Transcript, TranscriptWriter
from telefonbot.telephony.base import AudioFrame, AudioTransport, CallEnded, DtmfDigit, InboundEvent
from telefonbot.tts.base import TTS

log = logging.getLogger(__name__)


class CallerHungUp(Exception):
    """Der Anrufer hat aufgelegt -- beendet das Gespraech an jeder Stelle."""


@dataclass
class CallConfig:
    """Zeiten und Schalter eines Gespraechs."""

    segmenter: SegmenterConfig = field(default_factory=SegmenterConfig)
    dtmf_interdigit_s: float = 3.0
    """So lange wird nach einer Taste auf die naechste gewartet."""
    dtmf_terminator: str = "#"
    max_turns: int = 40
    """Notbremse gegen endlose Gespraeche."""
    barge_in: bool = True
    greeting_delay_s: float = 0.3
    """Kurze Pause, bevor der Bot spricht -- sonst faellt er der Leitung ins Wort."""


@dataclass
class CallResult:
    """Ergebnis eines Anrufs; Grundlage fuer Statistik und Weiterleitung."""

    call_id: str
    flow_id: str
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = "completed"
    transfer_target: str | None = None
    turns: int = 0
    duration_s: float = 0.0
    transcript: Transcript | None = None

    @property
    def transferred(self) -> bool:
        return self.transfer_target is not None


class CallSession:
    """Fuehrt ein einzelnes Telefonat."""

    def __init__(
        self,
        flow: Flow,
        transport: AudioTransport,
        asr: ASR,
        tts: TTS,
        *,
        interpreter: RuleInterpreter | None = None,
        actions: ActionRegistry | None = None,
        config: CallConfig | None = None,
        transcript_writer: TranscriptWriter | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.flow = flow
        self.transport = transport
        self.asr = asr
        self.tts = tts
        self.config = config or CallConfig()
        self.actions = actions or ActionRegistry()
        self.transcript_writer = transcript_writer

        info = transport.info
        self.context = CallContext(
            call_id=info.call_id,
            caller=info.caller,
            called=info.called,
            meta=dict(meta or {}),
        )
        self.engine = FlowEngine(flow, interpreter or RuleInterpreter(), context=self.context)
        self.transcript = Transcript(
            call_id=info.call_id,
            flow_id=flow.id,
            caller=info.caller,
            sensitive_slots={name for name, spec in flow.slots.items() if spec.sensitive},
        )

        segmenter_config = SegmenterConfig(
            frame_ms=transport.frame_ms,
            start_speech_s=self.config.segmenter.start_speech_s,
            end_silence_s=self.config.segmenter.end_silence_s,
            no_input_s=flow.settings.timeout_s,
            max_utterance_s=self.config.segmenter.max_utterance_s,
        )
        self.segmenter = SpeechSegmenter(EnergyVAD(), segmenter_config)

        self._queue: asyncio.Queue[InboundEvent] = asyncio.Queue()
        self._pending_get: asyncio.Task[InboundEvent] | None = None
        self._reader: asyncio.Task[None] | None = None
        self._ended = False

    # ------------------------------------------------------------------ Ablauf

    async def run(self) -> CallResult:
        """Fuehrt das Gespraech vollstaendig durch."""
        started = time.monotonic()
        self._reader = asyncio.create_task(self._read_events())
        turns = 0
        reason = "completed"
        transfer_target: str | None = None

        try:
            if self.config.greeting_delay_s:
                await asyncio.sleep(self.config.greeting_delay_s)
            turn = self.engine.start()

            while True:
                turns += 1
                if turns > self.config.max_turns:
                    log.warning("Anruf %s: Zugbegrenzung erreicht", self.context.call_id)
                    reason = "max_turns"
                    break

                barged = await self._speak_all(turn)
                pending = turn.pending

                if isinstance(pending, Hangup):
                    reason = pending.reason
                    break
                if isinstance(pending, Transfer):
                    transfer_target = pending.target
                    reason = "transferred"
                    self.transcript.add("system", f"Weiterleitung an {pending.target}", node_id=pending.node_id)
                    break
                if isinstance(pending, Invoke):
                    turn = await self._run_action(pending)
                    continue
                if isinstance(pending, Collect):
                    user_input = await self._listen(pending, barged_in=barged)
                    turn = self.engine.submit(user_input)
                    continue
                raise RuntimeError(f"Unerwarteter Effekt: {pending!r}")

        except CallerHungUp:
            reason = "caller_hangup"
            self.transcript.add("system", "Anrufer hat aufgelegt")
        finally:
            await self._shutdown(reason)

        result = CallResult(
            call_id=self.context.call_id,
            flow_id=self.flow.id,
            slots=dict(self.context.slots),
            reason=reason,
            transfer_target=transfer_target,
            turns=turns,
            duration_s=round(time.monotonic() - started, 2),
            transcript=self.transcript,
        )
        if self.transcript_writer:
            self.transcript_writer.write(self.transcript, result.slots)
        log.info(
            "Anruf %s beendet: %s nach %s Zuegen (%.1fs)",
            result.call_id, result.reason, result.turns, result.duration_s,
        )
        return result

    # ------------------------------------------------------------------ Sprechen

    async def _speak_all(self, turn: Turn) -> bool:
        """Gibt alle Ansagen eines Zuges aus. ``True``, wenn unterbrochen wurde."""
        for effect in turn.all_effects:
            if not isinstance(effect, Speak) or not effect.text:
                continue
            self.transcript.add("bot", effect.text, node_id=effect.node_id)
            speech = await self.tts.synthesize(effect.text)
            samples = self._to_line_rate(speech.samples, speech.sample_rate)

            allow_barge_in = self.config.barge_in and effect.barge_in
            if allow_barge_in:
                self.segmenter.reset()
            if await self._play(samples, allow_barge_in=allow_barge_in):
                log.debug("Barge-in bei Knoten %s", effect.node_id)
                self.transcript.add("system", "Anrufer unterbricht", node_id=effect.node_id)
                return True
        return False

    async def _play(self, samples: Samples, *, allow_barge_in: bool) -> bool:
        """Spielt Audio ab und horcht dabei auf Unterbrechungen."""
        send_task = asyncio.create_task(self.transport.send_audio(samples))
        try:
            while not send_task.done():
                get_task = self._ensure_get()
                done, _ = await asyncio.wait(
                    {get_task, send_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if get_task not in done:
                    continue
                event = self._take_event(get_task)
                if isinstance(event, CallEnded):
                    raise CallerHungUp
                if isinstance(event, DtmfDigit):
                    self._queue.put_nowait(event)  # Taste gehoert zur naechsten Antwort
                    await self.transport.stop_audio()
                    return True
                if isinstance(event, AudioFrame) and allow_barge_in:
                    if self.segmenter.push(event.samples) is SegmentEvent.SPEECH_START:
                        await self.transport.stop_audio()
                        return True
            return False
        finally:
            if not send_task.done():
                send_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await send_task

    # ------------------------------------------------------------------ Zuhoeren

    async def _listen(self, collect: Collect, *, barged_in: bool) -> UserInput:
        """Wartet auf die Antwort des Anrufers und laesst sie erkennen."""
        if not barged_in:
            self.segmenter.reset()
        self.segmenter.config.no_input_s = collect.timeout_s

        digits = ""
        expects_digits = collect.expect.kind in (ExpectKind.DIGITS, ExpectKind.NUMBER)
        deadline = time.monotonic() + collect.timeout_s + self.segmenter.config.max_utterance_s

        while True:
            timeout = self._listen_timeout(collect, digits, deadline)
            event = await self._get_event(timeout=timeout)

            if event is None:
                if digits:
                    return UserInput(dtmf=digits)
                return UserInput(timed_out=True)
            if isinstance(event, CallEnded):
                raise CallerHungUp

            if isinstance(event, DtmfDigit):
                if event.digit == self.config.dtmf_terminator:
                    return UserInput(dtmf=digits)
                digits += event.digit
                self.transcript.add(
                    "dtmf", self._maskiere(digits, collect.slot), node_id=collect.node_id
                )
                if not expects_digits or self._digits_complete(collect, digits):
                    return UserInput(dtmf=digits)
                continue

            if isinstance(event, AudioFrame):
                if digits:
                    continue  # begonnene Tasteneingabe nicht durch Nebengeraeusch stoeren
                result = self.segmenter.push(event.samples)
                if result is SegmentEvent.NO_INPUT:
                    return UserInput(timed_out=True)
                if result in (SegmentEvent.SPEECH_END, SegmentEvent.MAX_DURATION):
                    return await self._transcribe(self.segmenter.take_audio(), collect)

    def _listen_timeout(self, collect: Collect, digits: str, deadline: float) -> float:
        """Wieviel Wartezeit bleibt, bis aufgegeben wird."""
        if digits:
            return self.config.dtmf_interdigit_s
        remaining = deadline - time.monotonic()
        # Auch ohne eingehende Bloecke (Stillepakete) muss der Timeout greifen.
        return max(0.1, min(remaining, collect.timeout_s + 1.0))

    @staticmethod
    def _digits_complete(collect: Collect, digits: str) -> bool:
        expected = collect.expect.length
        if expected is not None:
            return len(digits) >= expected
        return False

    async def _transcribe(self, audio: Samples, collect: Collect) -> UserInput:
        if not audio:
            return UserInput(timed_out=True)
        transcript = await self.asr.transcribe(audio, self.transport.sample_rate)
        if transcript.empty:
            self.transcript.add("user", "", node_id=collect.node_id, konfidenz=0.0)
            return UserInput(text="", confidence=0.0)
        self.transcript.add(
            "user",
            self._maskiere(transcript.text, collect.slot),
            node_id=collect.node_id,
            konfidenz=transcript.confidence,
            dauer_s=round(transcript.duration_s, 2),
        )
        return UserInput(text=transcript.text, confidence=transcript.confidence)

    def _maskiere(self, text: str, slot: str | None) -> str:
        """Aeusserungen zu sensiblen Slots nicht im Klartext protokollieren.

        Die Dialogsteuerung bekommt weiterhin den echten Text -- nur Protokoll
        und Live-Anzeige sehen die Maskierung. Sonst stuende die vorgelesene
        Matrikelnummer woertlich in der Protokolldatei, waehrend der Slot
        daneben brav mit *** erscheint.
        """
        if slot and slot in self.transcript.sensitive_slots:
            return REDACTED
        return text

    # ------------------------------------------------------------------ Aktionen

    async def _run_action(self, invoke: Invoke) -> Turn:
        context = ActionContext(self.context.call_id, self.context.caller, self.context.slots)
        try:
            value = await self.actions.run(invoke.action, invoke.args, context)
        except ActionError as exc:
            self.transcript.add("action", str(exc), node_id=invoke.node_id, erfolg=False)
            return self.engine.submit_action_result(error=str(exc))
        self.transcript.add(
            "action", invoke.action, node_id=invoke.node_id, erfolg=True, ergebnis=str(value)[:200]
        )
        return self.engine.submit_action_result(value)

    # ------------------------------------------------------------------ Technik

    def _to_line_rate(self, samples: Samples, sample_rate: int) -> Samples:
        if sample_rate == self.transport.sample_rate:
            return samples
        return resample(samples, sample_rate, self.transport.sample_rate)

    async def _read_events(self) -> None:
        """Haengt am Transport und puffert Ereignisse, damit nichts verloren geht."""
        try:
            async for event in self.transport.events():
                await self._queue.put(event)
                if isinstance(event, CallEnded):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ereignisstrom abgebrochen")
            await self._queue.put(CallEnded("transport_error"))

    def _ensure_get(self) -> asyncio.Task[InboundEvent]:
        if self._pending_get is None:
            self._pending_get = asyncio.create_task(self._queue.get())
        return self._pending_get

    def _take_event(self, task: asyncio.Task[InboundEvent]) -> InboundEvent:
        self._pending_get = None
        return task.result()

    async def _get_event(self, *, timeout: float | None = None) -> InboundEvent | None:
        """Naechstes Ereignis; ``None`` bei Zeitueberschreitung.

        ``shield`` sorgt dafuer, dass ein Timeout die wartende Leseoperation
        nicht abbricht -- sonst ginge das Ereignis verloren, das gleich eintrifft.
        """
        task = self._ensure_get()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return self._take_event(task)

    async def _shutdown(self, reason: str) -> None:
        if self._ended:
            return
        self._ended = True
        if self._pending_get is not None:
            self._pending_get.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._pending_get
            self._pending_get = None
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        with contextlib.suppress(Exception):
            await self.transport.hangup(reason)
