"""Spracherkennung: Schnittstelle, faster-whisper-Adapter, Fake fuer Tests."""

from telefonbot.asr.base import ASR, Transcript
from telefonbot.asr.fake import ScriptedASR

__all__ = ["ASR", "ScriptedASR", "Transcript"]
