"""Higgsfield 이미지/영상 생성 브랜치 대체.

n8n 흐름 (Switch → HF * Submit → Wait(5s) → HF * Status → Status Switch):
  image      : soul/standard 제출 → completed 면 images[0].url 다운로드, queued/in_progress 면 재대기,
               그 외 상태는 n8n 에서 출력이 없어 장면이 조용히 빠졌다 → 여기서는 AssetGenerationError.
  loop_video : kling-video/v3.0/std/text-to-video 제출 → completed 면 video.url 다운로드,
               queued/in_progress 면 재대기, 그 외(failed/nsfw/canceled 등)는 출력이 없어 장면이 빠진다
               (이미지 폴백 브랜치는 워크플로우에서 삭제됨) → 여기서는 AssetGenerationError.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import requests

from .errors import AssetGenerationError, PipelineError
from .http import make_session
from .logging_setup import get_logger

log = get_logger("higgsfield")

IMAGE_PATH = "/higgsfield-ai/soul/standard"
VIDEO_PATH = "/kling-video/v3.0/std/text-to-video"
PENDING = ("queued", "in_progress")


@dataclass
class Asset:
    asset_type: str          # "image" | "video"  (n8n Edit Fields / Edit Fields1)
    data: bytes


class AssetClient(Protocol):
    def generate(self, visual: dict[str, Any]) -> Asset: ...


def image_payload(prompt: str) -> dict[str, Any]:
    return {"prompt": prompt, "batch_size": 1, "resolution": "1080p", "aspect_ratio": "9:16", "enhance_prompt": False}


def video_duration(duration: Any) -> int:
    """Math.max(3, Math.min(15, Math.ceil(Number(duration))))"""
    return max(3, min(15, math.ceil(float(duration))))


def video_payload(prompt: str, duration: Any) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "sound": "off",
        "duration": video_duration(duration),
        "cfg_scale": 0.5,
        "multi_shots": False,
        "aspect_ratio": "9:16",
    }


def _result_url(body: dict[str, Any], label: str, scene: Any) -> str:
    """완료 응답의 결과 주소. 주소가 빠져 있으면 그 장면만 건너뛰도록 AssetGenerationError로 바꾼다."""
    try:
        return body["video"]["url"] if label == "video" else body["images"][0]["url"]
    except (KeyError, IndexError, TypeError) as e:
        raise AssetGenerationError("higgsfield", f"{label} 완료 응답에 결과 주소가 없습니다: {e!r}", scene=scene) from e


class HiggsfieldClient:
    def __init__(self, auth_header: str, base_url: str = "https://api.higgsfield.ai", *,
                 poll_interval: float = 5.0, poll_timeout: float = 1800.0,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.auth_header = auth_header
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.session = session or make_session()
        self._sleep = sleep
        self._clock = clock

    # ---------- public ----------
    def generate(self, visual: dict[str, Any]) -> Asset:
        scene = visual.get("scene_number")
        kind = visual["recommended_asset"]
        if kind == "image":
            return Asset("image", self.generate_image(visual["image_prompt"], scene))
        if kind == "loop_video":
            body = self._run_job(VIDEO_PATH, video_payload(visual["loop_video_prompt"], visual["duration"]),
                                 scene, "video")
            return Asset("video", self._download(_result_url(body, "video", scene), scene))
        raise PipelineError("higgsfield", f"알 수 없는 recommended_asset: {kind!r}", scene=scene)

    def generate_image(self, prompt: str, scene: Any) -> bytes:
        body = self._run_job(IMAGE_PATH, image_payload(prompt), scene, "image")
        return self._download(_result_url(body, "image", scene), scene)

    # ---------- internals ----------
    def _headers(self, json_body: bool = False) -> dict[str, str]:
        h = {"Authorization": self.auth_header}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _run_job(self, path: str, payload: dict[str, Any], scene: Any, label: str) -> dict[str, Any]:
        try:
            r = self.session.post(self.base_url + path, json=payload, headers=self._headers(True), timeout=60)
        except requests.RequestException as e:
            raise AssetGenerationError("higgsfield", f"{label} 제출 실패: {e}", scene=scene) from e
        if r.status_code >= 400:
            raise AssetGenerationError("higgsfield", f"{label} 제출 [{r.status_code}] {r.text[:300]}", scene=scene)
        submitted = r.json()
        status_url = submitted.get("status_url")
        if not status_url:
            raise AssetGenerationError("higgsfield", f"{label} 제출 응답에 status_url 이 없습니다: {submitted}", scene=scene)
        log.info("scene %s: %s 제출 (request_id=%s)", scene, label, submitted.get("request_id"))

        deadline = self._clock() + self.poll_timeout
        while True:
            self._sleep(self.poll_interval)  # n8n Wait 노드 (상태 확인 전에 대기)
            try:
                s = self.session.get(status_url, headers=self._headers(), timeout=60)
            except requests.RequestException as e:
                raise AssetGenerationError("higgsfield", f"{label} 상태 조회 실패: {e}", scene=scene) from e
            if s.status_code >= 400:
                raise AssetGenerationError("higgsfield", f"{label} 상태 조회 [{s.status_code}] {s.text[:300]}", scene=scene)
            body = s.json()
            status = body.get("status")
            if status == "completed":
                return body
            if status not in PENDING:
                raise AssetGenerationError("higgsfield", f"{label} 생성 실패 (status={status})", scene=scene)
            if self._clock() > deadline:
                raise AssetGenerationError("higgsfield", f"{label} 생성 타임아웃 ({self.poll_timeout:.0f}s)", scene=scene)
            log.debug("scene %s: %s %s...", scene, label, status)

    def _download(self, url: str, scene: Any) -> bytes:
        try:
            r = self.session.get(url, timeout=300)
        except requests.RequestException as e:
            raise AssetGenerationError("higgsfield", f"다운로드 실패: {e}", scene=scene) from e
        if r.status_code >= 400:
            raise AssetGenerationError("higgsfield", f"다운로드 [{r.status_code}] {url}", scene=scene)
        return r.content
