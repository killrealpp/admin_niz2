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
    audio_data = base64.b64encode(audio_bytes).decode("ascii")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/fnsmvsvmpvpovbot",
        "X-Title": "Booking Bot Voice Transcription",
    }
    formats = _openrouter_format_candidates(audio_format)
    models = _unique([model, "openai/whisper-1"])
    last_response: httpx.Response | None = None
    with httpx.Client(timeout=60.0) as client:
        for candidate_model in models:
            for candidate_format in formats:
                payload: dict[str, object] = {
                    "model": candidate_model,
                    "input_audio": {
                        "data": audio_data,
                        "format": candidate_format,
                    },
                }
                if language:
                    payload["language"] = language
                response = client.post(url, headers=headers, json=payload)
                last_response = response
                if response.status_code < 400:
                    try:
                        result = response.json()
                    except ValueError as exc:
                        raise VoiceTranscriptionError(
                            f"OpenRouter transcription returned invalid JSON: {response.text[:500]}"
                        ) from exc
                    text = str(result.get("text") or "").strip()
                    if not text:
                        text = _text_from_chat_completion_shape(result)
                    return text
                if response.status_code in {401, 402, 403, 429}:
                    raise VoiceTranscriptionError(
                        f"OpenRouter transcription failed {response.status_code}: {response.text[:500]}"
                    )
    if last_response is not None:
        raise VoiceTranscriptionError(
            f"OpenRouter transcription failed {last_response.status_code}: {last_response.text[:500]}"
        )
    raise VoiceTranscriptionError("OpenRouter transcription failed without response")


def _openrouter_format_candidates(audio_format: str) -> list[str]:
    candidates = [audio_format]
    if audio_format == "ogg":
        candidates.extend(["opus", "webm"])
    return _unique(candidates)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _text_from_chat_completion_shape(result: dict) -> str:
    choices = result.get("choices") if isinstance(result, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message") or {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return " ".join(parts).strip()
    return ""


def _audio_format(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"wav", "mp3", "flac", "m4a", "ogg", "webm", "aac"}:
        return suffix
    return "ogg"
