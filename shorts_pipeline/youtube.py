"""`Read Final Video` + `Upload a video`(YouTube) 노드 대체.

n8n-nodes-base YouTube 노드 소스 기준 resumable 업로드:
  POST https://www.googleapis.com/upload/youtube/v3/videos
       ?uploadType=resumable&part=snippet,status,recordingDetails&notifySubscribers=true
  → 응답 Location 으로 1MiB 씩 PUT (Content-Range, 진행 중 308, 완료 시 응답에 id)
워크플로우에 categoryId/privacyStatus 가 없어서 기본은 categoryId="" 이고 privacyStatus 는 보내지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

import requests

from .errors import PipelineError
from .http import make_session
from .logging_setup import get_logger

log = get_logger("youtube")

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK_SIZE = 1024 * 1024  # n8n UPLOAD_CHUNK_SIZE


class YouTubeClient(Protocol):
    def upload(self, path: Path, title: str) -> str: ...


def youtube_title(final_filename: str) -> str:
    """final_filename.replace(/\\.mp4$/i, '').replace(/_/g, ' ')"""
    return re.sub(r"\.mp4$", "", final_filename, flags=re.IGNORECASE).replace("_", " ")


def upload_payload(title: str, category_id: str = "", privacy_status: str | None = None) -> dict[str, Any]:
    status = {"privacyStatus": privacy_status} if privacy_status else {}
    return {"snippet": {"title": title, "categoryId": category_id}, "status": status, "recordingDetails": {}}


class YouTubeUploader:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, *,
                 category_id: str = "", privacy_status: str | None = None,
                 session: requests.Session | None = None, timeout: float = 300.0):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.category_id = category_id
        self.privacy_status = privacy_status
        self.session = session or make_session()
        self.timeout = timeout

    def _access_token(self) -> str:
        try:
            r = self.session.post(TOKEN_URL, data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            }, timeout=60)
        except requests.RequestException as e:
            raise PipelineError("youtube", f"토큰 발급 요청 실패: {e}") from e
        if r.status_code >= 400:
            raise PipelineError("youtube", f"토큰 발급 실패 [{r.status_code}] {r.text[:300]}")
        token = r.json().get("access_token")
        if not token:
            raise PipelineError("youtube", "토큰 응답에 access_token 이 없습니다")
        return token

    def upload(self, path: Path, title: str) -> str:
        size = Path(path).stat().st_size
        token = self._access_token()
        try:
            r = self.session.post(
                UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status,recordingDetails",
                        "notifySubscribers": "true"},
                json=upload_payload(title, self.category_id, self.privacy_status),
                headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(size),
                         "X-Upload-Content-Type": "video/mp4"},
                timeout=60,
            )
        except requests.RequestException as e:
            raise PipelineError("youtube", f"업로드 시작 실패: {e}") from e
        if r.status_code >= 400:
            raise PipelineError("youtube", f"업로드 시작 실패 [{r.status_code}] {r.text[:300]}")
        upload_url = r.headers.get("Location") or r.headers.get("location")
        if not upload_url:
            raise PipelineError("youtube", "업로드 응답에 Location 헤더가 없습니다")

        video_id = None
        offset = 0
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                next_offset = offset + len(chunk)
                try:
                    p = self.session.put(upload_url, data=chunk, allow_redirects=False, timeout=self.timeout,
                                         headers={"Content-Range": f"bytes {offset}-{next_offset - 1}/{size}"})
                except requests.RequestException as e:
                    raise PipelineError("youtube", f"업로드 실패 ({offset}/{size} bytes): {e}") from e
                if p.status_code != 308:
                    if p.status_code >= 400:
                        raise PipelineError("youtube", f"업로드 실패 [{p.status_code}] {p.text[:300]}")
                    video_id = p.json().get("id")
                offset = next_offset
        if not video_id:
            raise PipelineError("youtube", "업로드 완료 응답에 video id 가 없습니다")
        log.info("YouTube 업로드 완료: id=%s, title=%s", video_id, title)
        return video_id
