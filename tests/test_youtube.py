"""YouTube resumable 업로드 흐름 (n8n YouTube 노드 소스와 같은 요청을 보내는지)."""
import pytest

from shorts_pipeline.errors import PipelineError
from shorts_pipeline.youtube import CHUNK_SIZE, TOKEN_URL, UPLOAD_URL, YouTubeUploader


class Resp:
    def __init__(self, status=200, json_data=None, headers=None):
        self.status_code = status
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = str(json_data)

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, put_status=None, start=None, token=None):
        self.posts = []
        self.puts = []
        self.put_status = put_status
        self.start = start or Resp(200, headers={"Location": "https://upload/session"})
        self.token = token or Resp(200, {"access_token": "AT"})

    def post(self, url, **kw):
        self.posts.append((url, kw))
        return self.token if url == TOKEN_URL else self.start

    def put(self, url, data=None, headers=None, allow_redirects=True, timeout=None):
        self.puts.append((url, len(data), headers, allow_redirects))
        if self.put_status is not None:
            return Resp(self.put_status, {"error": "x"})
        total = int(headers["Content-Range"].rsplit("/", 1)[1])
        end = int(headers["Content-Range"].split("-")[1].split("/")[0])
        return Resp(200, {"id": "VID123"}) if end + 1 == total else Resp(308)


def uploader(session, **kw):
    return YouTubeUploader("cid", "sec", "rt", session=session, **kw)


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"x" * (CHUNK_SIZE * 2 + 10))
    return p


def test_resumable_upload(video):
    s = FakeSession()
    assert uploader(s).upload(video, "20261109 제목") == "VID123"
    (turl, tkw), (url, kw) = s.posts
    assert turl == TOKEN_URL and tkw["data"]["grant_type"] == "refresh_token" and tkw["data"]["refresh_token"] == "rt"
    assert url == UPLOAD_URL
    assert kw["params"] == {"uploadType": "resumable", "part": "snippet,status,recordingDetails",
                            "notifySubscribers": "true"}
    assert kw["json"] == {"snippet": {"title": "20261109 제목", "categoryId": ""}, "status": {}, "recordingDetails": {}}
    size = CHUNK_SIZE * 2 + 10
    assert kw["headers"] == {"Authorization": "Bearer AT", "X-Upload-Content-Length": str(size),
                             "X-Upload-Content-Type": "video/mp4"}
    assert [p[2]["Content-Range"] for p in s.puts] == [
        f"bytes 0-{CHUNK_SIZE - 1}/{size}",
        f"bytes {CHUNK_SIZE}-{CHUNK_SIZE * 2 - 1}/{size}",
        f"bytes {CHUNK_SIZE * 2}-{size - 1}/{size}",
    ]
    assert all(p[0] == "https://upload/session" and p[3] is False for p in s.puts)


def test_privacy_override(video):
    s = FakeSession()
    uploader(s, privacy_status="private").upload(video, "t")
    assert s.posts[1][1]["json"]["status"] == {"privacyStatus": "private"}


@pytest.mark.parametrize("session,match", [
    (FakeSession(token=Resp(400, {"error": "invalid_grant"})), "토큰 발급 실패"),
    (FakeSession(start=Resp(403, {"error": "quota"})), "업로드 시작 실패"),
    (FakeSession(start=Resp(200, headers={})), "Location"),
    (FakeSession(put_status=500), "업로드 실패"),
])
def test_errors(video, session, match):
    with pytest.raises(PipelineError, match=match):
        uploader(session).upload(video, "t")
