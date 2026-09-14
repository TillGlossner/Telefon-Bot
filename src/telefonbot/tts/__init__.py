"""Sprachsynthese: Schnittstelle, Piper-Adapter, Cache, Fake fuer Tests."""

from telefonbot.tts.base import TTS, Speech
from telefonbot.tts.cache import CachingTTS
from telefonbot.tts.fake import FakeTTS

__all__ = ["TTS", "CachingTTS", "FakeTTS", "Speech"]
