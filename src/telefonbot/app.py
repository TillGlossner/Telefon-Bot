"""Verdrahtung: aus Konfiguration wird ein lauffaehiger Dienst.

Hier -- und nur hier -- wird entschieden, welche konkreten Bausteine zum
Einsatz kommen. Fehlt ein optionales Paket (faster-whisper, piper), sagt der
Dienst das deutlich und faellt fuer den Textbetrieb auf Attrappen zurueck,
statt beim ersten Anruf abzustuerzen.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path

from telefonbot.asr.base import ASR
from telefonbot.audio.vad import SegmenterConfig
from telefonbot.config import AppConfig
from telefonbot.flow.loader import load_flow_file
from telefonbot.flow.model import Flow, NodeKind
from telefonbot.nlu.rules import RuleInterpreter
from telefonbot.session.actions import (
    ActionRegistry,
    make_file_ticket_action,
    make_http_action,
    noop_action,
)
from telefonbot.session.call import CallConfig, CallSession
from telefonbot.session.sprechzeiten import Sprechzeiten
from telefonbot.session.transcript import TranscriptWriter
from telefonbot.telephony.audiosocket import AudioSocketServer, AudioSocketTransport
from telefonbot.tts.base import TTS
from telefonbot.tts.cache import CachingTTS

log = logging.getLogger(__name__)


def build_asr(config: AppConfig) -> ASR:
    """Erkenner nach Konfiguration; ohne faster-whisper kommt die Attrappe."""
    if config.asr.engine == "fake":
        from telefonbot.asr.fake import ScriptedASR

        return ScriptedASR([])
    try:
        from telefonbot.asr.whisper import FasterWhisperASR, WhisperConfig
    except ImportError:  # pragma: no cover -- haengt von der Installation ab
        log.error("faster-whisper fehlt; installiere 'telefonbot[asr]'")
        raise
    return FasterWhisperASR(
        WhisperConfig(
            model=config.asr.model,
            device=config.asr.device,
            compute_type=config.asr.compute_type,
            language=config.asr.language,
            beam_size=config.asr.beam_size,
            initial_prompt=config.asr.initial_prompt,
            model_dir=config.asr.model_dir,
        )
    )


def build_tts(config: AppConfig) -> TTS:
    """Sprachausgabe nach Konfiguration, bei Bedarf mit Ansagen-Cache."""
    if config.tts.engine == "fake":
        from telefonbot.tts.fake import FakeTTS

        base: TTS = FakeTTS(sample_rate=config.telephony.sample_rate)
    else:
        from telefonbot.tts.piper import PiperConfig, PiperTTS

        base = PiperTTS(
            PiperConfig(
                voice_path=config.tts.voice_path,
                output_sample_rate=config.telephony.sample_rate,
                length_scale=config.tts.length_scale,
            )
        )
    if config.tts.cache_enabled:
        return CachingTTS(base, config.tts.cache_dir)
    return base


def build_actions(config: AppConfig) -> ActionRegistry:
    """Fachaktionen registrieren -- hier wird die Fachanbindung eingehaengt."""
    registry = ActionRegistry(timeout_s=config.session.action_timeout_s)
    registry.register("noop", noop_action)
    ticket = make_file_ticket_action(config.actions.ticket_dir)
    registry.register("create_ticket", ticket)
    registry.register("create_appointment", ticket)
    if config.actions.webhook_url:
        registry.register(
            "notify_backend",
            make_http_action(config.actions.webhook_url, token=config.actions.webhook_token),
        )
    return registry


def build_call_config(config: AppConfig) -> CallConfig:
    return CallConfig(
        segmenter=SegmenterConfig(
            frame_ms=20,
            start_speech_s=config.vad.start_speech_s,
            end_silence_s=config.vad.end_silence_s,
            max_utterance_s=config.vad.max_utterance_s,
        ),
        dtmf_interdigit_s=config.session.dtmf_interdigit_s,
        max_turns=config.session.max_turns,
        barge_in=config.session.barge_in,
        greeting_delay_s=config.session.greeting_delay_s,
    )


def prompts_of(flow: Flow) -> list[str]:
    """Alle festen Ansagen ohne Platzhalter -- Kandidaten fuer den TTS-Cache."""
    texts = []
    for node in flow.nodes.values():
        for text in (node.text, node.reprompt, node.no_input_text):
            if text and "{" not in text and node.kind is not NodeKind.BRANCH:
                texts.append(text)
    return sorted(set(texts))


class BotService:
    """Der Dienst: nimmt Anrufe an und fuehrt sie durch den Entscheidungsbaum."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.flow = load_flow_file(config.flow)
        self.asr = build_asr(config)
        self.tts = build_tts(config)
        self.actions = build_actions(config)
        self.sprechzeiten = Sprechzeiten.aus_konfiguration(
            config.sprechzeiten.tage, config.sprechzeiten.geschlossen_an
        )
        self.call_config = build_call_config(config)
        self.transcripts = TranscriptWriter(
            config.transcripts.directory, enabled=config.transcripts.enabled
        )
        from telefonbot.control.server import ControlServer, Stats

        self.stats = Stats()
        self.control = (
            ControlServer(
                self.stats,
                host=config.control.host,
                port=config.control.port,
                info={"flow": self.flow.id, "flow_version": self.flow.version},
            )
            if config.control.enabled
            else None
        )
        self.server = AudioSocketServer(
            self.handle_call,
            host=config.telephony.host,
            port=config.telephony.port,
            max_concurrent_calls=config.telephony.max_concurrent_calls,
        )

    async def warmup(self) -> None:
        """Modelle laden und feste Ansagen vorsynthetisieren."""
        await self.asr.warmup()
        if isinstance(self.tts, CachingTTS):
            await self.tts.warmup(prompts_of(self.flow))
            log.info("Ansagen im Cache: %s Treffer, %s neu", self.tts.hits, self.tts.misses)
        else:
            await self.tts.warmup()

    async def handle_call(self, transport: AudioSocketTransport) -> None:
        """Ein Anruf von Anfang bis Ende."""
        self.stats.call_started()
        session = CallSession(
            self.flow,
            transport,
            self.asr,
            self.tts,
            interpreter=RuleInterpreter(),
            actions=self.actions,
            config=self.call_config,
            transcript_writer=self.transcripts,
            meta=self.sprechzeiten.kontext(dt.datetime.now()),
        )
        result = None
        try:
            result = await session.run()
        finally:
            # Auch ein abgestuerztes Gespraech muss aus der Statistik verschwinden,
            # sonst zeigt die Ueberwachung dauerhaft laufende Anrufe an.
            self.stats.call_finished(
                transport.info.call_id,
                result.reason if result else "error",
                result.transfer_target if result else None,
            )
        if result and result.transfer_target:
            transport.pending_transfer = result.transfer_target

    async def run(self) -> None:
        """Startet Control-API und AudioSocket-Server."""
        Path(self.config.transcripts.directory).mkdir(parents=True, exist_ok=True)
        if self.control:
            self.control.start()
        await self.warmup()
        log.info(
            "Bot bereit: Flow '%s' v%s, Telefonie auf %s:%s",
            self.flow.id,
            self.flow.version,
            self.config.telephony.host,
            self.config.telephony.port,
        )
        try:
            await self.server.serve_forever()
        except asyncio.CancelledError:
            log.info("Beende Dienst")
            raise
        finally:
            await self.server.stop()
            if self.control:
                self.control.stop()
