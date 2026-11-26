"""Higgsfield 제출 → 대기 → 상태 분기 → 다운로드/폴백 흐름 (n8n Switch 분기와 동일한지)."""
import pytest

from shorts_pipeline.errors import AssetGenerationError
from shorts_pipeline.higgsfield import HiggsfieldClient


class Resp:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code = status
        self._json = json_data
        self.content = content
        self.text = str(json_data)

    def json(self):
        return self._json


class FakeSession:
    """URL 별로 상태 응답 시퀀스를 돌려준다."""

    def __init__(self, statuses):
        self.statuses = {k: list(v) for k, v in statuses.items()}
        self.posts = []
        self.gets = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        kind = "video" if "kling" in url else f"image{len([p for p in self.posts if 'soul' in p[0]])}"
        return Resp(json_data={"request_id": kind, "status_url": f"https://status/{kind}"})

    def get(self, url, headers=None, timeout=None):
        self.gets.append((url, headers))
        if url.startswith("https://status/"):
            kind = url.rsplit("/", 1)[1]
            st = self.statuses[kind].pop(0)
            body = {"status": st}
            if st == "completed":
                body["images"] = [{"url": f"https://cdn/{kind}.png"}]
                body["video"] = {"url": f"https://cdn/{kind}.mp4"}
            return Resp(json_data=body)
        return Resp(content=f"BYTES:{url}".encode())


def client(session, sleeps=None, timeout=1800.0):
    t = [0.0]

    def sleep(s):
        (sleeps if sleeps is not None else []).append(s)
        t[0] += s

    return HiggsfieldClient("Key id:secret", poll_interval=5.0, poll_timeout=timeout,
                            session=session, sleep=sleep, clock=lambda: t[0])


VISUAL = {"scene_number": 2, "duration": 6.3, "image_prompt": "IMG", "loop_video_prompt": "VID"}


def test_image_queued_then_completed():
    s = FakeSession({"image1": ["queued", "in_progress", "completed"]})
    sleeps = []
    a = client(s, sleeps).generate({**VISUAL, "recommended_asset": "image"})
    assert a.asset_type == "image" and a.data == b"BYTES:https://cdn/image1.png"
    assert sleeps == [5.0, 5.0, 5.0]  # Wait 노드: 매 상태확인 전에 5초
    url, body, headers = s.posts[0]
    assert url.endswith("/higgsfield-ai/soul/standard") and body["prompt"] == "IMG"
    assert headers == {"Authorization": "Key id:secret", "Content-Type": "application/json"}
    assert s.gets[0][1] == {"Authorization": "Key id:secret"}
    assert s.gets[-1][1] is None  # 다운로드에는 인증 헤더 없음 (n8n 동일)


def test_video_completed():
    s = FakeSession({"video": ["in_progress", "completed"]})
    a = client(s).generate({**VISUAL, "recommended_asset": "loop_video"})
    assert a.asset_type == "video" and a.data == b"BYTES:https://cdn/video.mp4"
    assert s.posts[0][1]["duration"] == 7 and s.posts[0][1]["prompt"] == "VID"


@pytest.mark.parametrize("bad", ["failed", "nsfw", "canceled"])
def test_video_failure_raises_without_fallback(bad):
    # 이미지 폴백 브랜치가 삭제됨 → 추가 이미지 요청 없이 실패로 끝나고 파이프라인이 장면을 뺀다
    s = FakeSession({"video": ["queued", bad]})
    with pytest.raises(AssetGenerationError, match=f"status={bad}"):
        client(s).generate({**VISUAL, "recommended_asset": "loop_video"})
    assert len(s.posts) == 1


@pytest.mark.parametrize("bad", ["failed", "nsfw"])
def test_image_failure_raises(bad):
    # n8n 에서는 출력이 없어 장면이 빠짐 → 코드에선 예외로 알리고 파이프라인이 해당 장면을 건너뜀
    s = FakeSession({"image1": [bad]})
    with pytest.raises(AssetGenerationError):
        client(s).generate({**VISUAL, "recommended_asset": "image"})


def test_poll_timeout():
    s = FakeSession({"image1": ["queued"] * 100})
    with pytest.raises(AssetGenerationError, match="타임아웃"):
        client(s, timeout=20).generate({**VISUAL, "recommended_asset": "image"})
