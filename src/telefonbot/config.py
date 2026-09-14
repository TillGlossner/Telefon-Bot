"""Konfiguration aus YAML plus Umgebungsvariablen.

Eine Datei fuer den Normalfall, Umgebungsvariablen fuer Betriebsdetails
(``TELEFONBOT_ASR_MODEL``, ``TELEFONBOT_TELEPHONY_PORT``, ...). Geheimnisse
gehoeren nicht in die YAML, sondern in die Umgebung oder eine systemd-
EnvironmentFile.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ENV_PREFIX = "TELEFONBOT_"


@dataclass
class TelephonyConfig:
    host: str = "127.0.0.1"
    port: int = 8090
    max_concurrent_calls: int = 8
    sample_rate: int = 8000


@dataclass
class AsrConfig:
    engine: str = "whisper"  # "whisper" | "fake"
    model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "int8_float16"
    language: str = "de"
    beam_size: int = 5
    initial_prompt: str = ""
    model_dir: str | None = None


@dataclass
class TtsConfig:
    engine: str = "piper"  # "piper" | "fake"
    voice_path: str = "models/piper/de_DE-thorsten-high.onnx"
    length_scale: float = 1.05
    cache_dir: str = "var/tts-cache"
    cache_enabled: bool = True


@dataclass
class VadConfig:
    engine: str = "energy"  # "energy" | "silero"
    model_path: str = "models/silero_vad.onnx"
    margin_db: float = 12.0
    end_silence_s: float = 0.8
    start_speech_s: float = 0.12
    max_utterance_s: float = 30.0


@dataclass
class SessionConfig:
    barge_in: bool = True
    greeting_delay_s: float = 0.3
    max_turns: int = 40
    dtmf_interdigit_s: float = 3.0
    action_timeout_s: float = 8.0


@dataclass
class TranscriptConfig:
    enabled: bool = True
    directory: str = "var/transkripte"
    store_audio: bool = False
    """Rohaudio speichern -- nur mit Rechtsgrundlage und Loeschfrist einschalten."""
    retention_days: int = 30


@dataclass
class ActionsConfig:
    ticket_dir: str = "var/vorgaenge"
    webhook_url: str = ""
    webhook_token: str = ""


@dataclass
class ControlConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    """Absichtlich nur lokal: die API hat keine Authentisierung."""
    port: int = 8091


@dataclass
class AppConfig:
    """Gesamtkonfiguration des Bots."""

    flow: str = "config/flows/lehrstuhl_sekretariat.yaml"
    log_level: str = "INFO"
    telephony: TelephonyConfig = field(default_factory=TelephonyConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    transcripts: TranscriptConfig = field(default_factory=TranscriptConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    control: ControlConfig = field(default_factory=ControlConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: str | Path | None = None, *, env: dict[str, str] | None = None) -> AppConfig:
    """Laedt die Konfiguration; fehlende Datei ist kein Fehler (Defaults gelten)."""
    config = AppConfig()
    if path:
        file = Path(path)
        if file.exists():
            import yaml

            raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            _apply_mapping(config, raw, where=str(file))
        else:
            log.warning("Konfiguration %s nicht gefunden -- verwende Vorgaben", file)
    _apply_env(config, env if env is not None else dict(os.environ))
    return config


def _apply_mapping(target: Any, raw: dict[str, Any], *, where: str, prefix: str = "") -> None:
    known = {f.name: f for f in fields(target)}
    for key, value in (raw or {}).items():
        spec = known.get(str(key))
        if spec is None:
            log.warning("%s: unbekannte Einstellung '%s%s' ignoriert", where, prefix, key)
            continue
        current = getattr(target, spec.name)
        if is_dataclass(current) and isinstance(value, dict):
            _apply_mapping(current, value, where=where, prefix=f"{prefix}{key}.")
        else:
            setattr(target, spec.name, _coerce(current, value))


def _apply_env(config: AppConfig, env: dict[str, str]) -> None:
    """``TELEFONBOT_ASR_MODEL=small`` setzt ``config.asr.model``."""
    for raw_key, raw_value in env.items():
        if not raw_key.startswith(ENV_PREFIX):
            continue
        parts = raw_key[len(ENV_PREFIX) :].lower().split("_")
        if not _set_by_path(config, parts, raw_value):
            log.warning("Unbekannte Umgebungsvariable %s ignoriert", raw_key)


def _set_by_path(target: Any, parts: list[str], value: str) -> bool:
    """Setzt einen Wert entlang der Namensteile; ``False``, wenn der Pfad nicht passt.

    Namensteile sind mehrdeutig (``max_concurrent_calls`` besteht aus drei),
    deshalb wird immer der laengste passende Feldname genommen.
    """
    if not is_dataclass(target) or not parts:
        return False
    names = [f.name for f in fields(target)]
    match = _longest_match(names, parts)
    if match is None:
        return False
    attribute = getattr(target, match["name"])
    rest = parts[match["used"] :]
    if not rest:
        setattr(target, match["name"], _coerce(attribute, value))
        return True
    return _set_by_path(attribute, rest, value)


def _longest_match(candidates: list[str], parts: list[str]) -> dict[str, Any] | None:
    """Findet das Feld, das die meisten Namensteile abdeckt (``max_concurrent_calls``)."""
    best: dict[str, Any] | None = None
    for size in range(len(parts), 0, -1):
        name = "_".join(parts[:size])
        if name in candidates:
            best = {"name": name, "used": size}
            break
    return best


def _coerce(current: Any, value: Any) -> Any:
    """Bringt YAML-/Umgebungswerte auf den Typ des Vorgabewerts."""
    if current is None:
        return value
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "ja", "on")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, str):
        return str(value)
    return value
