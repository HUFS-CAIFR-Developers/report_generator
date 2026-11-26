"""Typecast `Convert text to speech with timestamps` 노드 대체.

@neosapience/n8n-nodes-typecast 소스 기준:
  POST https://api.typecast.ai/v1/text-to-speech/with-timestamps?granularity=word
  header X-API-KEY, body {voice_id, text, model, prompt}
  응답 {audio(base64), audio_format, audio_duration, words[{text,start,end}], characters}
워크플로우는 model/emotion 을 기본값으로 두었으므로 model=ssfm-v30, prompt={emotion_type: smart}.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

from .errors import PipelineError
from .http import make_session

TYPECAST_URL = "https://api.typecast.ai/v1/text-to-speech/with-timestamps"


@dataclass
class TTSResult:
    audio: bytes
    audio_format: str
    audio_duration: float | None
    words: list[dict[str, Any]]


class TTSClient(Protocol):
    def synthesize(self, text: str) -> TTSResult: ...


def build_typecast_body(text: str, voice_id: str, model: str) -> dict[str, Any]:
    body: dict[str, Any] = {"voice_id": voice_id, "text": text, "model": model}
    if model == "ssfm-v30":
        body["prompt"] = {"emotion_type": "smart"}
    else:  # ssfm-v21 기본값
        body["prompt"] = {"emotion_preset": "normal", "emotion_intensity": 1}
    return body


class TypecastClient:
    def __init__(self, api_key: str, voice_id: str, model: str = "ssfm-v30",
                 session: requests.Session | None = None, timeout: float = 180.0):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.session = session or make_session()
        self.timeout = timeout

    def synthesize(self, text: str) -> TTSResult:
        try:
            r = self.session.post(
                TYPECAST_URL,
                params={"granularity": "word"},
                json=build_typecast_body(text, self.voice_id, self.model),
                headers={"X-API-KEY": self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise PipelineError("typecast", f"요청 실패: {e}") from e
        if r.status_code >= 400:
            raise PipelineError("typecast", f"[{r.status_code}] {r.text[:300]}")
        data = r.json()
        audio_b64 = data.get("audio") or ""
        if not audio_b64:
            raise PipelineError("typecast", "응답에 audio 가 없습니다")
        return TTSResult(
            audio=base64.b64decode(audio_b64),
            audio_format=data.get("audio_format") or "wav",
            audio_duration=data.get("audio_duration"),
            words=data.get("words") or [],
        )


def save_audio(result: TTSResult, work_dir: Path, scene_number: int) -> Path:
    """Read/Write Files from Disk4: audio_{scene}.wav"""
    path = work_dir / f"audio_{scene_number}.wav"
    path.write_bytes(result.audio)
    return path
