from __future__ import annotations

import asyncio
import base64
from io import BytesIO

import httpx
from aiogram import Bot
from aiogram.types import Message
from openai import OpenAI

from app.core.config import get_settings


class VoiceTranscriptionError(RuntimeError):
    pass


async def transcribe_telegram_voice(bot: Bot, message: Message) -> str:
    settings = get_settings()
    if not settings.voice_transcription_enabled:
        raise VoiceTranscriptionError("Voice transcription is disabled")
    provider = settings.voice_transcription_provider.lower().strip()
    if provider == "openrouter" and not settings.openrouter_api_key:
        raise VoiceTranscriptionError("OPENROUTER_API_KEY is required for voice transcription")
    if provider == "openai" and not settings.openai_api_key:
        raise VoiceTranscriptionError("OPENAI_API_KEY is required for voice transcription")
    if not message.voice:
        raise VoiceTranscriptionError("Telegram message has no voice payload")
    if message.voice.duration and message.voice.duration > settings.voice_transcription_max_seconds:
        raise VoiceTranscriptionError("Voice message is too long")

    telegram_file = await bot.get_file(message.voice.file_id)
    if not telegram_file.file_path:
        raise VoiceTranscriptionError("Telegram file path is empty")
    audio = BytesIO()
    await bot.download_file(telegram_file.file_path, destination=audio)
    audio.seek(0)
    audio.name = "voice.ogg"

    text = await asyncio.to_thread(
        _transcribe_audio,
        audio,
        provider,
        settings.openrouter_api_key if provider == "openrouter" else settings.openai_api_key,
        settings.openrouter_base_url,
        settings.voice_transcription_model,
        settings.voice_transcription_language or None,
    )
    if not text:
        raise VoiceTranscriptionError("Empty voice transcription")
    return text


def _transcribe_audio(
    audio: BytesIO,
    provider: str,
    api_key: str,
    openrouter_base_url: str,
    model: str,
    language: str | None,
) -> str:
    if provider == "openrouter":
        return _transcribe_audio_openrouter(
            audio,
            api_key=api_key,
            base_url=openrouter_base_url,
            model=model,
            language=language,
        )
    client = OpenAI(api_key=api_key, timeout=45.0)
    transcription = client.audio.transcriptions.create(
        model=model,
        file=audio,
        language=language,
    )
    return str(getattr(transcription, "text", "") or "").strip()


def _transcribe_audio_openrouter(
    audio: BytesIO,
    *,
    api_key: str,
    base_url: str,
    model: str,
    language: str | None,
) -> str:
    url = base_url.rstrip("/") + "/audio/transcriptions"
    audio_bytes = audio.getvalue()
    audio_format = _audio_format(getattr(audio, "name", "voice.ogg"))
    payload: dict[str, object] = {
        "model": model,
        "input_audio": {
            "data": base64.b64encode(audio_bytes).decode("ascii"),
            "format": audio_format,
        },
    }
    if language:
        payload["language"] = language
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/fnsmvsvmpvpovbot",
        "X-Title": "Booking Bot Voice Transcription",
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 500 and model != "openai/whisper-1":
            payload["model"] = "openai/whisper-1"
            response = client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise VoiceTranscriptionError(
            f"OpenRouter transcription failed {response.status_code}: {response.text[:500]}"
        )
    payload = response.json()
    return str(payload.get("text") or "").strip()


def _audio_format(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"wav", "mp3", "flac", "m4a", "ogg", "webm", "aac"}:
        return suffix
    return "ogg"
